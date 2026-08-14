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
import errno
import os

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


def test_execute_orphan_mode_remove_refuses_a_swapped_parent(tmp_path, monkeypatch):
    """A parent component swapped to a symlink between scan and os.remove must not delete the file it now points at."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    victim = outside / "poster.png"
    victim.write_bytes(b"x")
    m = _make(allowed)
    _live(monkeypatch, allowed)
    item = _swap_parent_for_link(allowed, outside)
    logger, errors = _collecting_logger()

    res = m._execute_orphan_mode([item], "remove", logger)

    assert res["count"] == 0
    assert victim.exists()  # the swapped-in target is untouched
    assert errors


def test_execute_orphan_mode_move_refuses_a_swapped_parent(tmp_path, monkeypatch):
    """Same swap on the move path — shutil.move must not relocate an outside file."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    victim = outside / "poster.png"
    victim.write_bytes(b"x")
    m = _make(allowed)
    _live(monkeypatch, allowed)
    item = _swap_parent_for_link(allowed, outside)
    logger, errors = _collecting_logger()

    res = m._execute_orphan_mode([item], "move", logger)

    assert res["count"] == 0
    assert victim.exists()  # not dragged into the restore dir
    assert errors


def test_execute_orphan_mode_move_refuses_a_symlinked_restore_dir(
    tmp_path, monkeypatch
):
    """The move destination is confined too: a restore dir linking outside the roots must not receive the file."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    (allowed / ORPHAN_RESTORE_DIR_NAME).symlink_to(outside, target_is_directory=True)
    f = allowed / "orphan.png"
    f.write_bytes(b"x")
    item = {"path": str(f), "size": 1, "parsed": "orphan", "asset_dir": str(allowed)}
    m = _make(allowed)
    _live(monkeypatch, allowed)
    logger, errors = _collecting_logger()

    res = m._execute_orphan_mode([item], "move", logger)

    assert res["count"] == 0
    assert f.exists()  # left in place
    assert not (outside / "orphan.png").exists()  # nothing written outside
    assert errors


def test_clean_empty_dirs_refuses_a_dir_outside_the_roots(tmp_path, monkeypatch):
    """The empty-dir sweep re-confines each dir: an asset dir swapped to a link must not have the outside tree pruned through it."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    stray = outside / "empty"
    stray.mkdir()
    cfg = _live(monkeypatch, allowed)
    swapped = allowed / "assets"
    swapped.symlink_to(outside, target_is_directory=True)
    m = _make(allowed)
    m.logger, errors = _collecting_logger()

    assert m._clean_empty_dirs(str(swapped), cfg) == 0
    assert stray.exists()  # pruning stops at the roots
    assert errors


def test_clean_empty_dirs_refuses_a_dir_outside_base_dir_without_a_config(
    tmp_path, monkeypatch
):
    """The bloat pass prunes with no config at all, so base_dir is the only floor: a component swapped mid-sweep must not have rmdir reach past it."""
    base = tmp_path / "metadata"
    show = base / "Show"
    (show / "empty").mkdir(parents=True)
    outside = tmp_path / "outside"
    (outside / "empty").mkdir(parents=True)
    m = _make()
    m.logger, errors = _collecting_logger()

    real_listdir = os.listdir
    swapped = []

    def _swapping_listdir(path, *a, **kw):
        """Swap `Show` for a link to `outside` between the walk and the rmdir."""
        if not swapped and str(path) == str(show / "empty"):
            swapped.append(True)
            show.rename(base / "Show_real")
            show.symlink_to(outside, target_is_directory=True)
        return real_listdir(path, *a, **kw)

    monkeypatch.setattr(os, "listdir", _swapping_listdir)

    assert m._clean_empty_dirs(str(base)) == 0
    assert swapped  # the race window was actually entered
    assert (outside / "empty").is_dir()  # pruning stops at base_dir
    assert errors


def test_clean_empty_dirs_still_prunes_inside_base_dir_without_a_config(tmp_path):
    """The floor must not disable the bloat pass, which passes no config."""
    base = tmp_path / "metadata"
    (base / "Show" / "empty").mkdir(parents=True)
    m = _make()

    assert m._clean_empty_dirs(str(base)) == 2
    assert not (base / "Show").exists()  # pruned bottom-up, base kept


# ── Descriptor-bound deletion (the race re-confinement only narrows) ─────────


