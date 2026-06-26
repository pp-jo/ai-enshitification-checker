import json
from pathlib import Path

import pytest

from aimeter.api import ApiError, fetch_scores
from aimeter.cli import run
from aimeter.constants import LABEL_IMPROVED, LABEL_STABLE, LABEL_WORSENED
from aimeter.format import format_model_line, format_summary
from aimeter.models import ModelResult, analyze_model, parse_stale_hours

FIXTURES = Path(__file__).parent / "fixtures"
API_FIXTURE = FIXTURES / "api_response.json"


def load_fixture() -> dict:
    return json.loads(API_FIXTURE.read_text())


def test_analyze_model_labels() -> None:
    data = load_fixture()
    by_name = {entry["name"]: entry for entry in data["data"]}

    gpt55 = analyze_model("gpt-5.5", by_name["gpt-5.5"])
    assert gpt55.delta == -5
    assert gpt55.label == LABEL_STABLE

    gpt54 = analyze_model("gpt-5.4", by_name["gpt-5.4"])
    assert gpt54.delta == -5
    assert gpt54.label == LABEL_WORSENED
    assert not gpt54.strong_signal

    codex = analyze_model("claude-sonnet-4-6", by_name["claude-sonnet-4-6"])
    assert codex.label == LABEL_WORSENED
    assert codex.strong_signal

    kimi = analyze_model("kimi-k2.7-code", by_name["kimi-k2.7-code"])
    assert kimi.label == LABEL_IMPROVED


def test_analyze_model_missing_trend() -> None:
    entry = {
        "name": "kimi-k2.7-code",
        "currentScore": 66,
        "periodAvg": 54,
        "standardError": 8.2,
        "isStale": False,
    }
    result = analyze_model("kimi-k2.7-code", entry)
    assert result.label == LABEL_IMPROVED
    assert result.trend is None


def test_analyze_model_not_found() -> None:
    result = analyze_model("missing-model", None)
    assert not result.found


def test_run_normal_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: load_fixture())
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
    payload = {"success": True, "data": [{"name": "gpt-5.5", "currentScore": 47, "periodAvg": 52}]}
    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: payload)
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
    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: load_fixture())
    exit_code = run([])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "gpt-5.5:" not in output
    assert "Podsumowanie: 0 poprawiło się, 0 pogorszyło się, 0 bez zmian" in output


def test_run_verbose_v1_shows_calculations(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: load_fixture())
    exit_code = run(["gpt-5.5"], verbosity=1)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "→ Δ = wynik(" in output
    assert "→ próg = max(5," in output
    assert "→ ocena:" in output
    assert "→ CUSUM:" in output


def test_run_verbose_v2_shows_api_fields(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = {
        "success": True,
        "data": [{
            "name": "gpt-5.5",
            "currentScore": 47,
            "periodAvg": 52,
            "standardError": 10.7,
            "trend": "stable",
            "isStale": False,
            "dataPoints": 12,
            "stability": 78,
            "confidenceLower": 39,
            "confidenceUpper": 55,
        }],
    }
    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: payload)
    exit_code = run(["gpt-5.5"], verbosity=2)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "punkty danych: 12" in output
    assert "stabilność: 78/100" in output
    assert "CI: [39, 55]" in output


def test_run_no_verbose_no_calculations(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: load_fixture())
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
    "improved,worsened,stable,expected",
    [
        (1, 0, 2, "Podsumowanie: 1 poprawił się, 0 pogorszyło się, 2 bez zmian"),
        (2, 1, 0, "Podsumowanie: 2 poprawiły się, 1 pogorszył się, 0 bez zmian"),
        (12, 0, 0, "Podsumowanie: 12 poprawiło się, 0 pogorszyło się, 0 bez zmian"),
        (0, 22, 0, "Podsumowanie: 0 poprawiło się, 22 pogorszyły się, 0 bez zmian"),
    ],
)
def test_format_summary_pluralization(
    improved: int, worsened: int, stable: int, expected: str
) -> None:
    results = (
        [_result_with_label(LABEL_IMPROVED)] * improved
        + [_result_with_label(LABEL_WORSENED)] * worsened
        + [_result_with_label(LABEL_STABLE)] * stable
    )
    assert format_summary(results) == expected


def test_format_model_line_strong_signal() -> None:
    data = load_fixture()
    by_name = {entry["name"]: entry for entry in data["data"]}
    result = analyze_model("claude-sonnet-4-6", by_name["claude-sonnet-4-6"])

    line = format_model_line(result)

    assert line == (
        "claude-sonnet-4-6:  46 (Δ-12) [!!]  | pogorszył się  | 7d avg 58  "
        "| SE ±5.5  | CUSUM:↓"
    )


def test_format_model_line_stale_and_high_se() -> None:
    data = load_fixture()
    by_name = {entry["name"]: entry for entry in data["data"]}
    result = analyze_model("claude-opus-4-8", by_name["claude-opus-4-8"])

    line = format_model_line(result)

    assert line == (
        "claude-opus-4-8:  57 (Δ+2)  | bez zmian  | 7d avg 55  "
        "| SE ±13.0 (SE↕)  | CUSUM:↓  | stale 6h"
    )


def test_format_model_line_high_se_only() -> None:
    data = load_fixture()
    by_name = {entry["name"]: entry for entry in data["data"]}
    result = analyze_model("gpt-5.5", by_name["gpt-5.5"])

    line = format_model_line(result)

    assert line == (
        "gpt-5.5:  47 (Δ-5)  | bez zmian  | 7d avg 52  "
        "| SE ±10.7 (SE↕)  | CUSUM:→"
    )


def test_parse_stale_hours_rejects_bool() -> None:
    assert parse_stale_hours(True) is None
    assert parse_stale_hours(False) is None
    assert parse_stale_hours(6) == 6
    assert parse_stale_hours("6h") == 6
    assert parse_stale_hours(None) is None
