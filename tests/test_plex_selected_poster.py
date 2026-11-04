"""PlexClient.copies_without_upload: copies with no uploaded poster selected; None when Plex can't say."""

from types import SimpleNamespace

import pytest
from plexapi.exceptions import NotFound

from backend.util.plex import PlexClient


def _poster(key, selected=True):
    return SimpleNamespace(ratingKey=key, selected=selected)


def _client(item=None, search=()):
    items = {str(getattr(i, "ratingKey", "")): i for i in search}
    client = PlexClient.__new__(PlexClient)
    noop = lambda *a, **k: None  # noqa: E731
    client.logger = SimpleNamespace(debug=noop, info=noop, error=noop)

    def fetch(key):
        if item is None:
            raise NotFound("gone")
        return item if str(key) == "7" else items[str(key)]

    section = SimpleNamespace(search=lambda **k: list(search))
    client.plex = SimpleNamespace(
        fetchItem=fetch, library=SimpleNamespace(section=lambda name: section)
    )
    return client


def _shown(client, plex_id="7"):
    return client.copies_without_upload("Films", "Dune", year=2021, plex_id=plex_id)


@pytest.mark.parametrize(
    "posters, missing",
    [
        ([_poster("upload://posters/abc")], []),
        ([_poster("metadata://posters/tmdb", False), _poster("upload://posters/abc")], []),
        ([_poster("metadata://posters/tmdb")], ["7"]),
        ([_poster("https://image.tmdb.org/t/p/original/x.jpg")], ["7"]),
        ([_poster("upload://posters/abc", False)], ["7"]),
        ([], ["7"]),
    ],
)
def test_what_plex_has_selected(posters, missing):
    item = SimpleNamespace(TYPE="movie", ratingKey=7, posters=lambda: posters)

    found = _shown(_client(item))

    assert found == missing


def test_a_title_search_reports_only_the_copy_without_an_upload():
    kept = SimpleNamespace(ratingKey=1, posters=lambda: [_poster("upload://posters/a")])
    lost = SimpleNamespace(ratingKey=2, posters=lambda: [_poster("metadata://posters/b")])

    found = _shown(_client(search=[kept, lost]), plex_id=None)

    assert found == ["2"]


def test_unknown_when_plex_holds_no_such_item():
    found = _shown(_client(item=None, search=[]))

    assert found is None


def test_unknown_when_plex_cannot_list_the_posters():
    def broken():
        raise ConnectionError("Plex timed out")

    found = _shown(_client(SimpleNamespace(TYPE="movie", posters=broken)))

    assert found is None
