"""
Tests for the per-action debug logging added to sync_gdrive and
poster_renamerr.

These cover:
- The sync_gdrive run summary formatter (counters → human string).
- poster_renamerr.process_file logging a [ACTION] dest ← src debug
  line on every successful file operation, regardless of action_type.
- That a failed shutil operation does NOT emit the success debug line.
"""

from __future__ import annotations

from typing import List, Tuple

import pytest

from backend.modules.poster_renamerr import PosterRenamerr
from backend.modules.sync_gdrive import _format_counter_summary, _rclone_line_level
from backend.util.config import PosterRenamerrConfig
from backend.util.logger import Logger


class CapturingLogger:
    """Records every method call so tests can assert log-level + message."""

    def __init__(self):
        self.calls: List[Tuple[str, str]] = []

    def _record(self, level):
        def _log(msg, *a, **kw):
            self.calls.append((level, str(msg)))

        return _log

    def __getattr__(self, name):
        # Cover .info / .debug / .warning / .error / .heartbeat uniformly.
        return self._record(name)

    def get_adapter(self, *_a, **_kw):
        return self

    def lines(self, level: str) -> List[str]:
        return [msg for lvl, msg in self.calls if lvl == level]


# --- sync_gdrive _format_counter_summary ---


def test_summary_empty_counters_returns_no_changes_string():
    assert _format_counter_summary({}) == "already in sync, no changes"


def test_summary_all_zero_returns_no_changes_string():
    counters = {"copied": 0, "deleted": 0, "updated": 0, "renamed": 0}
    assert _format_counter_summary(counters) == "already in sync, no changes"


def test_summary_single_action_lists_count():
    assert _format_counter_summary({"copied": 3}) == "3 copied"


def test_summary_multiple_actions_joined_and_sorted():
    summary = _format_counter_summary(
        {"renamed": 1, "copied": 5, "deleted": 2, "updated": 0}
    )
    # sorted() over dict keys -> alphabetical order; zero-count actions dropped
    assert summary == "5 copied, 2 deleted, 1 renamed"


def test_summary_excludes_zero_counts():
    summary = _format_counter_summary({"copied": 2, "deleted": 0, "renamed": 4})
    assert "deleted" not in summary
    assert summary == "2 copied, 4 renamed"


# --- poster_renamerr.process_file debug logging ---


@pytest.fixture
def renamerr_with_capture():
    """A PosterRenamerr instance whose logger captures every call."""
    logger = CapturingLogger()
    module = PosterRenamerr(logger=logger)
    module.config = PosterRenamerrConfig()
    # CapturingLogger is what the module sees after .get_adapter() in __init__.
    return module, logger


def _seed_source_file(tmp_path, name: str = "src.jpg") -> str:
    src = tmp_path / name
    src.write_bytes(b"poster")
    return str(src)


def test_process_file_copy_logs_action_at_debug(renamerr_with_capture, tmp_path):
    module, logger = renamerr_with_capture
    src = _seed_source_file(tmp_path)
    dest = str(tmp_path / "dest.jpg")
    assert module.process_file(src, dest, "copy") is True
    debug_lines = logger.lines("debug")
    assert any(f"[COPY] {dest} ← {src}" in line for line in debug_lines), debug_lines


def test_process_file_hardlink_logs_action_at_debug(renamerr_with_capture, tmp_path):
    module, logger = renamerr_with_capture
    src = _seed_source_file(tmp_path)
    dest = str(tmp_path / "hl.jpg")
    assert module.process_file(src, dest, "hardlink") is True
    assert any(
        f"[HARDLINK] {dest} ← {src}" in line for line in logger.lines("debug")
    )


def test_process_file_symlink_logs_action_at_debug(renamerr_with_capture, tmp_path):
    module, logger = renamerr_with_capture
    src = _seed_source_file(tmp_path)
    dest = str(tmp_path / "ln.jpg")
    assert module.process_file(src, dest, "symlink") is True
    assert any(
        f"[SYMLINK] {dest} ← {src}" in line for line in logger.lines("debug")
    )


def test_process_file_move_logs_action_at_debug(renamerr_with_capture, tmp_path):
    module, logger = renamerr_with_capture
    src = _seed_source_file(tmp_path)
    dest = str(tmp_path / "moved.jpg")
    assert module.process_file(src, dest, "move") is True
    assert any(
        f"[MOVE] {dest} ← {src}" in line for line in logger.lines("debug")
    )


