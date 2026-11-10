"""Tests for the media bulk-delete helper used by the Manage page's bulk
duplicate cleanup (_bulk_delete_sync + _remove_media_item).

Rows are seeded without arr_id, so the *arr round-trip is skipped and only the
local-cache deletion path runs — deterministic and offline."""

import json
import os
import sys
import tempfile
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.api.media_api import _bulk_delete_sync, router  # noqa: E402
from backend.util.arr import ARRConnectionError, SonarrClient  # noqa: E402
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
            pass  # temp DB already removed or still locked — nothing to clean up


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
    payload = json.loads(res.body)
    assert [f["id"] for f in payload["data"]["failed"]] == [999999]
    assert db.media.get_by_id(a) is None


# --- a failed *arr delete reports the true status and keeps the row ---

def _seed_arr(db, title, arr_id=42):
    db.media.upsert(
        {"title": title, "normalized_title": title.lower(), "year": 2021, "arr_id": arr_id},
        "movie",
        "radarr",
        "Radarr 4K",
    )
    row = db.media.execute_query(
        "SELECT id FROM media_cache WHERE title=?", (title,), fetch_one=True
    )
    assert db.media.get_by_id(row["id"])["arr_id"] == arr_id
    return row["id"]


@pytest.fixture
def radarr(monkeypatch):
    """Configures "Radarr 4K"; ``client`` stands in for what create_arr_client returns."""
    instances = SimpleNamespace(
        radarr={"Radarr 4K": SimpleNamespace(url="http://r:7878", api="k")},
        sonarr={},
        lidarr={},
    )
    monkeypatch.setattr(
        "backend.api.media_api.load_config", lambda: SimpleNamespace(instances=instances)
    )
    state = SimpleNamespace(client=None, calls=[])
    monkeypatch.setattr("backend.api.media_api.create_arr_client", lambda **kw: state.client)
    return state


def _client(state, outcome):
    def delete_media(*args):
        state.calls.append(args)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return SimpleNamespace(delete_media=delete_media)


def _bulk(db, rid, delete_files=True, add_exclusion=False):
    res = _bulk_delete_sync(db, StubLogger(), [rid], delete_files, add_exclusion)
    return json.loads(res.body)["data"]


@pytest.mark.parametrize(
    "outcome, reason",
    [
        (None, "Radarr 4K did not confirm the delete — see the server log"),
        (
            ARRConnectionError("http://r:7878/api/v3/movie/42?apikey=hunter2"),
            "Deleting from Radarr 4K failed: could not connect — see the server log",
        ),
    ],
)
def test_a_failed_arr_delete_keeps_the_row_and_says_why(db, radarr, outcome, reason):
    rid = _seed_arr(db, "Dune")
    radarr.client = _client(radarr, outcome)

    data = _bulk(db, rid)

    assert data == {"removed": [], "failed": [{"id": rid, "reason": reason}]}
    assert db.media.get_by_id(rid) is not None


def test_an_unreachable_instance_keeps_the_row(db, radarr):
    rid = _seed_arr(db, "Dune")

    data = _bulk(db, rid)

    assert data["failed"] == [{"id": rid, "reason": "could not connect to Radarr 4K"}]
    assert db.media.get_by_id(rid) is not None


def test_an_unconfigured_instance_keeps_the_row(db, monkeypatch):
    rid = _seed_arr(db, "Dune")
    empty = SimpleNamespace(radarr={}, sonarr={}, lidarr={})
    monkeypatch.setattr(
        "backend.api.media_api.load_config", lambda: SimpleNamespace(instances=empty)
    )

    data = _bulk(db, rid)

    assert data["failed"] == [{"id": rid, "reason": "Radarr 4K is not configured"}]
    assert db.media.get_by_id(rid) is not None


def test_a_confirmed_arr_delete_removes_the_row(db, radarr):
    rid = _seed_arr(db, "Dune")
    radarr.client = _client(radarr, SimpleNamespace(ok=True))

    data = _bulk(db, rid, delete_files=True, add_exclusion=True)

    assert data == {"removed": [rid], "failed": []}
    assert radarr.calls == [(42, True, True)]
    assert db.media.get_by_id(rid) is None


def test_sonarr_gets_its_own_exclusion_parameter():
    """Sonarr names it addImportListExclusion; the old URL sent Radarr's name."""
    client = object.__new__(SonarrClient)
    client.url, client.api_version = "http://s:8989", "v3"
    sent = []
    client.make_delete_request = lambda endpoint, params=None: sent.append((endpoint, params))

    client.delete_media(7, True, True)

    assert sent == [
        (
            "http://s:8989/api/v3/series/7",
            {"deleteFiles": True, "addImportListExclusion": True},
        )
    ]


def test_a_single_delete_with_files_reports_a_failed_arr_delete(db, radarr):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    rid = _seed_arr(db, "Dune")
    radarr.client = _client(radarr, None)
    app = FastAPI()
    app.state.logger = StubLogger()
    app.state.db = db
    app.include_router(router)

    resp = TestClient(app).request("DELETE", f"/api/media/{rid}", json={"deleteFiles": True})

    assert resp.status_code == 502
    assert resp.json()["message"] == (
        f"Media item {rid} was not deleted: Radarr 4K did not confirm the delete "
        "— see the server log"
    )
    assert db.media.get_by_id(rid) is not None
