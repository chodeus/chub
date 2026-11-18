"""Tests for poster_cleanarr stale-duplicate detection — a Kometa asset folder
whose {tvdb/tmdb} id matches a live media item but whose name != the item's
canonical folder (media_cache.folder). Safety: never remove the only copy."""

import os
from types import SimpleNamespace

import pytest

from backend.modules.poster_cleanarr import ORPHAN_RESTORE_DIR_NAME, PosterCleanarr
from backend.util.config import ChubConfig, ConfigError, InstanceDetail
from backend.util.database import ChubDB
from backend.util.path_safety import resolve_confined

def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


def _make(*allowed_roots):
    """Bare instance; `allowed_roots` seed the construction-time snapshot only."""
    m = object.__new__(PosterCleanarr)
    m.logger = _logger()
    m.full_config = ChubConfig()
    m.full_config.poster_renamerr.source_dirs = [str(r) for r in allowed_roots]
    return m


def _live(monkeypatch, *allowed_roots):
    """Point load_config at a config whose allowed roots are `allowed_roots`."""
    cfg = ChubConfig()
    cfg.poster_renamerr.source_dirs = [str(r) for r in allowed_roots]
    monkeypatch.setattr("backend.util.config.load_config", lambda: cfg)
    return cfg


def _collecting_logger():
    """(logger, errors) — the logger appends every error message to the list."""
    errors = []
    logger = _logger()
    logger.error = errors.append
    return logger, errors


@pytest.fixture
def db(tmp_path):
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as database:
        yield database


def _seed(
    db, instance, folder, tvdb=None, tmdb=None, season=None, plex_mapping_id=None
):
    db.media.execute_query(
        "INSERT INTO media_cache (identity_key, instance_name, folder, tvdb_id, "
        "tmdb_id, season_number, plex_mapping_id, asset_type, matched) "
        "VALUES (?,?,?,?,?,?,?,?,1)",
        (
            f"{instance}|{folder}|{season}",
            instance,
            folder,
            tvdb,
            tmdb,
            season,
            plex_mapping_id,
            "show",
        ),
    )


def test_canonical_folder_map_keys_by_id(db):
    m = _make()
    _seed(db, "sonarr", "Dune Prophecy (2024) {tvdb-367118}", tvdb=367118)
    _seed(db, "radarr", "Inception (2010) {tmdb-27205}", tmdb=27205)
    # A season row must NOT define the canonical (folder is the same, season set):
    _seed(db, "sonarr", "Dune Prophecy (2024) {tvdb-367118}", tvdb=367118, season=1)
    cmap = m._build_canonical_folder_map(db, ["sonarr", "radarr"])
    assert cmap[("tvdb", 367118)] == {"Dune Prophecy (2024) {tvdb-367118}"}
    assert cmap[("tmdb", 27205)] == {"Inception (2010) {tmdb-27205}"}


def test_canonical_folder_map_respects_instances(db):
    m = _make()
    _seed(db, "sonarr", "Show A (2020) {tvdb-1}", tvdb=1)
    _seed(db, "other", "Show B (2020) {tvdb-2}", tvdb=2)
    cmap = m._build_canonical_folder_map(db, ["sonarr"])
    assert ("tvdb", 1) in cmap
    assert ("tvdb", 2) not in cmap


