"""Tests for the develop-only Plex artwork source (backend/util/cl2k/plex_art.py)
and the Plex host SSRF allowlist (backend/util/cl2k/image_fetch.py).

No live Plex: plexapi's PlexServer is monkeypatched with a fake that mirrors the
real surface (fetchItem → item.logos()/arts()/posters(), server.url()).
"""

from types import SimpleNamespace

import backend.util.cl2k.image_fetch as image_fetch
from backend.util.cl2k.plex_art import _matches, _resolve, plex_images


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------


def _logger():
    return SimpleNamespace(
        warning=lambda *a, **k: None,
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )


def _config(plex_instances):
    return SimpleNamespace(instances=SimpleNamespace(plex=plex_instances))


def _db(rows_by_instance):
    return SimpleNamespace(
        plex=SimpleNamespace(get_by_instance=lambda name: rows_by_instance.get(name))
    )


class _Res:
    def __init__(self, key, provider="themoviedb", selected=False):
        self.key = key
        self.provider = provider
        self.selected = selected


class _Item:
    def logos(self):
        return [
            _Res(
                "/library/metadata/9/clearLogos/local", provider="local", selected=True
            )
        ]

    def arts(self):
        return [_Res("https://image.tmdb.org/t/p/original/bg.jpg")]

    def posters(self):
        return [_Res("/library/metadata/9/posters/p1")]


class _Server:
    def __init__(self, url, token):
        self.url_base = url
        self.token = token

    def fetchItem(self, rating_key):
        assert rating_key == 9
        return _Item()

    def url(self, key, includeToken=False):
        tok = "?X-Plex-Token=secret" if includeToken else ""
        return f"{self.url_base}{key}{tok}"


def _patch_plexserver(monkeypatch):
    import plexapi.server

    monkeypatch.setattr(plexapi.server, "PlexServer", _Server)


# --------------------------------------------------------------------------
# guid matching + resolution
# --------------------------------------------------------------------------


def test_matches_by_each_id():
    g = {"tmdb": "503314", "tvdb": "81189", "imdb": "tt0133093"}
    assert _matches(g, 503314, None, None)
    assert _matches(g, None, 81189, None)
    assert _matches(g, None, None, "tt0133093")
    assert not _matches(g, 999, None, None)


def test_resolve_type_gates_movie_vs_show():
    # Same tmdb id under both a movie and a show row (separate TMDB namespaces).
    rows = {
        "main": [
            {"asset_type": "movie", "plex_id": "10", "guids": '{"tmdb": "62715"}'},
            {"asset_type": "show", "plex_id": "20", "guids": '{"tmdb": "62715"}'},
        ]
    }
    cfg = _config(
        {"main": SimpleNamespace(url="http://plex:32400", api="t", enabled=True)}
    )
    db = _db(rows)
    _c, key_show = _resolve(
        cfg, db, media_type="show", tmdb_id=62715, tvdb_id=None, imdb_id=None
    )
    _c, key_movie = _resolve(
        cfg, db, media_type="movie", tmdb_id=62715, tvdb_id=None, imdb_id=None
    )
    assert key_show == "20"
    assert key_movie == "10"


def test_resolve_skips_disabled_or_unconfigured_instances():
    rows = {"main": [{"asset_type": "movie", "plex_id": "5", "guids": '{"tmdb": "1"}'}]}
    cfg = _config({"main": SimpleNamespace(url="", api="", enabled=True)})  # no url
    _c, key = _resolve(
        _config(cfg.instances.plex),
        _db(rows),
        media_type="movie",
        tmdb_id=1,
        tvdb_id=None,
        imdb_id=None,
    )
    assert key is None


# --------------------------------------------------------------------------
# plex_images end-to-end (mocked Plex)
# --------------------------------------------------------------------------


def test_plex_images_extracts_logos_arts_posters(monkeypatch):
    _patch_plexserver(monkeypatch)
    rows = {
        "main": [{"asset_type": "show", "plex_id": "9", "guids": '{"tmdb": "62715"}'}]
    }
    cfg = _config(
        {"main": SimpleNamespace(url="http://plex:32400", api="tok", enabled=True)}
    )
    res = plex_images(cfg, _db(rows), _logger(), kind="show", tmdb_id=62715)
    assert (
        len(res["logos"]) == 1
        and len(res["backdrops"]) == 1
        and len(res["posters"]) == 1
    )
    # local key → base + token; remote provider key → passthrough.
    assert (
        res["logos"][0]["url"]
        == "http://plex:32400/library/metadata/9/clearLogos/local?X-Plex-Token=secret"
    )
    assert res["logos"][0]["selected"] is True
    assert res["backdrops"][0]["url"] == "https://image.tmdb.org/t/p/original/bg.jpg"
    assert "reason" not in res


def test_plex_images_no_instance_returns_reason():
    res = plex_images(_config({}), _db({}), _logger(), kind="movie", tmdb_id=1)
    assert res["logos"] == [] and res["reason"]


def test_plex_images_not_in_library_returns_reason():
    cfg = _config(
        {"main": SimpleNamespace(url="http://plex:32400", api="t", enabled=True)}
    )
    res = plex_images(cfg, _db({"main": []}), _logger(), kind="movie", tmdb_id=999)
    assert res["backdrops"] == [] and "synced Plex library" in res["reason"]


# --------------------------------------------------------------------------
# SSRF allowlist
# --------------------------------------------------------------------------


def test_ssrf_allows_configured_plex_netloc(monkeypatch):
    monkeypatch.setattr(image_fetch, "_plex_netlocs", lambda: {"192.168.2.206:32400"})
    assert image_fetch._is_allowed_image_host(
        "http://192.168.2.206:32400/library/metadata/9/x?X-Plex-Token=t"
    )
    # same host, different port (another service) is NOT allowed
    assert not image_fetch._is_allowed_image_host("http://192.168.2.206:9999/secret")
    # cloud-metadata SSRF target stays blocked
    assert not image_fetch._is_allowed_image_host(
        "http://169.254.169.254/latest/meta-data/"
    )
    # the CDNs still pass
    assert image_fetch._is_allowed_image_host(
        "https://image.tmdb.org/t/p/original/x.jpg"
    )


def test_ssrf_allows_plex_tv_cdn():
    # Plex's artwork picker returns remote-provider art (tmdb/fanarttv/gracenote)
    # as absolute metadata-static.plex.tv URLs — selecting one must be fetchable
    # (it 500'd before *.plex.tv was allowlisted).
    assert image_fetch._is_allowed_image_host(
        "https://metadata-static.plex.tv/2/gracenote/2af07f7e.jpg"
    )
    assert image_fetch._is_allowed_image_host("https://images.plex.tv/photo?u=x")
    # lookalike domains stay blocked
    assert not image_fetch._is_allowed_image_host("https://evilplex.tv/x.png")
    assert not image_fetch._is_allowed_image_host("https://plex.tv.attacker.io/x.png")
