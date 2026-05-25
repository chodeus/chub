"""Tests for MediaCache.find_duplicates and find_folder_collisions.

These cover the two-tier model:
  * find_duplicates: identity-based (same external ID within an instance)
  * find_folder_collisions: title-based with conflicting external IDs
    (e.g. ``Destination X (US)`` vs ``Destination X (UK)``)
"""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util.database import ChubDB  # noqa: E402


class StubLogger:
    def debug(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def get_adapter(self, *_a, **_kw):
        return self


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = ChubDB(logger=StubLogger(), db_path=path, quiet=True)
    db.__enter__()
    db._ensure_schema_initialized()
    try:
        yield db
    finally:
        db.__exit__(None, None, None)
        try:
            os.unlink(path)
        except OSError:
            pass  # best-effort cleanup; temp file may already be gone


def _insert(db, *, identity_key, title, normalized_title, year, instance_name,
            tvdb_id=None, tmdb_id=None, imdb_id=None, musicbrainz_id=None,
            folder=None, asset_type="show", season_number=None):
    db.media.execute_query(
        """
        INSERT INTO media_cache (
            identity_key, asset_type, title, normalized_title, year,
            tvdb_id, tmdb_id, imdb_id, musicbrainz_id, folder,
            instance_name, season_number
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            identity_key,
            asset_type,
            title,
            normalized_title,
            str(year) if year is not None else None,
            tvdb_id,
            tmdb_id,
            imdb_id,
            musicbrainz_id,
            folder,
            instance_name,
            season_number,
        ),
    )


def test_different_tvdb_ids_with_same_normalized_title_are_not_duplicates(db):
    """The regression case: Destination X (US) and Destination X (UK)
    normalize to the same title but are different shows. They must NOT
    appear in find_duplicates."""
    _insert(
        db,
        identity_key="sonarr|show|tvdb:449931",
        title="Destination X (US)",
        normalized_title="destinationx",
        year=2025,
        tvdb_id=449931,
        folder="/data/media/tv/Destination X (US) (2025) {tvdb-449931}",
        instance_name="sonarr",
    )
    _insert(
        db,
        identity_key="sonarr|show|tvdb:465530",
        title="Destination X (UK)",
        normalized_title="destinationx",
        year=2025,
        tvdb_id=465530,
        folder="/data/media/tv/Destination X (UK) (2025) {tvdb-465530}",
        instance_name="sonarr",
    )

    assert db.media.find_duplicates() == []


def test_different_tvdb_ids_with_same_normalized_title_are_folder_collisions(db):
    """The same case must surface in folder_collisions, with both
    identities exposed so the user can tell them apart."""
    _insert(
        db,
        identity_key="sonarr|show|tvdb:449931",
        title="Destination X (US)",
        normalized_title="destinationx",
        year=2025,
        tvdb_id=449931,
        folder="/data/media/tv/Destination X (US) (2025) {tvdb-449931}",
        instance_name="sonarr",
    )
    _insert(
        db,
        identity_key="sonarr|show|tvdb:465530",
        title="Destination X (UK)",
        normalized_title="destinationx",
        year=2025,
        tvdb_id=465530,
        folder="/data/media/tv/Destination X (UK) (2025) {tvdb-465530}",
        instance_name="sonarr",
    )

    collisions = db.media.find_folder_collisions()
    assert len(collisions) == 1
    c = collisions[0]
    assert c["normalized_title"] == "destinationx"
    assert c["count"] == 2
    identities = set(c["identities"].split(","))
    assert identities == {"tvdb:449931", "tvdb:465530"}
    titles = json.loads(c["titles"])
    assert "Destination X (US)" in titles
    assert "Destination X (UK)" in titles


def test_same_tvdb_id_within_instance_is_a_duplicate(db):
    """Two rows sharing an external ID within the same instance are a
    real duplicate worth resolving."""
    _insert(
        db,
        identity_key="sonarr|show|tvdb:12345",
        title="Some Show",
        normalized_title="someshow",
        year=2020,
        tvdb_id=12345,
        folder="/data/media/tv/Some Show A",
        instance_name="sonarr",
    )
    _insert(
        db,
        identity_key="sonarr|show|tvdb:12345|alt",
        title="Some Show",
        normalized_title="someshow",
        year=2020,
        tvdb_id=12345,
        folder="/data/media/tv/Some Show B",
        instance_name="sonarr",
    )

    dups = db.media.find_duplicates()
    assert len(dups) == 1
    d = dups[0]
    assert d["count"] == 2
    assert d["instance_name"] == "sonarr"
    assert d["identity"] == "tvdb:12345"


def test_same_tvdb_id_across_different_instances_is_not_a_duplicate(db):
    """Cross-instance overlap (e.g. Radarr + Radarr4K) is intentional
    quality coverage, not a duplicate."""
    _insert(
        db,
        identity_key="radarr|movie|tmdb:42",
        title="The Matrix",
        normalized_title="thematrix",
        year=1999,
        tmdb_id=42,
        instance_name="radarr",
        asset_type="movie",
    )
    _insert(
        db,
        identity_key="radarr4k|movie|tmdb:42",
        title="The Matrix",
        normalized_title="thematrix",
        year=1999,
        tmdb_id=42,
        instance_name="radarr4k",
        asset_type="movie",
    )

    assert db.media.find_duplicates() == []


def test_rows_with_no_external_ids_are_skipped_by_find_duplicates(db):
    """Rows without any external ID can't be matched safely — the
    detector skips them rather than guessing from titles."""
    _insert(
        db,
        identity_key="sonarr|show|title:mystery|y:2020",
        title="Mystery",
        normalized_title="mystery",
        year=2020,
        instance_name="sonarr",
    )
    _insert(
        db,
        identity_key="sonarr|show|title:mystery|y:2020|alt",
        title="Mystery",
        normalized_title="mystery",
        year=2020,
        instance_name="sonarr",
    )

    assert db.media.find_duplicates() == []


def test_season_rows_excluded_from_both_detectors(db):
    """A multi-season show fans out to one row per season. Those
    season rows must not be reported as duplicates of each other."""
    _insert(
        db,
        identity_key="sonarr|show|tvdb:99|s:1",
        title="Show",
        normalized_title="show",
        year=2020,
        tvdb_id=99,
        instance_name="sonarr",
        season_number=1,
    )
    _insert(
        db,
        identity_key="sonarr|show|tvdb:99|s:2",
        title="Show",
        normalized_title="show",
        year=2020,
        tvdb_id=99,
        instance_name="sonarr",
        season_number=2,
    )

    assert db.media.find_duplicates() == []
    assert db.media.find_folder_collisions() == []


def test_artists_with_distinct_mbids_are_not_folder_collisions(db):
    """Two Lidarr artists sharing a normalized name but with distinct
    MusicBrainz IDs are unambiguously different artists (e.g. REZZ the
    EDM producer vs REZZ the pop artist). They must NOT surface as
    folder collisions."""
    _insert(
        db,
        identity_key="lidarr|artist|mb:aaaa-1111",
        title="REZZ",
        normalized_title="rezz",
        year=None,
        musicbrainz_id="aaaa-1111",
        folder="/data/media/music/REZZ",
        instance_name="lidarr",
        asset_type="artist",
    )
    _insert(
        db,
        identity_key="lidarr|artist|mb:bbbb-2222",
        title="REZZ (pop)",
        normalized_title="rezz",
        year=None,
        musicbrainz_id="bbbb-2222",
        folder="/data/media/music/REZZ (pop)",
        instance_name="lidarr",
        asset_type="artist",
    )

    assert db.media.find_folder_collisions() == []


def test_artists_sharing_an_mbid_surface_as_duplicates_not_collisions(db):
    """Two artist rows sharing the same MBID within an instance are a
    genuine duplicate — owned by find_duplicates(), not surfaced as a
    folder collision."""
    _insert(
        db,
        identity_key="lidarr|artist|mb:cccc-3333",
        title="Safia",
        normalized_title="safia",
        year=None,
        musicbrainz_id="cccc-3333",
        folder="/data/media/music/Safia",
        instance_name="lidarr",
        asset_type="artist",
    )
    _insert(
        db,
        identity_key="lidarr|artist|mb:cccc-3333|alt",
        title="SAFIA",
        normalized_title="safia",
        year=None,
        musicbrainz_id="cccc-3333",
        folder="/data/media/music/SAFIA",
        instance_name="lidarr",
        asset_type="artist",
    )

    assert db.media.find_folder_collisions() == []

    dups = db.media.find_duplicates()
    assert len(dups) == 1
    assert dups[0]["identity"] == "mb:cccc-3333"
    assert dups[0]["count"] == 2


def test_artists_with_one_missing_mbid_still_collide(db):
    """If one of two artist rows is missing an MBID, we don't have
    enough info to suppress — fall back to surfacing the collision so
    the user can investigate."""
    _insert(
        db,
        identity_key="lidarr|artist|mb:dddd-4444",
        title="Icarus",
        normalized_title="icarus",
        year=None,
        musicbrainz_id="dddd-4444",
        folder="/data/media/music/Icarus",
        instance_name="lidarr",
        asset_type="artist",
    )
    _insert(
        db,
        identity_key="lidarr|artist|title:icarus|alt",
        title="Icarus (garage duo)",
        normalized_title="icarus",
        year=None,
        folder="/data/media/music/Icarus (garage duo)",
        instance_name="lidarr",
        asset_type="artist",
    )

    collisions = db.media.find_folder_collisions()
    assert len(collisions) == 1
    assert collisions[0]["normalized_title"] == "icarus"
