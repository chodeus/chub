"""Tests for mirror, the horizontal artwork flip.

Where the flip lands IS the design. It is applied at the END of framing rather
than to the source bytes, because the AI text-removal mask and the extend
outpaint are both built in source space, and because the logo and label are
composited after the artwork. So mirror has to do exactly two things: flip the
artwork on every render path, and touch nothing else — a mirrored poster whose
season band reads backwards is the failure this file exists to catch.

It also has to survive the trip: the flag crosses four layers (request model ->
api endpoint -> module maker -> renderer), and a forward dropped anywhere shows
up only as "the toggle does nothing", so each hop is asserted.
"""

import base64
import types

import pytest

pytest.importorskip("httpx")
pytest.importorskip("wand.image")  # Wand + ImageMagick required (cl2k extra)

from fastapi import BackgroundTasks  # noqa: E402
from wand.color import Color  # noqa: E402
from wand.image import Image  # noqa: E402

import backend.api.cl2k_maker as api  # noqa: E402
import backend.modules.cl2k_maker as maker  # noqa: E402
from backend.util.cl2k import geometry as geo  # noqa: E402
from backend.util.cl2k.renderer import (  # noqa: E402
    frame_backdrop,
    render_cl2k,
    render_framed_art,
    render_square_art,
)


def _two_tone(w=1920, h=1080):
    """Left half red, right half blue — the flip has to swap the halves."""
    with Image(width=w, height=h, background=Color("red")) as bg:
        with Image(width=w // 2, height=h, background=Color("blue")) as right:
            bg.composite(right, left=w // 2, top=0)
        bg.format = "jpeg"
        return bg.make_blob()


def _sides(blob):
    """Sample colours 10% in from each edge, on the middle row."""
    with Image(blob=blob) as img:
        y = img.height // 2
        return img[int(img.width * 0.1), y], img[int(img.width * 0.9), y]


def _sig(blob, flop=False):
    """Pixel signature (not encoded bytes — ImageMagick stamps a PNG tIME chunk)."""
    with Image(blob=blob) as img:
        if flop:
            img.flop()
        return img.signature


def _strip(blob, top, height):
    """Raw RGB of one horizontal strip, for an exact same-pixels comparison."""
    with Image(blob=blob) as img:
        img.crop(0, top, width=img.width, height=height)
        return img.make_blob("RGB")


def _logger():
    return types.SimpleNamespace(
        info=lambda *a, **k: None,
        debug=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )


# --------------------------------------------------------------------------
# the flip itself
# --------------------------------------------------------------------------


@pytest.mark.parametrize("size", [(1920, 1080), (1000, 1000)], ids=["16:9", "1:1"])
def test_framed_art_mirror_swaps_the_sides(size):
    width, height = size
    kw = dict(backdrop_bytes=_two_tone(), width=width, height=height)
    plain_l, plain_r = _sides(render_framed_art(**kw))
    mirror_l, mirror_r = _sides(render_framed_art(**kw, mirror=True))

    assert plain_l.red > 0.9 and plain_r.blue > 0.9
    assert mirror_l.blue > 0.9 and mirror_r.red > 0.9


def test_square_art_forwards_mirror():
    left, right = _sides(render_square_art(backdrop_bytes=_two_tone(), mirror=True))
    assert left.blue > 0.9 and right.red > 0.9


def test_frame_backdrop_mirrors_the_poster_frame():
    # The .psd POSTER layer is this function's output, so an unmirrored frame here
    # would export a document that disagrees with the poster beside it.
    left, right = _sides(frame_backdrop(backdrop_bytes=_two_tone(), mirror=True))
    assert left.blue > 0.9 and right.red > 0.9


@pytest.mark.parametrize("fit_mode", ["cover", "fit"])
def test_mirror_composes_with_the_framing_it_does_not_replace_it(fit_mode):
    # Off-centre framing, so a flip applied to the SOURCE instead of the framed
    # result would land the crop window on the other side and fail this.
    # frame_backdrop returns PNG, so the comparison is lossless and exact.
    kw = dict(
        backdrop_bytes=_two_tone(),
        fit_mode=fit_mode,
        focus_x=0.2,
        v_pos=0.3,
        zoom=1.6,
    )
    assert _sig(frame_backdrop(**kw, mirror=True)) == _sig(frame_backdrop(**kw), flop=True)


def test_render_cl2k_mirrors_the_artwork_and_never_the_label():
    """The whole point of flipping at the end of framing: text stays readable."""
    kw = dict(
        backdrop_bytes=_two_tone(),
        kind="season",
        title="Mirror Test",
        season_text="Season one",
    )
    plain, mirrored = render_cl2k(**kw), render_cl2k(**kw, mirror=True)

    left, right = _sides(mirrored)
    assert left.blue > 0.9 and right.red > 0.9  # artwork flipped

    # Below the gradient's full-black row there is no artwork left, so every lit
    # pixel in this strip is typeset label. Identical pixels = the text did not flip.
    top = geo.GRADIENT_FULL_BLACK_Y + 20
    height = geo.CANVAS_H - geo.BORDER_WIDTH - 5 - top
    assert _strip(mirrored, top, height) == _strip(plain, top, height)
    # ...and the strip is genuinely asymmetric, or the line above proves nothing.
    with Image(blob=plain) as img:
        img.crop(0, top, width=img.width, height=height)
        with img.clone() as flipped:
            flipped.flop()
            assert flipped.signature != img.signature


# --------------------------------------------------------------------------
# the flag's trip through the layers
# --------------------------------------------------------------------------


_ENDPOINTS = [
    # (endpoint, the module function it must forward to, request model, takes BackgroundTasks)
    ("preview", "render_preview", api.GenerateRequest, False),
    ("generate", "generate_for_item", api.GenerateRequest, True),
    ("square_generate", "generate_square_art", api.SquareArtRequest, True),
    ("background_generate", "generate_background_art", api.BackgroundArtRequest, True),
    ("psd_export", "psd_for_item", api.GenerateRequest, False),
]


@pytest.mark.parametrize("route,target,model,tasks", _ENDPOINTS, ids=[e[0] for e in _ENDPOINTS])
def test_an_endpoint_forwards_mirror_to_its_maker(route, target, model, tasks, monkeypatch):
    seen = {}
    monkeypatch.setattr(api, "load_config", object)
    # The save routes shape a result dict; the render routes return bytes.
    # *a: render_preview takes db/config/logger positionally.
    out = {"status": "generated"} if tasks else b"blob"
    monkeypatch.setattr(api, target, lambda *a, **kw: (seen.update(kw), out)[1])
    req = model(kind="movie", title="T", tmdb_id=7, mirror=True)
    extra = {"background_tasks": BackgroundTasks()} if tasks else {}

    getattr(api, route)(req, db=object(), logger=_logger(), **extra)

    # Split, because these endpoints answer a raising stub with a clean 4xx —
    # "never called" would otherwise read as "called without mirror".
    assert seen, f"{route} never reached {target}"
    assert seen.get("mirror") is True, f"{route} dropped mirror on the way to {target}"


@pytest.mark.parametrize("route,model", [("square_preview", api.SquareArtRequest),
                                         ("background_preview", api.BackgroundArtRequest)])
def test_an_art_preview_forwards_mirror_to_the_renderer(route, model, monkeypatch):
    seen = {}
    target = "render_square_art" if route == "square_preview" else "render_framed_art"
    monkeypatch.setattr(api, target, lambda **kw: (seen.update(kw), b"jpeg")[1])
    req = model(kind="movie", title="T", tmdb_id=7, backdrop_b64="", mirror=True)
    monkeypatch.setattr(api, "_source_art_bytes", lambda _req: b"ART")

    getattr(api, route)(req, db=object(), logger=_logger())

    assert seen.get("mirror") is True


def test_the_seasons_job_carries_mirror_into_every_season(monkeypatch):
    seen = {}
    monkeypatch.setattr(api, "load_config", object)
    monkeypatch.setattr(
        api, "generate_seasons", lambda **kw: (seen.update(kw), {"status": "ok"})[1]
    )
    req = api.SeasonsRequest(title="T", tmdb_id=7, seasons=[1], mirror=True)

    api._run_seasons_job(api._new_season_job(1, "T"), object(), _logger(), req)

    assert seen.get("mirror") is True


@pytest.mark.parametrize(
    "maker_fn,renderer_fn",
    [
        ("generate_square_art", "render_square_art"),
        ("generate_background_art", "render_framed_art"),
    ],
)
def test_an_asset_maker_forwards_mirror_to_the_renderer(maker_fn, renderer_fn, monkeypatch):
    seen = {}
    monkeypatch.setattr(maker, "_backfill_title_year", lambda *a, **kw: ("T", 2024))
    monkeypatch.setattr(maker, "_persist_poster", lambda *a, **kw: {"status": "ok"})
    monkeypatch.setattr(
        maker.renderer, renderer_fn, lambda **kw: (seen.update(kw), b"jpeg")[1]
    )

    getattr(maker, maker_fn)(
        db=object(),
        full_config=types.SimpleNamespace(cl2k_maker=object(), sync_gdrive=None),
        logger=_logger(),
        kind="movie",
        title="T",
        tmdb_id=7,
        backdrop_bytes=b"ART",
        mirror=True,
    )

    assert seen.get("mirror") is True


def test_resolve_and_render_forwards_mirror_to_the_poster_renderer(monkeypatch):
    seen = {}
    monkeypatch.setattr(maker, "TMDBClient", lambda *a, **k: object())
    monkeypatch.setattr(maker, "_resolve_default_art", lambda *a, **kw: (None, None))
    monkeypatch.setattr(maker, "render_cl2k", lambda **kw: (seen.update(kw), b"jpeg")[1])

    maker._resolve_and_render(
        object(),
        types.SimpleNamespace(
            cl2k_maker=types.SimpleNamespace(
                language="en",
                whiten_logo=True,
                text_logo_fallback=True,
                text_logo_stroke=0,
            ),
            tmdb=None,
        ),
        _logger(),
        kind="movie",
        title="T",
        tmdb_id=7,
        backdrop_bytes=b"ART",
        custom_logo_bytes=b"LOGO",
        mirror=True,
    )

    assert seen.get("mirror") is True


def test_generate_seasons_carries_mirror_into_each_poster(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        maker, "generate_for_item", lambda **kw: (seen.update(kw), {"status": "ok"})[1]
    )

    maker.generate_seasons(
        db=object(),
        full_config=object(),
        logger=_logger(),
        title="T",
        tmdb_id=7,
        seasons=[1],
        mirror=True,
    )

    assert seen.get("mirror") is True


@pytest.mark.parametrize(
    "model",
    [api.GenerateRequest, api.SquareArtRequest, api.BackgroundArtRequest, api.SeasonsRequest],
)
def test_mirror_is_off_unless_asked_for(model):
    # Every poster ever made was rendered without this flag; a truthy default
    # would silently flip the lot on the next re-render.
    extra = {"seasons": [1]} if model is api.SeasonsRequest else {"kind": "movie"}
    assert model(title="T", tmdb_id=7, **extra).mirror is False


def test_a_mirror_request_returns_mirrored_art_over_http(monkeypatch):
    """The whole stack in one shot: JSON on the wire -> pydantic -> endpoint ->
    maker -> renderer -> flipped pixels. The unit tests above each cover one hop;
    this is the one that would catch a model that quietly drops the field."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    cfg = types.SimpleNamespace(
        cl2k_maker=types.SimpleNamespace(
            language="en",
            whiten_logo=True,
            text_logo_fallback=False,
            text_logo_stroke=0,
        ),
        tmdb=None,
    )
    monkeypatch.setattr(api, "load_config", lambda: cfg)
    monkeypatch.setattr(maker, "TMDBClient", lambda *a, **k: object())
    monkeypatch.setattr(maker, "_resolve_default_art", lambda *a, **kw: (None, None))
    monkeypatch.setattr(maker, "_fanart_logo", lambda *a, **kw: None)  # no network

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_cl2k_logger] = _logger
    app.dependency_overrides[api.get_database] = object
    client = TestClient(app)

    body = {
        "kind": "movie",
        "title": "T",
        "tmdb_id": 7,
        "backdrop_b64": base64.b64encode(_two_tone()).decode(),
        "place_logo": False,
    }
    plain = client.post("/api/cl2k-maker/preview", json=body)
    mirrored = client.post("/api/cl2k-maker/preview", json={**body, "mirror": True})

    assert (plain.status_code, mirrored.status_code) == (200, 200)
    assert _sides(plain.content)[0].red > 0.9  # unmirrored: red on the left
    left, right = _sides(mirrored.content)
    assert left.blue > 0.9 and right.red > 0.9
