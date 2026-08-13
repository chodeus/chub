"""Tests for the media_api query methods that moved into the DB interfaces.

Two layers: the new MediaCache / CollectionCache / PosterCache methods against a
real temp database, then the handlers whose contract nothing else pinned.
"""

import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util.config import ChubConfig, ConfigError  # noqa: E402
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
    """Mount the media router on a bare app carrying main.py's ConfigError handler."""
    import backend.api.main as apimain
    import backend.api.media_api as media_api

    app = FastAPI()
    app.state.logger = _StubLog()
    app.state.db = db
    app.add_exception_handler(ConfigError, apimain.handle_config_error)
    app.include_router(media_api.router)
    return TestClient(app, raise_server_exceptions=False)


def _seed(db, title, asset_type="movie", instance_name="radarr", **fields):
    """Upsert one media row and return its integer id."""
    item = {"title": title, "normalized_title": title.lower(), "year": 2021, **fields}
    db.media.upsert(item, asset_type, "radarr", instance_name)
    row = db.media.execute_query(
        "SELECT id FROM media_cache WHERE title=? AND instance_name=?",
        (title, instance_name),
        fetch_one=True,
    )
    return row["id"]


# --- MediaCache.find_low_rated ---------------------------------------------


def test_find_low_rated_orders_and_excludes_blank_ratings(db):
    """Only numerically-rated rows below the threshold, worst first."""
    _seed(db, "Bad", rating="2.5")
    _seed(db, "Worse", rating="1.0")
    _seed(db, "Good", rating="9.0")
    _seed(db, "Unrated")  # rating NULL
    _seed(db, "Blank", rating="")  # `or None` in upsert stores NULL

    rows = db.media.find_low_rated(5.0)
    assert [r["title"] for r in rows] == ["Worse", "Bad"]


def test_find_low_rated_filters_by_asset_type_and_paginates(db):
    """asset_type narrows the set; limit/offset walk it in rating order."""
    _seed(db, "Cheap Movie", rating="1.0")
    _seed(db, "Cheap Show", asset_type="show", rating="2.0")

    assert [r["title"] for r in db.media.find_low_rated(5.0, asset_type="show")] == [
        "Cheap Show"
    ]
    page = db.media.find_low_rated(5.0, limit=1, offset=1)
    assert [r["title"] for r in page] == ["Cheap Show"]


# --- MediaCache.find_incomplete_metadata -----------------------------------


def test_find_incomplete_metadata_skips_never_populated_fields(db):
    """A movie can't have a tvdb_id, so its absence must not flag the row."""
    _seed(db, "Movie", tvdb_id=None)
    _seed(db, "Show", asset_type="show", tvdb_id=None)

    titles = {r["title"] for r in db.media.find_incomplete_metadata(["tvdb_id"])}
    assert titles == {"Show"}


def test_find_incomplete_metadata_catch_all_covers_unknown_types(db):
    """An asset_type outside the known set is matched on the raw field list."""
    _seed(db, "Album", asset_type="album", tvdb_id=None)

    titles = {r["title"] for r in db.media.find_incomplete_metadata(["tvdb_id"])}
    assert titles == {"Album"}


def test_find_incomplete_metadata_rejects_fields_off_the_allow_list(db):
    """Field names reach SQL by interpolation — anything unknown is dropped."""
    _seed(db, "Movie")

    assert db.media.find_incomplete_metadata(["bogus_column"]) == []
    assert db.media.find_incomplete_metadata(["rating; DROP TABLE media_cache--"]) == []
    # The table is still there, and a valid request still works.
    assert [r["title"] for r in db.media.find_incomplete_metadata(["studio"])] == [
        "Movie"
    ]


def test_find_incomplete_metadata_orders_by_title_and_paginates(db):
    """Rows come back title-ascending so limit/offset paginate deterministically."""
    for title in ("Charlie", "Alpha", "Bravo"):
        _seed(db, title)

    page1 = db.media.find_incomplete_metadata(["studio"], limit=2)
    page2 = db.media.find_incomplete_metadata(["studio"], offset=2)
    assert [r["title"] for r in page1] == ["Alpha", "Bravo"]
    assert [r["title"] for r in page2] == ["Charlie"]


# --- MediaCache.get_arr_linked ---------------------------------------------


def test_get_arr_linked_needs_both_arr_id_and_instance(db):
    """Rows without an arr_id can't be checked against a live *arr."""
    _seed(db, "Linked", arr_id=7)
    _seed(db, "Unlinked")

    rows = db.media.get_arr_linked()
    assert [r["title"] for r in rows] == ["Linked"]
    assert set(rows[0]) == {
        "id",
        "title",
        "asset_type",
        "instance_name",
        "arr_id",
        "folder",
        "root_folder",
    }


# --- MediaCache.find_by_tag ------------------------------------------------


