import os
from types import SimpleNamespace

from backend.modules.sync_gdrive import SyncGDrive


def _module(tmp_path, locations, dry_run=False, prune=True, cancelled=False):
    m = object.__new__(SyncGDrive)
    m.logger = SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    m.config = SimpleNamespace(
        gdrive_list=[SimpleNamespace(location=str(tmp_path / p)) for p in locations],
        dry_run=dry_run,
        prune_orphan_drives=prune,
    )
    m._cancel_event = None
    m.is_cancelled = lambda: cancelled
    return m


def _mkdrive(tmp_path, rel, files=0):
    d = tmp_path / rel
    d.mkdir(parents=True, exist_ok=True)
    for i in range(files):
        (d / f"p{i}.jpg").write_bytes(b"x")
    return d


def test_removes_empty_orphan_only(tmp_path):
    _mkdrive(tmp_path, "posters/MM2K/Live", files=3)
    gone = _mkdrive(tmp_path, "posters/MM2K/Reitenth")           # orphan, empty
    keep = _mkdrive(tmp_path, "posters/MM2K/OldGuy", files=5)    # orphan, populated
    m = _module(tmp_path, ["posters/MM2K/Live"])
    removed, kept = m._prune_orphan_drive_folders()
    assert removed == [str(gone)]
    assert kept == [(str(keep), 5)]
    assert not gone.exists() and keep.exists()


def test_configured_drive_is_never_touched_even_when_empty(tmp_path):
    # A configured drive whose remote emptied must survive — it refills next sync.
    empty_but_configured = _mkdrive(tmp_path, "posters/MM2K/IamSpartacus")
    m = _module(tmp_path, ["posters/MM2K/IamSpartacus"])
    removed, kept = m._prune_orphan_drive_folders()
    assert removed == [] and kept == []
    assert empty_but_configured.exists()


def test_only_scans_dirs_holding_a_configured_drive(tmp_path):
    _mkdrive(tmp_path, "posters/MM2K/Live", files=1)
    # A sibling tree with no configured drive must be invisible to the sweep.
    untouched = _mkdrive(tmp_path, "unrelated/SomethingElse")
    m = _module(tmp_path, ["posters/MM2K/Live"])
    removed, _ = m._prune_orphan_drive_folders()
    assert removed == []
    assert untouched.exists()


def test_nested_empty_subdirs_still_count_as_empty(tmp_path):
    _mkdrive(tmp_path, "posters/MM2K/Live", files=1)
    orphan = _mkdrive(tmp_path, "posters/MM2K/Gone/sub/deeper")
    m = _module(tmp_path, ["posters/MM2K/Live"])
    removed, kept = m._prune_orphan_drive_folders()
    assert removed == [str(tmp_path / "posters/MM2K/Gone")] and kept == []
    assert not orphan.exists()


def test_dry_run_reports_without_deleting(tmp_path):
    _mkdrive(tmp_path, "posters/MM2K/Live", files=1)
    orphan = _mkdrive(tmp_path, "posters/MM2K/Reitenth")
    m = _module(tmp_path, ["posters/MM2K/Live"], dry_run=True)
    removed, _ = m._prune_orphan_drive_folders()
    assert removed == [str(orphan)]
    assert orphan.exists(), "dry run must not delete"


def test_symlinked_dir_is_skipped(tmp_path):
    _mkdrive(tmp_path, "posters/MM2K/Live", files=1)
    outside = _mkdrive(tmp_path, "outside/precious", files=2)
    link = tmp_path / "posters/MM2K/link"
    os.symlink(outside, link)
    m = _module(tmp_path, ["posters/MM2K/Live"])
    removed, kept = m._prune_orphan_drive_folders()
    assert removed == [] and kept == []
    assert outside.exists() and link.is_symlink()


def test_disabled_by_config(tmp_path):
    _mkdrive(tmp_path, "posters/MM2K/Live", files=1)
    orphan = _mkdrive(tmp_path, "posters/MM2K/Reitenth")
    m = _module(tmp_path, ["posters/MM2K/Live"], prune=False)
    m._report_orphan_drive_folders()
    assert orphan.exists()


def test_no_configured_drives_is_a_noop(tmp_path):
    orphan = _mkdrive(tmp_path, "posters/MM2K/Reitenth")
    m = _module(tmp_path, [])
    assert m._prune_orphan_drive_folders() == ([], [])
    assert orphan.exists()


def test_symlinked_configured_location_does_not_widen_the_cleanup_root(tmp_path):
    """A configured location that is itself a symlink must not put the tree it
    points into in scope. realpath() would otherwise make the TARGET's parent a
    cleanup root, exposing unrelated sibling directories to deletion."""
    shared = tmp_path / "shared"
    (shared / "Live").mkdir(parents=True)
    (shared / "Live" / "p.jpg").write_bytes(b"x")
    precious = shared / "PreciousEmptyDir"
    precious.mkdir()

    posters = tmp_path / "posters" / "MM2K"
    posters.mkdir(parents=True)
    link = posters / "Live"
    os.symlink(shared / "Live", link)

    m = _module(tmp_path, [])
    m.config.gdrive_list = [SimpleNamespace(location=str(link))]
    removed, kept = m._prune_orphan_drive_folders()

    assert removed == [], f"escaped the sync tree: {removed}"
    assert precious.exists()


def test_symlinked_location_does_not_disarm_a_real_sibling_root(tmp_path):
    # The skip must not blind the sweep to genuine orphans under a real drive.
    _mkdrive(tmp_path, "posters/MM2K/Real", files=1)
    orphan = _mkdrive(tmp_path, "posters/MM2K/Gone")
    outside = _mkdrive(tmp_path, "elsewhere/Target", files=1)
    link = tmp_path / "posters/MM2K/Linked"
    os.symlink(outside, link)

    m = _module(tmp_path, ["posters/MM2K/Real"])
    m.config.gdrive_list.append(SimpleNamespace(location=str(link)))
    removed, _ = m._prune_orphan_drive_folders()
    assert removed == [str(orphan)]
    assert outside.exists()

