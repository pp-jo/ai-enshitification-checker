import math
import statistics
from dataclasses import dataclass
from typing import Any

from aimeter.constants import (
    CUMUL_SUM_LABEL,
    CUSUM_ARROWS,
    LABEL_IMPROVED,
    LABEL_NO_DATA,
    LABEL_STABLE,
    LABEL_WORSENED,
    MIN_THRESHOLD,
    SE_THRESHOLD_SCALE,
    STRONG_SIGNAL_MULTIPLIER,
)


@dataclass
class PeriodStats:
    period_avg: float
    standard_error: float | None
    data_points: int
    confidence_lower: float | None = None
    confidence_upper: float | None = None


def extract_history_scores(history_payload: dict[str, Any]) -> list[float]:
    data = history_payload.get("data")
    if not isinstance(data, list):
        return []

    scores: list[float] = []
    for point in data:
        if not isinstance(point, dict):
            continue
        score = point.get("score")
        if isinstance(score, (int, float)):
            scores.append(float(score))
    return scores


def compute_period_stats(scores: list[float]) -> PeriodStats | None:
    if not scores:
        return None

    n = len(scores)
    period_avg = statistics.mean(scores)
    if n < 2:
        return PeriodStats(period_avg=period_avg, standard_error=None, data_points=n)

    stdev = statistics.stdev(scores)
    standard_error = stdev / math.sqrt(n)
    ci_half = 1.96 * standard_error
    return PeriodStats(
        period_avg=period_avg,
        standard_error=standard_error,
        data_points=n,
        confidence_lower=period_avg - ci_half,
        confidence_upper=period_avg + ci_half,
    )


@dataclass
class ModelResult:
    name: str
    current_score: float | None
    period_avg: float | None
    standard_error: float | None
    trend: str | None
    is_stale: bool
    stale_hours: int | None
    delta: float | None
    threshold: float | None
    label: str
    strong_signal: bool
    found: bool = True
    data_points: int | None = None
    stability: float | None = None
    confidence_lower: float | None = None
    confidence_upper: float | None = None


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
    label: str, delta: float, threshold: float, trend: str | None
) -> bool:
    if label != LABEL_WORSENED:
        return False
    if abs(delta) >= STRONG_SIGNAL_MULTIPLIER * threshold:
        return True
    if trend == "down":
        return True
    return False


def format_cusum(trend: str | None) -> str:
    arrow = CUSUM_ARROWS.get(trend or "", "→")
    return f"{CUMUL_SUM_LABEL}:{arrow}"


def parse_stale_hours(stale_duration: Any) -> int | None:
    if stale_duration is None:
        return None
    if isinstance(stale_duration, bool):
        return None
    if isinstance(stale_duration, (int, float)):
        return int(stale_duration)
    if isinstance(stale_duration, str):
        text = stale_duration.strip().lower()
        if text.endswith("h"):
            try:
                return int(float(text[:-1]))
            except ValueError:
                return None
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def analyze_model(
    name: str,
    entry: dict[str, Any] | None,
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
            strong_signal=False,
            found=False,
        )

    current_score = entry.get("currentScore")
    trend = entry.get("trend")
    is_stale = bool(entry.get("isStale", False))
    stale_hours = parse_stale_hours(entry.get("staleDuration"))
    stability = entry.get("stability")

    if period_stats is not None:
        period_avg = period_stats.period_avg
        standard_error = period_stats.standard_error
        data_points = period_stats.data_points
        confidence_lower = period_stats.confidence_lower
        confidence_upper = period_stats.confidence_upper
    else:
        period_avg = None
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
            strong_signal=False,
            data_points=data_points,
            stability=stability,
            confidence_lower=confidence_lower,
            confidence_upper=confidence_upper,
        )

    delta = current_score - period_avg
    threshold = compute_threshold(standard_error)
    label = compute_label(delta, threshold)
    strong_signal = compute_strong_signal(label, delta, threshold, trend)

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
        strong_signal=strong_signal,
        data_points=data_points,
        stability=stability,
        confidence_lower=confidence_lower,
        confidence_upper=confidence_upper,
    )
