import json

import pytest

from aimeter.api import fetch_scores
from aimeter.cli import collect_model_outcomes, load_model_history, run
from aimeter.constants import API_URL, HISTORY_URL


def set_responses(
    responses: dict[str, bytes | Exception],
    bad_entry: dict[str, object],
    bad_history: bytes = b'{"success":true,"data":[{"score":50},{"score":50}]}',
) -> None:
    responses[API_URL] = json.dumps({
        "success": True,
        "data": [bad_entry, {"name": "good", "id": "2", "currentScore": 55}],
    }).encode()
    responses[HISTORY_URL.format(model_id="1")] = bad_history
    responses[HISTORY_URL.format(model_id="2")] = (
        b'{"success":true,"data":[{"score":50},{"score":50}]}'
    )


@pytest.mark.parametrize("verbosity", [0, 1, 2])
@pytest.mark.parametrize(
    "field,value,no_assessment",
    [
        ("currentScore", "47", True),
        ("currentScore", True, True),
        ("currentScore", False, True),
        ("currentScore", [], True),
        ("stability", "78", False),
        ("stability", True, False),
        ("isStale", "false", False),
        ("staleDuration", "Infinity", False),
        ("trend", "sideways", False),
        ("trend", ["down"], False),
        ("id", True, True),
        ("id", [], True),
    ],
)
def test_bad_fields_do_not_crash_or_hide_healthy_models(
    field: str,
    value: object,
    no_assessment: bool,
    verbosity: int,
    http_responses: dict[str, bytes | Exception],
    capsys: pytest.CaptureFixture[str],
) -> None:
    entry: dict[str, object] = {
        "name": "bad", "id": "1", "currentScore": 55, "trend": "stable",
    }
    entry[field] = value
    set_responses(http_responses, entry)
    assert run(["bad", "good"], verbosity=verbosity) == 0
    output = capsys.readouterr()
    bad_line = next(line for line in output.out.splitlines() if line.startswith("bad:"))
    assert ("no data" in bad_line) == no_assessment
    assert "good:  55 (Δ+5)" in output.out
    assert "improved" in output.out
    assert " [!!]" not in bad_line
    assert "stale" not in bad_line
    assert output.err.count(f"[WARN] bad: invalid {field}; treated as missing") == 1
    assert "[WARN]" not in output.out


