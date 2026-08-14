"""Tests for poster_cleanarr stale-duplicate detection — a Kometa asset folder
whose {tvdb/tmdb} id matches a live media item but whose name != the item's
canonical folder (media_cache.folder). Safety: never remove the only copy."""

from types import SimpleNamespace

import pytest

from backend.modules.poster_cleanarr import ORPHAN_RESTORE_DIR_NAME, PosterCleanarr
from backend.util.config import ChubConfig, ConfigError
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
    """Bare instance; `allowed_roots` are the config roots the passes confine to."""
    m = object.__new__(PosterCleanarr)
    m.logger = _logger()
    m.full_config = ChubConfig()
    m.full_config.poster_renamerr.source_dirs = [str(r) for r in allowed_roots]
    return m


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
    assert cmap[("tvdb", 367118)] == "Dune Prophecy (2024) {tvdb-367118}"
    assert cmap[("tmdb", 27205)] == "Inception (2010) {tmdb-27205}"


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
    cmap = {("tvdb", 367118): "Dune Prophecy (2024) {tvdb-367118}"}
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
    cmap = {("tvdb", 367118): "Dune Prophecy (2024) {tvdb-367118}"}
    assert m._scan_stale_duplicates([str(root)], cmap) == []


def test_scan_stale_ignores_unknown_id(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    folder = root / "Some Show (2020) {tvdb-999}"
    folder.mkdir(parents=True)
    (folder / "poster.jpg").write_bytes(b"x")
    assert m._scan_stale_duplicates([str(root)], {("tvdb", 1): "X"}) == []


def test_scan_stale_marks_canonical_present(tmp_path):
    m = _make()
    root = tmp_path / "assets"
    (root / "Dune Prophecy (2024) {tvdb-367118}").mkdir(parents=True)
    old = root / "Dune - Prophecy (2024) {tvdb-367118}"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    cmap = {("tvdb", 367118): "Dune Prophecy (2024) {tvdb-367118}"}
    stale = m._scan_stale_duplicates([str(root)], cmap)
    assert len(stale) == 1
    assert stale[0]["canonical_present"] is True


def test_execute_stale_remove_deletes_old_folder(tmp_path):
    m = _make()
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
            "id": ("tvdb", 1),
            "size": 1,
        }
    ]
    res = m._execute_stale_mode(stale, "remove", _logger())
    assert res["count"] == 1
    assert not old.exists()


def test_execute_stale_remove_keeps_only_copy(tmp_path):
    """If the canonical folder is NOT on disk yet, removing the stale dup would
    delete the only staged copy — keep it and report instead."""
    m = _make()
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
            "id": ("tvdb", 1),
            "size": 1,
        }
    ]
    res = m._execute_stale_mode(stale, "remove", _logger())
    assert res["count"] == 0  # nothing removed
    assert old.exists()  # only copy preserved


def test_execute_stale_report_deletes_nothing(tmp_path):
    m = _make()
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
            "id": ("tvdb", 1),
            "size": 1,
        }
    ]
    res = m._execute_stale_mode(stale, "report", _logger())
    assert res["count"] == 1
    assert old.exists()


def test_execute_stale_move_moves_folder(tmp_path):
    """move mode: stale folder with canonical present is moved under
    <asset_dir>/<ORPHAN_RESTORE_DIR_NAME>/<name> and the original is gone."""
    m = _make()
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
        ("tvdb", 1): tvdb_canonical,
        ("tmdb", 2): tmdb_canonical,
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


def test_run_stale_pass_aborts_when_no_instances(db, tmp_path):
    m = _make(tmp_path)
    res = m._run_stale_pass(
        db=db,
        instances=[],
        asset_dirs=[str(tmp_path)],
        mode="report",
        logger=_logger(),
    )
    assert res["count"] == 0


def test_run_stale_pass_reports(db, tmp_path):
    m = _make(tmp_path)
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


def _seed_stale_pair(root, canonical="Dune Prophecy (2024) {tvdb-367118}"):
    """A stale-named folder plus its canonical sibling, so remove mode is allowed."""
    (root / canonical).mkdir(parents=True)
    old = root / "Dune - Prophecy (2024) {tvdb-367118}"
    old.mkdir(parents=True)
    (old / "poster.jpg").write_bytes(b"x")
    return old


def test_run_stale_pass_skips_asset_dir_outside_allowed_roots(db, tmp_path):
    """The stale pass refuses an unconfined dir at execution time; the allowed one still cleans."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    confined_stale = _seed_stale_pair(allowed)
    outside_stale = _seed_stale_pair(outside)
    m = _make(allowed)
    assert resolve_confined(str(outside), m.full_config) is None  # control
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


def test_run_invokes_orphan_and_stale_passes(monkeypatch, tmp_path):
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
    m.full_config = SimpleNamespace()
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
