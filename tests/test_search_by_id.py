"""Asset (poster_cache) and library (media_cache) search must accept an
id pasted from a filename tag — {tmdb-…}/{tvdb-…}/{imdb-tt…} — or a bare
IMDb id, in addition to title matching."""

import os
import tempfile

import pytest

from backend.util.database import ChubDB
from backend.util.helper import parse_search_id
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
            pass  # temp file already gone — nothing to clean up


def test_parse_search_id_forms():
    assert parse_search_id("tmdb-286532") == (286532, None, None)
    assert parse_search_id("{tmdb-286532}") == (286532, None, None)
    assert parse_search_id("tvdb-417373") == (None, 417373, None)
    assert parse_search_id("imdb-tt0910885") == (None, None, "tt0910885")
    assert parse_search_id("tt0910885") == (None, None, "tt0910885")  # bare imdb
    assert parse_search_id("TT0910885") == (None, None, "tt0910885")  # case-folded
    assert parse_search_id("Shaun of the Dead") == (None, None, None)
    assert parse_search_id("") == (None, None, None)


def _titles(result):
    return {r["title"] for r in result["items"]}


def test_media_search_by_id(db):
    db.media.upsert(
        {
            "title": "Hard Matter",
            "normalized_title": normalize_titles("Hard Matter"),
            "year": "2026",
            "tmdb_id": 949536,
            "tvdb_id": 417373,
            "imdb_id": "tt18212138",
            "alternate_titles": [],
            "normalized_alternate_titles": [],
        },
        "movie",
        "radarr",
        "radarr_main",
    )
    for q in (
        "tmdb-949536",
        "{tmdb-949536}",
        "tvdb-417373",
        "tt18212138",
        "imdb-tt18212138",
    ):
        assert _titles(db.media.search(query=q)) == {"Hard Matter"}, q
    # title search unaffected
    assert _titles(db.media.search(query="Hard")) == {"Hard Matter"}
    # a non-matching id / title returns nothing
    assert _titles(db.media.search(query="tmdb-000000")) == set()
    assert _titles(db.media.search(query="Nonexistent")) == set()


def test_poster_search_by_id(db):
    db.poster.upsert(
        {
            "title": "Shaun of the Dead",
            "normalized_title": normalize_titles("Shaun of the Dead"),
            "year": 2004,
            "tmdb_id": 747,
            "tvdb_id": None,
            "imdb_id": "tt0365748",
            "season_number": None,
            "folder": "Owner",
            "file": "/src/shaun.png",
            "style": None,
            "priority": 0,
            "image_type": "poster",
            "asset_type": "movie",
        }
    )
    for q in ("tmdb-747", "{tmdb-747}", "tt0365748", "imdb-tt0365748"):
        assert _titles(db.poster.search(query=q)) == {"Shaun of the Dead"}, q
    assert _titles(db.poster.search(query="Shaun")) == {"Shaun of the Dead"}
    assert _titles(db.poster.search(query="tmdb-999999")) == set()


def test_poster_browse_by_id(db):
    db.poster.upsert(
        {
            "title": "Shaun of the Dead",
            "normalized_title": normalize_titles("Shaun of the Dead"),
            "year": 2004,
            "tmdb_id": 747,
            "tvdb_id": None,
            "imdb_id": "tt0365748",
            "season_number": None,
            "folder": "Owner",
            "file": "/src/shaun.png",
            "style": None,
            "priority": 0,
            "image_type": "poster",
            "asset_type": "movie",
        }
    )
    for q in ("tmdb-747", "{tmdb-747}", "tt0365748", "imdb-tt0365748"):
        assert _titles(db.poster.browse(query=q)) == {"Shaun of the Dead"}, q
    # title and wildcard search unaffected
    assert _titles(db.poster.browse(query="Shaun")) == {"Shaun of the Dead"}
    assert _titles(db.poster.browse(query="Shaun*")) == {"Shaun of the Dead"}
    # a non-matching id / title returns nothing
    assert _titles(db.poster.browse(query="tmdb-999999")) == set()
    assert _titles(db.poster.browse(query="Nonexistent")) == set()
