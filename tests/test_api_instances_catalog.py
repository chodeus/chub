from types import SimpleNamespace

import pytest

from backend.api.instances import _PlexFetchError, _fetch_plex_libraries
from backend.util.plex_library_cache import get_cached_libraries, invalidate, _CACHE


def test_fetch_plex_libraries_blocks_ssrf_url():
    # Link-local metadata address must be refused before any network call.
    plex = SimpleNamespace(url="http://169.254.169.254", api="token")
    with pytest.raises(_PlexFetchError) as exc:
        _fetch_plex_libraries(plex)
    assert exc.value.code == "URL_BLOCKED"
    assert exc.value.status_code == 400


def test_fetch_plex_libraries_missing_credentials():
    with pytest.raises(_PlexFetchError) as exc:
        _fetch_plex_libraries(SimpleNamespace(url="", api=""))
    assert exc.value.code == "PLEX_CREDENTIALS_MISSING"


def test_cache_returns_fetched_value_and_memoizes():
    _CACHE.clear()
    calls = {"n": 0}

    def fetch(instance):
        calls["n"] += 1
        return [{"title": "Movies", "type": "movie"}]

    a = get_cached_libraries("Plex", fetch, ttl_seconds=60, now=1000.0)
    b = get_cached_libraries("Plex", fetch, ttl_seconds=60, now=1030.0)
    assert a == b == [{"title": "Movies", "type": "movie"}]
    assert calls["n"] == 1


def test_cache_expires_after_ttl():
    _CACHE.clear()
    calls = {"n": 0}

    def fetch(instance):
        calls["n"] += 1
        return [{"title": "Movies", "type": "movie"}]

    get_cached_libraries("Plex", fetch, ttl_seconds=60, now=1000.0)
    get_cached_libraries("Plex", fetch, ttl_seconds=60, now=1100.0)
    assert calls["n"] == 2


def test_invalidate_clears_one_and_all():
    _CACHE.clear()
    get_cached_libraries("A", lambda i: [{"title": "x"}], 60, 1000.0)
    get_cached_libraries("B", lambda i: [{"title": "y"}], 60, 1000.0)
    invalidate("A")
    assert "A" not in _CACHE and "B" in _CACHE
    invalidate()
    assert _CACHE == {}
