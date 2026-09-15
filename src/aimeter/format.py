from datetime import datetime
from typing import Literal

from aimeter.constants import (
    CUMUL_SUM_LABEL,
    CUSUM_ARROWS,
    LABEL_IMPROVED,
    LABEL_NO_DATA,
    LABEL_STABLE,
    LABEL_WORSENED,
    MIN_THRESHOLD,
    SE_HIGH_THRESHOLD,
    SE_THRESHOLD_SCALE,
    STRONG_SIGNAL_MULTIPLIER,
)
from aimeter.models import ModelResult, Trend


def format_header() -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"AI Stupid Meter, {now}"


def format_delta(delta: float) -> str:
    if delta >= 0:
        return f"(Δ+{delta:.0f})"
    return f"(Δ{delta:.0f})"


def format_se(standard_error: float | None) -> str:
    if standard_error is None:
        return "SE —"
    se_text = f"SE ±{standard_error:.1f}"
    if standard_error > SE_HIGH_THRESHOLD:
        return f"{se_text} (SE↕)"
    return se_text


def format_cusum(trend: Trend | None) -> str:
    arrow = CUSUM_ARROWS.get(trend or "", "?")
    return f"{CUMUL_SUM_LABEL}:{arrow}"


def format_model_line(result: ModelResult) -> str:
    score = f"{result.current_score:.0f}" if result.current_score is not None else "—"
    delta_text = format_delta(result.delta) if result.delta is not None else "(Δ—)"
    marker = " [!!]" if result.strong_signal else ""

    avg = f"{result.period_avg:.0f}" if result.period_avg is not None else "—"
    period_max = f"{result.period_max:.0f}" if result.period_max is not None else "—"
    se = format_se(result.standard_error)
    cusum = format_cusum(result.trend)

    parts = [
        f"{result.name}:  {score} {delta_text}{marker}",
        f"| {result.label}",
        f"| 7d avg {avg}",
        f"| 7d max {period_max}",
        f"| {se}",
        f"| {cusum}",
    ]

    if result.is_stale:
        hours = result.stale_hours
        stale_text = f"stale {hours}h" if hours is not None else "stale"
        parts.append(f"| {stale_text}")

    return "  ".join(parts)


def format_diagnostic(
    detail: str,
    *,
    name: str | None = None,
    level: Literal["INFO", "WARN", "ERROR"] = "WARN",
) -> str:
    context = f"{name}: " if name is not None else ""
    return f"[{level}] {context}{detail}"


def format_missing_model(name: str) -> str:
    return format_diagnostic(
        "not found in API — model may have been renamed, check the watched list",
        name=name,
    )


def format_summary(results: list[ModelResult]) -> str:
    found = [r for r in results if r.found]
    improved = sum(1 for r in found if r.label == LABEL_IMPROVED)
    worsened = sum(1 for r in found if r.label == LABEL_WORSENED)
    stable = sum(1 for r in found if r.label == LABEL_STABLE)
    no_data = sum(1 for r in found if r.label == LABEL_NO_DATA)

    parts = [
        f"Summary: {improved} improved",
        f"{worsened} worsened",
        f"{stable} unchanged",
    ]
    if no_data:
        parts.append(f"{no_data} no data")
    return ", ".join(parts)


_CUSUM_DESC = {
    "up": "the model is improving over the last ~48h",
    "down": "the model is deteriorating over the last ~48h",
    "stable": "no short-term trend (~48h)",
}

_INDENT = "    "


def _format_threshold_comparison(
    value: float,
    threshold: float,
    relation: Literal["<", "≥", "≤"],
    *,
    value_label: str = "Δ",
    threshold_label: str = "threshold",
) -> str:
    """Show a decided comparison without hiding differences through rounding."""
    value_text, threshold_text = f"{value:.0f}", f"{abs(threshold):.1f}"
    if threshold < 0:
        threshold_label = f"−{threshold_label}"
    if value_text == f"{threshold:.0f}":
        value_text = f"{value:.1f}"
        if value != threshold and value_text == f"{threshold:.1f}":
            position = "above" if relation == "≥" else "below"
            return (
                f"{value_label}(≈{value_text}), {threshold_label}(≈{threshold_text}): "
                f"{position} the threshold before rounding"
            )
    return f"{value_label}({value_text}) {relation} {threshold_label}({threshold_text})"


