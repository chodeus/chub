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
from backend.modules.sync_gdrive import _format_counter_summary
from backend.util.config import PosterRenamerrConfig


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