@pytest.mark.parametrize("verbosity", [0, 1, 2])
@pytest.mark.parametrize(
    "body,has_warning",
    [
        (b'{"success":true,"data":[]}', False),
        (b'{"success":true,"data":[{"score":true},{"score":"50"}]}', True),
        (b'{"success":true,"data":{}}', True),
        (b'{"success":false,"data":[]}', True),
        (b'{"success":true,"data":[{"score":NaN}]}', True),
        (b'{"success":true,"data":[{"score":1e308},{"score":-1e308}]}', True),
    ],
)
def test_unusable_history_preserves_current_score_and_other_models(
    body: bytes,
    has_warning: bool,
    verbosity: int,
    http_responses: dict[str, bytes | Exception],
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_responses(
        http_responses,
        {"name": "bad", "id": "1", "currentScore": 55},
        body,
    )
    assert run(["bad", "good"], verbosity=verbosity) == 0
    output = capsys.readouterr()
    assert "bad:  55 (Δ—)  | no data" in output.out
    assert "good:  55 (Δ+5)" in output.out
    assert "1 no data" in output.out
    assert ("[WARN] bad:" in output.err) == has_warning
    assert "[WARN]" not in output.out


def test_mixed_history_uses_only_valid_points_for_all_statistics(
    http_responses: dict[str, bytes | Exception], capsys: pytest.CaptureFixture[str]
) -> None:
    set_responses(
        http_responses,
        {"name": "bad", "id": "1", "currentScore": 50},
        b'{"success":true,"data":['
        b'{"score":40},{"score":true},{"score":"50"},{"score":60}]}',
    )
    assert run(["bad"], verbosity=2) == 0
    output = capsys.readouterr()
    assert "50 (Δ+0)  | unchanged  | 7d avg 50  | 7d max 60" in output.out
    assert "SE ±10.0" in output.out
    assert "COMBINED 7d points: 2" in output.out
    assert "CI (COMBINED 7d): [30, 70]" in output.out
    assert output.err == "[WARN] bad: discarded history points: 2\n"


def test_invalid_name_does_not_break_indexing_in_cli(
    http_responses: dict[str, bytes | Exception], capsys: pytest.CaptureFixture[str]
) -> None:
    set_responses(http_responses, {"name": [], "id": "1", "currentScore": 50})
    assert run(["bad", "good"]) == 0
    output = capsys.readouterr().out
    assert "[WARN] bad: not found in API" in output
    assert "good:  55 (Δ+5)" in output


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonstandard_json_constants_fail_cleanly_in_cli(
    constant: str,
    http_responses: dict[str, bytes | Exception],
    capsys: pytest.CaptureFixture[str],
) -> None:
    http_responses[API_URL] = (
        '{"success":true,"data":[{"name":"bad","currentScore":' + constant + "}]}"
    ).encode()
    assert run(["bad"], verbosity=2) == 1
    output = capsys.readouterr()
    assert output.err == "[ERROR] API returned invalid JSON\n"
    assert output.out == ""


def test_numeric_history_error_is_retained_without_printing(
    http_responses: dict[str, bytes | Exception], capsys: pytest.CaptureFixture[str]
) -> None:
    http_responses[HISTORY_URL.format(model_id="1")] = (
        b'{"success":true,"data":['
        b'{"score":1e308},{"score":-1e308},{"score":true}]}'
    )
    outcome = load_model_history("1")
    assert outcome.stats is None
    assert outcome.discarded_points == 1
    assert outcome.status == "numeric_error"
    assert outcome.detail is not None
    assert "statistics" in outcome.detail
    output = capsys.readouterr()
    assert output.out == output.err == ""


def test_history_decode_error_is_retained_without_printing(
    http_responses: dict[str, bytes | Exception], capsys: pytest.CaptureFixture[str]
) -> None:
    http_responses[HISTORY_URL.format(model_id="1")] = b"invalid JSON"
    outcome = load_model_history("1")
    assert outcome.stats is None
    assert outcome.status == "invalid_data"
    assert outcome.detail is not None
    assert "JSON" in outcome.detail
    output = capsys.readouterr()
    assert output.out == output.err == ""


def test_missing_id_does_not_request_history(
    http_responses: dict[str, bytes | Exception],
) -> None:
    outcome = load_model_history(None)
    assert outcome.stats is None
    assert outcome.status == "missing_id"
    assert outcome.detail == "missing history identifier"


def test_collected_results_keep_each_models_history_diagnostics(
    http_responses: dict[str, bytes | Exception],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_responses(
        http_responses,
        {"name": "bad", "id": "1", "currentScore": 55},
        b'{"success":true,"data":[{"score":40},{"score":true},{"score":60}]}',
    )
    http_responses[HISTORY_URL.format(model_id="2")] = b"invalid JSON"
    leaderboard = fetch_scores()

    outcomes = collect_model_outcomes(leaderboard, ["bad", "good"])
    assert [outcome.result.name for outcome in outcomes] == ["bad", "good"]
    assert outcomes[0].result.period_avg == 50
    assert outcomes[0].history.discarded_points == 1
    assert outcomes[0].history.status == "ok"
    assert outcomes[0].history.detail is None
    assert outcomes[1].result.current_score == 55
    assert outcomes[1].result.delta is None
    assert outcomes[1].history.status == "invalid_data"
    assert outcomes[1].history.detail is not None
    assert "JSON" in outcomes[1].history.detail

    # The rendering path consumes these same outcomes without reading history again.
    http_responses.clear()
    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: leaderboard)
    monkeypatch.setattr("aimeter.cli.collect_model_outcomes", lambda *_args: outcomes)
    assert run(["bad", "good"], verbosity=2) == 0
    output = capsys.readouterr()
    assert "bad:  55 (Δ+5)" in output.out
    assert "good:  55 (Δ—)  | no data" in output.out
    assert output.err.count("[WARN] bad: discarded history points: 1") == 1
    assert output.err.count("[WARN] good: invalid history data") == 1
    assert "JSON" in output.err
