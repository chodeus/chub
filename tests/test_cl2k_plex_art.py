"""Tests for the develop-only Plex artwork source (backend/util/cl2k/plex_art.py)
and the Plex host SSRF allowlist (backend/util/cl2k/image_fetch.py).

No live Plex: plexapi's PlexServer is monkeypatched with a fake that mirrors the
real surface (fetchItem → item.logos()/arts()/posters(), server.url()).
"""

from types import SimpleNamespace

import pytest

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
    # Local key → BOTH file_path and url become the token-free CL2K proxy path
    # (the browser loads it token-free; the backend unwraps ?src= and re-mints).
    # Remote provider key → passthrough on both. X-Plex-Token never appears.
    logo = res["logos"][0]
    proxy = (
        "/api/cl2k-maker/plex-art"
        "?src=http%3A%2F%2Fplex%3A32400%2Flibrary%2Fmetadata%2F9%2FclearLogos%2Flocal"
    )
    assert logo["file_path"] == proxy
    assert logo["url"] == proxy
    assert "X-Plex-Token" not in logo["file_path"]
    assert "X-Plex-Token" not in logo["url"]
    assert logo["selected"] is True
    backdrop = res["backdrops"][0]
    assert backdrop["file_path"] == "https://image.tmdb.org/t/p/original/bg.jpg"
    assert backdrop["url"] == "https://image.tmdb.org/t/p/original/bg.jpg"
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


def test_ssrf_allows_thetvdb_artwork():
    # Plex serves TheTVDB-agent art (common on shows) as absolute
    # artworks.thetvdb.com URLs — selecting one 500'd ("disallowed host") until
    # the CDN was allowlisted alongside tmdb/fanart/plex.
    assert image_fetch._is_allowed_image_host(
        "https://artworks.thetvdb.com/banners/v4/movie/6187/backgrounds/x.jpg"
    )
    assert image_fetch._is_allowed_image_host("https://thetvdb.com/x.jpg")
    # lookalikes stay blocked
    assert not image_fetch._is_allowed_image_host("https://thetvdb.com.attacker.io/x")
    assert not image_fetch._is_allowed_image_host("https://eviltvdb.com/x.png")


# --------------------------------------------------------------------------
# /plex-art proxy route
# --------------------------------------------------------------------------


def test_img_media_type_from_magic_bytes():
    from backend.api.cl2k_maker import _img_media_type

    assert _img_media_type(b"\x89PNG\r\n\x1a\n....") == "image/png"
    assert _img_media_type(b"\xff\xd8\xff\xe0abc") == "image/jpeg"
    assert _img_media_type(b"RIFF\x00\x00\x00\x00WEBPvp8 ") == "image/webp"
    assert _img_media_type(b"garbage") == "image/jpeg"


def test_plex_art_proxy_streams_bytes_without_token(monkeypatch):
    import backend.api.cl2k_maker as api

    seen = {}

    def _fake_download(src):
        seen["src"] = src
        return b"\x89PNG\r\n\x1a\nDATA"

    monkeypatch.setattr(api, "download_image", _fake_download)
    resp = api.plex_art_proxy(
        src="http://plex:32400/library/metadata/9/thumb/1699", logger=_logger()
    )
    assert resp.status_code == 200
    assert resp.media_type == "image/png"
    assert resp.body == b"\x89PNG\r\n\x1a\nDATA"
    # The proxy fetches the tokenless src server-side (download re-mints the token).
    assert "X-Plex-Token" not in seen["src"]


def test_plex_art_proxy_rejects_non_artwork_src(monkeypatch):
    # A leaked <img> URL carries a live stream token + the Plex host in src; that
    # src must not be rewritable to a non-artwork Plex endpoint (the /:/prefs
    # response leaks the account-level PlexOnlineToken).
    import backend.api.cl2k_maker as api
    from fastapi import HTTPException

    called = {"n": 0}
    monkeypatch.setattr(
        api, "download_image", lambda src: called.__setitem__("n", called["n"] + 1)
    )
    for bad in (
        "http://plex:32400/:/prefs",
        "http://plex:32400/myplex/account",
        "http://plex:32400/library/sections/1/all",
        "http://plex:32400/photo/:/transcode?url=http://169.254.169.254/",
        "http://plex:32400/library/metadata/9/children",
        # dot-segment traversal (raw + percent-encoded) — requests/Plex collapse
        # ../ downstream to /:/prefs, so a string-only regex on the raw path is
        # defeated. This is the round-2 blocker; must be rejected pre-fetch.
        "http://plex:32400/library/metadata/1/art/../../../../:/prefs",
        "http://plex:32400/library/metadata/1/art/%2e%2e/%2e%2e/%2e%2e/:/prefs",
        "http://plex:32400/library/metadata/1/art/..%2f..%2f..%2f:/prefs",
        "http://plex:32400/library/metadata/1/art//../:/prefs",
    ):
        with pytest.raises(HTTPException) as excinfo:
            api.plex_art_proxy(src=bad, logger=_logger())
        assert excinfo.value.status_code == 400
    assert called["n"] == 0  # never reached the fetch


