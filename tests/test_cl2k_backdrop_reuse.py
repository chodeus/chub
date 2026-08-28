"""Tests for cl2k_generated.get_backdrop_for — season backdrop reuse.

A new season inherits the show's existing backdrop (DAPS: same background across
seasons, only the season number changes). The lookup is by tmdb_id, and TMDB ids
are unique only WITHIN a media type — movie 2122 and tv 2122 are different
entities — so it must be scoped to the series kinds or a same-numbered movie's
backdrop can land on a season card.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.util.database import ChubDB  # noqa: E402
from backend.util.database.cl2k_generated import cl2k_generated_for  # noqa: E402


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
    d = ChubDB(logger=StubLogger(), db_path=path, quiet=True)
    d.__enter__()
    d._ensure_schema_initialized()
    yield d
    try:
        d.__exit__(None, None, None)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def _record(db, *, kind, tmdb_id, file, backdrop_path, season_number=None):
    cl2k_generated_for(db).record(
        {
            "kind": kind,
            "tmdb_id": tmdb_id,
            "tvdb_id": None,
            "imdb_id": None,
            "season_number": season_number,
            "title": f"{kind}-{tmdb_id}",
            "year": 2020,
            "file": file,
            "backdrop_path": backdrop_path,
            "logo_source": None,
            "uploaded": 0,
        }
    )


def test_season_reuses_the_shows_backdrop(db):
    _record(db, kind="show", tmdb_id=2122, file="/out/show.jpg", backdrop_path="/show.jpg")
    assert cl2k_generated_for(db).get_backdrop_for(2122) == "/show.jpg"


def test_a_same_numbered_movie_backdrop_is_not_reused(db):
    """movie 2122 ("The Whole Ten Yards") and tv 2122 ("King of the Hill") share a
    number but not an identity. The movie is recorded LAST, so an unscoped
    most-recent lookup would return it."""
    _record(db, kind="show", tmdb_id=2122, file="/out/show.jpg", backdrop_path="/show.jpg")
    _record(db, kind="movie", tmdb_id=2122, file="/out/movie.jpg", backdrop_path="/movie.jpg")
    assert cl2k_generated_for(db).get_backdrop_for(2122) == "/show.jpg"


def test_no_series_row_returns_none_rather_than_a_movie(db):
    """With only a movie at that number there is nothing legitimate to reuse."""
    _record(db, kind="movie", tmdb_id=2122, file="/out/movie.jpg", backdrop_path="/movie.jpg")
    assert cl2k_generated_for(db).get_backdrop_for(2122) is None


def test_an_earlier_season_backdrop_is_reusable(db):
    _record(
        db,
        kind="season",
        tmdb_id=2122,
        season_number=1,
        file="/out/s1.jpg",
        backdrop_path="/s1.jpg",
    )
    assert cl2k_generated_for(db).get_backdrop_for(2122) == "/s1.jpg"


def test_rows_without_a_backdrop_are_skipped(db):
    _record(db, kind="show", tmdb_id=2122, file="/out/show.jpg", backdrop_path="/show.jpg")
    _record(db, kind="season", tmdb_id=2122, season_number=2, file="/out/s2.jpg", backdrop_path=None)
    assert cl2k_generated_for(db).get_backdrop_for(2122) == "/show.jpg"


def test_missing_tmdb_id_returns_none(db):
    assert cl2k_generated_for(db).get_backdrop_for(None) is None
    assert cl2k_generated_for(db).get_backdrop_for(0) is None
