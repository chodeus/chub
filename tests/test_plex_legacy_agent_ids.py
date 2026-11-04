"""Libraries on a legacy agent (HAMA, the retired TheTVDB/TheMovieDB/IMDb agents) still yield ids."""

from types import SimpleNamespace

import pytest

from backend.util.plex import PlexClient, legacy_agent_ids


@pytest.mark.parametrize(
    "guid, ids",
    [
        ("com.plexapp.agents.hama://tvdb-267440?lang=en", {"tvdb": "267440"}),
        ("com.plexapp.agents.hama://tvdb3-267440?lang=en", {"tvdb": "267440"}),
        ("com.plexapp.agents.hama://tsdb-1429?lang=en", {"tmdb": "1429"}),
        ("com.plexapp.agents.hama://tmdb-949?lang=en", {"tmdb": "949"}),
        ("com.plexapp.agents.hama://imdb-tt0113277?lang=en", {"imdb": "tt0113277"}),
        ("com.plexapp.agents.hama://anidb-10261?lang=en", {}),
        ("com.plexapp.agents.thetvdb://79126?lang=en", {"tvdb": "79126"}),
        ("com.plexapp.agents.themoviedb://949?lang=en", {"tmdb": "949"}),
        ("com.plexapp.agents.imdb://tt0113277?lang=en", {"imdb": "tt0113277"}),
        ("com.plexapp.agents.imdb://0113277?lang=en", {}),
        ("com.plexapp.agents.thetvdb://abc?lang=en", {}),
        ("com.plexapp.agents.none://1234?lang=en", {}),
        ("plex://movie/5d7768274de0ee001fcc8cc8", {}),
        ("local://1234", {}),
        (None, {}),
    ],
)
def test_legacy_agent_ids(guid, ids):
    found = legacy_agent_ids(guid)

    assert found == ids


class _Movie:
    title = "Heat"
    year = 1995
    ratingKey = 7
    media = []
    labels = []

    def __init__(self, guid, guids=()):
        self.guid = guid
        self.guids = [SimpleNamespace(id=g) for g in guids]


def _indexed(item):
    client = PlexClient.__new__(PlexClient)
    section = SimpleNamespace(type="movie")
    client.plex = SimpleNamespace(library=SimpleNamespace(section=lambda name: section))
    client.fetch_all_plex_media_with_paging = lambda logger, sec: [item]
    noop = lambda *a, **k: None  # noqa: E731
    log = SimpleNamespace(debug=noop, info=noop, warning=noop, error=noop)
    return client.get_all_plex_media("Films", log, "Plex")


def test_snapshot_rows_carry_legacy_agent_ids():
    rows = _indexed(_Movie("com.plexapp.agents.themoviedb://949?lang=en"))

    assert rows[0]["guids"] == {"tmdb": "949"}


def test_modern_guid_wins_over_the_legacy_string():
    rows = _indexed(
        _Movie("com.plexapp.agents.themoviedb://111?lang=en", guids=["tmdb://949"])
    )

    assert rows[0]["guids"] == {"tmdb": "949"}
