"""backend.util.writable: where a write would land, and whether CHUB can make it."""

import errno
import os
import stat
import tempfile

import pytest

from backend.util.writable import destination_refused, nearest_existing_dir, writable_error


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
        (errno.EROFS, "Read-only file system", "The folder is on a read-only mount: set the volume to read/write, or check the disk if it went read-only on errors."),
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


@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EDQUOT, errno.EROFS])
def test_a_full_or_read_only_disk_is_always_the_destination(tmp_path, code):
    refused = destination_refused(OSError(code, "refused"), str(tmp_path / "logo.png"))
    assert refused is True


@pytest.mark.parametrize(
    "code", [errno.ENOENT, errno.EACCES, errno.EROFS], ids=["missing", "unreadable", "read-only"]
)
def test_an_error_naming_only_the_source_is_not_the_destination(tmp_path, code):
    dest = str(tmp_path / "kometa" / "logo.png")
    src = str(tmp_path / "posters" / "Dune - Logo.png")
    refused = destination_refused(OSError(code, "refused", src), dest)
    assert refused is False


def test_a_denied_write_to_the_destination_file_is_the_destination(tmp_path):
    dest = str(tmp_path / "logo.png")
    refused = destination_refused(OSError(errno.EACCES, "Permission denied", dest), dest)
    assert refused is True


@pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")
def test_a_link_its_folder_refuses_is_the_destination(tmp_path):
    folder = tmp_path / "Dune (2021)"
    folder.mkdir()
    src = tmp_path / "src.png"
    src.write_bytes(b"png")
    folder.chmod(0o555)
    try:
        with pytest.raises(OSError) as raised:
            os.link(src, folder / "logo.png.chub-tmp")
        refused = destination_refused(raised.value, str(folder / "logo.png"))
    finally:
        folder.chmod(0o755)
    assert (raised.value.errno, refused) == (errno.EACCES, True)
