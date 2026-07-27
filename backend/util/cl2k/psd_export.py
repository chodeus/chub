"""Export a CL2K poster as a layered ``.psd`` for editing in Photopea/Photoshop.

Assembles the render components as named layers — POSTER, GRADIENT, LOGO, TEXT,
BORDER — using Pillow for the pixels and psd-tools to write the file. The TEXT
layer is rasterized (re-type it live in Photopea if you need editable text).
Mirrors PosterFlow's PSD-export concept; geometry comes from :mod:`geometry`.
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


def _flat_white(logo: Image.Image) -> Image.Image:
    white = Image.new("RGBA", logo.size, (255, 255, 255, 0))
    white.putalpha(logo.split()[3])
    return white


def _whiten(logo: Image.Image, flat_fallback: bool = True) -> Image.Image:
    """CL2K two-tone whiten — Pillow mirror of ``renderer._whiten``.

    Same recipe and constants (see :mod:`geometry`, "logo whitening") so the
    PSD's LOGO layer matches the rendered poster: white fills, black keylines,
    local-contrast pass for interior accents, flat-white fallback for logos
    that would come out mostly black (suppressed when the invert pass follows,
    mirroring the renderer).
    """
    import numpy as np
    from PIL import ImageFilter

    logo = logo.convert("RGBA")
    rgba = np.asarray(logo, dtype=np.float32) / 255.0
    rgb, alpha = rgba[..., :3], rgba[..., 3]
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    light = (mx + mn) / 2.0
    denom = 1.0 - np.abs(2.0 * light - 1.0)
    sat = np.where(denom > 1e-6, (mx - mn) / np.where(denom > 1e-6, denom, 1.0), 0.0)
    key = np.clip(
        (np.maximum(sat, light) - geo.WHITEN_KEY_BLACK)
        / (geo.WHITEN_KEY_WHITE - geo.WHITEN_KEY_BLACK),
        0.0,
        1.0,
    )
    luma = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    sigma = max(2.0, logo.width * geo.WHITEN_DETAIL_SIGMA)
    blurred = (
        np.asarray(
            Image.fromarray((luma * 255.0).round().astype("uint8")).filter(
                ImageFilter.GaussianBlur(sigma)
            ),
            dtype=np.float32,
        )
        / 255.0
    )
    detail = np.clip(
        (blurred - luma - geo.WHITEN_DETAIL_LO)
        / (geo.WHITEN_DETAIL_HI - geo.WHITEN_DETAIL_LO),
        0.0,
        1.0,
    )
    key *= 1.0 - detail
    a_sum = float(alpha.sum())
    if (
        flat_fallback
        and a_sum > 1e-3
        and float((key * alpha).sum()) / a_sum < geo.WHITEN_FALLBACK_MEAN
    ):
        return _flat_white(logo)
    out = np.empty_like(rgba)
    out[..., 0] = out[..., 1] = out[..., 2] = key
    out[..., 3] = alpha
    return Image.fromarray((out * 255.0).round().astype("uint8"), "RGBA")


def _invert_to_clear(logo: Image.Image) -> Image.Image:
    """Invert logo — Pillow mirror of ``renderer._invert_to_clear``.

    White → transparent, black → white: darkness becomes opacity, so a
    plate-style logo's LOGO layer matches the rendered poster's clearlogo.
    """
    import numpy as np

    rgba = np.asarray(logo.convert("RGBA"), dtype=np.float32) / 255.0
    luma = rgba[..., :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    out = np.empty_like(rgba)
    out[..., 0] = out[..., 1] = out[..., 2] = 1.0
    out[..., 3] = (1.0 - luma) * rgba[..., 3]
    return Image.fromarray((out * 255.0).round().astype("uint8"), "RGBA")


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
    whiten: bool = True,
    flat_white: bool = False,
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

    # No clear logo but a title? Typeset the same wordmark the flattened render
    # falls back to, instead of exporting an empty LOGO layer. Reuses the
    # renderer's own generator (lazy import — this module is otherwise Pillow-only)
    # so the two can't drift. The wordmark is already CL2K white-on-transparent,
    # so it skips the whiten/invert passes a sourced logo needs.
    wordmark = False
    if not logo_bytes and title:
        from backend.util.cl2k.renderer import generate_text_logo

        logo_bytes = generate_text_logo(title) or None
        wordmark = logo_bytes is not None

    logo_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if logo_bytes:
        lg = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
        bbox = lg.getbbox()
        if bbox:
            lg = lg.crop(bbox)
        if wordmark:
            pass
        elif flat_white:
            lg = _flat_white(lg)
        elif whiten:
            lg = _whiten(lg, flat_fallback=not invert)
        if invert and not flat_white and not wordmark:
            lg = _invert_to_clear(lg)
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

    layers = [("POSTER", poster), ("GRADIENT", gradient), ("LOGO", logo_layer)]
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
        layers.append((_layer_name(label_text, "LABEL"), text_layer))
    layers.append(("BORDER LAYER", border))

    # RGBA document so each layer's transparency lands on its own (native) alpha
    # channel — matching the official CL2K_template.psd (RGB, 4-channel composite),
    # whose layers all use native alpha rather than masks. An RGB document makes
    # some psd-tools versions push the alpha into a per-layer mask instead, which
    # is messier to edit; RGBA keeps the layers clean (logo/gradient/border carry
    # their own transparency, no mask to detach).
    psd = PSDImage.new(mode="RGBA", size=(w, h))
    for name, img in layers:
        psd.append(PixelLayer.frompil(img, psd, name))

    buf = io.BytesIO()
    psd.save(buf)
    return buf.getvalue()
