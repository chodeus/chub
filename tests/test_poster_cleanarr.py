"""Tests for backend/modules/poster_cleanarr.py focused on the expanded Plex
in-use SQL columns (clear_logo / square_art) and the overlays_only EXIF
filter behavior."""

import io
import os
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.modules.poster_cleanarr import (
    KOMETA_OVERLAY_EXIF_TAG,
    KOMETA_OVERLAY_EXIF_VALUE,
    RESTORE_DIR_NAME,
    PosterCleanarr,
)


class StubLogger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def log_outro(self):
        pass

    def get_adapter(self, *a, **k):
        return self


def make_module(overlays_only=False):
    m = object.__new__(PosterCleanarr)
    m.logger = StubLogger()
    m._cancel_event = None
    m.config = SimpleNamespace(overlays_only=overlays_only)
    m.mode = "report"
    m.plex_path = ""
    m.working_dir = ""
    return m


# --- PR #115: _query_in_use_images covers the new "new experience" columns ---


def _make_plex_db(path, rows):
    """Create a minimal metadata_items table with the columns CHUB queries.
    `rows` is a list of dicts keyed by column name."""
    columns = [
        "user_thumb_url",
        "user_art_url",
        "user_banner_url",
        "user_clear_logo_url",
        "user_square_art_url",
    ]
    conn = sqlite3.connect(path)
    try:
        col_defs = ", ".join(f"{c} TEXT" for c in columns)
        conn.execute(f"CREATE TABLE metadata_items ({col_defs})")
        for row in rows:
            placeholders = ", ".join("?" for _ in columns)
            conn.execute(
                f"INSERT INTO metadata_items ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(row.get(c) for c in columns),
            )
        conn.commit()
    finally:
        conn.close()


def test_query_in_use_collects_clear_logo_and_square_art(tmp_path):
    db = tmp_path / "plex.db"
    _make_plex_db(
        str(db),
        [
            {"user_thumb_url": "upload://posters/aaa"},
            {"user_clear_logo_url": "upload://clearLogos/bbb"},
            {"user_square_art_url": "metadata://squareArt/ccc"},
            {"user_art_url": "upload://art/ddd"},
            {"user_banner_url": "upload://banners/eee"},
        ],
    )

    in_use = make_module()._query_in_use_images(str(db))

    assert in_use == {"aaa", "bbb", "ccc", "ddd", "eee"}


def test_query_in_use_tolerates_old_plex_missing_new_columns(tmp_path):
    """If the Plex DB is on an older version without the new columns, the
    query should still return the rows it can read (the per-column try/except
    inside _query_in_use_images swallows OperationalError)."""
    db = tmp_path / "plex.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE metadata_items (user_thumb_url TEXT, user_art_url TEXT, user_banner_url TEXT)"
        )
        conn.execute(
            "INSERT INTO metadata_items (user_thumb_url) VALUES (?)",
            ("upload://posters/legacy",),
        )
        conn.commit()
    finally:
        conn.close()

    in_use = make_module()._query_in_use_images(str(db))

    assert in_use == {"legacy"}


def test_scan_bloat_images_skips_uploaded_themes(tmp_path):
    """Uploaded theme audio is never bloat, the selected theme included."""
    bundle = tmp_path / "Metadata" / "TV Shows" / "a" / "show.bundle"
    for rel in ("posters/active", "posters/old", "themes/selected", "themes/n/other"):
        path = bundle / "Uploads" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    bloat = make_module()._scan_bloat_images(str(tmp_path / "Metadata"), {"active"})

    assert [b["name"] for b in bloat] == ["old"]


def test_run_reports_no_bloat_when_the_in_use_read_fails(tmp_path, monkeypatch):
    """A DB without user_art_url reads as 0 in-use, so report mode must not list live artwork."""
    plex = tmp_path / "plex"
    live = plex / "Metadata" / "Movies" / "a" / "x.bundle" / "Uploads" / "posters" / "live_thumb"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"x")
    db_dir = plex / "Plug-in Support" / "Databases"
    db_dir.mkdir(parents=True)
    con = sqlite3.connect(db_dir / "com.plexapp.plugins.library.db")
    con.execute("CREATE TABLE metadata_items (id INTEGER PRIMARY KEY, user_thumb_url TEXT)")
    con.execute("INSERT INTO metadata_items (user_thumb_url) VALUES ('upload://posters/live_thumb')")
    con.commit()
    con.close()

    errors = []
    m = make_module()
    m.logger.error = lambda msg, *a, **k: errors.append(msg)
    m.mode = "report"
    m.plex_path = str(plex)
    m.working_dir = str(tmp_path)
    m.config = SimpleNamespace(
        local_db=True, use_existing_db=False, ignore_running=False, overlays_only=False,
        target_paths=None, excluded_libraries=[],
    )
    executed = []
    monkeypatch.setattr(m, "_execute_mode", lambda *a, **k: executed.append(a) or {"count": 0})
    monkeypatch.setattr(m, "_run_asset_passes", lambda: ({}, {}))

    m.run()

    assert executed == []
    assert [e for e in errors if "0 in-use images" in e]
    assert not [e for e in errors if "An error occurred" in e]


