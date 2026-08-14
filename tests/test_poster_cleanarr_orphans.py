"""Tests for poster_cleanarr's orphan-asset deletion safety guards — the most
destructive path in the module (irreversible os.remove / shutil.move).

Covers: the empty-title-set guard that aborts mass deletion, instance-filtered
title-set construction (incl. alternate titles), and the report/move/remove
executor.
"""

from types import SimpleNamespace

import pytest

from backend.modules.poster_cleanarr import ORPHAN_RESTORE_DIR_NAME, PosterCleanarr
from backend.util.config import ChubConfig, ConfigError
from backend.util.database import ChubDB
from backend.util.normalization import normalize_titles
from backend.util.path_safety import resolve_confined


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


def _make(*allowed_roots):
    """Bare instance; `allowed_roots` seed the construction-time snapshot only."""
    m = object.__new__(PosterCleanarr)
    m.logger = _logger()
    m.full_config = ChubConfig()
    m.full_config.poster_renamerr.source_dirs = [str(r) for r in allowed_roots]
    return m


def _live(monkeypatch, *allowed_roots):
    """Point load_config at a config whose allowed roots are `allowed_roots`."""
    cfg = ChubConfig()
    cfg.poster_renamerr.source_dirs = [str(r) for r in allowed_roots]
    monkeypatch.setattr("backend.util.config.load_config", lambda: cfg)
    return cfg


def _collecting_logger():
    """(logger, errors) — the logger appends every error message to the list."""
    errors = []
    logger = _logger()
    logger.error = errors.append
    return logger, errors


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


def test_orphan_pass_aborts_when_title_set_empty(db, tmp_path, monkeypatch):
    """If media_cache is empty for the configured instances, the comparison
    set is empty and the pass must abort WITHOUT deleting anything — the last
    line of defense against wiping every asset."""
    m = _make(tmp_path)
    _live(monkeypatch, tmp_path)  # authorized, so the title-set guard is what aborts
    orphan = tmp_path / "Some Movie (2020).png"
    orphan.write_bytes(b"x")

    res = m._run_orphan_pass(
        db, ["radarr1"], [str(tmp_path)], "remove", False, _logger()
    )

    assert res["count"] == 0
    assert orphan.exists()  # nothing deleted


def test_orphan_pass_skips_asset_dir_outside_allowed_roots(db, tmp_path, monkeypatch):
    """A dir outside the allowed roots is refused at execution time; its neighbour still cleans."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    m = _make(allowed)
    cfg = _live(monkeypatch, allowed)
    assert resolve_confined(str(outside), cfg) is None  # control
    _seed_media(db, "k1", "radarr1", normalize_titles("Keeper (2020)"))
    confined_orphan = allowed / "Gone Movie (2019).png"
    confined_orphan.write_bytes(b"x")
    outside_orphan = outside / "Gone Movie (2019).png"
    outside_orphan.write_bytes(b"x")

    res = m._run_orphan_pass(
        db,
        ["radarr1"],
        [str(allowed), str(outside)],
        "remove",
        False,
        _logger(),
    )

    assert res["count"] == 1
    assert not confined_orphan.exists()  # allowed root still processed
    assert outside_orphan.exists()  # unauthorized root untouched


def test_orphan_pass_works_via_the_shim_shape_with_a_live_config(db, tmp_path, monkeypatch):
    """poster_renamerr's post-rename cleanup builds a bare instance — it must still clean."""
    m = object.__new__(PosterCleanarr)  # shim entry point's shape: no full_config
    m.logger = _logger()

    live = ChubConfig()
    live.poster_renamerr.destination_dir = str(tmp_path)
    monkeypatch.setattr("backend.util.config.load_config", lambda: live)

    _seed_media(db, "k1", "radarr1", normalize_titles("Keeper (2020)"))
    orphan = tmp_path / "Gone Movie (2019).png"
    orphan.write_bytes(b"x")

    res = m._run_orphan_pass(db, ["radarr1"], [str(tmp_path)], "remove", False, _logger())

    assert res["count"] == 1, res
    assert not orphan.exists()


def test_orphan_pass_fails_closed_when_config_unavailable(db, tmp_path, monkeypatch):
    """No config means no authorization, so the pass must delete nothing."""
    m = object.__new__(PosterCleanarr)  # shim entry point's shape: no full_config
    m.logger = _logger()

    def _boom():
        raise ConfigError("corrupt config")

    monkeypatch.setattr("backend.util.config.load_config", _boom)
    _seed_media(db, "k1", "radarr1", normalize_titles("Keeper (2020)"))
    orphan = tmp_path / "Gone Movie (2019).png"
    orphan.write_bytes(b"x")
    errors = []
    logger = _logger()
    logger.error = errors.append

    res = m._run_orphan_pass(db, ["radarr1"], [str(tmp_path)], "remove", False, logger)

    assert res["count"] == 0
    assert orphan.exists()  # nothing deleted on an unverifiable authorization
    assert errors  # and the refusal is logged, not silent


