"""PlexClient reads and writes labels on one target: the exact ratingKey, else a title search."""

from types import SimpleNamespace

import pytest
from plexapi.exceptions import NotFound

from backend.util.plex import PlexClient


class _Item:
    def __init__(self, *labels, fail_writes=False):
        self.labels = [SimpleNamespace(tag=t) for t in labels]
        self.added, self.removed = [], []
        self._fail = fail_writes

    def addLabel(self, label):
        if self._fail:
            raise ConnectionError("Plex timed out")
        self.added.append(label)

    def removeLabel(self, label):
        self.removed.append(label)


def _no_title_search(*a, **k):
    pytest.fail("a known ratingKey must never fall back to a title search")


def _client(fetch=None, locate=_no_title_search):
    client = PlexClient.__new__(PlexClient)
    noop = lambda *a, **k: None  # noqa: E731
    client.logger = SimpleNamespace(info=noop, debug=noop, error=noop)
    client.plex = SimpleNamespace(fetchItem=fetch)
    client._locate_targets_uncached = locate
    return client


def _raising(exc):
    def fetch(rating_key):
        raise exc

    return fetch


KEYED = {"library_name": "Films", "title": "Some Film", "year": 2024, "plex_id": "7"}
UNKEYED = {"library_name": "Films", "title": "Some Film", "year": 2024}


def test_reads_the_exact_rating_key_item():
    item = _Item("kids", "4k")
    fetched = []

    def fetch(rating_key):
        fetched.append(rating_key)
        return item

    labels = _client(fetch).current_labels(KEYED)

    assert labels == ["kids", "4k"]
    assert fetched == [7]


def test_none_when_the_rating_key_is_gone_without_a_title_search():
    labels = _client(_raising(NotFound("404"))).current_labels(KEYED)

    assert labels is None


def test_a_failed_lookup_raises_rather_than_reading_as_gone():
    client = _client(_raising(ConnectionError("Plex unreachable")))

    with pytest.raises(ConnectionError):
        client.current_labels(KEYED)


def test_without_a_rating_key_searches_by_title():
    found = _client(locate=lambda *a, **k: [_Item("x")]).current_labels(UNKEYED)
    missing = _client(locate=lambda *a, **k: []).current_labels(UNKEYED)

    assert (found, missing) == (["x"], None)


def test_writes_go_to_the_item_the_labels_were_read_from():
    item = _Item()

    _client(lambda rk: item).batch_update_labels(KEYED, ["kids"], ["old"])

    assert (item.added, item.removed) == (["kids"], ["old"])


def test_a_write_to_a_gone_item_raises():
    client = _client(_raising(NotFound("404")))

    with pytest.raises(LookupError):
        client.batch_update_labels(KEYED, ["kids"], [])


def test_a_failed_write_raises():
    client = _client(lambda rk: _Item(fail_writes=True))

    with pytest.raises(ConnectionError):
        client.batch_update_labels(KEYED, ["kids"], [])


def test_a_dry_run_writes_nothing_but_still_needs_the_item():
    item = _Item()
    _client(lambda rk: item).batch_update_labels(KEYED, ["kids"], ["old"], dry_run=True)
    gone = _client(_raising(NotFound("404")))

    assert (item.added, item.removed) == ([], [])
    with pytest.raises(LookupError):
        gone.batch_update_labels(KEYED, ["kids"], [], dry_run=True)
