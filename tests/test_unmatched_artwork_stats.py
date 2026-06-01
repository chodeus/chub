"""Tests for UnmatchedAssets.get_artwork_stats — per-image-type coverage
(applied / missing / needs_review / ignored) derived from media_asset_matches.
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


def _module():
    m = object.__new__(UnmatchedAssets)
    m.logger = _logger()
    m.allowed_instances = set()
    m.plex_libraries = {}
    m.unmatched_media = m.unmatched_collections = []
    m.all_media = m.all_collections = []
    # config: one ARR instance, no ignore gates
    m.config = SimpleNamespace(
        instances=["radarr_main"],
        ignore_unmonitored=False,
        ignore_folders=[],
        ignore_profiles=[],
        ignore_tags=[],
        ignore_titles=[],
        ignore_collections=[],
    )
    m.full_config = SimpleNamespace(tmdb=SimpleNamespace(apikey=""))
    return m


def test_artwork_stats_classifies_each_state(db):
    a = _seed_movie(db, "Alpha", 101)  # logo applied, bg missing
    b = _seed_movie(db, "Bravo", 102)  # logo missing, bg ignored
    c = _seed_movie(db, "Charlie", 103)  # logo needs_review

    db.media_asset_matches.upsert(
        target_kind="media", target_id=a, image_type="logo",
        source="tmdb", match_status="applied",
    )
    db.media_asset_matches.set_ignored("media", b, "background", True)
    db.media_asset_matches.upsert(
        target_kind="media", target_id=c, image_type="logo",
        source="tmdb", match_status="failed",
    )

    m = _module()
    stats = m.get_artwork_stats(db)
    logo = stats["types"]["logo"]
    bg = stats["types"]["background"]

    assert logo["total"] == 3
    assert logo["applied"] == 1            # Alpha
    assert logo["needs_review"] == 1       # Charlie (failed → review)
    assert logo["missing"] == 1            # Bravo
    assert logo["ignored"] == 0
    assert round(logo["percent_complete"], 1) == round(1 / 3 * 100, 1)

    assert bg["ignored"] == 1              # Bravo bg ignored
    assert bg["missing"] == 2              # Alpha + Charlie bg missing
    assert bg["applied"] == 0

    # squareart present as a type, all missing (none applied)
    assert stats["types"]["squareart"]["total"] == 3
    assert stats["types"]["squareart"]["missing"] == 3
    # no banner key
    assert "banner" not in stats["types"]


def test_artwork_stats_ignored_excluded_from_missing(db):
    a = _seed_movie(db, "Alpha", 201)
    db.media_asset_matches.set_ignored("media", a, "logo", True)
    m = _module()
    logo = m.get_artwork_stats(db)["types"]["logo"]
    assert logo["ignored"] == 1
    assert logo["missing"] == 0  # an ignored item is not also counted missing


def test_artwork_stats_empty_universe(db):
    m = _module()
    stats = m.get_artwork_stats(db)
    assert stats["types"]["logo"]["total"] == 0
    assert stats["types"]["logo"]["percent_complete"] == 0
    assert stats["summary"]["missing"] == 0