def test_build_title_set_filters_by_instance_and_absorbs_alternates(db):
    m = _make()
    _seed_media(db, "k1", "radarr1", "dune", '["dunepartone"]')
    _seed_media(db, "k2", "other_instance", "shouldbeignored")

    titles = m._build_library_title_set(db, ["radarr1"], include_collections=False)

    assert "dune" in titles
    assert "dunepartone" in titles  # alternate titles absorbed
    assert "shouldbeignored" not in titles  # other instance excluded


def test_execute_orphan_mode_report_then_remove(tmp_path, monkeypatch):
    """report counts but deletes nothing; remove actually deletes the file."""
    m = _make()
    _live(monkeypatch, tmp_path)
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


def test_execute_orphan_mode_move_relocates(tmp_path, monkeypatch):
    """The restore dir doesn't exist yet: the dest guard must authorize the
    parent makedirs creates, not the leaf, or moves silently stop happening."""
    m = _make()
    _live(monkeypatch, tmp_path)
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
    assert (tmp_path / ORPHAN_RESTORE_DIR_NAME / "orphan.png").exists()


# ── Live-config authorization + per-target re-confinement ────────────────────


def test_orphan_pass_ignores_the_construction_time_config_snapshot(
    db, tmp_path, monkeypatch
):
    """A root removed from config after the module was built must stop
    authorizing: the worker reads the live config, never self.full_config."""
    m = _make(tmp_path)  # the construction-time snapshot still carries the root
    _live(monkeypatch)  # ...but the live config no longer allows anything
    _seed_media(db, "k1", "radarr1", normalize_titles("Keeper (2020)"))
    orphan = tmp_path / "Gone Movie (2019).png"
    orphan.write_bytes(b"x")
    logger, errors = _collecting_logger()

    assert m._authorized_asset_dirs([str(tmp_path)], logger) == []
    res = m._run_orphan_pass(db, ["radarr1"], [str(tmp_path)], "remove", False, logger)

    assert res["count"] == 0
    assert orphan.exists()  # the de-authorized root is not cleaned
    assert errors  # and the refusal is logged, not silent


def _swap_parent_for_link(allowed, outside):
    """Orphan item under `allowed` whose parent then becomes a link to `outside`."""
    show = allowed / "Show"
    show.mkdir()
    scanned = show / "poster.png"
    scanned.write_bytes(b"x")
    item = {
        "path": str(scanned),
        "size": 1,
        "parsed": "show",
        "asset_dir": str(allowed),
    }
    scanned.unlink()
    show.rmdir()
    show.symlink_to(outside, target_is_directory=True)
    return item


def _write(tmp_path, name):
    f = tmp_path / name
    f.write_bytes(b"x")
    return f


def test_scan_tmdb_id_match_spares_title_mismatch(tmp_path):
    """A {tmdb-N} tag whose id IS in the library spares the file even when its
    title doesn't match anything in the title set."""
    m = _make()
    _write(tmp_path, "Renamed Title (2020) {tmdb-123}.png")

    orphans = m._scan_orphan_assets(
        [str(tmp_path)], library_titles=set(), tmdb_ids={123}, tvdb_ids=set()
    )

    assert orphans == []


def test_scan_tvdb_id_match_spares_title_mismatch(tmp_path):
    """tvdb id matching spares the same way as tmdb."""
    m = _make()
    _write(tmp_path, "Renamed Show (2019) {tvdb-555}.png")

    orphans = m._scan_orphan_assets(
        [str(tmp_path)], library_titles=set(), tmdb_ids=set(), tvdb_ids={555}
    )

    assert orphans == []


def test_scan_id_miss_falls_back_to_title(tmp_path):
    """Spare-only: a {tmdb-N} NOT in the library does not flag the file — it
    falls through to the title check, which here matches, so it's kept."""
    m = _make()
    _write(tmp_path, "Some Movie (2020) {tmdb-999}.png")
    title_key = normalize_titles("Some Movie (2020)")

    orphans = m._scan_orphan_assets(
        [str(tmp_path)],
        library_titles={title_key},  # title matches
        tmdb_ids={123},  # 999 not present, but that must NOT flag
        tvdb_ids=set(),
    )

    assert orphans == []  # stale id but matching title -> kept


def test_scan_flags_only_when_id_and_title_both_miss(tmp_path):
    """The single removal path: neither the id tag nor the title matches."""
    m = _make()
    f = _write(tmp_path, "Some Movie (2020) {tmdb-999}.png")

    orphans = m._scan_orphan_assets(
        [str(tmp_path)],
        library_titles=set(),  # title misses
        tmdb_ids={123},  # id misses
        tvdb_ids=set(),
    )

    assert len(orphans) == 1
    assert orphans[0]["path"] == str(f)