HELD = os.path.join("Movies", "a", "x.bundle", "Uploads", "posters")


def _run_restore_dir_mode(tmp_path, monkeypatch, mode, errors=None):
    """Run ``mode`` on one held file, local_db on and no Plex database folder."""
    plex = tmp_path / "plex"
    held = plex / RESTORE_DIR_NAME / HELD / "p.jpg"
    held.parent.mkdir(parents=True, exist_ok=True)
    held.write_bytes(b"x")
    m = make_module()
    if errors is not None:
        m.logger.error = lambda msg, *a, **k: errors.append(msg)
    m.mode = mode
    m.plex_path = str(plex)
    m.working_dir = str(tmp_path)
    m.config = SimpleNamespace(
        local_db=True,
        use_existing_db=False,
        ignore_running=False,
        overlays_only=False,
        target_paths=None,
        excluded_libraries=[],
    )
    monkeypatch.setattr(m, "_run_asset_passes", lambda: ({}, {}))
    m.run()
    return plex


@pytest.mark.parametrize("mode, restored", [("restore", b"x"), ("clear", None)])
def test_restore_and_clear_run_without_a_plex_database_folder(
    tmp_path, monkeypatch, mode, restored
):
    """Neither mode reads the Plex database, so its folder may be missing."""
    plex = _run_restore_dir_mode(tmp_path, monkeypatch, mode)

    back = plex / "Metadata" / HELD / "p"
    assert (back.read_bytes() if back.exists() else None) == restored
    assert not (plex / RESTORE_DIR_NAME).exists()


def test_restore_leaves_files_behind_a_linked_folder_where_they_are(
    tmp_path, monkeypatch
):
    """A folder link inside the restore folder is not followed into."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "keep.jpg").write_bytes(b"k")
    linked = tmp_path / "plex" / RESTORE_DIR_NAME / "Movies" / "linked"
    linked.parent.mkdir(parents=True)
    linked.symlink_to(outside, target_is_directory=True)

    plex = _run_restore_dir_mode(tmp_path, monkeypatch, "restore")

    assert (outside / "keep.jpg").read_bytes() == b"k"
    assert not (plex / "Metadata" / "Movies" / "linked").exists()
    assert (plex / "Metadata" / HELD / "p").read_bytes() == b"x"


def test_restore_refuses_a_restore_folder_that_is_a_link(tmp_path, monkeypatch):
    """A linked restore folder is left alone, and so is what it points at."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (tmp_path / "plex").mkdir()
    (tmp_path / "plex" / RESTORE_DIR_NAME).symlink_to(outside, target_is_directory=True)
    errors = []

    # The held file lands in `outside`, written through the link.
    plex = _run_restore_dir_mode(tmp_path, monkeypatch, "restore", errors)

    assert (outside / HELD / "p.jpg").read_bytes() == b"x"
    assert not (plex / "Metadata" / HELD / "p").exists()
    assert (plex / RESTORE_DIR_NAME).is_symlink()
    assert [e for e in errors if "is a link" in e and "nothing restored" in e]


@pytest.mark.parametrize(
    "stray", ["._p.jpg", os.path.join(".AppleDouble", "p.jpg"), "Thumbs.db"]
)
def test_restore_moves_back_only_held_files(tmp_path, monkeypatch, stray):
    """Hidden names and non-.jpg files in the restore folder stay out of Metadata."""
    path = tmp_path / "plex" / RESTORE_DIR_NAME / HELD / stray
    path.parent.mkdir(parents=True)
    path.write_bytes(b"s")

    plex = _run_restore_dir_mode(tmp_path, monkeypatch, "restore")

    back = plex / "Metadata" / HELD
    assert sorted(p.name for p in back.rglob("*")) == ["p"]


@pytest.mark.parametrize("mode", ["restore", "clear"])
def test_restore_and_clear_leave_metadata_folders_alone(tmp_path, monkeypatch, mode):
    """Neither mode removes from Metadata, so neither sweeps its empty folders."""
    bundle = tmp_path / "plex" / "Metadata" / "Movies" / "b" / "y.bundle"
    empty = bundle / "Uploads" / "art"
    empty.mkdir(parents=True)

    _run_restore_dir_mode(tmp_path, monkeypatch, mode)

    assert empty.is_dir()


