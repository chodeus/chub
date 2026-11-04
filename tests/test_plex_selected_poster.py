"""PlexClient.shows_uploaded_poster: False only when Plex has gone back to a provider poster."""

from types import SimpleNamespace

import pytest
from plexapi.exceptions import NotFound

from backend.util.plex import PlexClient


def _poster(key, selected=True):
    return SimpleNamespace(ratingKey=key, selected=selected)


def _client(item=None, search=()):
    client = PlexClient.__new__(PlexClient)
    noop = lambda *a, **k: None  # noqa: E731
    client.logger = SimpleNamespace(debug=noop, info=noop, error=noop)

    def fetch(key):
        if item is None:
            raise NotFound("gone")
        return item

    section = SimpleNamespace(search=lambda **k: list(search))
    client.plex = SimpleNamespace(
        fetchItem=fetch, library=SimpleNamespace(section=lambda name: section)
    )
    return client


def _shown(client):
    return client.shows_uploaded_poster("Films", "Dune", year=2021, plex_id="7")


@pytest.mark.parametrize(
    "posters, shown",
    [
        ([_poster("upload://posters/abc")], True),
        ([_poster("metadata://posters/tmdb", False), _poster("upload://posters/abc")], True),
        ([_poster("metadata://posters/tmdb")], False),
        ([_poster("https://image.tmdb.org/t/p/original/x.jpg")], False),
        ([_poster("upload://posters/abc", False)], False),
        ([], False),
    ],
)
def test_what_plex_has_selected(posters, shown):
    item = SimpleNamespace(TYPE="movie", posters=lambda: posters)

    assert _shown(_client(item)) is shown


def test_unknown_when_plex_holds_no_such_item():
    assert _shown(_client(item=None, search=[])) is None


def test_unknown_when_plex_cannot_list_the_posters():
    def broken():
        raise ConnectionError("Plex timed out")

    assert _shown(_client(SimpleNamespace(TYPE="movie", posters=broken))) is None
