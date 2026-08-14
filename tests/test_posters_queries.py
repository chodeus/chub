"""Tests for the posters.py query methods that moved into the DB interfaces.

Two layers: the new PosterCache / MediaCache / CollectionCache methods against a
real temp database, then the poster handlers whose contract nothing else pinned.
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
    """Mount the posters router on a bare app carrying main.py's ConfigError handler."""
    import backend.api.main as apimain
    import backend.api.posters as posters

    app = FastAPI()
    app.state.logger = _StubLog()
    app.state.db = db
    app.add_exception_handler(ConfigError, apimain.handle_config_error)
    app.include_router(posters.router)
    return TestClient(app, raise_server_exceptions=False)


def _seed_poster(db, title, file=None, folder="/src", **fields):
    """Upsert one poster_cache row and return its integer id."""
    path = file or f"/src/{title}.jpg"
    db.poster.upsert(
        {
            "title": title,
            "normalized_title": title.lower(),
            "year": 2021,
            "tmdb_id": None,
            "tvdb_id": None,
            "imdb_id": None,
            "season_number": None,
            "folder": folder,
            "file": path,
            "asset_type": "movie",
            **fields,
        }
    )
    row = db.poster.execute_query(
        "SELECT id FROM poster_cache WHERE file=?", (path,), fetch_one=True
    )
    return row["id"]


def _seed_media(db, title, instance_name="radarr", original_file=None, **fields):
    """Upsert one media row (optionally matched to a poster file) and return its id."""
    item = {"title": title, "normalized_title": title.lower(), "year": 2021, **fields}
    db.media.upsert(item, "movie", "radarr", instance_name)
    row = db.media.execute_query(
        "SELECT id FROM media_cache WHERE title=? AND instance_name=?",
        (title, instance_name),
        fetch_one=True,
    )
    if original_file:
        db.media.update(
            asset_type="movie",
            title=title,
            year=2021,
            instance_name=instance_name,
            matched_value=1,
            original_file=original_file,
            id=row["id"],
        )
    return row["id"]


# --- PosterCache.get_collections / get_collection ---------------------------


def test_get_collections_orders_by_name_not_insertion(db):
    """The list is name-ascending, so insertion order must not leak through."""
    db.poster.create_collection("Zebra", None, "2026-01-01T00:00:00")
    db.poster.create_collection("Alpha", None, "2026-01-02T00:00:00")

    assert [c["name"] for c in db.poster.get_collections()] == ["Alpha", "Zebra"]


def test_get_collection_returns_the_row_or_none(db):
    """A known id resolves its own row; an unknown id is None, never a stray row."""
    first = db.poster.create_collection("Halloween", "spooky", "2026-01-01T00:00:00")
    db.poster.create_collection("Xmas", "merry", "2026-01-02T00:00:00")

    row = db.poster.get_collection(first)
    assert row["name"] == "Halloween" and row["description"] == "spooky"
    assert db.poster.get_collection(999999) is None


# --- PosterCache.get_collection_posters ------------------------------------


def test_get_collection_posters_is_scoped_and_title_ordered(db):
    """Only this collection's posters come back, title-ascending."""
    zebra = _seed_poster(db, "Zebra")
    alpha = _seed_poster(db, "Alpha")
    other = _seed_poster(db, "Other")
    mine = db.poster.create_collection("Mine", None, "2026-01-01T00:00:00")
    theirs = db.poster.create_collection("Theirs", None, "2026-01-01T00:00:00")
    db.poster.add_collection_item(mine, zebra)
    db.poster.add_collection_item(mine, alpha)
    db.poster.add_collection_item(theirs, other)

    rows = db.poster.get_collection_posters(mine)
    assert [r["title"] for r in rows] == ["Alpha", "Zebra"]
    assert set(rows[0]) == {
        "id",
        "asset_type",
        "title",
        "year",
        "season_number",
        "folder",
        "file",
        "style",
    }


def test_get_collection_posters_drops_membership_rows_with_no_poster(db):
    """The JOIN is the filter: an item pointing at a deleted poster isn't returned."""
    kept = _seed_poster(db, "Kept")
    coll = db.poster.create_collection("Mine", None, "2026-01-01T00:00:00")
    db.poster.add_collection_item(coll, kept)
    db.poster.add_collection_item(coll, 999999)

    assert [r["id"] for r in db.poster.get_collection_posters(coll)] == [kept]


# --- PosterCache.remove_collection_item / delete_collection -----------------


