import urllib.error

import pytest

from aimeter.api import ApiError, fetch_history, fetch_scores
from aimeter.constants import API_URL, HISTORY_URL
from aimeter.parsing import HistoryData, LeaderboardData


def fetch_endpoint(endpoint: str) -> LeaderboardData | HistoryData:
    return fetch_scores() if endpoint == "scores" else fetch_history("1")


def endpoint_url(endpoint: str) -> str:
    return API_URL if endpoint == "scores" else HISTORY_URL.format(model_id="1")


@pytest.mark.parametrize("endpoint", ["scores", "history"])
@pytest.mark.parametrize(
    "body",
    [
        b"{", b"\xff", b"[]", b"true",
        b'{"success": true, "data": [], "extra": NaN}',
        b'{"success": true, "data": [], "extra": Infinity}',
        b'{"success": true, "data": [], "extra": -Infinity}',
        b'{"success": true, "data": [], "extra": ' + b"1" * 5000 + b"}",
    ],
    ids=["syntax", "encoding", "array", "boolean", "nan", "inf", "negative-inf", "huge-int"],
)
def test_invalid_json_is_a_controlled_api_error(
    endpoint: str, body: bytes, http_responses: dict[str, bytes | Exception]
) -> None:
    http_responses[endpoint_url(endpoint)] = body
    with pytest.raises(ApiError, match="JSON") as exc:
        fetch_endpoint(endpoint)
    if body not in (b"[]", b"true"):
        assert exc.value.__cause__ is not None


@pytest.mark.parametrize("endpoint", ["scores", "history"])
@pytest.mark.parametrize(
    "body",
    [
        b'{"data": []}',
        b'{"success": 1, "data": []}',
        b'{"success": "true", "data": []}',
        b'{"success": false, "data": []}',
        b'{"success": true, "data": {}}',
        b'{"success": true}',
    ],
)
def test_envelope_errors_are_translated_to_api_errors(
    endpoint: str, body: bytes, http_responses: dict[str, bytes | Exception]
) -> None:
    http_responses[endpoint_url(endpoint)] = body
    with pytest.raises(ApiError) as exc:
        fetch_endpoint(endpoint)
    assert exc.value.__cause__ is not None


def test_scores_are_validated_after_json_decoding(
    http_responses: dict[str, bytes | Exception],
) -> None:
    http_responses[API_URL] = (
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
    http_responses[API_URL] = (
        b'{"success":true,"data":[{"name":"example","currentScore":'
        + str(10**400).encode() + b"}]}"
    )
    assert fetch_scores().by_name["example"].current_score is None


def test_history_is_validated_after_json_decoding(
    http_responses: dict[str, bytes | Exception],
) -> None:
    http_responses[HISTORY_URL.format(model_id="1")] = (
        b'{"success":true,"data":['
        b'{"score":40},{"score":true},{"score":"50"},{"score":1e400},{"score":60}]}'
    )
    result = fetch_history("1")
    assert result.scores == [40.0, 60.0]
    assert result.discarded_points == 3


def test_history_id_is_encoded_as_a_single_path_segment(
    http_responses: dict[str, bytes | Exception],
) -> None:
    url = HISTORY_URL.format(model_id="a%2Fb%3Fc%3Dd%23e")
    http_responses[url] = b'{"success":true,"data":[]}'
    assert fetch_history("a/b?c=d#e").scores == []


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timeout"),
        urllib.error.URLError("network"),
        OSError("read failure"),
    ],
)
def test_history_network_errors_are_controlled(
    error: Exception, http_responses: dict[str, bytes | Exception]
) -> None:
    http_responses[HISTORY_URL.format(model_id="1")] = error
    with pytest.raises(ApiError, match="unreachable") as exc:
        fetch_history("1")
    assert exc.value.__cause__ is error


def test_fetch_scores_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
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
