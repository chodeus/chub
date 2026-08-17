"""Tests for the system.py / jobs.py query methods that moved into the DB interfaces.

Two layers: the new DbMaintenance / SystemHealth / DBWorker / cache methods against
a real temp database, then the system handlers whose contract nothing else pinned.
"""

import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util.config import ConfigError  # noqa: E402
from backend.util.database import ChubDB  # noqa: E402


class _StubLog:
    """Swallows every log call; get_adapter returns itself."""

    def __getattr__(self, _):
        """Any log method is a no-op."""
        return lambda *a, **k: None

    def get_adapter(self, *_a, **_kw):
        """Adapters are the same sink."""
        return self


@pytest.fixture
def db(tmp_path):
    """A ChubDB backed by a real (temporary) sqlite file."""
    with ChubDB(_StubLog(), db_path=str(tmp_path / "chub.db")) as database:
        yield database


def _client(db):
    """Mount the system router on a bare app carrying main.py's ConfigError handler."""
    import backend.api.main as apimain
    import backend.api.system as system

    app = FastAPI()
    app.state.logger = _StubLog()
    app.state.db = db
    app.add_exception_handler(ConfigError, apimain.handle_config_error)
    app.include_router(system.router)
    return TestClient(app, raise_server_exceptions=False)


def _seed_job(db, status="pending", received_at="2026-01-02T00:00:00+00:00", **fields):
    """Insert one jobs row with an exact status/received_at and return its id."""
    row = {
        "type": "module_run",
        "status": status,
        "received_at": received_at,
        "payload": "{}",
        **fields,
    }
    keys = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    return db.worker.execute_query(
        f"INSERT INTO jobs ({keys}) VALUES ({marks})",
        tuple(row.values()),
        last_row_id=True,
    )


def _seed_snapshot(db, instance, snapshot_at, status="healthy", service="radarr"):
    """Insert one system_health_snapshots row and return its id."""
    return db.worker.execute_query(
        "INSERT INTO system_health_snapshots "
        "(snapshot_at, service, instance_name, status) VALUES (?, ?, ?, ?)",
        (snapshot_at, service, instance, status),
        last_row_id=True,
    )


def _seed_media(db, title, instance_name="radarr", matched=None):
    """Upsert one media row, optionally flipping its matched flag, and return its id."""
    db.media.upsert(
        {"title": title, "normalized_title": title.lower(), "year": 2021},
        "movie",
        "radarr",
        instance_name,
    )
    row = db.media.execute_query(
        "SELECT id FROM media_cache WHERE title=? AND instance_name=?",
        (title, instance_name),
        fetch_one=True,
    )
    if matched is not None:
        db.media.execute_query(
            "UPDATE media_cache SET matched=? WHERE id=?", (matched, row["id"])
        )
    return row["id"]


# --- DbMaintenance.ping -----------------------------------------------------


def test_ping_round_trips_a_live_database(db):
    """A usable DB answers True rather than a falsy 'probably fine'."""
    assert db.maintenance.ping() is True


def test_ping_raises_on_an_unusable_database(tmp_path):
    """/api/health reports 'error' only because ping propagates — never swallow it."""
    import sqlite3

    from backend.util.database import DbMaintenance

    broken = tmp_path / "broken.db"
    broken.write_bytes(b"this is not a sqlite file" * 100)
    # Built directly: ChubDB's schema init would raise before ping ever ran.
    maintenance = DbMaintenance(logger=_StubLog(), db_path=str(broken))

    with pytest.raises(sqlite3.DatabaseError):
        maintenance.ping()


# --- DbMaintenance.table_row_counts / page_stats / list_migrations ----------


def test_table_row_counts_reports_seeded_rows(db):
    """Counts come from the tables themselves, not from a cached figure."""
    for title in ("Dune", "Sicario"):
        _seed_media(db, title)

    counts = {t["name"]: t["rows"] for t in db.maintenance.table_row_counts()}
    assert counts["media_cache"] == 2
    assert counts["jobs"] == 0


def test_table_row_counts_hides_sqlite_internal_tables(db):
    """The allowlist is the filter — enumerating sqlite_master would leak these."""
    _seed_job(db)  # jobs has an INTEGER PRIMARY KEY, so sqlite_sequence may exist

    names = {t["name"] for t in db.maintenance.table_row_counts()}
    assert not any(n.startswith("sqlite_") for n in names)
    assert names <= set(db.maintenance.STATS_TABLES)


