"""Tests for CL2K logo extraction (keying a white title out of a poster).

Synthetic fixtures only (no network): a white bar on a dark/coloured field stands
in for a title. Covers the white-key (saturated background dropped), the brush
mask confining the key, and trim-to-content.
"""

import io

from PIL import Image, ImageDraw

from backend.util.cl2k.logo_extract import (
    extract_subject_logo,
    extract_title_logo,
    fill_dark_bodies,
    ink_color_edges,
    tighten_text_mask,
)


def _jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=95)
    return buf.getvalue()


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _poster_with_title() -> Image.Image:
    # purple field (saturated -> low min channel -> keyed out), white title bar
    img = Image.new("RGB", (400, 240), (90, 40, 130))
    ImageDraw.Draw(img).rectangle((60, 100, 340, 140), fill=(255, 255, 255))
    return img


def test_extracts_white_title_as_transparent_png():
    out = extract_title_logo(_jpeg(_poster_with_title()))
    res = Image.open(io.BytesIO(out))
    assert res.mode == "RGBA"
    # trimmed to roughly the title bar (~280x40), not the full 400x240 frame
    assert 250 <= res.width <= 320
    assert res.height <= 80
    # the kept pixels are white with high alpha
    alpha = res.split()[-1]
    assert alpha.getextrema()[1] == 255
    cx, cy = res.width // 2, res.height // 2
    r, g, b, a = res.getpixel((cx, cy))
    assert (r, g, b) == (255, 255, 255) and a > 200


def test_mask_confines_the_key_to_the_brushed_region():
    img = _poster_with_title()
    # a bright speck OUTSIDE the title (top-left corner)
    ImageDraw.Draw(img).ellipse((10, 10, 50, 50), fill=(250, 250, 250))

    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rectangle((40, 80, 360, 160), fill=255)  # only over the title

    out = extract_title_logo(_jpeg(img), _png(mask))
    res = Image.open(io.BytesIO(out))
    # speck excluded -> result stays near the title width, not stretched to the corner
    assert res.width <= 320


def test_blank_input_yields_empty_logo():
    blank = Image.new("RGB", (200, 120), (20, 30, 40))  # nothing bright to key
    out = extract_title_logo(_jpeg(blank))
    res = Image.open(io.BytesIO(out))
    assert res.split()[-1].getextrema()[1] == 0  # fully transparent


def _poster_with_coloured_title() -> Image.Image:
    # mid-grey field (not bright -> the white key ignores it), saturated RED title
    img = Image.new("RGB", (400, 240), (120, 122, 124))
    ImageDraw.Draw(img).rectangle((60, 100, 340, 140), fill=(210, 40, 40))
    return img


