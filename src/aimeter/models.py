import math
import statistics
from dataclasses import dataclass
from typing import Literal, TypeAlias

from aimeter.constants import (
    LABEL_IMPROVED,
    LABEL_NO_DATA,
    LABEL_STABLE,
    LABEL_WORSENED,
    MIN_THRESHOLD,
    SE_THRESHOLD_SCALE,
    STRONG_SIGNAL_MULTIPLIER,
)

Trend: TypeAlias = Literal["up", "down", "stable"]


@dataclass(frozen=True)
class LeaderboardEntry:
    name: str
    model_id: str | None
    current_score: float | None
    trend: Trend | None
    is_stale: bool | None
    stale_hours: int | None
    stability: float | None


class AnalysisError(ValueError):
    """Finite history statistics could not be computed."""


@dataclass
class PeriodStats:
    period_avg: float
    period_max: float
    standard_error: float | None
    data_points: int
    confidence_lower: float | None = None
    confidence_upper: float | None = None


def compute_period_stats(scores: list[float]) -> PeriodStats | None:
    """Compute statistics from validated scores, rejecting numeric overflow."""
    if not scores:
        return None

    try:
        return _compute_period_stats(scores)
    except (OverflowError, ValueError) as exc:
        raise AnalysisError("Cannot compute finite history statistics") from exc


def _compute_period_stats(scores: list[float]) -> PeriodStats:
    if not all(math.isfinite(score) for score in scores):
        raise ValueError("History contains non-finite scores")
    n = len(scores)
    period_avg = statistics.mean(scores)
    period_max = max(scores)
    if not math.isfinite(period_avg):
        raise ValueError("History average is non-finite")
    if n < 2:
        return PeriodStats(
            period_avg=period_avg,
            period_max=period_max,
            standard_error=None,
            data_points=n,
        )

    stdev = statistics.stdev(scores)
    standard_error = stdev / math.sqrt(n)
    ci_half = 1.96 * standard_error
    confidence_lower = period_avg - ci_half
    confidence_upper = period_avg + ci_half
    if not all(
        math.isfinite(value)
        for value in (standard_error, confidence_lower, confidence_upper)
    ):
        raise ValueError("History uncertainty is non-finite")
    return PeriodStats(
        period_avg=period_avg,
        period_max=period_max,
        standard_error=standard_error,
        data_points=n,
        confidence_lower=confidence_lower,
        confidence_upper=confidence_upper,
    )


@dataclass(frozen=True)
class StrongSignalAssessment:
    applicable: bool
    large_drop_threshold: float
    large_drop: bool
    cusum_down: bool

    @property
    def is_strong(self) -> bool:
        return self.applicable and (self.large_drop or self.cusum_down)


@dataclass
class ModelResult:
    name: str
    current_score: float | None
    period_avg: float | None
    standard_error: float | None
    trend: Trend | None
    is_stale: bool | None
    stale_hours: int | None
    delta: float | None
    threshold: float | None
    label: str
    strong_signal_assessment: StrongSignalAssessment | None = None
    found: bool = True
    data_points: int | None = None
    period_max: float | None = None
    stability: float | None = None
    confidence_lower: float | None = None
    confidence_upper: float | None = None
    analysis_error: str | None = None

    @property
    def strong_signal(self) -> bool:
        assessment = self.strong_signal_assessment
        return assessment is not None and assessment.is_strong


def compute_threshold(standard_error: float | None) -> float:
    se = standard_error or 0
    return max(MIN_THRESHOLD, se * SE_THRESHOLD_SCALE)


def compute_label(delta: float, threshold: float) -> str:
    if delta >= threshold:
        return LABEL_IMPROVED
    if delta <= -threshold:
        return LABEL_WORSENED
    return LABEL_STABLE


def compute_strong_signal(
    label: str, delta: float, threshold: float, trend: Trend | None
) -> StrongSignalAssessment:
    large_drop_threshold = STRONG_SIGNAL_MULTIPLIER * threshold
    return StrongSignalAssessment(
        applicable=label == LABEL_WORSENED,
        large_drop_threshold=large_drop_threshold,
        large_drop=delta <= -large_drop_threshold,
        cusum_down=trend == "down",
    )


def analyze_model(
    name: str,
    entry: LeaderboardEntry | None,
    *,
    period_stats: PeriodStats | None = None,
) -> ModelResult:
    if entry is None:
        return ModelResult(
            name=name,
            current_score=None,
            period_avg=None,
            standard_error=None,
            trend=None,
            is_stale=False,
            stale_hours=None,
            delta=None,
            threshold=None,
            label=LABEL_STABLE,
            found=False,
        )

    current_score = entry.current_score
    trend = entry.trend
    is_stale = entry.is_stale
    stale_hours = entry.stale_hours
    stability = entry.stability

    if period_stats is not None:
        period_avg: float | None = period_stats.period_avg
        period_max: float | None = period_stats.period_max
        standard_error = period_stats.standard_error
        data_points: int | None = period_stats.data_points
        confidence_lower = period_stats.confidence_lower
        confidence_upper = period_stats.confidence_upper
    else:
        period_avg = None
        period_max = None
        standard_error = None
        data_points = None
        confidence_lower = None
        confidence_upper = None

    if period_avg is None or current_score is None:
        return ModelResult(
            name=name,
            current_score=current_score,
            period_avg=period_avg,
            standard_error=standard_error,
            trend=trend,
            is_stale=is_stale,
            stale_hours=stale_hours,
            delta=None,
            threshold=None,
            label=LABEL_NO_DATA,
            data_points=data_points,
            period_max=period_max,
            stability=stability,
            confidence_lower=confidence_lower,
            confidence_upper=confidence_upper,
        )

    delta: float | None = current_score - period_avg
    threshold: float | None = compute_threshold(standard_error)
    analysis_error = None
    if not all(
        math.isfinite(value)
        for value in (delta, threshold, STRONG_SIGNAL_MULTIPLIER * threshold)
    ):
        delta = None
        threshold = None
        label = LABEL_NO_DATA
        strong_signal_assessment = None
        analysis_error = "Cannot compute a finite model assessment"
    else:
        label = compute_label(delta, threshold)
        strong_signal_assessment = compute_strong_signal(label, delta, threshold, trend)

    return ModelResult(
        name=name,
        current_score=current_score,
        period_avg=period_avg,
        standard_error=standard_error,
        trend=trend,
        is_stale=is_stale,
        stale_hours=stale_hours,
        delta=delta,
        threshold=threshold,
        label=label,
        strong_signal_assessment=strong_signal_assessment,
        data_points=data_points,
        period_max=period_max,
        stability=stability,
        confidence_lower=confidence_lower,
        confidence_upper=confidence_upper,
        analysis_error=analysis_error,
    )
