import math
from collections.abc import Callable
from dataclasses import replace

import pytest

from aimeter.constants import (
    LABEL_IMPROVED,
    LABEL_NO_DATA,
    LABEL_STABLE,
    LABEL_WORSENED,
)
from aimeter.models import (
    AnalysisError,
    LeaderboardEntry,
    ModelResult,
    PeriodStats,
    Trend,
    analyze_model,
    compute_period_stats,
)
from aimeter.parsing import HistoryData, parse_leaderboard

ENTRY = LeaderboardEntry(
    name="example",
    model_id="1",
    current_score=40.0,
    trend=None,
    is_stale=None,
    stale_hours=None,
    stability=None,
)


def test_statistics_have_expected_mean_maximum_error_and_interval() -> None:
    stats = compute_period_stats([40.0, 50.0, 60.0])
    assert stats is not None
    expected_error = 10 / math.sqrt(3)
    assert stats.period_avg == 50.0
    assert stats.period_max == 60.0
    assert stats.data_points == 3
    assert stats.standard_error == pytest.approx(expected_error)
    assert stats.confidence_lower == pytest.approx(50 - 1.96 * expected_error)
    assert stats.confidence_upper == pytest.approx(50 + 1.96 * expected_error)


def test_empty_history_has_no_statistics() -> None:
    assert compute_period_stats([]) is None


def test_single_point_has_no_estimated_uncertainty() -> None:
    stats = compute_period_stats([50.0])
    assert stats is not None
    assert stats.period_avg == stats.period_max == 50
    assert stats.data_points == 1
    assert stats.standard_error is None
    assert stats.confidence_lower is stats.confidence_upper is None
    result = analyze_model("example", ENTRY, period_stats=stats)
    assert result.threshold == 5
    assert result.label == LABEL_WORSENED


@pytest.mark.parametrize("score", [0.0, 50.0, 1e308])
def test_constant_scores_have_zero_uncertainty(score: float) -> None:
    stats = compute_period_stats([score, score, score])
    assert stats is not None
    assert stats.standard_error == 0
    assert stats.period_avg == stats.period_max == score
    assert stats.confidence_lower == stats.confidence_upper == score


@pytest.mark.parametrize(
    "scores",
    [
        [float("nan")],
        [float("inf")],
        [50.0, float("nan")],
        [-1e308, 1e308],
        [0.0, 1.7e308],
    ],
)
def test_unsafe_statistics_raise_controlled_error(scores: list[float]) -> None:
    with pytest.raises(AnalysisError, match="finite history statistics"):
        compute_period_stats(scores)


@pytest.mark.parametrize("score,average", [(1e308, -1e308), (-1e308, 1e308)])
def test_delta_overflow_preserves_scores_but_produces_no_assessment(
    score: float, average: float
) -> None:
    stats = compute_period_stats([average, average])
    result = analyze_model(
        "example", replace(ENTRY, current_score=score), period_stats=stats
    )
    assert result.current_score == score
    assert result.period_avg == average
    assert result.delta is None
    assert result.threshold is None
    assert result.label == LABEL_NO_DATA
    assert not result.strong_signal
    assert result.strong_signal_assessment is None
    assert result.analysis_error is not None


def test_missing_score_keeps_history_without_a_false_assessment() -> None:
    result = analyze_model(
        "example",
        replace(ENTRY, current_score=None),
        period_stats=compute_period_stats([50.0, 60.0]),
    )
    assert result.current_score is None
    assert result.period_avg == 55
    assert result.delta is None
    assert result.label == LABEL_NO_DATA
    assert result.analysis_error is None
    assert not result.strong_signal
    assert result.strong_signal_assessment is None


def test_missing_trend_does_not_block_a_large_drop_signal() -> None:
    result = analyze_model(
        "example", ENTRY, period_stats=compute_period_stats([60.0, 60.0])
    )
    assert result.trend is None
    assert result.delta == -20
    assert result.label == LABEL_WORSENED
    assert result.strong_signal


def test_analyze_model_labels(
    analyze_from_fixture: Callable[[str], ModelResult],
) -> None:
    gpt55 = analyze_from_fixture("gpt-5.5")
    assert gpt55.delta == -5
    assert gpt55.label == LABEL_STABLE

    gpt54 = analyze_from_fixture("gpt-5.4")
    assert gpt54.delta == -5
    assert gpt54.label == LABEL_WORSENED
    assert not gpt54.strong_signal

    sonnet = analyze_from_fixture("claude-sonnet-4-6")
    assert sonnet.label == LABEL_WORSENED
    assert sonnet.strong_signal

    kimi = analyze_from_fixture("kimi-k2.7-code")
    assert kimi.label == LABEL_IMPROVED


