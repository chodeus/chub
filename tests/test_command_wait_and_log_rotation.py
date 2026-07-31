"""Regressions for the 2026-07-31 log/command investigation.

Two independent production faults are pinned here:
  * upgradinatorr reported four Lidarr searches as failures while all four
    actually completed — the wait budget charged *arr queue time against the
    run timeout (arr.wait_for_command_result).
  * general.log grew to 296MB/2.4M lines because RotatingFileHandler was built
    without maxBytes, so doRollover() never fired (logger.rotation_namer +
    the size cap).
"""

import logging

import pytest

from backend.modules.upgradinatorr import (
    DEFERRED_OUTCOMES,
    Upgradinatorr,
    _BufferingLogger,
)
from backend.util import arr as arr_mod
from backend.util.arr import (
    COMMAND_COMPLETED,
    COMMAND_FAILED,
    COMMAND_QUEUE_TIMEOUT_SECONDS,
    COMMAND_TIMEOUT,
    COMMAND_UNREACHABLE,
    BaseARRClient,
)
from backend.util.logger import SafeFormatter, rotation_namer


class _Clock:
    """Stands in for the `time` module inside arr, so the waits below don't
    actually sleep. Swapped in as `arr.time` rather than by patching attributes
    on the stdlib module, which would replace sleep/monotonic process-wide."""

    def __init__(self) -> None:
        self.now = 0.0

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.now


class _Silent:
    def _noop(self, *_a, **_k):
        return None

    debug = info = warning = error = exception = _noop


def _client(responses, monkeypatch):
    """A BaseARRClient whose command polls return `responses` in order (the last
    entry repeats), with a virtual clock patched over arr's time module."""
    clock = _Clock()
    monkeypatch.setattr(arr_mod, "time", clock)

    client = BaseARRClient.__new__(BaseARRClient)
    # api_base is a read-only property derived from these two.
    client.url = "http://arr.test"
    client.api_version = "v1"
    client.logger = _Silent()
    client.instance_name = "lidarr_main"

    seq = list(responses)

    def fake_get(_endpoint):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    client.make_get_request = fake_get
    return client, clock


def test_long_queue_wait_then_success_is_not_a_timeout(monkeypatch):
    """The exact production case: command 1498341 sat queued for 9m52s, ran for
    4m45s, and completed. The old fixed 10-minute budget gave up 13s after it
    started running and reported a failure."""
    queued_polls = [{"status": "queued"}] * 200  # ~16 min of queue time
    running_polls = [{"status": "started"}] * 60  # ~5 min of run time
    client, clock = _client(
        queued_polls + running_polls + [{"status": "completed"}], monkeypatch
    )

    assert client.wait_for_command_result(1498341) == COMMAND_COMPLETED
    # Proves the wait ran well past the old 600s ceiling without bailing.
    assert clock.now > 600


def test_stuck_in_queue_past_the_queue_budget_defers(monkeypatch):
    client, _ = _client([{"status": "queued"}], monkeypatch)

    assert client.wait_for_command_result(7) == COMMAND_TIMEOUT


def test_queue_budget_is_not_charged_to_a_running_command(monkeypatch):
    """A command that starts just under the queue budget still gets its own full
    run budget rather than inheriting an already-exhausted clock."""
    almost = int(COMMAND_QUEUE_TIMEOUT_SECONDS / 5) - 2
    client, clock = _client(
        [{"status": "queued"}] * almost
        + [{"status": "started"}] * 100
        + [{"status": "completed"}],
        monkeypatch,
    )

    assert client.wait_for_command_result(9) == COMMAND_COMPLETED
    assert clock.now > COMMAND_QUEUE_TIMEOUT_SECONDS


def test_unreachable_instance_gives_up_instead_of_burning_the_budget(monkeypatch):
    client, clock = _client([None], monkeypatch)

    assert client.wait_for_command_result(11) == COMMAND_UNREACHABLE
    # Bails on consecutive errors, not after the full hour-long queue budget.
    assert clock.now < COMMAND_QUEUE_TIMEOUT_SECONDS


@pytest.mark.parametrize("status", ["failed", "aborted", "cancelled", "orphaned"])
def test_terminal_failures_are_reported_as_failures(status, monkeypatch):
    client, _ = _client([{"status": status}], monkeypatch)

    assert client.wait_for_command_result(13) == COMMAND_FAILED


def test_wait_for_command_bool_wrapper_still_works(monkeypatch):
    client, _ = _client([{"status": "completed"}], monkeypatch)
    assert client.wait_for_command(15) is True

    client, _ = _client([{"status": "failed"}], monkeypatch)
    assert client.wait_for_command(16) is False


