"""backend.util.writable: where a write would land, and whether CHUB can make it."""

import errno
import os
import stat
import tempfile

import pytest

from backend.util.writable import nearest_existing_dir, writable_error


def test_a_writable_folder_passes_and_keeps_no_probe_file(tmp_path):
    refusal = writable_error(str(tmp_path / "new" / "deeper"))
    assert refusal is None
    assert list(tmp_path.iterdir()) == []


def test_nearest_existing_dir_climbs_past_missing_folders_and_files(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder")
    assert nearest_existing_dir(str(tmp_path / "a" / "b")) == str(tmp_path)
    assert nearest_existing_dir(str(blocker / "x")) == str(tmp_path)
    assert nearest_existing_dir(str(tmp_path)) == str(tmp_path)


@pytest.mark.parametrize(
    "code,strerror,hint",
    [
        (errno.EACCES, "Permission denied", "Check the volume's host path, and that the folder's owner matches PUID/PGID."),
        (errno.EROFS, "Read-only file system", "The volume is mounted read-only; set its access mode to read/write."),
        (errno.ENOSPC, "No space left on device", "The disk is full; free some space on it."),
        (errno.ENOTCONN, "Transport endpoint is not connected", "Check the volume's host path, and that its disk or mount is working."),
    ],
)
def test_the_refusal_names_the_fix_for_its_cause(tmp_path, monkeypatch, code, strerror, hint):
    def _refuse(*a, **k):
        raise OSError(code, strerror)

    monkeypatch.setattr(tempfile, "TemporaryFile", _refuse)
    st = os.stat(tmp_path)

    refusal = writable_error(str(tmp_path))

    assert (refusal.errno, refusal.strerror) == (
        code,
        f"Cannot create files in {tmp_path}: {strerror} (CHUB runs as "
        f"{os.getuid()}:{os.getgid()}; the folder is owned by {st.st_uid}:{st.st_gid}, "
        f"{stat.filemode(st.st_mode)}). {hint}",
    )
