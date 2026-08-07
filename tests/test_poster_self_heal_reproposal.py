"""The re-proposal loop and the fail-open that made it dangerous.

A successful auto-apply renames the file out from under poster_cache. Because the
cache's conflict key includes `file`, the row can't be updated in place — so the
next run re-read the stale row, re-proposed the same rename, and hit a collision
that its OWN previous rename created. That failure was then swallowed by upsert's
terminal-status CASE, so the run reported work "left for manual review" that no
surface could display.
"""

import pytest

from backend.util.cl2k import gdrive_upload
from backend.util.database.poster_heal_review import OPEN_STATUSES, poster_heal_review_for


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _Sync:
    gdrive_sa_location = None
    token = '{"access_token":"x","refresh_token":"y"}'
    client_id = ""
    client_secret = ""


class _Log:
    def __init__(self):
        self.warnings = []

    def info(self, *a, **kw):
        pass

    def debug(self, *a, **kw):
        pass

    def warning(self, msg, *a, **kw):
        self.warnings.append(str(msg))


# --- the fail-open: a listing failure must not read as "the name is free" ---


def test_list_files_strict_raises_when_rclone_fails(monkeypatch):
    monkeypatch.setattr(gdrive_upload, "_rclone_path", lambda: "/usr/bin/rclone")
    monkeypatch.setattr(gdrive_upload, "_ensure_remote", lambda *a, **kw: None)
    monkeypatch.setattr(
        gdrive_upload.subprocess,
        "run",
        lambda *a, **kw: _Result(returncode=1, stderr="quota exceeded"),
    )
    with pytest.raises(RuntimeError, match="lsf failed"):
        gdrive_upload.list_files("FOLDER", _Sync(), _Log(), strict=True)


def test_list_files_strict_raises_without_a_token(monkeypatch):
    monkeypatch.setattr(gdrive_upload, "_upload_auth_args", lambda cfg: [])
    with pytest.raises(RuntimeError, match="token"):
        gdrive_upload.list_files("FOLDER", _Sync(), _Log(), strict=True)


def test_list_files_non_strict_still_degrades_to_empty(monkeypatch):
    """The healer's live-Drive source must keep tolerating a listing failure —
    a Drive problem must not abort a run with local posters still to heal."""
    monkeypatch.setattr(gdrive_upload, "_rclone_path", lambda: "/usr/bin/rclone")
    monkeypatch.setattr(gdrive_upload, "_ensure_remote", lambda *a, **kw: None)
    monkeypatch.setattr(
        gdrive_upload.subprocess,
        "run",
        lambda *a, **kw: _Result(returncode=1, stderr="boom"),
    )
    log = _Log()
    assert gdrive_upload.list_files("FOLDER", _Sync(), log) == []
    assert any("lsf failed" in w for w in log.warnings)


def test_apply_refuses_when_the_collision_check_cannot_run(monkeypatch):
    """The whole point: apply must NOT proceed on an unreadable listing."""
    from backend.util.poster_self_heal import apply as apply_mod

    moved = []
    monkeypatch.setattr(
        apply_mod,
        "list_files",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("rclone lsf failed: boom")),
    )
    monkeypatch.setattr(apply_mod, "move_file", lambda *a, **kw: moved.append(a))

    row = {
        "current_filename": "Old.jpg",
        "proposed_filename": "New.jpg",
        "poster_file": "/posters/Old.jpg",
        "drive_folder_id": "FOLDER",
    }
    with pytest.raises(RuntimeError, match="lsf failed"):
        apply_mod.apply_proposal(row, _Sync(), _Log())
    assert moved == [], "a rename ran despite the collision check failing"


# --- 'failed' is open, and not sticky ---


def test_failed_is_an_open_status():
    assert "failed" in OPEN_STATUSES
    assert "applied" not in OPEN_STATUSES
    assert "dismissed" not in OPEN_STATUSES


class _NullLog:
    def __getattr__(self, _):
        return lambda *a, **k: None

    def get_adapter(self, *a, **k):
        return self


@pytest.fixture
def db():
    import os
    import tempfile

    from backend.util.database import ChubDB

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        with ChubDB(_NullLog(), db_path=path) as handle:
            yield handle
    finally:
        os.unlink(path)


