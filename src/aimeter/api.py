import json
import urllib.error
import urllib.request
from typing import Any

from aimeter.constants import API_URL, HISTORY_URL, REQUEST_TIMEOUT


class ApiError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _fetch_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as response:
            body = response.read().decode()
    except urllib.error.HTTPError as exc:
        raise ApiError(f"[ERROR] API returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ApiError("[ERROR] API unreachable") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ApiError("[ERROR] API returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise ApiError("[ERROR] API response is not a JSON object")

    return payload


def fetch_scores(url: str = API_URL) -> dict[str, Any]:
    payload = _fetch_json(url)
    if not payload.get("success"):
        raise ApiError("[ERROR] API returned success=false")
    return payload


def fetch_history(model_id: str, url: str | None = None) -> dict[str, Any]:
    history_url = url or HISTORY_URL.format(model_id=model_id)
    payload = _fetch_json(history_url)
    if not payload.get("success"):
        raise ApiError("[ERROR] History API returned success=false")
    return payload


def index_by_name(data: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        entry["name"]: entry
        for entry in data
        if isinstance(entry, dict) and "name" in entry
    }
