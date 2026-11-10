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
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.api.media_api import _bulk_delete_sync, router  # noqa: E402
from backend.util.arr import SonarrClient  # noqa: E402
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




class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body
        self.headers, self.ok = {}, status < 400
        self.text = json.dumps(body) if body is not None else ""

    def __bool__(self):
        return self.ok

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture
def arrs(monkeypatch):
    """The *arr HTTP side only: hosts map to (app name, ids present, DELETE status)."""
    state = SimpleNamespace(hosts={}, deletes=[])

    def request(self, method, url, **kw):
        app, present, forced = state.hosts[next(h for h in state.hosts if url.startswith(h))]
        if app is None:
            return _Resp(503)
        if url.endswith("/system/status"):
            return _Resp(200, {"appName": app, "version": "5"})
        if method == "DELETE":
            state.deletes.append((url, kw.get("params")))
            if forced:
                return _Resp(forced)
            arr_id = int(url.rsplit("/", 1)[1])
            if arr_id not in present:
                return _Resp(404, {"message": "NotFound"})
            present.discard(arr_id)
            return _Resp(200)
        return _Resp(404)

    monkeypatch.setattr(requests.Session, "request", request)
    # The client backs off between probes of a down instance; no need to wait here.
    monkeypatch.setattr("backend.util.arr.time.sleep", lambda *_: None)
    return state


def _configure(monkeypatch, **types):
    instances = SimpleNamespace(radarr={}, sonarr={}, lidarr={})
    for arr_type, names in types.items():
        setattr(
            instances,
            arr_type,
            {name: SimpleNamespace(url=url, api="k") for name, url in names.items()},
        )
    monkeypatch.setattr(
        "backend.util.arr_delete.load_config", lambda: SimpleNamespace(instances=instances)
    )


def _seed_arr(
    db, title, arr_id=42, asset_type="movie", arr_type="radarr", name="Radarr 4K", **extra
):
    row = {"title": title, "normalized_title": title.lower(), "year": 2021}
    db.media.upsert(
        {**row, "arr_id": arr_id, **extra},
        asset_type,
        arr_type,
        name,
    )
    row = db.media.execute_query(
        "SELECT id FROM media_cache WHERE title=?", (title,), fetch_one=True
    )
    return row["id"]


def _bulk(db, ids, delete_files=True, add_exclusion=False):
    res = _bulk_delete_sync(db, StubLogger(), ids, delete_files, add_exclusion)
    return json.loads(res.body)["data"]


@pytest.fixture
def radarr(monkeypatch, arrs):
    arrs.hosts["http://r:7878"] = ("Radarr", {42, 43}, None)
    _configure(monkeypatch, radarr={"Radarr 4K": "http://r:7878"})
    return arrs


def test_a_confirmed_arr_delete_removes_the_row(db, radarr):
    rid = _seed_arr(db, "Dune")

    data = _bulk(db, [rid], delete_files=True, add_exclusion=True)

    assert data == {"removed": [rid], "failed": []}
    assert radarr.deletes == [
        (
            "http://r:7878/api/v3/movie/42",
            {"deleteFiles": True, "addImportExclusion": True},
        )
    ]
    assert db.media.get_by_id(rid) is None


def test_an_item_already_gone_from_the_arr_removes_the_row(db, radarr):
    rid = _seed_arr(db, "Dune", arr_id=99)

    data = _bulk(db, [rid])
    assert data == {"removed": [rid], "failed": []}
    assert db.media.get_by_id(rid) is None


@pytest.mark.parametrize(
    "status, reason",
    [
        (500, "Radarr 4K did not confirm the delete — see the server log"),
        (
            401,
            "Deleting from Radarr 4K failed: unauthorized: check the API key "
            "— see the server log",
        ),
    ],
)
def test_a_failed_arr_delete_keeps_the_row_and_says_why(db, radarr, status, reason):
    radarr.hosts["http://r:7878"] = ("Radarr", {42}, status)
    rid = _seed_arr(db, "Dune")

    data = _bulk(db, [rid])
    assert data == {"removed": [], "failed": [{"id": rid, "reason": reason}]}
    assert db.media.get_by_id(rid) is not None