def _orphan_item(path, asset_dir):
    """An orphan entry for `path`, as _scan_orphan_assets would emit it."""
    return {
        "path": str(path),
        "size": 1,
        "parsed": "orphan",
        "asset_dir": str(asset_dir),
    }


def test_execute_orphan_mode_remove_unlinks_through_a_parent_descriptor(
    tmp_path, monkeypatch
):
    """The delete goes through os.unlink(name, dir_fd=...) on the confined parent — a bare os.remove(path) would resolve the path a second time."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    f = allowed / "orphan.png"
    f.write_bytes(b"x")
    m = _make(allowed)
    _live(monkeypatch, allowed)

    calls = []
    real_unlink = os.unlink

    def _recording_unlink(path, *a, dir_fd=None, **kw):
        """Record the name/descriptor pair, then delegate to the real unlink."""
        calls.append((path, dir_fd))
        return real_unlink(path, *a, dir_fd=dir_fd, **kw)

    # `os` here is the same module object poster_cleanarr calls through.
    monkeypatch.setattr(os, "unlink", _recording_unlink)
    res = m._execute_orphan_mode([_orphan_item(f, allowed)], "remove", _logger())

    assert res["count"] == 1
    assert not f.exists()
    assert [name for name, _fd in calls] == ["orphan.png"]  # the NAME, not the path
    assert calls[0][1] is not None  # ...resolved against a descriptor


def test_execute_orphan_mode_remove_refuses_a_parent_swapped_after_the_check(
    tmp_path, monkeypatch
):
    """The parent is re-pointed at an outside dir the instant after it is opened: the descriptor pin must refuse rather than delete through the new path."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    victim = outside / "poster.png"
    victim.write_bytes(b"x")
    show = allowed / "Show"
    show.mkdir()
    f = show / "poster.png"
    f.write_bytes(b"x")
    m = _make(allowed)
    _live(monkeypatch, allowed)

    real_open = os.open

    def _swapping_open(path, *a, **kw):
        """Open normally, then re-point that same dir at `outside`."""
        fd = real_open(path, *a, **kw)
        # Match on the basename: the walk opens each component by NAME.
        if (
            os.path.basename(str(path)) == show.name
            and show.is_dir()
            and not show.is_symlink()
        ):
            show.rename(allowed / "Show_real")
            show.symlink_to(outside, target_is_directory=True)
        return fd

    monkeypatch.setattr(os, "open", _swapping_open)
    logger, errors = _collecting_logger()
    res = m._execute_orphan_mode([_orphan_item(f, allowed)], "remove", logger)

    assert res["count"] == 0
    assert victim.exists()  # the swapped-in dir is never deleted through
    assert (allowed / "Show_real" / "poster.png").exists()  # nor the pinned one
    assert errors


def test_execute_orphan_mode_remove_refuses_an_intermediate_component_swapped_after_confinement(
    tmp_path, monkeypatch
):
    """An INTERMEDIATE component becomes a link once confinement has passed."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    lib = allowed / "lib"
    show = lib / "Show"
    show.mkdir(parents=True)
    f = show / "poster.png"
    f.write_bytes(b"x")
    victim = outside / "Show" / "poster.png"
    victim.parent.mkdir(parents=True)
    victim.write_bytes(b"x")
    m = _make(allowed)
    _live(monkeypatch, allowed)

    real_open = os.open
    swapped = []

    def _swapping_open(path, *a, **kw):
        """Swap `lib` for a link to `outside` in the check→open window."""
        if not swapped and str(path).startswith(os.path.realpath(allowed)):
            swapped.append(True)
            lib.rename(allowed / "lib_real")
            lib.symlink_to(outside, target_is_directory=True)
        return real_open(path, *a, **kw)

    monkeypatch.setattr(os, "open", _swapping_open)
    logger, errors = _collecting_logger()

    res = m._execute_orphan_mode([_orphan_item(f, allowed)], "remove", logger)

    assert swapped  # the race window was actually entered
    assert res["count"] == 0
    assert victim.exists()  # the swapped-in tree is never deleted through
    assert (allowed / "lib_real" / "Show" / "poster.png").exists()  # nor the real one
    assert errors


def test_execute_orphan_mode_remove_deletes_the_link_not_its_target(
    tmp_path, monkeypatch
):
    """An orphaned symlink is unlinked by name; resolving it first would delete the artwork it points at."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "keep.png"
    target.write_bytes(b"x")
    link = allowed / "orphan.png"
    link.symlink_to(target)
    m = _make(allowed)
    _live(monkeypatch, allowed)

    res = m._execute_orphan_mode([_orphan_item(link, allowed)], "remove", _logger())

    assert res["count"] == 1
    assert not link.is_symlink()  # the link entry is gone
    assert target.exists()  # its target survives