def test_subject_extracts_coloured_title_keeping_its_colour():
    img = _poster_with_coloured_title()
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rectangle(
        (40, 80, 360, 160), fill=255
    )  # over the title + some field

    out = extract_subject_logo(_jpeg(img), _png(mask))
    res = Image.open(io.BytesIO(out))
    assert res.mode == "RGBA"
    # trimmed to roughly the red bar (~280 wide), not the full 400 frame
    assert 250 <= res.width <= 320
    assert res.height <= 80
    # kept pixels keep their ORIGINAL red (NOT pre-whitened) at high alpha
    r, g, b, a = res.getpixel((res.width // 2, res.height // 2))
    assert r > 150 and g < 100 and b < 100 and a > 200


def test_white_key_misses_the_coloured_title():
    # the gap subject mode fills: the brightness key can't catch a saturated title
    out = extract_title_logo(_jpeg(_poster_with_coloured_title()))
    res = Image.open(io.BytesIO(out))
    assert res.split()[-1].getextrema()[1] == 0  # nothing keyed -> fully transparent


def _coloured_title_strokes():
    """Thin red vertical strokes (stroke-shaped 'letters') on a grey plate."""
    img = Image.new("RGB", (400, 240), (120, 122, 124))
    d = ImageDraw.Draw(img)
    for x in range(70, 340, 45):
        d.rectangle((x, 90, x + 12, 150), fill=(210, 40, 40))
    return img


def test_tighten_shrinks_block_to_coloured_glyphs(monkeypatch):
    # Colour-key fallback (detector off): a generous block over a stroke-shaped
    # coloured title keys down to the strokes — white (remove) on a stroke, black
    # in the gaps between them.
    import numpy as np

    from backend.util.cl2k import text_detect

    monkeypatch.setattr(text_detect, "detect_text_probmap", lambda _b: None)
    img = _coloured_title_strokes()
    block = Image.new("L", img.size, 0)
    ImageDraw.Draw(block).rectangle((50, 80, 360, 160), fill=255)

    out = tighten_text_mask(_jpeg(img), _png(block))
    assert out is not None
    m = Image.open(io.BytesIO(out)).convert("L")
    assert m.size == img.size
    assert m.getpixel((76, 120)) > 200  # on a red stroke -> remove
    assert m.getpixel((110, 120)) < 60  # a gap between strokes -> keep
    assert (np.asarray(m) > 127).sum() < (np.asarray(block) > 127).sum()


def _white_on_red():
    img = Image.new("RGB", (500, 200), (210, 40, 40))  # saturated red plate
    d = ImageDraw.Draw(img)
    for x in range(60, 440, 55):
        d.rectangle((x, 60, x + 22, 150), fill=(255, 255, 255))  # white letters
    block = Image.new("L", img.size, 0)
    ImageDraw.Draw(block).rectangle((40, 45, 460, 165), fill=255)
    return img, block


def test_tighten_detector_keys_the_white_title_not_the_plate(monkeypatch):
    # White title on a saturated plate, WITH the detector: the ink is keyed
    # against the background sampled OUTSIDE the brush, so it lands on the WHITE
    # letters (polarity-agnostic), not inverted onto the red plate. The probmap is
    # a real detector output shape (a filled line box, incl. inter-glyph gaps) —
    # the anchor must still recover white from it.
    import numpy as np

    from backend.util.cl2k import text_detect

    img, block = _white_on_red()  # white bars on a saturated red plate
    prob = np.zeros((200, 500), np.float32)
    prob[55:155, 40:460] = 1.0  # DBNet-style filled box over the whole text line
    monkeypatch.setattr(text_detect, "detect_text_probmap", lambda _b: prob)

    out = tighten_text_mask(_jpeg(img), _png(block))
    assert out is not None
    m = np.asarray(Image.open(io.BytesIO(out)).convert("L")) > 127
    px = np.asarray(img)[m]
    assert (px.min(axis=1) > 170).mean() > 0.6  # on the WHITE letters, not red


def test_detect_anchors_rejects_when_ink_matches_background():
    # A detected box over a UNIFORM region (no distinct ink) -> every cluster
    # sits on the background -> no anchors (distinctness backstop), so tighten
    # falls through to the colour-key instead of masking the plate.
    import numpy as np

    from backend.util.cl2k import logo_extract

    img = Image.new("RGB", (400, 200), (200, 40, 40))  # uniform red, no title
    prob = np.zeros((200, 400), np.float32)
    prob[70:130, 60:340] = 1.0
    arr = np.asarray(logo_extract._open_rgb_bounded(_jpeg(img))).astype(np.float32)
    lab = logo_extract._srgb_to_lab(arr)
    block = np.zeros((200, 400), bool)
    block[40:170, 40:360] = True
    bg = logo_extract._outside_background(lab, block, 400)
    assert logo_extract._detect_anchors(prob, lab, block, bg, 33.0) == []


def test_matches_background_only_rejects_a_dominant_plate():
    # The distinctness check: reject an anchor near a DOMINANT background cluster
    # (a plate = inversion); pass a vivid colour far from all; and — the fix for
    # the blue-on-blue-ish poster — pass an anchor near only a MINOR background
    # element (a small window reflection), not a real plate.
    import numpy as np

    from backend.util.cl2k import logo_extract

    cent = np.array([[50.0, 10.0, -20.0], [82.0, -4.0, 6.0]], np.float32)
    big = (cent, np.array([0.5, 0.5], np.float32))  # both dominant
    small = (cent, np.array([0.02, 0.98], np.float32))  # first is a 2% minority

    near = np.array([51.0, 11.0, -19.0], np.float32)  # near cent[0]
    vivid = np.array([40.0, 60.0, -55.0], np.float32)  # far from all
    assert logo_extract._matches_background(
        near, big
    )  # near a dominant plate -> reject
    assert not logo_extract._matches_background(vivid, big)  # far -> pass
    assert not logo_extract._matches_background(
        near, small
    )  # near a 2% element -> pass


def test_tighten_multi_colour_title_keys_both_colours(monkeypatch):
    # A two-colour title (cream + red rows on a grey field): every ink cluster
    # becomes an anchor, so the union masks BOTH colours — the old single
    # dominant anchor kept one row and dropped the other.
    import numpy as np

    from backend.util.cl2k import text_detect

    img = Image.new("RGB", (500, 300), (95, 100, 108))
    d = ImageDraw.Draw(img)
    for x in range(60, 440, 55):
        d.rectangle((x, 70, x + 22, 130), fill=(245, 240, 220))  # cream row
        d.rectangle((x, 170, x + 22, 230), fill=(210, 30, 30))  # red row
    prob = np.zeros((300, 500), np.float32)
    prob[65:135, 40:460] = 1.0
    prob[165:235, 40:460] = 1.0
    monkeypatch.setattr(text_detect, "detect_text_probmap", lambda _b: prob)
    block = Image.new("L", img.size, 0)
    ImageDraw.Draw(block).rectangle((30, 50, 470, 250), fill=255)

    out = tighten_text_mask(_jpeg(img), _png(block))
    assert out is not None
    m = np.asarray(Image.open(io.BytesIO(out)).convert("L")) > 127
    assert m[100, 71]  # on a cream bar -> remove
    assert m[200, 71]  # on a red bar -> remove
    assert not m[100, 100]  # grey gap between bars -> keep


def test_tighten_accepts_white_title_on_pale_field(monkeypatch):
    # White ink whose ΔE to the pale field is inside 8..20: kept as a LIGHT
    # suspect with the key band clamped below the field distance, and accepted
    # because the mask stays inside the detector box. The old hard veto returned
    # None ("kept your mask") for every white-on-pale title.
    import numpy as np

    from backend.util.cl2k import text_detect

    img = Image.new("RGB", (500, 200), (200, 205, 212))  # pale fog field
    d = ImageDraw.Draw(img)
    for x in range(60, 440, 55):
        d.rectangle((x, 60, x + 22, 150), fill=(255, 255, 255))
    prob = np.zeros((200, 500), np.float32)
    prob[55:155, 40:460] = 1.0
    monkeypatch.setattr(text_detect, "detect_text_probmap", lambda _b: prob)
    block = Image.new("L", img.size, 0)
    ImageDraw.Draw(block).rectangle((40, 45, 460, 165), fill=255)

    out = tighten_text_mask(_jpeg(img), _png(block))
    assert out is not None
    m = np.asarray(Image.open(io.BytesIO(out)).convert("L")) > 127
    assert m[100, 71]  # on a white bar -> remove
    assert not m[100, 100]  # pale gap between bars -> keep (band is clamped)


def test_tighten_unions_outline_with_fill(monkeypatch):
    # White fill + black outline on a mid-blue field: the outline is its own
    # ink cluster, far from the field, so the union masks fill AND outline — a
    # single-anchor key left the outline behind to ghost through the erase.
    import numpy as np

    from backend.util.cl2k import text_detect

    img = Image.new("RGB", (500, 200), (90, 110, 150))
    d = ImageDraw.Draw(img)
    for x in range(60, 440, 55):
        d.rectangle((x - 6, 54, x + 28, 156), fill=(10, 10, 10))  # outline slab
        d.rectangle((x, 60, x + 22, 150), fill=(255, 255, 255))  # fill
    prob = np.zeros((200, 500), np.float32)
    prob[50:160, 40:460] = 1.0
    monkeypatch.setattr(text_detect, "detect_text_probmap", lambda _b: prob)
    block = Image.new("L", img.size, 0)
    ImageDraw.Draw(block).rectangle((40, 45, 460, 165), fill=255)

    out = tighten_text_mask(_jpeg(img), _png(block))
    assert out is not None
    m = np.asarray(Image.open(io.BytesIO(out)).convert("L")) > 127
    assert m[100, 71]  # white fill -> remove
    assert m[100, 56]  # black outline -> remove too
    assert not m[100, 100]  # field gap between glyphs -> keep


def test_tighten_drops_dark_scenery_near_background(monkeypatch):
    # A dark blob (figures/scenery) whose colour sits NEAR a dark background
    # cluster: dark suspects are dropped, so the blob stays unmasked while the
    # white title keys — keying it would have swallowed the artwork.
    import numpy as np

    from backend.util.cl2k import text_detect

    img = Image.new("RGB", (500, 200), (60, 62, 66))  # dark field
    d = ImageDraw.Draw(img)
    for x in range(60, 250, 55):
        d.rectangle((x, 60, x + 22, 150), fill=(255, 255, 255))
    d.rectangle((300, 40, 430, 160), fill=(35, 37, 41))  # near-field scenery
    prob = np.zeros((200, 500), np.float32)
    prob[55:155, 40:460] = 1.0
    monkeypatch.setattr(text_detect, "detect_text_probmap", lambda _b: prob)
    block = Image.new("L", img.size, 0)
    ImageDraw.Draw(block).rectangle((40, 45, 460, 165), fill=255)

    out = tighten_text_mask(_jpeg(img), _png(block))
    assert out is not None
    m = np.asarray(Image.open(io.BytesIO(out)).convert("L")) > 127
    assert m[100, 71]  # white bar -> remove
    assert not m[100, 350]  # dark blob -> keep (dropped dark suspect)


def test_tighten_fallback_rejects_plate_inversion(monkeypatch):
    # Detector unavailable -> colour-key fallback. Its stroke-shape gate must
    # reject the plate-shaped result (a light title over saturated colour) so it
    # returns None (keep the block) instead of a backwards mask.
    from backend.util.cl2k import text_detect

    monkeypatch.setattr(text_detect, "detect_text_probmap", lambda _b: None)
    img, block = _white_on_red()
    assert tighten_text_mask(_jpeg(img), _png(block)) is None


def test_tighten_falls_back_on_desaturated_plate(monkeypatch):
    # Detector off + no saturated title to key on -> None (keep the user's block).
    from backend.util.cl2k import text_detect

    monkeypatch.setattr(text_detect, "detect_text_probmap", lambda _b: None)
    img = Image.new("RGB", (300, 200), (120, 122, 124))
    block = Image.new("L", img.size, 0)
    ImageDraw.Draw(block).rectangle((20, 20, 280, 180), fill=255)
    assert tighten_text_mask(_jpeg(img), _png(block)) is None


def test_tighten_without_mask_returns_none():
    assert tighten_text_mask(_jpeg(_poster_with_coloured_title()), None) is None


# --------------------------------------------------------------------------
# colour-edge inking (whiten helper)
# --------------------------------------------------------------------------


def _two_colour_logo(divider=None):
    """Green block abutting a blue block; optional black divider between them."""
    img = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((40, 40, 200, 160), fill=(40, 170, 70, 255))  # green
    d.rectangle((200, 40, 360, 160), fill=(50, 90, 200, 255))  # blue, abutting
    if divider:
        d.rectangle((193, 40, 207, 160), fill=(0, 0, 0, 255))  # black keyline
    return img


def _white_blob(divider=False):
    """What plain whiten yields: the whole thing flattened to white (+ a kept
    black divider when the source had one)."""
    img = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((40, 40, 360, 160), fill=(255, 255, 255, 255))
    if divider:
        d.rectangle((193, 40, 207, 160), fill=(0, 0, 0, 255))
    return img


def test_ink_separates_outlineless_colour_boundary():
    import numpy as np

    out = ink_color_edges(_png(_white_blob()), _png(_two_colour_logo()))
    res = np.asarray(Image.open(io.BytesIO(out)).convert("RGB"))
    # a black separator appears at the x=200 boundary, mid-height
    band = res[100, 194:207].sum(axis=1)
    assert (band < 90).any(), "expected a black keyline at the colour boundary"
    # the fills away from the boundary stay white
    assert tuple(res[100, 80]) == (255, 255, 255)
    assert tuple(res[100, 320]) == (255, 255, 255)


def test_ink_is_noop_when_a_keyline_already_exists():
    # source already has a black divider -> whitened keeps it -> nothing to add.
    wp = _png(_white_blob(divider=True))
    out = ink_color_edges(wp, _png(_two_colour_logo(divider=True)))
    assert out == wp  # near-keyline suppression left the mask empty


def test_ink_is_noop_on_a_flat_logo():
    wp = _png(Image.new("RGBA", (200, 120), (255, 255, 255, 255)))
    out = ink_color_edges(wp, _png(Image.new("RGBA", (200, 120), (200, 50, 50, 255))))
    assert out == wp  # no colour edges -> unchanged


# --------------------------------------------------------------------------
# dark-body fill (whiten helper)
# --------------------------------------------------------------------------


def test_fill_dark_bodies_fills_a_wide_neutral_dark_shape():
    import numpy as np

    orig = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(orig)
    d.rectangle((0, 0, 399, 199), fill=(230, 220, 180, 255))  # light field
    d.rectangle((150, 40, 250, 160), fill=(28, 28, 30, 255))  # 100px NEUTRAL dark body
    wp = _png(
        Image.new("RGBA", (400, 200), (255, 255, 255, 255))
    )  # whiten merged it white

    out = fill_dark_bodies(wp, _png(orig))
    res = np.asarray(Image.open(io.BytesIO(out)).convert("L"))
    assert res[100, 200] < 40  # centre of the dark body -> filled black
    assert res[100, 30] > 200  # light field -> stays white


def test_fill_dark_bodies_spares_a_wide_vivid_dark_fill():
    # a wide dark-but-VIVID fill (navy) is a coloured fill -> stays white, not black
    import numpy as np

    orig = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(orig)
    d.rectangle((0, 0, 399, 199), fill=(230, 220, 180, 255))
    d.rectangle((150, 40, 250, 160), fill=(12, 20, 95, 255))  # deep navy body
    wp = _png(Image.new("RGBA", (400, 200), (255, 255, 255, 255)))
    out = fill_dark_bodies(wp, _png(orig))
    res = np.asarray(Image.open(io.BytesIO(out)).convert("L"))
    assert res[100, 200] > 200  # vivid navy body -> spared (stays white)


def test_fill_dark_bodies_noop_on_thin_outline():
    # a thin dark outline is not a "body" — the opening drops it -> unchanged.
    orig = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    ImageDraw.Draw(orig).rectangle(
        (60, 60, 340, 140), outline=(0, 0, 0, 255), width=6, fill=(240, 40, 40, 255)
    )
    wp = _png(Image.new("RGBA", (400, 200), (255, 255, 255, 255)))
    assert fill_dark_bodies(wp, _png(orig)) == wp


# --------------------------------------------------------------------------
# text detector (DBNet ONNX) — fail-soft + shape
# --------------------------------------------------------------------------


def test_text_detect_fail_soft_on_bad_bytes():
    # Never raises — undecodable input (or an absent model) yields None so
    # tighten falls back to the colour-key.
    from backend.util.cl2k import text_detect

    assert text_detect.detect_text_probmap(b"not an image") is None


def test_text_detect_probmap_shape_when_available():
    from backend.util.cl2k import text_detect

    if not text_detect.available():
        import pytest

        pytest.skip("onnxruntime/model not installed")
    img = Image.new("RGB", (320, 96), (255, 255, 255))
    ImageDraw.Draw(img).text((10, 35), "HELLO WORLD", fill=(0, 0, 0))
    prob = text_detect.detect_text_probmap(_png(img))
    assert prob is not None
    assert prob.shape == (96, 320)
    assert 0.0 <= float(prob.min()) and float(prob.max()) <= 1.0
