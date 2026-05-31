"""Tests for backend/util/plex_metadata.py — variant classification & DB helpers."""

import sqlite3

import pytest

from backend.util.plex_metadata import (
    PLEX_DB_NAME,
    _classify_variant_kind,
    _plex_is_running,
    copy_plex_db,
    get_in_use_hashes,
    get_plex_metadata_dir,
    invalidate_cache,
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


# --- _plex_is_running ---


def test_plex_is_running_false_when_no_lockfiles(tmp_path):
    """Without -shm/-wal lockfiles, Plex isn't running."""
    assert _plex_is_running(str(tmp_path)) is False


def test_plex_is_running_true_with_wal(tmp_path):
    db_dir = tmp_path / "Plug-in Support" / "Databases"
    db_dir.mkdir(parents=True)
    (db_dir / f"{PLEX_DB_NAME}-wal").write_bytes(b"")
    assert _plex_is_running(str(tmp_path)) is True


def test_plex_is_running_true_with_shm(tmp_path):
    db_dir = tmp_path / "Plug-in Support" / "Databases"
    db_dir.mkdir(parents=True)
    (db_dir / f"{PLEX_DB_NAME}-shm").write_bytes(b"")
    assert _plex_is_running(str(tmp_path)) is True


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
