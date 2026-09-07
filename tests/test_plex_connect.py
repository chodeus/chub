"""Tests for backend.util.plex.connect_plex_with_retry — the shared
server-level connect-with-retry used by poster_cleanarr and plex_maintenance."""

from backend.util import plex as plex_mod
from backend.util.plex import connect_plex_with_retry


class _Log:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def test_connect_success(monkeypatch):
    class FakeServer:
        version = "1.2.3"

        def __init__(self, url, token, timeout=None):
            pass

    monkeypatch.setattr(plex_mod, "PlexServer", FakeServer)
    server = connect_plex_with_retry("http://x", "tok", _Log(), instance_name="p")
    assert isinstance(server, FakeServer)


def test_connect_auth_failure_returns_none_without_retry(monkeypatch):
    calls = {"n": 0}

    class FakeServer:
        def __init__(self, *a, **k):
            calls["n"] += 1
            raise Exception("401 Unauthorized")

    monkeypatch.setattr(plex_mod, "PlexServer", FakeServer)
    monkeypatch.setattr(plex_mod.time, "sleep", lambda s: None)
    assert connect_plex_with_retry("http://x", "tok", _Log(), max_retries=3) is None
    assert calls["n"] == 1  # auth failure is terminal — no retry


def test_connect_retries_then_succeeds(monkeypatch):
    state = {"n": 0}

    class FakeServer:
        version = "9"

        def __init__(self, *a, **k):
            state["n"] += 1
            if state["n"] < 3:
                raise Exception("connection refused")

    monkeypatch.setattr(plex_mod, "PlexServer", FakeServer)
    monkeypatch.setattr(plex_mod.time, "sleep", lambda s: None)
    server = connect_plex_with_retry("http://x", "tok", _Log(), max_retries=5)
    assert server is not None
    assert state["n"] == 3


def test_connect_gives_up_after_max_retries(monkeypatch):
    class FakeServer:
        def __init__(self, *a, **k):
            raise Exception("connection refused")

    monkeypatch.setattr(plex_mod, "PlexServer", FakeServer)
    monkeypatch.setattr(plex_mod.time, "sleep", lambda s: None)
    assert connect_plex_with_retry("http://x", "tok", _Log(), max_retries=2) is None


class _DebugLog(_Log):
    def debug(self, *a, **k):
        pass


def _client_with_fake_search(search_results, counter):
    """A minimal PlexClient whose library.section().search() is counted."""
    from backend.util.plex import PlexClient

    class FakeSection:
        type = "show"

        def search(self, **kw):
            counter["n"] += 1
            return list(search_results)

    class FakeLibrary:
        def section(self, name):
            return FakeSection()

    client = object.__new__(PlexClient)
    client.plex = type("P", (), {"library": FakeLibrary()})()
    client.logger = _DebugLog()
    return client


def test_locate_targets_memoized_per_client():
    """Resolving the same item repeatedly (logo, background, … all share the
    same locate params) must hit Plex once, not once per call."""
    counter = {"n": 0}

    class FakeItem:
        title = "Show"
        editionTitle = None

        def seasons(self):
            return []

    client = _client_with_fake_search([FakeItem()], counter)

    r1 = client._locate_targets("TV", "Show", year=2021)
    r2 = client._locate_targets("TV", "Show", year=2021)  # logo vs background
    assert counter["n"] == 1  # second call served from the per-client cache
    assert r1 == r2 and len(r1) == 1

    # A different season is a distinct key → one more search, then cached.
    client._locate_targets("TV", "Show", year=2021, season_number=1)
    client._locate_targets("TV", "Show", year=2021, season_number=1)
    assert counter["n"] == 2


def _client_with_year_aware_search(year_results, titleonly_results):
    """PlexClient whose section.search distinguishes a year-qualified search
    (``search(title=, year=)``) from a title-only fallback search."""
    from backend.util.plex import PlexClient

    class FakeSection:
        type = "movie"

        def search(self, **kw):
            if "year" in kw and kw["year"] is not None:
                return list(year_results)
            return list(titleonly_results)

    class FakeLibrary:
        def section(self, name):
            return FakeSection()

    client = object.__new__(PlexClient)
    client.plex = type("P", (), {"library": FakeLibrary()})()
    client.logger = _DebugLog()
    client._locate_cache = {}
    return client


