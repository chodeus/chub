"""Re-sync (upsert ON CONFLICT) must refresh *arr-sourced fields like title."""

import os
import tempfile

import pytest

from backend.util.database import ChubDB
from backend.util.normalization import normalize_titles
from tests.conftest import StubLogger


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    d = ChubDB(logger=StubLogger(), db_path=path, quiet=True)
    d.__enter__()
    d._ensure_schema_initialized()
    try:
        yield d
    finally:
        d.__exit__(None, None, None)
        try:
            os.unlink(path)
        except OSError:
            pass


def _movie(title, year="2026"):
    return {
        "title": title,
        "normalized_title": normalize_titles(title),
        "year": year,
        "tmdb_id": 949536,
        "imdb_id": "tt18212138",
        "alternate_titles": [],
        "normalized_alternate_titles": [],
    }


def test_upsert_refreshes_retitled_movie(db):
    """A movie retitled in Radarr (same id) must update title AND year on the
    next sync — not keep the stale title while normalized_title moves on.
    Regression: 'Hard Matter' stayed as the display title after the film was
    renamed to 'Kill Code', leaving title/normalized_title inconsistent and
    breaking matching."""
    db.media.upsert(_movie("Hard Matter"), "movie", "radarr", "radarr_main")
    row = db.media.execute_query(
        "SELECT title, normalized_title FROM media_cache WHERE tmdb_id=949536",
        fetch_one=True,
    )
    assert row["title"] == "Hard Matter"

    # Radarr renames it; re-sync (same imdb/tmdb id -> same identity_key).
    db.media.upsert(_movie("Kill Code", year="2027"), "movie", "radarr", "radarr_main")
    row = db.media.execute_query(
        "SELECT title, normalized_title, year FROM media_cache WHERE tmdb_id=949536",
        fetch_one=True,
    )
    assert row["title"] == "Kill Code"
    assert row["normalized_title"] == "killcode"
    assert str(row["year"]) == "2027"
    # title and normalized_title stay consistent
    assert row["normalized_title"] == normalize_titles(row["title"])


def test_upsert_preserves_match_state_on_resync(db):
    """Re-sync must NOT clobber CHUB's own match-state fields."""
    db.media.upsert(_movie("Hard Matter"), "movie", "radarr", "radarr_main")
    mid = db.media.execute_query(
        "SELECT id FROM media_cache WHERE tmdb_id=949536", fetch_one=True
    )["id"]
    db.media.execute_query(
        "UPDATE media_cache SET matched=1, original_file='/p.jpg' WHERE id=?", (mid,)
    )
    db.media.upsert(_movie("Kill Code"), "movie", "radarr", "radarr_main")
    row = db.media.get_by_id(mid)
    assert row["matched"] == 1
    assert row["original_file"] == "/p.jpg"
    assert row["title"] == "Kill Code"


def test_upsert_refreshes_changed_secondary_id(db):
    """When the row is keyed on imdb and the tvdb id changes on re-sync, the
    stale secondary id must be refreshed (TVDb re-issues ids)."""
    item = {
        "title": "Some Show",
        "normalized_title": normalize_titles("Some Show"),
        "year": "2020",
        "imdb_id": "tt9000000",
        "tvdb_id": 100,
        "tmdb_id": None,
        "alternate_titles": [],
        "normalized_alternate_titles": [],
    }
    db.media.upsert(item, "show", "sonarr", "sonarr_main")
    item2 = {**item, "tvdb_id": 200}  # same imdb key, new tvdb
    db.media.upsert(item2, "show", "sonarr", "sonarr_main")
    row = db.media.execute_query(
        "SELECT tvdb_id, imdb_id FROM media_cache WHERE imdb_id='tt9000000'",
        fetch_one=True,
    )
    assert row["tvdb_id"] == 200


def test_sync_prunes_row_when_identity_id_changes(db):
    """If the *identity* id changes (here tmdb, with no imdb), sync replaces the
    old row with a fresh one — no duplicate left behind."""
    base = {
        "title": "Identity Mover",
        "normalized_title": normalize_titles("Identity Mover"),
        "year": "2026",
        "imdb_id": None,
        "tvdb_id": None,
        "alternate_titles": [],
        "normalized_alternate_titles": [],
    }
    db.media.sync_for_instance(
        "radarr_main", "radarr", "movie", [{**base, "tmdb_id": 111}]
    )
    # Re-sync: same movie, tmdb id re-issued as 222.
    db.media.sync_for_instance(
        "radarr_main", "radarr", "movie", [{**base, "tmdb_id": 222}]
    )
    rows = db.media.execute_query(
        "SELECT tmdb_id FROM media_cache WHERE instance_name='radarr_main' AND asset_type='movie'",
        fetch_all=True,
    )
    assert len(rows) == 1  # old tmdb:111 row pruned, not duplicated
    assert rows[0]["tmdb_id"] == 222


def test_collection_upsert_refreshes_changed_id(db):
    """A collection re-linked to a different TMDb id (same title/library) must
    refresh the id on re-sync rather than keep the stale one."""
    rec = {
        "title": "Marvel Collection",
        "normalized_title": normalize_titles("Marvel Collection"),
        "year": None,
        "tmdb_id": 100,
        "tvdb_id": None,
        "imdb_id": None,
        "folder": "/c",
        "library_name": "Movies",
    }
    db.collection.upsert(dict(rec), "plex_main")
    db.collection.upsert({**rec, "tmdb_id": 200}, "plex_main")
    row = db.collection.execute_query(
        "SELECT tmdb_id FROM collections_cache WHERE title='Marvel Collection'",
        fetch_one=True,
    )
    assert row["tmdb_id"] == 200
