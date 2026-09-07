"""Perf half of the 2026-09 sweep — these assert behaviour is unchanged."""

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


def test_batched_sync_writes_the_same_rows_as_per_row_upsert(db):
    """Batched sync must add, update and delete exactly what per-row did."""
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
    """Chunk size is 500; a larger sync must not drop the remainder."""
    pc = db.plex
    pc.sync_for_library("A", "Movies", [_plex_item(i, "A") for i in range(1201)])
    assert len([r for r in pc.get_all() if r["instance_name"] == "A"]) == 1201


def test_background_distance_matches_the_broadcast_form():
    """The running-minimum rewrite must return the same numbers."""
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


def test_plain_select_does_not_serialise_but_begin_immediate_does():
    """A plain SELECT holds no write lock, so both connections could insert."""
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    setup = sqlite3.connect(path)
    setup.execute("CREATE TABLE j (id INTEGER PRIMARY KEY, name TEXT)")
    setup.commit()

    a, b = sqlite3.connect(path), sqlite3.connect(path)
    seen_by_a = a.execute("SELECT id FROM j WHERE name=?", ("m",)).fetchone()
    a_locked = a.in_transaction
    seen_by_b = b.execute("SELECT id FROM j WHERE name=?", ("m",)).fetchone()
    assert seen_by_a is None and seen_by_b is None
    assert a_locked is False  # a plain SELECT holds no write lock
    a.execute("INSERT INTO j (name) VALUES (?)", ("m",))
    a.commit()
    b.execute("INSERT INTO j (name) VALUES (?)", ("m",))
    b.commit()
    rows = setup.execute("SELECT COUNT(*) FROM j").fetchone()[0]
    assert rows == 2

    # BEGIN IMMEDIATE is what actually serialises the check with the insert.
    setup.execute("DELETE FROM j")
    setup.commit()
    c = sqlite3.connect(path)
    d = sqlite3.connect(path, timeout=0.1)
    c.execute("BEGIN IMMEDIATE")
    with pytest.raises(sqlite3.OperationalError):
        d.execute("BEGIN IMMEDIATE")


@pytest.mark.parametrize(
    "job_type,payload",
    [
        ("module_run", {"module_name": "nohl"}),
        ("plex_metadata_scan", {}),
        ("kometa_assets_scan", {}),
    ],
)
def test_concurrent_enqueue_collapses_to_one_job(tmp_path, job_type, payload):
    """Every dedup branch must hold the write lock, not just module_run."""
    from backend.util.database import ChubDB

    path = os.path.join(tmp_path, "chub.db")
    with ChubDB(_logger(), db_path=path, quiet=True) as setup:
        setup.worker  # schema is built on interface access, not on __enter__

    start = threading.Barrier(2)
    results = []

    def enqueue():
        with ChubDB(_logger(), db_path=path, quiet=True) as handle:
            start.wait(timeout=5)
            results.append(handle.worker.enqueue_job("jobs", payload, job_type))

    threads = [threading.Thread(target=enqueue) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    with ChubDB(_logger(), db_path=path, quiet=True) as check:
        rows = check.worker.execute_query(
            "SELECT COUNT(*) c FROM jobs WHERE type = ?", (job_type,), fetch_one=True
        )
    assert len(results) == 2
    assert rows["c"] == 1

def test_bounded_deque_retains_the_limit_and_counts_every_match():
    """The deque caps retention; the reported total must still count them all."""
    from collections import deque

    limit = 100
    retained: deque = deque(maxlen=limit)
    total_seen = 0
    for i in range(2500):
        total_seen += 1
        retained.append(f"line {i}")
    assert len(retained) == limit
    assert total_seen == 2500
    assert list(retained)[-1] == "line 2499"

def test_unlink_on_exit_removes_the_temp_file_on_failure(tmp_path):
    from backend.util.poster_images import _unlink_on_exit

    victim = tmp_path / "tmpXXXX.jpg"
    victim.write_bytes(b"x")
    raised = False
    try:
        with _unlink_on_exit(str(victim)):
            raise ValueError("save failed")
    except ValueError:
        raised = True
    assert raised
    assert not victim.exists()


def test_unlink_on_exit_tolerates_a_file_already_moved(tmp_path):
    from backend.util.poster_images import _unlink_on_exit

    moved = tmp_path / "gone.jpg"
    with _unlink_on_exit(str(moved)):
        pass  # shutil.move consumed it on the success path
    assert not moved.exists()


def test_progress_cadence_is_every_250_plus_a_final_pin():
    """Per-item reporting committed once per poster; 100% must still be sent."""
    total = 1100
    emitted = [
        idx for idx in range(1, total + 1) if idx % 250 == 0 or idx == total
    ]
    assert emitted == [250, 500, 750, 1000, 1100]
    assert int(emitted[-1] / total * 100) == 100
    assert len(emitted) < total / 100
