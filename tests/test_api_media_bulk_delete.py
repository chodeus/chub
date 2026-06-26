"""Tests for the media bulk-delete helper used by the Manage page's bulk
duplicate cleanup (_bulk_delete_sync + _remove_media_item).

Rows are seeded without arr_id, so the *arr round-trip is skipped and only the
local-cache deletion path runs — deterministic and offline."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.api.media_api import _bulk_delete_sync  # noqa: E402
from backend.util.database import ChubDB  # noqa: E402


class StubLogger:
    def debug(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def get_adapter(self, *_a, **_kw):
        return self


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = ChubDB(logger=StubLogger(), db_path=path, quiet=True)
    database.__enter__()
    database._ensure_schema_initialized()
    try:
        yield database
    finally:
        database.__exit__(None, None, None)
        try:
            os.unlink(path)
        except OSError:
            pass


def _seed(db, title):
    db.media.upsert(
        {"title": title, "normalized_title": title.lower(), "year": 2021},
        "movie",
        "radarr",
        "Radarr 4K",
    )
    row = db.media.execute_query(
        "SELECT id FROM media_cache WHERE title=?", (title,), fetch_one=True
    )
    return row["id"]


def test_bulk_delete_removes_all_ids(db):
    a = _seed(db, "Dune")
    b = _seed(db, "Sicario")
    keep = _seed(db, "Arrival")

    res = _bulk_delete_sync(db, StubLogger(), [a, b], False, False)
    body = res.body.decode() if hasattr(res, "body") else ""
    assert '"removed"' in body

    assert db.media.get_by_id(a) is None
    assert db.media.get_by_id(b) is None
    # Unselected row is untouched
    assert db.media.get_by_id(keep) is not None


def test_bulk_delete_reports_missing_ids(db):
    a = _seed(db, "Dune")
    res = _bulk_delete_sync(db, StubLogger(), [a, 999999], False, False)
    body = res.body.decode()
    assert '"failed"' in body
    assert db.media.get_by_id(a) is None
