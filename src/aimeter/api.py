import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Literal, NoReturn, TypeAlias

from aimeter.constants import API_URL, HISTORY_URL, REQUEST_TIMEOUT
from aimeter.parsing import (
    HistoryData,
    LeaderboardData,
    PayloadError,
    parse_history,
    parse_leaderboard,
)


ApiErrorKind: TypeAlias = Literal["http", "timeout", "network", "invalid_response"]


class ApiError(Exception):
    def __init__(
        self, message: str, *, kind: ApiErrorKind, http_status: int | None = None
    ) -> None:
        self.kind = kind
        self.http_status = http_status
        super().__init__(message)


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"Invalid JSON constant: {value}")


def _fetch_json(url: str) -> object:
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise ApiError(
            f"API returned HTTP {exc.code}", kind="http", http_status=exc.code
        ) from exc
    except TimeoutError as exc:
        raise ApiError("API request timeout", kind="timeout") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise ApiError("API request timeout", kind="timeout") from exc
        raise ApiError("API unreachable", kind="network") from exc
    except OSError as exc:
        raise ApiError("API unreachable", kind="network") from exc

    try:
        payload: object = json.loads(
            body.decode("utf-8"), parse_constant=_reject_json_constant
        )
    except ValueError as exc:
        raise ApiError("API returned invalid JSON", kind="invalid_response") from exc

    if not isinstance(payload, dict):
        raise ApiError("API response is not a JSON object", kind="invalid_response")

    return payload


def fetch_scores(url: str = API_URL) -> LeaderboardData:
    payload = _fetch_json(url)
    try:
        return parse_leaderboard(payload)
    except PayloadError as exc:
        raise ApiError(str(exc), kind="invalid_response") from exc


def fetch_history(model_id: str, url: str | None = None) -> HistoryData:
    history_url = url or HISTORY_URL.format(
        model_id=urllib.parse.quote(model_id, safe="")
    )
    payload = _fetch_json(history_url)
    try:
        return parse_history(payload)
    except PayloadError as exc:
        raise ApiError(str(exc), kind="invalid_response") from exc
