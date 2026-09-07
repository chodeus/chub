"""Regression tests for the performance half of the 2026-09 review sweep.

These changes are meant to be cost-only, so most of these assert that behaviour
is unchanged — that is where a silent regression would hide.
"""

import os
import sqlite3
import tempfile
import threading
from types import SimpleNamespace

import pytest


def _logger():
    n = SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    n.get_adapter = lambda *a, **k: n
    return n


def _plex_item(i, instance):
    return {
        "plex_id": f"p{i}",
        "instance_name": instance,
        "asset_type": "movie",
        "library_name": "Movies",
        "title": f"T{i}",
        "normalized_title": f"t{i}",
        "year": 2020,
        "guids": {"tmdb": str(i)},
        "labels": [],
        "season_number": None,
    }


@pytest.fixture
def db():
    from backend.util.database import ChubDB

    path = os.path.join(tempfile.mkdtemp(), "chub.db")
    with ChubDB(_logger(), db_path=path, quiet=True) as handle:
        yield handle


# --- batched plex cache sync writes exactly what the per-row loop did ---


def test_batched_sync_writes_the_same_rows_as_per_row_upsert(db):
    """sync_for_library now batches into one transaction per chunk instead of
    a connect+commit per row. It must still add, update and delete the same."""
    pc = db.plex
    for item in [_plex_item(i, "A") for i in range(5)]:
        pc.upsert(item)
    per_row = {r["plex_id"] for r in pc.get_all() if r["instance_name"] == "A"}

    pc.sync_for_library("B", "Movies", [_plex_item(i, "B") for i in range(5)])
    batched = {r["plex_id"] for r in pc.get_all() if r["instance_name"] == "B"}
    assert batched == per_row == {f"p{i}" for i in range(5)}


def test_batched_sync_deletes_rows_no_longer_present(db):
    pc = db.plex
    pc.sync_for_library("A", "Movies", [_plex_item(i, "A") for i in range(5)])
    pc.sync_for_library("A", "Movies", [_plex_item(i, "A") for i in range(2)])
    remaining = {r["plex_id"] for r in pc.get_all() if r["instance_name"] == "A"}
    assert remaining == {"p0", "p1"}


def test_batched_sync_updates_changed_rows(db):
    pc = db.plex
    pc.sync_for_library("A", "Movies", [_plex_item(0, "A")])
    changed = _plex_item(0, "A")
    changed["title"] = "Renamed"
    pc.sync_for_library("A", "Movies", [changed])
    rows = [r for r in pc.get_all() if r["instance_name"] == "A"]
    assert len(rows) == 1 and rows[0]["title"] == "Renamed"


def test_chunking_crosses_the_chunk_boundary(db):
    """Chunk size is 500; a sync larger than that must not drop the remainder."""
    pc = db.plex
    pc.sync_for_library("A", "Movies", [_plex_item(i, "A") for i in range(1201)])
    assert len([r for r in pc.get_all() if r["instance_name"] == "A"]) == 1201


# --- the background-distance rewrite is bit-comparable ---


def test_background_distance_matches_the_broadcast_form():
    """Looping the backdrop colours with a running minimum replaced an
    H x W x N x 3 broadcast. Same numbers, a fraction of the memory."""
    np = pytest.importorskip("numpy")
    from backend.util.cl2k import logo_extract as le

    rng = np.random.default_rng(0)
    arr = rng.random((60, 40, 3), dtype=np.float32)
    bg = rng.random((5, 3), dtype=np.float32)

    lab, bg_lab = le._srgb_to_lab(arr), le._srgb_to_lab(bg)
    diff = lab[..., None, :] - bg_lab[None, None]
    expected = np.sqrt((diff * diff).sum(axis=-1)).min(axis=-1)

    assert np.allclose(le._background_distance(arr, bg), expected)


def test_background_distance_handles_a_single_colour():
    np = pytest.importorskip("numpy")
    from backend.util.cl2k import logo_extract as le

    arr = np.zeros((4, 4, 3), dtype=np.float32)
    bg = np.zeros((1, 3), dtype=np.float32)
    out = le._background_distance(arr, bg)
    assert out.shape == (4, 4)
    assert np.allclose(out, 0.0)


# --- the allowed-roots memo must not leak between configs ---


