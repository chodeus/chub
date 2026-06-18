"""Tests for poster_cleanarr stale-duplicate detection — a Kometa asset folder
whose {tvdb/tmdb} id matches a live media item but whose name != the item's
canonical folder (media_cache.folder). Safety: never remove the only copy."""

from types import SimpleNamespace

import pytest

from backend.modules.poster_cleanarr import PosterCleanarr
from backend.util.database import ChubDB


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


def _make():
    m = object.__new__(PosterCleanarr)
    m.logger = _logger()
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


def _cfg(m, mode="remove"):
    m.config = SimpleNamespace()
    return m


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
    res = m._execute_stale_mode(stale, "remove")
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
    res = m._execute_stale_mode(stale, "remove")
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
    res = m._execute_stale_mode(stale, "report")
    assert res["count"] == 1
    assert old.exists()


def test_run_stale_pass_aborts_when_no_instances(db, tmp_path):
    m = _make()
    res = m._run_stale_pass(
        db=db,
        instances=[],
        asset_dirs=[str(tmp_path)],
        mode="report",
        logger=_logger(),
    )
    assert res["count"] == 0


def test_run_stale_pass_reports(db, tmp_path):
    m = _make()
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
