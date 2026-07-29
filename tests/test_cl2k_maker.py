"""Tests for the CL2K maker module's logo-resolution gate.

The "too small to render crisply" rule (LOGO_MIN_WIDTH) must apply ONLY to a
logo the maker auto-sourced for the user (the TMDB/fanart fallback) — never to a
logo the user explicitly picked in the art picker. The live preview always
overlays the picked logo, so silently dropping it on save (the small
"The Tiny Chef Show" wordmarks) produced a poster that didn't match the preview.
"""

import types

import pytest

pytest.importorskip("wand.image")  # Wand + ImageMagick required (cl2k extra)

from wand.color import Color  # noqa: E402
from wand.image import Image  # noqa: E402

import backend.modules.cl2k_maker as maker  # noqa: E402


def _logo_png(width, height):
    """An opaque coloured logo of the given pixel size (content fills the canvas,
    so the trimmed width == ``width`` — what logo_is_usable measures)."""
    with Image(width=width, height=height, background=Color("red")) as img:
        img.format = "png"
        return img.make_blob()


def _backdrop_png():
    with Image(width=1000, height=1500, background=Color("#203040")) as img:
        img.format = "png"
        return img.make_blob()


@pytest.fixture
def env(monkeypatch):
    """A no-network _resolve_and_render harness: TMDB client is inert and every
    image download returns a sub-LOGO_MIN_WIDTH logo (340px wide)."""
    monkeypatch.setattr(maker, "TMDBClient", lambda *a, **k: object())
    monkeypatch.setattr(maker.image_fetch, "download", lambda *a, **k: _logo_png(340, 151))
    cfg = types.SimpleNamespace(
        language="en", text_logo_fallback=True, whiten_logo=False, text_logo_stroke=0
    )
    full_config = types.SimpleNamespace(cl2k_maker=cfg, tmdb=types.SimpleNamespace())
    logger = types.SimpleNamespace(
        debug=lambda *a, **k: None, info=lambda *a, **k: None, warning=lambda *a, **k: None
    )
    return full_config, logger


def test_explicit_small_logo_is_kept(env):
    """A logo the user picked (``logo_path`` supplied) survives even when it's
    narrower than LOGO_MIN_WIDTH — matching the preview that showed it."""
    full_config, logger = env
    _blob, info = maker._resolve_and_render(
        db=object(),
        full_config=full_config,
        logger=logger,
        kind="show",
        title="The Tiny Chef Show",
        tmdb_id=221230,
        backdrop_bytes=_backdrop_png(),
        logo_path="/iMuXNXkPq9OCKw5jljoIxkv8IRV.png",
    )
    assert info["logo_source"] == "tmdb"  # kept, not swapped for title text


def test_auto_sourced_small_logo_is_dropped(env, monkeypatch):
    """A logo the maker auto-selected (no ``logo_path`` given) is still rejected
    when too small — unchanged behaviour.

    ``text_logo_fallback`` is off so the drop yields ``logo_source="none"`` and no
    title wordmark is drawn: the wordmark path needs a real font, which the CI
    runner lacks (``resolve_font`` -> None). The gate decision is what's under
    test, not the text render.
    """
    full_config, logger = env
    full_config.cl2k_maker.text_logo_fallback = False
    monkeypatch.setattr(maker, "list_images", lambda *a, **k: {})
    monkeypatch.setattr(
        maker.image_fetch,
        "select_cl2k_inputs",
        lambda *a, **k: {"backdrop": None, "logo": "/auto-small.png"},
    )
    _blob, info = maker._resolve_and_render(
        db=object(),
        full_config=full_config,
        logger=logger,
        kind="show",
        title="The Tiny Chef Show",
        tmdb_id=221230,
        backdrop_bytes=_backdrop_png(),
        logo_path=None,
    )
    assert info["logo_source"] == "none"  # too small -> dropped (no fallback configured)


def test_a_successful_ai_extend_is_not_reframed_again(env, monkeypatch):
    """The AI-extended canvas is finished art — render it as-is.

    fit_extend_canvas has already applied zoom and v_pos to produce a full
    CANVAS_W x CANVAS_H canvas, and the AI filled the band below. Passing the
    same zoom/v_pos on to render_cl2k re-scales that finished image, and for
    v_pos > 0 (the ~0.4 headroom the docstring recommends) crops rows off its
    top and fades a black band over the fill the AI just generated.
    """
    full_config, logger = env
    monkeypatch.setattr(
        maker.renderer,
        "fit_extend_canvas",
        lambda *a, **k: (_backdrop_png(), b"mask"),
    )
    monkeypatch.setattr(maker.text_removal, "unavailable_reason", lambda *a, **k: None)
    monkeypatch.setattr(maker.text_removal, "remove_text", lambda *a, **k: _backdrop_png())
    seen = {}
    monkeypatch.setattr(maker, "render_cl2k", lambda **kw: seen.update(kw) or _backdrop_png())

    maker._resolve_and_render(
        db=object(),
        full_config=full_config,
        logger=logger,
        kind="show",
        title="The Tiny Chef Show",
        tmdb_id=221230,
        backdrop_bytes=_backdrop_png(),
        logo_path="/iMuXNXkPq9OCKw5jljoIxkv8IRV.png",
        fit_mode="extend",
        v_pos=0.4,
        zoom=1.5,
    )

    assert seen["fit_mode"] == "cover"
    assert seen["crop"] is None
    assert seen["v_pos"] == 0.0, "v_pos was already baked into the extended canvas"
    assert seen["zoom"] == 1.0, "zoom was already baked into the extended canvas"
