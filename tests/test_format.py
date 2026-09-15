from collections.abc import Callable
from dataclasses import replace

import pytest

from aimeter.constants import (
    LABEL_IMPROVED,
    LABEL_NO_DATA,
    LABEL_STABLE,
    LABEL_WORSENED,
)
from aimeter.format import format_model_line, format_summary, format_verbose_v1
from aimeter.models import ModelResult, analyze_model, compute_period_stats
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
    parsed = parse_leaderboard({
        "success": True,
        "data": [{"name": "example", "currentScore": 50, **entry}],
    })
    result = analyze_model(
        "example",
        parsed.by_name["example"],
        period_stats=compute_period_stats([50.0, 50.0]) if with_history else None,
    )
    assert len(parsed.warnings) == warning_count
    assert f"Cumul. sum:{arrow}" in format_model_line(result)
    verbose = "\n".join(format_verbose_v1(result))
    assert f"Cumul. sum:{arrow}" in verbose
    assert ("brak informacji o trendzie" in verbose) == (arrow == "?")


@pytest.mark.parametrize("missing_field", ["current_score", "period_avg"])
def test_verbose_calculations_check_required_scores(missing_field: str) -> None:
    entry = parse_leaderboard({
        "success": True, "data": [{"name": "example", "currentScore": 50}],
    }).by_name["example"]
    result = analyze_model(
        "example", entry, period_stats=compute_period_stats([50.0, 50.0])
    )
    result = replace(result, **{missing_field: None})
    assert "brak wystarczających danych" in "\n".join(format_verbose_v1(result))


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
        strong_signal=False,
    )


@pytest.mark.parametrize(
    "improved,worsened,stable,no_data,expected",
    [
        (
            1, 0, 2, 0,
            "Podsumowanie: 1 poprawił się, 0 pogorszyło się, 2 bez zmian",
        ),
        (
            2, 1, 0, 0,
            "Podsumowanie: 2 poprawiły się, 1 pogorszył się, 0 bez zmian",
        ),
        (
            0, 0, 1, 2,
            "Podsumowanie: 0 poprawiło się, 0 pogorszyło się, 1 bez zmian, 2 braki danych",
        ),
    ],
)
def test_format_summary_pluralization(
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
        "claude-sonnet-4-6:  46 (Δ-12) [!!]  | pogorszył się  | 7d avg 58  "
        "| 7d max 58  "
        "| SE ±0.0  | Cumul. sum:↓"
    )


def test_format_model_line_stale_and_high_se(
    analyze_from_fixture: Callable[[str], ModelResult],
) -> None:
    result = analyze_from_fixture("claude-opus-4-8")

    line = format_model_line(result)

    assert (
        "claude-opus-4-8:  57 (Δ+2)  | bez zmian  | 7d avg 55  | 7d max 100  "
        in line
    )
    assert "SE↕" in line
    assert "Cumul. sum:↓  | stale 6h" in line


def test_format_model_line_high_se_only(
    analyze_from_fixture: Callable[[str], ModelResult],
) -> None:
    result = analyze_from_fixture("gpt-5.5")

    line = format_model_line(result)

    assert "gpt-5.5:  47 (Δ-5)  | bez zmian  | 7d avg 52  | 7d max 92  " in line
    assert "SE↕" in line
    assert "Cumul. sum:→" in line