def test_valid_plex_art_src_allows_local_file_key():
    # Recent Plex/plexapi returns locally-stored posters/art/logos (uploaded or
    # agent-combined) with a /library/metadata/<id>/file?url=<provider-uri> key;
    # rejecting it made every local poster show 400 (invisible in the picker).
    from backend.api.cl2k_maker import _valid_plex_art_src

    for provider in ("upload", "metadata", "media"):
        assert _valid_plex_art_src(
            f"http://plex:32400/library/metadata/738/file?url={provider}%3A%2F%2Fposters%2Fabc"
        )
    # the pre-existing artwork types still validate
    assert _valid_plex_art_src("http://plex:32400/library/metadata/9/thumb/1699")


def test_valid_plex_art_src_file_key_blocks_ssrf():
    # The ?url= on a file key must be a Plex provider URI, never an http(s) URL —
    # else the proxy could make Plex (with the re-minted admin token) fetch an
    # internal host. A file key without a valid provider ?url= is rejected.
    from backend.api.cl2k_maker import _valid_plex_art_src

    assert not _valid_plex_art_src(
        "http://plex:32400/library/metadata/1/file?url=http://169.254.169.254/latest"
    )
    assert not _valid_plex_art_src(
        "http://plex:32400/library/metadata/1/file?url=https%3A%2F%2Fevil.example%2Fx"
    )
    assert not _valid_plex_art_src("http://plex:32400/library/metadata/1/file")
    assert not _valid_plex_art_src(
        "http://plex:32400/library/metadata/1/file?url=%2Fetc%2Fpasswd"
    )


def test_plex_art_proxy_404_on_fetch_failure(monkeypatch):
    import backend.api.cl2k_maker as api
    from fastapi import HTTPException

    def _boom(src):
        raise ValueError("refusing to fetch image from disallowed host")

    monkeypatch.setattr(api, "download_image", _boom)
    with pytest.raises(HTTPException) as excinfo:
        api.plex_art_proxy(
            src="http://plex:32400/library/metadata/9/art/1", logger=_logger()
        )
    assert excinfo.value.status_code == 404


# --------------------------------------------------------------------------
# download() proxy-unwrap + redirect SSRF
# --------------------------------------------------------------------------


def test_unwrap_proxy_extracts_src():
    unwrap = image_fetch._unwrap_proxy
    assert (
        unwrap("/api/cl2k-maker/plex-art?src=http%3A%2F%2Fplex%3A32400%2Fx")
        == "http://plex:32400/x"
    )
    # ordinary paths / URLs pass through untouched
    assert unwrap("/t/p/original/x.jpg") == "/t/p/original/x.jpg"
    assert unwrap("https://image.tmdb.org/x.jpg") == "https://image.tmdb.org/x.jpg"


class _Resp:
    def __init__(self, *, redirect_to=None, content=b"img"):
        self.is_redirect = redirect_to is not None
        self.headers = {"Location": redirect_to} if redirect_to else {}
        self.content = content

    def raise_for_status(self):
        pass


class _Session:
    def __init__(self, responses):
        self._responses = list(responses)

    def get(self, url, timeout=None, allow_redirects=None):
        return self._responses.pop(0)


def test_download_blocks_redirect_to_disallowed_host(monkeypatch):
    monkeypatch.setattr(image_fetch, "_plex_netlocs", lambda: {"192.168.2.206:32400"})
    monkeypatch.setattr(image_fetch, "_with_plex_token", lambda u: u)
    sess = _Session([_Resp(redirect_to="http://169.254.169.254/latest/meta-data/")])
    with pytest.raises(ValueError, match="disallowed host"):
        image_fetch.download(
            "http://192.168.2.206:32400/library/metadata/9/art/1", session=sess
        )


def test_download_follows_redirect_to_allowed_host(monkeypatch):
    monkeypatch.setattr(image_fetch, "_plex_netlocs", lambda: {"192.168.2.206:32400"})
    monkeypatch.setattr(image_fetch, "_with_plex_token", lambda u: u)
    sess = _Session(
        [
            _Resp(redirect_to="https://image.tmdb.org/t/p/original/x.jpg"),
            _Resp(content=b"redirected-img"),
        ]
    )
    out = image_fetch.download(
        "http://192.168.2.206:32400/library/metadata/9/art/1", session=sess
    )
    assert out == b"redirected-img"
