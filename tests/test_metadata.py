import json
from dataclasses import replace

import pytest

from aimeter.cli import run
from aimeter.constants import API_URL, HISTORY_URL
from aimeter.format import format_extra_stats, format_model_line
from aimeter.models import (
    SuiteCoverage,
    analyze_model,
    compute_period_stats,
    get_suite_coverage,
)
from aimeter.parsing import parse_leaderboard


@pytest.mark.parametrize(
    "suites,expected",
    [
        (("hourly", "deep", "tooling"), "complete"),
        (("tooling", "hourly", "deep", "hourly"), "complete"),
        (("hourly",), "partial"),
        ((), "partial"),
        (None, "unknown"),
        (("future-suite",), "unknown"),
        (("hourly", "deep", "tooling", "future-suite"), "unknown"),
    ],
)
def test_completeness_requires_known_suites(
    suites: tuple[str, ...] | None, expected: SuiteCoverage
) -> None:
    assert get_suite_coverage(suites) == expected


@pytest.mark.parametrize(
    "suites,expected",
    [
        ([" hourly ", "deep", "hourly", "tooling"], ("hourly", "deep", "tooling")),
        (["hourly"], ("hourly",)),
        ([], ()),
        (["future-suite"], ("future-suite",)),
    ],
)
def test_metadata_is_normalized_and_reaches_assessment(
    suites: list[str], expected: tuple[str, ...]
) -> None:
    leaderboard = parse_leaderboard(
        {
            "success": True,
            "data": [
                {
                    "name": "model",
                    "currentScore": 40,
                    "suites": suites,
                    "coverage": "  5/7 tasks  ",
                }
            ],
        }
    )
    entry = leaderboard.by_name["model"]
    assert entry.suites == expected
    assert entry.coverage == "5/7 tasks"
    assert leaderboard.warnings == []
    stats = compute_period_stats([50.0, 50.0])
    result = analyze_model("model", entry, period_stats=stats)
    assert result.suites == expected
    assert result.coverage == entry.coverage
    assert result.delta == -10
    assert result.label == "worsened"
    assert result.strong_signal
    baseline = analyze_model(
        "model", replace(entry, suites=None, coverage=None), period_stats=stats
    )
    assert result.strong_signal_assessment == baseline.strong_signal_assessment


@pytest.mark.parametrize("null_fields", [False, True])
def test_absent_metadata_remains_unknown_and_optional(null_fields: bool) -> None:
    entry: dict[str, object] = {"name": "model"}
    if null_fields:
        entry.update(suites=None, coverage=None)
    leaderboard = parse_leaderboard({"success": True, "data": [entry]})
    result = analyze_model("model", leaderboard.by_name["model"])
    assert result.suites is result.coverage is None
    assert get_suite_coverage(result.suites) == "unknown"
    assert leaderboard.warnings == []
    assert "complete" not in format_model_line(result)
    assert format_extra_stats(result) == ["    → no extra statistics"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("coverage", ""),
        ("coverage", "  "),
        ("coverage", False),
        ("coverage", 42),
        ("coverage", []),
        ("coverage", {}),
        ("suites", "hourly"),
        ("suites", {}),
        ("suites", True),
        ("suites", ["hourly", 1]),
        ("suites", [""]),
        ("suites", ["  "]),
    ],
)
def test_invalid_metadata_warns_without_losing_valid_scores(
    field: str, value: object
) -> None:
    leaderboard = parse_leaderboard(
        {"success": True, "data": [{"name": "model", "currentScore": 40, field: value}]}
    )
    entry = leaderboard.by_name["model"]
    assert getattr(entry, field) is None
    assert entry.current_score == 40
    assert leaderboard.warnings == [f"model: invalid {field}; treated as missing"]


@pytest.mark.parametrize("verbosity", [0, 1, 2])
@pytest.mark.parametrize(
    "suites,coverage,marker,details,warning",
    [
        (
            ["hourly"],
            "1 of 3 suites (no deep, tooling)",
            "partial: 1/3 suites",
            "suites (API): hourly (partial)",
            True,
        ),
        ([], None, "partial: 0/3 suites", "suites (API): none (partial)", True),
        (
            ["hourly", "deep", "tooling"],
            "5/7 tasks",
            "coverage: 5/7 tasks",
            "suites (API): hourly, deep, tooling (complete)",
            False,
        ),
        (
            ["hourly", "new-suite"],
            None,
            "suites: unknown",
            "suites (API): hourly, new-suite (unknown)",
            False,
        ),
        (
            ["hourly", "deep", "tooling", "new-suite"],
            "4 of 4 suites",
            "suites: unknown",
            "suites (API): hourly, deep, tooling, new-suite (unknown)",
            False,
        ),
    ],
)
def test_report_shows_completeness_and_warns_once_per_model(
    suites: list[str],
    coverage: str | None,
    marker: str,
    details: str,
    warning: bool,
    verbosity: int,
    http_responses: dict[str, bytes | Exception],
    capsys: pytest.CaptureFixture[str],
) -> None:
    http_responses[API_URL] = json.dumps(
        {
            "success": True,
            "data": [
                {
                    "name": "model",
                    "id": "1",
                    "currentScore": 40,
                    "isStale": False,
                    "suites": suites,
                    "coverage": coverage,
                },
                {"name": "healthy", "id": "2", "currentScore": 55},
            ],
        }
    ).encode()
    for model_id in ("1", "2"):
        http_responses[HISTORY_URL.format(model_id=model_id)] = (
            b'{"success":true,"data":[{"score":50},{"score":50}]}'
        )
    assert run(["model", "healthy", "model"], verbosity=verbosity) == 0
    output = capsys.readouterr()
    rows = [line for line in output.out.splitlines() if line.startswith("model:")]
    assert len(rows) == 2
    assert all("40 (Δ-10) [!!]  | worsened" in row and marker in row for row in rows)
    assert "healthy:  55 (Δ+5)  | improved" in output.out
    if coverage is not None:
        assert all((f"coverage: {coverage}" in row) == (not warning) for row in rows)
        assert (f"coverage (API): {coverage}" in output.out) == (verbosity == 2)
        if warning:
            assert output.out.count(coverage) == (2 if verbosity == 2 else 0)
    assert (details in output.out) == (verbosity == 2)
    if warning:
        assert output.err == (
            "[WARN] model: incomplete benchmark suites; changes in the contributing "
            "suites may affect Δ\n"
        )
    elif "new-suite" in suites:
        assert output.err == (
            "[WARN] model: unknown benchmark suites: new-suite; "
            "completeness cannot be determined; aimeter may need an update\n"
        )
    else:
        assert output.err == ""


def test_unknown_suite_warning_lists_only_unrecognized_names(
    http_responses: dict[str, bytes | Exception], capsys: pytest.CaptureFixture[str]
) -> None:
    http_responses[API_URL] = json.dumps(
        {
            "success": True,
            "data": [
                {
                    "name": "model",
                    "currentScore": 40,
                    "suites": [
                        "hourly",
                        "new-a",
                        "deep",
                        " new-b ",
                        "new-a",
                        "tooling",
                    ],
                },
                {"name": "missing", "currentScore": 40},
            ],
        }
    ).encode()
    assert run(["model", "missing", "model"]) == 0
    output = capsys.readouterr()
    assert "| suites: unknown" in output.out
    assert output.err == (
        "[WARN] model: unknown benchmark suites: new-a, new-b; "
        "completeness cannot be determined; aimeter may need an update\n"
    )
