"""Tests for poster_cleanarr's orphan-asset deletion safety guards — the most
destructive path in the module (irreversible os.remove / shutil.move).

Covers: the empty-title-set guard that aborts mass deletion, instance-filtered
title-set construction (incl. alternate titles), and the report/move/remove
executor.
"""

from types import SimpleNamespace

import pytest

from backend.modules.poster_cleanarr import PosterCleanarr
from backend.util.database import ChubDB
from backend.util.normalization import normalize_titles


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


def _seed_media(db, identity_key, instance_name, normalized_title, alt=None):
    db.media.execute_query(
        "INSERT INTO media_cache (identity_key, instance_name, normalized_title, "
        "normalized_alternate_titles, asset_type) VALUES (?,?,?,?,?)",
        (identity_key, instance_name, normalized_title, alt, "movie"),
    )


def test_orphan_pass_aborts_when_title_set_empty(db, tmp_path):
    """If media_cache is empty for the configured instances, the comparison
    set is empty and the pass must abort WITHOUT deleting anything — the last
    line of defense against wiping every asset."""
    m = _make()
    orphan = tmp_path / "Some Movie (2020).png"
    orphan.write_bytes(b"x")

    res = m._run_orphan_pass(
        db, ["radarr1"], [str(tmp_path)], "remove", False, _logger()
    )

    assert res["count"] == 0
    assert orphan.exists()  # nothing deleted


def test_build_title_set_filters_by_instance_and_absorbs_alternates(db):
    m = _make()
    _seed_media(db, "k1", "radarr1", "dune", '["dunepartone"]')
    _seed_media(db, "k2", "other_instance", "shouldbeignored")

    titles = m._build_library_title_set(db, ["radarr1"], include_collections=False)

    assert "dune" in titles
    assert "dunepartone" in titles  # alternate titles absorbed
    assert "shouldbeignored" not in titles  # other instance excluded


def test_execute_orphan_mode_report_then_remove(tmp_path):
    """report counts but deletes nothing; remove actually deletes the file."""
    m = _make()
    f = tmp_path / "orphan.png"
    f.write_bytes(b"x")
    orphan = {
        "path": str(f),
        "size": 1,
        "parsed": "orphan",
        "asset_dir": str(tmp_path),
    }

    report = m._execute_orphan_mode([dict(orphan)], "report", _logger())
    assert report["count"] == 1
    assert f.exists()  # report never deletes

    removed = m._execute_orphan_mode([dict(orphan)], "remove", _logger())
    assert removed["count"] == 1
    assert not f.exists()  # remove deletes


def test_execute_orphan_mode_move_relocates(tmp_path):
    m = _make()
    f = tmp_path / "orphan.png"
    f.write_bytes(b"x")
    orphan = {
        "path": str(f),
        "size": 1,
        "parsed": "orphan",
        "asset_dir": str(tmp_path),
    }

    res = m._execute_orphan_mode([orphan], "move", _logger())
    assert res["count"] == 1
    assert not f.exists()  # moved out of its original location


# ── ID-based matching (spare-only) ───────────────────────────────────────────


def _write(tmp_path, name):
    f = tmp_path / name
    f.write_bytes(b"x")
    return f


def test_scan_tmdb_id_match_spares_title_mismatch(tmp_path):
    """A {tmdb-N} tag whose id IS in the library spares the file even when its
    title doesn't match anything in the title set."""
    m = _make()
    _write(tmp_path, "Renamed Title (2020) {tmdb-123}.png")

    orphans = m._scan_orphan_assets(
        [str(tmp_path)], library_titles=set(), tmdb_ids={123}, tvdb_ids=set()
    )

    assert orphans == []


def test_scan_tvdb_id_match_spares_title_mismatch(tmp_path):
    """tvdb id matching spares the same way as tmdb."""
    m = _make()
    _write(tmp_path, "Renamed Show (2019) {tvdb-555}.png")

    orphans = m._scan_orphan_assets(
        [str(tmp_path)], library_titles=set(), tmdb_ids=set(), tvdb_ids={555}
    )

    assert orphans == []