def format_verbose_v1(result: ModelResult) -> list[str]:
    """Δ, threshold, and [!!] logic — -v."""
    if not result.found:
        return []

    cusum_line = (
        f"{_INDENT}→ {format_cusum(result.trend)}  "
        f"{_CUSUM_DESC.get(result.trend or '', 'no trend information')}"
    )
    assessment = result.strong_signal_assessment
    if (
        result.delta is None
        or result.threshold is None
        or result.current_score is None
        or result.period_avg is None
        or assessment is None
    ):
        return [
            f"{_INDENT}→ not enough data to compute Δ",
            cusum_line,
        ]

    lines: list[str] = []

    score = f"{result.current_score:.0f}"
    avg = f"{result.period_avg:.0f}"
    sign = "+" if result.delta >= 0 else ""
    rounded = any(
        value != round(value)
        for value in (result.current_score, result.period_avg, result.delta)
    )
    equality = "≈" if rounded else "="
    lines.append(
        f"{_INDENT}→ Δ {equality} score({score}) − 7d avg({avg})"
        f" {equality} {sign}{result.delta:.0f}"
    )

    se = result.standard_error or 0.0
    se_scaled = se * SE_THRESHOLD_SCALE
    min_t = f"{MIN_THRESHOLD:.0f}"
    scale = f"{SE_THRESHOLD_SCALE}"
    lines.append(
        f"{_INDENT}→ threshold = max({min_t}, SE×{scale})"
        f" = max({min_t}, {se:.1f}×{scale})"
        f" = max({min_t}, {se_scaled:.1f}) = {result.threshold:.1f}"
    )

    delta_abs = abs(result.delta)
    if result.label == LABEL_IMPROVED:
        rationale = _format_threshold_comparison(result.delta, result.threshold, "≥")
    elif result.label == LABEL_WORSENED:
        rationale = _format_threshold_comparison(result.delta, -result.threshold, "≤")
    else:
        rationale = _format_threshold_comparison(
            delta_abs, result.threshold, "<", value_label="|Δ|"
        )
    lines.append(f"{_INDENT}→ label: {rationale}  →  {result.label}")

    if not assessment.applicable:
        lines.append(
            f"{_INDENT}→ [!!]: not applicable (label ≠ {LABEL_WORSENED})"
        )
    else:
        mult = f"{STRONG_SIGNAL_MULTIPLIER:.0f}"
        cond_drop = _format_threshold_comparison(
            delta_abs, assessment.large_drop_threshold,
            "≥" if assessment.large_drop else "<",
            value_label="|Δ|", threshold_label=f"{mult}×threshold",
        )
        if assessment.large_drop:
            cond_drop += " ✓"
        cond_cusum = (
            f"{CUMUL_SUM_LABEL}:↓ ✓" if assessment.cusum_down else f"{CUMUL_SUM_LABEL}:↓? no"
        )
        verdict = "yes → [!!]" if assessment.is_strong else "no → no [!!]"
        lines.append(f"{_INDENT}→ [!!]: {cond_drop}   {cond_cusum}   →  {verdict}")

    lines.append(cusum_line)

    return lines


def format_verbose_v2(result: ModelResult) -> list[str]:
    """COMBINED 7d statistics (computed locally) + API metadata — -vv."""
    if not result.found:
        return []

    parts: list[str] = []

    if result.data_points is not None:
        parts.append(f"COMBINED 7d points: {result.data_points}")
    if result.confidence_lower is not None and result.confidence_upper is not None:
        cl = f"{result.confidence_lower:.0f}"
        cu = f"{result.confidence_upper:.0f}"
        parts.append(f"CI (COMBINED 7d): [{cl}, {cu}]")
    if result.stability is not None:
        parts.append(f"stability (API): {result.stability:.0f}/100")

    if not parts:
        return [f"{_INDENT}→ no extra statistics"]
    return [f"{_INDENT}→ {' │ '.join(parts)}"]


def format_legend() -> str:
    separator = "─" * 78
    se_max = f"{SE_HIGH_THRESHOLD:.0f}"
    items = (
        f"[!!] strong signal: large Δ or {CUMUL_SUM_LABEL}:↓",
        f"SE↕ high measurement error (SE>{se_max}), score is less reliable",
        f"{CUMUL_SUM_LABEL}:↑↓→ trend over the last ~48h",
        f"{CUMUL_SUM_LABEL}:? no trend information",
    )
    return "\n".join((separator, *items))
