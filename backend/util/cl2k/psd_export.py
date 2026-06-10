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
    scale = max(w / im.width, h / im.height)
    # LANCZOS — sharpest downscale to canvas; PIL's default BICUBIC is softer.
    im = im.resize(
        (round(im.width * scale), round(im.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = (im.width - w) // 2
    top = (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


def _whiten(logo: Image.Image) -> Image.Image:
    logo = logo.convert("RGBA")
    alpha = logo.split()[3]
    white = Image.new("RGBA", logo.size, (255, 255, 255, 0))
    white.putalpha(alpha)
    return white


def _font(bold: bool, px: int) -> ImageFont.FreeTypeFont:
    path = geo.resolve_font(bold=bold)
    try:
        return ImageFont.truetype(path, px) if path else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def _centered(draw: ImageDraw.ImageDraw, text: str, center_y: int, font) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    w = box[2] - box[0]
    h = box[3] - box[1]
    draw.text((geo.CENTER_X - w / 2, center_y - h / 2), text, font=font, fill="white")


def export_psd(
    *,
    backdrop_bytes: bytes,
    kind: str = "movie",
    logo_bytes: Optional[bytes] = None,
    title: str = "",
    season_text: str = "",
    logo_max_width: int = geo.LOGO_WIDTH_STD,
    whiten: bool = True,
) -> bytes:
    """Build the CL2K poster as a layered PSD and return its bytes."""
    from psd_tools import PSDImage
    from psd_tools.api.layers import PixelLayer

    w, h = geo.CANVAS_W, geo.CANVAS_H
    kind = kind.lower()
    baseline = geo.logo_baseline(kind)

    poster = _cover(Image.open(io.BytesIO(backdrop_bytes)).convert("RGB"), w, h).convert("RGBA")
    gradient = Image.open(geo.GRADIENT_PNG).convert("RGBA")

    logo_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if logo_bytes:
        lg = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
        bbox = lg.getbbox()
        if bbox:
            lg = lg.crop(bbox)
        if whiten:
            lg = _whiten(lg)
        tw = min(logo_max_width, geo.LOGO_WIDTH_MAX)
        th = round(lg.height * tw / lg.width)
        max_h = baseline - geo.LOGO_ZONE_TOP
        if th > max_h:
            th = max_h
            tw = round(lg.width * th / lg.height)
        lg = lg.resize((tw, th), Image.Resampling.LANCZOS)
        logo_layer.alpha_composite(lg, (geo.CENTER_X - tw // 2, baseline - th))

    text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)
    if kind == "collection":
        _centered(td, "COLLECTION", geo.COLLECTION_LABEL_Y, _font(False, geo.LABEL_FONT_PX))
    elif kind == "season" and season_text:
        _centered(td, season_text.upper(), geo.SEASON_TEXT_Y, _font(False, geo.LABEL_FONT_PX))

    border = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(border)
    bw = geo.BORDER_WIDTH
    bd.rectangle([0, 0, w, bw], fill="white")
    bd.rectangle([0, h - bw, w, h], fill="white")
    bd.rectangle([0, 0, bw, h], fill="white")
    bd.rectangle([w - bw, 0, w, h], fill="white")

    psd = PSDImage.new(mode="RGB", size=(w, h))
    for name, img in (
        ("POSTER", poster),
        ("GRADIENT", gradient),
        ("LOGO", logo_layer),
        ("TEXT", text_layer),
        ("BORDER", border),
    ):
        psd.append(PixelLayer.frompil(img, psd, name))

    buf = io.BytesIO()
    psd.save(buf)
    return buf.getvalue()