@pytest.mark.parametrize("mode", ["move", "remove"])
def test_move_and_remove_sweep_empty_metadata_folders(tmp_path, monkeypatch, mode):
    """The modes that remove from Metadata prune its empty folders afterwards."""
    plex = tmp_path / "plex"
    empty = plex / "Metadata" / "Movies" / "b" / "y.bundle" / "Uploads" / "art"
    empty.mkdir(parents=True)
    (plex / "Plug-in Support" / "Databases").mkdir(parents=True)
    m = make_module()
    m.mode = mode
    m.plex_path = str(plex)
    m.working_dir = str(tmp_path)
    m.config = SimpleNamespace(
        local_db=True,
        use_existing_db=False,
        ignore_running=False,
        overlays_only=False,
        target_paths=None,
        excluded_libraries=[],
    )
    monkeypatch.setattr(m, "_get_plex_database", lambda *a: None)
    monkeypatch.setattr(m, "_run_asset_passes", lambda: ({}, {}))

    m.run()

    assert not empty.exists()


# --- PR #90: _is_kometa_overlay + overlays_only mode in _execute_mode ---


def _write_image(path, exif_overlay):
    """Write a tiny JPEG to `path`, optionally tagged with the Kometa overlay
    EXIF marker. Plex stores its uploads extensionless, so no suffix is used
    on disk — Pillow detects format from magic bytes."""
    img = Image.new("RGB", (4, 4), color=(127, 127, 127))
    exif = img.getexif()
    if exif_overlay:
        exif[KOMETA_OVERLAY_EXIF_TAG] = KOMETA_OVERLAY_EXIF_VALUE
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    with open(path, "wb") as f:
        f.write(buf.getvalue())


def test_is_kometa_overlay_true_for_tagged(tmp_path):
    p = tmp_path / "kometa_overlay"
    _write_image(str(p), exif_overlay=True)
    assert PosterCleanarr._is_kometa_overlay(str(p)) is True


def test_is_kometa_overlay_false_for_custom_upload(tmp_path):
    p = tmp_path / "user_upload"
    _write_image(str(p), exif_overlay=False)
    assert PosterCleanarr._is_kometa_overlay(str(p)) is False


def test_is_kometa_overlay_false_for_unreadable_file(tmp_path):
    p = tmp_path / "garbage"
    p.write_bytes(b"not an image")
    # Conservative: unreadable means "not an overlay" → keep the file.
    assert PosterCleanarr._is_kometa_overlay(str(p)) is False


class _CapturingLogger(StubLogger):
    """StubLogger variant that records info() calls for assertion."""

    def __init__(self):
        self.info_lines = []

    def info(self, *a, **k):
        if a:
            self.info_lines.append(str(a[0]))


def test_execute_mode_remove_logs_per_file_at_info(tmp_path):
    """Destructive bloat removal must surface each file at INFO so users
    can audit what was deleted without flipping log_level: debug. Pins
    the [REMOVE] format and the per-pass summary line."""
    overlay_a = tmp_path / "alpha.png"
    overlay_b = tmp_path / "beta.png"
    _write_image(str(overlay_a), exif_overlay=False)
    _write_image(str(overlay_b), exif_overlay=False)
    bloat = [
        {"path": str(overlay_a), "size": os.path.getsize(overlay_a), "name": "alpha"},
        {"path": str(overlay_b), "size": os.path.getsize(overlay_b), "name": "beta"},
    ]
    module = make_module(overlays_only=False)
    module.logger = _CapturingLogger()
    result = module._execute_mode(
        bloat, mode="remove", metadata_dir=str(tmp_path), restore_dir=""
    )

    info = module.logger.info_lines
    # Each removed file logged at INFO with the [REMOVE] tag
    assert any("[REMOVE]" in line and "alpha.png" in line for line in info), info
    assert any("[REMOVE]" in line and "beta.png" in line for line in info), info
    # Final summary line
    assert any("bloat scan" in line and "2 remove" in line for line in info), info
    # Files actually gone (behaviour preserved)
    assert result["count"] == 2
    assert not overlay_a.exists()
    assert not overlay_b.exists()


def test_execute_mode_report_does_not_emit_destructive_log(tmp_path):
    """Report mode is non-destructive — the per-file action log must NOT
    fire, even though the summary may still appear."""
    f = tmp_path / "x.png"
    _write_image(str(f), exif_overlay=False)
    bloat = [{"path": str(f), "size": os.path.getsize(f), "name": "x"}]
    module = make_module(overlays_only=False)
    module.logger = _CapturingLogger()
    module._execute_mode(
        bloat, mode="report", metadata_dir=str(tmp_path), restore_dir=""
    )
    assert not any("[REMOVE]" in line for line in module.logger.info_lines)
    # File still exists
    assert f.exists()


