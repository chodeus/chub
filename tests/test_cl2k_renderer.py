"""Tests for the CL2K renderer's logo pipeline and framed-art rendering.

Covers the highest-churn pieces with synthetic fixtures (no network):
* two-tone whiten — saturated fills go white, dark keylines stay black, and a
  mostly-dark logo falls back to the flat white silhouette;
* logo_scale — the slider multiplies the guide-fit box past the 600px width
  guide, clamped by the canvas;
* the B/W touch-up flip — brushed regions invert, everything else untouched;
* render_framed_art — exact canvas dims + letterboxing in fit mode;
* JPEG encoding — progressive scan + embedded ICC on the framed-art output;
* PSD export parity — the POSTER layer equals renderer.frame_backdrop's
  framing pixel-for-pixel, and the LOGO layer honours logo_scale.
"""

import io

import pytest

pytest.importorskip("wand.image")  # Wand + ImageMagick required (cl2k extra)

from wand.color import Color  # noqa: E402
from wand.drawing import Drawing  # noqa: E402
from wand.image import Image  # noqa: E402

from backend.util.cl2k.renderer import (  # noqa: E402
    _place_logo,
    frame_backdrop,
    process_logo,
    render_framed_art,
)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def _png(width, height, draw_fn):
    with Image(width=width, height=height, background=Color("transparent")) as img:
        with Drawing() as d:
            draw_fn(d)
            d(img)
        img.format = "png"
        return img.make_blob()


def _colored_logo():
    """A saturated fill inside a black keyline plate — the two-tone fixture."""

    def draw(d):
        d.fill_color = Color("black")
        d.rectangle(left=0, top=0, width=599, height=199)
        d.fill_color = Color("red")
        d.rectangle(left=30, top=30, width=540, height=140)

    return _png(600, 200, draw)


def _solid_logo(color, w=2000, h=300):
    def draw(d):
        d.fill_color = Color(color)
        d.rectangle(left=0, top=0, width=w - 1, height=h - 1)

    return _png(w, h, draw)


def _backdrop(color="#27408b", w=1920, h=1080):
    with Image(width=w, height=h, background=Color(color)) as bg:
        bg.format = "jpeg"
        return bg.make_blob()


def _placed_size(logo_bytes, scale, max_width=600):
    """Place on a black canvas and measure the placed logo's trimmed bounds."""
    with Image(width=1000, height=1500, background=Color("black")) as canvas:
        _place_logo(canvas, logo_bytes, 1352, max_width, True, scale, 0)
        canvas.trim(color=Color("black"))
        return canvas.width, canvas.height


# --------------------------------------------------------------------------
# two-tone whiten
# --------------------------------------------------------------------------


