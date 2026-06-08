"""CL2K poster renderer (ImageMagick via Wand).

Reproduces the community CL2K template programmatically: a full-bleed textless
backdrop, the black bottom gradient, a whitened clear logo placed on the locked
guides, an optional COLLECTION / season label, and the default white border —
exported as a high-quality JPEG per the DAPS rules. All geometry comes from
:mod:`backend.util.cl2k.geometry`.

ImageMagick (not Pillow) is used here for gradient compositing, logo whitening,
and text, matching the wider MM2K/CL2K toolchain. Pillow stays in use elsewhere
in Chub; this module does not touch it.

Run standalone for a quick visual check::

    python -m backend.util.cl2k.renderer \\
        --backdrop art.jpg --logo logo.png --kind movie --out poster.jpg
"""

from __future__ import annotations

from typing import Optional

from wand.color import Color
from wand.drawing import Drawing
from wand.image import Image

from backend.util.cl2k import geometry as geo


# ----- helpers ---------------------------------------------------------------
def _cover_resize(
    img: Image,
    width: int,
    height: int,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
) -> None:
    """Resize + crop ``img`` in place to exactly width×height (cover fill).

    ``focus_x``/``focus_y`` (0..1) choose what stays in frame: the focal point of
    the scaled image is centred in the crop, clamped to the edges. 0.5/0.5 is the
    centre crop (the default, unchanged behaviour).
    """
    scale = max(width / img.width, height / img.height)
    img.resize(int(round(img.width * scale)), int(round(img.height * scale)))
    left = int(round(focus_x * img.width - width / 2))
    top = int(round(focus_y * img.height - height / 2))
    left = max(0, min(left, img.width - width))
    top = max(0, min(top, img.height - height))
    img.crop(left, top, width=width, height=height)


def _whiten(logo: Image) -> None:
    """Recolour the logo to solid white while preserving its alpha (CL2K rule)."""
    logo.colorize(color=Color("white"), alpha=Color("white"))


def _place_logo(
    base: Image,
    logo_bytes: bytes,
    baseline: int,
    max_width: int,
    whiten: bool,
) -> None:
    """Whiten, size and bottom-align the clear logo onto ``base``.

    Width targets ``max_width`` (the 600px guide by default), but height is
    clamped so the logo top never rises above ``LOGO_ZONE_TOP``.
    """
    with Image(blob=logo_bytes) as logo:
        logo.background_color = Color("transparent")
        logo.trim(color=Color("transparent"))  # drop padding -> width == content
        if whiten:
            _whiten(logo)
        target_w = min(max_width, geo.LOGO_WIDTH_MAX)  # never bust the max-width guide
        target_h = int(round(logo.height * target_w / logo.width))
        max_h = baseline - geo.LOGO_ZONE_TOP
        if target_h > max_h:
            target_h = max_h
            target_w = int(round(logo.width * target_h / logo.height))
        logo.resize(target_w, target_h, filter="lanczos")
        base.composite(
            logo,
            left=geo.CENTER_X - target_w // 2,
            top=baseline - target_h,
        )


def _draw_text(
    base: Image,
    text: str,
    center_y: int,
    font_path: Optional[str],
    font_size: int,
    kerning: float = 0.0,
) -> None:
    """Draw centred white text with its vertical centre at ``center_y``."""
    with Drawing() as draw:
        if font_path:
            draw.font = font_path
        draw.font_size = font_size
        draw.fill_color = Color("white")
        draw.text_alignment = "center"
        if kerning:
            draw.text_kerning = kerning
        # Wand anchors text on the baseline; nudge down ~0.35em to centre it.
        draw.text(geo.CENTER_X, int(center_y + font_size * 0.35), text)
        draw(base)


def _draw_border(base: Image) -> None:
    """Composite the default white frame (DAPS rule)."""
    bw = geo.BORDER_WIDTH
    with Drawing() as draw:
        draw.fill_color = Color(geo.BORDER_COLOR)
        draw.stroke_width = 0
        draw.rectangle(left=0, top=0, width=geo.CANVAS_W, height=bw)
        draw.rectangle(left=0, top=geo.CANVAS_H - bw, width=geo.CANVAS_W, height=bw)
        draw.rectangle(left=0, top=0, width=bw, height=geo.CANVAS_H)
        draw.rectangle(left=geo.CANVAS_W - bw, top=0, width=bw, height=geo.CANVAS_H)
        draw(base)


# ----- public ----------------------------------------------------------------
def generate_text_logo(
    title: str,
    font_path: Optional[str] = None,
    font_px: int = 200,
    color: str = "white",
) -> bytes:
    """Render ``title`` as an ALL-CAPS transparent wordmark (text-logo fallback).

    Used only when no real clear logo is found (TMDB -> fanart -> here). The
    result is fed through the normal logo path, so it is width-normalised to the
    600px logo box like any clear logo — keeping every CL2K poster logo-shaped
    rather than switching to baked-on MM2K title text.
    """
    text = (title or "").upper()
    font = font_path or geo.resolve_font(bold=True)
    with Image(width=3000, height=600, background=Color("transparent")) as img:
        with Drawing() as draw:
            if font:
                draw.font = font
            draw.font_size = font_px
            draw.fill_color = Color(color)
            draw.text_alignment = "center"
            draw.text(1500, int(300 + font_px * 0.35), text)
            draw(img)
        img.trim()
        img.format = "png"
        return img.make_blob()


