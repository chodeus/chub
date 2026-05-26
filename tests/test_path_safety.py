"""Tests for backend/util/path_safety.py — filesystem access guard."""


from backend.util.path_safety import (
    _discover_container_mounts,
    get_allowed_roots,
    get_browse_roots,
    is_path_allowed,
)


def test_empty_config_has_only_config_dir(empty_config, tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    roots = get_allowed_roots(empty_config)
    assert any(str(r).startswith(str(tmp_path.resolve())) for r in roots)


def test_configured_roots_are_returned(config_with_roots):
    config, tmp_path = config_with_roots
    roots = get_allowed_roots(config)
    resolved = {str(r) for r in roots}
    assert str((tmp_path / "posters_src").resolve()) in resolved
    assert str((tmp_path / "posters_dst").resolve()) in resolved
    assert str((tmp_path / "nohl_src").resolve()) in resolved
    assert str((tmp_path / "jdup_src").resolve()) in resolved


def test_nonexistent_roots_are_filtered(empty_config):
    """Non-existent paths should not appear in the allowed roots."""
    empty_config.poster_renamerr.source_dirs = ["/this/does/not/exist/anywhere"]
    roots = get_allowed_roots(empty_config)
    for r in roots:
        assert str(r) != "/this/does/not/exist/anywhere"


def test_is_path_allowed_for_inside_root(config_with_roots):
    config, tmp_path = config_with_roots
    inside = tmp_path / "posters_src" / "movie.jpg"
    inside.write_text("x")
    assert is_path_allowed(str(inside), config)


def test_is_path_allowed_rejects_outside_root(config_with_roots, tmp_path):
    config, _ = config_with_roots
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    # outside is not in any allowed root
    assert not is_path_allowed(str(outside / "x.jpg"), config)


def test_is_path_allowed_rejects_traversal(config_with_roots, tmp_path):
    config, tmp_path = config_with_roots
    # ../ escape from one root
    sneaky = str(tmp_path / "posters_src" / ".." / "elsewhere" / "x.jpg")
    # elsewhere doesn't exist but resolve should still escape
    assert not is_path_allowed(sneaky, config)


def test_is_path_allowed_rejects_null_byte(config_with_roots):
    config, _ = config_with_roots
    assert not is_path_allowed("/tmp/foo\x00.jpg", config)


def test_is_path_allowed_rejects_empty_string(config_with_roots):
    config, _ = config_with_roots
    assert not is_path_allowed("", config)


def test_is_path_allowed_rejects_non_string(config_with_roots):
    config, _ = config_with_roots
    assert not is_path_allowed(None, config)  # type: ignore[arg-type]
    assert not is_path_allowed(123, config)  # type: ignore[arg-type]


def test_nohl_source_dirs_with_object_form(empty_config, tmp_path):
    """Nohl source dirs can be NohlSourceDir(path=...) objects."""
    from backend.util.config import NohlConfig, NohlSourceDir

    src = tmp_path / "nohl_obj"
    src.mkdir()
    empty_config.nohl = NohlConfig(
        source_dirs=[NohlSourceDir(path=str(src), mode="resolve")]
    )

    roots = get_allowed_roots(empty_config)
    assert any(str(r) == str(src.resolve()) for r in roots)


# --- _discover_container_mounts ---


# Sample of /proc/self/mountinfo as it appears inside an Unraid docker
# container: pseudo-filesystems for /, /proc, /sys, /dev, /tmp, /var/log,
# plus five real user bind mounts that the picker should surface.
SAMPLE_MOUNTINFO = """\
1 0 0:21 / / rw,relatime - overlay overlay rw,lowerdir=/lower,upperdir=/upper
2 1 0:22 / /proc rw,nosuid,nodev,noexec - proc proc rw
3 1 0:23 / /sys rw,nosuid,nodev,noexec - sysfs sysfs ro
4 1 0:24 / /dev rw,nosuid - tmpfs tmpfs rw,size=65536k
5 1 8:1 /mnt/cache/appdata/chub /config rw,relatime master:1 - ext4 /dev/sda1 rw
6 1 8:1 /mnt/cache/appdata/kometa/assets /kometa rw,relatime master:1 - ext4 /dev/sda1 rw
7 1 8:1 /mnt/user/data/media /media rw,relatime master:1 - xfs /dev/sda2 rw
8 1 8:1 /mnt/user/data /data rw,relatime master:1 - xfs /dev/sda2 rw
9 1 8:1 /mnt/cache/appdata/plex /plex rw,relatime master:1 - btrfs /dev/sda3 rw
10 1 0:25 / /tmp rw,nosuid - tmpfs tmpfs rw,size=4G
11 1 0:26 / /var/log rw,relatime - tmpfs tmpfs rw
"""


def _write_mountinfo(tmp_path, content):
    p = tmp_path / "mountinfo"
    p.write_text(content)
    return str(p)


def test_discover_mounts_returns_user_binds(tmp_path):
    """Pseudo-fs and OS mount points are filtered; user binds remain."""
    path = _write_mountinfo(tmp_path, SAMPLE_MOUNTINFO)
    discovered = {str(p) for p in _discover_container_mounts(path)}
    assert discovered == {"/config", "/kometa", "/media", "/data", "/plex"}


def test_discover_mounts_missing_file_returns_empty(tmp_path):
    """macOS dev hosts have no mountinfo — must degrade silently."""
    assert _discover_container_mounts(str(tmp_path / "nope")) == []


def test_discover_mounts_skips_pseudo_fs_types(tmp_path):
    """Even if a pseudo-fs is mounted at a non-system path, drop it."""
    content = "1 0 0:21 / /custom rw - tmpfs tmpfs rw\n"
    path = _write_mountinfo(tmp_path, content)
    assert _discover_container_mounts(path) == []


def test_discover_mounts_skips_system_prefixes(tmp_path):
    """OS mount points (/usr, /var, /etc, ...) must never be surfaced."""
    content = (
        "1 0 8:1 / /usr/local rw - ext4 /dev/sda1 rw\n"
        "2 0 8:1 / /var/cache rw - ext4 /dev/sda1 rw\n"
        "3 0 8:1 / /etc/secret rw - ext4 /dev/sda1 rw\n"
    )
    path = _write_mountinfo(tmp_path, content)
    assert _discover_container_mounts(path) == []


def test_discover_mounts_handles_malformed_lines(tmp_path):
    """Truncated or missing-dash lines are skipped, not fatal."""
    content = (
        "garbage\n"
        "1 0 8:1 / /short\n"  # no " - " separator
        "2 1 8:1 / /good rw - ext4 /dev/sda1 rw\n"
    )
    path = _write_mountinfo(tmp_path, content)
    discovered = {str(p) for p in _discover_container_mounts(path)}
    assert discovered == {"/good"}


def test_discover_mounts_deduplicates(tmp_path):
    """If the same mount appears twice in mountinfo, only return it once."""
    content = (
        "1 0 8:1 / /data rw - ext4 /dev/sda1 rw\n"
        "2 0 8:1 / /data rw - ext4 /dev/sda1 rw\n"
    )
    path = _write_mountinfo(tmp_path, content)
    assert _discover_container_mounts(path) == [__import__("pathlib").Path("/data")]


# --- get_browse_roots ---


def test_browse_roots_drops_file_paths(empty_config, tmp_path):
    """Files (e.g. service-account .json) must not appear in the picker."""
    sa_file = tmp_path / "creds.json"
    sa_file.write_text("{}")
    empty_config.sync_gdrive.gdrive_sa_location = str(sa_file)
    browse = get_browse_roots(empty_config)
    assert sa_file.resolve() not in browse
    # but is_path_allowed still treats it as in-range for the write check
    assert is_path_allowed(str(sa_file), empty_config)


def test_browse_roots_collapses_nested_paths(empty_config, tmp_path):
    """A child directory should be collapsed into its allowed ancestor."""
    from backend.util.config import GDriveListEntry

    outer = tmp_path / "kometa"
    inner = outer / "posters" / "MM2K" / "Mario"
    inner.mkdir(parents=True)
    # poster_renamerr is the outer root; gdrive_list points deep inside it.
    empty_config.poster_renamerr.source_dirs = [str(outer)]
    empty_config.sync_gdrive.gdrive_list = [
        GDriveListEntry(id="x", name="Mario", location=str(inner))
    ]
    browse = get_browse_roots(empty_config)
    paths = {str(p) for p in browse}
    assert str(outer.resolve()) in paths
    assert str(inner.resolve()) not in paths


def test_browse_roots_keeps_distinct_top_levels(empty_config, tmp_path):
    """Two independent roots should both appear."""
    a = tmp_path / "kometa"
    b = tmp_path / "data"
    a.mkdir()
    b.mkdir()
    empty_config.poster_renamerr.source_dirs = [str(a)]
    empty_config.nohl.source_dirs = [str(b)]
    paths = {str(p) for p in get_browse_roots(empty_config)}
    assert str(a.resolve()) in paths
    assert str(b.resolve()) in paths


def test_browse_roots_empty_when_no_config(empty_config, monkeypatch, tmp_path):
    """A config that points nowhere returns no browse roots (CONFIG_DIR aside)."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "nope"))  # doesn't exist
    assert get_browse_roots(empty_config) == []


def test_get_allowed_roots_includes_gdrive_list(empty_config, tmp_path):
    """Configured gdrive_list[*].location paths should appear in allowed roots."""
    from backend.util.config import GDriveListEntry

    location = tmp_path / "kometa_posters"
    location.mkdir()
    empty_config.sync_gdrive.gdrive_list = [
        GDriveListEntry(id="abc123", name="Test", location=str(location))
    ]
    roots = get_allowed_roots(empty_config)
    assert any(str(r) == str(location.resolve()) for r in roots)