def test_an_unreachable_instance_keeps_the_row(db, radarr):
    radarr.hosts["http://r:7878"] = (None, set(), None)
    rid = _seed_arr(db, "Dune")

    data = _bulk(db, [rid])
    assert data["failed"] == [{"id": rid, "reason": "could not connect to Radarr 4K"}]
    assert db.media.get_by_id(rid) is not None


def test_one_client_serves_every_row_of_an_instance(db, radarr, monkeypatch):
    from backend.util import arr_delete

    made = []
    real = arr_delete.create_arr_client
    monkeypatch.setattr(
        arr_delete, "create_arr_client", lambda **kw: made.append(kw) or real(**kw)
    )
    ids = [_seed_arr(db, "Dune"), _seed_arr(db, "Sicario", arr_id=43)]

    data = _bulk(db, ids)
    assert data["removed"] == ids
    assert len(made) == 1


def test_a_shared_instance_name_deletes_from_the_rows_own_arr(db, arrs, monkeypatch):
    """Names are unique per type only: a Sonarr row must never hit Radarr's movie 7."""
    arrs.hosts["http://r:7878"] = ("Radarr", {7}, None)
    arrs.hosts["http://s:8989"] = ("Sonarr", {7}, None)
    _configure(monkeypatch, radarr={"Main": "http://r:7878"}, sonarr={"Main": "http://s:8989"})
    rid = _seed_arr(db, "Severance", arr_id=7, asset_type="show", arr_type="sonarr", name="Main")

    data = _bulk(db, [rid])
    assert data["removed"] == [rid]
    assert [url for url, _params in arrs.deletes] == ["http://s:8989/api/v3/series/7"]
    assert 7 in arrs.hosts["http://r:7878"][1]


def test_an_instance_pointing_at_another_arr_is_refused(db, arrs, monkeypatch):
    arrs.hosts["http://r:7878"] = ("Radarr", {7}, None)
    _configure(monkeypatch, sonarr={"Main": "http://r:7878"})
    rid = _seed_arr(db, "Severance", arr_id=7, asset_type="show", arr_type="sonarr", name="Main")

    data = _bulk(db, [rid])
    assert data["failed"] == [{"id": rid, "reason": "Main is not a Sonarr instance"}]
    assert arrs.deletes == []


@pytest.mark.parametrize(
    "asset_type, arr_type, extra",
    [
        ("show", "sonarr", {"season_number": 2}),
        # Specials: season 0 is falsy and must still count as a season.
        ("show", "sonarr", {"season_number": 0}),
        ("album", "lidarr", {}),
    ],
)
def test_a_season_or_album_row_is_never_sent_to_the_arr(
    db, arrs, monkeypatch, asset_type, arr_type, extra
):
    """A season row carries its series' id and an album row an album id."""
    arrs.hosts["http://x:1"] = ("Sonarr" if arr_type == "sonarr" else "Lidarr", {7}, None)
    _configure(monkeypatch, **{arr_type: {"Main": "http://x:1"}})
    rid = _seed_arr(
        db, "Item", arr_id=7, asset_type=asset_type, arr_type=arr_type, name="Main", **extra
    )

    data = _bulk(db, [rid])

    assert data["failed"] == [
        {"id": rid, "reason": "only a whole movie, series or artist can be deleted from its *arr"}
    ]
    assert arrs.deletes == []
    assert db.media.get_by_id(rid) is not None


@pytest.mark.parametrize("delete_files", [False, True])
def test_a_linked_row_on_an_unconfigured_instance_is_refused(db, arrs, monkeypatch, delete_files):
    """Removing the row would leave the item in an *arr CHUB can no longer reach."""
    _configure(monkeypatch)
    rid = _seed_arr(db, "Dune")

    data = _bulk(db, [rid], delete_files=delete_files)

    assert data["failed"] == [{"id": rid, "reason": "Radarr 4K is not configured"}]
    assert db.media.get_by_id(rid) is not None


