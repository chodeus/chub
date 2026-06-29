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
            "seasons": [
                {"season_number": 1, "monitored": True, "season_has_episodes": 6}
            ],
        }
    ]
    result = connector._process_arr_media(shows, "show")
    s1 = next(r for r in result if r["season_number"] == 1)
    assert s1["genres"] == ["Drama", "Romance"]
    assert s1["cast_data"] == [{"name": "Lead"}]


# --- _process_arr_media: artist + album fan-out (music) ---


def _artist_with_albums():
    return [
        {
            "title": "REZZ",
            "musicbrainz_id": "artist-mbid-1",
            "monitored": True,
            "genres": ["Electronic"],
            "seasons": [
                {
                    "season_number": 0,
                    "album_id": 101,
                    "album_title": "Mass Manipulation",
                    "foreign_album_id": "album-mbid-1",
                    "monitored": True,
                },
                {
                    "season_number": 1,
                    "album_id": 102,
                    "album_title": "Certain Kind of Magic",
                    "foreign_album_id": "album-mbid-2",
                    "monitored": False,
                },
            ],
        }
    ]


def test_artist_fans_out_to_artist_plus_album_rows(connector):
    """An artist with 2 albums yields the artist row plus 2 asset_type=album
    rows — albums are first-class, NOT artist+season rows."""
    result = connector._process_arr_media(_artist_with_albums(), "artist")
    assert len(result) == 3
    artist_row = result[0]
    assert artist_row.get("asset_type") in (None, "artist")
    assert artist_row["season_number"] is None
    albums = [r for r in result if r.get("asset_type") == "album"]
    assert len(albums) == 2
    for a in albums:
        assert a["season_number"] is None


def test_album_rows_carry_mbid_and_parent_linkage(connector):
    """Each album row carries its own album MBID and the parent artist's MBID
    and title, so it can be matched independently and parent-scoped."""
    result = connector._process_arr_media(_artist_with_albums(), "artist")
    albums = {r["title"]: r for r in result if r.get("asset_type") == "album"}
    mass = albums["Mass Manipulation"]
    assert mass["musicbrainz_id"] == "album-mbid-1"
    assert mass["parent_musicbrainz_id"] == "artist-mbid-1"
    assert mass["parent_title"] == "REZZ"
    assert mass["arr_id"] == 101
    # Per-album monitored flag is preserved.
    assert albums["Certain Kind of Magic"]["monitored"] is False


def test_artist_without_albums_yields_only_artist_row(connector):
    """seasons=None (include_episode=False) must not crash and yields just
    the artist row."""
    artists = [{"title": "Boards of Canada", "musicbrainz_id": "a", "seasons": None}]
    result = connector._process_arr_media(artists, "artist")
    assert len(result) == 1
    assert result[0]["season_number"] is None


def test_album_rows_carry_per_album_has_content(connector):
    """Each album row's has_content reflects THAT album's own track-file
    presence (set in arr normalize), not the artist-level rollup it copies.
    Regression: every Lidarr row had has_content unset, so the Statistics
    page showed 0 in-library and counted every monitored album as missing."""
    artists = [
        {
            "title": "REZZ",
            "musicbrainz_id": "artist-mbid-1",
            "monitored": True,
            "has_content": True,  # artist-level rollup (has some music)
            "seasons": [
                {
                    "season_number": 0,
                    "album_id": 101,
                    "album_title": "Mass Manipulation",
                    "foreign_album_id": "album-mbid-1",
                    "monitored": True,
                    "has_content": True,  # this album is on disk
                },
                {
                    "season_number": 1,
                    "album_id": 102,
                    "album_title": "Certain Kind of Magic",
                    "foreign_album_id": "album-mbid-2",
                    "monitored": True,
                    "has_content": False,  # this album has no files
                },
            ],
        }
    ]
    result = connector._process_arr_media(artists, "artist")
    albums = {r["title"]: r for r in result if r.get("asset_type") == "album"}
    assert albums["Mass Manipulation"]["has_content"] is True
    assert albums["Certain Kind of Magic"]["has_content"] is False, (
        "empty album must not inherit the artist's has_content=True rollup"
    )
    # Artist row keeps its own aggregate rollup.
    assert result[0]["has_content"] is True