def test_execute_orphan_mode_remove_sweeps_dead_links_only_inside_the_roots(
    tmp_path, monkeypatch
):
    """Behaviour change to keep visible: confinement resolves a link's TARGET, so the dead-link sweep still clears links into a root but now refuses links pointing at an unconfigured directory."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    inside_link = allowed / "gone-inside.png"
    inside_link.symlink_to(allowed / "missing.png")
    outside_link = allowed / "gone-outside.png"
    outside_link.symlink_to(outside / "missing.png")
    m = _make(allowed)
    _live(monkeypatch, allowed)
    logger, errors = _collecting_logger()

    res = m._execute_orphan_mode(
        [_orphan_item(inside_link, allowed), _orphan_item(outside_link, allowed)],
        "remove",
        logger,
    )

    assert res["count"] == 1
    assert not inside_link.is_symlink()  # dead link into a root: still swept
    assert outside_link.is_symlink()  # dead link out of the roots: refused
    assert errors


def test_execute_orphan_mode_aggregates_refusals_into_one_error(tmp_path, monkeypatch):
    """Links into unconfigured storage are retained and re-refused every pass, so the refusals collapse to one summary line; detail moves to debug."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    items = []
    for i in range(5):
        link = allowed / f"gone-{i}.png"
        link.symlink_to(outside / f"missing-{i}.png")
        items.append(_orphan_item(link, allowed))
    m = _make(allowed)
    _live(monkeypatch, allowed)
    logger, errors = _collecting_logger()
    debugs = []
    logger.debug = debugs.append

    res = m._execute_orphan_mode(items, "remove", logger)

    assert res["count"] == 0
    assert len(errors) == 1  # one line per pass, not one per link
    assert "refused 5 path(s)" in errors[0]
    assert len(debugs) == 5  # per-link detail retained at debug


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


# ── Anchored moves, anchored rmdir, per-item authorization ──────────────────


def test_execute_orphan_mode_move_renames_through_both_parent_descriptors(
    tmp_path, monkeypatch
):
    """The move is an os.rename resolved against a descriptor on each parent, not a path pair shutil re-walks."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    f = allowed / "orphan.png"
    f.write_bytes(b"x")
    m = _make(allowed)
    _live(monkeypatch, allowed)

    calls = []
    real_rename = os.rename

    def _recording_rename(src, dst, **kw):
        calls.append((src, dst, kw.get("src_dir_fd"), kw.get("dst_dir_fd")))
        return real_rename(src, dst, **kw)

    monkeypatch.setattr(os, "rename", _recording_rename)

    res = m._execute_orphan_mode([_orphan_item(f, allowed)], "move", _logger())

    assert res["count"] == 1
    assert (allowed / ORPHAN_RESTORE_DIR_NAME / "orphan.png").exists()
    assert len(calls) == 1
    src, dst, src_fd, dst_fd = calls[0]
    assert (src, dst) == ("orphan.png", "orphan.png")  # bare names, not paths
    assert src_fd is not None and dst_fd is not None  # ...against both fds


def test_execute_orphan_mode_move_refuses_a_parent_swapped_after_the_check(
    tmp_path, monkeypatch
):
    """The source parent becomes a link to an outside dir the instant after confinement passes: the move must refuse, not relocate the outside file."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    victim = outside / "poster.png"
    victim.write_bytes(b"x")
    show = allowed / "Show"
    show.mkdir()
    f = show / "poster.png"
    f.write_bytes(b"x")
    m = _make(allowed)
    _live(monkeypatch, allowed)
    logger, errors = _collecting_logger()

    real_confined = m._confined_target
    swapped = []

    def _swapping_confined(path, config, log):
        """Swap `Show` for a link to `outside` once the file itself is confined."""
        result = real_confined(path, config, log)
        if not swapped and str(path) == str(f):
            swapped.append(True)
            show.rename(allowed / "Show_real")
            show.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(m, "_confined_target", _swapping_confined)

    res = m._execute_orphan_mode([_orphan_item(f, allowed)], "move", logger)

    assert swapped  # the race window was actually entered
    assert res["count"] == 0
    assert victim.exists()  # never dragged into the restore dir
    assert (allowed / "Show_real" / "poster.png").exists()  # nor the pinned one
    assert errors


