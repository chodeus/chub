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

from typing import Optional, Tuple

from wand.color import Color
from wand.drawing import Drawing
from wand.image import Image

from backend.util.cl2k import color, geometry as geo


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


def _apply_crop(
    img: Image, crop: Optional[Tuple[float, float, float, float]]
) -> None:
    """Crop ``img`` in place to a normalized ``(x, y, w, h)`` region (0..1), or no-op.

    Clamped to the image bounds. Shared by the fit + extend framings to isolate the
    subject region of a wide backdrop before scaling.
    """
    if not crop:
        return
    cx, cy, cw, ch = crop
    x = max(0, min(int(round(cx * img.width)), img.width - 1))
    y = max(0, min(int(round(cy * img.height)), img.height - 1))
    w = max(1, min(int(round(cw * img.width)), img.width - x))
    h = max(1, min(int(round(ch * img.height)), img.height - y))
    img.crop(x, y, width=w, height=h)


def _extend_fill(img: Image, width: int, fill_h: int, from_top: bool) -> bytes:
    """Build a ``width``×``fill_h`` edge-extend fill from ``img``'s top or bottom strip.

    BOTH fills sample only a THIN edge strip, so the first fill row matches the
    photo's edge row and the seam is invisible (C0-continuous). A thick strip
    would put content from well inside the photo right at the seam — a visible
    brightness step where the fill meets the photo (the template gradient is only
    ~70% black at typical seam heights, so it doesn't hide it). A *bottom* fill is
    additionally faded to black toward the canvas edge so it merges into the CL2K
    gradient/black; a *top* fill is NOT faded (the CL2K top has no gradient).
    Returns PNG bytes.
    """
    if from_top:
        strip_h = max(2, min(img.height, 12))  # thin: the sky edge, not the heads
        src_top = 0
    else:
        strip_h = max(2, min(img.height, 24))  # thin: the edge row, not the scene
        src_top = img.height - strip_h
    with img.clone() as s:
        s.crop(0, src_top, width=width, height=strip_h)
        s.resize(width, fill_h, filter="triangle")
        s.blur(radius=0, sigma=max(8.0, fill_h / 24.0))
        if not from_top:
            # Fade DOWN to black (white at the seam -> black at the canvas edge).
            with Image(width=width, height=fill_h, pseudo="gradient:white-black") as ramp:
                s.composite(ramp, left=0, top=0, operator="multiply")
        s.format = "png"
        return s.make_blob()


def _blend_seam(img: Image, width: int, seam_y: int, half: int = 10) -> None:
    """Soft-blur a thin horizontal band across ``seam_y`` so the photo→fill seam
    is imperceptible. Even a thin-strip fill lands a few luminance units off the
    photo's edge row (the blur shifts it), and in the near-black gradient zone a
    ~3-unit row step still reads as a faint line on a good display."""
    top = max(0, seam_y - half)
    band_h = min(2 * half, img.height - top)
    if band_h <= 2:
        return
    with img.clone() as band:
        band.crop(0, top, width=width, height=band_h)
        band.blur(radius=0, sigma=half / 2.0)
        img.composite(band, left=0, top=top)


def _fit_resize(
    img: Image,
    width: int,
    height: int,
    crop: Optional[Tuple[float, float, float, float]] = None,
    v_pos: float = 0.0,
) -> None:
    """Contain-fit ``img`` to ``width`` and place it on a black canvas — the CL2K
    "fit" framing, in place.

    Unlike :func:`_cover_resize` (which scales up and crops the *sides* to fill the
    2:3 canvas — cutting off subjects spread across a wide 16:9 backdrop), this
    scales the image *down* so its full width is preserved (everyone stays in
    frame) and fills the empty band(s). This reproduces how a poster artist fits a
    wide key-art into the 2:3 frame.

    ``v_pos`` (0..1) positions the photo vertically when it's shorter than the
    canvas: 0 = top-anchored (default), 1 = bottom-anchored, 0.4 ≈ headroom above
    the subjects. The freed space is edge-extended — **sky upward** above the photo
    (no black fade; the CL2K top has no gradient) and **faded to black downward**
    below it (so it merges into the gradient/logo zone). ``crop`` (``x, y, w, h``
    0..1) optionally isolates the subject region before fitting.
    """
    _apply_crop(img, crop)
    new_h = int(round(img.height * width / img.width))
    img.resize(width, new_h, filter="lanczos")
    v_pos = max(0.0, min(1.0, v_pos))
    if new_h >= height:
        # Taller than the canvas: keep the v_pos-chosen vertical slice.
        top = int(round(v_pos * (new_h - height)))
        img.crop(0, top, width=width, height=height)
        return
    # Shorter than the canvas: position the photo and edge-extend the freed band(s).
    gap = height - new_h
    top_off = int(round(v_pos * gap))
    bot_h = gap - top_off
    top_blob = _extend_fill(img, width, top_off, from_top=True) if top_off > 0 else None
    bot_blob = _extend_fill(img, width, bot_h, from_top=False) if bot_h > 0 else None
    img.background_color = Color("black")
    if top_off > 0:
        img.splice(width=0, height=top_off, x=0, y=0)  # push photo down
    img.extent(width=width, height=height, x=0, y=0)  # pad bottom to full height
    if top_blob:
        with Image(blob=top_blob) as t:
            img.composite(t, left=0, top=0)
        _blend_seam(img, width, top_off)
    if bot_blob:
        with Image(blob=bot_blob) as b:
            img.composite(b, left=0, top=top_off + new_h)
        _blend_seam(img, width, top_off + new_h)


