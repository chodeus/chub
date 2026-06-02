"""Tests for UnmatchedAssets.get_artwork_stats — per-image-type coverage
(applied / missing / needs_review / ignored).

Coverage is PROVENANCE-based: it is derived purely from media_asset_matches
rows. An item with no row for a type is "not yet evaluated" and is not counted
at all (so an empty table — e.g. just after a reset, or before asset_renamerr's
first run — reports every count as 0). asset_renamerr records a "missing" row
for genuine no-source-artwork gaps; those are what populate the missing bucket.
"""

from types import SimpleNamespace

import pytest

from backend.modules.unmatched_assets import UnmatchedAssets
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


@pytest.fixture
def db(tmp_path):
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as database:
        yield database


def _seed_movie(db, title, tmdb):
    item = {
        "title": title,
        "normalized_title": normalize_titles(title),
        "year": "2020",
        "tmdb_id": tmdb,
        "imdb_id": f"tt{tmdb}",
        "alternate_titles": [],
        "normalized_alternate_titles": [],
        "has_content": 1,  # passes should_include's release/has-content gate
    }
    db.media.upsert(item, "movie", "radarr", "radarr_main")
    row = db.media.execute_query(
        "SELECT id FROM media_cache WHERE tmdb_id=?", (tmdb,), fetch_one=True
    )
    return row["id"]


def _module(asset_types=None):
    m = object.__new__(UnmatchedAssets)
    m.logger = _logger()
    m.allowed_instances = set()
    m.plex_libraries = {}
    m.unmatched_media = m.unmatched_collections = []
    m.all_media = m.all_collections = []
    # config: one ARR instance, no ignore gates.
    m.config = SimpleNamespace(
        instances=["radarr_main"],
        ignore_unmonitored=False,
        ignore_folders=[],
        ignore_profiles=[],
        ignore_tags=[],
        ignore_titles=[],
        ignore_collections=[],
    )
    # asset_types drives which artwork types the view surfaces, and lives on the
    # asset_renamerr config (the matcher that writes the rows) — mirrors the real
    # FullConfig structure so the deselection path is exercised correctly.
    m.full_config = SimpleNamespace(
        tmdb=SimpleNamespace(apikey=""),
        asset_renamerr=SimpleNamespace(
            asset_types=asset_types or ["logo", "background", "squareart"]
        ),
    )
    return m


def test_artwork_stats_classifies_each_state(db):
    applied_id = _seed_movie(db, "Applied", 101)
    missing_id = _seed_movie(db, "Missing", 102)
    failed_id = _seed_movie(db, "Failed", 103)
    ignored_id = _seed_movie(db, "Ignored", 104)
    _seed_movie(db, "NoRow", 105)  # no logo row at all → must NOT be counted

    db.media_asset_matches.upsert(
        target_kind="media", target_id=applied_id, image_type="logo",
        source="tmdb", match_status="applied",
    )
    db.media_asset_matches.upsert(
        target_kind="media", target_id=missing_id, image_type="logo",
        match_status="missing", detail="no source artwork found",
    )
    db.media_asset_matches.upsert(
        target_kind="media", target_id=failed_id, image_type="logo",
        source="tmdb", match_status="failed",
    )
    db.media_asset_matches.set_ignored("media", ignored_id, "logo", True)

    logo = _module().get_artwork_stats(db)["types"]["logo"]

    assert logo["applied"] == 1
    assert logo["missing"] == 1
    assert logo["needs_review"] == 1       # failed → review
    assert logo["ignored"] == 1
    # total counts only evaluated (row-backed) items — the no-row movie excluded
    assert logo["total"] == 4
    assert round(logo["percent_complete"], 1) == 25.0
    # no banner key
    assert "banner" not in _module().get_artwork_stats(db)["types"]