def test_a_whole_lidarr_artist_is_deleted_from_lidarr(db, arrs, monkeypatch):
    arrs.hosts["http://l:8686"] = ("Lidarr", {5}, None)
    _configure(monkeypatch, lidarr={"Lidarr": "http://l:8686"})
    rid = _seed_arr(db, "Artist", arr_id=5, asset_type="artist", arr_type="lidarr", name="Lidarr")

    data = _bulk(db, [rid])
    assert data["removed"] == [rid]
    assert [url for url, _params in arrs.deletes] == ["http://l:8686/api/v1/artist/5"]


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


def _single_delete(db, rid):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.state.logger = StubLogger()
    app.state.db = db
    app.include_router(router)
    return TestClient(app).request("DELETE", f"/api/media/{rid}", json={"deleteFiles": True})


def test_a_single_delete_reports_an_unconfirmed_arr_delete(db, radarr):
    radarr.hosts["http://r:7878"] = ("Radarr", {42}, 500)
    rid = _seed_arr(db, "Dune")

    resp = _single_delete(db, rid)

    assert resp.status_code == 502
    assert resp.json()["message"] == (
        f"Media item {rid} was not deleted: Radarr 4K did not confirm the delete "
        "— see the server log"
    )
    assert db.media.get_by_id(rid) is not None


def test_a_single_delete_of_a_season_is_refused(db, arrs, monkeypatch):
    arrs.hosts["http://s:8989"] = ("Sonarr", {7}, None)
    _configure(monkeypatch, sonarr={"Main": "http://s:8989"})
    rid = _seed_arr(
        db, "Show", arr_id=7, asset_type="show", arr_type="sonarr", name="Main", season_number=3
    )

    resp = _single_delete(db, rid)

    assert resp.status_code == 409
    assert arrs.deletes == []
    assert db.media.get_by_id(rid) is not None


def test_a_single_delete_of_an_item_gone_from_the_arr_deleted_no_files(db, radarr):
    rid = _seed_arr(db, "Dune", arr_id=99)

    resp = _single_delete(db, rid)

    assert resp.status_code == 200
    assert resp.json()["data"]["files_deleted"] is False
    assert db.media.get_by_id(rid) is None


def test_a_single_delete_reports_the_files_it_deleted(db, radarr):
    rid = _seed_arr(db, "Dune")

    resp = _single_delete(db, rid)
    assert resp.json()["data"]["files_deleted"] is True


def _resolve(db, body):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.state.logger = StubLogger()
    app.state.db = db
    app.include_router(router)
    return TestClient(app).post("/api/media/duplicates/x/resolve", json=body)


def test_a_string_id_cannot_remove_the_kept_item(db, radarr):
    keep = _seed_arr(db, "Dune")
    other = _seed_arr(db, "Dune copy", arr_id=43)

    resp = _resolve(db, {"keepId": keep, "removeIds": [str(keep), other], "deleteFiles": True})

    assert resp.json()["data"]["removed"] == [other]
    assert db.media.get_by_id(keep) is not None
    assert [url for url, _params in radarr.deletes] == ["http://r:7878/api/v3/movie/43"]


def test_a_twin_of_the_kept_item_is_removed_from_chub_only(db, radarr):
    """Two rows for one Radarr movie: deleting the twin there would delete the kept item."""
    keep = _seed_arr(db, "Dune")
    twin = _seed_arr(db, "Dune twin")

    resp = _resolve(db, {"keepId": keep, "removeIds": [twin], "deleteFiles": True})

    assert resp.json()["data"]["removed"] == [twin]
    assert radarr.deletes == []
    assert 42 in radarr.hosts["http://r:7878"][1]


@pytest.mark.parametrize("ids", [[1, "x"], "1", [True], [0]])
def test_bulk_delete_rejects_ids_that_are_not_media_ids(db, ids):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.state.logger = StubLogger()
    app.state.db = db
    app.include_router(router)

    resp = TestClient(app).post("/api/media/bulk-delete", json={"ids": ids})

    assert resp.status_code == 400


