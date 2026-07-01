import json
from pathlib import Path

import pytest

from aimeter.api import ApiError, fetch_scores
from aimeter.cli import run
from aimeter.constants import LABEL_IMPROVED, LABEL_NO_DATA, LABEL_STABLE, LABEL_WORSENED
from aimeter.format import format_model_line, format_summary
from aimeter.models import (
    ModelResult,
    analyze_model,
    compute_period_stats,
    extract_history_scores,
    parse_stale_hours,
)

FIXTURES = Path(__file__).parent / "fixtures"
API_FIXTURE = FIXTURES / "api_response.json"
HISTORY_FIXTURE = FIXTURES / "history_response.json"


def load_fixture() -> dict:
    return json.loads(API_FIXTURE.read_text())


def load_history_fixture() -> dict:
    return json.loads(HISTORY_FIXTURE.read_text())


def mock_fetch_history(model_id: str) -> dict:
    histories = load_history_fixture()
    if model_id not in histories:
        raise ApiError("[ERROR] History API returned success=false")
    return histories[model_id]


def analyze_from_fixture(name: str) -> ModelResult:
    data = load_fixture()
    by_name = {entry["name"]: entry for entry in data["data"]}
    entry = by_name[name]
    history = mock_fetch_history(str(entry["id"]))
    period_stats = compute_period_stats(extract_history_scores(history))
    return analyze_model(name, entry, period_stats=period_stats)


def patch_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: load_fixture())
    monkeypatch.setattr("aimeter.cli.fetch_history", mock_fetch_history)


def test_analyze_model_labels() -> None:
    gpt55 = analyze_from_fixture("gpt-5.5")
    assert gpt55.delta == -5
    assert gpt55.label == LABEL_STABLE

    gpt54 = analyze_from_fixture("gpt-5.4")
    assert gpt54.delta == -5
    assert gpt54.label == LABEL_WORSENED
    assert not gpt54.strong_signal

    codex = analyze_from_fixture("claude-sonnet-4-6")
    assert codex.label == LABEL_WORSENED
    assert codex.strong_signal

    kimi = analyze_from_fixture("kimi-k2.7-code")
    assert kimi.label == LABEL_IMPROVED


def test_compute_period_stats() -> None:
    stats = compute_period_stats([12, 12, 12, 12, 12, 12, 92, 92, 92, 92, 92, 92])
    assert stats is not None
    assert stats.period_avg == 52
    assert stats.data_points == 12
    assert stats.standard_error is not None
    assert stats.standard_error > 10


def test_analyze_model_missing_trend() -> None:
    entry = {
        "id": "188",
        "name": "kimi-k2.7-code",
        "currentScore": 66,
        "isStale": False,
    }
    history = mock_fetch_history("188")
    period_stats = compute_period_stats(extract_history_scores(history))
    result = analyze_model("kimi-k2.7-code", entry, period_stats=period_stats)
    assert result.label == LABEL_IMPROVED
    assert result.trend is None


def test_analyze_model_no_history() -> None:
    entry = {
        "id": "256",
        "name": "gpt-5.5",
        "currentScore": 47,
        "trend": "stable",
        "isStale": False,
        "stability": 29,
    }
    result = analyze_model("gpt-5.5", entry, period_stats=None)
    assert result.label == LABEL_NO_DATA
    assert result.delta is None
    assert result.found is True


def test_analyze_model_not_found() -> None:
    result = analyze_model("missing-model", None)
    assert not result.found


