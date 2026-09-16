import http.client
import json
import urllib.error
from io import BytesIO
from unittest.mock import Mock

import pytest

from aimeter.api import ApiError, ApiErrorKind
from aimeter.cli import HistoryStatus, load_model_history, run
from aimeter.constants import API_URL, HISTORY_URL


@pytest.fixture
def report_responses(
    http_responses: dict[str, bytes | Exception],
) -> dict[str, bytes | Exception]:
    http_responses[API_URL] = json.dumps(
        {
            "success": True,
            "data": [
                {"name": "partial", "id": "1", "currentScore": 55, "trend": "stable"},
                {"name": "healthy", "id": "2", "currentScore": 55, "trend": "stable"},
            ],
        }
    ).encode()
    http_responses[HISTORY_URL.format(model_id="1")] = (
        b'{"success":true,"data":[{"score":40},{"score":60}]}'
    )
    http_responses[HISTORY_URL.format(model_id="2")] = (
        b'{"success":true,"data":[{"score":50},{"score":50}]}'
    )
    return http_responses


@pytest.mark.parametrize("verbosity", [0, 1, 2])
@pytest.mark.parametrize(
    "response,status,expected_detail,discarded",
    [
        pytest.param(
            urllib.error.HTTPError("url", 503, "unavailable", None, None),
            "request_error",
            "failed to fetch history (HTTP 503)",
            0,
            id="http-503",
        ),
        pytest.param(
            TimeoutError("deadline exceeded"),
            "request_error",
            "failed to fetch history (API request timeout)",
            0,
            id="timeout",
        ),
        pytest.param(
            urllib.error.URLError(TimeoutError("deadline exceeded")),
            "request_error",
            "failed to fetch history (API request timeout)",
            0,
            id="wrapped-timeout",
        ),
        pytest.param(
            urllib.error.URLError("offline"),
            "request_error",
            "failed to fetch history (API unreachable)",
            0,
            id="network",
        ),
        pytest.param(
            b"{",
            "invalid_data",
            "invalid history data (API returned invalid JSON)",
            0,
            id="json",
        ),
        pytest.param(
            b'{"success":true,"data":[{"score":NaN}]}',
            "invalid_data",
            "invalid history data (API returned invalid JSON)",
            0,
            id="nonstandard-json",
        ),
        pytest.param(
            b"\xff",
            "invalid_data",
            "invalid history data (API returned invalid JSON)",
            0,
            id="encoding",
        ),
        pytest.param(
            b'{"success":false,"data":[]}',
            "invalid_data",
            "invalid history data (API returned success=false or invalid success value)",
            0,
            id="unsuccessful-response",
        ),
        pytest.param(
            b'{"success":true,"data":{}}',
            "invalid_data",
            "invalid history data (API response missing data list)",
            0,
            id="structure",
        ),
        pytest.param(
            b'{"success":true,"data":[{"score":true},{"score":"50"}]}',
            "invalid_data",
            "history contains no valid points",
            2,
            id="all-points-invalid",
        ),
        pytest.param(
            b'{"success":true,"data":['
            b'{"score":1e308},{"score":-1e308},{"score":true}]}',
            "numeric_error",
            "history statistics calculation error (Cannot compute finite history statistics)",
            1,
            id="numeric",
        ),
    ],
)
def test_history_failure_warns_once_and_preserves_partial_report(
    response: bytes | Exception,
    status: HistoryStatus,
    expected_detail: str,
    discarded: int,
    verbosity: int,
    report_responses: dict[str, bytes | Exception],
    capsys: pytest.CaptureFixture[str],
) -> None:
    report_responses[HISTORY_URL.format(model_id="1")] = response
    history = load_model_history("1")
    assert history.status == status
    assert history.stats is None
    assert history.discarded_points == discarded
    assert history.detail == expected_detail
    assert capsys.readouterr() == ("", "")

    assert run(["partial", "healthy"], verbosity=verbosity) == 0
    output = capsys.readouterr()
    assert "partial:  55 (Δ—)  | no data  | 7d avg —  | 7d max —" in output.out
    assert "healthy:  55 (Δ+5)  | improved" in output.out
    assert output.out.index("partial:") < output.out.index("healthy:")
    assert (
        "Summary: 1 improved, 0 worsened, 0 unchanged, 1 no data"
        in output.out.splitlines()
    )
    assert output.err == f"[WARN] partial: {expected_detail}" + (
        f"; discarded history points: {discarded}\n" if discarded else "\n"
    )
    assert "[WARN]" not in output.out