def fit_extend_canvas(
    backdrop_bytes: bytes,
    crop: Optional[Tuple[float, float, float, float]] = None,
    width: int = geo.CANVAS_W,
    height: int = geo.CANVAS_H,
    feather: int = 28,
) -> Tuple[bytes, Optional[bytes]]:
    """Prepare the canvas + mask for AI outpaint ("extend" framing).

    Fits the (optionally cropped) backdrop to the canvas *width* and top-anchors it,
    leaving the empty bottom band for an AI inpainter to fill so the subjects stay
    full-size (no shrink, no side-crop) — the artist's "extend the bottom, crop the
    wasted top" trick. Returns ``(canvas_png, mask_png)`` where the mask is white
    (=generate) over the empty band and black (=keep) over the photo, feathered at
    the seam. Returns ``(canvas_png, None)`` when the fitted photo already fills the
    height — nothing to extend, the caller should just fit/cover it.

    The mask convention matches :mod:`text_removal` (white = fill), so the canvas +
    mask feed straight into ``text_removal.remove_text`` for any provider.
    """
    with Image(blob=backdrop_bytes) as img:
        _apply_crop(img, crop)
        new_h = int(round(img.height * width / img.width))
        img.resize(width, new_h, filter="lanczos")
        if new_h >= height:
            img.crop(0, 0, width=width, height=height)
            img.format = "png"
            return img.make_blob(), None
        img.background_color = Color("black")
        img.extent(width=width, height=height, x=0, y=0)
        img.format = "png"
        canvas_png = img.make_blob()

    # Mask: white over the empty band (start a little above the seam so the AI
    # blends into the photo edge), black over the kept photo, soft-feathered.
    band_top = max(0, new_h - feather)
    with Image(width=width, height=height, background=Color("black")) as mask:
        with Drawing() as draw:
            draw.fill_color = Color("white")
            draw.rectangle(left=0, top=band_top, width=width, height=height - band_top)
            draw(mask)
        mask.blur(radius=0, sigma=feather / 2.0)
        mask.format = "png"
        mask_png = mask.make_blob()
    return canvas_png, mask_png


def _whiten(logo: Image) -> None:
    """Recolour the logo to solid white while preserving its alpha (CL2K rule)."""
    logo.colorize(color=Color("white"), alpha=Color("white"))


def process_logo(logo_bytes: bytes, *, whiten: bool = True) -> Tuple[bytes, int, int]:
    """Trim transparent padding and (optionally) whiten a clear logo.

    Returns ``(png_bytes, width, height)`` for the *trimmed* result — the exact
    bytes and dimensions :func:`_place_logo` would size and place. The frontend
    uses this for the live logo overlay: drawing these bytes at the box derived
    from ``width``/``height`` + the logo geometry matches the rendered placement
    pixel-for-pixel, so the size/position sliders preview instantly without a
    server render per drag.
    """
    with Image(blob=logo_bytes) as logo:
        logo.background_color = Color("transparent")
        logo.trim(color=Color("transparent"))
        if whiten:
            _whiten(logo)
        logo.format = "png"
        return logo.make_blob(), logo.width, logo.height


