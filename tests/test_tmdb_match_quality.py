"""Tests for the optional TMDB/fuzzy match-quality pass in backend/util/tmdb.py.

Network is never hit — TMDB calls go through a fake client stub.
"""

import json

from backend.util import tmdb
from backend.util.config import TMDBConfig
from backend.util.database import ChubDB
from tests.conftest import StubLogger


def _db(tmp_path):
    db = ChubDB(logger=StubLogger(), db_path=str(tmp_path / "mq.db"), quiet=True)
    db.__enter__()
    db._ensure_schema_initialized()
    return db


class _FakeClient:
    """Stand-in for TMDBClient.get_details keyed by tmdb_id."""

    def __init__(self, table):
        self.table = table

    def get_details(self, tmdb_id, media_type):
        return self.table.get(int(tmdb_id))


def test_run_match_quality_empty_db_is_zeros(tmp_path):
    db = _db(tmp_path)
    try:
        summary = tmdb.run_match_quality(db, TMDBConfig(), StubLogger())
        assert summary == {
            "verified": 0,
            "id_mismatches": 0,
            "akas_hydrated": 0,
            "fuzzy_flagged": 0,
        }
    finally:
        db.__exit__(None, None, None)


def test_run_match_quality_runs_fuzzy_without_apikey(tmp_path):
    """Fuzzy near-miss flagging is local and must run even with no TMDB key,
    while the TMDB-backed verify/hydrate stay at zero."""
    db = _db(tmp_path)
    try:
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key,asset_type,title,normalized_title,instance_name,match_status) "
            "VALUES ('k','movie','Spider Man','spiderman','radarr','unmatched')"
        )
        db.poster.execute_query(
            "INSERT INTO poster_cache (asset_type,title,normalized_title,year) "
            "VALUES ('movie','Spider-Man','spidermann',2002)"
        )
        summary = tmdb.run_match_quality(db, TMDBConfig(), StubLogger())
        assert summary["fuzzy_flagged"] == 1
        assert summary["verified"] == 0
        assert summary["akas_hydrated"] == 0
    finally:
        db.__exit__(None, None, None)


def test_fuzzy_flags_near_miss(tmp_path):
    db = _db(tmp_path)
    try:
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key,asset_type,title,normalized_title,instance_name,match_status) "
            "VALUES ('k','movie','Spider Man','spiderman','radarr','unmatched')"
        )
        db.poster.execute_query(
            "INSERT INTO poster_cache (asset_type,title,normalized_title,year) "
            "VALUES ('movie','Spider-Man','spidermann',2002)"
        )
        flagged = tmdb._fuzzy_flag_unmatched(db, StubLogger(), 100)
        assert flagged == 1
        row = db.media.execute_query(
            "SELECT match_status, match_reason FROM media_cache WHERE normalized_title='spiderman'",
            fetch_one=True,
        )
        assert row["match_status"] == "needs_review"
        assert "Fuzzy suggestion" in row["match_reason"]
    finally:
        db.__exit__(None, None, None)


def test_fuzzy_ignores_already_matched(tmp_path):
    db = _db(tmp_path)
    try:
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key,asset_type,title,normalized_title,instance_name,match_status) "
            "VALUES ('k','movie','Spider Man','spiderman','radarr','matched')"
        )
        db.poster.execute_query(
            "INSERT INTO poster_cache (asset_type,title,normalized_title,year) "
            "VALUES ('movie','Spider-Man','spidermann',2002)"
        )
        assert tmdb._fuzzy_flag_unmatched(db, StubLogger(), 100) == 0
    finally:
        db.__exit__(None, None, None)


def test_verify_flags_id_mismatch_and_hydrates_akas(tmp_path):
    db = _db(tmp_path)
    try:
        # Row claims tmdb 999 but TMDB says that id is a different movie.
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key,asset_type,title,normalized_title,tmdb_id,instance_name) "
            "VALUES ('k','movie','Real Movie','realmovie',999,'radarr')"
        )
        fake = _FakeClient(
            {
                999: {
                    "title": "Totally Different Film",
                    "original_title": "Totally Different Film",
                    "year": 1999,
                    "alternative_titles": ["Some AKA"],
                    "verified": True,
                }
            }
        )
        counts = tmdb._verify_and_hydrate(db, fake, StubLogger(), None, 100)
        assert counts["verified"] == 1
        assert counts["id_mismatches"] == 1
        row = db.media.execute_query(
            "SELECT match_status FROM media_cache WHERE tmdb_id=999", fetch_one=True
        )
        assert row["match_status"] == "needs_review"
    finally:
        db.__exit__(None, None, None)


def test_verify_matching_title_hydrates_without_flag(tmp_path):
    db = _db(tmp_path)
    try:
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key,asset_type,title,normalized_title,tmdb_id,instance_name) "
            "VALUES ('k','movie','Inception','inception',27205,'radarr')"
        )
        fake = _FakeClient(
            {
                27205: {
                    "title": "Inception",
                    "original_title": "Inception",
                    "year": 2010,
                    "alternative_titles": ["Origen", "Origine"],
                    "verified": True,
                }
            }
        )
        counts = tmdb._verify_and_hydrate(db, fake, StubLogger(), None, 100)
        assert counts["id_mismatches"] == 0
        assert counts["akas_hydrated"] == 1
        row = db.media.execute_query(
            "SELECT match_status, normalized_alternate_titles FROM media_cache WHERE tmdb_id=27205",
            fetch_one=True,
        )
        # title matched -> not flagged
        assert row["match_status"] != "needs_review"
        akas = json.loads(row["normalized_alternate_titles"] or "[]")
        assert "origen" in akas
    finally:
        db.__exit__(None, None, None)


def test_tmdb_details_cache_roundtrip(tmp_path):
    db = _db(tmp_path)
    try:
        db.tmdb_details_cache.put(
            27205,
            "movie",
            title="Inception",
            year=2010,
            alternative_titles=["Origen"],
            verified=True,
        )
        hit, details = db.tmdb_details_cache.get(27205, "movie", 60)
        assert hit is True
        assert details["title"] == "Inception"
        assert details["alternative_titles"] == ["Origen"]
        # negative cache
        db.tmdb_details_cache.put(404404, "movie", verified=False)
        hit2, details2 = db.tmdb_details_cache.get(404404, "movie", 60)
        assert hit2 is True
        assert details2["verified"] is False
    finally:
        db.__exit__(None, None, None)
