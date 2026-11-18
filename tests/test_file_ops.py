"""file_ops on a real filesystem: what lands at the destination, and what stays at the source."""

import errno
import os

import pytest

from backend.util import file_ops
from backend.util.file_ops import copy_into_place, link_into_place, move_into_place

_SKIP_AS_ROOT = pytest.mark.skipif(os.getuid() == 0, reason="root writes to a 0o555 folder")


def _folders(tmp_path):
    src_dir, dest_dir = tmp_path / "posters", tmp_path / "kometa"
    src_dir.mkdir()
    dest_dir.mkdir()
    src = src_dir / "a.png"
    src.write_bytes(b"img")
    return src_dir, src, dest_dir, dest_dir / "a.png"


def _rename_crosses_volumes(monkeypatch, src):
    """Docker gives EXDEV for a rename between two bind mounts, even on one disk."""
    real_replace = os.replace

    def _replace(a, b, *args, **kw):
        if a == str(src):
            raise OSError(errno.EXDEV, os.strerror(errno.EXDEV), a, None, b)
        return real_replace(a, b, *args, **kw)

    monkeypatch.setattr(os, "replace", _replace)


def test_a_move_in_one_volume_replaces_the_destination_and_leaves_no_source(tmp_path):
    src_dir, src, dest_dir, dest = _folders(tmp_path)
    dest.write_bytes(b"old")
    kept = move_into_place(str(src), str(dest))
    assert kept is None
    assert (os.listdir(src_dir), os.listdir(dest_dir), dest.read_bytes()) == ([], ["a.png"], b"img")


def test_a_move_across_volumes_copies_then_deletes_the_source(tmp_path, monkeypatch):
    src_dir, src, dest_dir, dest = _folders(tmp_path)
    _rename_crosses_volumes(monkeypatch, src)
    kept = move_into_place(str(src), str(dest))
    assert kept is None
    assert (os.listdir(src_dir), os.listdir(dest_dir), dest.read_bytes()) == ([], ["a.png"], b"img")


@_SKIP_AS_ROOT
def test_a_move_from_a_read_only_folder_lands_and_says_why_the_source_stayed(tmp_path):
    src_dir, src, dest_dir, dest = _folders(tmp_path)
    dest.write_bytes(b"old")
    src_dir.chmod(0o555)
    try:
        kept = move_into_place(str(src), str(dest))
    finally:
        src_dir.chmod(0o755)
    assert (kept.errno, kept.filename) == (errno.EACCES, str(src))
    assert (os.listdir(dest_dir), dest.read_bytes(), src.read_bytes()) == (["a.png"], b"img", b"img")


@_SKIP_AS_ROOT
def test_a_move_into_a_folder_it_cannot_write_raises_and_keeps_both_files(tmp_path):
    _src_dir, src, dest_dir, dest = _folders(tmp_path)
    dest.write_bytes(b"old")
    dest_dir.chmod(0o555)
    try:
        with pytest.raises(PermissionError):
            move_into_place(str(src), str(dest))
    finally:
        dest_dir.chmod(0o755)
    assert (src.read_bytes(), os.listdir(dest_dir), dest.read_bytes()) == (b"img", ["a.png"], b"old")


def test_a_source_someone_else_deleted_mid_move_is_not_reported_as_kept(tmp_path, monkeypatch):
    _src_dir, src, _dest_dir, dest = _folders(tmp_path)
    _rename_crosses_volumes(monkeypatch, src)
    real_copy = file_ops._copy

    def _copy_then_lose_source(a, tmp, *meta):
        real_copy(a, tmp, *meta)
        os.remove(a)

    monkeypatch.setattr(file_ops, "_copy", _copy_then_lose_source)
    kept = move_into_place(str(src), str(dest))
    assert kept is None
    assert dest.read_bytes() == b"img"


def test_a_move_across_volumes_keeps_the_files_times(tmp_path, monkeypatch):
    _src_dir, src, _dest_dir, dest = _folders(tmp_path)
    os.utime(src, (1_000_000, 1_000_000))
    _rename_crosses_volumes(monkeypatch, src)
    kept = move_into_place(str(src), str(dest))
    assert kept is None
    assert os.stat(dest).st_mtime == 1_000_000


