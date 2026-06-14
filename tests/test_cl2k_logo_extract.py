"""Tests for CL2K logo extraction (keying a white title out of a poster).

Synthetic fixtures only (no network): a white bar on a dark/coloured field stands
in for a title. Covers the white-key (saturated background dropped), the brush
mask confining the key, and trim-to-content.
"""

import io

from PIL import Image, ImageDraw

from backend.util.cl2k.logo_extract import extract_title_logo


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
