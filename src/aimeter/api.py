import json
import urllib.error
import urllib.parse
import urllib.request
from typing import NoReturn

from aimeter.constants import API_URL, HISTORY_URL, REQUEST_TIMEOUT
from aimeter.parsing import (
    HistoryData,
    LeaderboardData,
    PayloadError,
    parse_history,
    parse_leaderboard,
)


class ApiError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"Invalid JSON constant: {value}")


def _fetch_json(url: str) -> object:
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise ApiError(f"[ERROR] API returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ApiError("[ERROR] API unreachable") from exc

    try:
        payload: object = json.loads(
            body.decode("utf-8"), parse_constant=_reject_json_constant
        )
    except ValueError as exc:
        raise ApiError("[ERROR] API returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise ApiError("[ERROR] API response is not a JSON object")

    return payload


def fetch_scores(url: str = API_URL) -> LeaderboardData:
    payload = _fetch_json(url)
    try:
        return parse_leaderboard(payload)
    except PayloadError as exc:
        raise ApiError(f"[ERROR] {exc}") from exc


def fetch_history(model_id: str, url: str | None = None) -> HistoryData:
    history_url = url or HISTORY_URL.format(
        model_id=urllib.parse.quote(model_id, safe="")
    )
    payload = _fetch_json(history_url)
    try:
        return parse_history(payload)
    except PayloadError as exc:
        raise ApiError(f"[ERROR] History: {exc}") from exc
