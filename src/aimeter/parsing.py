import math
from dataclasses import dataclass

from aimeter.models import LeaderboardEntry, Trend


class PayloadError(ValueError):
    """The decoded response does not have the required structure."""


@dataclass
class LeaderboardData:
    by_name: dict[str, LeaderboardEntry]
    warnings: list[str]


@dataclass
class HistoryData:
    scores: list[float]
    discarded_points: int


def parse_finite_number(value: object) -> float | None:
    """Accept finite JSON numbers, excluding booleans and numeric strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def parse_stale_hours(value: object) -> int | None:
    number: float | None
    if isinstance(value, str):
        text = value.strip().lower().removesuffix("h")
        try:
            number = float(text)
        except (ValueError, OverflowError):
            return None
    else:
        number = parse_finite_number(value)
    if number is None or not math.isfinite(number) or number < 0:
        return None
    return int(number)


def _parse_model_id(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        try:
            return str(value)
        except ValueError:
            return None
    if isinstance(value, str):
        return value.strip() or None
    return None


def _parse_trend(value: object) -> Trend | None:
    if value == "up":
        return "up"
    if value == "down":
        return "down"
    if value == "stable":
        return "stable"
    return None


def _require_data(payload: object) -> list[object]:
    if not isinstance(payload, dict):
        raise PayloadError("API response is not a JSON object")
    if payload.get("success") is not True:
        raise PayloadError("API returned success=false or invalid success value")
    data = payload.get("data")
    if not isinstance(data, list):
        raise PayloadError("API response missing data list")
    return data


def _parse_entry(
    name: str, entry: dict[str, object], warnings: list[str]
) -> LeaderboardEntry:
    model_id = _parse_model_id(entry.get("id"))
    current_score = parse_finite_number(entry.get("currentScore"))
    trend = _parse_trend(entry.get("trend"))
    stale_value = entry.get("isStale")
    is_stale = stale_value if isinstance(stale_value, bool) else None
    stale_hours = parse_stale_hours(entry.get("staleDuration"))
    stability = parse_finite_number(entry.get("stability"))

    for field, parsed in (
        ("id", model_id),
        ("currentScore", current_score),
        ("trend", trend),
        ("isStale", is_stale),
        ("staleDuration", stale_hours),
        ("stability", stability),
    ):
        if entry.get(field) is not None and parsed is None:
            warnings.append(f"{name}: invalid {field}; treated as missing")

    return LeaderboardEntry(
        name=name,
        model_id=model_id,
        current_score=current_score,
        trend=trend,
        is_stale=is_stale,
        stale_hours=stale_hours,
        stability=stability,
    )


def parse_leaderboard(payload: object) -> LeaderboardData:
    data = _require_data(payload)
    entries_by_name: dict[str, dict[str, object]] = {}
    warnings: list[str] = []
    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            warnings.append(f"Leaderboard entry {index}: not an object; skipped")
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            warnings.append(f"Leaderboard entry {index}: invalid name; skipped")
            continue
        name = name.strip()
        if name in entries_by_name:
            warnings.append(f"{name}: duplicate name; using the last entry")
        entries_by_name[name] = entry

    if data and not entries_by_name:
        raise PayloadError("API response contains no entries with valid model names")
    # Field warnings describe only the entry selected for each model.
    by_name = {
        name: _parse_entry(name, entry, warnings)
        for name, entry in entries_by_name.items()
    }
    return LeaderboardData(by_name=by_name, warnings=warnings)


def parse_history(payload: object) -> HistoryData:
    data = _require_data(payload)
    scores: list[float] = []
    for point in data:
        if not isinstance(point, dict):
            continue
        score = parse_finite_number(point.get("score"))
        if score is not None:
            scores.append(score)
    return HistoryData(scores=scores, discarded_points=len(data) - len(scores))
