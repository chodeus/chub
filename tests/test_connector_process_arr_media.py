"""Regression tests for Connector._process_arr_media — the per-season
monitored + has_content propagation that backs unmatched_assets'
should_include filter."""

import pytest

from backend.util.connector import Connector


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
def connector():
    """Build a Connector without going through the parsed_instances path —
    we only care about the pure transform method here."""
    c = object.__new__(Connector)
    c.logger = StubLogger()
    return c


# --- _process_arr_media: show + season fan-out ---


def test_movie_passthrough_unchanged(connector):
    """Movies are returned untouched — no season fan-out, no overrides."""
    movies = [
        {
            "title": "The Matrix",
            "year": 1999,
            "has_content": True,
            "monitored": True,
            "tmdb_id": 603,
        }
    ]
    result = connector._process_arr_media(movies, "movie")
    assert result == movies  # same list, untouched


def test_show_fans_out_to_show_plus_seasons(connector):
    """A show with 2 seasons yields 3 rows: show + S1 + S2."""
    shows = [
        {
            "title": "Heated Rivalry",
            "year": 2025,
            "tvdb_id": 464461,
            "monitored": True,
            "seasons": [
                {"season_number": 1, "monitored": True, "season_has_episodes": 6},
                {"season_number": 2, "monitored": True, "season_has_episodes": 0},
            ],
        }
    ]
    result = connector._process_arr_media(shows, "show")
    assert len(result) == 3
    # Row 0: show-level (no season_number)
    assert result[0]["season_number"] is None
    # Rows 1-2: per-season
    seasons = sorted(
        (r for r in result if r["season_number"] is not None),
        key=lambda r: r["season_number"],
    )
    assert [r["season_number"] for r in seasons] == [1, 2]


def test_per_season_has_content_overrides_show(connector):
    """Each season row's has_content reflects that season's own episode
    count, not the show-level rollup. Regression for the case where
    Heated Rivalry S2 (0 downloaded) was inheriting the show's
    has_content=True from S1's downloads."""
    shows = [
        {
            "title": "Heated Rivalry",
            "year": 2025,
            "has_content": True,  # show-level rollup
            "monitored": True,
            "seasons": [
                {"season_number": 1, "monitored": True, "season_has_episodes": 6},
                {"season_number": 2, "monitored": True, "season_has_episodes": 0},
            ],
        }
    ]
    result = connector._process_arr_media(shows, "show")
    s1 = next(r for r in result if r["season_number"] == 1)
    s2 = next(r for r in result if r["season_number"] == 2)
    assert s1["has_content"] is True
    assert s2["has_content"] is False, "S2 has 0 episodes, has_content must be False"


def test_per_season_monitored_overrides_show(connector):
    """Each season row's monitored reflects that season's own monitored
    flag, not the show-level one. Regression for the case where Super
    Dragon Ball Heroes Specials (S0, unmonitored) inherited the show's
    monitored=True."""
    shows = [
        {
            "title": "Super Dragon Ball Heroes",
            "year": 2018,
            "monitored": True,  # show-level
            "seasons": [
                {"season_number": 0, "monitored": False, "season_has_episodes": 0},
                {"season_number": 1, "monitored": True, "season_has_episodes": 10},
            ],
        }
    ]
    result = connector._process_arr_media(shows, "show")
    s0 = next(r for r in result if r["season_number"] == 0)
    s1 = next(r for r in result if r["season_number"] == 1)
    assert s0["monitored"] is False, "S0 is unmonitored — must not inherit show's True"
    assert s1["monitored"] is True


def test_season_without_monitored_key_falls_back(connector):
    """If a season dict omits 'monitored', the season row keeps whatever
    came from the show — don't silently flip to False."""
    shows = [
        {
            "title": "Some Show",
            "year": 2024,
            "monitored": True,
            "seasons": [
                {"season_number": 1, "season_has_episodes": 5},  # no 'monitored'
            ],
        }
    ]
    result = connector._process_arr_media(shows, "show")
    s1 = next(r for r in result if r["season_number"] == 1)
    assert s1["monitored"] is True


def test_genres_and_cast_preserved_per_season(connector):
    """Season rows must inherit genres and cast_data from the parent show
    so the unmatched_assets filtering by genre still works."""
    shows = [
        {
            "title": "Heated Rivalry",
            "year": 2025,
            "monitored": True,
            "genres": ["Drama", "Romance"],
            "cast_data": [{"name": "Lead"}],
            "seasons": [{"season_number": 1, "monitored": True, "season_has_episodes": 6}],
        }
    ]
    result = connector._process_arr_media(shows, "show")
    s1 = next(r for r in result if r["season_number"] == 1)
    assert s1["genres"] == ["Drama", "Romance"]
    assert s1["cast_data"] == [{"name": "Lead"}]