def test_find_by_tag_escapes_like_metacharacters(db):
    """`_` in a tag must be literal, not a single-character wildcard."""
    _seed(db, "Dune", tags=["4K_UHD"])
    _seed(db, "Sicario", tags=["4KxUHD"])

    rows = db.media.find_by_tag("4K_UHD")
    assert [r["title"] for r in rows] == ["Dune"]
    assert set(rows[0]) == {
        "id",
        "tmdb_id",
        "tvdb_id",
        "imdb_id",
        "season_number",
        "title",
        "year",
    }


# --- MediaCache.delete_by_ids ----------------------------------------------


def test_delete_by_ids_removes_only_the_listed_rows(db):
    """The unlisted row survives."""
    doomed = _seed(db, "Doomed")
    keeper = _seed(db, "Keeper")

    assert db.media.delete_by_ids([doomed]) == 1
    assert db.media.get_by_id(doomed) is None
    assert db.media.get_by_id(keeper) is not None


def test_delete_by_ids_no_ops_on_an_empty_list(db):
    """An empty list must not degrade into a whole-table DELETE."""
    keeper = _seed(db, "Keeper")

    assert db.media.delete_by_ids([]) == 0
    assert db.media.get_by_id(keeper) is not None


# --- MediaCache.record_edit / get_edit_history ------------------------------


def test_edit_history_round_trips_newest_first(db):
    """History reads back newest-first and honours the limit."""
    mid = _seed(db, "Dune")
    db.media.record_edit(mid, "2026-01-01T00:00:00", "dean", "rating", "5", "6")
    db.media.record_edit(mid, "2026-02-01T00:00:00", "dean", "studio", None, "A24")

    rows = db.media.get_edit_history(mid)
    assert [r["field"] for r in rows] == ["studio", "rating"]
    assert rows[0]["old_value"] is None
    assert rows[0]["new_value"] == "A24"
    assert len(db.media.get_edit_history(mid, limit=1)) == 1


def test_record_edit_stringifies_values_but_keeps_none(db):
    """Non-text values are stored as TEXT; None stays a genuine NULL."""
    mid = _seed(db, "Dune")
    db.media.record_edit(mid, "2026-01-01T00:00:00", "dean", "runtime", 90, None)

    row = db.media.get_edit_history(mid)[0]
    assert row["old_value"] == "90"
    assert row["new_value"] is None


def test_edit_history_is_scoped_to_one_media_id(db):
    """Another item's edits never leak into this item's trail."""
    a = _seed(db, "Dune")
    b = _seed(db, "Sicario")
    db.media.record_edit(a, "2026-01-01T00:00:00", "dean", "rating", "5", "6")
    db.media.record_edit(b, "2026-01-01T00:00:00", "dean", "rating", "1", "2")

    assert len(db.media.get_edit_history(a)) == 1


# --- CollectionCache.get_by_title_and_instance ------------------------------


def test_get_collection_by_title_and_instance_is_instance_scoped(db):
    """The same collection title in another instance is a different row."""
    for instance in ("plex1", "plex2"):
        db.collection.upsert({"title": "Marvel", "library_name": "Movies"}, instance)

    row = db.collection.get_by_title_and_instance("Marvel", "plex2")
    assert row["instance_name"] == "plex2"
    assert db.collection.get_by_title_and_instance("Marvel", "plex3") is None


# --- PosterCache poster_collections ----------------------------------------


def test_poster_collection_create_and_resolve_id(db):
    """A created collection resolves by name; an unknown name is None."""
    db.poster.create_collection("Halloween", "spooky", "2026-01-01T00:00:00")

    coll_id = db.poster.get_collection_id_by_name("Halloween")
    assert coll_id is not None
    assert db.poster.get_collection_id_by_name("Nope") is None


def test_poster_collection_id_lookup_prefers_the_newest_duplicate(db):
    """Names aren't unique — the lookup must return the most recent row."""
    db.poster.create_collection("Halloween", "first", "2026-01-01T00:00:00")
    first = db.poster.get_collection_id_by_name("Halloween")
    db.poster.create_collection("Halloween", "second", "2026-02-01T00:00:00")

    assert db.poster.get_collection_id_by_name("Halloween") > first


def test_add_collection_item_ignores_a_duplicate_pair(db):
    """The UNIQUE(collection_id, poster_id) pair is inserted once, not raised on."""
    db.poster.create_collection("Halloween", None, "2026-01-01T00:00:00")
    coll_id = db.poster.get_collection_id_by_name("Halloween")

    db.poster.add_collection_item(coll_id, 42)
    db.poster.add_collection_item(coll_id, 42)

    rows = db.poster.execute_query(
        "SELECT poster_id FROM poster_collection_items WHERE collection_id=?",
        (coll_id,),
        fetch_all=True,
    )
    assert [r["poster_id"] for r in rows] == [42]


# --- Route contracts not covered elsewhere ---------------------------------


