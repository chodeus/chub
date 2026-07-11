"""Tests for backend/util/plex_metadata.py — variant classification & DB helpers."""

import os
import sqlite3

import pytest

from backend.util.plex_metadata import (
    PLEX_DB_NAME,
    _classify_variant_kind,
    build_bundle_section_map,
    copy_plex_db,
    get_in_use_hashes,
    get_plex_metadata_dir,
    invalidate_cache,
    scan_bundles,
)


# --- _classify_variant_kind ---


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/data/.../Uploads/posters/abc.jpg", "poster"),
        ("/data/.../Contents/Posters/x.jpg", "poster"),
        ("/data/.../Uploads/art/x.jpg", "art"),
        ("/data/.../Uploads/banners/x.jpg", "banner"),
        ("/data/banner/x.jpg", "banner"),
        ("/data/Thumbnails/x.jpg", "thumb"),
        ("/data/Thumbs/x.jpg", "thumb"),
        ("/data/ChapterImages/x.jpg", "chapter"),
        ("/data/themes/x.mp3", "theme"),
        ("/data/random/x.jpg", "other"),
    ],
)
def test_classify_variant_kind(path, expected):
    assert _classify_variant_kind(path) == expected


def test_classify_variant_kind_case_insensitive():
    assert _classify_variant_kind("/PATH/Uploads/POSTERS/x.jpg") == "poster"


# --- get_plex_metadata_dir ---


def test_get_plex_metadata_dir_joins():
    assert get_plex_metadata_dir("/plex") == "/plex/Metadata"


# --- copy_plex_db ---


def test_copy_plex_db_returns_none_when_missing(tmp_path):
    """Missing source DB returns None instead of raising."""
    assert copy_plex_db(str(tmp_path / "nope"), str(tmp_path / "dest.db")) is None


def test_copy_plex_db_succeeds(tmp_path):
    src_dir = tmp_path / "Plug-in Support" / "Databases"
    src_dir.mkdir(parents=True)
    src = src_dir / PLEX_DB_NAME
    src.write_bytes(b"sqlite-stub")
    dest = tmp_path / "out" / "copy.db"

    result = copy_plex_db(str(tmp_path), str(dest))
    assert result == str(dest)
    assert dest.exists()


# --- get_in_use_hashes ---


def _make_plex_db(path):
    """Create a stub Plex DB with metadata_items table and a few rows."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE metadata_items (id INTEGER PRIMARY KEY, "
        "user_thumb_url TEXT, user_art_url TEXT, user_banner_url TEXT)"
    )
    conn.executemany(
        "INSERT INTO metadata_items (user_thumb_url, user_art_url, user_banner_url) "
        "VALUES (?, ?, ?)",
        [
            ("upload://posters/abc123", None, None),
            (None, "metadata://art/zzz999", None),
            (
                "http://external.example/x.jpg",
                None,
                None,
            ),  # not upload:// or metadata://
            (None, None, "upload://banners/banner1"),
        ],
    )
    conn.commit()
    conn.close()


def test_get_in_use_hashes_extracts_filenames(tmp_path):
    db = tmp_path / "lib.db"
    _make_plex_db(str(db))
    hashes = get_in_use_hashes(str(db))
    assert "abc123" in hashes
    assert "zzz999" in hashes
    assert "banner1" in hashes
    # External URLs are filtered by the LIKE clause
    assert "x.jpg" not in hashes


def test_get_in_use_hashes_handles_missing_db():
    assert get_in_use_hashes("/no/such/db") == set()


# --- invalidate_cache ---


def test_invalidate_cache_does_not_raise():
    # No-op assertion; just verify it doesn't crash on empty cache
    invalidate_cache()
    invalidate_cache()


def test_get_in_use_hashes_includes_clear_logo_and_square_art(tmp_path):
    """Regression: the in-use scan must protect clear logos + square art (the
    'new experience' columns) so the bloat cleaner can't delete custom ones."""
    from backend.util.plex_metadata import IN_USE_IMAGE_COLUMNS

    assert "user_clear_logo_url" in IN_USE_IMAGE_COLUMNS
    assert "user_square_art_url" in IN_USE_IMAGE_COLUMNS

    db = tmp_path / "lib5.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE metadata_items (id INTEGER PRIMARY KEY, "
        "user_thumb_url TEXT, user_art_url TEXT, user_banner_url TEXT, "
        "user_clear_logo_url TEXT, user_square_art_url TEXT)"
    )
    conn.execute(
        "INSERT INTO metadata_items (user_clear_logo_url, user_square_art_url) "
        "VALUES ('upload://logos/logo1', 'upload://squareart/sq1')"
    )
    conn.commit()
    conn.close()

    hashes = get_in_use_hashes(str(db))
    assert "logo1" in hashes
    assert "sq1" in hashes