def test_deferred_outcomes_are_not_counted_as_failures():
    stats = {}
    for outcome in DEFERRED_OUTCOMES:
        Upgradinatorr._record_search_attempt(stats, outcome)

    assert stats["searches_deferred"] == len(DEFERRED_OUTCOMES)
    assert stats.get("searches_failed", 0) == 0
    assert Upgradinatorr._deferred_count(stats) == len(DEFERRED_OUTCOMES)


def test_completed_and_failed_outcomes_still_counted():
    stats = {}
    Upgradinatorr._record_search_attempt(stats, COMMAND_COMPLETED)
    Upgradinatorr._record_search_attempt(stats, COMMAND_FAILED)

    assert stats["searches_succeeded"] == 1
    assert stats["searches_failed"] == 1
    assert stats["searches_attempted"] == 2


@pytest.mark.parametrize(
    "default_name,expected",
    [
        ("/logs/general/general.log.1", "/logs/general/general.1.log"),
        ("/logs/general/general.log.9", "/logs/general/general.9.log"),
        ("/appdata/my.logs/general.log.2", "/appdata/my.logs/general.2.log"),
        ("/logs/general/general.log", "/logs/general/general.log"),
    ],
)
def test_rotation_namer_keeps_files_matching_the_star_dot_log_glob(
    default_name, expected
):
    """prune_old_logs() and the log viewer both rglob('*.log'); the stdlib's
    default '<base>.log.N' naming escapes that glob entirely."""
    assert rotation_namer(default_name) == expected
    if expected.endswith(".log"):
        assert expected.rsplit("/", 1)[-1].endswith(".log")


def test_size_cap_is_set_so_rollover_can_fire():
    from backend.util.logger import _max_log_bytes

    # maxBytes=0 is the stdlib default and means "never roll over" — the bug.
    assert _max_log_bytes() > 0


@pytest.mark.parametrize("raw", ["-1", "not-a-number", "10MB"])
def test_unusable_log_size_cap_falls_back_instead_of_disabling_rollover(
    raw, monkeypatch
):
    """A negative or malformed LOG_MAX_BYTES must not collapse to 0, which is the
    documented "no cap" opt-out and would restore unbounded growth."""
    from backend.util.logger import DEFAULT_MAX_LOG_BYTES, _max_log_bytes

    monkeypatch.setenv("LOG_MAX_BYTES", raw)

    assert _max_log_bytes() == DEFAULT_MAX_LOG_BYTES


def test_explicit_zero_still_disables_the_cap(monkeypatch):
    from backend.util.logger import _max_log_bytes

    monkeypatch.setenv("LOG_MAX_BYTES", "0")

    assert _max_log_bytes() == 0


@pytest.mark.parametrize("raw", ["30m", "", "0", "-5", "abc"])
def test_command_budget_env_never_raises_at_import(raw, monkeypatch):
    """These are read at module import, so a bad value would take down every
    importer of backend.util.arr rather than just degrading one setting."""
    from backend.util.arr import _positive_int_env

    monkeypatch.setenv("ARR_COMMAND_QUEUE_TIMEOUT", raw)

    assert _positive_int_env("ARR_COMMAND_QUEUE_TIMEOUT", 3600) == 3600


def test_command_budget_env_honours_a_valid_override(monkeypatch):
    from backend.util.arr import _positive_int_env

    monkeypatch.setenv("ARR_COMMAND_QUEUE_TIMEOUT", "900")

    assert _positive_int_env("ARR_COMMAND_QUEUE_TIMEOUT", 3600) == 900


def test_buffered_logs_keep_their_original_event_time():
    """upgradinatorr buffers log calls and replays them at the end of the run;
    without orig_created every line of a 49-minute run reads as the flush time."""
    buffered = _BufferingLogger()
    buffered.info("early event")

    captured = []

    class _Capture:
        def info(self, msg, *args, **kwargs):
            captured.append((msg, kwargs))

    buffered.flush_to(_Capture())

    assert len(captured) == 1
    msg, kwargs = captured[0]
    assert msg == "early event"
    assert "orig_created" in kwargs["extra"]


def test_formatter_renders_the_original_event_time():
    formatter = SafeFormatter(
        fmt="%(asctime)s %(levelname)s %(source_tag)s[%(filename)s]: %(message)s",
        datefmt="%d/%m/%Y %H:%M:%S",
    )
    record = logging.LogRecord(
        name="upgradinatorr",
        level=logging.ERROR,
        pathname="arr.py",
        lineno=1,
        msg="Command 1498341 timed out",
        args=(),
        exc_info=None,
    )
    flush_time = record.created
    record.orig_created = flush_time - 2937  # the run's real 48m57s span

    rendered = formatter.format(record)

    assert formatter.formatTime(record, formatter.datefmt) in rendered
    assert record.created == flush_time - 2937
