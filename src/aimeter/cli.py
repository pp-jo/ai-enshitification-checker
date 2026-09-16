import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal, TypeAlias

from aimeter.api import ApiError, fetch_history, fetch_scores
from aimeter.config import ConfigError, load_watched_models
from aimeter.constants import DEFAULT_WATCHED_MODELS, HISTORY_MAX_WORKERS
from aimeter.format import (
    format_calculations,
    format_diagnostic,
    format_extra_stats,
    format_header,
    format_legend,
    format_missing_model,
    format_model_line,
    format_summary,
)
from aimeter.models import (
    AnalysisError,
    ModelResult,
    PeriodStats,
    analyze_model,
    compute_period_stats,
)
from aimeter.parsing import LeaderboardData

HistoryStatus: TypeAlias = Literal[
    "ok", "empty", "missing_id", "request_error", "invalid_data", "numeric_error"
]


@dataclass
class HistoryOutcome:
    status: HistoryStatus
    stats: PeriodStats | None = None
    detail: str | None = None
    discarded_points: int = 0


@dataclass
class ModelOutcome:
    result: ModelResult
    history: HistoryOutcome


def load_model_history(model_id: str | None) -> HistoryOutcome:
    """Classify history availability and retain diagnostics without printing."""
    if model_id is None:
        return HistoryOutcome(status="missing_id", detail="missing history identifier")
    try:
        history = fetch_history(model_id)
    except ApiError as exc:
        if exc.kind == "invalid_response":
            return HistoryOutcome(
                status="invalid_data", detail=f"invalid history data ({exc})"
            )
        reason = str(exc)
        if exc.kind == "http" and exc.http_status is not None:
            reason = f"HTTP {exc.http_status}"
        return HistoryOutcome(
            status="request_error", detail=f"failed to fetch history ({reason})"
        )

    if not history.scores:
        if history.discarded_points:
            return HistoryOutcome(
                status="invalid_data",
                detail="history contains no valid points",
                discarded_points=history.discarded_points,
            )
        return HistoryOutcome(status="empty", detail="history is empty")

    try:
        stats = compute_period_stats(history.scores)
    except AnalysisError as exc:
        return HistoryOutcome(
            status="numeric_error",
            detail=f"history statistics calculation error ({exc})",
            discarded_points=history.discarded_points,
        )
    return HistoryOutcome(
        status="ok", stats=stats, discarded_points=history.discarded_points
    )


def collect_model_outcomes(
    leaderboard: LeaderboardData, watched_models: list[str]
) -> list[ModelOutcome]:
    """Fetch unique histories concurrently, then assess in configuration order."""
    entries = [leaderboard.by_name.get(name) for name in watched_models]
    model_ids = list(
        dict.fromkeys(
            entry.model_id
            for entry in entries
            if entry is not None and entry.model_id is not None
        )
    )
    histories: dict[str, HistoryOutcome] = {}
    if model_ids:
        if sys.stderr.isatty():
            print(
                format_diagnostic("Fetching model histories…", level="INFO"),
                file=sys.stderr,
                flush=True,
            )
        executor = ThreadPoolExecutor(
            max_workers=min(HISTORY_MAX_WORKERS, len(model_ids))
        )
        try:
            # Submit every history before waiting, so network waits overlap.
            futures = {
                model_id: executor.submit(load_model_history, model_id)
                for model_id in model_ids
            }
            histories = {
                model_id: future.result() for model_id, future in futures.items()
            }
        finally:
            # Also cancel queued work on interruption; running HTTP must finish.
            executor.shutdown(wait=True, cancel_futures=True)

    outcomes: list[ModelOutcome] = []
    for name, entry in zip(watched_models, entries, strict=True):
        history = (
            histories[entry.model_id]
            if entry is not None and entry.model_id is not None
            else load_model_history(None)
        )
        result = analyze_model(name, entry, period_stats=history.stats)
        outcomes.append(ModelOutcome(result=result, history=history))
    return outcomes


def collect_model_diagnostics(outcome: ModelOutcome, verbosity: int) -> list[str]:
    """Prepare each issue once, including expected missing data in verbose mode."""
    result, history = outcome.result, outcome.history
    if not result.found:
        return []

    diagnostics: list[str] = []
    if verbosity >= 1 and result.current_score is None:
        diagnostics.append(
            format_diagnostic("missing current score", name=result.name, level="INFO")
        )

    history_warning = history.status in (
        "request_error",
        "invalid_data",
        "numeric_error",
    )
    detail = history.detail
    if history.discarded_points:
        discarded = f"discarded history points: {history.discarded_points}"
        detail = f"{detail}; {discarded}" if detail else discarded
        history_warning = True
    if detail and (history_warning or verbosity >= 1):
        diagnostics.append(
            format_diagnostic(
                detail, name=result.name, level="WARN" if history_warning else "INFO"
            )
        )

    if result.analysis_error is not None:
        diagnostics.append(
            format_diagnostic(
                f"assessment calculation error ({result.analysis_error})",
                name=result.name,
            )
        )
    return diagnostics


def run(watched_models: list[str] | None = None, verbosity: int = 0) -> int:
    models = DEFAULT_WATCHED_MODELS.copy() if watched_models is None else watched_models
    lines: list[str] = [format_header(), ""]
    outcomes: list[ModelOutcome] = []
    diagnostics: list[str] = []

    if models:
        try:
            leaderboard = fetch_scores()
        except ApiError as exc:
            print(format_diagnostic(str(exc), level="ERROR"), file=sys.stderr)
            return 1

        if not leaderboard.by_name:
            print(format_diagnostic("API returned empty model list"), file=sys.stderr)
            return 0

        outcomes = collect_model_outcomes(leaderboard, models)
        diagnostics = [format_diagnostic(warning) for warning in leaderboard.warnings]

    for outcome in outcomes:
        result = outcome.result
        diagnostics.extend(collect_model_diagnostics(outcome, verbosity))
        if not result.found:
            lines.append(format_missing_model(result.name))
        else:
            lines.append(format_model_line(result))
            if verbosity >= 1:
                lines.extend(format_calculations(result))
            if verbosity >= 2:
                lines.extend(format_extra_stats(result))

    lines.append("")
    lines.append(format_summary([outcome.result for outcome in outcomes]))
    lines.append(format_legend())
    for diagnostic in dict.fromkeys(diagnostics):
        print(diagnostic, file=sys.stderr)
    print("\n".join(lines))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Stupid Meter — check AI model trends",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  aimeter          — standard output\n"
            "  aimeter -v       — + Δ calculations, threshold, [!!] logic\n"
            "  aimeter -vv      — + COMBINED 7d statistics and stability (API)\n"
            "  aimeter -vvv...  — same as -vv\n"
            "  aimeter --config ./config.toml — custom model list"
        ),
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        help=(
            "TOML file with the model list (default: "
            "$XDG_CONFIG_HOME/aimeter/config.toml or ~/.config/aimeter/config.toml)"
        ),
    )
    parser.add_argument(
        "-v",
        action="count",
        default=0,
        dest="verbosity",
        help="More detail (repeatable: -v, -vv)",
    )
    args = parser.parse_args()
    try:
        watched_models = load_watched_models(args.config)
    except ConfigError as exc:
        parser.error(str(exc))
    sys.exit(run(watched_models=watched_models, verbosity=args.verbosity))