def test_table_row_counts_skips_a_table_the_schema_lacks(db):
    """An allowlisted-but-absent table is skipped, not counted into an error."""
    db.maintenance.execute_query("DROP TABLE gdrive_stats")

    names = {t["name"] for t in db.maintenance.table_row_counts()}
    assert "gdrive_stats" not in names
    assert "media_cache" in names


def test_page_stats_derives_its_byte_totals_from_the_page_size(db):
    """total_bytes/free_bytes are page_size multiplied by the right counter."""
    stats = db.maintenance.page_stats()

    assert stats["page_size"] > 0 and stats["page_count"] > 0
    assert stats["total_bytes"] == stats["page_size"] * stats["page_count"]
    assert stats["free_bytes"] == stats["page_size"] * stats["freelist_count"]


def test_list_migrations_is_newest_first(db):
    """Ordering is applied_at DESC, so an older entry can't lead the list."""
    db.maintenance.execute_query(
        "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
        ("20260101_old", "2026-01-01T00:00:00"),
    )
    db.maintenance.execute_query(
        "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
        ("20260202_new", "2026-02-02T00:00:00"),
    )

    # Schema init writes its own real migrations, so compare positions not slices.
    names = [m["name"] for m in db.maintenance.list_migrations()]
    assert names.index("20260202_new") < names.index("20260101_old")


def test_list_migrations_is_empty_when_the_table_is_absent(db):
    """The existence guard keeps a pre-migrations database from erroring."""
    db.maintenance.execute_query("DROP TABLE schema_migrations")

    assert db.maintenance.list_migrations() == []


# --- DbMaintenance.vacuum ---------------------------------------------------


def test_vacuum_releases_the_free_pages_a_bulk_delete_left(db):
    """VACUUM is what empties the freelist; a no-op would leave it populated."""
    for i in range(500):
        db.poster.execute_query(
            "INSERT INTO poster_cache (file, title, year, asset_type, "
            "normalized_title) VALUES (?, ?, 2020, 'movie', ?)",
            (f"/src/p{i}.jpg", f"Movie {i}", f"movie{i}"),
        )
    db.poster.execute_query("DELETE FROM poster_cache")
    assert db.maintenance.page_stats()["freelist_count"] > 0

    db.maintenance.vacuum()

    assert db.maintenance.page_stats()["freelist_count"] == 0


# --- SystemHealth -----------------------------------------------------------


def test_recent_snapshots_is_newest_first_under_the_limit(db):
    """Newest-first ordering plus the LIMIT decide the window."""
    for at in ("2026-01-01T00:00:00", "2026-01-03T00:00:00", "2026-01-02T00:00:00"):
        _seed_snapshot(db, "radarr-main", at)

    rows = db.system_health.recent_snapshots(limit=2)
    assert [r["snapshot_at"] for r in rows] == [
        "2026-01-03T00:00:00",
        "2026-01-02T00:00:00",
    ]


def test_recent_snapshots_scopes_to_one_instance(db):
    """The instance filter is a WHERE, not a post-filter on an unbounded read."""
    _seed_snapshot(db, "radarr-main", "2026-01-01T00:00:00")
    _seed_snapshot(db, "sonarr-main", "2026-01-02T00:00:00")

    rows = db.system_health.recent_snapshots(instance="radarr-main")
    assert [r["instance_name"] for r in rows] == ["radarr-main"]


def test_latest_per_instance_keeps_one_row_per_instance(db):
    """The self-join collapses history to each instance's most recent probe."""
    _seed_snapshot(db, "radarr-main", "2026-01-01T00:00:00", status="unhealthy")
    _seed_snapshot(db, "radarr-main", "2026-01-05T00:00:00", status="healthy")
    _seed_snapshot(db, "sonarr-main", "2026-01-02T00:00:00", status="timeout")

    rows = db.system_health.latest_per_instance()
    assert len(rows) == 2  # the superseded radarr probe must not survive the join
    latest = {r["instance_name"]: r for r in rows}
    assert latest["radarr-main"]["status"] == "healthy"
    assert latest["sonarr-main"]["status"] == "timeout"


# --- DBWorker job reporting -------------------------------------------------