class _FakeMovie:
    def __init__(self, year):
        self.title = "Thanks for Sharing"
        self.year = year
        self.editionTitle = None

    def seasons(self):
        return []


def test_locate_targets_year_tolerant_fallback_within_one():
    """Year drift: strict year= search misses, but a single title-only hit one
    year off is accepted (Plex 2012 vs *arr 2013)."""
    plex_2012 = _FakeMovie(2012)
    client = _client_with_year_aware_search(
        year_results=[], titleonly_results=[plex_2012]
    )
    targets = client._locate_targets("Films", "Thanks for Sharing", year=2013)
    assert targets == [plex_2012]


def test_locate_targets_year_tolerant_fallback_rejects_off_by_two():
    """A 2-year gap is outside ±1 tolerance and stays a miss when ambiguous."""
    client = _client_with_year_aware_search(
        year_results=[],
        titleonly_results=[_FakeMovie(2010), _FakeMovie(2015)],
    )
    targets = client._locate_targets("Films", "Thanks for Sharing", year=2013)
    assert targets == []


def test_locate_targets_lone_titleonly_hit_rejects_wrong_year():
    """A LONE title-only hit of a clearly different year is a different release
    (e.g. a remake) and must NOT receive the poster — the single-candidate
    branch is year-guarded like the multi-candidate one. Regression: a
    'Halloween' (2018) poster landed on the 1978 item when only the 1978 film
    was in the library."""
    client = _client_with_year_aware_search(
        year_results=[], titleonly_results=[_FakeMovie(1978)]
    )
    targets = client._locate_targets("Films", "Thanks for Sharing", year=2018)
    assert targets == []


def test_locate_targets_lone_titleonly_hit_keeps_yearless_candidate():
    """A lone hit with NO year (Plex metadata gap) is kept — a missing year
    must not reject the only candidate (mirrors _disambiguate_by_year)."""
    yearless = _FakeMovie(None)
    client = _client_with_year_aware_search(
        year_results=[], titleonly_results=[yearless]
    )
    targets = client._locate_targets("Films", "Thanks for Sharing", year=2018)
    assert targets == [yearless]


def test_locate_targets_lone_titleonly_hit_rejects_malformed_year():
    """A lone hit with a non-empty MALFORMED year fails closed — an
    unverifiable candidate must not receive the poster (only genuinely
    missing years are treated as a metadata gap)."""
    client = _client_with_year_aware_search(
        year_results=[], titleonly_results=[_FakeMovie("not-a-year")]
    )
    targets = client._locate_targets("Films", "Thanks for Sharing", year=2018)
    assert targets == []


def _client_with_fetchitem(item_or_exc, search_counter):
    """PlexClient whose plex.fetchItem returns an item (or raises) and whose
    section.search is counted, to prove ratingKey resolution skips searching."""
    from backend.util.plex import PlexClient

    class FakeSection:
        def search(self, **kw):
            search_counter["n"] += 1
            return list(search_counter.get("results", []))

    class FakeLibrary:
        def section(self, name):
            return FakeSection()

    class FakePlex:
        library = FakeLibrary()

        def fetchItem(self, rk):
            if isinstance(item_or_exc, Exception):
                raise item_or_exc
            return item_or_exc

    client = object.__new__(PlexClient)
    client.plex = FakePlex()
    client.logger = _DebugLog()
    client._locate_cache = {}
    return client


def test_locate_targets_fetches_by_rating_key():
    """plex_id present → fetch the exact item by ratingKey; never title-search."""

    class FakeItem:
        TYPE = "movie"

    item = FakeItem()
    counter = {"n": 0}
    client = _client_with_fetchitem(item, counter)
    targets = client._locate_targets(
        "Films", "Wrong *arr Title", year=1999, plex_id="218095"
    )
    assert targets == [item]
    assert counter["n"] == 0  # ratingKey hit — no fallback search


def test_locate_targets_stale_rating_key_falls_back_to_search():
    """A stale ratingKey (fetchItem raises) self-heals via the title+year search."""
    found = _FakeMovie(2007)
    counter = {"n": 0, "results": [found]}
    client = _client_with_fetchitem(RuntimeError("404 not found"), counter)
    targets = client._locate_targets(
        "Films", "AVPR", year=2007, plex_id="999999"
    )
    assert targets == [found]  # fell back to the live search
    assert counter["n"] >= 1
