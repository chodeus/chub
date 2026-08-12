"""Export a CL2K poster as a layered ``.psd`` for editing in Photopea/Photoshop.

Assembles the creator-template structure — POSTER>Main, GRADIENT>live gradient
fill, LOGO>Layer 1, an editable type layer for the label, and an effects-only
BORDER LAYER carrying live Stroke + Inner Glow — using Pillow for layout and
psd-tools to write the file (live pieces built in :mod:`psd_live`). The POSTER
and LOGO pixels come from the renderer's own framing/logo passes, so the
document matches the flattened poster. The embedded preview is our own flat
composite; geometry comes from :mod:`geometry`.
"""

from __future__ import annotations

import io
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from backend.util.cl2k import geometry as geo


def _cover(im: Image.Image, w: int, h: int) -> Image.Image:
    if (im.width, im.height) == (w, h):
        # Already framed (renderer.frame_backdrop output) — pass through
        # untouched so the POSTER layer stays pixel-identical to the render.
        return im
    scale = max(w / im.width, h / im.height)
    # LANCZOS — sharpest downscale to canvas; PIL's default BICUBIC is softer.
    im = im.resize(
        (round(im.width * scale), round(im.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = (im.width - w) // 2
    top = (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


def _layer_name(text: str, fallback: str) -> str:
    """A layer name psd-tools can actually write.

    The legacy Pascal layer name is encoded MacRoman, so a label containing
    anything outside that codec (CJK, Cyrillic, a stray smart quote) raised
    UnicodeEncodeError inside ``psd.save()`` and 500'd the whole export — while
    the render path handled the identical input fine. The template names its
    label layers with stable ASCII identifiers ('SEASON 3', 'SPECIALS') that are
    independent of the glyphs drawn, so falling back to one loses nothing.
    """
    try:
        text.encode("mac_roman")
    except (UnicodeEncodeError, LookupError):
        return fallback
    return text


def _font(bold: bool, px: int) -> ImageFont.FreeTypeFont:
    path = geo.resolve_font(bold=bold)
    try:
        return ImageFont.truetype(path, px) if path else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def _centered(
    draw: ImageDraw.ImageDraw, text: str, center_y: int, font, kerning: float = 0.0
) -> None:
    """Draw centred white text, with optional CL2K letter tracking.

    PIL has no kerning parameter (Wand's ``text_kerning`` adds ``kerning`` px
    between every character pair), so tracked text is drawn char-by-char with
    the same inter-character gaps — keeping the PSD label the same width as the
    rendered poster's.
    """
    box = draw.textbbox((0, 0), text, font=font)
    h = box[3] - box[1]
    # textbbox measures the INK relative to the draw origin, and PIL's origin is
    # the ascender line, not the ink top. Subtracting box[1] is what actually
    # centres the ink on center_y — without it the label sat ~6px low, below both
    # the template's band and the flattened render of the same poster.
    y = center_y - h / 2 - box[1]
    if kerning <= 0:
        w = box[2] - box[0]
        draw.text((geo.CENTER_X - w / 2 - box[0], y), text, font=font, fill="white")
        return
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + kerning * max(0, len(text) - 1)
    x = geo.CENTER_X - total / 2
    for ch, cw in zip(text, widths):
        draw.text((x, y), ch, font=font, fill="white")
        x += cw + kerning


# The template's own border-plate colour. Never visible: fill opacity is 0 and
# only the live Stroke + Inner Glow paint — but the plate must stay OPAQUE, the
# effects key off the layer's alpha shape (a transparent plate draws nothing).
_BORDER_PLATE_RGBA = (189, 0, 0, 255)


def export_psd(
    *,
    backdrop_bytes: bytes,
    kind: str = "movie",
    logo_bytes: Optional[bytes] = None,
    title: str = "",
    season_text: str = "",
    band_label: str = "",
    logo_max_width: Optional[int] = None,
    logo_scale: float = 1.0,
    logo_y_offset: int = 0,
    logo_flip_bytes: Optional[bytes] = None,  # B/W touch-up regions (mask PNG)
    logo_erase_bytes: Optional[bytes] = None,  # erase regions (mask PNG, white=erase)
    whiten: bool = True,
    flat_white: bool = False,
    logo_3d: bool = False,
    invert: bool = False,
) -> bytes:
    """Build the CL2K poster as a layered PSD and return its bytes."""
    from psd_tools import PSDImage
    from psd_tools.api.layers import PixelLayer

    w, h = geo.CANVAS_W, geo.CANVAS_H
    kind = kind.lower()
    baseline = geo.logo_baseline(kind)

    poster = _cover(
        Image.open(io.BytesIO(backdrop_bytes)).convert("RGB"), w, h
    ).convert("RGBA")
    gradient = Image.open(geo.GRADIENT_PNG).convert("RGBA")

    # No clear logo but a title? Typeset the wordmark the flattened render falls
    # back to, instead of exporting an empty LOGO layer. Reuses the renderer's own
    # generator (lazy import — this module is otherwise Pillow-only) so the shape
    # of the wordmark can't drift. NOTE the parity is for DEFAULTS only: render_cl2k
    # can pass a custom title_font and text_logo_stroke, which export_psd has no
    # parameters for, so a request setting either gets a .psd wordmark that differs
    # from its flattened poster.
    wordmark = False
    if not logo_bytes and title:
        from backend.util.cl2k.renderer import generate_text_logo

        logo_bytes = generate_text_logo(title) or None
        wordmark = logo_bytes is not None

    logo_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if logo_bytes:
        from backend.util.cl2k.renderer import process_logo

        # ONE owner for trim + recolour + brush + invert — the render path's own
        # pass, so the LOGO layer and its embedded preview cannot drift from the
        # flattened JPEG (Pillow mirrors of it did, missing the two-tone
        # post-passes). Everything below is placement, which the .psd owns.
        if wordmark:
            # Already CL2K white-on-transparent: only the trim applies — whitening
            # or inverting a wordmark would mangle or erase it.
            processed, _pw, _ph = process_logo(logo_bytes, whiten=False)
        else:
            processed, _pw, _ph = process_logo(
                logo_bytes,
                whiten=whiten,
                flat_white=flat_white,
                logo_3d=logo_3d,
                flip_mask_bytes=logo_flip_bytes,
                erase_mask_bytes=logo_erase_bytes,
                invert=invert,
            )
        lg = Image.open(io.BytesIO(processed)).convert("RGBA")
        if logo_max_width is None:
            tw, th = geo.auto_logo_size(lg.width, lg.height, baseline)
        else:
            tw = min(logo_max_width, geo.LOGO_WIDTH_MAX)
            th = round(lg.height * tw / lg.width)
            max_h = baseline - geo.LOGO_ZONE_TOP
            if th > max_h:
                th = max_h
                tw = round(lg.width * th / lg.height)
        # Scale the guide-fit box as a whole, canvas-clamped — mirrors
        # renderer._place_logo so the LOGO layer matches the rendered poster.
        scale = max(0.25, min(float(logo_scale or 1.0), 3.0))
        tw = max(1, round(tw * scale))
        th = max(1, round(th * scale))
        if tw > w:
            th = max(1, round(th * w / tw))
            tw = w
        if th > h:
            tw = max(1, round(tw * h / th))
            th = h
        lg = lg.resize((tw, th), Image.Resampling.LANCZOS)
        off = max(
            geo.LOGO_Y_OFFSET_MIN, min(int(logo_y_offset or 0), geo.LOGO_Y_OFFSET_MAX)
        )
        top = max(0, min(baseline - th + off, h - th))
        logo_layer.alpha_composite(lg, (geo.CENTER_X - tw // 2, top))

    # The bottom label, when there is one, becomes its own self-describing layer
    # ("COLLECTION" / "SEASON 3") instead of a generic "TEXT" layer — and movies,
    # which have no label, get no empty layer at all.
    # Precedence mirrors render_cl2k: an explicit banner wins, else COLLECTION, else
    # the season band — so the .psd label matches the flattened /generate output.
    label_text, label_y = "", geo.SEASON_TEXT_Y
    if band_label:
        label_text = band_label.upper()
    elif kind == "collection":
        label_text, label_y = "COLLECTION", geo.COLLECTION_LABEL_Y
    elif kind == "season" and season_text:
        label_text = season_text.upper()

    # Bounds are inclusive in PIL too, so the far edge is w-1 / h-1 and the band
    # thickness is bw-1 — passing w/bw here painted 26px bands on the bottom and
    # right but 27px on the top and left. The glow is composited under the stroke
    # so the exported BORDER LAYER matches the flattened render pixel for pixel.
    border = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if geo.INNER_GLOW_PNG.exists():
        with Image.open(geo.INNER_GLOW_PNG) as glow:
            border.alpha_composite(glow.convert("RGBA"))
    bd = ImageDraw.Draw(border)
    bw = geo.BORDER_WIDTH
    bd.rectangle([0, 0, w - 1, bw - 1], fill="white")
    bd.rectangle([0, h - bw, w - 1, h - 1], fill="white")
    bd.rectangle([0, 0, bw - 1, h - 1], fill="white")
    bd.rectangle([w - bw, 0, w - 1, h - 1], fill="white")

    text_layer = None
    if label_text:
        text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        _centered(
            ImageDraw.Draw(text_layer),
            label_text,
            label_y,
            _font(False, geo.LABEL_FONT_PX),
            # Same rule as the renderer, so the .psd label is the same width as
            # the flattened poster's; a flat LABEL_TRACKING here rendered
            # COMPLETE LIMITED SERIES ~140px wider, running under the border.
            kerning=geo.tracking_to_kerning(geo.label_tracking(label_text)),
        )

    # RGBA document so each layer's transparency lands on its own (native) alpha
    # channel; psd-tools would push alpha into a per-layer mask in an RGB doc.
    psd = PSDImage.new(mode="RGBA", size=(w, h))
    from psd_tools.api.layers import Group

    from backend.util.cl2k import psd_live

    # Creator-template structure: POSTER>Main, GRADIENT>live fill, LOGO>Layer 1.
    poster_group = Group.new(psd, "POSTER", open_folder=False)
    PixelLayer.frompil(poster, poster_group, "Main")
    gradient_group = Group.new(psd, "GRADIENT", open_folder=False)
    psd_live.make_gradient_layer(gradient_group)
    logo_group = Group.new(psd, "LOGO", open_folder=False)
    logo_bbox = logo_layer.getbbox()
    if logo_bbox:
        PixelLayer.frompil(
            logo_layer.crop(logo_bbox), logo_group, "Layer 1",
            top=logo_bbox[1], left=logo_bbox[0],
        )
    if text_layer is not None:
        ink = text_layer.getbbox()
        if ink:
            label_layer = PixelLayer.frompil(
                text_layer.crop(ink),
                psd,
                _layer_name(label_text, "LABEL"),
                top=ink[1],
                left=ink[0],
            )
            tysh = psd_live.label_type_block(
                label_text,
                geo.label_tracking(label_text),
                label_y,
                ink[2] - ink[0],
            )
            # Donor asset present -> a real editable type layer; absent -> the
            # raster stays a plain pixel layer (still correct, just not live).
            if tysh is not None:
                from psd_tools.constants import Tag

                label_layer.tagged_blocks[Tag.TYPE_TOOL_OBJECT_SETTING] = tysh
    psd_live.make_border_layer(psd, Image.new("RGBA", (w, h), _BORDER_PLATE_RGBA))

    # The embedded preview must be OUR flat composite: psd-tools cannot render
    # the live effects (no Inner Glow, broken edge stroke), so letting save()
    # recomposite would embed garbage for every non-Photoshop viewer.
    preview = poster.copy()
    preview.alpha_composite(gradient)
    preview.alpha_composite(logo_layer)
    if text_layer is not None:
        preview.alpha_composite(text_layer)
    preview.alpha_composite(border)

    buf = io.BytesIO()
    psd_live.inject_preview(psd, preview, buf)
    return buf.getvalue()
