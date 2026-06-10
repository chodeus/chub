"""Tests for backend/util/cl2k/naming.py — ID-tagged CL2K poster filenames."""

from backend.util.cl2k.naming import build_poster_filename


def test_season_zero_is_written_as_specials():
    """Season 0 must use the `- Specials` form, not `- Season 00`."""
    name = build_poster_filename(
        kind="season",
        title="Breaking Bad",
        year=2008,
        tvdb_id=81189,
        season_number=0,
    )
    assert name == "Breaking Bad (2008) {tvdb-81189} - Specials.jpg"


def test_numbered_season_is_zero_padded():
    name = build_poster_filename(
        kind="season",
        title="Breaking Bad",
        year=2008,
        tvdb_id=81189,
        season_number=1,
    )
    assert name == "Breaking Bad (2008) {tvdb-81189} - Season 01.jpg"


def test_year_based_season_passes_number_through():
    """Year-based shows (F1) feed the year as the season number."""
    name = build_poster_filename(
        kind="season",
        title="Formula 1 Drive to Survive",
        year=2019,
        tmdb_id=98765,
        season_number=2026,
    )
    assert name == "Formula 1 Drive to Survive (2019) {tmdb-98765} - Season 2026.jpg"


def test_movie_has_no_season_suffix():
    name = build_poster_filename(
        kind="movie",
        title="The Matrix",
        year=1999,
        tmdb_id=603,
        imdb_id="tt0133093",
    )
    assert name == "The Matrix (1999) {tmdb-603} {imdb-tt0133093}.jpg"
