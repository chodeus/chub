"""Tests for poster_cleanarr's orphan-asset deletion safety guards — the most
destructive path in the module (irreversible os.remove / shutil.move).

Covers: the empty-title-set guard that aborts mass deletion, instance-filtered
title-set construction (incl. alternate titles), and the report/move/remove
executor.
"""

from types import SimpleNamespace

import pytest

from backend.modules.poster_cleanarr import PosterCleanarr
from backend.util.database import ChubDB


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


def _make():
    m = object.__new__(PosterCleanarr)
    m.logger = _logger()
    return m


@pytest.fixture
def db(tmp_path):
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as database:
        yield database


def _seed_media(db, identity_key, instance_name, normalized_title, alt=None):
    db.media.execute_query(
        "INSERT INTO media_cache (identity_key, instance_name, normalized_title, "
        "normalized_alternate_titles, asset_type) VALUES (?,?,?,?,?)",
        (identity_key, instance_name, normalized_title, alt, "movie"),
    )


def test_orphan_pass_aborts_when_title_set_empty(db, tmp_path):
    """If media_cache is empty for the configured instances, the comparison
    set is empty and the pass must abort WITHOUT deleting anything — the last
    line of defense against wiping every asset."""
    m = _make()
    orphan = tmp_path / "Some Movie (2020).png"
    orphan.write_bytes(b"x")

    res = m._run_orphan_pass(
        db, ["radarr1"], [str(tmp_path)], "remove", False, _logger()
    )

    assert res["count"] == 0
    assert orphan.exists()  # nothing deleted


def test_build_title_set_filters_by_instance_and_absorbs_alternates(db):
    m = _make()
    _seed_media(db, "k1", "radarr1", "dune", '["dunepartone"]')
    _seed_media(db, "k2", "other_instance", "shouldbeignored")

    titles = m._build_library_title_set(db, ["radarr1"], include_collections=False)

    assert "dune" in titles
    assert "dunepartone" in titles  # alternate titles absorbed
    assert "shouldbeignored" not in titles  # other instance excluded


def test_execute_orphan_mode_report_then_remove(tmp_path):
    """report counts but deletes nothing; remove actually deletes the file."""
    m = _make()
    f = tmp_path / "orphan.png"
    f.write_bytes(b"x")
    orphan = {
        "path": str(f),
        "size": 1,
        "parsed": "orphan",
        "asset_dir": str(tmp_path),
    }

    report = m._execute_orphan_mode([dict(orphan)], "report", _logger())
    assert report["count"] == 1
    assert f.exists()  # report never deletes

    removed = m._execute_orphan_mode([dict(orphan)], "remove", _logger())
    assert removed["count"] == 1
    assert not f.exists()  # remove deletes


def test_execute_orphan_mode_move_relocates(tmp_path):
    m = _make()
    f = tmp_path / "orphan.png"
    f.write_bytes(b"x")
    orphan = {
        "path": str(f),
        "size": 1,
        "parsed": "orphan",
        "asset_dir": str(tmp_path),
    }

    res = m._execute_orphan_mode([orphan], "move", _logger())
    assert res["count"] == 1
    assert not f.exists()  # moved out of its original location
