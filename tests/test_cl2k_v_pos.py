"""Tests for v_pos, the single vertical framing control.

v_pos absorbed focus_y, so it carries two obligations. It must reproduce the old
default exactly at 0 — every poster already made was framed at focus_y=0.5 with
v_pos=0, and a shifted centre would silently re-frame all of them. And its two
halves are deliberately asymmetric: down may edge-extend past the source because
that band lands in the CL2K gradient, up may not, because the top of the poster
is bright artwork with nothing to hide a fabricated band.
"""

import inspect

import pytest

pytest.importorskip("wand.image")  # Wand + ImageMagick required (cl2k extra)

from wand.color import Color  # noqa: E402
from wand.drawing import Drawing  # noqa: E402
from wand.image import Image  # noqa: E402

from backend.util.cl2k import geometry as geo  # noqa: E402
from backend.util.cl2k.renderer import (  # noqa: E402
    _cover_resize,
    _fit_resize,
    frame_backdrop,
)


def _banded(w, h, bands=15):
    """Full-width horizontal bands, so any vertical pan changes what's in frame."""
    with Image(width=w, height=h, background=Color("black")) as bg:
        with Drawing() as d:
            for i in range(bands):
                d.fill_color = Color(f"rgb({(i * 23) % 256},{(i * 41) % 256},{(i * 7) % 256})")
                d.rectangle(
                    left=0, top=int(i * h / bands), width=w - 1, height=int(h / bands) - 1
                )
            d(bg)
        return bg.make_blob("png")


def _framed(src, v_pos, zoom=1.0):
    """Framed result as a PIXEL signature.

    Not a hash of the PNG: ImageMagick stamps a tIME chunk into the output, so
    encoded bytes differ between two runs of identical work whenever they land on
    opposite sides of a second boundary. signature covers pixels only.
    """
    with Image(blob=_banded(*src)) as img:
        _cover_resize(img, geo.CANVAS_W, geo.CANVAS_H, 0.5, v_pos, zoom)
        return img.signature


@pytest.mark.parametrize("src", [(1920, 1080), (3840, 2160), (2560, 1080), (1000, 1600)])
def test_v_pos_zero_is_the_centred_crop(src):
    # The invariant the whole change rests on: 0 must mean what focus_y=0.5 +
    # v_pos=0 meant. Compared against the centre crop computed independently.
    with Image(blob=_banded(*src)) as img:
        scale = max(geo.CANVAS_W / img.width, geo.CANVAS_H / img.height)
        img.resize(round(img.width * scale), round(img.height * scale))
        left = max(0, min(round(0.5 * img.width - geo.CANVAS_W / 2), img.width - geo.CANVAS_W))
        top = max(0, min(round(0.5 * img.height - geo.CANVAS_H / 2), img.height - geo.CANVAS_H))
        img.crop(left, top, width=geo.CANVAS_W, height=geo.CANVAS_H)
        expected = img.signature
    assert _framed(src, 0.0) == expected


def test_v_pos_pans_down_past_the_source_into_the_gradient():
    # Downward is allowed to run out of source: the edge-extended band sits in the
    # CL2K gradient/black zone. A 16:9 backdrop has no source below the crop at
    # zoom 1, so this only moves at all because of that allowance.
    assert _framed((1920, 1080), 0.5) != _framed((1920, 1080), 0.0)
    assert _framed((1920, 1080), 1.0) != _framed((1920, 1080), 0.5)


def test_v_pos_up_is_source_bounded_not_fabricated():
    # A cover-filled 16:9 backdrop is exactly CANVAS_H tall, so there is nothing
    # above the crop. Up must clamp rather than invent a band at the top, where
    # no gradient could hide it.
    assert _framed((1920, 1080), -1.0) == _framed((1920, 1080), 0.0)


@pytest.mark.parametrize("v_pos", [-1.0, -0.5, 0.5, 1.0])
def test_v_pos_moves_both_ways_once_there_is_slack(v_pos):
    # Zoom creates real source on both sides, so the control is live in both
    # directions — the case Focus Y used to cover.
    assert _framed((1920, 1080), v_pos, zoom=1.5) != _framed((1920, 1080), 0.0, zoom=1.5)


def test_v_pos_is_clamped_to_the_declared_range():
    assert _framed((1920, 1080), 9.0) == _framed((1920, 1080), geo.V_POS_MAX)
    # Needs zoom: a cover-filled 16:9 is exactly CANVAS_H tall, so centre_top is 0
    # and every negative v_pos lands on top=0 with or without the clamp. At 1.5x
    # there is real source above the crop, so the clamp is the only thing stopping
    # -9 from panning straight past it.
    assert _framed((1920, 1080), -9.0, zoom=1.5) == _framed((1920, 1080), geo.V_POS_MIN, zoom=1.5)
    # No companion assertion for _v_pos_top: it clamps the resulting crop top to
    # [0, src_h - height] anyway, so deleting its v_pos clamp changes no output —
    # an assertion there would pass on the broken code and prove nothing.


def test_fit_mode_keeps_the_top_anchored_zero_to_one_scale():
    # v_pos is one control but not one scale: fit/extend ANCHOR the photo from the
    # top over 0..1, so negative names nothing there and floors to 0. The maker's
    # vertical slider narrows its range on those modes off the back of this, so a
    # change here silently turns half that slider back into a dead control.
    def fitted(v_pos):
        with Image(blob=_banded(1920, 1080)) as img:
            _fit_resize(img, geo.CANVAS_W, geo.CANVAS_H, None, v_pos, 1.0)
            return img.signature

    assert fitted(-1.0) == fitted(0.0)
    assert fitted(0.5) != fitted(0.0)


def test_frame_backdrop_no_longer_accepts_focus_y():
    # focus_y is retired; a caller still passing it should fail loudly rather
    # than have a silently ignored framing argument. Splatted, not written as a
    # literal keyword: a literal is a statically resolvable wrong-argument call
    # and CodeQL (py/call/wrong-named-argument) fails the run on it.
    retired = {"focus_y": 0.2}
    assert "focus_y" not in inspect.signature(frame_backdrop).parameters
    with pytest.raises(TypeError):
        frame_backdrop(backdrop_bytes=_banded(1920, 1080), **retired)