def test_a_failed_copy_leaves_the_destination_whole(tmp_path):
    dest = tmp_path / "a.png"
    dest.write_bytes(b"old")
    with pytest.raises(FileNotFoundError):
        copy_into_place(str(tmp_path / "missing.png"), str(dest))
    assert (os.listdir(tmp_path), dest.read_bytes()) == (["a.png"], b"old")


def test_relinking_a_file_already_hardlinked_there_leaves_only_the_link(tmp_path):
    _src_dir, src, dest_dir, dest = _folders(tmp_path)
    link_into_place(str(src), str(dest))
    link_into_place(str(src), str(dest))
    assert (os.listdir(dest_dir), os.path.samefile(src, dest)) == (["a.png"], True)


def test_a_move_onto_a_hard_link_of_the_source_deletes_the_source(tmp_path):
    src_dir, src, dest_dir, dest = _folders(tmp_path)
    os.link(src, dest)
    kept = move_into_place(str(src), str(dest))
    assert (kept, os.listdir(src_dir), dest.read_bytes()) == (None, [], b"img")


@pytest.mark.parametrize("spelling", ["{d}/a.png", "{d}/../posters/a.png"])
def test_a_move_onto_its_own_path_keeps_the_file(tmp_path, spelling):
    src_dir, src, _dest_dir, _dest = _folders(tmp_path)
    kept = move_into_place(str(src), spelling.format(d=src_dir))
    assert (kept, src.read_bytes()) == (None, b"img")


@pytest.mark.parametrize("place", [copy_into_place, link_into_place, file_ops.symlink_into_place])
@pytest.mark.parametrize("spelling", ["{d}/a.png", "{d}/../posters/a.png"])
def test_placing_a_file_onto_its_own_path_keeps_the_file(tmp_path, place, spelling):
    src_dir, src, _dest_dir, _dest = _folders(tmp_path)
    place(str(src), spelling.format(d=src_dir))
    assert (src.is_symlink(), os.listdir(src_dir)) == (False, ["a.png"])
    assert src.read_bytes() == b"img"


@pytest.mark.parametrize("onto_itself", [False, True])
def test_a_move_of_a_link_places_its_bytes_and_leaves_its_target(tmp_path, onto_itself):
    src_dir, target, _dest_dir, dest = _folders(tmp_path)
    link = dest if onto_itself else src_dir / "link.png"
    os.symlink(target, link)
    kept = move_into_place(str(link), str(dest))
    assert (kept, dest.is_symlink(), dest.read_bytes(), target.read_bytes()) == (None, False, b"img", b"img")
    assert os.path.lexists(link) is onto_itself


def test_a_move_onto_a_symlink_to_the_source_puts_the_file_there(tmp_path):
    src_dir, src, dest_dir, dest = _folders(tmp_path)
    os.symlink(src, dest)
    kept = move_into_place(str(src), str(dest))
    assert (kept, os.listdir(src_dir), dest.is_symlink(), dest.read_bytes()) == (None, [], False, b"img")


@pytest.mark.parametrize(
    ("make_dest", "action_type", "expected"),
    [
        ("own path", "move", True),
        ("copy", "move", True),
        ("hard link", "move", False),
        ("symlink", "move", False),
        ("hard link", "copy", True),
    ],
)
def test_only_a_move_onto_a_link_to_its_source_is_not_already_in_place(tmp_path, make_dest, action_type, expected):
    src_dir, src, _dest_dir, dest = _folders(tmp_path)
    if make_dest == "own path":
        dest = src_dir / "a.png"
    elif make_dest == "copy":
        dest.write_bytes(b"img")
    else:
        (os.link if make_dest == "hard link" else os.symlink)(src, dest)
    assert file_ops.already_in_place(str(src), str(dest), action_type) is expected


def test_a_destination_with_the_same_size_and_time_but_other_bytes_is_not_already_in_place(tmp_path):
    _src_dir, src, _dest_dir, dest = _folders(tmp_path)
    dest.write_bytes(b"new")
    st = os.stat(src)
    os.utime(dest, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert file_ops.already_in_place(str(src), str(dest), "copy") is False


def test_a_copy_without_keep_mode_gets_a_new_files_mode(tmp_path, umask_022):
    _src_dir, src, _dest_dir, dest = _folders(tmp_path)
    src.chmod(0o600)
    copy_into_place(str(src), str(dest), keep_mode=False)
    assert oct(dest.stat().st_mode & 0o777) == oct(0o644)