def test_count_by_status_counts_only_that_status(db):
    """The status is a bound parameter in the WHERE, not a filter on everything."""
    _seed_job(db, status="error")
    _seed_job(db, status="error")
    _seed_job(db, status="success")

    assert db.worker.count_by_status("error") == 2
    assert db.worker.count_by_status("cancelled") == 0


def test_count_by_status_since_groups_inside_the_window(db):
    """Only jobs at or after the cutoff are grouped, and each status keeps its own count."""
    _seed_job(db, status="error", received_at="2026-01-05T00:00:00+00:00")
    _seed_job(db, status="success", received_at="2026-01-05T00:00:00+00:00")
    _seed_job(db, status="success", received_at="2026-01-06T00:00:00+00:00")
    _seed_job(db, status="success", received_at="2025-12-01T00:00:00+00:00")

    counts = db.worker.count_by_status_since("2026-01-01T00:00:00+00:00")
    assert counts == {"error": 1, "success": 2}


def test_recent_failures_excludes_successes_and_pre_cutoff_rows(db):
    """Both halves of the WHERE matter: status='error' AND inside the window."""
    doomed = _seed_job(db, status="error", received_at="2026-01-05T00:00:00+00:00")
    _seed_job(db, status="success", received_at="2026-01-05T00:00:00+00:00")
    _seed_job(db, status="error", received_at="2025-01-01T00:00:00+00:00")

    rows = db.worker.recent_failures("2026-01-01T00:00:00+00:00")
    assert [r["id"] for r in rows] == [doomed]
    assert set(rows[0]) == {"id", "type", "payload", "error", "received_at"}


def test_recent_failures_breaks_received_at_ties_by_id(db):
    """A webhook burst shares received_at — without `, id DESC` the LIMIT is arbitrary."""
    ids = [
        _seed_job(db, status="error", received_at="2026-01-05T00:00:00+00:00")
        for _ in range(3)
    ]

    rows = db.worker.recent_failures("2026-01-01T00:00:00+00:00", limit=2)
    assert [r["id"] for r in rows] == [ids[2], ids[1]]


def test_jobs_of_type_since_filters_on_both_type_and_cutoff(db):
    """A module_run in the window and an old webhook are both excluded."""
    wanted = _seed_job(db, type="webhook", received_at="2026-01-05T00:00:00+00:00")
    _seed_job(db, type="module_run", received_at="2026-01-05T00:00:00+00:00")
    _seed_job(db, type="webhook", received_at="2025-01-01T00:00:00+00:00")

    rows = db.worker.jobs_of_type_since("webhook", "2026-01-01T00:00:00+00:00")
    assert [r["id"] for r in rows] == [wanted]


def test_cancel_running_job_reports_the_row_it_changed(db):
    """The count is the DB's rowcount, so a second cancel reports zero."""
    job = _seed_job(db, status="running")

    assert db.worker.cancel_running_job(job, "2026-01-05T00:00:00+00:00") == 1
    assert db.worker.cancel_running_job(job, "2026-01-05T00:00:00+00:00") == 0


def test_cancel_running_job_leaves_a_pending_job_alone(db):
    """`AND status='running'` is the guard — a queued job must not be cancelled."""
    pending = _seed_job(db, status="pending")

    assert db.worker.cancel_running_job(pending, "2026-01-05T00:00:00+00:00") == 0
    assert db.worker.get_job_by_id("jobs", pending)["status"] == "pending"


def test_job_reporting_refuses_a_table_outside_the_allowlist(db):
    """Every new jobs method runs _check_table, so a stray table name can't reach SQL."""
    for call in (
        lambda: db.worker.count_by_status("error", table_name="media_cache"),
        lambda: db.worker.count_by_status_since("2026-01-01", table_name="media_cache"),
        lambda: db.worker.recent_failures("2026-01-01", table_name="media_cache"),
        lambda: db.worker.jobs_of_type_since("x", "2026-01-01", table_name="media_cache"),
        lambda: db.worker.cancel_running_job(1, "2026-01-01", table_name="media_cache"),
    ):
        with pytest.raises(ValueError):
            call()


# --- MediaCache / CollectionCache counts ------------------------------------