def _rec(poster_file, status="proposed"):
    return {
        "poster_file": poster_file,
        "drive_folder_id": "FOLDER",
        "asset_type": "movie",
        "drift_type": "tvdb",
        "current_filename": "Old.jpg",
        "proposed_filename": "New.jpg",
        "tmdb_id_old": 1,
        "tmdb_id_new": 1,
        "title_old": "Old",
        "title_new": "Old",
        "confidence": 1.0,
        "reason": "backfill tvdb",
        "status": status,
    }


def test_an_applied_row_whose_reapply_fails_becomes_visible(db):
    """The bug: upsert's CASE re-preserved 'applied', so a failing re-apply left
    the row current, terminal, and unreachable by every review surface."""
    reviews = poster_heal_review_for(db)
    reviews.upsert(_rec("/p/x.jpg"))
    reviews.set_status(reviews.list_open()[0]["id"], "applied")
    assert reviews.open_count() == 0

    reviews.upsert(_rec("/p/x.jpg"))  # a later run re-proposes
    assert reviews.open_count() == 0, "CASE should still hold it terminal"

    reviews.mark_failed("/p/x.jpg", "refusing to apply: already exists")
    assert reviews.open_count() == 1
    row = reviews.list_open()[0]
    assert row["status"] == "failed"
    assert "already exists" in row["reason"]


def test_failed_is_not_sticky_so_a_later_clean_run_clears_it(db):
    """A sticky 'failed' would latch a transient Drive error forever."""
    reviews = poster_heal_review_for(db)
    reviews.upsert(_rec("/p/y.jpg"))
    reviews.mark_failed("/p/y.jpg", "transient")
    assert reviews.list_open()[0]["status"] == "failed"

    reviews.upsert(_rec("/p/y.jpg", status="proposed"))
    assert reviews.list_open()[0]["status"] == "proposed"


def test_drop_stale_row_is_exact_not_a_prefix(db):
    from backend.util.poster_self_heal.cache_reconcile import drop_stale_row

    db.poster.execute_query(
        "INSERT INTO poster_cache (title, file) VALUES ('A', '/p/X.jpg')"
    )
    db.poster.execute_query(
        "INSERT INTO poster_cache (title, file) VALUES ('A', '/p/X.jpg.bak')"
    )
    drop_stale_row(db, "/p/X.jpg")
    left = [
        r["file"]
        for r in db.poster.execute_query(
            "SELECT file FROM poster_cache", fetch_all=True
        )
        or []
    ]
    assert left == ["/p/X.jpg.bak"], "an exact delete took a sibling path"


def test_drop_stale_row_never_raises_when_the_cache_is_unusable():
    """The rename already landed on Drive — a cache problem must not fail the run."""
    from backend.util.poster_self_heal.cache_reconcile import drop_stale_row

    class _Boom:
        class poster:
            @staticmethod
            def execute_query(*a, **kw):
                raise RuntimeError("database is locked")

    log = _Log()
    assert drop_stale_row(_Boom(), "/p/X.jpg", log) == 0
    assert any("stale cache row" in w for w in log.warnings)


def test_drop_stale_row_ignores_a_blank_path(db):
    from backend.util.poster_self_heal.cache_reconcile import drop_stale_row

    assert drop_stale_row(db, "") == 0


def test_dismissed_files_returns_only_dismissed(db):
    reviews = poster_heal_review_for(db)
    reviews.upsert(_rec("/p/keep.jpg"))
    reviews.upsert(_rec("/p/no.jpg"))
    reviews.set_status(
        [r for r in reviews.list_open() if r["poster_file"] == "/p/no.jpg"][0]["id"],
        "dismissed",
    )
    assert reviews.dismissed_files() == {"/p/no.jpg"}


def test_should_auto_apply_refuses_a_dismissed_poster():
    """'dismissed' is documented as terminal and sticky. The upsert CASE only
    keeps it out of the review QUEUE — without this guard auto-apply still
    renamed the file on disk and on Drive, the opposite of dismissing it."""
    from backend.modules.poster_self_heal import should_auto_apply

    prop = {"poster_file": "/p/no.jpg", "status": "proposed"}
    assert should_auto_apply(prop, True, set()) is True
    assert should_auto_apply(prop, True, {"/p/no.jpg"}) is False


def test_should_auto_apply_respects_auto_and_status():
    from backend.modules.poster_self_heal import should_auto_apply

    prop = {"poster_file": "/p/x.jpg", "status": "proposed"}
    assert should_auto_apply(prop, False, set()) is False  # auto-apply off
    ambiguous = {"poster_file": "/p/x.jpg", "status": "pending"}
    assert should_auto_apply(ambiguous, True, set()) is False  # needs a manual pick
