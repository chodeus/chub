"""Library-statistics semantics: 'missing' is monitored + no-file + RELEASED;
unreleased monitored items are 'upcoming', not missing; Lidarr album release
dates gate this; artist container rows are excluded from in_library / missing /
upcoming (their albums carry the signal) so the count matches Lidarr's
album-level wanted/missing.
"""

import os
import tempfile

import pytest

from backend.util.database import ChubDB
from backend.util.normalization import normalize_titles
from tests.conftest import StubLogger


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    d = ChubDB(logger=StubLogger(), db_path=path, quiet=True)
    d.__enter__()
    d._ensure_schema_initialized()
    try:
        yield d
    finally:
        d.__exit__(None, None, None)
        try:
            os.unlink(path)
        except OSError:
            pass


def _item(title, **over):
    base = dict(
        title=title,
        normalized_title=normalize_titles(title),
        year=2026,
        alternate_titles=[],
        normalized_alternate_titles=[],
        monitored=True,
        has_content=False,
    )
    base.update(over)
    return base


def _seed(db):
    # Albums (Lidarr) — release_date gates missing vs upcoming
    db.media.upsert(
        _item("Rel Missing", release_date="2020-01-01"), "album", "lidarr", "Lidarr"
    )
    db.media.upsert(
        _item("Rel InLib", release_date="2020-01-01", has_content=True),
        "album",
        "lidarr",
        "Lidarr",
    )
    db.media.upsert(
        _item("Future Album", release_date="2099-01-01"), "album", "lidarr", "Lidarr"
    )
    db.media.upsert(
        _item("No Date"), "album", "lidarr", "Lidarr"
    )  # NULL date -> released
    # Artist container rows — must be excluded from in_library/missing/upcoming
    db.media.upsert(_item("Artist NoMusic"), "artist", "lidarr", "Lidarr")
    db.media.upsert(
        _item("Artist WithMusic", has_content=True), "artist", "lidarr", "Lidarr"
    )
    # Movies (Radarr) — status gates release for non-albums
    db.media.upsert(
        _item("Movie Released", status="released"), "movie", "radarr", "radarr"
    )
    db.media.upsert(
        _item("Movie Announced", status="announced"), "movie", "radarr", "radarr"
    )


def test_missing_is_released_only_upcoming_split_artists_excluded(db):
    _seed(db)
    s = db.media.get_stats()

    # missing = Rel Missing + No Date (albums) + Movie Released
    assert s["missing"] == 3
    # upcoming = Future Album + Movie Announced
    assert s["upcoming"] == 2
    # in_library = Rel InLib only (artist-with-music excluded)
    assert s["in_library"] == 1


def test_by_type_breakdown(db):
    _seed(db)
    by_type = {r["asset_type"]: r for r in db.media.get_stats()["by_type"]}

    assert by_type["album"]["missing"] == 2  # Rel Missing + No Date
    assert by_type["album"]["upcoming"] == 1  # Future Album
    assert by_type["album"]["in_library"] == 1  # Rel InLib

    assert by_type["movie"]["missing"] == 1  # Movie Released
    assert by_type["movie"]["upcoming"] == 1  # Movie Announced

    # Artist rows count toward total/monitored but never content metrics.
    assert by_type["artist"]["total"] == 2
    assert by_type["artist"]["in_library"] == 0
    assert by_type["artist"]["missing"] == 0
    assert by_type["artist"]["upcoming"] == 0


def test_by_instance_lidarr_excludes_artists(db):
    _seed(db)
    detailed = db.media.get_detailed_stats()
    lidarr = next(r for r in detailed["by_instance"] if r["instance_name"] == "Lidarr")
    # Album-level only: Rel Missing + No Date missing; Future upcoming; Rel InLib in library.
    assert lidarr["missing"] == 2
    assert lidarr["upcoming"] == 1
    assert lidarr["in_library"] == 1