def render_cl2k(
    *,
    backdrop_bytes: bytes,
    kind: str,
    logo_bytes: Optional[bytes] = None,
    title: str = "",
    season_text: str = "",
    logo_max_width: int = geo.LOGO_WIDTH_STD,
    whiten: bool = True,
    font_path: Optional[str] = None,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
) -> bytes:
    """Render a CL2K poster and return JPEG bytes.

    ``kind`` is one of ``movie`` / ``show`` / ``collection`` / ``season``. A
    clear logo is preferred; when none is supplied (or usable) the ``title`` is
    drawn as all-caps text in the logo area (MM2K fallback). ``focus_x``/
    ``focus_y`` (0..1) choose which part of the wide backdrop is kept when it is
    cover-cropped to the 2:3 canvas (0.5/0.5 = centre).
    """
    kind = kind.lower()
    baseline = geo.logo_baseline(kind)
    label_font = font_path or geo.resolve_font(bold=False)
    title_font = font_path or geo.resolve_font(bold=True)

    with Image(blob=backdrop_bytes) as base:
        _cover_resize(base, geo.CANVAS_W, geo.CANVAS_H, focus_x, focus_y)

        with Image(filename=str(geo.GRADIENT_PNG)) as grad:
            base.composite(grad, left=0, top=0)

        if not logo_bytes and title:
            # No clear logo found (TMDB -> fanart exhausted): synthesise a
            # typeset wordmark and place it through the same logo path so the
            # poster stays logo-shaped.
            logo_bytes = generate_text_logo(title, title_font)
        if logo_bytes:
            _place_logo(base, logo_bytes, baseline, logo_max_width, whiten)

        label_kerning = geo.tracking_to_kerning(geo.LABEL_TRACKING)
        if kind == "collection":
            _draw_text(base, "COLLECTION", geo.COLLECTION_LABEL_Y, label_font,
                       geo.LABEL_FONT_PX, kerning=label_kerning)
        elif kind == "season" and season_text:
            _draw_text(base, season_text.upper(), geo.SEASON_TEXT_Y, label_font,
                       geo.LABEL_FONT_PX, kerning=label_kerning)

        _draw_border(base)

        base.format = "jpeg"
        base.compression_quality = geo.OUTPUT_QUALITY
        return base.make_blob()


def overlay_label(
    image_bytes: bytes,
    text: str,
    center_y: Optional[int] = None,
    font_path: Optional[str] = None,
) -> bytes:
    """Draw a CL2K-style label (white, centred, tracked Arial) onto an existing
    image and return JPEG bytes.

    Used to re-text a finished poster — e.g. swap a season year — without running
    the full CL2K render (no logo/gradient/border added). ``center_y`` defaults to
    the locked CL2K season-label y; pass another value to match a custom poster's
    band. Pairs with AI text-removal: erase the old label, then draw the new one
    here so the new text is always crisp and in the CL2K font.
    """
    if center_y is None:
        center_y = geo.SEASON_TEXT_Y
    font = font_path or geo.resolve_font(bold=False)
    with Image(blob=image_bytes) as base:
        _draw_text(
            base,
            (text or "").upper(),
            int(center_y),
            font,
            geo.LABEL_FONT_PX,
            kerning=geo.tracking_to_kerning(geo.LABEL_TRACKING),
        )
        base.format = "jpeg"
        base.compression_quality = geo.OUTPUT_QUALITY
        return base.make_blob()


def apply_border(image_bytes: bytes) -> bytes:
    """Composite the default 26px white CL2K frame onto a finished poster.

    Used by the save-as-is paths (re-text / finished-poster upload / Drive .psd) so
    a borderless poster still satisfies the DAPS white-border rule, mirroring the
    frame ``render_cl2k`` bakes in. The frame is painted inset over the canvas
    edges, so re-applying it to an already-26px-white-bordered poster is a no-op.
    Returns JPEG bytes.
    """
    with Image(blob=image_bytes) as base:
        _draw_border(base)
        base.format = "jpeg"
        base.compression_quality = geo.OUTPUT_QUALITY
        return base.make_blob()


# ----- CLI harness (P1 visual check) -----------------------------------------
def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Render a CL2K poster (visual check).")
    ap.add_argument("--backdrop", required=True, help="source backdrop image")
    ap.add_argument("--logo", help="clear logo (PNG with alpha)")
    ap.add_argument("--kind", default="movie", choices=["movie", "show", "collection", "season"])
    ap.add_argument("--title", default="", help="title for the text fallback")
    ap.add_argument("--season-text", default="", help="e.g. 'Season 1'")
    ap.add_argument("--width", type=int, default=geo.LOGO_WIDTH_STD, help="logo width (600 or 800)")
    ap.add_argument("--no-whiten", action="store_true", help="keep the logo's original colours")
    ap.add_argument("--font", help="font file for text")
    ap.add_argument("--out", required=True, help="output .jpg path")
    args = ap.parse_args()

    with open(args.backdrop, "rb") as fh:
        backdrop = fh.read()
    logo = None
    if args.logo:
        with open(args.logo, "rb") as fh:
            logo = fh.read()

    blob = render_cl2k(
        backdrop_bytes=backdrop,
        kind=args.kind,
        logo_bytes=logo,
        title=args.title,
        season_text=args.season_text,
        logo_max_width=args.width,
        whiten=not args.no_whiten,
        font_path=args.font,
    )
    with open(args.out, "wb") as fh:
        fh.write(blob)
    print(f"wrote {args.out} ({len(blob)} bytes)")


if __name__ == "__main__":
    main()
