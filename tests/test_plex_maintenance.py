"""Tests for backend/modules/plex_maintenance.py — dry_run gating and
PhotoTranscoder cleanup accounting."""

import os
import shutil
import threading
from types import SimpleNamespace

from backend.modules.plex_maintenance import PlexMaintenance
from backend.util import plex_metadata
from backend.util.plex_metadata import scan_transcoder_cache


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


def test_photo_transcoder_skips_synology_metadata_and_links(tmp_path):
    cache_dir = _make_cache(tmp_path, n_files=1, size=10)
    synology = cache_dir / "@eaDir" / "f0.jpg" / "SYNOPHOTO_THUMB_S.jpg"
    synology.parent.mkdir(parents=True)
    synology.write_bytes(b"y" * 5)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"z" * 100)
    link = cache_dir / "link.jpg"
    link.symlink_to(outside)
    m = make_module(plex_path=str(tmp_path))

    # The size shown on the page and the cleanup walk the same files.
    scan = scan_transcoder_cache(str(tmp_path), force=True)
    stats = m._clean_photo_transcoder()

    assert (scan["count"], scan["size_bytes"]) == (1, 10)
    assert stats == {"count": 1, "total_size": 10}
    assert synology.exists()
    assert link.is_symlink()
    assert outside.exists()


def test_photo_transcoder_refuses_a_linked_cache_folder(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep.jpg").write_bytes(b"x" * 10)
    (tmp_path / "Cache").mkdir()
    (tmp_path / "Cache" / "PhotoTranscoder").symlink_to(elsewhere, target_is_directory=True)
    m = make_module(plex_path=str(tmp_path))

    scan = scan_transcoder_cache(str(tmp_path), force=True)
    stats = m._clean_photo_transcoder()

    assert (scan["count"], stats) == (0, {"count": 0, "total_size": 0})
    assert (elsewhere / "keep.jpg").exists()
    assert any(msg[0] == "warning" and "symlink" in msg[1] for msg in m.logger.msgs)


def test_photo_transcoder_rechecks_each_file_before_removing(tmp_path, monkeypatch):
    cache_dir = _make_cache(tmp_path, n_files=1, size=10)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f0.jpg").write_bytes(b"keep")
    real_files = plex_metadata.transcoder_files

    def folder_swapped_after_listing(*args, **kwargs):
        for path, size in real_files(*args, **kwargs):
            shutil.rmtree(cache_dir)
            cache_dir.symlink_to(outside, target_is_directory=True)
            yield path, size

    monkeypatch.setattr(plex_metadata, "transcoder_files", folder_swapped_after_listing)
    stats = make_module(plex_path=str(tmp_path))._clean_photo_transcoder()

    assert stats == {"count": 0, "total_size": 0}
    assert (outside / "f0.jpg").read_bytes() == b"keep"


def test_transcoder_walk_checks_cancel_in_folders_without_files(tmp_path):
    for i in range(3):
        (tmp_path / "Cache" / "PhotoTranscoder" / f"{i:02x}").mkdir(parents=True)
    asked = []

    def cancel_on_third_folder():
        asked.append(1)
        return len(asked) == 3

    files = list(plex_metadata.transcoder_files(str(tmp_path), cancel_on_third_folder))

    assert (files, len(asked)) == ([], 3)


def test_photo_transcoder_stops_mid_folder_when_cancelled(tmp_path, monkeypatch):
    cache_dir = _make_cache(tmp_path, n_files=3, size=10)
    m = make_module(plex_path=str(tmp_path))
    m._cancel_event = threading.Event()
    real_remove = os.remove

    def remove_then_cancel(path):
        real_remove(path)
        m._cancel_event.set()

    monkeypatch.setattr(os, "remove", remove_then_cancel)
    stats = m._clean_photo_transcoder()

    assert stats == {"count": 1, "total_size": 10}
    assert len(list(cache_dir.iterdir())) == 2


def test_photo_transcoder_file_plex_removed_first_is_not_an_error(tmp_path, monkeypatch):
    _make_cache(tmp_path, n_files=3, size=10)
    m = make_module(plex_path=str(tmp_path))
    real_remove = os.remove

    def plex_got_there_first(path):
        real_remove(path)
        if path.endswith("f1.jpg"):
            raise FileNotFoundError(path)

    monkeypatch.setattr(os, "remove", plex_got_there_first)
    stats = m._clean_photo_transcoder()

    assert stats == {"count": 2, "total_size": 20}
    assert [msg for msg in m.logger.msgs if msg[0] == "error"] == []
    assert not any("f1.jpg" in msg[1] for msg in m.logger.msgs if msg[0] == "debug")


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