def test_remove_collection_item_reports_the_rows_it_deleted(db):
    """The count is the DB's rowcount, so a repeat removal reports zero."""
    poster = _seed_poster(db, "Dune")
    coll = db.poster.create_collection("Mine", None, "2026-01-01T00:00:00")
    db.poster.add_collection_item(coll, poster)

    assert db.poster.remove_collection_item(coll, poster) == 1
    assert db.poster.remove_collection_item(coll, poster) == 0


def test_remove_collection_item_leaves_the_poster_in_other_collections(db):
    """(collection_id, poster_id) is the unique key — both must be in the WHERE."""
    poster = _seed_poster(db, "Dune")
    mine = db.poster.create_collection("Mine", None, "2026-01-01T00:00:00")
    theirs = db.poster.create_collection("Theirs", None, "2026-01-01T00:00:00")
    db.poster.add_collection_item(mine, poster)
    db.poster.add_collection_item(theirs, poster)

    db.poster.remove_collection_item(mine, poster)
    assert db.poster.get_collection_posters(mine) == []
    assert [r["id"] for r in db.poster.get_collection_posters(theirs)] == [poster]


def test_delete_collection_takes_its_membership_rows_with_it(db):
    """The collection and its items go; a sibling collection is untouched."""
    poster = _seed_poster(db, "Dune")
    doomed = db.poster.create_collection("Doomed", None, "2026-01-01T00:00:00")
    keeper = db.poster.create_collection("Keeper", None, "2026-01-01T00:00:00")
    db.poster.add_collection_item(doomed, poster)
    db.poster.add_collection_item(keeper, poster)

    db.poster.delete_collection(doomed)
    assert db.poster.get_collection(doomed) is None
    assert db.poster.get_collection_posters(doomed) == []
    assert [r["id"] for r in db.poster.get_collection_posters(keeper)] == [poster]


# --- PosterCache.find_missing_dimensions -----------------------------------


def test_find_missing_dimensions_skips_rows_that_already_have_both(db):
    """A row is only pending while width OR height is still NULL."""
    measured = _seed_poster(db, "Measured")
    pending = _seed_poster(db, "Pending")
    db.poster.record_dimensions(measured, 1000, 1500)

    assert [r["id"] for r in db.poster.find_missing_dimensions()] == [pending]


def test_find_missing_dimensions_walks_ids_in_order_under_the_limit(db):
    """Batches are id-ordered so an incremental backfill can't loop on one page."""
    ids = [_seed_poster(db, t) for t in ("One", "Two", "Three")]

    rows = db.poster.find_missing_dimensions(limit=2)
    assert [r["id"] for r in rows] == ids[:2]
    assert set(rows[0]) == {"id", "file"}


# --- PosterCache.added_since -----------------------------------------------


def test_added_since_reads_the_cutoff_as_an_instant_not_a_string(db):
    """created_at is stored in UTC; a cutoff in another offset must be converted first."""
    _seed_poster(db, "Later", created_at="2026-01-05T10:00:00+00:00")
    _seed_poster(db, "Earlier", created_at="2026-01-05T08:00:00+00:00")

    # 17:00+08:00 is 09:00 UTC, but a TEXT compare reads "17" as after both rows.
    rows = db.poster.added_since("2026-01-05T17:00:00+08:00")
    assert [r["title"] for r in rows] == ["Later"]


# --- MediaCache / CollectionCache approve_match + reopen_for_review ---------


def test_approve_match_promotes_the_row_and_clears_conflicts(db):
    """Approval writes matched/1.0 and empties the conflict list."""
    mid = _seed_media(db, "Dune")
    db.media.update(
        asset_type="movie",
        title="Dune",
        year=2021,
        instance_name="radarr",
        match_status="needs_review",
        match_confidence=0.4,
        conflict_ids='[{"tmdb_id": 1}]',
        id=mid,
    )

    db.media.approve_match(mid)

    row = db.media.get_by_id(mid)
    assert row["match_status"] == "matched"
    assert row["match_confidence"] == 1.0
    assert row["conflict_ids"] == "[]"


def test_approve_match_touches_only_the_requested_media_row(db):
    """The WHERE carries the row id — a sibling keeps its review state."""
    target = _seed_media(db, "Dune")
    bystander = _seed_media(db, "Sicario")
    for mid in (target, bystander):
        db.media.reopen_for_review(mid)

    db.media.approve_match(target)

    assert db.media.get_by_id(bystander)["match_status"] == "needs_review"