def test_allowed_roots_memo_is_keyed_on_the_roots_not_the_config(tmp_path):
    """load_config returns a fresh deep copy each call, so an identity key
    would both miss constantly and risk serving another config's roots."""
    from backend.util import path_safety as ps

    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    a.mkdir()
    b.mkdir()

    ps._ROOTS_CACHE.clear()
    first = ps._resolve_roots((str(a),))
    second = ps._resolve_roots((str(b),))
    assert first == [a.resolve()]
    assert second == [b.resolve()]
    # Same input, served from the memo, still equal — and a distinct list.
    third = ps._resolve_roots((str(a),))
    assert third == first and third is not first


def test_allowed_roots_memo_is_bounded():
    from backend.util import path_safety as ps

    ps._ROOTS_CACHE.clear()
    for i in range(30):
        ps._resolve_roots((f"/nonexistent-{i}",))
    assert len(ps._ROOTS_CACHE) <= 9


# --- the job dedup SELECT must hold the write lock ---


def test_plain_select_does_not_serialise_but_begin_immediate_does():
    """The old comment claimed the dedup SELECT shared a transaction with the
    INSERT. It did not: two connections both passed the check and both wrote."""
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    setup = sqlite3.connect(path)
    setup.execute("CREATE TABLE j (id INTEGER PRIMARY KEY, name TEXT)")
    setup.commit()

    a, b = sqlite3.connect(path), sqlite3.connect(path)
    assert a.execute("SELECT id FROM j WHERE name=?", ("m",)).fetchone() is None
    assert a.in_transaction is False  # no write lock held by a SELECT
    assert b.execute("SELECT id FROM j WHERE name=?", ("m",)).fetchone() is None
    a.execute("INSERT INTO j (name) VALUES (?)", ("m",))
    a.commit()
    b.execute("INSERT INTO j (name) VALUES (?)", ("m",))
    b.commit()
    assert setup.execute("SELECT COUNT(*) FROM j").fetchone()[0] == 2

    # BEGIN IMMEDIATE is what actually serialises the check with the insert.
    setup.execute("DELETE FROM j")
    setup.commit()
    c = sqlite3.connect(path)
    d = sqlite3.connect(path, timeout=0.1)
    c.execute("BEGIN IMMEDIATE")
    with pytest.raises(sqlite3.OperationalError):
        d.execute("BEGIN IMMEDIATE")


def test_enqueue_takes_the_write_lock_before_the_dedup_select():
    import inspect

    from backend.util.database import worker

    src = inspect.getsource(worker)
    assert 'conn.execute("BEGIN IMMEDIATE")' in src
    assert "inside the same connection/transaction as the INSERT" not in src


# --- bounded log retention keeps the reported total honest ---


def test_instance_logs_report_total_seen_not_the_retained_slice():
    """all_lines became a bounded deque; without a separate counter the
    reported total would silently cap at the limit."""
    import inspect

    from backend.api import instances

    src = inspect.getsource(instances)
    assert "all_lines: deque = deque(maxlen=limit)" in src
    assert '"total": total_seen' in src
    assert '"total": len(all_lines)' not in src


# --- a failed optimize must not leave a temp file in the poster folder ---


def test_unlink_on_exit_removes_the_temp_file_on_failure(tmp_path):
    from backend.util.poster_images import _unlink_on_exit

    victim = tmp_path / "tmpXXXX.jpg"
    victim.write_bytes(b"x")
    with pytest.raises(ValueError):
        with _unlink_on_exit(str(victim)):
            raise ValueError("save failed")
    assert not victim.exists()


def test_unlink_on_exit_tolerates_a_file_already_moved(tmp_path):
    from backend.util.poster_images import _unlink_on_exit

    moved = tmp_path / "gone.jpg"
    with _unlink_on_exit(str(moved)):
        pass  # shutil.move consumed it on the success path
    assert not moved.exists()


# --- progress writes are throttled, not per-item ---


def test_poster_self_heal_progress_is_throttled():
    import inspect

    from backend.modules import poster_self_heal

    src = inspect.getsource(poster_self_heal)
    assert "idx % 250 == 0 or idx == total" in src


def test_thread_safety_of_the_roots_memo():
    """The memo is read and written from request threads."""
    from backend.util import path_safety as ps

    ps._ROOTS_CACHE.clear()
    errors = []

    def hammer():
        try:
            for _ in range(200):
                ps._resolve_roots(("/tmp",))
        except Exception as exc:  # pragma: no cover - only on a real race
            errors.append(exc)

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