@pytest.mark.parametrize("endpoint", ["scores", "history"])
def test_interrupted_http_response_is_handled(
    endpoint: str,
    report_responses: dict[str, bytes | Exception],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    url = API_URL if endpoint == "scores" else HISTORY_URL.format(model_id="1")
    body = report_responses[url]
    assert isinstance(body, bytes)
    # Even valid-looking JSON must be rejected when the HTTP body is incomplete.
    headers = f"HTTP/1.1 200 OK\r\nContent-Length: {len(body) + 10}\r\n\r\n".encode()
    socket = Mock()
    socket.makefile.return_value = BytesIO(headers + body)
    response = http.client.HTTPResponse(socket)
    response.begin()

    def open_with_interrupted_response(
        request_url: str, *, timeout: int
    ) -> http.client.HTTPResponse | BytesIO:
        if request_url == url:
            return response
        response_body = report_responses[request_url]
        assert isinstance(response_body, bytes)
        return BytesIO(response_body)

    monkeypatch.setattr("urllib.request.urlopen", open_with_interrupted_response)

    exit_code = run(["partial", "healthy"])
    output = capsys.readouterr()
    assert response.closed
    if endpoint == "scores":
        assert exit_code == 1
        assert output.out == ""
        assert output.err == "[ERROR] API response could not be read\n"
    else:
        assert exit_code == 0
        assert "partial:  55 (Δ—)  | no data  | 7d avg —" in output.out
        assert "healthy:  55 (Δ+5)  | improved" in output.out
        assert (
            "Summary: 1 improved, 0 worsened, 0 unchanged, 1 no data"
            in output.out.splitlines()
        )
        assert output.err == (
            "[WARN] partial: failed to fetch history (API response could not be read)\n"
        )


@pytest.mark.parametrize("verbosity", [0, 1, 2])
@pytest.mark.parametrize("absence", ["missing", "null"])
@pytest.mark.parametrize("field", ["id", "currentScore"])
def test_expected_missing_fields_are_explained_only_in_verbose_mode(
    field: str,
    absence: str,
    verbosity: int,
    report_responses: dict[str, bytes | Exception],
    capsys: pytest.CaptureFixture[str],
) -> None:
    body = report_responses[API_URL]
    assert isinstance(body, bytes)
    payload = json.loads(body)
    if absence == "missing":
        del payload["data"][0][field]
    else:
        payload["data"][0][field] = None
    report_responses[API_URL] = json.dumps(payload).encode()
    if field == "id":
        # The HTTP fixture fails on any request for this model's history.
        del report_responses[HISTORY_URL.format(model_id="1")]

    assert run(["partial", "healthy"], verbosity=verbosity) == 0
    output = capsys.readouterr()
    assert "healthy:  55 (Δ+5)" in output.out
    assert "1 no data" in output.out
    if field == "currentScore":
        assert "partial:  — (Δ—)  | no data  | 7d avg 50  | 7d max 60" in output.out
        cause = "missing current score"
        if verbosity >= 2:
            assert "COMBINED 7d points: 2" in output.out
    else:
        assert "partial:  55 (Δ—)  | no data  | 7d avg —" in output.out
        cause = "missing history identifier"
    assert output.err == (f"[INFO] partial: {cause}\n" if verbosity else "")


@pytest.mark.parametrize("verbosity", [0, 1, 2])
def test_empty_history_has_its_own_state_and_verbose_explanation(
    verbosity: int,
    report_responses: dict[str, bytes | Exception],
    capsys: pytest.CaptureFixture[str],
) -> None:
    report_responses[HISTORY_URL.format(model_id="1")] = b'{"success":true,"data":[]}'
    history = load_model_history("1")
    assert history.status == "empty"
    assert history.stats is None
    assert history.discarded_points == 0

    assert run(["partial", "healthy"], verbosity=verbosity) == 0
    output = capsys.readouterr()
    assert "partial:  55 (Δ—)  | no data  | 7d avg —  | 7d max —" in output.out
    assert "healthy:  55 (Δ+5)  | improved" in output.out
    assert (
        "Summary: 1 improved, 0 worsened, 0 unchanged, 1 no data"
        in output.out.splitlines()
    )
    assert "[WARN]" not in output.out
    assert output.err == ("[INFO] partial: history is empty\n" if verbosity else "")


@pytest.mark.parametrize("kind", ["http", "timeout", "network", "invalid_response"])
def test_history_status_uses_error_kind_instead_of_message(
    kind: ApiErrorKind,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_history(_model_id: str) -> None:
        raise ApiError(
            "same detail for every failure",
            kind=kind,
            http_status=503 if kind == "http" else None,
        )

    monkeypatch.setattr("aimeter.cli.fetch_history", fail_history)
    history = load_model_history("1")
    assert history.status == (
        "invalid_data" if kind == "invalid_response" else "request_error"
    )
    if kind == "http":
        assert history.detail == "failed to fetch history (HTTP 503)"


@pytest.mark.parametrize("verbosity", [0, 1, 2])
def test_analysis_overflow_has_a_warning_and_preserves_history_statistics(
    verbosity: int,
    report_responses: dict[str, bytes | Exception],
    capsys: pytest.CaptureFixture[str],
) -> None:
    report_responses[API_URL] = (
        b'{"success":true,"data":['
        b'{"name":"partial","id":"1","currentScore":1e308},'
        b'{"name":"healthy","id":"2","currentScore":55}]}'
    )
    report_responses[HISTORY_URL.format(model_id="1")] = (
        b'{"success":true,"data":[{"score":-1e308}]}'
    )
    assert run(["partial", "healthy"], verbosity=verbosity) == 0
    output = capsys.readouterr()
    partial_line = next(
        line for line in output.out.splitlines() if line.startswith("partial:")
    )
    assert "(Δ—)  | no data" in partial_line
    assert "7d avg —" not in partial_line
    assert "7d max —" not in partial_line
    assert "healthy:  55 (Δ+5)" in output.out
    assert "1 no data" in output.out
    assert output.err == (
        "[WARN] partial: assessment calculation error (Cannot compute a finite model assessment)\n"
    )


@pytest.mark.parametrize("verbosity", [0, 1, 2])
def test_parser_and_discard_warnings_keep_context_and_are_not_repeated(
    verbosity: int,
    report_responses: dict[str, bytes | Exception],
    capsys: pytest.CaptureFixture[str],
) -> None:
    report_responses[API_URL] = (
        b'{"success":true,"data":['
        b'null,{"name":[]},'
        b'{"name":"partial","currentScore":"obsolete"},'
        b'{"name":"partial","id":"1","currentScore":55,"stability":"78"}]}'
    )
    report_responses[HISTORY_URL.format(model_id="1")] = (
        b'{"success":true,"data":[{"score":40},{"score":true},{"score":60}]}'
    )
    history = load_model_history("1")
    assert history.status == "ok"
    assert history.stats is not None and history.stats.period_avg == 50
    assert history.discarded_points == 1

    assert run(["partial", "partial"], verbosity=verbosity) == 0
    output = capsys.readouterr()
    assert output.out.count("partial:  55 (Δ+5)") == 2
    assert "[WARN]" not in output.out
    assert output.err.splitlines() == [
        "[WARN] Leaderboard entry 0: not an object; skipped",
        "[WARN] Leaderboard entry 1: invalid name; skipped",
        "[WARN] partial: duplicate name; using the last entry",
        "[WARN] partial: invalid stability; treated as missing",
        "[WARN] partial: discarded history points: 1",
    ]


@pytest.mark.parametrize(
    "response,cause",
    [
        (urllib.error.HTTPError("url", 503, "unavailable", None, None), "HTTP 503"),
        (TimeoutError(), "timeout"),
        (urllib.error.URLError(TimeoutError()), "timeout"),
        (urllib.error.URLError("offline"), "unreachable"),
        (b"{", "JSON"),
        (b'{"success":true,"data":{}}', "data list"),
        (
            b'{"success":true,"data":[null,{"name":[]}]}',
            "no entries with valid model names",
        ),
    ],
)
def test_leaderboard_failure_only_prints_an_error_to_stderr(
    response: bytes | Exception,
    cause: str,
    http_responses: dict[str, bytes | Exception],
    capsys: pytest.CaptureFixture[str],
) -> None:
    http_responses[API_URL] = response
    assert run(["partial", "healthy"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert len(output.err.splitlines()) == 1
    assert output.err.startswith("[ERROR] ")
    assert cause in output.err


@pytest.mark.parametrize("verbosity", [0, 1, 2])
def test_healthy_report_and_absent_model_do_not_add_stderr_diagnostics(
    verbosity: int,
    report_responses: dict[str, bytes | Exception],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(["healthy", "absent"], verbosity=verbosity) == 0
    output = capsys.readouterr()
    assert "healthy:  55 (Δ+5)  | improved" in output.out
    assert output.out.count("[WARN] absent: not found in API") == 1
    assert "no data" not in output.out
    assert output.err == ""