def test_process_file_failure_does_not_emit_success_debug(
    renamerr_with_capture, tmp_path
):
    """If the shutil op raises, the success debug line must not fire."""
    module, logger = renamerr_with_capture
    src = str(tmp_path / "missing.jpg")  # does not exist
    dest = str(tmp_path / "dest.jpg")
    assert module.process_file(src, dest, "copy") is False
    # The error path should log at ERROR, and there must be NO success debug.
    assert not any("[COPY]" in line for line in logger.lines("debug"))
    assert any("Error copying file" in line for line in logger.lines("error"))


def test_process_file_uses_action_verb_from_call(renamerr_with_capture, tmp_path):
    """The log prefix must match the action_type passed in, not be hardcoded."""
    module, logger = renamerr_with_capture
    src = _seed_source_file(tmp_path, "a.jpg")
    # Same source, two different action types — each should log its own verb.
    module.process_file(src, str(tmp_path / "c.jpg"), "copy")
    src2 = _seed_source_file(tmp_path, "b.jpg")
    module.process_file(src2, str(tmp_path / "h.jpg"), "hardlink")
    verbs = [line.split(" ", 1)[0] for line in logger.lines("debug")]
    assert "[COPY]" in verbs
    assert "[HARDLINK]" in verbs


# --- sync_gdrive verbose / heartbeat routing ---


def test_rclone_error_lines_always_go_to_error():
    """rclone errors must surface regardless of verbose."""
    assert _rclone_line_level("oh no", "ERROR", verbose=False) == "error"
    assert _rclone_line_level("oh no", "ERROR", verbose=True) == "error"


def test_rclone_stats_lines_always_heartbeat():
    """--stats progress lines (Transferred:/Checks:/Elapsed) are
    repetitive-by-design and must heartbeat even when verbose is on."""
    for line in (
        "Transferred:   	    1.136 GiB / 1.136 GiB, 100%, 2.303 MiB/s",
        "Checks:                 0 / 0, -",
        "Elapsed time:      9m22.0s",
    ):
        assert _rclone_line_level(line, "INFO", verbose=False) == "heartbeat"
        # Still heartbeat with verbose=True — these aren't per-file actions.
        assert _rclone_line_level(line, "INFO", verbose=True) == "heartbeat"


def test_rclone_per_file_action_lines_routing_honors_verbose():
    """The contract users care about: file action lines visible at INFO
    when verbose=True, suppressed under heartbeat otherwise."""
    for line in (
        "Hatchet (2006) {tmdb-11908}.jpg: Copied (new)",
        "Bostafari.jpg: Deleted",
        "Inception.jpg: Updated",
        "old.jpg: Renamed to new.jpg",
        "stale.jpg: Removed",
    ):
        assert (
            _rclone_line_level(line, "INFO", verbose=False) == "heartbeat"
        ), f"{line!r} should heartbeat when verbose=False"
        assert (
            _rclone_line_level(line, "INFO", verbose=True) == "info"
        ), f"{line!r} should info when verbose=True"


def test_rclone_other_lines_go_to_info():
    """One-off setup / completion lines aren't repetitive; always INFO."""
    for line in (
        "Local file system at /kometa/posters/CL2K/Bostafari: Checks finished",
        "Running all checks before starting transfers",
        "Some other notice from rclone",
    ):
        assert _rclone_line_level(line, "INFO", verbose=False) == "info"


# --- Logger level filtering ---


def test_logger_log_level_debug_emits_debug_records(tmp_path, monkeypatch):
    """log_level: debug must surface DEBUG records that log_level: info hides.

    Pins the Python logging contract: setLevel("DEBUG") includes DEBUG;
    setLevel("INFO") drops them. If a future refactor accidentally
    hard-codes INFO, this catches it.
    """
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    debug_logger = Logger(log_level="debug", module_name="logging_audit_debug")
    info_logger = Logger(log_level="info", module_name="logging_audit_info")
    # Internal stdlib logger.level is the standard for filtering.
    import logging as _logging

    assert debug_logger._logger.level == _logging.DEBUG
    assert info_logger._logger.level == _logging.INFO


def test_logger_heartbeat_lines_are_prefixed(tmp_path, monkeypatch):
    """heartbeat() prepends [hb] so the frontend's Hide-Heartbeat toggle
    can filter them. The user's earlier confusion ("I thought I should see
    every Copied line") was that without verbose, per-file rclone lines
    route through heartbeat and the UI hides the [hb]-tagged output.

    heartbeat() lives on ChubLoggerAdapter (returned by Logger.get_adapter),
    which is what every module actually uses via base_module.py.
    """
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    log = Logger(log_level="debug", module_name="logging_audit_hb")
    adapter = log.get_adapter("AUDIT")
    seen = []
    adapter.info = lambda msg, *a, **kw: seen.append(("info", msg))
    adapter.heartbeat("rclone progress")
    assert seen == [("info", "[hb] rclone progress")]