def test_scan_ignore_list_spares_unmatched(tmp_path):
    """A title in the ignore set is never flagged, even with no library match
    and no id tag."""
    m = _make()
    _write(tmp_path, "Personal Poster.png")

    orphans = m._scan_orphan_assets(
        [str(tmp_path)],
        library_titles=set(),
        tmdb_ids=set(),
        tvdb_ids=set(),
        ignore_keys={normalize_titles("Personal Poster")},
    )

    assert orphans == []


# ── Dead-symlink sweep ───────────────────────────────────────────────────────


def test_scan_flags_broken_symlink_even_when_title_matches(tmp_path):
    """A symlink whose target is gone is flagged as a dead link BEFORE the
    spare-only checks — so it's caught even when its title matches the library
    (which would otherwise spare it)."""
    m = _make()
    link = tmp_path / "Some Movie (2020).png"
    link.symlink_to(tmp_path / "missing_target.png")  # target never created
    title_key = normalize_titles("Some Movie (2020)")

    orphans = m._scan_orphan_assets(
        [str(tmp_path)],
        library_titles={title_key},  # title matches — normally a spare
        tmdb_ids=set(),
        tvdb_ids=set(),
    )

    assert len(orphans) == 1
    assert orphans[0]["path"] == str(link)
    assert orphans[0]["reason"] == "dead_link"


def test_scan_spares_healthy_symlink_with_matching_title(tmp_path):
    """A symlink whose target exists is not a dead link; normal title matching
    applies, so a matching title spares it."""
    m = _make()
    assets = tmp_path / "assets"
    assets.mkdir()
    target = tmp_path / "real_target.png"  # outside the scanned asset dir
    target.write_bytes(b"x")
    link = assets / "Some Movie (2020).png"
    link.symlink_to(target)

    orphans = m._scan_orphan_assets(
        [str(assets)],
        library_titles={normalize_titles("Some Movie (2020)")},
        tmdb_ids=set(),
        tvdb_ids=set(),
    )

    assert orphans == []


def test_scan_dead_link_circuit_breaker_skips_when_target_unmounted(tmp_path):
    """When most links are broken — what an unmounted link target looks like —
    the sweep is skipped to avoid mass-flagging good links."""
    m = _make()
    for i in range(25):  # > DEAD_LINK_MIN_FOR_RATIO, 100% broken > the ratio
        (tmp_path / f"Title {i} (2020).png").symlink_to(tmp_path / f"missing_{i}.png")

    orphans = m._scan_orphan_assets(
        [str(tmp_path)],
        library_titles=set(),
        tmdb_ids=set(),
        tvdb_ids=set(),
    )

    assert orphans == []  # breaker tripped → nothing flagged


def test_resolve_orphan_instances_prefers_orphan_instances():
    """When orphan_instances is set, it is used as the comparison-set source."""
    cfg = SimpleNamespace(orphan_instances=["radarr1", "sonarr1"], instances=["plex1"])
    assert PosterCleanarr._resolve_orphan_instances(cfg) == ["radarr1", "sonarr1"]


def test_resolve_orphan_instances_falls_back_to_instances_when_empty():
    """Pre-split configs listed ARR names in `instances`; an empty
    `orphan_instances` must fall back to `instances` so they keep working."""
    cfg = SimpleNamespace(
        orphan_instances=[], instances=["plex1", "radarr1", "sonarr1"]
    )
    assert PosterCleanarr._resolve_orphan_instances(cfg) == [
        "plex1",
        "radarr1",
        "sonarr1",
    ]


def test_resolve_orphan_instances_handles_missing_attrs():
    """Missing/None attributes degrade to an empty list, never raise."""
    assert PosterCleanarr._resolve_orphan_instances(SimpleNamespace()) == []
    cfg = SimpleNamespace(orphan_instances=None, instances=None)
    assert PosterCleanarr._resolve_orphan_instances(cfg) == []


def test_build_library_id_sets_filters_by_instance(db):
    m = _make()
    db.media.execute_query(
        "INSERT INTO media_cache (identity_key, instance_name, normalized_title, "
        "tmdb_id, tvdb_id, asset_type) VALUES (?,?,?,?,?,?)",
        ("k1", "radarr1", "dune", 12345, None, "movie"),
    )
    db.media.execute_query(
        "INSERT INTO media_cache (identity_key, instance_name, normalized_title, "
        "tmdb_id, tvdb_id, asset_type) VALUES (?,?,?,?,?,?)",
        ("k2", "sonarr1", "show", None, 67890, "series"),
    )
    db.media.execute_query(
        "INSERT INTO media_cache (identity_key, instance_name, normalized_title, "
        "tmdb_id, tvdb_id, asset_type) VALUES (?,?,?,?,?,?)",
        ("k3", "other", "ignored", 99999, None, "movie"),
    )

    tmdb_ids, tvdb_ids = m._build_library_id_sets(db, ["radarr1", "sonarr1"])

    assert tmdb_ids == {12345}
    assert tvdb_ids == {67890}
    assert 99999 not in tmdb_ids  # other instance excluded