def _api(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.state.logger = StubLogger()
    app.state.db = db
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("bad", ["²", "①", 2**63, "9" * 5000], ids=["superscript", "circled", "2^63", "5000-digits"])
def test_an_id_sqlite_cannot_hold_is_a_400_before_any_delete(db, radarr, bad):
    good = _seed_arr(db, "Dune")

    resp = _api(db).post("/api/media/bulk-delete", json={"ids": [good, bad], "deleteFiles": True})

    assert resp.status_code == 400
    assert radarr.deletes == []


@pytest.mark.parametrize("keep", [2**63, "9" * 5000], ids=["2^63", "5000-digits"])
def test_an_out_of_range_keep_id_is_a_400(db, keep):
    resp = _api(db).post(
        "/api/media/duplicates/x/resolve", json={"keepId": keep, "removeIds": [1]}
    )

    assert resp.status_code == 400


def test_leading_zeros_never_make_a_valid_id_too_long_to_read():
    from backend.api.media_api import _media_id

    assert _media_id("0" * 5000 + "7") == 7


def test_a_repeated_id_is_removed_once(db, radarr):
    rid = _seed_arr(db, "Dune")

    resp = _api(db).post("/api/media/bulk-delete", json={"ids": [rid, str(rid)]})

    assert resp.json()["data"] == {"removed": [rid], "failed": []}


def test_one_ids_error_keeps_the_others_report(db, radarr, monkeypatch):
    first, second = _seed_arr(db, "Dune"), _seed_arr(db, "Sicario", arr_id=43)
    real = db.media.get_by_id

    def flaky(rid):
        if rid == first:
            raise RuntimeError("/srv token=hunter2")
        return real(rid)

    monkeypatch.setattr(db.media, "get_by_id", flaky)

    data = _bulk(db, [first, second])

    assert data["removed"] == [second]
    assert data["failed"] == [
        {"id": first, "reason": "Delete failed: unexpected error — see the server log"}
    ]


def test_a_title_cased_legacy_kept_row_still_protects_its_arr_item(db, arrs, monkeypatch):
    """Rows written before upsert lowercased source carry "Sonarr"."""
    arrs.hosts["http://s:8989"] = ("Sonarr", {7}, None)
    _configure(monkeypatch, sonarr={"Main": "http://s:8989"})
    show = {"arr_id": 7, "asset_type": "show", "arr_type": "sonarr", "name": "Main"}
    keep = _seed_arr(db, "Severance", **show)
    twin = _seed_arr(db, "Severance twin", **show)
    db.media.execute_query("UPDATE media_cache SET source='Sonarr' WHERE id=?", (keep,))

    resp = _resolve(db, {"keepId": keep, "removeIds": [twin], "deleteFiles": True})

    assert resp.json()["data"]["removed"] == [twin]
    assert arrs.deletes == []
    assert 7 in arrs.hosts["http://s:8989"][1]


def test_a_kept_album_does_not_shield_an_artist_with_the_same_id(db, arrs, monkeypatch):
    """Album and artist ids are separate Lidarr sequences: album 5 is not artist 5."""
    arrs.hosts["http://l:8686"] = ("Lidarr", {5}, None)
    _configure(monkeypatch, lidarr={"Lidarr": "http://l:8686"})
    lidarr = {"arr_id": 5, "arr_type": "lidarr", "name": "Lidarr"}
    keep = _seed_arr(db, "Album", asset_type="album", **lidarr)
    artist = _seed_arr(db, "Artist", asset_type="artist", **lidarr)

    resp = _resolve(db, {"keepId": keep, "removeIds": [artist], "deleteFiles": True})

    assert resp.json()["data"]["removed"] == [artist]
    assert [url for url, _params in arrs.deletes] == ["http://l:8686/api/v1/artist/5"]


def test_a_single_delete_whose_row_delete_fails_says_the_files_went(db, radarr, monkeypatch):
    rid = _seed_arr(db, "Dune")

    def boom(_rid):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(db.media, "delete_by_id", boom)
    resp = _api(db).request("DELETE", f"/api/media/{rid}", json={"deleteFiles": True})

    assert resp.status_code == 500
    assert resp.json()["message"] == (
        f"Media item {rid} and its files were deleted from Radarr 4K, but CHUB could "
        "not remove its own entry — see the server log"
    )