# --- library scoping: in-use set is GLOBAL, opt-out only labels candidates ---


def _make_indexed_db(path, rows, sections):
    """metadata_items keyed by an in-use user_thumb_url anchor + library_sections.

    rows: list of (id, title, year, metadata_type, library_section_id, thumb_url)
    sections: list of (id, name, section_type)
    """
    os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE metadata_items (id INTEGER PRIMARY KEY, title TEXT, "
        "year INTEGER, metadata_type INTEGER, library_section_id INTEGER, "
        "user_thumb_url TEXT)"
    )
    conn.executemany(
        "INSERT INTO metadata_items "
        "(id, title, year, metadata_type, library_section_id, user_thumb_url) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute(
        "CREATE TABLE library_sections (id INTEGER PRIMARY KEY, name TEXT, section_type INTEGER)"
    )
    conn.executemany(
        "INSERT INTO library_sections (id, name, section_type) VALUES (?, ?, ?)",
        sections,
    )
    conn.commit()
    conn.close()


def _touch(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_get_in_use_hashes_is_global_across_libraries(tmp_path):
    """The in-use set must span EVERY library — no library_section_id predicate.

    A library opt-out that narrowed this would drop excluded libraries' live
    artwork from the protected set and delete it. This pins it global."""
    db = tmp_path / "multi.db"
    _make_indexed_db(
        db,
        rows=[
            (1, "Film A", 1999, 1, 1, "upload://posters/films_hash"),
            (2, "Album B", 2001, 9, 2, "upload://posters/music_hash"),
        ],
        sections=[(1, "Films", 1), (2, "Music", 8)],
    )
    hashes = get_in_use_hashes(str(db))
    # Both libraries' in-use images are protected regardless of library.
    assert hashes == {"films_hash", "music_hash"}


def test_build_bundle_section_map_labels_bundles_by_library(tmp_path):
    """Each .bundle resolves to its owning library NAME via an anchored file."""
    db = tmp_path / "map.db"
    _make_indexed_db(
        db,
        rows=[
            (1, "Film A", 1999, 1, 1, "upload://posters/films_anchor"),
            (2, "Album B", 2001, 9, 2, "upload://posters/music_anchor"),
        ],
        sections=[(1, "Films", 1), (2, "Music", 8)],
    )
    md = tmp_path / "Metadata"
    films_bundle = md / "Movies" / "a" / "film.bundle"
    music_bundle = md / "Albums" / "b" / "album.bundle"
    # anchor file (matches the DB thumb) + a bloat file in each bundle
    _touch(films_bundle / "Uploads" / "posters" / "films_anchor")
    _touch(films_bundle / "Uploads" / "posters" / "films_bloat")
    _touch(music_bundle / "Uploads" / "posters" / "music_anchor")
    _touch(music_bundle / "Uploads" / "posters" / "music_bloat")

    section_map = build_bundle_section_map(str(db), str(md))

    assert section_map.get(os.path.realpath(str(films_bundle))) == "Films"
    assert section_map.get(os.path.realpath(str(music_bundle))) == "Music"


def test_build_bundle_section_map_skips_unanchored(tmp_path):
    """A bundle with no anchored (in-use) file is absent from the map — the
    caller then treats it as library-unknown and fails OPEN (not excluded)."""
    db = tmp_path / "map2.db"
    _make_indexed_db(
        db,
        rows=[(1, "Film A", 1999, 1, 1, "upload://posters/films_anchor")],
        sections=[(1, "Films", 1)],
    )
    md = tmp_path / "Metadata"
    orphan_bundle = md / "Albums" / "z" / "orphan.bundle"
    _touch(orphan_bundle / "Uploads" / "posters" / "no_anchor_here")

    section_map = build_bundle_section_map(str(db), str(md))

    assert os.path.realpath(str(orphan_bundle)) not in section_map


def test_scan_bundles_hides_unanchored_contents_clutter_keeps_upload_bloat(
    tmp_path, monkeypatch
):
    """Issue 1: unanchored Contents-only bundles (Music '(unknown)' clutter) are
    dropped, but an unanchored bundle that still holds a deletable upload is
    kept, and anchored titled bundles are unaffected."""
    plex = tmp_path / "plex"
    db_src = plex / "Plug-in Support" / "Databases" / PLEX_DB_NAME
    _make_indexed_db(
        db_src,
        rows=[(1, "The Matrix", 1999, 1, 1, "upload://posters/matrix_thumb")],
        sections=[(1, "Films", 1)],
    )
    md = plex / "Metadata"
    # (a) anchored movie: active thumb + an upload bloat variant → kept, titled
    movie = md / "Movies" / "a" / "matrix.bundle"
    _touch(movie / "Uploads" / "posters" / "matrix_thumb")
    _touch(movie / "Uploads" / "posters" / "matrix_old")
    # (b) unanchored Contents-only music default → "(unknown)" clutter → dropped
    clutter = md / "Albums" / "b" / "music.bundle"
    _touch(clutter / "Contents" / "_combined" / "Posters" / "default.jpg")
    # (c) unanchored but with a deletable upload → real orphan bloat → kept
    orphan = md / "Movies" / "c" / "ghost.bundle"
    _touch(orphan / "Uploads" / "posters" / "ghost_bloat")

    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    invalidate_cache()
    scan = scan_bundles(str(plex), force=True)
    bundles = scan["bundles"]

    titles = {b["title"] for b in bundles}
    assert "The Matrix" in titles
    # The Contents-only music clutter bundle is gone entirely.
    paths = {b["bundle_path"] for b in bundles}
    assert not any(p.endswith("music.bundle") for p in paths)
    # The unanchored-but-has-upload bundle survives (rating_key None, kept).
    ghost = [b for b in bundles if b["bundle_path"].endswith("ghost.bundle")]
    assert len(ghost) == 1
    assert ghost[0]["rating_key"] is None
    assert any("ghost_bloat" in v["filename"] for v in ghost[0]["variants"])


def test_library_optout_decision_excludes_only_matching_library(tmp_path):
    """The poster_cleanarr deletion-side opt-out decision (using the real
    helpers) excludes a bloat file whose bundle is in an opted-out library,
    keeps one in an included library, and fails OPEN on an unresolved bundle."""
    from backend.modules.poster_cleanarr import _bundle_root, _normalize_lib

    db = tmp_path / "optout.db"
    _make_indexed_db(
        db,
        rows=[
            (1, "Film A", 1999, 1, 1, "upload://posters/films_anchor"),
            (2, "Album B", 2001, 9, 2, "upload://posters/music_anchor"),
        ],
        sections=[(1, "Films", 1), (2, "Music", 8)],
    )
    md = tmp_path / "Metadata"
    films_bundle = md / "Movies" / "a" / "film.bundle"
    music_bundle = md / "Albums" / "b" / "album.bundle"
    orphan_bundle = md / "Movies" / "c" / "ghost.bundle"  # no anchor -> unresolved
    _touch(films_bundle / "Uploads" / "posters" / "films_anchor")
    films_bloat = films_bundle / "Uploads" / "posters" / "films_bloat"
    _touch(films_bloat)
    _touch(music_bundle / "Uploads" / "posters" / "music_anchor")
    music_bloat = music_bundle / "Uploads" / "posters" / "music_bloat"
    _touch(music_bloat)
    orphan_bloat = orphan_bundle / "Uploads" / "posters" / "orphan_bloat"
    _touch(orphan_bloat)

    section_map = build_bundle_section_map(str(db), str(md))
    excluded = {_normalize_lib("Music")}

    def is_excluded(path):
        root = _bundle_root(str(path))
        lib = section_map.get(root) if root else None
        return lib is not None and _normalize_lib(lib) in excluded

    assert is_excluded(music_bloat) is True  # opted-out library -> dropped
    assert is_excluded(films_bloat) is False  # included library -> kept
    assert is_excluded(orphan_bloat) is False  # unresolved bundle -> fail-open keep
