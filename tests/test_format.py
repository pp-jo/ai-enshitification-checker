from collections.abc import Callable
from dataclasses import replace

import pytest

from aimeter.constants import (
    CUMUL_SUM_LABEL,
    LABEL_IMPROVED,
    LABEL_NO_DATA,
    LABEL_STABLE,
    LABEL_WORSENED,
    SE_HIGH_THRESHOLD,
)
from aimeter.format import (
    format_calculations,
    format_legend,
    format_model_line,
    format_summary,
)
from aimeter.models import ModelResult, Trend, analyze_model, compute_period_stats
from aimeter.parsing import parse_leaderboard


@pytest.mark.parametrize(
    "entry,arrow,warning_count",
    [
        ({}, "?", 0),
        ({"trend": None}, "?", 0),
        ({"trend": "sideways"}, "?", 1),
        ({"trend": "stable"}, "→", 0),
        ({"trend": "up"}, "↑", 0),
        ({"trend": "down"}, "↓", 0),
    ],
)
@pytest.mark.parametrize("with_history", [False, True])
def test_trend_presentation_distinguishes_unknown_from_stable(
    entry: dict[str, object], arrow: str, warning_count: int, with_history: bool
) -> None:
    parsed = parse_leaderboard(
        {
            "success": True,
            "data": [{"name": "example", "currentScore": 50, **entry}],
        }
    )
    result = analyze_model(
        "example",
        parsed.by_name["example"],
        period_stats=compute_period_stats([50.0, 50.0]) if with_history else None,
    )
    assert len(parsed.warnings) == warning_count
    assert f"Cumul. sum:{arrow}" in format_model_line(result)
    verbose = "\n".join(format_calculations(result))
    assert f"Cumul. sum:{arrow}" in verbose
    assert ("no trend information" in verbose) == (arrow == "?")


@pytest.mark.parametrize("missing_field", ["current_score", "period_avg"])
def test_verbose_calculations_check_required_scores(missing_field: str) -> None:
    entry = parse_leaderboard(
        {
            "success": True,
            "data": [{"name": "example", "currentScore": 50}],
        }
    ).by_name["example"]
    result = analyze_model(
        "example", entry, period_stats=compute_period_stats([50.0, 50.0])
    )
    result = replace(result, **{missing_field: None})
    assert "not enough data" in "\n".join(format_calculations(result))


def _result_with_label(label: str) -> ModelResult:
    return ModelResult(
        name="test",
        current_score=50,
        period_avg=50,
        standard_error=5,
        trend="stable",
        is_stale=False,
        stale_hours=None,
        delta=0,
        threshold=5,
        label=label,
    )


@pytest.mark.parametrize(
    "improved,worsened,stable,no_data,expected",
    [
        (
            1,
            0,
            2,
            0,
            "Summary: 1 improved, 0 worsened, 2 unchanged",
        ),
        (
            2,
            1,
            0,
            0,
            "Summary: 2 improved, 1 worsened, 0 unchanged",
        ),
        (
            0,
            0,
            1,
            2,
            "Summary: 0 improved, 0 worsened, 1 unchanged, 2 no data",
        ),
    ],
)
def test_format_summary_counts(
    improved: int, worsened: int, stable: int, no_data: int, expected: str
) -> None:
    results = (
        [_result_with_label(LABEL_IMPROVED)] * improved
        + [_result_with_label(LABEL_WORSENED)] * worsened
        + [_result_with_label(LABEL_STABLE)] * stable
        + [_result_with_label(LABEL_NO_DATA)] * no_data
    )
    assert format_summary(results) == expected


def test_format_model_line_strong_signal(
    analyze_from_fixture: Callable[[str], ModelResult],
) -> None:
    result = analyze_from_fixture("claude-sonnet-4-6")

    line = format_model_line(result)

    assert line == (
        "claude-sonnet-4-6:  46 (Δ-12) [!!]  | worsened  | 7d avg 58  "
        "| 7d max 58  "
        "| SE ±0.0  | Cumul. sum:↓"
    )


def test_format_model_line_stale_and_high_se(
    analyze_from_fixture: Callable[[str], ModelResult],
) -> None:
    result = analyze_from_fixture("claude-opus-4-8")

    line = format_model_line(result)

    assert (
        "claude-opus-4-8:  57 (Δ+2)  | unchanged  | 7d avg 55  | 7d max 100  " in line
    )
    assert "SE↕" in line
    assert "Cumul. sum:↓  | stale 6h" in line


def test_format_model_line_high_se_only(
    analyze_from_fixture: Callable[[str], ModelResult],
) -> None:
    result = analyze_from_fixture("gpt-5.5")

    line = format_model_line(result)

    assert "gpt-5.5:  47 (Δ-5)  | unchanged  | 7d avg 52  | 7d max 92  " in line
    assert "SE↕" in line
    assert "Cumul. sum:→" in line


def _signal_result(delta: float, trend: Trend | None = "stable") -> ModelResult:
    entry = parse_leaderboard(
        {
            "success": True,
            "data": [{"name": "example", "currentScore": delta, "trend": trend}],
        }
    ).by_name["example"]
    return analyze_model("example", entry, period_stats=compute_period_stats([0.0]))