def test_count_added_since_honours_the_created_at_cutoff(db):
    """created_at is stamped on first insert; the cutoff must actually filter."""
    _seed_media(db, "Dune")
    db.media.execute_query(
        "UPDATE media_cache SET created_at='2020-01-01 00:00:00' WHERE title='Dune'"
    )
    _seed_media(db, "Sicario")
    db.media.execute_query(
        "UPDATE media_cache SET created_at='2026-01-05 00:00:00' WHERE title='Sicario'"
    )

    assert db.media.count_added_since("2026-01-01 00:00:00") == 1
    assert db.media.count_added_since("2019-01-01 00:00:00") == 2


def test_count_added_since_counts_a_current_timestamp_row_against_an_iso_cutoff(db):
    """created_at is CURRENT_TIMESTAMP-shaped; the digest's ISO cutoff must still match it."""
    _seed_media(db, "Dune")
    db.media.execute_query(
        "UPDATE media_cache SET created_at='2026-01-05 18:30:00' WHERE title='Dune'"
    )
    _seed_media(db, "Sicario")
    db.media.execute_query(
        "UPDATE media_cache SET created_at='2026-01-05 03:00:00' WHERE title='Sicario'"
    )

    # ' ' sorts below 'T' at index 10, so a TEXT compare drops Dune despite it
    # being the later row. This is the exact cutoff shape system.py builds.
    assert db.media.count_added_since("2026-01-05T09:00:00.123456+00:00") == 1


def test_count_unmatched_counts_only_unmatched_media(db):
    """matched=0 is the filter; a matched row must not inflate the figure."""
    _seed_media(db, "Dune", matched=0)
    _seed_media(db, "Sicario", matched=1)

    assert db.media.count_unmatched() == 1


def test_collection_count_unmatched_counts_only_unmatched_collections(db):
    """The collections figure reads collections_cache, never media_cache."""
    db.collection.upsert({"title": "Marvel", "library_name": "Movies"}, "plex1")
    db.collection.upsert({"title": "DC", "library_name": "Movies"}, "plex1")
    marvel = db.collection.get_by_title_and_instance("Marvel", "plex1", "Movies")
    db.collection.execute_query(
        "UPDATE collections_cache SET matched=1 WHERE id=?", (marvel["id"],)
    )
    # Two unmatched media decoys, so reading the wrong table gives a wrong number.
    _seed_media(db, "Decoy", matched=0)
    _seed_media(db, "Decoy Two", matched=0)

    assert db.collection.count_unmatched() == 1


def test_count_by_instance_scopes_to_that_instance(db):
    """The instance name is in the WHERE — the count is not the whole table."""
    _seed_media(db, "Dune", instance_name="radarr-main")
    _seed_media(db, "Sicario", instance_name="radarr-main")
    _seed_media(db, "Arrival", instance_name="radarr-4k")

    assert db.media.count_by_instance("radarr-main") == 2
    assert db.media.count_by_instance("radarr-nope") == 0


# --- clear() rowcounts ------------------------------------------------------


def test_poster_clear_returns_the_rows_it_deleted(db):
    """The wipe reports its own rowcount, so a repeat wipe reports zero."""
    db.poster.execute_query(
        "INSERT INTO poster_cache (file, title, year, asset_type, normalized_title) "
        "VALUES ('/src/a.jpg', 'A', 2020, 'movie', 'a')"
    )

    assert db.poster.clear() == 1
    assert db.poster.clear() == 0


def test_artwork_clear_keep_ignored_counts_only_what_it_deleted(db):
    """A user_confirmed row survives, so it must not be counted as deleted."""
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=1,
        image_type="logo",
        match_status="applied",
    )
    db.media_asset_matches.set_ignored("media", 2, "background", True)
    db.media_asset_matches.set_user_confirmed("media", 3, "logo", True)

    assert db.media_asset_matches.clear(keep_ignored=True) == 1
    assert db.media_asset_matches.get_one("media", 2, "background")["ignored"] == 1
    assert db.media_asset_matches.get_one("media", 3, "logo")["user_confirmed"] == 1


# --- Route contracts not covered elsewhere ---------------------------------


def test_artwork_reset_route_reports_only_the_rows_it_deleted(db):
    """The response count comes from the DELETE, not from a wider pre-count."""
    db.media_asset_matches.upsert(
        target_kind="media", target_id=1, image_type="logo", match_status="applied"
    )
    db.media_asset_matches.set_user_confirmed("media", 3, "logo", True)

    body = _client(db).post("/api/system/db/artwork-matches/reset").json()
    assert body["data"]["deleted"] == 1


