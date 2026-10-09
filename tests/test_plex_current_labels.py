"""PlexClient.current_labels reads an item's labels live: None when gone, raises when the read fails."""

from types import SimpleNamespace

import pytest

from backend.util.plex import PlexClient


def _client(locate):
    client = PlexClient.__new__(PlexClient)
    client.logger = SimpleNamespace(error=lambda *a, **k: None)
    client._locate_targets_uncached = locate
    return client


ENTRY = {"library_name": "Films", "title": "Some Film", "year": 2024, "plex_id": "7"}


def test_returns_the_live_item_labels():
    seen = {}

    def locate(library, title, **kwargs):
        seen.update(library=library, title=title, plex_id=kwargs.get("plex_id"))
        return [SimpleNamespace(labels=[SimpleNamespace(tag="kids"), SimpleNamespace(tag="4k")])]

    labels = _client(locate).current_labels(ENTRY)

    assert labels == ["kids", "4k"]
    assert seen == {"library": "Films", "title": "Some Film", "plex_id": "7"}


def test_none_when_plex_no_longer_has_the_item():
    labels = _client(lambda *a, **k: []).current_labels(ENTRY)

    assert labels is None


def test_a_failed_lookup_raises_rather_than_reading_as_gone():
    def boom(*a, **k):
        raise RuntimeError("Plex unreachable")

    with pytest.raises(RuntimeError):
        _client(boom).current_labels(ENTRY)