def test_reopen_for_review_sends_a_media_row_back(db):
    """Unlocking flips match_status back to needs_review."""
    mid = _seed_media(db, "Dune")
    db.media.approve_match(mid)

    db.media.reopen_for_review(mid)

    assert db.media.get_by_id(mid)["match_status"] == "needs_review"


def test_collection_approve_and_reopen_round_trip(db):
    """CollectionCache carries the same pair against collections_cache."""
    db.collection.upsert({"title": "Marvel", "library_name": "Movies"}, "plex1")
    cid = db.collection.get_by_title_and_instance("Marvel", "plex1", "Movies")["id"]

    db.collection.approve_match(cid)
    row = db.collection.get_by_id(cid)
    assert row["match_status"] == "matched" and row["match_confidence"] == 1.0
    assert row["conflict_ids"] == "[]"

    db.collection.reopen_for_review(cid)
    assert db.collection.get_by_id(cid)["match_status"] == "needs_review"


# --- MediaCache.find_by_original_file_basename -----------------------------


def test_find_by_original_file_basename_escapes_like_metacharacters(db):
    """`_` in a filename must be literal, not a single-character wildcard."""
    _seed_media(db, "Dune", original_file="/src/Dune_2021.jpg")
    _seed_media(db, "Sicario", original_file="/src/DuneX2021.jpg")

    rows = db.media.find_by_original_file_basename("Dune_2021.jpg")
    assert [r["title"] for r in rows] == ["Dune"]


def test_find_by_original_file_basename_returns_the_unmatch_fields(db):
    """The caller re-keys media_cache.update from these columns."""
    _seed_media(db, "Dune", original_file="/src/Dune (2021).jpg")

    rows = db.media.find_by_original_file_basename("Dune (2021).jpg")
    assert set(rows[0]) == {
        "id",
        "title",
        "instance_name",
        "asset_type",
        "year",
        "season_number",
    }


# --- Route contracts not covered elsewhere ---------------------------------


def test_collections_route_hydrates_each_collection_with_its_posters(db):
    """GET /collections returns the join result and its count per collection."""
    poster = _seed_poster(db, "Dune")
    filled = db.poster.create_collection("Filled", None, "2026-01-01T00:00:00")
    db.poster.create_collection("Empty", None, "2026-01-02T00:00:00")
    db.poster.add_collection_item(filled, poster)

    body = _client(db).get("/api/posters/collections").json()
    collections = body["data"]["collections"]
    assert [c["name"] for c in collections] == ["Empty", "Filled"]
    assert collections[0]["poster_count"] == 0
    assert collections[1]["poster_count"] == 1
    assert [p["title"] for p in collections[1]["posters"]] == ["Dune"]


def test_create_collection_route_returns_the_row_it_just_inserted(db):
    """The read-back is by the new id, so an older same-named row can't win."""
    db.poster.create_collection("Halloween", "older", "2026-01-01T00:00:00")

    resp = _client(db).post(
        "/api/posters/collections", json={"name": "Halloween", "description": "newer"}
    )
    assert resp.status_code == 200
    created = resp.json()["data"]["collection"]
    assert created["description"] == "newer"
    assert created["id"] == db.poster.get_collection_id_by_name("Halloween")


def test_create_collection_route_requires_a_name(db):
    """A nameless collection is a 400, not an unnamed row."""
    resp = _client(db).post("/api/posters/collections", json={"description": "x"})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "MISSING_NAME"
    assert db.poster.get_collections() == []


