"""Tests for backend/modules/plex_maintenance.py — dry_run gating and
PhotoTranscoder cleanup accounting."""

import os
from types import SimpleNamespace

from backend.modules.plex_maintenance import PlexMaintenance


class StubLogger:
    def __init__(self):
        self.msgs = []

    def debug(self, *a, **kw):
        self.msgs.append(("debug",) + a)

    def info(self, *a, **kw):
        self.msgs.append(("info",) + a)

    def warning(self, *a, **kw):
        self.msgs.append(("warning",) + a)

    def error(self, *a, **kw):
        self.msgs.append(("error",) + a)


def make_module(plex_path="", dry_run=False):
    m = object.__new__(PlexMaintenance)
    m._cancel_event = None
    m.logger = StubLogger()
    m.plex_path = plex_path
    m.config = SimpleNamespace(
        log_level="info",
        dry_run=dry_run,
        plex_path=plex_path,
        empty_trash=False,
        clean_bundles=False,
        optimize_db=False,
        photo_transcoder=True,
        sleep=0,
        timeout=600,
        instances=[],
    )
    return m


def _make_cache(tmp_path, n_files=3, size=10):
    transcoder = tmp_path / "Cache" / "PhotoTranscoder" / "sub"
    transcoder.mkdir(parents=True)
    for i in range(n_files):
        (transcoder / f"f{i}.jpg").write_bytes(b"x" * size)
    return transcoder


def test_photo_transcoder_deletes_files(tmp_path):
    cache_dir = _make_cache(tmp_path, n_files=3, size=10)
    m = make_module(plex_path=str(tmp_path))
    stats = m._clean_photo_transcoder()
    assert stats == {"count": 3, "total_size": 30}
    assert list(cache_dir.iterdir()) == []


def test_photo_transcoder_dry_run_keeps_files(tmp_path):
    cache_dir = _make_cache(tmp_path, n_files=3, size=10)
    m = make_module(plex_path=str(tmp_path), dry_run=True)
    stats = m._clean_photo_transcoder()
    # Counts what it would delete, deletes nothing.
    assert stats == {"count": 3, "total_size": 30}
    assert len(list(cache_dir.iterdir())) == 3


def test_photo_transcoder_failed_delete_not_counted(tmp_path, monkeypatch):
    _make_cache(tmp_path, n_files=3, size=10)
    m = make_module(plex_path=str(tmp_path))

    real_remove = os.remove
    failed = []

    def flaky_remove(path):
        if path.endswith("f1.jpg"):
            failed.append(path)
            raise PermissionError("locked")
        real_remove(path)

    monkeypatch.setattr(os, "remove", flaky_remove)
    stats = m._clean_photo_transcoder()
    # The failed file must not be in the count or the byte total.
    assert failed
    assert stats == {"count": 2, "total_size": 20}


def test_maintenance_tasks_skipped_in_dry_run():
    m = make_module(dry_run=True)
    m.config.empty_trash = True
    m.config.clean_bundles = True

    calls = []
    plex_server = SimpleNamespace(
        library=SimpleNamespace(
            emptyTrash=lambda: calls.append("emptyTrash"),
            cleanBundles=lambda: calls.append("cleanBundles"),
            optimize=lambda: calls.append("optimize"),
        )
    )
    results = m._run_plex_maintenance(plex_server)
    assert calls == []
    assert results == {"Empty Trash": "dry run", "Clean Bundles": "dry run"}


def test_maintenance_tasks_run_without_dry_run():
    m = make_module(dry_run=False)
    m.config.empty_trash = True

    calls = []
    plex_server = SimpleNamespace(
        library=SimpleNamespace(emptyTrash=lambda: calls.append("emptyTrash"))
    )
    results = m._run_plex_maintenance(plex_server)
    assert calls == ["emptyTrash"]
    assert results == {"Empty Trash": "success"}
