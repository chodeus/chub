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

from backend.util.cl2k import geometry as geo  # noqa: E402
from backend.util.cl2k.renderer import (  # noqa: E402
    _place_logo,
    frame_backdrop,
    logo_is_usable,
    process_logo,
    render_cl2k,
    render_framed_art,
)

# _solid_logo's default source dimensions — the shape auto_logo_size reads.
_LOGO_SRC = (2000, 300)


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


def _plate_logo():
    """A white sticker plate with black 'text' — the invert-logo fixture."""

    def draw(d):
        d.fill_color = Color("white")
        d.rectangle(left=0, top=0, width=599, height=199)
        d.fill_color = Color("black")
        d.rectangle(left=100, top=60, width=400, height=80)

    return _png(600, 200, draw)


def test_invert_turns_plate_into_clearlogo():
    # White plate + black text, whitened then inverted: the text region comes
    # out opaque white, the plate fully transparent (darkness = opacity).
    png, w, h = process_logo(_plate_logo(), whiten=True, invert=True)
    with Image(blob=png) as img:
        text = img[w // 2, h // 2]  # inside the black rectangle
        plate = img[20, 20]  # plate corner, far from the text
        assert text.alpha > 0.95
        assert (text.red, text.green, text.blue) == (1.0, 1.0, 1.0)
        assert plate.alpha < 0.05


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
# logo trim — invisible alpha must not push the visible artwork off-centre
# --------------------------------------------------------------------------


def _logo_with_side_glow(glow_alpha, ink=1000, pad=200, tail=400):
    """White ink block plus a one-sided block at ``glow_alpha`` on its right.

    ``glow_alpha=0`` draws no block at all. The asymmetry is the point: a trim
    that keeps the block centres the *box*, which puts the visible ink left of
    the canvas centre by half the block's width.
    """

    def draw(d):
        if glow_alpha:
            d.fill_color = Color(f"rgba(255,255,255,{glow_alpha / 255:.6f})")
            d.rectangle(left=pad + ink, top=0, width=tail - 1, height=299)
        d.fill_color = Color("white")
        d.rectangle(left=pad, top=60, width=ink - 1, height=179)

    return _png(pad + ink + tail, 300, draw)


def _visible_ink_offset(logo_bytes):
    """Centre-offset (px) of the placed logo's *visible* ink from canvas centre."""
    with Image(width=1000, height=1500, background=Color("black")) as canvas:
        _place_logo(canvas, logo_bytes, geo.MAIN_LOGO_BOTTOM, None, False)
        blob = canvas.make_blob("png")
    with Image(blob=blob) as flat:
        with flat.clone() as probe:
            probe.transform_colorspace("gray")
            probe.threshold(200 / 255)
            probe.background_color = Color("black")
            probe.trim(color=Color("black"))
            left, width = probe.page_x, probe.width
    return (left + (width - 1) / 2) - (geo.CANVAS_W - 1) / 2


@pytest.mark.parametrize("glow_alpha", [0, 1, 5, geo.LOGO_TRIM_ALPHA])
def test_subvisible_alpha_does_not_shift_the_logo(glow_alpha):
    # <=LOGO_TRIM_ALPHA is invisible padding: the ink stays centred. The 0.5px
    # tolerance is the unavoidable half-pixel when the placed width is odd.
    assert abs(_visible_ink_offset(_logo_with_side_glow(glow_alpha))) <= 0.5


def test_visible_glow_is_kept_as_part_of_the_logo():
    # A glow the eye CAN see is design, not padding — it stays inside the box, so
    # the ink is deliberately off-centre. Guards against over-trimming.
    assert _visible_ink_offset(_logo_with_side_glow(64)) < -50


def test_all_subvisible_logo_is_left_uncropped():
    # Nothing above the threshold. ImageMagick trims a uniform image to 1x1
    # rather than to nothing, so a size check alone would crop the logo to a
    # single pixel while the Pillow PSD path (None bbox) left it whole.
    def draw(d):
        d.fill_color = Color(f"rgba(255,255,255,{geo.LOGO_TRIM_ALPHA / 255:.6f})")
        d.rectangle(left=100, top=50, width=699, height=199)

    blob = _png(900, 300, draw)
    _png_bytes, w, h = process_logo(blob, whiten=False)
    assert (w, h) == (900, 300)


def test_trim_agrees_across_the_renderer_entry_points():
    # process_logo (frontend overlay + brush space), logo_is_usable (the
    # too-small gate) and _place_logo must measure the same box.
    logo = _logo_with_side_glow(1)
    _, w, _h = process_logo(logo, whiten=False)
    assert w == 1000  # the invisible tail is gone, not 1400
    assert logo_is_usable(logo, min_width=1000)
    assert not logo_is_usable(logo, min_width=1001)


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


def test_render_cl2k_svg_logo_never_crashes():
    """An SVG clear logo must never 500 the render (the deployed ImageMagick has
    no SVG delegate, and select_logo prefers SVG). When cairosvg is available the
    SVG is rasterized and used; when it isn't, render falls back to the typeset
    wordmark. Either path returns valid JPEG bytes rather than raising Wand's
    'no decode delegate for SVG'."""
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="200">'
        b'<rect width="800" height="200" fill="white"/></svg>'
    )
    blob = render_cl2k(
        backdrop_bytes=_backdrop(), kind="movie", logo_bytes=svg, title="Dune"
    )
    assert blob[:2] == b"\xff\xd8"  # JPEG SOI — rendered, did not crash