def test_add_to_collection_route_404s_for_an_unknown_collection(db):
    """The existence check runs before the insert, so no orphan item is written."""
    poster = _seed_poster(db, "Dune")

    resp = _client(db).post(
        "/api/posters/collections/999999/add", json={"poster_id": poster}
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "COLLECTION_NOT_FOUND"


def test_add_to_collection_route_is_idempotent(db):
    """Re-adding the same poster keeps one membership row, not two."""
    poster = _seed_poster(db, "Dune")
    coll = db.poster.create_collection("Mine", None, "2026-01-01T00:00:00")
    client = _client(db)

    for _ in range(2):
        resp = client.post(
            f"/api/posters/collections/{coll}/add", json={"poster_id": poster}
        )
        assert resp.status_code == 200
    assert len(db.poster.get_collection_posters(coll)) == 1


def test_remove_from_collection_route_404s_when_the_pair_is_absent(db):
    """The 404 is driven by the deleted rowcount, not by a separate lookup."""
    poster = _seed_poster(db, "Dune")
    coll = db.poster.create_collection("Mine", None, "2026-01-01T00:00:00")
    db.poster.add_collection_item(coll, poster)
    client = _client(db)

    first = client.delete(f"/api/posters/collections/{coll}/remove/{poster}")
    second = client.delete(f"/api/posters/collections/{coll}/remove/{poster}")
    assert first.status_code == 200
    assert second.status_code == 404
    assert second.json()["error_code"] == "ITEM_NOT_FOUND"


def test_delete_collection_route_404s_then_deletes_everything(db):
    """An unknown id is a 404; a known one takes its membership rows with it."""
    poster = _seed_poster(db, "Dune")
    coll = db.poster.create_collection("Mine", None, "2026-01-01T00:00:00")
    db.poster.add_collection_item(coll, poster)
    client = _client(db)

    missing = client.delete("/api/posters/collections/999999")
    assert missing.status_code == 404
    deleted = client.delete(f"/api/posters/collections/{coll}")
    assert deleted.status_code == 200
    assert db.poster.get_collection(coll) is None
    assert db.poster.get_collection_posters(coll) == []


def test_approve_then_unlock_route_round_trips_a_media_row(db):
    """Approve locks the row; unlock reopens it and drops the lock."""
    mid = _seed_media(db, "Dune")
    client = _client(db)

    approved = client.post(f"/api/posters/match/{mid}/approve")
    assert approved.status_code == 200
    row = db.media.get_by_id(mid)
    assert row["match_status"] == "matched" and row["user_confirmed"] == 1

    unlocked = client.post(f"/api/posters/match/{mid}/unlock")
    assert unlocked.status_code == 200
    row = db.media.get_by_id(mid)
    assert row["match_status"] == "needs_review" and row["user_confirmed"] == 0


def test_approve_route_writes_to_collections_when_kind_is_collection(db):
    """kind=collection must reach CollectionCache, not the media table."""
    db.collection.upsert({"title": "Marvel", "library_name": "Movies"}, "plex1")
    cid = db.collection.get_by_title_and_instance("Marvel", "plex1", "Movies")["id"]
    decoy = _seed_media(db, "Dune")

    resp = _client(db).post(f"/api/posters/match/{cid}/approve?kind=collection")
    assert resp.status_code == 200
    assert db.collection.get_by_id(cid)["match_status"] == "matched"
    assert db.media.get_by_id(decoy)["match_status"] is None


def test_backfill_dimensions_route_measures_only_the_unmeasured(db, tmp_path):
    """Rows with a readable file get width/height; a missing file is skipped."""
    from PIL import Image

    real = tmp_path / "Dune.jpg"
    Image.new("RGB", (400, 600)).save(real)
    measurable = _seed_poster(db, "Dune", file=str(real))
    _seed_poster(db, "Ghost", file=str(tmp_path / "gone.jpg"))

    body = _client(db).post("/api/posters/backfill-dimensions").json()
    assert body["data"] == {"updated": 1, "skipped": 1, "batch_size": 200}
    row = db.poster.get_by_integer_id(measurable)
    assert (row["width"], row["height"]) == (400, 600)


def test_delete_poster_route_unmatches_the_media_it_was_applied_to(db):
    """Deleting the poster row clears the media rows pointing at that file."""
    poster = _seed_poster(db, "Dune", file="Dune (2021).jpg", folder="/src")
    mid = _seed_media(db, "Dune", original_file="/src/Dune (2021).jpg")

    body = _client(db).delete(f"/api/posters/{poster}").json()
    assert body["data"]["media_unmatched"] == 1
    row = db.media.get_by_id(mid)
    assert row["matched"] == 0 and row["original_file"] == ""


def test_delete_poster_route_leaves_lookalike_filenames_matched(db):
    """`_` in the deleted poster's name must not wildcard onto another row."""
    poster = _seed_poster(db, "Dune", file="Dune_2021.jpg", folder="/src")
    literal = _seed_media(db, "Dune", original_file="/src/Dune_2021.jpg")
    lookalike = _seed_media(db, "Sicario", original_file="/src/DuneX2021.jpg")

    body = _client(db).delete(f"/api/posters/{poster}").json()
    assert body["data"]["media_unmatched"] == 1
    assert db.media.get_by_id(literal)["matched"] == 0
    assert db.media.get_by_id(lookalike)["matched"] == 1
