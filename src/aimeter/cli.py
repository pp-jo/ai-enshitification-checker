import argparse
import sys
from dataclasses import dataclass

from aimeter.api import ApiError, fetch_history, fetch_scores
from aimeter.config import ConfigError, load_watched_models
from aimeter.constants import WATCHED_MODELS
from aimeter.format import (
    format_header,
    format_legend,
    format_missing_model,
    format_model_line,
    format_summary,
    format_verbose_v1,
    format_verbose_v2,
)
from aimeter.models import (
    AnalysisError,
    ModelResult,
    PeriodStats,
    analyze_model,
    compute_period_stats,
)
from aimeter.parsing import LeaderboardData


@dataclass
class HistoryOutcome:
    stats: PeriodStats | None = None
    error: str | None = None
    discarded_points: int = 0


@dataclass
class ModelOutcome:
    result: ModelResult
    history: HistoryOutcome


def load_model_history(model_id: str | None) -> HistoryOutcome:
    """Retain parsing and numeric issues for the later diagnostics layer."""
    if model_id is None:
        return HistoryOutcome()
    try:
        history = fetch_history(model_id)
    except ApiError as exc:
        return HistoryOutcome(error=str(exc))

    try:
        stats = compute_period_stats(history.scores)
    except AnalysisError as exc:
        return HistoryOutcome(
            error=str(exc), discarded_points=history.discarded_points
        )
    return HistoryOutcome(stats=stats, discarded_points=history.discarded_points)


def collect_model_outcomes(
    leaderboard: LeaderboardData, watched_models: list[str]
) -> list[ModelOutcome]:
    """Keep each assessment and its history diagnostics together for rendering."""
    outcomes: list[ModelOutcome] = []
    for name in watched_models:
        entry = leaderboard.by_name.get(name)
        history = load_model_history(entry.model_id if entry is not None else None)
        result = analyze_model(name, entry, period_stats=history.stats)
        outcomes.append(ModelOutcome(result=result, history=history))
    return outcomes


def run(watched_models: list[str] | None = None, verbosity: int = 0) -> int:
    models = WATCHED_MODELS.copy() if watched_models is None else watched_models
    lines: list[str] = [format_header(), ""]

    try:
        leaderboard = fetch_scores()
    except ApiError as exc:
        print(exc.message)
        return 1

    if not leaderboard.by_name:
        print("[WARN] API returned empty model list")
        return 0

    outcomes = collect_model_outcomes(leaderboard, models)
    for outcome in outcomes:
        result = outcome.result
        if not result.found:
            lines.append(format_missing_model(result.name))
        else:
            lines.append(format_model_line(result))
            if verbosity >= 1:
                lines.extend(format_verbose_v1(result))
            if verbosity >= 2:
                lines.extend(format_verbose_v2(result))

    lines.append("")
    lines.append(format_summary([outcome.result for outcome in outcomes]))
    lines.append(format_legend())
    print("\n".join(lines))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Stupid Meter — sprawdź trendy modeli AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Przykłady:\n"
            "  aimeter          — standardowy output\n"
            "  aimeter -v       — + obliczenia Δ, próg, logika [!!]\n"
            "  aimeter -vv      — + statystyki COMBINED 7d i stabilność (API)\n"
            "  aimeter -vvv...  — odpowiednik -vv\n"
            "  aimeter --config ./config.toml — własna lista modeli"
        ),
    )
    parser.add_argument(
        "--config",
        metavar="PLIK",
        help=(
            "Plik TOML z listą modeli (domyślnie: "
            "$XDG_CONFIG_HOME/aimeter/config.toml lub ~/.config/aimeter/config.toml)"
        ),
    )
    parser.add_argument(
        "-v",
        action="count",
        default=0,
        dest="verbosity",
        help="Więcej szczegółów (można powtórzyć: -v, -vv)",
    )
    args = parser.parse_args()
    try:
        watched_models = load_watched_models(args.config)
    except ConfigError as exc:
        parser.error(str(exc))
    sys.exit(run(watched_models=watched_models, verbosity=args.verbosity))
