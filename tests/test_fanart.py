"""Tests for FanartClient — fanart.tv logo/background selection.

Network is never touched: `_fetch` is monkeypatched to return canned raw API
dicts so we can assert the selection logic (HD-preferred, language tier, most
likes, season-scoped backgrounds, id routing), the required-client-key gate,
and caching.
"""

from types import SimpleNamespace

import pytest

from backend.util.config import FanartConfig
from backend.util.database import ChubDB
from backend.util.fanart import FanartClient


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


@pytest.fixture
def db(tmp_path):
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as database:
        yield database


def _client(client_key="personal", db=None):
    return FanartClient(FanartConfig(client_key=client_key), db, _logger())


MOVIE_RAW = {
    "hdmovielogo": [
        {"url": "L_en_hi", "lang": "en", "likes": 10},
        {"url": "L_en_lo", "lang": "en", "likes": 2},
        {"url": "L_de", "lang": "de", "likes": 50},  # more likes but wrong lang
    ],
    "movielogo": [{"url": "L_sd", "lang": "en", "likes": 100}],  # SD, ignored when HD present
    "moviebackground": [
        {"url": "BG_en", "lang": "en", "likes": 5},
        {"url": "BG_00", "lang": "00", "likes": 1},  # textless preferred for bg
    ],
}


def test_disabled_without_client_key(db):
    c = _client(client_key="", db=db)
    assert c.enabled is False
    assert c.get_images({"asset_type": "movie", "tmdb_id": 1}) is None


def test_enabled_with_client_key(db):
    assert _client(db=db).enabled is True


def test_logo_prefers_language_then_likes(db):
    c = _client(db=db)
    c._fetch = lambda kind, lid: MOVIE_RAW
    images = c.get_images({"asset_type": "movie", "tmdb_id": 123}, language=["en"])
    # English tier beats the higher-liked German; within English, most likes wins.
    assert images["logo"] == "L_en_hi"


def test_logo_hd_preferred_over_sd(db):
    c = _client(db=db)
    c._fetch = lambda kind, lid: MOVIE_RAW
    images = c.get_images({"asset_type": "movie", "tmdb_id": 123}, language=["en"])
    assert images["logo"] != "L_sd"  # SD movielogo ignored while HD exists


def test_background_prefers_textless(db):
    c = _client(db=db)
    c._fetch = lambda kind, lid: MOVIE_RAW
    images = c.get_images({"asset_type": "movie", "tmdb_id": 123}, language=["en"])
    # Textless (lang "00") background wins even with fewer likes.
    assert images["background"] == "BG_00"


def test_logo_falls_back_to_sd_when_no_hd(db):
    c = _client(db=db)
    c._fetch = lambda kind, lid: {"movielogo": [{"url": "ONLY_SD", "lang": "en", "likes": 1}]}
    images = c.get_images({"asset_type": "movie", "tmdb_id": 9}, language=["en"])
    assert images["logo"] == "ONLY_SD"


def test_tv_uses_tvdb_and_scopes_season_background(db):
    raw = {
        "hdtvlogo": [{"url": "TVLOGO", "lang": "en", "likes": 3}],
        "showbackground": [
            {"url": "S1", "lang": "00", "season": "1", "likes": 2},
            {"url": "ALL", "lang": "00", "season": "all", "likes": 9},
            {"url": "S2", "lang": "00", "season": "2", "likes": 100},
        ],
    }
    captured = {}
    c = _client(db=db)

    def fake_fetch(kind, lid):
        captured["kind"] = kind
        captured["lid"] = lid
        return raw

    c._fetch = fake_fetch
    images = c.get_images(
        {"asset_type": "show", "tvdb_id": 456, "season_number": 1}, language=["en"]
    )
    assert captured == {"kind": "tv", "lid": "456"}  # TV routed by tvdb id
    assert images["logo"] == "TVLOGO"
    # Exact season beats both "all" (higher likes) and the wrong season.
    assert images["background"] == "S1"


def test_show_level_background_prefers_all(db):
    raw = {
        "showbackground": [
            {"url": "ALL", "lang": "00", "season": "all", "likes": 1},
            {"url": "S1", "lang": "00", "season": "1", "likes": 99},
        ]
    }
    c = _client(db=db)
    c._fetch = lambda kind, lid: raw
    images = c.get_images({"asset_type": "show", "tvdb_id": 7}, language=["en"])
    assert images["background"] == "ALL"  # show-level → "all", not a season-specific one


def test_movie_falls_back_to_imdb_id(db):
    captured = {}
    c = _client(db=db)

    def fake_fetch(kind, lid):
        captured["lid"] = lid
        return {}

    c._fetch = fake_fetch
    c.get_images({"asset_type": "movie", "tmdb_id": None, "imdb_id": "tt42"})
    assert captured["lid"] == "tt42"


def test_caching_avoids_refetch(db):
    calls = {"n": 0}
    c = _client(db=db)

    def fake_fetch(kind, lid):
        calls["n"] += 1
        return MOVIE_RAW

    c._fetch = fake_fetch
    media = {"asset_type": "movie", "tmdb_id": 555}
    c.get_images(media)
    c.get_images(media)  # memo hit
    assert calls["n"] == 1

    # A fresh client (no memo) reads from the persistent fanart_images_cache.
    c2 = _client(db=db)
    c2._fetch = fake_fetch
    c2.get_images(media)
    assert calls["n"] == 1  # served from DB cache, not refetched


def test_collection_returns_none(db):
    c = _client(db=db)
    c._fetch = lambda kind, lid: {"hdmovielogo": [{"url": "X", "lang": "en", "likes": 1}]}
    assert c.get_images({"asset_type": "collection", "tmdb_id": 1}) is None
