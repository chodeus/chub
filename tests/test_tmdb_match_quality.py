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
        self.breaker_tripped = False
        self.breaker_reason = ""

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


def test_verify_skips_on_transient_failure(tmp_path):
    """A transient TMDB failure (get_details -> None) must NOT flag the row as
    'not found' — that was the Married-with-Children false positive."""
    db = _db(tmp_path)
    try:
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key,asset_type,title,normalized_title,tmdb_id,instance_name) "
            "VALUES ('k','show','Married with Children','marriedwithchildren',4239,'sonarr')"
        )
        fake = _FakeClient({4239: None})  # transient
        counts = tmdb._verify_and_hydrate(db, fake, StubLogger(), None, 100)
        assert counts["id_mismatches"] == 0
        row = db.media.execute_query(
            "SELECT match_status FROM media_cache WHERE tmdb_id=4239", fetch_one=True
        )
        assert row["match_status"] != "needs_review"
    finally:
        db.__exit__(None, None, None)


def test_verify_flags_genuine_not_found(tmp_path):
    """A genuine 404 (verified=False) SHOULD flag the row."""
    db = _db(tmp_path)
    try:
        db.media.execute_query(
            "INSERT INTO media_cache (identity_key,asset_type,title,normalized_title,tmdb_id,instance_name) "
            "VALUES ('k','movie','Ghost Movie','ghostmovie',99999999,'radarr')"
        )
        fake = _FakeClient(
            {99999999: {"title": None, "original_title": None, "year": None, "alternative_titles": [], "verified": False}}
        )
        counts = tmdb._verify_and_hydrate(db, fake, StubLogger(), None, 100)
        assert counts["id_mismatches"] == 1
        row = db.media.execute_query(
            "SELECT match_status FROM media_cache WHERE tmdb_id=99999999", fetch_one=True
        )
        assert row["match_status"] == "needs_review"
    finally:
        db.__exit__(None, None, None)


class _BoomSession:
    """Fake requests.Session whose .get always fails like a TMDB outage."""

    def __init__(self):
        self.calls = 0

    def get(self, *_a, **_k):
        self.calls += 1
        raise tmdb.requests.ConnectionError("TMDB unreachable")


def test_circuit_breaker_trips_and_short_circuits(tmp_path, monkeypatch):
    """After BREAKER_THRESHOLD consecutive outages the client stops calling TMDB
    for the rest of the run, logs the outage exactly once, and fails fast."""
    monkeypatch.setattr(tmdb.time, "sleep", lambda *_a, **_k: None)  # no real backoff
    db = _db(tmp_path)
    logger = StubLogger()
    try:
        client = tmdb.TMDBClient(TMDBConfig(apikey="key"), db, logger)
        boom = _BoomSession()
        client._local.session = boom

        for _ in range(client.BREAKER_THRESHOLD):
            assert client._request_with_retry("http://x", {}, what="row") is None

        assert client.breaker_tripped is True
        outage_logs = [m for m in logger.messages["error"] if "appears to be down" in m]
        assert len(outage_logs) == 1  # logged once, not per remaining row

        calls_before = boom.calls
        assert client._request_with_retry("http://x", {}, what="next") is None
        assert boom.calls == calls_before  # short-circuited — no new HTTP attempts
    finally:
        db.__exit__(None, None, None)


def test_circuit_breaker_resets_on_success(tmp_path, monkeypatch):
    """A real TMDB response resets the consecutive-failure count, so isolated
    blips never trip the breaker."""
    monkeypatch.setattr(tmdb.time, "sleep", lambda *_a, **_k: None)
    db = _db(tmp_path)
    try:
        client = tmdb.TMDBClient(TMDBConfig(apikey="key"), db, StubLogger())

        class _Resp:
            status_code = 200

            def json(self):
                return {}

        class _Flaky:
            fail = True

            def get(self, *_a, **_k):
                if self.fail:
                    raise tmdb.requests.ConnectionError("blip")
                return _Resp()

        flaky = _Flaky()
        client._local.session = flaky

        for _ in range(client.BREAKER_THRESHOLD - 1):
            client._request_with_retry("http://x", {}, what="row")
        assert client.breaker_tripped is False

        flaky.fail = False
        assert client._request_with_retry("http://x", {}, what="ok") is not None

        flaky.fail = True
        for _ in range(client.BREAKER_THRESHOLD - 1):
            client._request_with_retry("http://x", {}, what="row")
        assert client.breaker_tripped is False  # reset means it takes a full run to trip
    finally:
        db.__exit__(None, None, None)