def test_poster_cache_clear_route_reports_the_deleted_rows(db):
    """The wipe count is the rowcount of the DELETE the route performed."""
    db.poster.execute_query(
        "INSERT INTO poster_cache (file, title, year, asset_type, normalized_title) "
        "VALUES ('/src/a.jpg', 'A', 2020, 'movie', 'a')"
    )

    body = _client(db).post("/api/system/db/poster-cache/clear").json()
    assert body["data"]["deleted"] == 1
    assert db.stats.count_poster_cache() == 0


def test_cleanup_candidates_route_reports_each_count_from_its_own_table(db):
    """errored_jobs / unmatched_media / unmatched_collections must not cross-wire."""
    # Deliberately distinct counts — equal ones would let a swapped pair pass.
    for _ in range(3):
        _seed_job(db, status="error")
    for title in ("Dune", "Sicario"):
        _seed_media(db, title, matched=0)
    _seed_media(db, "Arrival", matched=1)
    db.collection.upsert({"title": "Marvel", "library_name": "Movies"}, "plex1")

    data = _client(db).get("/api/system/cleanup-candidates").json()["data"]
    assert data == {
        "errored_jobs": 3,
        "unmatched_media": 2,
        "unmatched_collections": 1,
    }


def test_digest_route_reports_the_window_it_was_asked_for(db):
    """Jobs outside the ?days window are excluded from the counts and failures."""
    _seed_job(db, status="error", received_at="2020-01-01T00:00:00+00:00")
    _seed_job(db, status="success")  # dated 2026-01-02, far outside a 1-day window
    _seed_snapshot(db, "radarr-main", "2026-01-01T00:00:00")

    data = _client(db).get("/api/system/digest?days=1").json()["data"]
    assert data["window_days"] == 1
    assert data["job_counts"] == {}
    assert data["recent_failures"] == []
    assert [h["instance_name"] for h in data["latest_instance_health"]] == [
        "radarr-main"
    ]


def test_health_snapshots_route_clamps_its_limit(db):
    """limit is clamped into 1..500 before it reaches the query."""
    for i in range(3):
        _seed_snapshot(db, "radarr-main", f"2026-01-0{i + 1}T00:00:00")
    client = _client(db)

    zero = client.get("/api/system/health/snapshots?limit=0").json()
    assert len(zero["data"]["snapshots"]) == 1
    huge = client.get("/api/system/health/snapshots?limit=99999").json()
    assert len(huge["data"]["snapshots"]) == 3


def test_health_snapshots_route_filters_by_instance(db):
    """The ?instance query reaches the WHERE, not just the response message."""
    _seed_snapshot(db, "radarr-main", "2026-01-01T00:00:00")
    _seed_snapshot(db, "sonarr-main", "2026-01-02T00:00:00")

    body = _client(db).get("/api/system/health/snapshots?instance=sonarr-main").json()
    assert [s["instance_name"] for s in body["data"]["snapshots"]] == ["sonarr-main"]


def test_latest_per_instance_keeps_every_service_on_a_shared_instance(db):
    """Grouping by instance alone dropped whichever service probed less recently."""
    _seed_snapshot(db, "shared", "2026-01-05 10:00:00", service="radarr")
    _seed_snapshot(db, "shared", "2026-01-05 10:05:00", service="sonarr")

    rows = db.system_health.latest_per_instance()

    assert sorted(r["service"] for r in rows) == ["radarr", "sonarr"]


def test_latest_per_instance_returns_one_row_per_pair_on_a_timestamp_tie(db):
    """A scheduler pass writes identical snapshot_at values; id breaks the tie."""
    _seed_snapshot(db, "radarr1", "2026-01-05 10:00:00", status="healthy")
    newest = _seed_snapshot(db, "radarr1", "2026-01-05 10:00:00", status="error")

    rows = db.system_health.latest_per_instance()

    assert len(rows) == 1
    assert rows[0]["status"] == "error"  # highest id wins, deterministically
    assert newest  # the tie-breaking row is the one that was seeded last


