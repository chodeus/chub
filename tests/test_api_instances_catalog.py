from backend.util.plex_library_cache import get_cached_libraries, invalidate, _CACHE


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
