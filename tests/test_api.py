import urllib.error
from io import BytesIO

import pytest

from aimeter.api import ApiError, ApiErrorKind, fetch_history, fetch_scores
from aimeter.parsing import HistoryData, LeaderboardData, PayloadError

# Expected API contract, independent of the production URL constants.
EXPECTED_QUERY = "period=7d&sortBy=combined"
EXPECTED_SCORES_URL = (
    "https://aistupidlevel.info/dashboard/scores?mode=leaderboard&" + EXPECTED_QUERY
)
EXPECTED_HISTORY_URL = (
    "https://aistupidlevel.info/dashboard/history/{model_id}?" + EXPECTED_QUERY
)


def fetch_endpoint(endpoint: str) -> LeaderboardData | HistoryData:
    return fetch_scores() if endpoint == "scores" else fetch_history("1")


def endpoint_url(endpoint: str) -> str:
    return (
        EXPECTED_SCORES_URL
        if endpoint == "scores"
        else EXPECTED_HISTORY_URL.format(model_id="1")
    )


@pytest.mark.parametrize(
    "body",
    [
        b"{",
        b"\xff",
        b"[]",
        b"true",
        b'{"success": true, "data": [], "extra": NaN}',
        b'{"success": true, "data": [], "extra": Infinity}',
        b'{"success": true, "data": [], "extra": -Infinity}',
        b'{"success": true, "data": [], "extra": ' + b"1" * 5000 + b"}",
    ],
    ids=[
        "syntax",
        "encoding",
        "array",
        "boolean",
        "nan",
        "inf",
        "negative-inf",
        "huge-int",
    ],
)
def test_invalid_json_is_a_controlled_api_error(
    body: bytes, http_responses: dict[str, bytes | Exception]
) -> None:
    http_responses[EXPECTED_SCORES_URL] = body
    non_object = body in (b"[]", b"true")
    message = "not a JSON object" if non_object else "invalid JSON"
    with pytest.raises(ApiError, match=message) as exc:
        fetch_scores()
    assert exc.value.kind == "invalid_response"
    assert exc.value.http_status is None
    assert "[ERROR]" not in str(exc.value)
    if not non_object:
        assert isinstance(exc.value.__cause__, ValueError)


def test_history_propagates_json_errors(
    http_responses: dict[str, bytes | Exception],
) -> None:
    http_responses[EXPECTED_HISTORY_URL.format(model_id="1")] = b"{"
    with pytest.raises(ApiError, match="invalid JSON") as exc:
        fetch_history("1")
    assert exc.value.kind == "invalid_response"
    assert isinstance(exc.value.__cause__, ValueError)


@pytest.mark.parametrize("endpoint", ["scores", "history"])
def test_envelope_errors_are_translated_to_api_errors(
    endpoint: str, http_responses: dict[str, bytes | Exception]
) -> None:
    # Payload variants are covered by the parser tests; check the API boundary here.
    http_responses[endpoint_url(endpoint)] = b'{"success": true, "data": {}}'
    with pytest.raises(ApiError, match="missing data list") as exc:
        fetch_endpoint(endpoint)
    assert exc.value.kind == "invalid_response"
    assert exc.value.http_status is None
    assert "[ERROR]" not in str(exc.value)
    assert isinstance(exc.value.__cause__, PayloadError)
    assert str(exc.value) == str(exc.value.__cause__)


def test_scores_request_and_response_contract(
    http_responses: dict[str, bytes | Exception],
) -> None:
    http_responses[EXPECTED_SCORES_URL] = (
        b'{"success":true,"data":['
        b'{"name":"normal","currentScore":0},'
        b'{"name":"overflow","currentScore":1e400}]}'
    )
    result = fetch_scores()
    assert result.by_name["normal"].current_score == 0.0
    assert result.by_name["overflow"].current_score is None
    assert len(result.warnings) == 1
    assert "overflow" in result.warnings[0]


def test_large_json_integer_is_rejected_at_field_level(
    http_responses: dict[str, bytes | Exception],
) -> None:
    http_responses[EXPECTED_SCORES_URL] = (
        b'{"success":true,"data":[{"name":"example","currentScore":'
        + str(10**400).encode()
        + b"}]}"
    )
    assert fetch_scores().by_name["example"].current_score is None


def test_history_request_and_response_contract(
    http_responses: dict[str, bytes | Exception],
) -> None:
    http_responses[EXPECTED_HISTORY_URL.format(model_id="1")] = (
        b'{"success":true,"data":['
        b'{"score":40},{"score":true},{"score":"50"},{"score":1e400},{"score":60}]}'
    )
    result = fetch_history("1")
    assert result.scores == [40.0, 60.0]
    assert result.discarded_points == 3


def test_history_id_is_encoded_as_a_single_path_segment(
    http_responses: dict[str, bytes | Exception],
) -> None:
    url = EXPECTED_HISTORY_URL.format(model_id="a%2Fb%3Fc%3Dd%23e")
    http_responses[url] = b'{"success":true,"data":[]}'
    assert fetch_history("a/b?c=d#e").scores == []


@pytest.mark.parametrize(
    "error,kind,message,http_status",
    [
        (
            urllib.error.HTTPError("url", 503, "error", None, None),
            "http",
            "HTTP 503",
            503,
        ),
        (
            urllib.error.HTTPError("url", 404, "error", None, None),
            "http",
            "HTTP 404",
            404,
        ),
        (TimeoutError("deadline exceeded"), "timeout", "timeout", None),
        (
            urllib.error.URLError(TimeoutError("deadline exceeded")),
            "timeout",
            "timeout",
            None,
        ),
        (urllib.error.URLError("network"), "network", "unreachable", None),
        (urllib.error.URLError("timeout"), "network", "unreachable", None),
        (OSError("connection failure"), "network", "unreachable", None),
    ],
)
def test_transport_errors_keep_their_kind_status_and_cause(
    error: Exception,
    kind: ApiErrorKind,
    message: str,
    http_status: int | None,
    http_responses: dict[str, bytes | Exception],
) -> None:
    http_responses[EXPECTED_SCORES_URL] = error
    with pytest.raises(ApiError, match=message) as exc:
        fetch_scores()
    assert exc.value.kind == kind
    assert exc.value.http_status == http_status
    assert exc.value.__cause__ is error
    assert "[ERROR]" not in str(exc.value)


@pytest.mark.parametrize(
    "error,kind,message",
    [
        (TimeoutError("deadline exceeded"), "timeout", "timeout"),
        (OSError("read failure"), "network", "unreachable"),
    ],
)
def test_history_read_errors_keep_their_kind_and_cause(
    error: Exception,
    kind: ApiErrorKind,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailedResponse(BytesIO):
        def read(self, *_args: object) -> bytes:
            raise error

    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: FailedResponse())
    with pytest.raises(ApiError, match=message) as exc:
        fetch_history("1")
    assert exc.value.kind == kind
    assert exc.value.http_status is None
    assert exc.value.__cause__ is error
    assert "[ERROR]" not in str(exc.value)