def test_execute_mode_overlays_only_keeps_custom_uploads(tmp_path):
    overlay = tmp_path / "kometa_overlay"
    custom = tmp_path / "user_upload"
    _write_image(str(overlay), exif_overlay=True)
    _write_image(str(custom), exif_overlay=False)

    bloat = [
        {
            "path": str(overlay),
            "size": os.path.getsize(overlay),
            "name": "kometa_overlay",
        },
        {"path": str(custom), "size": os.path.getsize(custom), "name": "user_upload"},
    ]

    module = make_module(overlays_only=True)
    result = module._execute_mode(
        bloat, mode="remove", metadata_dir=str(tmp_path), restore_dir=""
    )

    # The custom upload survives; only the Kometa overlay was removed.
    assert os.path.exists(custom)
    assert not os.path.exists(overlay)
    assert result["count"] == 1
    assert result["ignored_non_overlay"] == 1


def test_execute_mode_overlays_off_removes_everything(tmp_path):
    """Sanity check: with overlays_only disabled, the prior behavior holds —
    every bloat file is actioned regardless of EXIF state."""
    overlay = tmp_path / "kometa_overlay"
    custom = tmp_path / "user_upload"
    _write_image(str(overlay), exif_overlay=True)
    _write_image(str(custom), exif_overlay=False)

    bloat = [
        {
            "path": str(overlay),
            "size": os.path.getsize(overlay),
            "name": "kometa_overlay",
        },
        {"path": str(custom), "size": os.path.getsize(custom), "name": "user_upload"},
    ]

    module = make_module(overlays_only=False)
    result = module._execute_mode(
        bloat, mode="remove", metadata_dir=str(tmp_path), restore_dir=""
    )

    assert not os.path.exists(overlay)
    assert not os.path.exists(custom)
    assert result["count"] == 2
    assert result.get("ignored_non_overlay", 0) == 0


def test_execute_mode_overlays_only_report_mode_counts_only_overlays(tmp_path):
    """In report mode, overlays_only should also suppress non-overlay files
    from the count — the filter applies to every mode, not just remove/move."""
    overlay = tmp_path / "kometa_overlay"
    custom = tmp_path / "user_upload"
    _write_image(str(overlay), exif_overlay=True)
    _write_image(str(custom), exif_overlay=False)

    bloat = [
        {
            "path": str(overlay),
            "size": os.path.getsize(overlay),
            "name": "kometa_overlay",
        },
        {"path": str(custom), "size": os.path.getsize(custom), "name": "user_upload"},
    ]

    module = make_module(overlays_only=True)
    result = module._execute_mode(
        bloat, mode="report", metadata_dir=str(tmp_path), restore_dir=""
    )

    # Nothing actually moved/removed in report mode, but the count reflects
    # what *would* be actioned.
    assert os.path.exists(overlay)
    assert os.path.exists(custom)
    assert result["count"] == 1
    assert result["ignored_non_overlay"] == 1


def test_orphan_scan_spares_kometa_asset_files(tmp_path):
    """asset_renamerr (kometa) writes logo.png / background.png; Kometa writes
    poster.jpg too. The orphan pass must NOT flag these as orphans when the media
    is in the library — matched via the parent folder or the suffix-stripped
    flat name."""
    m = make_module()
    assets = tmp_path / "assets"

    # asset_folders layout: <Title (Year)>/<asset>.ext
    folder = assets / "The Show (2020)"
    folder.mkdir(parents=True)
    for name in ("poster.jpg", "logo.png", "background.png"):
        (folder / name).write_bytes(b"x")

    # flat layout: <Title (Year)>_<asset>.ext
    (assets / "The Show (2020)_logo.png").write_bytes(b"x")

    # a genuine orphan: unrelated title, no folder context
    (assets / "Totally Unknown Thing (1999).jpg").write_bytes(b"x")

    titles = {"theshow"}  # normalized library title
    orphans = m._scan_orphan_assets([str(assets)], titles)
    orphan_names = {os.path.basename(o["path"]) for o in orphans}

    assert "poster.jpg" not in orphan_names
    assert "logo.png" not in orphan_names
    assert "background.png" not in orphan_names
    assert "The Show (2020)_logo.png" not in orphan_names
    # the genuinely-unmatched file is still flagged
    assert "Totally Unknown Thing (1999).jpg" in orphan_names
