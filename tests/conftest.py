import json
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pytest

from aimeter.api import ApiError
from aimeter.models import ModelResult, analyze_model, compute_period_stats
from aimeter.parsing import (
    HistoryData,
    LeaderboardData,
    parse_history,
    parse_leaderboard,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def leaderboard_fixture() -> LeaderboardData:
    payload = json.loads((FIXTURES / "api_response.json").read_text(encoding="utf-8"))
    return parse_leaderboard(payload)


@pytest.fixture
def history_fixtures() -> dict[str, HistoryData]:
    payload = json.loads(
        (FIXTURES / "history_response.json").read_text(encoding="utf-8")
    )
    return {model_id: parse_history(history) for model_id, history in payload.items()}


@pytest.fixture
def mock_fetch_history(
    history_fixtures: dict[str, HistoryData],
) -> Callable[[str], HistoryData]:
    def fetch(model_id: str) -> HistoryData:
        if model_id not in history_fixtures:
            raise ApiError("[ERROR] History API returned success=false")
        return history_fixtures[model_id]

    return fetch


@pytest.fixture
def analyze_from_fixture(
    leaderboard_fixture: LeaderboardData,
    mock_fetch_history: Callable[[str], HistoryData],
) -> Callable[[str], ModelResult]:
    def analyze(name: str) -> ModelResult:
        entry = leaderboard_fixture.by_name[name]
        assert entry.model_id is not None
        history = mock_fetch_history(entry.model_id)
        return analyze_model(
            name, entry, period_stats=compute_period_stats(history.scores)
        )

    return analyze


@pytest.fixture
def patch_api(
    monkeypatch: pytest.MonkeyPatch,
    leaderboard_fixture: LeaderboardData,
    mock_fetch_history: Callable[[str], HistoryData],
) -> None:
    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: leaderboard_fixture)
    monkeypatch.setattr("aimeter.cli.fetch_history", mock_fetch_history)


@pytest.fixture
def http_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, bytes | Exception]:
    """Serve explicit responses through the real API decoding/parsing path."""
    responses: dict[str, bytes | Exception] = {}

    def open_response(url: str, *, timeout: int) -> BytesIO:
        if url not in responses:
            pytest.fail(f"Unexpected HTTP request: {url}")
        response = responses[url]
        if isinstance(response, Exception):
            raise response
        return BytesIO(response)

    monkeypatch.setattr("urllib.request.urlopen", open_response)
    return responses