def test_execute_orphan_mode_move_falls_back_across_devices(tmp_path, monkeypatch):
    """EXDEV is the one case the anchored rename can't serve: it must fall back to the copy path, not drop the move."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    f = allowed / "orphan.png"
    f.write_bytes(b"x")
    m = _make(allowed)
    _live(monkeypatch, allowed)

    def _cross_device(*a, **kw):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    # shutil.move's own os.rename is patched too, so it takes its copy branch.
    monkeypatch.setattr(os, "rename", _cross_device)
    logger, errors = _collecting_logger()

    res = m._execute_orphan_mode([_orphan_item(f, allowed)], "move", logger)

    assert res["count"] == 1
    assert not f.exists()
    assert (allowed / ORPHAN_RESTORE_DIR_NAME / "orphan.png").exists()
    assert not errors  # a cross-device move is normal, not a refusal


def test_clean_empty_dirs_rmdirs_through_a_parent_descriptor(tmp_path, monkeypatch):
    """With a config the prune goes through os.rmdir(name, dir_fd=...) — a bare os.rmdir(path) would re-walk every component."""
    allowed = tmp_path / "allowed"
    (allowed / "Show" / "empty").mkdir(parents=True)
    cfg = _live(monkeypatch, allowed)
    m = _make(allowed)
    m.logger, errors = _collecting_logger()

    calls = []
    real_rmdir = os.rmdir

    def _recording_rmdir(path, *a, dir_fd=None, **kw):
        calls.append((path, dir_fd))
        return real_rmdir(path, *a, dir_fd=dir_fd, **kw)

    monkeypatch.setattr(os, "rmdir", _recording_rmdir)

    assert m._clean_empty_dirs(str(allowed), cfg) == 2
    assert not (allowed / "Show").exists()  # pruned bottom-up, root kept
    assert [name for name, _fd in calls] == ["empty", "Show"]  # names, not paths
    assert all(fd is not None for _name, fd in calls)
    assert not errors


def test_clean_empty_dirs_refuses_a_parent_swapped_after_the_check(
    tmp_path, monkeypatch
):
    """A parent swapped to a link in the confine→rmdir window must not have the outside tree pruned through it."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    (outside / "empty").mkdir(parents=True)
    base = allowed / "assets"
    show = base / "Show"
    (show / "empty").mkdir(parents=True)
    cfg = _live(monkeypatch, allowed)
    m = _make(allowed)
    m.logger, errors = _collecting_logger()

    real_confined = m._confined_target
    swapped = []

    def _swapping_confined(path, config, log):
        """Swap `Show` for a link to `outside` once its child dir is confined."""
        result = real_confined(path, config, log)
        if not swapped and str(path) == str(show / "empty"):
            swapped.append(True)
            show.rename(base / "Show_real")
            show.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(m, "_confined_target", _swapping_confined)

    assert m._clean_empty_dirs(str(base), cfg) == 0
    assert swapped  # the race window was actually entered
    assert (outside / "empty").is_dir()  # pruning never reached through the link
    assert errors


def test_execute_orphan_mode_stops_when_config_stops_authorizing(
    tmp_path, tightening_config
):
    """Config is re-read per item, so a root dropped mid-batch stops the tail while the head — authorized when its turn came — still ran."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    head = allowed / "head.png"
    head.write_bytes(b"x")
    tail = allowed / "tail.png"
    tail.write_bytes(b"x")
    m = _make(allowed)
    calls = tightening_config(allowed)
    logger, errors = _collecting_logger()

    res = m._execute_orphan_mode(
        [_orphan_item(head, allowed), _orphan_item(tail, allowed)], "remove", logger
    )

    assert res["count"] == 1
    assert not head.exists()
    assert tail.exists()  # de-authorized before its turn
    assert len(calls) >= 2  # one load per item, not one per batch
    # Labelled by pass, so an empty-dir-sweep refusal cannot satisfy it.
    assert ["Orphan cleanup: refused 1 path(s)" in e for e in errors].count(True) == 1


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
