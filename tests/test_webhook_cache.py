"""Tests for backend/util/database/webhook_cache.py — the persistent webhook
dedup window that coalesces Sonarr/Radarr retries (anti-flood / idempotency)."""

from types import SimpleNamespace

import pytest

from backend.util.database import ChubDB


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


def test_first_call_inserts_then_duplicate(db):
    # First sighting inserts and is NOT a duplicate; the immediate retry is.
    assert db.webhook_cache.is_duplicate("movie", "Dune") is False
    assert db.webhook_cache.is_duplicate("movie", "Dune") is True
    assert db.webhook_cache.count() == 1


def test_distinct_items_do_not_collide(db):
    assert db.webhook_cache.is_duplicate("movie", "A") is False
    assert db.webhook_cache.is_duplicate("movie", "B") is False
    # same name, different type is also distinct
    assert db.webhook_cache.is_duplicate("series", "A") is False
    assert db.webhook_cache.count() == 3


def test_expired_row_is_swept_and_not_duplicate(db):
    assert db.webhook_cache.is_duplicate("movie", "Dune", ttl_seconds=600) is False
    # ttl_seconds=0 makes the just-inserted row already past the cutoff, so it
    # is swept and the call is treated as a fresh sighting (not a duplicate).
    assert db.webhook_cache.is_duplicate("movie", "Dune", ttl_seconds=0) is False
    assert db.webhook_cache.count() == 1


def test_delete_reopens_dedup_window(db):
    assert db.webhook_cache.is_duplicate("movie", "Dune") is False
    assert db.webhook_cache.is_duplicate("movie", "Dune") is True
    db.webhook_cache.delete("movie", "Dune")
    assert db.webhook_cache.count() == 0
    # retry after enqueue failure is treated as a fresh sighting
    assert db.webhook_cache.is_duplicate("movie", "Dune") is False
    # delete of a missing row is a harmless no-op
    db.webhook_cache.delete("movie", "does-not-exist")


def test_clear_and_last_seen(db):
    assert db.webhook_cache.last_seen("movie", "Dune") is None
    db.webhook_cache.is_duplicate("movie", "Dune")
    assert db.webhook_cache.last_seen("movie", "Dune") is not None
    db.webhook_cache.clear()
    assert db.webhook_cache.count() == 0
    assert db.webhook_cache.last_seen("movie", "Dune") is None


def _conn_failing_insert(exc):
    """Connection whose DELETE/SELECT succeed and whose INSERT raises `exc`."""

    class _Cur:
        @staticmethod
        def fetchone():
            return None

    class _Conn:
        def execute(self, sql, *a, **k):
            if sql.strip().upper().startswith("INSERT"):
                raise exc
            return _Cur()

        def commit(self):
            pass

        def rollback(self):
            pass

    class _Ctx:
        def __enter__(self):
            return _Conn()

        def __exit__(self, *a):
            return False

    return lambda *a, **k: _Ctx()


def test_locked_database_is_not_reported_as_duplicate(db, monkeypatch):
    """A locked database must propagate, not masquerade as "already seen"."""
    import sqlite3

    cache = db.webhook_cache
    monkeypatch.setattr(
        cache,
        "get_connection",
        _conn_failing_insert(sqlite3.OperationalError("database is locked")),
    )
    with pytest.raises(sqlite3.OperationalError):
        cache.is_duplicate("movie", "Some Movie", 600)


def test_unique_clash_is_still_reported_as_duplicate(db, monkeypatch):
    """Control: the documented IntegrityError race still coalesces duplicates."""
    import sqlite3

    cache = db.webhook_cache
    monkeypatch.setattr(
        cache,
        "get_connection",
        _conn_failing_insert(sqlite3.IntegrityError("UNIQUE constraint failed")),
    )
    verdict = cache.is_duplicate("movie", "Some Movie", 600)
    assert verdict is True
