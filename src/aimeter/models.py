from dataclasses import dataclass
from typing import Any

from aimeter.constants import (
    CUSUM_ARROWS,
    LABEL_IMPROVED,
    LABEL_STABLE,
    LABEL_WORSENED,
    MIN_THRESHOLD,
    SE_THRESHOLD_SCALE,
    STRONG_SIGNAL_MULTIPLIER,
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
    return f"CUSUM:{arrow}"


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


def analyze_model(name: str, entry: dict[str, Any] | None) -> ModelResult:
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
    period_avg = entry.get("periodAvg")
    standard_error = entry.get("standardError")
    trend = entry.get("trend")
    is_stale = bool(entry.get("isStale", False))
    stale_hours = parse_stale_hours(entry.get("staleDuration"))
    data_points = entry.get("dataPoints")
    stability = entry.get("stability")
    confidence_lower = entry.get("confidenceLower")
    confidence_upper = entry.get("confidenceUpper")

    if current_score is None or period_avg is None:
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
            label=LABEL_STABLE,
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