# --------------------------------------------------------------------------
# PSD export parity
# --------------------------------------------------------------------------


def _psd_layer_image(psd, name):
    """Full-canvas RGBA of the named layer; descends into the creator-style
    groups (POSTER>Main, LOGO>Layer 1) the live export writes."""
    layer = next(la for la in psd if la.name == name)
    return layer.composite(viewport=(0, 0, psd.width, psd.height))


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
    poster = _psd_layer_image(psd, "POSTER").convert("RGB")
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
        layer = _psd_layer_image(psd, "LOGO")
        bb = layer.getbbox()
        sizes[scale] = (bb[2] - bb[0], bb[3] - bb[1], bb[3])
    # The default box is now sized from the logo's own shape
    # (geometry.auto_logo_size) rather than a flat 700px guide, so assert the
    # contract this test is actually about: the slider scales that box, and the
    # slider may take it past the 800px guide line (guidelines, not limits).
    base_w, base_h = geo.auto_logo_size(*_LOGO_SRC, geo.MAIN_LOGO_BOTTOM)
    assert sizes[1.0][:2] == (base_w, base_h)
    assert sizes[1.25][0] == round(base_w * 1.25)
    assert sizes[1.25][0] > sizes[1.0][0]
    # aspect ratio survives the scale
    assert abs(sizes[1.25][0] / sizes[1.25][1] - base_w / base_h) < 0.05
    # bottom stays pinned to the template's y=1352 "Main Logo Bottom" guide
    assert sizes[1.0][2] == sizes[1.25][2] == 1352


@pytest.mark.parametrize(
    "glow_alpha, tail_kept",
    [(geo.LOGO_TRIM_ALPHA, False), (geo.LOGO_TRIM_ALPHA + 1, True)],
)
def test_psd_logo_layer_trims_like_the_renderer(glow_alpha, tail_kept):
    # The PSD path has its own Pillow bbox, so it can drift from the Wand
    # renderer's threshold. Straddle LOGO_TRIM_ALPHA and require both to agree.
    pytest.importorskip("psd_tools")
    from psd_tools import PSDImage

    from backend.util.cl2k.psd_export import export_psd

    logo = _logo_with_side_glow(glow_alpha)
    blob = export_psd(
        backdrop_bytes=frame_backdrop(backdrop_bytes=_backdrop()),
        kind="movie",
        logo_bytes=logo,
        whiten=False,
    )
    psd = PSDImage.open(io.BytesIO(blob))
    layer = _psd_layer_image(psd, "LOGO").convert("RGBA")
    # Bbox of the OPAQUE ink only — the layer bbox would include a kept glow.
    ink = layer.getchannel("A").point(lambda v: 255 if v > 128 else 0).getbbox()
    psd_centre = (ink[0] + ink[2] - 1) / 2 - (geo.CANVAS_W - 1) / 2

    _, process_w, _h = process_logo(logo, whiten=False)
    assert (process_w == 1400) is tail_kept  # 1000 ink + 400 tail

    if tail_kept:
        assert psd_centre < -50  # visible glow kept -> ink deliberately left
    else:
        assert abs(psd_centre) <= 0.5
    # and the PSD layer lands where the renderer puts it
    assert abs(psd_centre - _visible_ink_offset(logo)) <= 1.0


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
    resized = PILImage.open(_io.BytesIO(out)).size
    assert resized == (1920, 1080)
    # already-matching masks pass through untouched
    same = _png_bytes(PILImage.new("L", (1920, 1080), 255))
    assert _mask_to_image_dims(image, same) is same


# --------------------------------------------------------------------------
# BORDER LAYER parity with CL2K_template.psd
#
# The frame shipped 27px on the top/left and 26px on the bottom/right for months
# because nothing asserted it: ImageMagick's rectangle primitive is inclusive of
# both corners, so width=bw paints bw+1 px, and only the far edges clipped the
# extra one. Downstream border-strip passes then cropped a symmetric width and
# left a 1px white line behind. These lock the geometry and the inner glow.
# --------------------------------------------------------------------------


def _white_run(values):
    n = 0
    for v in values:
        if v < 250:
            break
        n += 1
    return n