def test_compute_period_stats() -> None:
    stats = compute_period_stats([12, 12, 12, 12, 12, 12, 92, 92, 92, 92, 92, 92])
    assert stats is not None
    assert stats.period_avg == 52
    assert stats.period_max == 92
    assert stats.data_points == 12
    assert stats.standard_error is not None
    assert stats.standard_error > 10


def test_analyze_model_missing_trend(
    mock_fetch_history: Callable[[str], HistoryData],
) -> None:
    entry = {
        "id": "188",
        "name": "kimi-k2.7-code",
        "currentScore": 66,
        "isStale": False,
    }
    history = mock_fetch_history("188")
    period_stats = compute_period_stats(history.scores)
    parsed = parse_leaderboard({"success": True, "data": [entry]})
    result = analyze_model(
        "kimi-k2.7-code", parsed.by_name["kimi-k2.7-code"], period_stats=period_stats
    )
    assert result.label == LABEL_IMPROVED
    assert result.trend is None


def test_analyze_model_no_history() -> None:
    entry = {
        "id": "256",
        "name": "gpt-5.5",
        "currentScore": 47,
        "trend": "stable",
        "isStale": False,
        "stability": 29,
    }
    parsed = parse_leaderboard({"success": True, "data": [entry]})
    result = analyze_model("gpt-5.5", parsed.by_name["gpt-5.5"], period_stats=None)
    assert result.label == LABEL_NO_DATA
    assert result.delta is None
    assert result.found is True
    assert result.strong_signal_assessment is None
    assert not result.strong_signal


def test_analyze_model_not_found() -> None:
    result = analyze_model("missing-model", None)
    assert not result.found
    assert result.strong_signal_assessment is None
    assert not result.strong_signal


@pytest.mark.parametrize(
    "delta,label",
    [
        (math.nextafter(-5.0, -math.inf), LABEL_WORSENED),
        (-5.0, LABEL_WORSENED),
        (math.nextafter(-5.0, math.inf), LABEL_STABLE),
        (math.nextafter(5.0, -math.inf), LABEL_STABLE),
        (5.0, LABEL_IMPROVED),
        (math.nextafter(5.0, math.inf), LABEL_IMPROVED),
    ],
)
def test_labels_use_unrounded_delta_at_both_boundaries(
    delta: float, label: str
) -> None:
    result = analyze_model(
        "example",
        replace(ENTRY, current_score=delta, trend="down"),
        period_stats=compute_period_stats([0.0]),
    )
    assert result.delta == delta
    assert result.label == label
    assert result.strong_signal == (label == LABEL_WORSENED)


@pytest.mark.parametrize(
    "delta,strong",
    [
        (math.nextafter(-10.0, math.inf), False),
        (-10.0, True),
        (math.nextafter(-10.0, -math.inf), True),
    ],
)
def test_large_drop_uses_unrounded_delta_at_its_boundary(
    delta: float, strong: bool
) -> None:
    result = analyze_model(
        "example",
        replace(ENTRY, current_score=delta),
        period_stats=compute_period_stats([0.0]),
    )
    assert result.label == LABEL_WORSENED
    assert result.strong_signal_assessment is not None
    assert result.strong_signal_assessment.large_drop is strong
    assert result.strong_signal is strong


@pytest.mark.parametrize("se,threshold", [(None, 5.0), (20.0, 14.0)])
@pytest.mark.parametrize(
    "delta_factor,trend,applicable,large_drop,cusum_down,strong",
    [
        (-1.2, "stable", True, False, False, False),
        (-2.0, "stable", True, True, False, True),
        (-1.2, "down", True, False, True, True),
        (-2.0, "down", True, True, True, True),
        (2.0, "down", False, False, True, False),
        (0.0, "down", False, False, True, False),
        (-0.9, "down", False, False, True, False),
        (-2.0, "up", True, True, False, True),
        (-2.0, None, True, True, False, True),
        (-1.2, None, True, False, False, False),
    ],
)
def test_strong_signal_retains_applicability_threshold_and_reasons(
    se: float | None,
    threshold: float,
    delta_factor: float,
    trend: Trend | None,
    applicable: bool,
    large_drop: bool,
    cusum_down: bool,
    strong: bool,
) -> None:
    result = analyze_model(
        "example",
        replace(ENTRY, current_score=delta_factor * threshold, trend=trend),
        period_stats=PeriodStats(
            period_avg=0,
            period_max=0,
            standard_error=se,
            data_points=2,
        ),
    )
    assessment = result.strong_signal_assessment
    assert assessment is not None
    assert result.threshold == threshold
    assert assessment.applicable is applicable
    assert assessment.large_drop_threshold == 2 * threshold
    assert assessment.large_drop is large_drop
    assert assessment.cusum_down is cusum_down
    assert assessment.is_strong is strong
    assert result.strong_signal is strong
