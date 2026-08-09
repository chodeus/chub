"""Concurrent uploads to one Drive folder must not create duplicate names.

rclone decides create-vs-replace by listing the destination first, and Drive
permits two files sharing a name — so two overlapping uploads both see "absent"
and both create. Reproduced against the real Drive before this fix: sequential
uploads left 1 copy, concurrent uploads left 2.

The fake below models exactly that: a listing, then a create-or-replace, with a
window between them.
"""

import threading
import time
import types

from backend.util.cl2k import gdrive_upload as gd


class FakeDrive:
    """A folder where create-vs-replace is decided by a listing, with a real
    gap between the check and the write — the shape that duplicates."""

    def __init__(self, gap=0.05):
        self.files = []  # names; a list, not a set — Drive allows duplicates
        self.gap = gap
        self._mutex = threading.Lock()

    def rclone_copy(self, name):
        present = name in self.files  # check
        time.sleep(self.gap)  # ...window...
        with self._mutex:
            if not present:
                self.files.append(name)  # create (duplicates if two got here)

    def count(self, name):
        return sum(1 for n in self.files if n == name)


def _install(monkeypatch, drive, name="poster.png"):
    """Point upload_file's subprocess at the fake, keeping the real locking."""
    monkeypatch.setattr(gd, "_rclone_path", lambda: "/usr/bin/rclone")
    monkeypatch.setattr(gd, "_ensure_remote", lambda _r: None)
    monkeypatch.setattr(gd, "_upload_auth_args", lambda _c: ["--drive-token", "x"])
    monkeypatch.setattr(
        gd, "list_files", lambda fid, cfg, log, strict=False: list(drive.files)
    )

    def fake_run(cmd, **kw):
        if "copy" in cmd:
            drive.rclone_copy(name)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(gd.subprocess, "run", fake_run)


def _logger():
    noop = lambda *a, **k: None  # noqa: E731
    return types.SimpleNamespace(debug=noop, info=noop, warning=noop, error=noop)


def _upload_twice_concurrently(folder="folder-A", path="/tmp/poster.png"):
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()  # maximise overlap
        gd.upload_file(path, folder, object(), _logger())

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_the_fake_reproduces_the_duplicate_without_the_lock(monkeypatch):
    """Guard the guard: if this ever passes, the fake stopped modelling the bug
    and the test below would prove nothing."""
    drive = FakeDrive()
    _install(monkeypatch, drive)
    monkeypatch.setattr(gd, "_folder_lock", lambda _f: threading.Lock())  # useless lock
    _upload_twice_concurrently()
    assert drive.count("poster.png") == 2


def test_concurrent_uploads_to_one_folder_leave_a_single_copy(monkeypatch):
    drive = FakeDrive()
    _install(monkeypatch, drive)
    _upload_twice_concurrently()
    assert drive.count("poster.png") == 1


def test_different_folders_still_upload_in_parallel(monkeypatch):
    """The lock is per folder, so unrelated destinations must not serialise."""
    assert gd._folder_lock("folder-A") is gd._folder_lock("folder-A")
    assert gd._folder_lock("folder-A") is not gd._folder_lock("folder-B")


def test_a_preexisting_duplicate_is_reaped(monkeypatch):
    drive = FakeDrive()
    drive.files = ["poster.png", "poster.png"]  # e.g. written before this fix
    _install(monkeypatch, drive)
    deduped = []

    def fake_run(cmd, **kw):
        if "dedupe" in cmd:
            deduped.append(cmd)
            drive.files = ["poster.png"]
        elif "copy" in cmd:
            drive.rclone_copy("poster.png")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(gd.subprocess, "run", fake_run)
    gd.upload_file("/tmp/poster.png", "folder-A", object(), _logger())
    assert deduped, "an existing duplicate should trigger a dedupe"
    assert "newest" in deduped[0], "must keep the newest, i.e. the copy just uploaded"
    assert drive.count("poster.png") == 1


def test_no_duplicate_means_no_destructive_command(monkeypatch):
    """The normal path must never run dedupe — it deletes."""
    drive = FakeDrive()
    _install(monkeypatch, drive)
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        if "copy" in cmd:
            drive.rclone_copy("poster.png")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(gd.subprocess, "run", fake_run)
    gd.upload_file("/tmp/poster.png", "folder-A", object(), _logger())
    assert not any("dedupe" in c for c in seen)


def test_a_rename_serialises_against_an_upload_to_the_same_folder(monkeypatch):
    """move_file is the folder's other writer (the poster healer renames while
    the maker uploads), so it has to take the same lock or the convention only
    covers half the writers."""
    drive = FakeDrive()
    _install(monkeypatch, drive)
    order = []

    def fake_run(cmd, **kw):
        op = "moveto" if "moveto" in cmd else "copy"
        order.append("%s-start" % op)
        time.sleep(0.05)
        order.append("%s-end" % op)
        if op == "copy":
            drive.rclone_copy("poster.png")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(gd.subprocess, "run", fake_run)
    barrier = threading.Barrier(2)

    def up():
        barrier.wait()
        gd.upload_file("/tmp/poster.png", "folder-A", object(), _logger())

    def mv():
        barrier.wait()
        gd.move_file("old.png", "poster.png", "folder-A", object(), _logger())

    ts = [threading.Thread(target=up), threading.Thread(target=mv)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # Never interleaved: each write finishes before the other starts.
    assert order[0].endswith("-start") and order[1].endswith("-end")
    assert order[1].split("-")[0] == order[0].split("-")[0]


def test_a_failed_duplicate_check_does_not_fail_the_upload(monkeypatch):
    drive = FakeDrive()
    _install(monkeypatch, drive)
    monkeypatch.setattr(
        gd, "list_files", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("api down"))
    )
    gd.upload_file("/tmp/poster.png", "folder-A", object(), _logger())
    assert drive.count("poster.png") == 1