def test_health_route_answers_503_when_the_database_is_unusable(db, monkeypatch):
    """Docker HEALTHCHECK curls -f this, so an unusable DB must not answer 200."""
    healthy = _client(db).get("/api/health")
    assert healthy.status_code == 200

    def _boom():
        raise RuntimeError("disk gone")

    monkeypatch.setattr(type(db.maintenance), "ping", lambda _self: _boom())
    resp = _client(db).get("/api/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["error_code"] == "DATABASE_UNAVAILABLE"
    assert body["data"]["checks"]["database"] == "error"  # diagnostics survive


def test_count_by_status_since_reads_the_cutoff_as_an_instant(db):
    """A caller-supplied offset cutoff must not shift the window via TEXT compare."""
    db.worker.execute_query(
        "INSERT INTO jobs (type, payload, status, received_at) VALUES (?,?,?,?)",
        ("webhook", "{}", "error", "2026-01-05 18:30:00"),
    )

    counts = db.worker.count_by_status_since("2026-01-05T09:00:00+00:00")

    assert counts.get("error") == 1


def _modules_client(db):
    """Mount the modules router the way _client mounts system's."""
    from backend.api import modules as modules_api

    app = FastAPI()
    app.state.logger = _StubLog()
    app.state.db = db
    app.include_router(modules_api.router)
    return TestClient(app, raise_server_exceptions=False)


def test_cancel_reports_conflict_when_the_job_stopped_first(db, monkeypatch):
    """cancel_running_job returning 0 means it finished — don't answer 'cancelling'."""
    job_id = db.worker.execute_query(
        "INSERT INTO jobs (type, payload, status, received_at) VALUES (?,?,?,?)",
        ("poster_renamerr", "{}", "running", "2026-01-05T10:00:00+00:00"),
        last_row_id=True,
    )
    # The handler imports it inside the function, so patch it at the source.
    monkeypatch.setattr(
        "backend.util.job_processor.request_cancellation", lambda _id: True
    )
    # The guarded UPDATE finds nothing: the job stopped between check and write.
    monkeypatch.setattr(
        type(db.worker), "cancel_running_job", lambda *_a, **_kw: 0
    )

    resp = _modules_client(db).delete(
        f"/api/modules/poster_renamerr/execution/{job_id}"
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "JOB_NOT_RUNNING"


def test_health_route_answers_503_when_there_is_no_database_handle(db):
    """No handle is as unserviceable as a failing ping — it must not pass the check."""
    from backend.api import system as system_api

    app = FastAPI()
    app.state.logger = _StubLog()  # state.db deliberately never set
    app.include_router(system_api.router)

    resp = TestClient(app, raise_server_exceptions=False).get("/api/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["error_code"] == "DATABASE_UNAVAILABLE"
    assert body["data"]["checks"]["database"] == "unavailable"
    assert body["data"]["status"] == "degraded"  # payload isn't claiming health


def test_record_snapshots_writes_a_pass_readably(db):
    """One scheduler pass lands atomically and reads back through the same mixin."""
    db.system_health.record_snapshots(
        [
            ("2026-01-05T10:00:00", "radarr", "radarr1", "healthy", 200, 42, None),
            ("2026-01-05T10:00:00", "sonarr", "sonarr1", "timeout", None, 3000, None),
        ]
    )

    rows = db.system_health.recent_snapshots()

    assert len(rows) == 2
    assert {r["status"] for r in rows} == {"healthy", "timeout"}


def test_record_snapshots_with_no_rows_is_a_noop(db):
    db.system_health.record_snapshots([])
    assert db.system_health.recent_snapshots() == []


def test_prune_snapshots_before_removes_only_older_rows(db):
    _seed_snapshot(db, "radarr1", "2026-01-01T10:00:00")
    _seed_snapshot(db, "radarr1", "2026-01-09T10:00:00")

    removed = db.system_health.prune_snapshots_before("2026-01-05T00:00:00")

    assert removed == 1
    kept = db.system_health.recent_snapshots()
    assert [r["snapshot_at"] for r in kept] == ["2026-01-09T10:00:00"]


def test_record_snapshots_raises_when_the_write_fails(db):
    """Fail loud: the scheduler's caller logs it — a swallow left dead
    instances looking merely un-probed."""
    db.worker.execute_query("DROP TABLE system_health_snapshots")

    with pytest.raises(Exception, match="system_health_snapshots"):
        db.system_health.record_snapshots(
            [("2026-01-05T10:00:00", "radarr", "radarr1", "healthy", 200, 1, None)]
        )
