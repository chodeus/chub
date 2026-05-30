"""Golden end-to-end matching tests.

Each case drops a real poster filename on disk, runs the ACTUAL parsing
(_get_assets_files -> poster_cache) and the ACTUAL matcher (match_item) against
a constructed *arr media row, and asserts match / no-match. This exercises the
whole chain — parse, normalize, classify, candidate lookup, is_match — as one
unit, which is where the season-regex and article-prefix bugs slipped through
unit tests.

To add a regression: append a (files, media, expect_match) row to CASES.
"""

import os

import pytest

from backend.modules.poster_renamerr import PosterRenamerr
from backend.util.database import ChubDB
from backend.util.normalization import normalize_titles
from tests.conftest import StubLogger


def _make_module():
    m = object.__new__(PosterRenamerr)
    m.logger = StubLogger()
    m._cancel_event = None
    return m


def _open_db(tmp_path):
    db = ChubDB(logger=StubLogger(), db_path=str(tmp_path / "golden.db"), quiet=True)
    db.__enter__()
    db._ensure_schema_initialized()
    return db


def _drop(root, files):
    for name in files:
        full = os.path.join(root, name)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(b"x")


_fake_id = [100000]


def media(
    asset_type,
    title,
    year=None,
    season=None,
    tmdb=None,
    tvdb=None,
    imdb=None,
    akas=None,
):
    """Build an *arr media row the way connector/normalization would."""
    _fake_id[0] += 1
    import json

    return {
        "id": _fake_id[0],
        "asset_type": asset_type,
        "title": title,
        "normalized_title": normalize_titles(title),
        "year": year,
        "season_number": season,
        "tmdb_id": tmdb,
        "tvdb_id": tvdb,
        "imdb_id": imdb,
        "instance_name": "radarr" if asset_type == "movie" else "sonarr",
        "library_name": "Library",
        "alternate_titles": json.dumps(akas or []),
        "normalized_alternate_titles": json.dumps(
            [normalize_titles(a) for a in (akas or [])]
        ),
    }


# (poster filenames, media row, expected_match)
CASES = [
    # --- id matches ---
    (
        ["Open Season 2 (2008) {tmdb-13690} {imdb-tt1107365}.jpg"],
        media("movie", "Open Season 2", 2008, tmdb=13690, imdb="tt1107365"),
        True,
    ),
    (
        ["Open Season 3 (2010) {tmdb-51170}.jpg"],
        media("movie", "Open Season 3", 2010, tmdb=51170),
        True,
    ),
    # --- no-id, article-prefixed show season (the The Lovers bug) ---
    (
        ["The Lovers (2023) - Season 1.jpg"],
        media("show", "The Lovers", 2023, season=1, tvdb=421837),
        True,
    ),
    # --- no-id season, year present, no article ---
    (
        ["Amazing Stories (1985) - Season 1.jpg"],
        media("show", "Amazing Stories", 1985, season=1, tvdb=1),
        True,
    ),
    # --- Specials -> season 0 ---
    (
        ["An Idiot Abroad (2010) - Specials.jpg"],
        media("show", "An Idiot Abroad", 2010, season=0, tvdb=2),
        True,
    ),
    # --- article-prefixed movie, by id ---
    (
        ["A Few Good Men (1992) {tmdb-881}.jpg"],
        media("movie", "A Few Good Men", 1992, tmdb=881),
        True,
    ),
    # --- singular "Special" in a movie title is NOT a season ---
    (
        ["X-Men First Class 35mm Special (2012) {tmdb-691677}.jpg"],
        media("movie", "X-Men First Class 35mm Special", 2012, tmdb=691677),
        True,
    ),
    # --- collection (no year on either side) ---
    (
        ["Marvel Cinematic Universe Collection.jpg"],
        media("collection", "Marvel Cinematic Universe Collection"),
        True,
    ),
    # --- AKA / alternate title match ---
    (
        ["Origen (2010).jpg"],
        media("movie", "Inception", 2010, akas=["Origen"]),
        True,
    ),
    # --- wrong year must NOT match ---
    (
        ["The Lovers (2017).jpg"],
        media("movie", "The Lovers", 2023, tmdb=999),
        False,
    ),
    # --- different title must NOT match ---
    (
        ["Completely Different (2020).jpg"],
        media("movie", "The Lovers", 2020),
        False,
    ),
]


@pytest.mark.parametrize("files,media_row,expect", CASES)
def test_match_golden(tmp_path, files, media_row, expect):
    m = _make_module()
    db = _open_db(tmp_path)
    try:
        src = str(tmp_path / "posters")
        _drop(src, files)
        for rec in m._get_assets_files(src):
            db.poster.upsert(rec)
        result = m.match_item(
            dict(media_row), db, is_collection=media_row["asset_type"] == "collection"
        )
        assert result["matched"] is expect, (
            f"{files[0]!r} vs {media_row['title']!r} "
            f"({media_row.get('year')}, season={media_row.get('season_number')}) "
            f"expected matched={expect}, got {result['matched']}; reasons={result.get('reasons')}"
        )
    finally:
        db.__exit__(None, None, None)
