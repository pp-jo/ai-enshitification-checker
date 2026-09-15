import json
from collections.abc import Callable
from pathlib import Path

import pytest

from aimeter.api import ApiError
from aimeter.cli import main, run
from aimeter.parsing import HistoryData, parse_leaderboard


def test_run_normal_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    patch_api: None,
) -> None:
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
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mock_fetch_history: Callable[[str], HistoryData],
) -> None:
    payload = {
        "success": True,
        "data": [{"id": "256", "name": "gpt-5.5", "currentScore": 47}],
    }
    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: parse_leaderboard(payload))
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
    monkeypatch.setattr(
        "aimeter.cli.fetch_scores",
        lambda: parse_leaderboard({"success": True, "data": []}),
    )
    exit_code = run()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "[WARN] API returned empty model list" in output


def test_run_empty_watched_models_list(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    patch_api: None,
) -> None:
    exit_code = run([])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "gpt-5.5:" not in output
    assert "Podsumowanie: 0 poprawiło się, 0 pogorszyło się, 0 bez zmian" in output


def test_run_verbose_v1_shows_calculations(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    patch_api: None,
) -> None:
    exit_code = run(["gpt-5.5"], verbosity=1)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "→ Δ = wynik(" in output
    assert "→ próg = max(5," in output
    assert "→ ocena:" in output
    assert "→ Cumul. sum:" in output


def test_run_verbose_v2_shows_combined_fields(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mock_fetch_history: Callable[[str], HistoryData],
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
    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: parse_leaderboard(payload))
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

    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: parse_leaderboard(payload))
    monkeypatch.setattr("aimeter.cli.fetch_history", fail_history)
    exit_code = run(["gpt-5.5"], verbosity=0)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "gpt-5.5:  47 (Δ—)  | brak danych  | 7d avg —  | 7d max —" in output
    assert "Podsumowanie:" in output
    assert "1 brak danych" in output
    assert "0 bez zmian, 1 brak danych" in output


def test_run_no_verbose_no_calculations(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    patch_api: None,
) -> None:
    run(["gpt-5.5"], verbosity=0)
    output = capsys.readouterr().out

    assert "→ Δ = wynik(" not in output
    assert "→ próg" not in output


@pytest.mark.parametrize(
    "source,model_name",
    [
        ("explicit", "kimi-k2.7-code"),
        ("xdg", "kimi-k2.7-code"),
        ("builtin", "kimi-k2.7-code"),
        ("explicit", " \t kimi-k2.7-code \t "),
        ("xdg", " \t kimi-k2.7-code \t "),
    ],
)
def test_main_uses_selected_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    source: str,
    model_name: str,
    patch_api: None,
) -> None:
    xdg_dir = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_dir))
    args = ["aimeter", "-vv"]
    if source == "explicit":
        path = tmp_path / "my models.toml"
        args.extend(["--config", str(path)])
    else:
        path = xdg_dir / "aimeter" / "config.toml"
    if source != "builtin":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"watched_models = [{json.dumps(model_name)}]", encoding="utf-8"
        )
    monkeypatch.setattr("sys.argv", args)

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "kimi-k2.7-code:" in output
    assert "→ Δ = wynik(" in output
    assert "punkty COMBINED 7d:" in output
    assert ("gpt-5.5:" in output) == (source == "builtin")
    if source != "builtin":
        assert "not found in API" not in output
