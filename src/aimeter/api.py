import json
import urllib.error
import urllib.request
from typing import Any

from aimeter.constants import API_URL, REQUEST_TIMEOUT


class ApiError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def fetch_scores(url: str = API_URL) -> dict[str, Any]:
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

    if not payload.get("success"):
        raise ApiError("[ERROR] API returned success=false")

    return payload


def index_by_name(data: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        entry["name"]: entry
        for entry in data
        if isinstance(entry, dict) and "name" in entry
    }