def _bordered_gray():
    """A mid-grey canvas with the real border drawn on it, as a numpy L array."""
    import numpy as np
    from PIL import Image as PILImage

    from backend.util.cl2k.renderer import _draw_border

    with Image(width=geo.CANVAS_W, height=geo.CANVAS_H, background=Color("gray50")) as im:
        _draw_border(im)
        im.format = "png"
        blob = im.make_blob()
    return np.asarray(PILImage.open(io.BytesIO(blob)).convert("L")).astype(int)


def test_border_is_symmetric_and_matches_the_psd_stroke():
    arr = _bordered_gray()
    row, col = arr[geo.CANVAS_H // 2, :], arr[:, geo.CANVAS_W // 2]
    assert _white_run(row) == geo.BORDER_WIDTH  # left
    assert _white_run(row[::-1]) == geo.BORDER_WIDTH  # right
    assert _white_run(col) == geo.BORDER_WIDTH  # top
    assert _white_run(col[::-1]) == geo.BORDER_WIDTH  # bottom
    assert geo.BORDER_WIDTH == 25  # PSD FrFX Stroke, Style=Inside, Size=25px


def test_inner_glow_darkens_inward_from_the_stroke():
    arr = _bordered_gray()
    row = arr[geo.CANVAS_H // 2, :]
    bw, reach = geo.BORDER_WIDTH, geo.GLOW_REACH
    # Darkest against the stroke, brightening inward, gone by GLOW_REACH.
    assert row[bw] < row[bw + 5] < row[bw + 12] < row[reach - 1]
    assert row[bw] < 128  # the glow really does cut the mid-grey down
    interior = row[reach + 20]
    assert abs(int(row[reach]) - int(interior)) <= 2  # fully faded by 48px in
    # symmetric on the opposite edge
    assert abs(int(row[bw]) - int(row[-bw - 1])) <= 2


def test_gradient_matches_the_template_endpoints():
    import numpy as np
    from PIL import Image as PILImage

    alpha = np.asarray(PILImage.open(geo.GRADIENT_PNG).convert("RGBA"))[:, 500, 3]
    # Clear through the artwork, opaque by the template's "Gradient Darkest" guide.
    assert alpha[geo.GRADIENT_START_Y - 1] == 0
    assert alpha[geo.GRADIENT_START_Y] > 0
    assert alpha[geo.GRADIENT_FULL_BLACK_Y] == 255
    assert (np.diff(alpha.astype(int)) >= 0).all()  # monotonic
    # The pre-2026-07 substitute ramp started ~240px higher; guard the regression.
    assert alpha[1000] == 0
    assert geo.GRADIENT_START_Y > 1000


def test_artwork_is_full_bleed_under_the_frame():
    """The template's POSTER group is (0,0,1000,1500) — art runs under an INSIDE
    stroke rather than being inset to fit within it."""
    import numpy as np
    from PIL import Image as PILImage

    framed = frame_backdrop(backdrop_bytes=_backdrop())
    arr = np.asarray(PILImage.open(io.BytesIO(framed)).convert("RGB")).astype(int)
    assert arr.shape[:2] == (geo.CANVAS_H, geo.CANVAS_W)
    assert not (arr > 250).all(axis=2).any()  # no white margin anywhere


def test_label_tracking_follows_the_template_not_string_length():
    """Only COMPLETE LIMITED SERIES is tracked 600; every season label is 800 —
    including the spelled-out ones that a >16-character rule caught by mistake."""
    assert geo.label_tracking("SEASON ONE") == geo.LABEL_TRACKING
    assert geo.label_tracking("SEASON FIFTY-NINE") == geo.LABEL_TRACKING
    assert geo.label_tracking("SPECIALS") == geo.LABEL_TRACKING
    assert geo.label_tracking("COLLECTION") == geo.LABEL_TRACKING
    assert geo.label_tracking("COMPLETE LIMITED SERIES") == geo.LABEL_TRACKING_LONG


# --------------------------------------------------------------------------
# live (editable) PSD structure — effects, gradient fill, type layer, preview
# --------------------------------------------------------------------------


def _live_psd(**kwargs):
    pytest.importorskip("psd_tools")
    from psd_tools import PSDImage

    from backend.util.cl2k.psd_export import export_psd

    blob = export_psd(
        backdrop_bytes=frame_backdrop(backdrop_bytes=_backdrop()), **kwargs
    )
    return PSDImage.open(io.BytesIO(blob)), blob


def test_psd_border_layer_carries_live_effects():
    psd, _ = _live_psd(kind="movie", logo_bytes=_solid_logo("white"))
    border = next(la for la in psd if la.name == "BORDER LAYER")
    fx = {e.__class__.__name__: e.enabled for e in border.effects}
    assert fx == {"Stroke": True, "InnerGlow": True}
    from psd_tools.constants import Tag

    assert border.tagged_blocks.get_data(Tag.BLEND_FILL_OPACITY) == 0
    lfx2 = border.tagged_blocks.get_data(Tag.OBJECT_BASED_EFFECTS_LAYER_INFO)
    stroke, glow = lfx2[b"FrFX"], lfx2[b"IrGl"]
    # present=True is load-bearing: without it readers report zero effects
    assert stroke[b"present"].value and glow[b"present"].value
    assert stroke[b"Sz  "].value == float(geo.BORDER_WIDTH)
    assert stroke[b"Styl"].enum == b"InsF"
    assert (glow[b"Ckmt"].value, glow[b"blur"].value) == (50.0, 45.0)


def test_psd_gradient_is_a_live_fill_layer():
    psd, _ = _live_psd(kind="movie", logo_bytes=_solid_logo("white"))
    grad = next(
        la for g in psd if g.is_group() and g.name == "GRADIENT" for la in g
    )
    assert grad.kind == "gradientfill"
    from psd_tools.constants import Tag

    gd = grad.tagged_blocks.get_data(Tag.GRADIENT_FILL_SETTING)
    assert (gd[b"Angl"].value, gd[b"Scl "].value) == (90.0, 30.0)
    stops = [
        (float(t[b"Opct"].value), int(t[b"Lctn"].value))
        for t in gd[b"Grad"][b"Trns"]
    ]
    # the template's own opacity stops — these are what put first-alpha at
    # y=1037 and full black at y=1374 when Photoshop rasterises the fill
    assert stops == [(100.0, 819), (0.0, 3909)]


def test_psd_label_is_an_editable_type_layer():
    psd, _ = _live_psd(
        kind="season", logo_bytes=_solid_logo("white"), season_text="Season three"
    )
    label = next(la for la in psd if la.kind == "type")
    assert label.text.rstrip("\r") == "SEASON THREE"
    from psd_tools.constants import Tag

    tysh = label.tagged_blocks.get_data(Tag.TYPE_TOOL_OBJECT_SETTING)
    engine = tysh.text_data[b"EngineData"].value["EngineDict"]
    style = engine["StyleRun"]["RunArray"][0]["StyleSheet"]["StyleSheetData"]
    assert int(style["Tracking"].value) == geo.label_tracking("SEASON THREE")
    assert float(style["FontSize"].value) == float(geo.LABEL_FONT_PX)
    # run lengths must cover text + trailing \r or Photoshop mis-parses runs
    for run in ("StyleRun", "ParagraphRun"):
        assert int(engine[run]["RunLengthArray"][0].value) == len("SEASON THREE") + 1
    # anchor pre-compensates centre-justification's tracking bias
    expected_tx = geo.CENTER_X - geo.label_tracking("SEASON THREE") * geo.LABEL_FONT_PX / 2000.0
    assert abs(tysh.transform[4] - expected_tx) < 0.01
    assert tysh.transform[5] == 1451.0


def test_psd_embedded_preview_is_the_flat_composite():
    # psd-tools cannot render the live effects, so the preview MUST be the
    # injected flat composite — not a recomposite (which would be garbage).
    psd, blob = _live_psd(kind="movie", logo_bytes=_solid_logo("white"))
    assert psd.has_preview()
    preview = psd.topil().convert("RGB")
    left = preview.getpixel((2, 750))
    top = preview.getpixel((500, 2))
    assert left == (255, 255, 255) and top == (255, 255, 255)  # border painted
    inside = preview.getpixel((500, 500))
    assert inside != (255, 255, 255)  # artwork, not a blown-out recomposite
    # and PIL parses the file independently of psd-tools
    from PIL import Image as PILImage

    with PILImage.open(io.BytesIO(blob)) as pil:
        assert pil.format == "PSD" and pil.size == (1000, 1500)


def test_psd_label_falls_back_to_raster_without_the_donor(monkeypatch, tmp_path):
    # The donor TySh asset is a committed derivative; a build without it must
    # still export — the label just stays a plain pixel layer instead of type.
    pytest.importorskip("psd_tools")
    from psd_tools import PSDImage

    from backend.util.cl2k import psd_live
    from backend.util.cl2k.psd_export import export_psd

    monkeypatch.setattr(psd_live, "LABEL_TYSH_BIN", tmp_path / "missing.bin")
    monkeypatch.setattr(psd_live, "_DONOR_CACHE", {})
    blob = export_psd(
        backdrop_bytes=frame_backdrop(backdrop_bytes=_backdrop()),
        kind="season",
        logo_bytes=_solid_logo("white"),
        season_text="Season three",
    )
    psd = PSDImage.open(io.BytesIO(blob))
    label = next(la for la in psd if la.name == "SEASON THREE")
    assert label.kind == "pixel"
    assert next(la for la in psd if la.name == "BORDER LAYER").effects  # still live