def logo_is_usable(logo_bytes: bytes, min_width: int = geo.LOGO_MIN_WIDTH) -> bool:
    """True if the clear logo is sharp enough to place at the CL2K logo box.

    Measures the logo's *trimmed* content width (transparent padding removed, the
    same trim :func:`_place_logo` does) and rejects anything narrower than
    ``min_width`` — those would have to be upscaled heavily to the ~600px box and
    render fuzzy. Per the CL2K rule, a too-small logo should yield to drawn title
    text instead. Returns True on any decode error (fail open — don't drop a logo
    we simply couldn't measure)."""
    try:
        with Image(blob=logo_bytes) as logo:
            logo.background_color = Color("transparent")
            logo.trim(color=Color("transparent"))
            return logo.width >= min_width
    except Exception:
        return True


def _place_logo(
    base: Image,
    logo_bytes: bytes,
    baseline: int,
    max_width: int,
    whiten: bool,
    logo_scale: float = 1.0,
    logo_y_offset: int = 0,
) -> None:
    """Whiten, size and bottom-align the clear logo onto ``base``.

    Width targets ``max_width`` (the 600px guide by default), but height is
    clamped so the logo top never rises above ``LOGO_ZONE_TOP``. ``logo_scale``
    relaxes that height clamp (only): the template's LOGO group is a placeholder
    sized by eye, and a hand-made poster lets a tall/boxy logo (< ~3:1 aspect,
    e.g. a sticker design) break the y=1100 top guide rather than shrink to an
    unreadable stamp. 1.0 = the strict guide box; the width caps always apply.

    ``logo_y_offset`` shifts the placement (px; positive = down) without changing
    the size — the template's own note ("only leave the Main-Logo area if the
    logo text is too small or unreadable") treats the vertical as judgement, and
    hand-made posters hang oversized logos below the bottom guide (measured
    Deuce Bigalow: top on the y=1100 line, bottom at y≈1349).
    """
    logo_scale = max(0.25, min(float(logo_scale or 1.0), 3.0))
    logo_y_offset = max(-600, min(int(logo_y_offset or 0), 200))
    with Image(blob=logo_bytes) as logo:
        logo.background_color = Color("transparent")
        logo.trim(color=Color("transparent"))  # drop padding -> width == content
        if whiten:
            _whiten(logo)
        target_w = min(max_width, geo.LOGO_WIDTH_MAX)  # never bust the max-width guide
        target_h = int(round(logo.height * target_w / logo.width))
        max_h = int(round((baseline - geo.LOGO_ZONE_TOP) * logo_scale))
        if target_h > max_h:
            target_h = max_h
            target_w = int(round(logo.width * target_h / logo.height))
        logo.resize(target_w, target_h, filter="lanczos")
        # Offset moves placement only; keep the logo fully on the canvas.
        top = baseline - target_h + logo_y_offset
        top = max(0, min(top, base.height - target_h))
        base.composite(
            logo,
            left=geo.CENTER_X - target_w // 2,
            top=top,
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


def _encode_jpeg(base: Image) -> bytes:
    """Encode a Wand image to JPEG at the CL2K quality with NO chroma subsampling
    (4:4:4), matching hand-made CL2K posters (which use ~q99 / full colour). The
    default libjpeg 4:2:0 subsampling softens coloured edges, so we force 4:4:4."""
    base.format = "jpeg"
    base.compression_quality = geo.OUTPUT_QUALITY
    base.options["jpeg:sampling-factor"] = geo.JPEG_SAMPLING_FACTOR
    # Embed a standard sRGB profile so colour-managed viewers render the (sRGB)
    # pixels correctly instead of stretching an untagged file into their gamut.
    base.profiles["icc"] = color.srgb_icc_bytes()
    if geo.JPEG_PROGRESSIVE:
        # Write a progressive (SOF2) JPEG to match the hand-made reference
        # convention. Quality is unaffected — only the scan order changes.
        # NOTE: Wand's `interlace_scheme` property sets image->interlace, but the
        # JPEG writer reads image_info->interlace; only MagickSetInterlaceScheme
        # sets that, so the property alone produces a baseline file. 6 =
        # JPEGInterlace in MagickCore's InterlaceType enum.
        from wand.api import library

        library.MagickSetInterlaceScheme(base.wand, 6)
    return base.make_blob()


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
    logo_scale: float = 1.0,
    logo_y_offset: int = 0,
    whiten: bool = True,
    font_path: Optional[str] = None,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    fit_mode: str = "cover",
    crop: Optional[Tuple[float, float, float, float]] = None,
    v_pos: float = 0.0,
    band_label: str = "",
    place_logo: bool = True,
) -> bytes:
    """Render a CL2K poster and return JPEG bytes.

    ``kind`` is one of ``movie`` / ``show`` / ``collection`` / ``season``. A
    clear logo is preferred; when none is supplied (or usable) the ``title`` is
    drawn as all-caps text in the logo area (MM2K fallback).

    ``band_label`` draws an explicit banner in the bottom label band (e.g.
    ``COMPLETE LIMITED SERIES`` or ``SPECIALS``), overriding the automatic
    COLLECTION / season label. Long strings use the tighter PSD tracking.

    ``fit_mode`` controls how the backdrop fills the 2:3 canvas:

    - ``"cover"`` (default): scale up and crop to fill; ``focus_x``/``focus_y``
      (0..1) choose which part is kept (0.5/0.5 = centre). Best when the subject
      already fills a roughly 2:3 region.
    - ``"fit"``: scale the backdrop *down* to the canvas width and top-anchor it
      on black, keeping the full width so subjects spread across a wide backdrop
      all stay in frame (the artist technique). ``crop`` (``x, y, w, h`` in 0..1)
      optionally isolates the subject region first; the black bottom band is the
      gradient/logo zone.
    """
    kind = kind.lower()
    baseline = geo.logo_baseline(kind)
    label_font = font_path or geo.resolve_font(bold=False)
    title_font = font_path or geo.resolve_font(bold=True)

    with Image(blob=backdrop_bytes) as base:
        if fit_mode == "fit":
            _fit_resize(base, geo.CANVAS_W, geo.CANVAS_H, crop, v_pos)
        else:
            _cover_resize(base, geo.CANVAS_W, geo.CANVAS_H, focus_x, focus_y)

        with Image(filename=str(geo.GRADIENT_PNG)) as grad:
            base.composite(grad, left=0, top=0)

        # ``place_logo=False`` renders the logo-less base (backdrop + gradient +
        # label + border) the frontend overlays a live logo on top of, so the
        # size/position sliders move the logo instantly without re-rendering. The
        # logo is baked in only on a real generate (or when a text-wordmark
        # fallback is needed, which the overlay can't reproduce client-side).
        if place_logo:
            if not logo_bytes and title:
                # No clear logo found (TMDB -> fanart exhausted): synthesise a
                # typeset wordmark and place it through the same logo path so the
                # poster stays logo-shaped.
                logo_bytes = generate_text_logo(title, title_font)
            if logo_bytes:
                _place_logo(
                    base, logo_bytes, baseline, logo_max_width, whiten, logo_scale,
                    logo_y_offset,
                )

        label_kerning = geo.tracking_to_kerning(geo.LABEL_TRACKING)
        if band_label:
            # Explicit banner (e.g. COMPLETE LIMITED SERIES). Long strings use the
            # tighter tracking the PSD specifies so they fit the width.
            txt = band_label.upper()
            tracking = geo.LABEL_TRACKING_LONG if len(txt) > 16 else geo.LABEL_TRACKING
            _draw_text(base, txt, geo.SEASON_TEXT_Y, label_font, geo.LABEL_FONT_PX,
                       kerning=geo.tracking_to_kerning(tracking))
        elif kind == "collection":
            _draw_text(base, "COLLECTION", geo.COLLECTION_LABEL_Y, label_font,
                       geo.LABEL_FONT_PX, kerning=label_kerning)
        elif kind == "season" and season_text:
            _draw_text(base, season_text.upper(), geo.SEASON_TEXT_Y, label_font,
                       geo.LABEL_FONT_PX, kerning=label_kerning)

        _draw_border(base)

        return _encode_jpeg(base)


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
        return _encode_jpeg(base)


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
        return _encode_jpeg(base)


def overlay_logo(
    image_bytes: bytes,
    logo_bytes: bytes,
    *,
    kind: str = "movie",
    logo_max_width: int = geo.LOGO_WIDTH_STD,
    logo_scale: float = 1.0,
    logo_y_offset: int = 0,
    whiten: bool = True,
) -> bytes:
    """Composite a clear logo onto a finished poster at the locked CL2K baseline.

    Trims, whitens and width-normalises the logo to the CL2K guides exactly like
    a fresh render (via the shared :func:`_place_logo`), then bottom-aligns it on
    the kind's baseline. Used to add a TMDB / fanart / custom logo onto an
    already-finished uploaded poster (the save-as-is flow), where no full render
    happens. The poster should already be the locked 1000×1500 canvas. Returns
    JPEG bytes.
    """
    baseline = geo.logo_baseline((kind or "movie").lower())
    with Image(blob=image_bytes) as base:
        _place_logo(
            base, logo_bytes, baseline, logo_max_width, whiten, logo_scale,
            logo_y_offset,
        )
        return _encode_jpeg(base)


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
