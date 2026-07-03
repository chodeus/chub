"""Tests for the off-loop Poster Cleanarr scan jobs: the cache-only readers,
the background scan-job handlers that warm those caches, and the enqueue dedup
that keeps a single scan in flight. These guarantee the API never walks the
Plex Metadata / Kometa asset trees on the event loop."""

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


def test_get_cached_scan_is_none_before_scan(tmp_path):
    from backend.util import plex_metadata as pm

    pm.invalidate_cache()
    assert pm.get_cached_scan(str(tmp_path)) is None
    assert pm.get_cached_transcoder(str(tmp_path)) is None


def test_plex_metadata_scan_job_warms_cache(tmp_path):
    from backend.util import plex_metadata as pm
    from backend.util.job_processor import _process_plex_metadata_scan_job

    pm.invalidate_cache()
    plex_path = str(tmp_path)
    # scan_bundles only caches when the Metadata dir exists (an absent dir is an
    # early empty return), so create it to exercise the cache-warming path.
    (tmp_path / "Metadata").mkdir()

    assert pm.get_cached_scan(plex_path) is None
    res = _process_plex_metadata_scan_job({"plex_path": plex_path}, _logger(), 1)
    assert res["success"] is True
    # The walk ran on this (worker) call; the API read path now finds it cached.
    assert pm.get_cached_scan(plex_path) is not None
    assert pm.get_cached_transcoder(plex_path) == {"count": 0, "size_bytes": 0}


def test_scan_with_posters_but_no_db_is_unavailable_and_not_cached(tmp_path):
    from backend.util import plex_metadata as pm

    pm.invalidate_cache()
    plex_path = str(tmp_path)
    # A real uploaded poster on disk (extension-less hash under a .bundle/Uploads/),
    # but NO Plex DB to copy — so the scan can't tell what's in use. It must NOT flag
    # every poster as deletable bloat and cache that: a transient DB blip would then
    # drive the (unguarded) per-variant delete to remove active artwork for the TTL.
    uploads = tmp_path / "Metadata" / "Movies" / "a" / "x.bundle" / "Uploads" / "posters"
    uploads.mkdir(parents=True)
    (uploads / "abc123").write_bytes(b"posterdata")  # extension-less = a real upload variant

    res = pm.scan_bundles(plex_path, force=True)
    assert res.get("unavailable") is True
    # A transient DB failure is not negative-cached — a re-scan once the DB is
    # readable returns the real answer.
    assert pm.get_cached_scan(plex_path) is None


def test_plex_metadata_scan_job_requires_plex_path():
    from backend.util.job_processor import _process_plex_metadata_scan_job

    res = _process_plex_metadata_scan_job({}, _logger(), 1)
    assert res["success"] is False
    assert res["error_code"] == "PLEX_PATH_UNSET"


def test_bloat_flat_from_scan_excludes_active_and_plex_sourced():
    from backend.util.plex_metadata import bloat_flat_from_scan

    scan = {
        "bundles": [
            {
                "bundle_path": "/b",
                "rating_key": 1,
                "title": "X",
                "year": 2000,
                "variants": [
                    {
                        "filename": "a",
                        "path": "/b/a",
                        "size": 10,
                        "active": True,
                        "source": "uploads",
                    },
                    {
                        "filename": "b",
                        "path": "/b/b",
                        "size": 30,
                        "active": False,
                        "source": "uploads",
                    },
                    {
                        "filename": "c",
                        "path": "/b/c",
                        "size": 20,
                        "active": False,
                        "source": "plex",
                    },
                ],
            }
        ]
    }
    flat = bloat_flat_from_scan(scan)
    # Active 'a' and Plex-sourced 'c' are never bloat; only the deletable
    # upload 'b' remains, and it carries the owning bundle's identity.
    assert [f["filename"] for f in flat] == ["b"]
    assert flat[0]["rating_key"] == 1 and flat[0]["size"] == 30


def test_get_cached_kometa_assets_is_none_before_scan():
    from backend.modules import poster_cleanarr as pcl

    with pcl._kometa_cache_lock:
        pcl._kometa_cache.clear()
    assert pcl.get_cached_kometa_assets() is None


def test_scan_jobs_dedup_to_single_in_flight(db):
    a = db.worker.enqueue_job(
        "jobs", {"plex_path": "/plex"}, job_type="plex_metadata_scan"
    )
    b = db.worker.enqueue_job(
        "jobs", {"plex_path": "/plex"}, job_type="plex_metadata_scan"
    )
    assert a["data"]["job_id"] == b["data"]["job_id"]
    assert b.get("deduped") is True

    k1 = db.worker.enqueue_job("jobs", {}, job_type="kometa_assets_scan")
    k2 = db.worker.enqueue_job("jobs", {}, job_type="kometa_assets_scan")
    assert k1["data"]["job_id"] == k2["data"]["job_id"]
    assert k2.get("deduped") is True

    # Distinct scan types don't collide with each other.
    assert a["data"]["job_id"] != k1["data"]["job_id"]
