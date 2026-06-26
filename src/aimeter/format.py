from datetime import datetime

from aimeter.constants import (
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
from aimeter.models import ModelResult, format_cusum


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


def format_model_line(result: ModelResult) -> str:
    score = f"{result.current_score:.0f}" if result.current_score is not None else "—"
    delta_text = format_delta(result.delta) if result.delta is not None else "(Δ—)"
    marker = " [!!]" if result.strong_signal else ""

    avg = f"{result.period_avg:.0f}" if result.period_avg is not None else "—"
    se = format_se(result.standard_error)
    cusum = format_cusum(result.trend)

    parts = [
        f"{result.name}:  {score} {delta_text}{marker}",
        f"| {result.label}",
        f"| 7d avg {avg}",
        f"| {se}",
        f"| {cusum}",
    ]

    if result.is_stale:
        hours = result.stale_hours
        stale_text = f"stale {hours}h" if hours is not None else "stale"
        parts.append(f"| {stale_text}")

    return "  ".join(parts)


def format_missing_model(name: str) -> str:
    return (
        f"[WARN] {name}: not found in API — "
        "model may have been renamed, check the watched list"
    )


def _polish_plural(count: int, singular: str, few: str, many: str) -> str:
    """Polska pluralizacja: 1 / 2-4 / 5+ (z wyjątkiem 12-14, które idą do `many`)."""
    if count == 1:
        return f"1 {singular}"
    last_digit = count % 10
    last_two = count % 100
    if 2 <= last_digit <= 4 and not 12 <= last_two <= 14:
        return f"{count} {few}"
    return f"{count} {many}"


def _plural_improved(count: int) -> str:
    return _polish_plural(count, "poprawił się", "poprawiły się", "poprawiło się")


def _plural_worsened(count: int) -> str:
    return _polish_plural(count, "pogorszył się", "pogorszyły się", "pogorszyło się")


def _plural_no_data(count: int) -> str:
    return _polish_plural(count, "brak danych", "braki danych", "braków danych")


def format_summary(results: list[ModelResult]) -> str:
    found = [r for r in results if r.found]
    improved = sum(1 for r in found if r.label == LABEL_IMPROVED)
    worsened = sum(1 for r in found if r.label == LABEL_WORSENED)
    stable = sum(1 for r in found if r.label == LABEL_STABLE)
    no_data = sum(1 for r in found if r.label == LABEL_NO_DATA)

    parts = [
        f"Podsumowanie: {_plural_improved(improved)}",
        _plural_worsened(worsened),
        f"{stable} bez zmian",
    ]
    if no_data:
        parts.append(_plural_no_data(no_data))
    return ", ".join(parts)


_CUSUM_DESC = {
    "up": "model poprawia się w ostatnich ~48h",
    "down": "model pogarsza się w ostatnich ~48h",
    "stable": "brak trendu krótkoterminowego (~48h)",
}

_INDENT = "    "


def format_verbose_v1(result: ModelResult) -> list[str]:
    """Obliczenia Δ, progu i logiki [!!] — poziom -v."""
    if not result.found:
        return []

    if result.delta is None or result.threshold is None:
        return [f"{_INDENT}→ brak wystarczających danych do obliczenia Δ"]

    lines: list[str] = []

    score = f"{result.current_score:.0f}"
    avg = f"{result.period_avg:.0f}"
    sign = "+" if result.delta >= 0 else ""
    lines.append(
        f"{_INDENT}→ Δ = wynik({score}) − 7d śr.({avg}) = {sign}{result.delta:.0f}"
    )

    se = result.standard_error or 0.0
    se_scaled = se * SE_THRESHOLD_SCALE
    min_t = f"{MIN_THRESHOLD:.0f}"
    scale = f"{SE_THRESHOLD_SCALE}"
    lines.append(
        f"{_INDENT}→ próg = max({min_t}, SE×{scale})"
        f" = max({min_t}, {se:.1f}×{scale})"
        f" = max({min_t}, {se_scaled:.1f}) = {result.threshold:.1f}"
    )

    delta_abs = abs(result.delta)
    if result.label == LABEL_IMPROVED:
        rationale = f"Δ({sign}{result.delta:.0f}) ≥ +próg({result.threshold:.1f})"
    elif result.label == LABEL_WORSENED:
        rationale = f"Δ({result.delta:.0f}) ≤ −próg({result.threshold:.1f})"
    else:
        rationale = f"|Δ|({delta_abs:.0f}) < próg({result.threshold:.1f})"
    lines.append(f"{_INDENT}→ ocena: {rationale}  →  {result.label}")

    if result.label != LABEL_WORSENED:
        lines.append(f"{_INDENT}→ [!!]: nie dotyczy (ocena ≠ pogorszył się)")
    else:
        threshold_x = STRONG_SIGNAL_MULTIPLIER * result.threshold
        mult = f"{STRONG_SIGNAL_MULTIPLIER:.0f}"
        big_drop = delta_abs >= threshold_x
        cusum_down = result.trend == "down"
        cond_drop = (
            f"|Δ|({delta_abs:.0f}) ≥ {mult}×próg({threshold_x:.1f}) ✓"
            if big_drop
            else f"|Δ|({delta_abs:.0f}) < {mult}×próg({threshold_x:.1f})"
        )
        cond_cusum = "CUSUM:↓ ✓" if cusum_down else "CUSUM:↓? nie"
        verdict = "tak → [!!]" if result.strong_signal else "nie → brak [!!]"
        lines.append(f"{_INDENT}→ [!!]: {cond_drop}   {cond_cusum}   →  {verdict}")

    arrow = CUSUM_ARROWS.get(result.trend or "", "→")
    desc = _CUSUM_DESC.get(result.trend or "", "nieznany trend")
    lines.append(f"{_INDENT}→ CUSUM:{arrow}  {desc}")

    return lines


def format_verbose_v2(result: ModelResult) -> list[str]:
    """Statystyki COMBINED 7d (liczone lokalnie) + metadane z API — poziom -vv."""
    if not result.found:
        return []

    parts: list[str] = []

    if result.data_points is not None:
        parts.append(f"punkty COMBINED 7d: {result.data_points}")
    if result.confidence_lower is not None and result.confidence_upper is not None:
        cl = f"{result.confidence_lower:.0f}"
        cu = f"{result.confidence_upper:.0f}"
        parts.append(f"CI (COMBINED 7d): [{cl}, {cu}]")
    if result.stability is not None:
        parts.append(f"stabilność (API): {result.stability:.0f}/100")

    if not parts:
        return [f"{_INDENT}→ brak dodatkowych statystyk"]
    return [f"{_INDENT}→ {' │ '.join(parts)}"]


def format_legend() -> str:
    separator = "─" * 78
    se_max = f"{SE_HIGH_THRESHOLD:.0f}"
    text = (
        "[!!] silny sygnał: duży Δ lub CUSUM:↓"
        "   │   "
        f"SE↕ błąd pomiaru wysoki (SE>{se_max}), wynik mniej wiarygodny"
        "   │   "
        "CUSUM:↑↓→ trend ostatnich ~48h"
    )
    return f"{separator}\n{text}"
