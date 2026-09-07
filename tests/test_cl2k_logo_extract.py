"""Tests for CL2K logo extraction (keying a white title out of a poster).

Synthetic fixtures only (no network): a white bar on a dark/coloured field stands
in for a title. Covers the white-key (saturated background dropped), the brush
mask confining the key, and trim-to-content.
"""

import io

from PIL import Image, ImageDraw

from backend.util.cl2k.logo_extract import (
    extract_logo_by_diff,
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


def _brush(size, rect) -> bytes:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rectangle(rect, fill=255)
    return _png(m)


def test_subject_keeps_both_halves_of_a_mixed_title():
    # white word + red word on a dark field; the colour key alone drops the white
    # word when a white-ish tone sits in the backdrop palette, so subject mode
    # unions in the brightness key
    img = Image.new("RGB", (400, 300), (40, 35, 30))
    d = ImageDraw.Draw(img)
    d.rectangle((60, 100, 340, 130), fill=(250, 248, 245))  # white word
    d.rectangle((60, 160, 340, 190), fill=(210, 170, 30))  # yellow word
    d.rectangle((0, 270, 400, 300), fill=(245, 243, 240))  # white-ish art far away

    out = extract_subject_logo(_jpeg(img), _brush(img.size, (40, 80, 360, 210)))
    res = Image.open(io.BytesIO(out))
    # both words in the crop: white bar at the top, yellow at the bottom (a
    # yellow-only extraction would crop to ~30px tall)
    assert res.height >= 85
    a = res.split()[-1].load()
    px = res.load()
    wx, wy = res.width // 2, res.height // 6  # mid white bar
    yx, yy = res.width // 2, res.height * 5 // 6  # mid yellow bar
    assert a[wx, wy] > 200, "white word must survive subject mode"
    assert a[yx, yy] > 200, "coloured word must survive subject mode"
    r, g, b, _ = px[yx, yy]
    assert r > 150 and b < 100, "coloured word keeps its original colour"


def test_subject_keys_every_colour_of_a_multicolour_title():
    # the colour key is distance-from-backdrop, not anchored to one hue: white,
    # red, yellow and green words must ALL extract with their original colours
    img = Image.new("RGB", (400, 420), (38, 34, 30))
    d = ImageDraw.Draw(img)
    bars = [
        ((60, 80, 340, 110), (250, 248, 245)),
        ((60, 150, 340, 180), (200, 35, 35)),
        ((60, 220, 340, 250), (215, 180, 45)),
        ((60, 290, 340, 320), (50, 160, 60)),
    ]
    for r, c in bars:
        d.rectangle(r, fill=c)

    out = extract_subject_logo(_jpeg(img), _brush(img.size, (40, 60, 360, 340)))
    res = Image.open(io.BytesIO(out))
    px = res.load()
    ox, oy = 58, 78  # crop origin = content bbox (bars start at (60, 80))
    for (x0, y0, x1, y1), (er, eg, eb) in bars:
        r, g, b, a = px[(x0 + x1) // 2 - ox, (y0 + y1) // 2 - oy]
        assert a > 200, f"word at y={y0} must extract"
        assert abs(r - er) < 30 and abs(g - eg) < 30 and abs(b - eb) < 30


def test_subject_ring_bleed_does_not_eat_the_title():
    # grunge 'spray' of title colour just OUTSIDE the brush poisons the backdrop
    # palette unless bleed clusters are dropped (no far-ring support)
    img = Image.new("RGB", (500, 360), (30, 28, 25))
    d = ImageDraw.Draw(img)
    d.rectangle((120, 140, 380, 220), fill=(215, 180, 45))  # fat yellow title
    # dense speckle hugging the title: inside the near ring, outside the brush
    for x in range(100, 400, 9):
        d.ellipse((x, 118, x + 5, 123), fill=(215, 180, 45))
        d.ellipse((x, 238, x + 5, 243), fill=(215, 180, 45))

    out = extract_subject_logo(_jpeg(img), _brush(img.size, (110, 132, 390, 228)))
    res = Image.open(io.BytesIO(out))
    arr = res.split()[-1]
    # the glyph body must stay SOLID: sample a grid inside the bar
    solid = sum(
        arr.load()[x, y] > 200
        for x in range(30, res.width - 30, 20)
        for y in range(20, res.height - 20, 12)
    )
    total = len(range(30, res.width - 30, 20)) * len(range(20, res.height - 20, 12))
    assert solid / total > 0.9, "title body must not be eaten by its own bleed"


def test_subject_union_rejected_on_a_pale_field():
    # coloured title on a cream field: the white key would grab the WHOLE field —
    # the coverage guard must reject the union and keep pure colour-key output
    img = Image.new("RGB", (400, 240), (235, 228, 210))
    ImageDraw.Draw(img).rectangle((60, 100, 340, 140), fill=(200, 30, 30))

    out = extract_subject_logo(_jpeg(img), _brush(img.size, (40, 80, 360, 160)))
    res = Image.open(io.BytesIO(out))
    assert 250 <= res.width <= 320 and res.height <= 80  # red bar only, no field
    r, g, b, a = res.getpixel((res.width // 2, res.height // 2))
    assert r > 150 and g < 100 and a > 200


def test_subject_union_drops_backdrop_spilling_across_the_brush():
    # a pale sky band crossing the brush border is backdrop, not title — the
    # spill guard must drop it even though it brightness-keys
    img = Image.new("RGB", (400, 300), (40, 45, 60))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 400, 90), fill=(200, 215, 235))  # sky, continues past brush
    d.rectangle((60, 140, 340, 190), fill=(200, 30, 30))  # red title

    out = extract_subject_logo(_jpeg(img), _brush(img.size, (30, 60, 370, 220)))
    res = Image.open(io.BytesIO(out))
    assert res.height <= 80, "sky band must not widen the crop"
    r, g, b, a = res.getpixel((res.width // 2, res.height // 2))
    assert r > 150 and g < 100 and a > 200  # the title itself survives


def test_subject_rescues_a_pale_word_next_to_a_vivid_one():
    # a big vivid word pulls the Otsu band-fit high enough that a pale muted
    # word lands under `lo` and vanishes; per-anchor rescue must keep it (its
    # min channel is under the white-key floor, so the union can't)
    import numpy as np

    img = Image.new("RGB", (400, 340), (128, 128, 128))
    d = ImageDraw.Draw(img)
    d.rectangle((100, 90, 300, 120), fill=(110, 120, 160))  # pale muted-blue word
    d.rectangle((50, 160, 350, 280), fill=(205, 35, 35))  # fat vivid red word

    out = extract_subject_logo(_jpeg(img), _brush(img.size, (40, 70, 360, 300)))
    res = Image.open(io.BytesIO(out))
    assert res.height >= 180, "crop must span BOTH words, not just the vivid one"
    arr = np.asarray(res)
    top = arr[: res.height // 3]
    op = top[..., 3] > 128
    assert int(op.sum()) > 2000, "pale word must survive"
    mean = top[..., :3][op].mean(axis=0)
    assert mean[2] > mean[0] + 20, "pale word keeps its blue tint"


def _junk_poster():
    """Red title bar plus an off-title junk blob, both far from the backdrop."""
    img = Image.new("RGB", (400, 300), (40, 42, 46))
    d = ImageDraw.Draw(img)
    d.rectangle((60, 90, 340, 130), fill=(200, 30, 30))  # the title
    d.ellipse((150, 190, 250, 250), fill=(60, 130, 200))  # scene junk in-brush
    return img


def test_subject_zone_filter_drops_junk_off_the_text_line(monkeypatch):
    import numpy as np

    from backend.util.cl2k import text_detect

    prob = np.zeros((300, 400), dtype=np.float32)
    prob[92:128, 65:335] = 1.0  # detector box over the title only
    monkeypatch.setattr(text_detect, "detect_text_probmap", lambda _b: prob)

    img = _junk_poster()
    out = extract_subject_logo(_jpeg(img), _brush(img.size, (40, 70, 360, 270)))
    res = Image.open(io.BytesIO(out))
    assert res.height <= 80, "junk blob must be dropped, crop is the title alone"
    r, g, b, a = res.getpixel((res.width // 2, res.height // 2))
    assert r > 150 and a > 200


def test_subject_zone_filter_fails_safe_without_detector(monkeypatch):
    from backend.util.cl2k import text_detect

    monkeypatch.setattr(text_detect, "detect_text_probmap", lambda _b: None)
    img = _junk_poster()
    out = extract_subject_logo(_jpeg(img), _brush(img.size, (40, 70, 360, 270)))
    res = Image.open(io.BytesIO(out))
    assert res.height > 140, "no detector -> keep everything the key found"


def test_subject_zone_filter_distrusts_a_partial_detection(monkeypatch):
    # the box covers only a minority DISCONNECTED piece; the flood then keeps
    # under half the keyed area -> the detector likely missed the wordmark, so
    # the filter must leave alpha alone rather than shave the bulk
    import numpy as np

    from backend.util.cl2k import text_detect

    prob = np.zeros((300, 400), dtype=np.float32)
    prob[92:112, 65:110] = 1.0  # box over the small bar only
    monkeypatch.setattr(text_detect, "detect_text_probmap", lambda _b: prob)

    img = Image.new("RGB", (400, 300), (40, 42, 46))
    d = ImageDraw.Draw(img)
    d.rectangle((60, 90, 110, 112), fill=(200, 30, 30))  # small detected bar
    d.rectangle((60, 150, 340, 250), fill=(200, 30, 30))  # bulk, disconnected
    out = extract_subject_logo(_jpeg(img), _brush(img.size, (40, 70, 360, 270)))
    res = Image.open(io.BytesIO(out))
    assert res.height > 140, "partial detection must not shave the wordmark"


def test_subject_spill_guard_reaches_deep_into_a_large_brush():
    # a bright column entering a TALL brush and running deep inside it must be
    # fully flood-killed — a fixed iteration cap left everything past ~256px
    img = Image.new("RGB", (300, 1400), (35, 38, 44))
    d = ImageDraw.Draw(img)
    d.rectangle((120, 0, 180, 1200), fill=(205, 212, 228))  # crosses the brush top
    d.rectangle((60, 1250, 240, 1300), fill=(200, 30, 30))  # red title near the foot

    out = extract_subject_logo(_jpeg(img), _brush(img.size, (20, 40, 280, 1350)))
    res = Image.open(io.BytesIO(out))
    assert res.height <= 80, "deep backdrop column must not survive the flood"
    r, g, b, a = res.getpixel((res.width // 2, res.height // 2))
    assert r > 150 and g < 100 and a > 200


def _coloured_title_strokes():
    """Thin red vertical strokes (stroke-shaped 'letters') on a grey plate."""
    img = Image.new("RGB", (400, 240), (120, 122, 124))
    d = ImageDraw.Draw(img)
    for x in range(70, 340, 45):
        d.rectangle((x, 90, x + 12, 150), fill=(210, 40, 40))
    return img


def test_tighten_survives_title_bleed_in_the_outside_ring(monkeypatch):
    # spray of the TITLE's colour just outside the block used to poison
    # _outside_background: the fallback anchor then "matched the background" and
    # tighten gave up. Bleed clusters have no far-ring support and are dropped.
    import numpy as np

    from backend.util.cl2k import text_detect

    monkeypatch.setattr(text_detect, "detect_text_probmap", lambda _b: None)
    img = Image.new("RGB", (500, 300), (120, 122, 124))
    d = ImageDraw.Draw(img)
    for x in range(90, 420, 45):  # stroke-shaped red title
        d.rectangle((x, 120, x + 12, 180), fill=(210, 40, 40))
    for x in range(60, 450, 8):  # dense red spray hugging the block
        d.rectangle((x, 100, x + 3, 103), fill=(210, 40, 40))
        d.rectangle((x, 197, x + 3, 200), fill=(210, 40, 40))

    block = Image.new("L", img.size, 0)
    ImageDraw.Draw(block).rectangle((70, 108, 440, 192), fill=255)

    out = tighten_text_mask(_jpeg(img), _png(block))
    assert out is not None, "bleed in the ring must not abort tightening"
    m = Image.open(io.BytesIO(out)).convert("L")
    assert m.getpixel((96, 150)) > 200  # on a red stroke -> remove
    assert m.getpixel((118, 150)) < 60  # centre of the gap between strokes -> keep
    assert (np.asarray(m) > 127).sum() < (np.asarray(block) > 127).sum()


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


# --------------------------------------------------------------------------
# diff key (after an AI erase)
# --------------------------------------------------------------------------

_FIELD = (40, 45, 55)
_TITLE_BOX = (60, 100, 340, 140)
_JUNK_BOX = (100, 30, 150, 70)  # scene detail the brush also covers


def _erase_poster(*, junk: bool) -> Image.Image:
    img = Image.new("RGB", (400, 240), _FIELD)
    draw = ImageDraw.Draw(img)
    draw.rectangle(_TITLE_BOX, fill=(255, 255, 255))
    if junk:
        draw.rectangle(_JUNK_BOX, fill=(240, 238, 235))
    return img


def _erased(img: Image.Image, *boxes) -> Image.Image:
    """``img`` with ``boxes`` painted back to the field — stands in for LaMa."""
    out = img.copy()
    draw = ImageDraw.Draw(out)
    for box in boxes:
        draw.rectangle(box, fill=_FIELD)
    return out


def _erase_mask() -> Image.Image:
    mask = Image.new("L", (400, 240), 0)
    ImageDraw.Draw(mask).rectangle((40, 20, 360, 160), fill=255)
    return mask


def _pin_detector(monkeypatch, hot_box):
    """Pin the DBNet probmap: hot over ``hot_box``, or absent when it is None.

    The vendored model is an optional dep, so a real detector run would make
    these assertions depend on whether onnxruntime is installed.
    """
    import numpy as np

    from backend.util.cl2k import text_detect

    def fake(_image_bytes):
        if hot_box is None:
            return None
        prob = np.zeros((240, 400), dtype=np.float32)
        x0, y0, x1, y1 = hot_box
        prob[y0:y1, x0:x1] = 1.0
        return prob

    monkeypatch.setattr(text_detect, "detect_text_probmap", fake)


def test_diff_keys_whatever_the_eraser_repainted(monkeypatch):
    _pin_detector(monkeypatch, None)
    img = _erase_poster(junk=False)
    out = extract_logo_by_diff(
        _png(img), _png(_erased(img, _TITLE_BOX)), _png(_erase_mask())
    )
    res = Image.open(io.BytesIO(out))
    assert res.mode == "RGBA"
    # trimmed to the repainted bar (~280x40), not the 400x240 frame
    assert 250 <= res.width <= 320
    assert res.height <= 80
    # ORIGINAL colours survive — the CL2K whiten pass recolours downstream
    r, g, b, a = res.getpixel((res.width // 2, res.height // 2))
    assert (r, g, b) == (255, 255, 255) and a > 200


def test_diff_ignores_inpaint_drift_outside_the_brush(monkeypatch):
    _pin_detector(monkeypatch, None)
    img = _erase_poster(junk=False)
    # The eraser also nudged a corner well outside the brush (inpaint drift).
    cleaned = _erased(img, _TITLE_BOX)
    ImageDraw.Draw(cleaned).rectangle((5, 190, 60, 230), fill=(200, 60, 60))

    out = extract_logo_by_diff(_png(img), _png(cleaned), _png(_erase_mask()))
    res = Image.open(io.BytesIO(out))
    assert res.height <= 80  # drift at y=190 would stretch this past 100


def test_diff_zone_filter_drops_repaint_off_the_text_line(monkeypatch):
    """The eraser repaints ALL of a loose brush, so scene detail diffs as hard as
    the title — the text-zone filter is what tells them apart (regression: the
    girl's dress keying in above the Cassadaga title)."""
    _pin_detector(monkeypatch, _TITLE_BOX)
    img = _erase_poster(junk=True)
    out = extract_logo_by_diff(
        _png(img), _png(_erased(img, _TITLE_BOX, _JUNK_BOX)), _png(_erase_mask())
    )
    res = Image.open(io.BytesIO(out))
    assert res.height <= 80  # junk at y=30 is gone; only the bar remains


def test_diff_keeps_repaint_when_the_detector_is_absent(monkeypatch):
    """Fail-safe: with no detector there is no text line to judge against, so the
    filter must leave the key alone rather than guess it away."""
    _pin_detector(monkeypatch, None)
    img = _erase_poster(junk=True)
    out = extract_logo_by_diff(
        _png(img), _png(_erased(img, _TITLE_BOX, _JUNK_BOX)), _png(_erase_mask())
    )
    res = Image.open(io.BytesIO(out))
    assert res.height >= 100  # spans the junk at y=30 down to the bar at y=140


# --------------------------------------------------------------------------
# despeckle: two-pointer row merge must match the old pairwise scan exactly
# --------------------------------------------------------------------------


def _despeckle_pairwise(alpha, min_area=12):
    """The pre-two-pointer despeckle, verbatim, as the equivalence oracle."""
    import numpy as np

    binary = alpha > 40
    h, _w = binary.shape
    parent = {}

    def find(a):
        """DSU find with path compression (oracle helper)."""
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        """DSU union by root (oracle helper)."""
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    next_id = 0
    prev_runs = []
    all_runs = []
    for y in range(h):
        idx = np.flatnonzero(binary[y])
        if idx.size == 0:
            prev_runs = []
            continue
        breaks = np.flatnonzero(np.diff(idx) > 1)
        starts = np.concatenate(([0], breaks + 1))
        ends = np.concatenate((breaks, [idx.size - 1]))
        cur_runs = []
        for s, e in zip(starts, ends):
            cs, ce = int(idx[s]), int(idx[e])
            lbl = next_id
            next_id += 1
            parent[lbl] = lbl
            for ps, pe, plbl in prev_runs:
                if pe >= cs - 1 and ps <= ce + 1:
                    union(lbl, plbl)
            cur_runs.append((cs, ce, lbl))
            all_runs.append((y, cs, ce, lbl))
        prev_runs = cur_runs

    area = {}
    for _y, cs, ce, lbl in all_runs:
        r = find(lbl)
        area[r] = area.get(r, 0) + (ce - cs + 1)
    keep = np.zeros_like(binary)
    for y, cs, ce, lbl in all_runs:
        if area[find(lbl)] >= min_area:
            keep[y, cs : ce + 1] = True
    return (alpha * keep).astype(np.uint8)


def test_despeckle_matches_the_pairwise_oracle_on_random_runs():
    """Property test: new merge == verbatim old implementation."""
    import numpy as np

    from backend.util.cl2k import logo_extract

    rng = np.random.default_rng(20260812)
    for _ in range(60):
        h, w = int(rng.integers(1, 30)), int(rng.integers(1, 45))
        on = rng.random((h, w)) < float(rng.random())
        alpha = (on * rng.integers(0, 256, (h, w))).astype(np.uint8)
        for min_area in (1, 4, 12, 40):
            assert np.array_equal(
                logo_extract._despeckle(alpha, min_area),
                _despeckle_pairwise(alpha, min_area),
            )


def test_despeckle_matches_the_oracle_on_adversarial_run_patterns():
    """Structured worst-case patterns match the oracle exactly."""
    import numpy as np

    from backend.util.cl2k import logo_extract

    cases = {}
    cases["solid"] = np.full((20, 30), 255, np.uint8)
    cases["empty"] = np.zeros((20, 30), np.uint8)
    checker = np.zeros((21, 31), np.uint8)
    checker[::2, ::2] = 255  # every run 1px wide: the worst case for the merge
    cases["checker"] = checker
    diagonal = np.zeros((40, 40), np.uint8)
    diagonal[np.arange(40), np.arange(40)] = 255  # 8-connectivity corner touches
    cases["diagonal"] = diagonal
    stripes = np.zeros((30, 60), np.uint8)
    stripes[:, ::3] = 200
    cases["stripes"] = stripes
    line = (np.random.default_rng(7).random(200) < 0.5).astype(np.uint8) * 255
    cases["single_row"] = line.reshape(1, 200)
    cases["single_col"] = line.reshape(200, 1)
    grain = np.random.default_rng(11).random((120, 400))
    cases["grain"] = ((grain < 0.5) * 255).astype(np.uint8)  # ~100 runs per row
    for name, alpha in cases.items():
        for min_area in (1, 12, 40):
            assert np.array_equal(
                logo_extract._despeckle(alpha, min_area),
                _despeckle_pairwise(alpha, min_area),
            ), f"{name} @ min_area={min_area}"


def test_despeckle_handles_a_grainy_no_mask_extract_in_budget():
    """The pathological case: thousands of tiny runs per row, which the pairwise
    row scan turned into O(runs^2) and stalled the render worker on."""
    import time

    import numpy as np

    from backend.util.cl2k import logo_extract

    rng = np.random.default_rng(4)
    alpha = ((rng.random((1000, 2000)) < 0.5) * 255).astype(np.uint8)
    start = time.perf_counter()
    out = logo_extract._despeckle(alpha)
    elapsed = time.perf_counter() - start
    assert out.shape == alpha.shape
    assert (out > 0).any()  # the mask survived; the oracle checks exact equality
    assert elapsed < 12.0  # ~0.6s here; the pairwise scan took ~7s
