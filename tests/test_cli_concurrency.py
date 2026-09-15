import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from io import StringIO
from threading import Event, current_thread, main_thread
from unittest.mock import Mock

import pytest

from aimeter.cli import HistoryOutcome, collect_model_outcomes, run
from aimeter.constants import API_URL, HISTORY_URL
from aimeter.parsing import HistoryData, parse_leaderboard


@pytest.fixture(autouse=True)
def block_unexpected_http(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_http(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Concurrency tests must not access the public API")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_http)


@pytest.mark.parametrize("model_count", [1, 2, 3, 4, 7])
def test_pool_size_is_bounded_by_unique_needed_histories(
    model_count: int, monkeypatch: pytest.MonkeyPatch,
) -> None:
    leaderboard = parse_leaderboard({
        "success": True,
        "data": [
            {"name": str(i), "id": str(i), "currentScore": 55}
            for i in range(model_count + 1)
        ],
    })
    names = [str(i) for i in range(model_count)]
    watched = names + [names[0], "absent"]
    fetch = Mock(return_value=HistoryData(scores=[50.0, 50.0], discarded_points=0))
    pool = Mock(wraps=ThreadPoolExecutor)
    monkeypatch.setattr("aimeter.cli.fetch_history", fetch)
    monkeypatch.setattr("aimeter.cli.ThreadPoolExecutor", pool)

    outcomes = collect_model_outcomes(leaderboard, watched)

    pool.assert_called_once_with(max_workers=min(4, model_count))
    assert Counter(call.args[0] for call in fetch.call_args_list) == Counter(names)
    assert [outcome.result.name for outcome in outcomes] == watched
    assert all(outcome.result.period_avg == 50 for outcome in outcomes[:-1])
    assert not outcomes[-1].result.found


@pytest.mark.parametrize("watched", [[], ["absent"], ["no-id"], ["absent", "no-id"]])
def test_no_needed_ids_skips_pool_and_progress(
    watched: list[str], monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    leaderboard = parse_leaderboard({
        "success": True,
        "data": [
            {"name": "no-id", "currentScore": 55},
            {"name": "unwatched", "id": "unused", "currentScore": 55},
        ],
    })
    pool = Mock(side_effect=AssertionError("No histories need a pool"))
    fetch = Mock(side_effect=AssertionError("No histories need HTTP"))
    monkeypatch.setattr("aimeter.cli.ThreadPoolExecutor", pool)
    monkeypatch.setattr("aimeter.cli.fetch_history", fetch)
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)

    outcomes = collect_model_outcomes(leaderboard, watched)

    pool.assert_not_called()
    fetch.assert_not_called()
    assert [outcome.result.name for outcome in outcomes] == watched
    assert all(outcome.history.status == "missing_id" for outcome in outcomes)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("http_status", [None, 429, 503])
def test_requests_are_deduplicated_per_run_and_failures_keep_model_context(
    http_status: int | None,
    http_responses: dict[str, bytes | Exception],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    http_responses[API_URL] = json.dumps({
        "success": True,
        "data": [
            {"name": "shared", "id": "1", "currentScore": 40},
            {"name": "alias", "id": "1", "currentScore": 55},
            {"name": "healthy", "id": "2", "currentScore": 55},
            {"name": "no-id", "currentScore": 55},
            {"name": "unwatched", "id": "3", "currentScore": 55},
        ],
    }).encode()
    shared_url = HISTORY_URL.format(model_id="1")
    healthy_url = HISTORY_URL.format(model_id="2")
    history = b'{"success":true,"data":[{"score":50},{"score":50}]}'
    http_responses[shared_url] = (
        history if http_status is None else urllib.error.HTTPError(
            shared_url, http_status, "unavailable", None, None
        )
    )
    http_responses[healthy_url] = history
    open_response = Mock(wraps=urllib.request.urlopen)
    monkeypatch.setattr("urllib.request.urlopen", open_response)
    watched = ["alias", "healthy", "shared", "alias", "absent", "no-id"]

    # Repeated runs must fetch fresh data, including previously failed histories.
    for run_number in (1, 2):
        assert run(watched) == 0
        output = capsys.readouterr()
        assert Counter(call.args[0] for call in open_response.call_args_list) == {
            API_URL: run_number,
            shared_url: run_number,
            healthy_url: run_number,
        }
        assert all(
            call.kwargs == {"timeout": 10} for call in open_response.call_args_list
        )
        rows = [line for line in output.out.splitlines() if line.startswith(
            ("alias:", "healthy:", "shared:", "[WARN] absent:", "no-id:")
        )]
        row_names = [line.removeprefix("[WARN] ").split(":", 1)[0] for line in rows]
        assert row_names == watched
        assert "healthy:  55 (Δ+5)  | improved" in output.out
        if http_status is None:
            assert "shared:  40 (Δ-10) [!!]  | worsened" in output.out
            assert output.out.count("alias:  55 (Δ+5)  | improved") == 2
            assert output.err == ""
        else:
            assert output.out.count("alias:  55 (Δ—)  | no data") == 2
            assert "shared:  40 (Δ—)  | no data" in output.out
            assert output.err.splitlines() == [
                f"[WARN] {name}: failed to fetch history (HTTP {http_status})"
                for name in ("alias", "shared")
            ]


@pytest.mark.parametrize("verbosity", [0, 1, 2])
def test_reverse_completion_preserves_report_and_diagnostic_order(
    verbosity: int, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    leaderboard = parse_leaderboard({
        "success": True,
        "data": [
            {"name": name, "id": name, "currentScore": 55}
            for name in ("first", "second", "third")
        ],
    })
    completed: list[str] = []

    class ReadyFuture(Future[HistoryOutcome]):
        def result(self, timeout: float | None = None) -> HistoryOutcome:
            assert self.done(), "All tasks must be submitted before waiting"
            return super().result(timeout=0)

    class ReverseExecutor:
        def __init__(self, *, max_workers: int) -> None:
            assert max_workers == 3
            self.tasks: list[
                tuple[Callable[[str], HistoryOutcome], str, ReadyFuture]
            ] = []

        def submit(
            self, fn: Callable[[str], HistoryOutcome], model_id: str
        ) -> ReadyFuture:
            future = ReadyFuture()
            self.tasks.append((fn, model_id, future))
            if len(self.tasks) == 3:
                for task, task_id, result in reversed(self.tasks):
                    result.set_result(task(task_id))
                    completed.append(task_id)
            return future

        def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
            pass

    histories = {
        "first": HistoryData(scores=[50.0, 50.0], discarded_points=1),
        "second": HistoryData(scores=[60.0, 60.0], discarded_points=2),
        "third": HistoryData(scores=[55.0, 55.0], discarded_points=3),
    }
    monkeypatch.setattr("aimeter.cli.ThreadPoolExecutor", ReverseExecutor)
    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: leaderboard)
    monkeypatch.setattr("aimeter.cli.fetch_history", histories.__getitem__)

    assert run(["first", "second", "third"], verbosity=verbosity) == 0
    output = capsys.readouterr()
    assert completed == ["third", "second", "first"]
    positions = [output.out.index(f"{name}:") for name in ("first", "second", "third")]
    assert positions == sorted(positions)
    assert "first:  55 (Δ+5)  | improved  | 7d avg 50" in output.out
    assert "second:  55 (Δ-5)  | worsened  | 7d avg 60" in output.out
    assert "third:  55 (Δ+0)  | unchanged  | 7d avg 55" in output.out
    assert output.err.splitlines() == [
        f"[WARN] {name}: discarded history points: {count}"
        for count, name in enumerate(("first", "second", "third"), start=1)
    ]


def test_two_history_reads_can_be_in_flight_together(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    leaderboard = parse_leaderboard({
        "success": True,
        "data": [
            {"name": name, "id": name, "currentScore": 55}
            for name in ("first", "second")
        ],
    })
    started = {name: Event() for name in ("first", "second")}

    def fetch(model_id: str) -> HistoryData:
        assert current_thread() is not main_thread()
        started[model_id].set()
        other = "second" if model_id == "first" else "first"
        assert started[other].wait(timeout=5), "History reads ran sequentially"
        return HistoryData(scores=[50.0, 50.0], discarded_points=0)

    monkeypatch.setattr("aimeter.cli.fetch_history", fetch)
    outcomes = collect_model_outcomes(leaderboard, ["first", "second"])

    assert [outcome.history.status for outcome in outcomes] == ["ok", "ok"]
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("phase", ["submit", "result"])
@pytest.mark.parametrize("error_type", [KeyboardInterrupt, RuntimeError])
def test_interruption_or_unexpected_error_requests_cancellation_of_queued_work(
    phase: str, error_type: type[BaseException], monkeypatch: pytest.MonkeyPatch,
) -> None:
    leaderboard = parse_leaderboard({
        "success": True,
        "data": [
            {"name": name, "id": name, "currentScore": 55}
            for name in ("first", "second", "third")
        ],
    })
    first: Future[HistoryOutcome] = Future()
    pending: Future[HistoryOutcome] = Future()
    executor = Mock(spec=ThreadPoolExecutor)
    error = error_type("interrupted")
    if phase == "submit":
        executor.submit.side_effect = [pending, error]
    else:
        first.set_exception(error)
        executor.submit.side_effect = [first, pending, Future()]
    monkeypatch.setattr("aimeter.cli.ThreadPoolExecutor", Mock(return_value=executor))

    with pytest.raises(error_type, match="interrupted"):
        collect_model_outcomes(leaderboard, ["first", "second", "third"])

    assert not pending.done()
    executor.shutdown.assert_called_once_with(wait=True, cancel_futures=True)


@pytest.mark.parametrize("stdout_tty", [False, True])
@pytest.mark.parametrize("stderr_tty", [False, True])
@pytest.mark.parametrize("verbosity", [0, 1, 2])
def test_progress_is_flushed_before_fetching_only_to_interactive_stderr(
    stdout_tty: bool, stderr_tty: bool, verbosity: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout, stderr = StringIO(), StringIO()
    monkeypatch.setattr(stdout, "isatty", lambda: stdout_tty)
    monkeypatch.setattr(stderr, "isatty", lambda: stderr_tty)
    flush = Mock(wraps=stderr.flush)
    monkeypatch.setattr(stderr, "flush", flush)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    progress = "[INFO] Fetching model histories…\n" if stderr_tty else ""
    leaderboard = parse_leaderboard({
        "success": True,
        "data": [{"name": "healthy", "id": "1", "currentScore": 55}],
    })

    def fetch(_model_id: str) -> HistoryData:
        assert stderr.getvalue() == progress
        assert stdout.getvalue() == ""
        assert flush.call_count == int(stderr_tty)
        return HistoryData(scores=[50.0, 50.0], discarded_points=0)

    monkeypatch.setattr("aimeter.cli.fetch_scores", lambda: leaderboard)
    monkeypatch.setattr("aimeter.cli.fetch_history", fetch)

    assert run(["healthy"], verbosity=verbosity) == 0
    assert "healthy:  55 (Δ+5)" in stdout.getvalue()
    assert "Fetching" not in stdout.getvalue()
    assert stderr.getvalue() == progress