@pytest.mark.parametrize(
    "delta,trend,strong,reason",
    [
        (
            -6,
            "stable",
            False,
            "|Δ|(6) < 2×threshold(10.0)   Cumul. sum:↓? no   →  no → no [!!]",
        ),
        (
            -10,
            "stable",
            True,
            "|Δ|(10.0) ≥ 2×threshold(10.0) ✓   Cumul. sum:↓? no   →  yes → [!!]",
        ),
        (
            -6,
            "down",
            True,
            "|Δ|(6) < 2×threshold(10.0)   Cumul. sum:↓ ✓   →  yes → [!!]",
        ),
        (
            -10,
            "down",
            True,
            "|Δ|(10.0) ≥ 2×threshold(10.0) ✓   Cumul. sum:↓ ✓   →  yes → [!!]",
        ),
        (10, "down", False, "not applicable (label ≠ worsened)"),
        (0, "down", False, "not applicable (label ≠ worsened)"),
    ],
)
def test_signal_marker_and_explanation_share_the_same_reasons(
    delta: float,
    trend: Trend,
    strong: bool,
    reason: str,
) -> None:
    result = _signal_result(delta, trend)
    assert (" [!!]" in format_model_line(result)) is strong
    assert f"    → [!!]: {reason}" in format_calculations(result)


@pytest.mark.parametrize(
    "delta,label,comparison",
    [
        (4.9, LABEL_STABLE, "|Δ|(4.9) < threshold(5.0)"),
        (
            4.99,
            LABEL_STABLE,
            "|Δ|(≈5.0), threshold(≈5.0): below the threshold before rounding",
        ),
        (5, LABEL_IMPROVED, "Δ(5.0) ≥ threshold(5.0)"),
        (
            5.01,
            LABEL_IMPROVED,
            "Δ(≈5.0), threshold(≈5.0): above the threshold before rounding",
        ),
        (5.1, LABEL_IMPROVED, "Δ(5.1) ≥ threshold(5.0)"),
        (-4.9, LABEL_STABLE, "|Δ|(4.9) < threshold(5.0)"),
        (
            -4.99,
            LABEL_STABLE,
            "|Δ|(≈5.0), threshold(≈5.0): below the threshold before rounding",
        ),
        (-5, LABEL_WORSENED, "Δ(-5.0) ≤ −threshold(5.0)"),
        (
            -5.01,
            LABEL_WORSENED,
            "Δ(≈-5.0), −threshold(≈5.0): below the threshold before rounding",
        ),
        (-5.1, LABEL_WORSENED, "Δ(-5.1) ≤ −threshold(5.0)"),
    ],
)
def test_verbose_label_boundary_is_not_hidden_by_rounding(
    delta: float,
    label: str,
    comparison: str,
) -> None:
    result = _signal_result(delta)
    assert result.label == label
    verbose = format_calculations(result)
    assert f"    → label: {comparison}  →  {label}" in verbose
    if delta in (-5, 5):
        assert verbose[0].startswith("    → Δ = score(")
        assert "≈" not in verbose[0]
    else:
        assert verbose[0].startswith("    → Δ ≈ score(")
        assert verbose[0].endswith("≈ +5" if delta > 0 else "≈ -5")


@pytest.mark.parametrize(
    "delta,strong,comparison",
    [
        (-9.9, False, "|Δ|(9.9) < 2×threshold(10.0)"),
        (
            -9.99,
            False,
            "|Δ|(≈10.0), 2×threshold(≈10.0): below the threshold before rounding",
        ),
        (-10, True, "|Δ|(10.0) ≥ 2×threshold(10.0) ✓"),
        (
            -10.01,
            True,
            "|Δ|(≈10.0), 2×threshold(≈10.0): above the threshold before rounding ✓",
        ),
        (-10.1, True, "|Δ|(10.1) ≥ 2×threshold(10.0) ✓"),
    ],
)
def test_verbose_large_drop_boundary_matches_marker_and_verdict(
    delta: float,
    strong: bool,
    comparison: str,
) -> None:
    result = _signal_result(delta)
    assert (" [!!]" in format_model_line(result)) is strong
    verdict = "yes → [!!]" if strong else "no → no [!!]"
    assert (
        f"    → [!!]: {comparison}   Cumul. sum:↓? no   →  {verdict}"
        in format_calculations(result)
    )


@pytest.mark.parametrize("trend_fields", [{}, {"trend": None}, {"trend": "sideways"}])
@pytest.mark.parametrize("delta,strong", [(-6, False), (-10, True)])
def test_unknown_trend_does_not_confirm_or_block_the_drop_reason(
    trend_fields: dict[str, object],
    delta: float,
    strong: bool,
) -> None:
    entry = parse_leaderboard(
        {
            "success": True,
            "data": [{"name": "example", "currentScore": delta, **trend_fields}],
        }
    ).by_name["example"]
    result = analyze_model("example", entry, period_stats=compute_period_stats([0.0]))
    assert (" [!!]" in format_model_line(result)) is strong
    verbose = "\n".join(format_calculations(result))
    assert "Cumul. sum:↓? no" in verbose
    assert "Cumul. sum:↓ ✓" not in verbose
    assert "Cumul. sum:?" in verbose


def test_legend_fits_separator_width() -> None:
    legend = format_legend()
    lines = legend.splitlines()
    assert lines[0] == "─" * 78
    assert all(len(line) <= 78 for line in lines)
    assert lines[1:] == [
        f"[!!] strong signal: large Δ or {CUMUL_SUM_LABEL}:↓",
        f"SE↕ high measurement error (SE>{SE_HIGH_THRESHOLD:.0f}), score is less reliable",
        f"{CUMUL_SUM_LABEL}:↑↓→ trend over the last ~48h",
        f"{CUMUL_SUM_LABEL}:? no trend information",
    ]