def test_whiten_two_tone_keeps_keylines():
    png, w, h = process_logo(_colored_logo(), whiten=True)
    with Image(blob=png) as img:
        center = img[w // 2, h // 2]  # saturated fill -> white
        edge = img[5, h // 2]  # keyline plate -> black
        assert (center.red, center.green, center.blue) == (1.0, 1.0, 1.0)
        assert (edge.red, edge.green, edge.blue) == (0.0, 0.0, 0.0)


def test_whiten_dark_logo_falls_back_to_flat_white():
    png, w, h = process_logo(_solid_logo("#181818", w=400, h=100), whiten=True)
    with Image(blob=png) as img:
        center = img[w // 2, h // 2]
        assert (center.red, center.green, center.blue) == (1.0, 1.0, 1.0)


def test_whiten_off_keeps_original_colors():
    png, w, h = process_logo(_colored_logo(), whiten=False)
    with Image(blob=png) as img:
        center = img[w // 2, h // 2]
        assert center.red > 0.9 and center.green < 0.1  # still red


# --------------------------------------------------------------------------
# logo_scale — the guide-fit box multiplies past the width guides (the
# 600/700/800 lines are guidelines, not limits; only the canvas clamps)
# --------------------------------------------------------------------------


def test_logo_scale_default_fits_the_600_guide():
    w, h = _placed_size(_solid_logo("white"), 1.0)
    assert w == 600 and h == 90


def test_logo_scale_enlarges_past_the_width_guides():
    w, h = _placed_size(_solid_logo("white"), 1.5)
    assert (w, h) == (900, 135)


def test_logo_scale_is_canvas_clamped():
    w, h = _placed_size(_solid_logo("white"), 3.0)
    assert w == 1000  # the 1000px canvas is the only cap


# --------------------------------------------------------------------------
# B/W touch-up flip
# --------------------------------------------------------------------------


def test_flip_mask_inverts_only_the_brushed_region():
    base, w, h = process_logo(_solid_logo("white", w=600, h=200), whiten=True)

    # display-resolution mask (half size): a white box over the left third
    def draw(d):
        d.fill_color = Color("white")
        d.rectangle(left=0, top=0, width=(w // 2) // 3, height=h // 2 - 1)

    mask = _png(w // 2, h // 2, draw)
    flipped, w2, h2 = process_logo(
        _solid_logo("white", w=600, h=200), whiten=True, flip_mask_bytes=mask
    )
    assert (w2, h2) == (w, h)
    with Image(blob=flipped) as img:
        left = img[w // 6, h // 2]  # brushed -> flipped to black
        right = img[w - 10, h // 2]  # untouched -> still white
        assert (left.red, left.green, left.blue) == (0.0, 0.0, 0.0)
        assert (right.red, right.green, right.blue) == (1.0, 1.0, 1.0)


# --------------------------------------------------------------------------
# framed art (square / background makers)
# --------------------------------------------------------------------------


def test_render_framed_art_dims_and_format():
    blob = render_framed_art(backdrop_bytes=_backdrop(), width=1920, height=1080)
    with Image(blob=blob) as img:
        assert (img.width, img.height, img.format) == (1920, 1080, "JPEG")


def test_render_framed_art_fit_letterboxes_on_black():
    # A square source contained in a 16:9 frame leaves black pillarboxes.
    blob = render_framed_art(
        backdrop_bytes=_backdrop(w=500, h=500), width=1920, height=1080, fit_mode="fit"
    )
    with Image(blob=blob) as img:
        bar = img[10, 540]  # left pillarbox
        center = img[960, 540]  # source content
        assert bar.red < 0.05 and bar.green < 0.05 and bar.blue < 0.05
        assert center.blue > 0.3  # the navy source


def test_encoder_is_progressive_with_icc():
    blob = render_framed_art(backdrop_bytes=_backdrop(), width=1920, height=1080)
    assert blob[:2] == b"\xff\xd8"  # JPEG SOI
    assert b"\xff\xc2" in blob  # SOF2 = progressive scan
    assert b"ICC_PROFILE" in blob[:65536]  # embedded sRGB profile


# --------------------------------------------------------------------------
# PSD export parity
# --------------------------------------------------------------------------


def test_psd_poster_layer_matches_renderer_framing():
    pytest.importorskip("psd_tools")
    from PIL import Image as PILImage
    from PIL import ImageChops
    from psd_tools import PSDImage

    from backend.util.cl2k.psd_export import export_psd

    framed = frame_backdrop(
        backdrop_bytes=_backdrop(), fit_mode="fit", v_pos=0.2, zoom=1.4
    )
    blob = export_psd(backdrop_bytes=framed, kind="movie", title="X")
    psd = PSDImage.open(io.BytesIO(blob))
    poster = next(la for la in psd if la.name == "POSTER").topil().convert("RGB")
    ref = PILImage.open(io.BytesIO(framed)).convert("RGB")
    assert poster.size == ref.size == (1000, 1500)
    assert ImageChops.difference(poster, ref).getbbox() is None  # pixel-identical


def test_psd_logo_layer_honours_logo_scale():
    pytest.importorskip("psd_tools")
    from psd_tools import PSDImage

    from backend.util.cl2k.psd_export import export_psd

    framed = frame_backdrop(backdrop_bytes=_backdrop())
    sizes = {}
    for scale in (1.0, 1.25):
        blob = export_psd(
            backdrop_bytes=framed,
            kind="movie",
            logo_bytes=_solid_logo("white"),
            logo_scale=scale,
        )
        psd = PSDImage.open(io.BytesIO(blob))
        layer = next(la for la in psd if la.name == "LOGO").topil()
        bb = layer.getbbox()
        sizes[scale] = (bb[2] - bb[0], bb[3] - bb[1], bb[3])
    # default box is the 700px recommended guide width; the slider may take it
    # past the 800px guide line (guidelines, not limits)
    assert sizes[1.0][:2] == (700, 105)
    assert sizes[1.25][:2] == (875, 131)
    # bottom stays pinned to the template's y=1352 "Main Logo Bottom" guide
    assert sizes[1.0][2] == sizes[1.25][2] == 1352


# --------------------------------------------------------------------------
# AI mask normalization (text_removal)
# --------------------------------------------------------------------------


def test_mask_resized_to_image_dims():
    """A display-resolution brush mask is normalized to the image's pixel size
    before any provider call (LaMa/HF don't resize server-side)."""
    import io as _io

    from PIL import Image as PILImage

    from backend.util.cl2k.text_removal import _mask_to_image_dims

    def _png_bytes(im):
        buf = _io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()

    image = _png_bytes(PILImage.new("RGB", (1920, 1080)))
    mask = _png_bytes(PILImage.new("L", (480, 270), 255))
    out = _mask_to_image_dims(image, mask)
    assert PILImage.open(_io.BytesIO(out)).size == (1920, 1080)
    # already-matching masks pass through untouched
    same = _png_bytes(PILImage.new("L", (1920, 1080), 255))
    assert _mask_to_image_dims(image, same) is same