def test_low_rated_route_returns_sorted_items(db):
    """GET /low-rated echoes the clamped paging and sorts worst-first."""
    _seed(db, "Bad", rating="2.5")
    _seed(db, "Worse", rating="1.0")

    body = _client(db).get("/api/media/low-rated?max_rating=5").json()
    assert [i["title"] for i in body["data"]["items"]] == ["Worse", "Bad"]
    assert body["data"]["limit"] == 100 and body["data"]["offset"] == 0


def test_low_rated_route_forwards_its_filters(db):
    """asset_type and limit reach the query, not just the echoed response."""
    _seed(db, "Cheap Movie", rating="1.0")
    _seed(db, "Cheap Show", asset_type="show", rating="2.0")
    client = _client(db)

    filtered = client.get("/api/media/low-rated?max_rating=5&asset_type=show").json()
    assert [i["title"] for i in filtered["data"]["items"]] == ["Cheap Show"]
    paged = client.get("/api/media/low-rated?max_rating=5&limit=1").json()
    assert [i["title"] for i in paged["data"]["items"]] == ["Cheap Movie"]


def test_incomplete_metadata_route_rejects_unknown_fields(db):
    """A fields list with nothing valid in it is a 400, not an empty 200."""
    resp = _client(db).get("/api/media/incomplete-metadata?fields=nope")
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_FIELDS"


def test_incomplete_metadata_route_annotates_missing_per_row(db):
    """`missing` lists only the fields that row's asset_type should populate."""
    _seed(db, "Movie", studio="A24")

    body = (
        _client(db)
        .get("/api/media/incomplete-metadata?fields=studio,tvdb_id,language")
        .json()
    )
    item = body["data"]["items"][0]
    assert item["missing"] == ["language"]  # studio set, tvdb_id never populated
    assert body["data"]["fields_checked"] == ["studio", "tvdb_id", "language"]


def test_orphaned_route_reports_rows_missing_from_their_arr(db, monkeypatch):
    """A cached arr_id the live instance no longer lists is orphaned."""
    import backend.api.media_api as media_api

    _seed(db, "Gone", arr_id=9)
    _seed(db, "Present", arr_id=5)
    monkeypatch.setattr(media_api, "load_config", lambda: ChubConfig())
    monkeypatch.setattr(
        media_api, "_live_arr_ids_by_instance", lambda *_a: {"radarr": {5}}
    )

    body = _client(db).get("/api/media/orphaned").json()
    assert [i["title"] for i in body["data"]["items"]] == ["Gone"]


def test_orphaned_purge_route_deletes_and_guards_empty_ids(db):
    """POST /orphaned/purge deletes the listed rows; an empty list is a 400."""
    client = _client(db)
    doomed = _seed(db, "Doomed")
    keeper = _seed(db, "Keeper")

    assert client.post("/api/media/orphaned/purge", json={"ids": []}).status_code == 400
    resp = client.post("/api/media/orphaned/purge", json={"ids": [doomed]})
    assert resp.status_code == 200
    assert db.media.get_by_id(doomed) is None
    assert db.media.get_by_id(keeper) is not None


def test_metadata_update_writes_one_audit_row_per_changed_field(db):
    """Only fields whose value actually changed reach the audit trail."""
    client = _client(db)
    mid = _seed(db, "Dune", rating="5.0")

    resp = client.put(
        f"/api/media/{mid}/metadata",
        json={"rating": "5.0", "studio": "A24", "language": "en"},
    )
    assert resp.status_code == 200

    history = client.get(f"/api/media/{mid}/history").json()["data"]["history"]
    assert {h["field"] for h in history} == {"studio", "language"}
    assert {h["media_id"] for h in history} == {mid}


def test_collection_from_tag_route_fills_the_poster_collection(db):
    """A tagged media row whose id matches a poster lands in the new collection."""
    _seed(db, "Dune", tags=["4K"], tmdb_id=438631)
    db.poster.upsert(
        {
            "title": "Dune",
            "normalized_title": "dune",
            "year": 2021,
            "tmdb_id": 438631,
            "tvdb_id": None,
            "imdb_id": None,
            "season_number": None,
            "folder": "Owner",
            "file": "/src/Dune.png",
            "asset_type": "movie",
        }
    )

    body = _client(db).post("/api/media/collections/from-tag", json={"tag": "4K"})
    assert body.status_code == 200
    data = body.json()["data"]
    assert data["poster_count"] == 1
    assert data["collection_id"] == db.poster.get_collection_id_by_name("4K")
    items = db.poster.execute_query(
        "SELECT poster_id FROM poster_collection_items WHERE collection_id=?",
        (data["collection_id"],),
        fetch_all=True,
    )
    assert len(items) == 1


def test_create_collection_route_reads_back_the_created_row(db):
    """POST /collections returns the row it just upserted."""
    resp = _client(db).post(
        "/api/media/collections",
        json={"title": "Marvel", "instance_name": "plex1", "year": 2012},
    )
    assert resp.status_code == 200
    collection = resp.json()["data"]["collection"]
    assert collection["title"] == "Marvel"
    assert collection["instance_name"] == "plex1"
