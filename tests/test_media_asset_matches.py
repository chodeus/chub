"""Tests for the media_asset_matches accessor — focus on the per-(media,
image_type) ``ignored`` flag added for the Unmatched → Additional artwork view.
"""

import sqlite3
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


def test_set_ignored_creates_row_for_missing_asset(db):
    """A *missing* asset has no match row; ignoring it must still persist the
    flag (so the Additional-artwork view can hide it)."""
    assert db.media_asset_matches.get_one("media", 7, "logo") is None
    db.media_asset_matches.set_ignored("media", 7, "logo", True)
    row = db.media_asset_matches.get_one("media", 7, "logo")
    assert row is not None and row["ignored"] == 1
    # status stays empty — ignoring is not the same as "applied"
    assert not row.get("match_status")


def test_set_ignored_toggles_without_losing_provenance(db):
    """Ignoring an already-applied asset flips the flag but keeps its match
    provenance (source/path), and un-ignoring restores it to active."""
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=7,
        image_type="background",
        source="tmdb",
        matched_url="http://x/bg.png",
        applied_method="plex",
        match_status="applied",
    )
    db.media_asset_matches.set_ignored("media", 7, "background", True)
    row = db.media_asset_matches.get_one("media", 7, "background")
    assert row["ignored"] == 1
    assert row["match_status"] == "applied"  # provenance preserved
    assert row["matched_url"] == "http://x/bg.png"

    db.media_asset_matches.set_ignored("media", 7, "background", False)
    assert db.media_asset_matches.get_one("media", 7, "background")["ignored"] == 0


def test_upsert_preserves_ignored_flag(db):
    """A later apply (upsert) must not silently clear a user's ignore flag."""
    db.media_asset_matches.set_ignored("media", 9, "logo", True)
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=9,
        image_type="logo",
        source="tmdb",
        matched_url="http://x/l.png",
        applied_method="plex",
        match_status="applied",
    )
    row = db.media_asset_matches.get_one("media", 9, "logo")
    assert row["ignored"] == 1  # untouched by upsert
    assert row["match_status"] == "applied"


def test_new_match_defaults_to_not_ignored(db):
    db.media_asset_matches.upsert(
        target_kind="media", target_id=5, image_type="logo", match_status="applied"
    )
    assert db.media_asset_matches.get_one("media", 5, "logo")["ignored"] == 0


# --- user_confirmed manual-pick lock (artwork picker) ---


def test_set_user_confirmed_creates_row_for_missing_asset(db):
    """Locking a not-yet-evaluated asset persists the flag even with no row."""
    assert db.media_asset_matches.get_one("media", 11, "logo") is None
    db.media_asset_matches.set_user_confirmed("media", 11, "logo", True)
    row = db.media_asset_matches.get_one("media", 11, "logo")
    assert row is not None and row["user_confirmed"] == 1


def test_new_match_defaults_to_not_user_confirmed(db):
    db.media_asset_matches.upsert(
        target_kind="media", target_id=6, image_type="background", match_status="applied"
    )
    assert db.media_asset_matches.get_one("media", 6, "background")["user_confirmed"] == 0


def test_upsert_preserves_user_confirmed_lock(db):
    """An auto-run upsert must not silently clear a user's manual-pick lock."""
    db.media_asset_matches.set_user_confirmed("media", 12, "squareart", True)
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=12,
        image_type="squareart",
        source="local",
        matched_file="/posters/x-squareart.png",
        applied_method="plex",
        match_status="applied",
    )
    row = db.media_asset_matches.get_one("media", 12, "squareart")
    assert row["user_confirmed"] == 1  # untouched by upsert
    assert row["match_status"] == "applied"


def _run_write(db, target_id, matched_file):
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=target_id,
        image_type="logo",
        source="local",
        matched_file=matched_file,
        match_status="applied",
        unless_locked=True,
    )


def test_unless_locked_leaves_a_locked_pick_as_it_is(db):
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=14,
        image_type="logo",
        source="local",
        matched_file="/posters/picked.png",
        match_status="applied",
    )
    db.media_asset_matches.set_user_confirmed("media", 14, "logo", True)
    _run_write(db, 14, "/posters/auto.png")
    row = db.media_asset_matches.get_one("media", 14, "logo")
    assert (row["matched_file"], row["user_confirmed"]) == ("/posters/picked.png", 1)


def test_unless_locked_still_writes_unlocked_and_new_rows(db):
    db.media_asset_matches.upsert(
        target_kind="media", target_id=15, image_type="logo", match_status="missing"
    )
    _run_write(db, 15, "/posters/auto.png")
    _run_write(db, 16, "/posters/new.png")
    rows = [db.media_asset_matches.get_one("media", i, "logo") for i in (15, 16)]
    assert [(r["matched_file"], r["match_status"]) for r in rows] == [
        ("/posters/auto.png", "applied"),
        ("/posters/new.png", "applied"),
    ]


def test_get_one_reads_through_the_callers_connection(db):
    conn = db.media_asset_matches.open_read_connection()
    conn.close()
    with pytest.raises(sqlite3.ProgrammingError):
        db.media_asset_matches.get_one("media", 1, "logo", conn=conn)


def test_a_lock_records_its_pick_and_a_bare_lock_keeps_the_rows_file(db):
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=17,
        image_type="logo",
        source="local",
        matched_file="/posters/auto.png",
        match_status="applied",
    )
    db.media_asset_matches.set_user_confirmed(
        "media", 17, "logo", True, matched_file="/posters/picked.png"
    )
    db.media_asset_matches.set_user_confirmed("media", 17, "logo", False)
    row = db.media_asset_matches.get_one("media", 17, "logo")
    assert (row["matched_file"], row["user_confirmed"], row["match_status"]) == (
        "/posters/picked.png",
        0,
        "applied",
    )


def test_set_user_confirmed_toggles_off(db):
    db.media_asset_matches.set_user_confirmed("media", 13, "logo", True)
    db.media_asset_matches.set_user_confirmed("media", 13, "logo", False)
    assert db.media_asset_matches.get_one("media", 13, "logo")["user_confirmed"] == 0


def test_clear_keep_ignored_preserves_locked_picks(db):
    """A reset that honours ignores must also honour manual-pick locks, so a
    re-run reuses the chosen file instead of re-resolving it."""
    db.media_asset_matches.upsert(
        target_kind="media",
        target_id=20,
        image_type="logo",
        source="local",
        matched_file="/posters/locked-logo.png",
        match_status="applied",
    )
    db.media_asset_matches.set_user_confirmed("media", 20, "logo", True)
    # an ordinary auto-matched row that should be dropped
    db.media_asset_matches.upsert(
        target_kind="media", target_id=21, image_type="logo", match_status="applied"
    )
    db.media_asset_matches.clear(keep_ignored=True)
    locked = db.media_asset_matches.get_one("media", 20, "logo")
    assert locked is not None and locked["matched_file"] == "/posters/locked-logo.png"
    assert db.media_asset_matches.get_one("media", 21, "logo") is None