def test_scan_stale_flags_wrong_named_folder(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    old = root / "Dune - Prophecy (2024) {tvdb-367118}"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    (old / "Season01.jpg").write_bytes(b"yy")
    cmap = {("tvdb", 367118): {"Dune Prophecy (2024) {tvdb-367118}"}}
    stale = m._scan_stale_duplicates([str(root)], cmap)
    assert len(stale) == 1
    e = stale[0]
    assert e["folder"] == str(old)
    assert e["name"] == "Dune - Prophecy (2024) {tvdb-367118}"
    assert e["canonical"] == "Dune Prophecy (2024) {tvdb-367118}"
    assert e["canonical_present"] is False
    assert e["size"] == 3
    assert e["id"] == ("tvdb", 367118)


def test_scan_stale_skips_canonical_folder(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    good = root / "Dune Prophecy (2024) {tvdb-367118}"
    good.mkdir(parents=True)
    (good / "poster.jpg").write_bytes(b"x")
    cmap = {("tvdb", 367118): {"Dune Prophecy (2024) {tvdb-367118}"}}
    assert m._scan_stale_duplicates([str(root)], cmap) == []


def test_scan_stale_ignores_unknown_id(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    folder = root / "Some Show (2020) {tvdb-999}"
    folder.mkdir(parents=True)
    (folder / "poster.jpg").write_bytes(b"x")
    assert m._scan_stale_duplicates([str(root)], {("tvdb", 1): {"X"}}) == []


def test_scan_stale_marks_canonical_present(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    (root / "Dune Prophecy (2024) {tvdb-367118}").mkdir(parents=True)
    old = root / "Dune - Prophecy (2024) {tvdb-367118}"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    cmap = {("tvdb", 367118): {"Dune Prophecy (2024) {tvdb-367118}"}}
    stale = m._scan_stale_duplicates([str(root)], cmap)
    assert len(stale) == 1
    assert stale[0]["canonical_present"] is True


def test_execute_stale_remove_deletes_old_folder(tmp_path, monkeypatch):
    m = _make()
    _live(monkeypatch, tmp_path)
    root = tmp_path / "assets"
    (root / "Dune Prophecy (2024) {tvdb-1}").mkdir(parents=True)  # canonical present
    old = root / "Dune - Prophecy (2024) {tvdb-1}"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    stale = [
        {
            "folder": str(old),
            "asset_dir": str(root),
            "name": old.name,
            "canonical": "Dune Prophecy (2024) {tvdb-1}",
            "canonical_present": True,
            "is_dir": True,
            "id": ("tvdb", 1),
            "size": 1,
        }
    ]
    res = m._execute_stale_mode(stale, "remove", _logger())
    assert res["count"] == 1
    assert not old.exists()


def test_execute_stale_remove_keeps_only_copy(tmp_path, monkeypatch):
    """If the canonical folder is NOT on disk yet, removing the stale dup would
    delete the only staged copy — keep it and report instead."""
    m = _make()
    _live(monkeypatch, tmp_path)  # authorized, so the only-copy guard is what keeps it
    root = tmp_path / "assets"
    old = root / "Dune - Prophecy (2024) {tvdb-1}"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    stale = [
        {
            "folder": str(old),
            "asset_dir": str(root),
            "name": old.name,
            "canonical": "Dune Prophecy (2024) {tvdb-1}",
            "canonical_present": False,
            "is_dir": True,
            "id": ("tvdb", 1),
            "size": 1,
        }
    ]
    res = m._execute_stale_mode(stale, "remove", _logger())
    assert res["count"] == 0  # nothing removed
    assert old.exists()  # only copy preserved


def test_execute_stale_report_deletes_nothing(tmp_path, monkeypatch):
    m = _make()
    _live(monkeypatch, tmp_path)
    root = tmp_path / "assets"
    old = root / "Dune - Prophecy (2024) {tvdb-1}"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    stale = [
        {
            "folder": str(old),
            "asset_dir": str(root),
            "name": old.name,
            "canonical": "Dune Prophecy (2024) {tvdb-1}",
            "canonical_present": True,
            "is_dir": True,
            "id": ("tvdb", 1),
            "size": 1,
        }
    ]
    res = m._execute_stale_mode(stale, "report", _logger())
    assert res["count"] == 1
    assert old.exists()


def test_execute_stale_move_moves_folder(tmp_path, monkeypatch):
    """move mode: stale folder with canonical present is moved under
    <asset_dir>/<ORPHAN_RESTORE_DIR_NAME>/<name> and the original is gone.
    The restore dir doesn't exist yet, so this also pins that the dest guard
    confines the parent makedirs creates rather than the leaf."""
    m = _make()
    _live(monkeypatch, tmp_path)
    root = tmp_path / "assets"
    canonical_name = "Show (2024) {tvdb-1}"
    (root / canonical_name).mkdir(parents=True)  # canonical present on disk
    old = root / "Show (2024) {tvdb-1} OLD"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    stale = [
        {
            "folder": str(old),
            "asset_dir": str(root),
            "name": old.name,
            "canonical": canonical_name,
            "canonical_present": True,
            "is_dir": True,
            "id": ("tvdb", 1),
            "size": 1,
        }
    ]
    res = m._execute_stale_mode(stale, "move", _logger())
    expected_dest = root / ORPHAN_RESTORE_DIR_NAME / old.name
    assert res["count"] == 1
    assert not old.exists()
    assert expected_dest.exists()


def test_scan_stale_both_ids_resolves_via_tvdb(db, tmp_path):
    """A folder with both {tvdb-N} and {tmdb-M} in the name resolves via the
    tvdb branch (elif priority in _scan_stale_duplicates) when both ids are
    in the canonical map."""
    m = _make()
    tvdb_canonical = "Show (2024) {tvdb-1}"
    tmdb_canonical = "Show (2024) {tmdb-2}"
    cmap = {
        ("tvdb", 1): {tvdb_canonical},
        ("tmdb", 2): {tmdb_canonical},
    }
    root = tmp_path / "assets"
    # Folder name carries BOTH ids but a different name (stale for both)
    folder_name = "Show (2024) {tvdb-1} {tmdb-2}"
    stale_dir = root / folder_name
    stale_dir.mkdir(parents=True)
    (stale_dir / "poster.jpg").write_bytes(b"x")
    stale = m._scan_stale_duplicates([str(root)], cmap)
    assert len(stale) == 1
    entry = stale[0]
    # tvdb branch wins (the elif means tvdb is checked first)
    assert entry["id"] == ("tvdb", 1)
    assert entry["canonical"] == tvdb_canonical


def test_run_stale_pass_aborts_when_no_instances(db, tmp_path, monkeypatch):
    m = _make(tmp_path)
    _live(monkeypatch, tmp_path)  # authorized, so the instances guard is what aborts
    res = m._run_stale_pass(
        db=db,
        instances=[],
        asset_dirs=[str(tmp_path)],
        mode="report",
        logger=_logger(),
    )
    assert res["count"] == 0


def test_run_stale_pass_reports(db, tmp_path, monkeypatch):
    m = _make(tmp_path)
    _live(monkeypatch, tmp_path)
    _seed(db, "sonarr", "Dune Prophecy (2024) {tvdb-367118}", tvdb=367118)
    root = tmp_path / "assets"
    old = root / "Dune - Prophecy (2024) {tvdb-367118}"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    res = m._run_stale_pass(
        db=db,
        instances=["sonarr"],
        asset_dirs=[str(root)],
        mode="report",
        logger=_logger(),
    )
    assert res["count"] == 1


_OLD = "Dune - Prophecy (2024) {tvdb-367118}"
_CANON = "Dune Prophecy (2024) {tvdb-367118}"


@pytest.mark.parametrize("mode", ["move", "remove"])
def test_stale_pass_clears_flat_files_under_an_old_folder_name(db, tmp_path, monkeypatch, mode):
    m = _make(tmp_path)
    _live(monkeypatch, tmp_path)
    _seed(db, "sonarr", _CANON, tvdb=367118)
    root = tmp_path / "assets"
    root.mkdir()
    untouched = [f"{_OLD}.nfo", f"{_OLD}_Season01.jpg", "No Id (2020).jpg", "Other (2020) {tvdb-9}.jpg"]
    for name in [f"{_CANON}.jpg", f"{_CANON}_logo.png", f"{_OLD}.jpg", f"{_OLD}_logo.png", *untouched]:
        (root / name).write_bytes(b"x")
    res = m._run_stale_pass(db=db, instances=["sonarr"], asset_dirs=[str(root)], mode=mode, logger=_logger())
    restore = root / ORPHAN_RESTORE_DIR_NAME
    left = sorted(p.name for p in root.iterdir() if p != restore)
    moved = sorted(p.name for p in restore.iterdir()) if restore.exists() else []
    assert (res["count"], left) == (2, sorted([f"{_CANON}.jpg", f"{_CANON}_logo.png", *untouched]))
    assert moved == ([f"{_OLD}.jpg", f"{_OLD}_logo.png"] if mode == "move" else [])


def test_scan_stale_names_a_flat_files_copy_after_the_canonical_id_tag(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    root.mkdir()
    canonical = "Dune Prophecy (2024) {tvdb-1} [x]"
    (root / f"{canonical}_logo.png").write_bytes(b"x")
    (root / f"{canonical}.jpg").write_bytes(b"x")
    (root / "Dune (2024) {tvdb-1}_logo.png").write_bytes(b"x")
    stale = m._scan_stale_duplicates([str(root)], {("tvdb", 1): {canonical}})
    assert [(e["name"], e["canonical"], e["canonical_folder"], e["canonical_present"]) for e in stale] == [
        ("Dune (2024) {tvdb-1}_logo.png", f"{canonical}_logo.png", canonical, True)
    ]


def test_scan_stale_reads_the_folder_name_before_the_placement_suffix(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    root.mkdir()
    canon = "Dune Prophecy (2024) {tvdb-1}"
    old = "Dune (2024) {tvdb-1} {imdb-tt9}"
    for name in [f"{canon}.png", f"{canon}_logo.png", f"{canon}_Season01_logo.png", f"{old}.jpg", f"{old}_logo.png"]:
        (root / name).write_bytes(b"x")
    stale = m._scan_stale_duplicates([str(root)], {("tvdb", 1): {canon}})
    assert [(e["name"], e["canonical"], e["canonical_present"]) for e in stale] == [
        (f"{old}.jpg", f"{canon}.png", True),
        (f"{old}_logo.png", f"{canon}_logo.png", True),
    ]


def test_stale_pass_keeps_each_instances_folder_for_one_id(db, tmp_path, monkeypatch):
    m = _make(tmp_path)
    _live(monkeypatch, tmp_path)
    _seed(db, "sonarr", _CANON, tvdb=367118)
    _seed(db, "sonarr-4k", _OLD, tvdb=367118)
    root = tmp_path / "assets"
    root.mkdir()
    for folder in (_CANON, _OLD):
        _place(root / folder, True)
        _place(root / f"{folder}.jpg", False)
    (root / "Dune Gone (2024) {tvdb-367118}.jpg").write_bytes(b"x")
    res = m._run_stale_pass(db=db, instances=["sonarr", "sonarr-4k"], asset_dirs=[str(root)], mode="remove", logger=_logger())
    left = sorted(p.name for p in root.iterdir())
    assert (res["count"], left) == (1, sorted([_CANON, f"{_CANON}.jpg", _OLD, f"{_OLD}.jpg"]))


def test_scan_stale_finds_the_canonical_copy_under_an_upper_case_extension(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    root.mkdir()
    for name in ("Dune (2024) {tvdb-1}.jpg", "Dune Prophecy (2024) {tvdb-1}.PNG"):
        (root / name).write_bytes(b"x")
    stale = m._scan_stale_duplicates([str(root)], {("tvdb", 1): {"Dune Prophecy (2024) {tvdb-1}"}})
    assert [(e["canonical"], e["canonical_present"]) for e in stale] == [("Dune Prophecy (2024) {tvdb-1}.PNG", True)]


def test_scan_stale_keeps_a_file_named_for_a_current_folder_that_ends_like_a_suffix(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    root.mkdir()
    for name in ("Show {tvdb-1}_logo.jpg", "Renamed Show {tvdb-1}_logo.jpg"):
        (root / name).write_bytes(b"x")
    folders = {"Show {tvdb-1}_logo", "Renamed Show {tvdb-1}"}
    assert m._scan_stale_duplicates([str(root)], {("tvdb", 1): folders}) == []


@pytest.mark.parametrize("current_poster", [False, True])
def test_scan_stale_needs_a_current_copy_for_each_asset_an_ambiguous_name_can_be(tmp_path, current_poster):
    m = _make()
    root = tmp_path / "assets"
    root.mkdir()
    names = ["Old Show {tvdb-1}_logo.jpg", "New Show {tvdb-1}_logo.png"] + ["New Show {tvdb-1}.jpg"] * current_poster
    for name in names:
        (root / name).write_bytes(b"x")
    stale = m._scan_stale_duplicates([str(root)], {("tvdb", 1): {"New Show {tvdb-1}"}})
    want = "New Show {tvdb-1}_logo.png" if current_poster else "New Show {tvdb-1}.jpg"
    assert [(e["name"], e["canonical"], e["canonical_present"]) for e in stale] == [
        ("Old Show {tvdb-1}_logo.jpg", want, current_poster)
    ]


def _place(path, is_dir, data=b"x"):
    """A flat file, or a folder holding poster.jpg, at ``path`` with ``data``."""
    if is_dir:
        path.mkdir()
        path = path / "poster.jpg"
    path.write_bytes(data)


def _bytes(path):
    """What ``path`` holds: a flat file's bytes, or its folder's poster.jpg."""
    return (path / "poster.jpg" if path.is_dir() else path).read_bytes()


@pytest.mark.parametrize("is_dir", [False, True])
def test_stale_pass_keeps_the_copy_a_canonical_link_points_at(db, tmp_path, monkeypatch, is_dir):
    m = _make(tmp_path)
    _live(monkeypatch, tmp_path)
    _seed(db, "sonarr", _CANON, tvdb=367118)
    root = tmp_path / "assets"
    root.mkdir()
    ext = "" if is_dir else ".jpg"
    _place(root / f"{_OLD}{ext}", is_dir)
    (root / f"{_CANON}{ext}").symlink_to(root / f"{_OLD}{ext}")
    res = m._run_stale_pass(db=db, instances=["sonarr"], asset_dirs=[str(root)], mode="remove", logger=_logger())
    assert (res["count"], _bytes(root / f"{_CANON}{ext}")) == (0, b"x")


def test_stale_pass_keeps_a_case_only_rename_on_a_case_insensitive_mount(db, tmp_path, monkeypatch):
    (tmp_path / "probe").touch()
    if not (tmp_path / "PROBE").exists():
        pytest.skip("needs a case-insensitive filesystem")
    m = _make(tmp_path)
    _live(monkeypatch, tmp_path)
    _seed(db, "sonarr", _CANON.replace("Prophecy", "PROPHECY"), tvdb=367118)
    root = tmp_path / "assets"
    root.mkdir()
    _place(root / _CANON, True)
    _place(root / f"{_CANON}.jpg", False)
    res = m._run_stale_pass(db=db, instances=["sonarr"], asset_dirs=[str(root)], mode="remove", logger=_logger())
    assert (res["count"], sorted(p.name for p in root.iterdir())) == (0, [_CANON, f"{_CANON}.jpg"])


@pytest.mark.parametrize("is_dir", [False, True])
def test_stale_move_keeps_an_earlier_restore_copy_of_the_same_name(db, tmp_path, monkeypatch, is_dir):
    m = _make(tmp_path)
    _live(monkeypatch, tmp_path)
    _seed(db, "sonarr", _CANON, tvdb=367118)
    root = tmp_path / "assets"
    restore = root / ORPHAN_RESTORE_DIR_NAME
    restore.mkdir(parents=True)
    ext = "" if is_dir else ".jpg"
    _place(restore / f"{_OLD}{ext}", is_dir, b"earlier")
    _place(root / f"{_CANON}{ext}", is_dir)
    _place(root / f"{_OLD}{ext}", is_dir, b"later")
    res = m._run_stale_pass(db=db, instances=["sonarr"], asset_dirs=[str(root)], mode="move", logger=_logger())
    kept = {p.name: _bytes(p) for p in restore.iterdir()}
    assert (res["count"], kept) == (1, {f"{_OLD}{ext}": b"earlier", f"{_OLD} (1){ext}": b"later"})


def _seed_stale_pair(root, canonical="Dune Prophecy (2024) {tvdb-367118}"):
    """A stale-named folder plus its canonical sibling, so remove mode is allowed."""
    (root / canonical).mkdir(parents=True)
    old = root / "Dune - Prophecy (2024) {tvdb-367118}"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    return old


def test_run_stale_pass_skips_asset_dir_outside_allowed_roots(
    db, tmp_path, monkeypatch
):
    """The stale pass refuses an unconfined dir at execution time; the allowed one still cleans."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    confined_stale = _seed_stale_pair(allowed)
    outside_stale = _seed_stale_pair(outside)
    m = _make(allowed)
    cfg = _live(monkeypatch, allowed)
    assert resolve_confined(str(outside), cfg) is None  # control
    _seed(db, "sonarr", "Dune Prophecy (2024) {tvdb-367118}", tvdb=367118)

    res = m._run_stale_pass(
        db=db,
        instances=["sonarr"],
        asset_dirs=[str(allowed), str(outside)],
        mode="remove",
        logger=_logger(),
    )

    assert res["count"] == 1
    assert not confined_stale.exists()  # allowed root still processed
    assert outside_stale.exists()  # unauthorized root untouched


def test_run_stale_pass_fails_closed_when_config_unavailable(db, tmp_path, monkeypatch):
    """Without a loadable config nothing can be authorized, so nothing is removed."""
    m = object.__new__(PosterCleanarr)  # shim entry point's shape: no full_config
    m.logger = _logger()

    def _boom():
        raise ConfigError("corrupt config")

    monkeypatch.setattr("backend.util.config.load_config", _boom)
    stale = _seed_stale_pair(tmp_path / "assets")
    _seed(db, "sonarr", "Dune Prophecy (2024) {tvdb-367118}", tvdb=367118)
    errors = []
    logger = _logger()
    logger.error = errors.append

    res = m._run_stale_pass(
        db=db,
        instances=["sonarr"],
        asset_dirs=[str(tmp_path / "assets")],
        mode="remove",
        logger=logger,
    )

    assert res["count"] == 0
    assert stale.exists()  # nothing removed on an unverifiable authorization
    assert errors  # and the refusal is logged, not silent


def test_stale_pass_ignores_the_construction_time_config_snapshot(
    db, tmp_path, monkeypatch
):
    """A root removed from config after the module was built must stop
    authorizing: the worker reads the live config, never self.full_config."""
    m = _make(tmp_path)  # the construction-time snapshot still carries the root
    _live(monkeypatch)  # ...but the live config no longer allows anything
    stale = _seed_stale_pair(tmp_path / "assets")
    _seed(db, "sonarr", "Dune Prophecy (2024) {tvdb-367118}", tvdb=367118)
    logger, errors = _collecting_logger()

    assert m._authorized_asset_dirs([str(tmp_path / "assets")], logger) == []
    res = m._run_stale_pass(
        db=db,
        instances=["sonarr"],
        asset_dirs=[str(tmp_path / "assets")],
        mode="remove",
        logger=logger,
    )

    assert res["count"] == 0
    assert stale.exists()  # the de-authorized root is not cleaned
    assert errors  # and the refusal is logged, not silent


def _swap_parent_for_link(allowed, outside):
    """Stale entry under `allowed` whose parent then becomes a link to `outside`."""
    parent = allowed / "shows"
    parent.mkdir(parents=True)
    scanned = parent / "Dune - Prophecy (2024) {tvdb-1}"
    scanned.mkdir()
    entry = {
        "folder": str(scanned),
        "asset_dir": str(allowed),
        "name": scanned.name,
        "canonical": "Dune Prophecy (2024) {tvdb-1}",
        "canonical_present": True,
        "is_dir": True,
        "id": ("tvdb", 1),
        "size": 1,
    }
    scanned.rmdir()
    parent.rmdir()
    parent.symlink_to(outside, target_is_directory=True)
    return entry


def _victim_folder(outside):
    """A folder outside the roots that the swapped-in link points at."""
    victim = outside / "Dune - Prophecy (2024) {tvdb-1}"
    victim.mkdir(parents=True)
    (victim / "poster.jpg").write_bytes(b"x")
    return victim


def test_execute_stale_remove_refuses_a_swapped_parent(tmp_path, monkeypatch):
    """A parent component swapped to a symlink between scan and rmtree must not delete the tree it now points at."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    victim = _victim_folder(outside)
    m = _make(allowed)
    _live(monkeypatch, allowed)
    entry = _swap_parent_for_link(allowed, outside)
    logger, errors = _collecting_logger()

    res = m._execute_stale_mode([entry], "remove", logger)

    assert res["count"] == 0
    assert victim.exists()  # the swapped-in target is untouched
    assert errors


def test_execute_stale_move_refuses_a_swapped_parent(tmp_path, monkeypatch):
    """Same swap on the move path — shutil.move must not relocate an outside folder."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    victim = _victim_folder(outside)
    m = _make(allowed)
    _live(monkeypatch, allowed)
    entry = _swap_parent_for_link(allowed, outside)
    logger, errors = _collecting_logger()

    res = m._execute_stale_mode([entry], "move", logger)

    assert res["count"] == 0
    assert victim.exists()  # not dragged into the restore dir
    assert errors


def test_execute_stale_remove_rmtrees_through_a_parent_descriptor(
    tmp_path, monkeypatch
):
    """The recursive delete is anchored to a descriptor on the confined parent, so a parent re-pointed the instant after it is opened is refused."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    victim = _victim_folder(outside)
    shows = allowed / "shows"
    shows.mkdir()
    stale = shows / "Dune - Prophecy (2024) {tvdb-1}"
    stale.mkdir()
    (stale / "poster.jpg").write_bytes(b"x")
    (shows / "Dune Prophecy (2024) {tvdb-1}").mkdir()  # canonical present
    m = _make(allowed)
    _live(monkeypatch, allowed)

    real_open = os.open

    def _swapping_open(path, *a, **kw):
        """Open normally, then re-point that same dir at `outside`."""
        fd = real_open(path, *a, **kw)
        # Match on the basename: the walk opens each component by NAME.
        if (
            os.path.basename(str(path)) == shows.name
            and shows.is_dir()
            and not shows.is_symlink()
        ):
            shows.rename(allowed / "shows_real")
            shows.symlink_to(outside, target_is_directory=True)
        return fd

    # `os` here is the same module object poster_cleanarr calls through.
    monkeypatch.setattr(os, "open", _swapping_open)
    logger, errors = _collecting_logger()
    entry = {
        "folder": str(stale),
        "asset_dir": str(allowed),
        "name": stale.name,
        "canonical": "Dune Prophecy (2024) {tvdb-1}",
        "canonical_present": True,
        "is_dir": True,
        "id": ("tvdb", 1),
        "size": 1,
    }

    res = m._execute_stale_mode([entry], "remove", logger)

    assert res["count"] == 0
    assert victim.exists()  # the swapped-in tree is never deleted through
    assert (allowed / "shows_real" / stale.name).exists()  # nor the pinned one
    assert errors


def test_run_invokes_orphan_and_stale_passes(monkeypatch, tmp_path, noop_media_resync):
    """run() with mode='nothing' (skips Plex/bloat) must still invoke BOTH the
    orphan and stale passes when their config flags are set — the path a
    SCHEDULED job takes, reading saved config. Proves all three cleaners are
    independently driven by config, so a schedule can run them in any mode."""

    class _FakeDB:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        "backend.modules.poster_cleanarr.ChubDB", lambda *a, **k: _FakeDB()
    )

    def _sched_logger():
        return SimpleNamespace(
            debug=lambda *a, **k: None,
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
            get_adapter=lambda *a, **k: _sched_logger(),
            log_outro=lambda *a, **k: None,
        )

    m = object.__new__(PosterCleanarr)
    m.logger = _sched_logger()
    m.mode = "nothing"
    m.plex_path = ""
    m.full_config = ChubConfig()
    live = ChubConfig()
    live.instances.sonarr["sonarr"] = InstanceDetail(url="http://sonarr:8989", api="key")
    monkeypatch.setattr("backend.util.config.load_config", lambda: live)
    m.config = SimpleNamespace(
        local_db=True,
        orphan_assets_enabled=True,
        orphan_assets_mode="report",
        stale_duplicates_enabled=True,
        stale_duplicates_mode="report",
        asset_dirs=[str(tmp_path)],
        instances=["sonarr"],
        orphan_instances=[],
        include_collections=True,
        orphan_ignore_titles=[],
        target_paths=None,
    )
    calls = []
    monkeypatch.setattr(
        m,
        "_run_orphan_pass",
        lambda **k: calls.append("orphan") or {"count": 0, "total_size": 0},
    )
    monkeypatch.setattr(
        m,
        "_run_stale_pass",
        lambda **k: calls.append("stale") or {"count": 0, "total_size": 0},
    )
    m.run()
    assert "orphan" in calls
    assert "stale" in calls
def test_stale_remove_passes_the_descriptor_to_rmtree(tmp_path, monkeypatch):
    """The delete resolves its name against dir_fd, not a path the kernel re-walks."""
    import shutil

    allowed = tmp_path / "allowed"
    shows = allowed / "shows"
    stale = shows / "Dune - Prophecy (2024) {tvdb-1}"
    stale.mkdir(parents=True)
    (stale / "poster.jpg").write_bytes(b"x")
    (shows / "Dune Prophecy (2024) {tvdb-1}").mkdir()
    m = _make(allowed)
    _live(monkeypatch, allowed)

    seen = {}
    real_rmtree = shutil.rmtree

    def _recording_rmtree(path, *a, **kw):
        seen["path"] = path
        seen["dir_fd"] = kw.get("dir_fd")
        return real_rmtree(path, *a, **kw)

    monkeypatch.setattr(shutil, "rmtree", _recording_rmtree)
    entry = {
        "folder": str(stale),
        "asset_dir": str(allowed),
        "name": stale.name,
        "canonical": "Dune Prophecy (2024) {tvdb-1}",
        "canonical_present": True,
        "is_dir": True,
        "id": ("tvdb", 1),
        "size": 1,
    }

    res = m._execute_stale_mode([entry], "remove", _collecting_logger()[0])

    assert res["count"] == 1
    assert seen["dir_fd"] is not None  # anchored, not path-walked
    assert seen["path"] == stale.name  # a bare name, resolved against the fd
    assert not stale.exists()


def _stale_entry(folder, asset_dir, canonical):
    """A stale-duplicate entry for `folder`, as _scan_stale_duplicates emits it."""
    return {
        "folder": str(folder),
        "asset_dir": str(asset_dir),
        "name": os.path.basename(str(folder)),
        "canonical": canonical,
        "canonical_folder": canonical,
        "canonical_present": True,
        "is_dir": True,
        "id": ("tvdb", 1),
        "size": 1,
    }


def test_execute_stale_move_renames_through_both_parent_descriptors(
    tmp_path, monkeypatch
):
    """The stale move is an os.rename resolved against a descriptor on each parent, not a path pair shutil re-walks."""
    allowed = tmp_path / "allowed"
    canonical = "Dune Prophecy (2024) {tvdb-1}"
    (allowed / canonical).mkdir(parents=True)  # canonical present
    stale = allowed / "Dune - Prophecy (2024) {tvdb-1}"
    stale.mkdir()
    (stale / "poster.jpg").write_bytes(b"x")
    m = _make(allowed)
    _live(monkeypatch, allowed)

    calls = []
    real_rename = os.rename

    def _recording_rename(src, dst, **kw):
        calls.append((src, dst, kw.get("src_dir_fd"), kw.get("dst_dir_fd")))
        return real_rename(src, dst, **kw)

    monkeypatch.setattr(os, "rename", _recording_rename)

    res = m._execute_stale_mode(
        [_stale_entry(stale, allowed, canonical)], "move", _logger()
    )

    assert res["count"] == 1
    assert (allowed / ORPHAN_RESTORE_DIR_NAME / stale.name / "poster.jpg").exists()
    assert len(calls) == 1
    src, dst, src_fd, dst_fd = calls[0]
    assert (src, dst) == (stale.name, stale.name)  # bare names, not paths
    assert src_fd is not None and dst_fd is not None  # ...against both fds


def test_execute_stale_mode_stops_when_config_stops_authorizing(
    tmp_path, tightening_config
):
    """Config is re-read per item, so a root dropped mid-batch stops the tail while the head — authorized when its turn came — still ran."""
    allowed = tmp_path / "allowed"
    entries = []
    for tag in ("A", "B"):
        (allowed / f"Show {tag} (2024) {{tvdb-1}}").mkdir(parents=True)
        old = allowed / f"Show {tag} old (2024) {{tvdb-1}}"
        old.mkdir()
        (old / "poster.jpg").write_bytes(b"x")
        entries.append(_stale_entry(old, allowed, f"Show {tag} (2024) {{tvdb-1}}"))
    m = _make(allowed)
    calls = tightening_config(allowed, authorized_calls=1)
    logger, errors = _collecting_logger()

    res = m._execute_stale_mode(entries, "remove", logger)

    assert res["count"] == 1
    assert not os.path.exists(entries[0]["folder"])
    assert os.path.exists(entries[1]["folder"])  # de-authorized before its turn
    assert len(calls) >= 2  # one load per item, not one per batch
    # Labelled by pass, so an empty-dir-sweep refusal cannot satisfy it.
    assert [
        "Stale-duplicate cleanup: refused 1 path(s)" in e for e in errors
    ].count(True) == 1
