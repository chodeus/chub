"""Tests for backend/util/maintenance.py — log pruning + backup retention."""

import time
from unittest.mock import MagicMock

from backend.util.config import ChubConfig
from backend.util.maintenance import prune_old_backups, prune_old_logs


def _allowing(root):
    """A config whose allowed roots cover `root`, so prune may delete under it."""
    config = ChubConfig()
    config.poster_renamerr.source_dirs = [str(root)]
    return config


def _touch(path, age_days=0):
    path.write_text("x")
    if age_days:
        old = time.time() - age_days * 86400
        import os

        os.utime(path, (old, old))


def test_prune_old_logs_disabled_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    (tmp_path / "mod").mkdir()
    _touch(tmp_path / "mod" / "mod.log", age_days=99)
    # retention 0 = disabled, nothing removed
    assert prune_old_logs(0, MagicMock()) == 0
    assert (tmp_path / "mod" / "mod.log").exists()


def test_prune_old_logs_removes_only_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    mod = tmp_path / "mod"
    mod.mkdir()
    fresh = mod / "mod.log"
    stale = mod / "mod.1.log"
    _touch(fresh, age_days=1)
    _touch(stale, age_days=30)

    removed = prune_old_logs(14, MagicMock())
    assert removed == 1
    assert fresh.exists()
    assert not stale.exists()


def test_prune_old_backups_keeps_newest(tmp_path):
    """Only the newest `keep` archives survive a prune."""
    for i in range(5):
        f = tmp_path / f"chub-backup-2026010{i}-000000.zip"
        _touch(f, age_days=5 - i)  # i=0 oldest, i=4 newest

    removed = prune_old_backups(
        tmp_path, keep=2, config=_allowing(tmp_path), logger=MagicMock()
    )
    assert removed == 3
    remaining = sorted(p.name for p in tmp_path.glob("chub-backup-*.zip"))
    # Newest two (i=3, i=4) survive
    assert remaining == [
        "chub-backup-20260103-000000.zip",
        "chub-backup-20260104-000000.zip",
    ]


def test_prune_old_backups_keep_zero_is_noop(tmp_path):
    """keep=0 disables pruning entirely."""
    _touch(tmp_path / "chub-backup-20260101-000000.zip")
    assert (
        prune_old_backups(
            tmp_path, keep=0, config=_allowing(tmp_path), logger=MagicMock()
        )
        == 0
    )
    assert list(tmp_path.glob("chub-backup-*.zip"))
