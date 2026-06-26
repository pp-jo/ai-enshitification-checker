import argparse
import sys

from aimeter.api import ApiError, fetch_scores, index_by_name
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
from aimeter.models import ModelResult, analyze_model


def run(watched_models: list[str] | None = None, verbosity: int = 0) -> int:
    models = WATCHED_MODELS if watched_models is None else watched_models
    lines: list[str] = [format_header(), ""]
    results: list[ModelResult] = []

    try:
        payload = fetch_scores()
    except ApiError as exc:
        print(exc.message)
        return 1

    data = payload.get("data")
    if not isinstance(data, list):
        print("[ERROR] API response missing data list")
        return 1

    if not data:
        print("[WARN] API returned empty model list")
        return 0

    by_name = index_by_name(data)

    for name in models:
        entry = by_name.get(name)
        result = analyze_model(name, entry)
        results.append(result)

        if not result.found:
            lines.append(format_missing_model(name))
        else:
            lines.append(format_model_line(result))
            if verbosity >= 1:
                lines.extend(format_verbose_v1(result))
            if verbosity >= 2:
                lines.extend(format_verbose_v2(result))

    lines.append("")
    lines.append(format_summary(results))
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
            "  aimeter -vv      — + surowe dane z API (dataPoints, CI)\n"
            "  aimeter -vvv...  — odpowiednik -vv"
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
    sys.exit(run(verbosity=args.verbosity))