def test_scan_id_miss_falls_back_to_title(tmp_path):
    """Spare-only: a {tmdb-N} NOT in the library does not flag the file — it
    falls through to the title check, which here matches, so it's kept."""
    m = _make()
    _write(tmp_path, "Some Movie (2020) {tmdb-999}.png")
    title_key = normalize_titles("Some Movie (2020)")

    orphans = m._scan_orphan_assets(
        [str(tmp_path)],
        library_titles={title_key},  # title matches
        tmdb_ids={123},  # 999 not present, but that must NOT flag
        tvdb_ids=set(),
    )

    assert orphans == []  # stale id but matching title -> kept


def test_scan_flags_only_when_id_and_title_both_miss(tmp_path):
    """The single removal path: neither the id tag nor the title matches."""
    m = _make()
    f = _write(tmp_path, "Some Movie (2020) {tmdb-999}.png")

    orphans = m._scan_orphan_assets(
        [str(tmp_path)],
        library_titles=set(),  # title misses
        tmdb_ids={123},  # id misses
        tvdb_ids=set(),
    )

    assert len(orphans) == 1
    assert orphans[0]["path"] == str(f)


def test_scan_ignore_list_spares_unmatched(tmp_path):
    """A title in the ignore set is never flagged, even with no library match
    and no id tag."""
    m = _make()
    _write(tmp_path, "Personal Poster.png")

    orphans = m._scan_orphan_assets(
        [str(tmp_path)],
        library_titles=set(),
        tmdb_ids=set(),
        tvdb_ids=set(),
        ignore_keys={normalize_titles("Personal Poster")},
    )

    assert orphans == []


def test_resolve_orphan_instances_prefers_orphan_instances():
    """When orphan_instances is set, it is used as the comparison-set source."""
    cfg = SimpleNamespace(
        orphan_instances=["radarr1", "sonarr1"], instances=["plex1"]
    )
    assert PosterCleanarr._resolve_orphan_instances(cfg) == ["radarr1", "sonarr1"]


def test_resolve_orphan_instances_falls_back_to_instances_when_empty():
    """Pre-split configs listed ARR names in `instances`; an empty
    `orphan_instances` must fall back to `instances` so they keep working."""
    cfg = SimpleNamespace(
        orphan_instances=[], instances=["plex1", "radarr1", "sonarr1"]
    )
    assert PosterCleanarr._resolve_orphan_instances(cfg) == [
        "plex1",
        "radarr1",
        "sonarr1",
    ]


def test_resolve_orphan_instances_handles_missing_attrs():
    """Missing/None attributes degrade to an empty list, never raise."""
    assert PosterCleanarr._resolve_orphan_instances(SimpleNamespace()) == []
    cfg = SimpleNamespace(orphan_instances=None, instances=None)
    assert PosterCleanarr._resolve_orphan_instances(cfg) == []


def test_build_library_id_sets_filters_by_instance(db):
    m = _make()
    db.media.execute_query(
        "INSERT INTO media_cache (identity_key, instance_name, normalized_title, "
        "tmdb_id, tvdb_id, asset_type) VALUES (?,?,?,?,?,?)",
        ("k1", "radarr1", "dune", 12345, None, "movie"),
    )
    db.media.execute_query(
        "INSERT INTO media_cache (identity_key, instance_name, normalized_title, "
        "tmdb_id, tvdb_id, asset_type) VALUES (?,?,?,?,?,?)",
        ("k2", "sonarr1", "show", None, 67890, "series"),
    )
    db.media.execute_query(
        "INSERT INTO media_cache (identity_key, instance_name, normalized_title, "
        "tmdb_id, tvdb_id, asset_type) VALUES (?,?,?,?,?,?)",
        ("k3", "other", "ignored", 99999, None, "movie"),
    )

    tmdb_ids, tvdb_ids = m._build_library_id_sets(db, ["radarr1", "sonarr1"])

    assert tmdb_ids == {12345}
    assert tvdb_ids == {67890}
    assert 99999 not in tmdb_ids  # other instance excluded