def test_artwork_no_rows_means_zero(db):
    """The blank-slate state (empty table, e.g. just after a reset): items exist
    in the library but no artwork rows → every type reports 0, nothing missing."""
    _seed_movie(db, "Alpha", 201)
    _seed_movie(db, "Bravo", 202)

    stats = _module().get_artwork_stats(db)
    for t in ("logo", "background", "squareart"):
        assert stats["types"][t]["total"] == 0
        assert stats["types"][t]["missing"] == 0
        assert stats["types"][t]["applied"] == 0
        assert stats["types"][t]["percent_complete"] == 0
    assert stats["summary"]["missing"] == 0
    assert stats["summary"]["needs_review"] == 0
    assert stats["summary"]["ignored"] == 0


def test_artwork_stats_ignored_excluded_from_missing(db):
    a = _seed_movie(db, "Alpha", 301)
    db.media_asset_matches.set_ignored("media", a, "logo", True)
    logo = _module().get_artwork_stats(db)["types"]["logo"]
    assert logo["ignored"] == 1
    assert logo["missing"] == 0  # an ignored item is not also counted missing


def test_artwork_needs_review_carries_failure_reason(db):
    """A failed apply must surface WHY in the needs_review item so the UI can
    explain itself instead of just saying 'failed'."""
    a = _seed_movie(db, "Alpha", 401)
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=a,
        image_type="logo",
        source="tmdb",
        match_status="failed",
        detail="not found in any configured Plex library",
    )
    review = _module().get_artwork_stats(db)["types"]["logo"]["needs_review_items"]
    assert len(review) == 1
    assert review[0]["reason"] == "not found in any configured Plex library"
    assert review[0]["match_status"] == "failed"


def test_artwork_stats_per_media_grouping(db):
    """One row per media item, with the artwork types it lacks grouped into
    missing/failed/ignored arrays (the per-media table model)."""
    a = _seed_movie(db, "Alpha", 501)  # logo applied, bg missing
    b = _seed_movie(db, "Bravo", 502)  # logo failed, square ignored, bg missing

    db.media_asset_matches.upsert(
        target_kind="media", target_id=a, image_type="logo", match_status="applied"
    )
    db.media_asset_matches.upsert(
        target_kind="media", target_id=a, image_type="background",
        match_status="missing",
    )
    db.media_asset_matches.upsert(
        target_kind="media", target_id=b, image_type="logo",
        match_status="failed", detail="not found in Plex",
    )
    db.media_asset_matches.upsert(
        target_kind="media", target_id=b, image_type="background",
        match_status="missing",
    )
    db.media_asset_matches.set_ignored("media", b, "squareart", True)

    media = _module().get_artwork_stats(db)["media"]

    alpha = next(r for r in media["unmatched"] if r["id"] == a)
    assert alpha["missing"] == ["background"]  # logo applied → not missing
    assert alpha["failed"] == [] and alpha["ignored_types"] == []

    bravo = next(r for r in media["unmatched"] if r["id"] == b)
    assert bravo["missing"] == ["background"]
    assert bravo["failed"] == ["logo"]
    assert bravo["reasons"]["logo"] == "not found in Plex"
    assert bravo["ignored_types"] == ["squareart"]

    # Bravo appears in needs_review (failed logo) and ignored (squareart) too
    assert any(r["id"] == b for r in media["needs_review"])
    assert any(r["id"] == b for r in media["ignored"])


def test_artwork_deselected_type_is_excluded(db):
    """A type not in the module's asset_types must not appear in the view, even
    if stray rows for it exist."""
    a = _seed_movie(db, "Alpha", 601)
    db.media_asset_matches.upsert(
        target_kind="media", target_id=a, image_type="logo", match_status="missing"
    )
    db.media_asset_matches.upsert(
        target_kind="media", target_id=a, image_type="squareart",
        match_status="missing",
    )

    stats = _module(asset_types=["logo", "background"]).get_artwork_stats(db)
    assert "squareart" not in stats["types"]
    assert "logo" in stats["types"] and "background" in stats["types"]
    assert stats["types"]["logo"]["missing"] == 1


def test_artwork_stats_empty_universe(db):
    stats = _module().get_artwork_stats(db)
    assert stats["types"]["logo"]["total"] == 0
    assert stats["types"]["logo"]["percent_complete"] == 0
    assert stats["summary"]["missing"] == 0
