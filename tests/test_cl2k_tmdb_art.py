"""CR-4 regression: tmdb_art.external_ids caches an authoritative 404 default but
never a transient failure — a single blip must not permanently blank a title's ids
(they feed generated filenames). Mirrors list_season_images' 404-only caching.
"""

import threading
import types

from backend.util.cl2k.tmdb_art import external_ids


class _Resp:
    def __init__(self, status_code, payload=None, ok=None):
        self.status_code = status_code
        self.ok = (200 <= status_code < 300) if ok is None else ok
        self._payload = payload

    def json(self):
        return self._payload


class _FakeTMDB:
    BASE = "https://api.themoviedb.org/3"

    def __init__(self, responses):
        self.enabled = True
        self.cfg = types.SimpleNamespace(apikey="k")
        self._memo = {}
        self._memo_lock = threading.Lock()
        self._responses = list(responses)
        self.calls = 0

    def _request_with_retry(self, url, params, *, what):
        self.calls += 1
        return self._responses.pop(0)


def test_external_ids_caches_a_404_default():
    """A 404 is authoritative 'no external ids' — memoized, so it isn't re-fetched."""
    tmdb = _FakeTMDB([_Resp(404)])
    assert external_ids(tmdb, 603, "movie") == {"tvdb_id": None, "imdb_id": None}
    assert external_ids(tmdb, 603, "movie") == {"tvdb_id": None, "imdb_id": None}
    assert tmdb.calls == 1  # second call served from the memo


def test_external_ids_does_not_cache_a_transient_5xx():
    """A 5xx is transient — not memoized, so a later retry recovers the real ids."""
    tmdb = _FakeTMDB(
        [_Resp(503, ok=False), _Resp(200, {"tvdb_id": 81189, "imdb_id": "tt0133093"})]
    )
    assert external_ids(tmdb, 603, "movie") == {"tvdb_id": None, "imdb_id": None}
    assert external_ids(tmdb, 603, "movie") == {"tvdb_id": 81189, "imdb_id": "tt0133093"}
    assert tmdb.calls == 2  # 5xx was NOT cached


def test_external_ids_does_not_cache_a_none_result():
    """A None (timeout / exhausted retries) is transient — not memoized either."""
    tmdb = _FakeTMDB([None, _Resp(200, {"tvdb_id": 999, "imdb_id": None})])
    assert external_ids(tmdb, 42, "show") == {"tvdb_id": None, "imdb_id": None}
    assert external_ids(tmdb, 42, "show") == {"tvdb_id": 999, "imdb_id": None}
    assert tmdb.calls == 2  # None was NOT cached