def test_run_normal_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    patch_api(monkeypatch)
    exit_code = run(["gpt-5.5", "gpt-5.4", "kimi-k2.7-code"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "AI Stupid Meter," in output
    assert "gpt-5.5:" in output
    assert "gpt-5.4:" in output
    assert "kimi-k2.7-code:" in output
    assert "poprawił się" in output
    assert "pogorszył się" in output or "pogorszyły się" in output
    assert "Podsumowanie:" in output


def test_run_model_not_in_response(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {
        "success": True,
        "data": [{"id": "256", "name": "gpt-5.5", "currentScore": 47}],
    }
    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: payload)
    monkeypatch.setattr("aimeter.cli.fetch_history", mock_fetch_history)
    exit_code = run(["gpt-5.5", "nonexistent-model"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "[WARN] nonexistent-model: not found in API" in output
    assert "gpt-5.5:" in output


def test_run_success_false(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def raise_api_error() -> dict:
        raise ApiError("[ERROR] API returned success=false")

    monkeypatch.setattr("aimeter.cli.fetch_scores", raise_api_error)
    exit_code = run()
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "[ERROR] API returned success=false" in output


def test_run_empty_data(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: {"success": True, "data": []})
    exit_code = run()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "[WARN] API returned empty model list" in output


def test_fetch_scores_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    def raise_http(*_args, **_kwargs):
        raise urllib.error.HTTPError("url", 503, "error", None, None)

    monkeypatch.setattr("urllib.request.urlopen", raise_http)
    with pytest.raises(ApiError, match="HTTP 503"):
        fetch_scores()


def test_fetch_scores_rejects_non_object_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class MockResponse:
        def read(self) -> bytes:
            return b"[]"

        def __enter__(self) -> "MockResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: MockResponse())
    with pytest.raises(ApiError, match="not a JSON object"):
        fetch_scores()


def test_run_empty_watched_models_list(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_api(monkeypatch)
    exit_code = run([])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "gpt-5.5:" not in output
    assert "Podsumowanie: 0 poprawiło się, 0 pogorszyło się, 0 bez zmian" in output


def test_run_verbose_v1_shows_calculations(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_api(monkeypatch)
    exit_code = run(["gpt-5.5"], verbosity=1)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "→ Δ = wynik(" in output
    assert "→ próg = max(5," in output
    assert "→ ocena:" in output
    assert "→ Cumul. sum:" in output


def test_run_verbose_v2_shows_combined_fields(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {
        "success": True,
        "data": [{
            "id": "256",
            "name": "gpt-5.5",
            "currentScore": 47,
            "trend": "stable",
            "isStale": False,
            "stability": 78,
        }],
    }
    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: payload)
    monkeypatch.setattr("aimeter.cli.fetch_history", mock_fetch_history)
    exit_code = run(["gpt-5.5"], verbosity=2)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "punkty COMBINED 7d: 12" in output
    assert "stabilność (API): 78/100" in output
    assert "CI (COMBINED 7d): [" in output


def test_run_history_failure_shows_no_data_label(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {
        "success": True,
        "data": [{"id": "999", "name": "gpt-5.5", "currentScore": 47, "trend": "stable"}],
    }

    def fail_history(_model_id: str) -> dict:
        raise ApiError("[ERROR] API unreachable")

    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: payload)
    monkeypatch.setattr("aimeter.cli.fetch_history", fail_history)
    exit_code = run(["gpt-5.5"], verbosity=0)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "gpt-5.5:  47 (Δ—)  | brak danych  | 7d avg —" in output
    assert "Podsumowanie:" in output
    assert "1 brak danych" in output
    assert "0 bez zmian, 1 brak danych" in output


def test_run_no_verbose_no_calculations(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_api(monkeypatch)
    run(["gpt-5.5"], verbosity=0)
    output = capsys.readouterr().out

    assert "→ Δ = wynik(" not in output
    assert "→ próg" not in output


def _result_with_label(label: str) -> ModelResult:
    return ModelResult(
        name="test",
        current_score=50,
        period_avg=50,
        standard_error=5,
        trend="stable",
        is_stale=False,
        stale_hours=None,
        delta=0,
        threshold=5,
        label=label,
        strong_signal=False,
    )


@pytest.mark.parametrize(
    "improved,worsened,stable,no_data,expected",
    [
        (
            1, 0, 2, 0,
            "Podsumowanie: 1 poprawił się, 0 pogorszyło się, 2 bez zmian",
        ),
        (
            2, 1, 0, 0,
            "Podsumowanie: 2 poprawiły się, 1 pogorszył się, 0 bez zmian",
        ),
        (
            0, 0, 1, 2,
            "Podsumowanie: 0 poprawiło się, 0 pogorszyło się, 1 bez zmian, 2 braki danych",
        ),
    ],
)
def test_format_summary_pluralization(
    improved: int, worsened: int, stable: int, no_data: int, expected: str
) -> None:
    results = (
        [_result_with_label(LABEL_IMPROVED)] * improved
        + [_result_with_label(LABEL_WORSENED)] * worsened
        + [_result_with_label(LABEL_STABLE)] * stable
        + [_result_with_label(LABEL_NO_DATA)] * no_data
    )
    assert format_summary(results) == expected


def test_format_model_line_strong_signal() -> None:
    result = analyze_from_fixture("claude-sonnet-4-6")

    line = format_model_line(result)

    assert line == (
        "claude-sonnet-4-6:  46 (Δ-12) [!!]  | pogorszył się  | 7d avg 58  "
        "| SE ±0.0  | Cumul. sum:↓"
    )


def test_format_model_line_stale_and_high_se() -> None:
    result = analyze_from_fixture("claude-opus-4-8")

    line = format_model_line(result)

    assert "claude-opus-4-8:  57 (Δ+2)  | bez zmian  | 7d avg 55  " in line
    assert "SE↕" in line
    assert "Cumul. sum:↓  | stale 6h" in line


def test_format_model_line_high_se_only() -> None:
    result = analyze_from_fixture("gpt-5.5")

    line = format_model_line(result)

    assert "gpt-5.5:  47 (Δ-5)  | bez zmian  | 7d avg 52  " in line
    assert "SE↕" in line
    assert "Cumul. sum:→" in line


def test_parse_stale_hours_rejects_bool() -> None:
    assert parse_stale_hours(True) is None
    assert parse_stale_hours(False) is None
    assert parse_stale_hours(6) == 6
    assert parse_stale_hours("6h") == 6
    assert parse_stale_hours(None) is None
