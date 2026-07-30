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

import itertools
from typing import List, Optional, Tuple

from wand.color import Color
from wand.drawing import Drawing
from wand.image import COMPOSITE_OPERATORS, Image

from backend.util.cl2k import color, geometry as geo
from backend.util.cl2k.logo_extract import (
    fill_dark_bodies,
    flatten_3d_logo,
    ink_color_edges,
)

# ImageMagick 7 renamed CopyOpacity to CopyAlpha; wand exposes whichever the
# linked library supports (IM6 = Debian/CI runners, IM7 = homebrew dev). Both
# take the source's intensity as the new alpha when the source has no alpha
# channel — which is how _whiten/_flip_regions use it.
_COPY_ALPHA = "copy_alpha" if "copy_alpha" in COMPOSITE_OPERATORS else "copy_opacity"


# ----- helpers ---------------------------------------------------------------
def _v_pos_top(src_h: int, height: int, v_pos: float) -> int:
    """Crop top for ``v_pos`` (-1..1, 0 = centred) within a source that overflows.

    Plain source-bounded panning — no black band, so callers that cannot hide one
    (every path except the cover-fill's downward extend) share this.
    """
    centre = max(0, min(int(round(0.5 * src_h - height / 2)), src_h - height))
    v_pos = max(geo.V_POS_MIN, min(float(v_pos or 0.0), geo.V_POS_MAX))
    span = centre if v_pos <= 0 else (src_h - height) - centre
    return max(0, min(centre + int(round(v_pos * span)), src_h - height))


def _cover_resize(
    img: Image,
    width: int,
    height: int,
    focus_x: float = 0.5,
    v_pos: float = 0.0,
    zoom: float = 1.0,
) -> None:
    """Resize + crop ``img`` in place to exactly width×height (cover fill).

    ``focus_x`` (0..1) chooses what stays in frame horizontally: the focal point
    of the scaled image is centred in the crop, clamped to the edges. 0.5 is the
    centre crop (the default).

    ``v_pos`` (-1..1) is the ONE vertical control; 0 is the centred crop.
    Positive pushes the framed image *up* without changing its size: it pans down
    through any source remaining below the crop and, once that runs out,
    edge-extends the bottom row faded to black — a band that lands in the CL2K
    gradient/black zone, so it stays hidden. Negative pans the other way, but only
    into real source above the crop: the gradient is bottom-only, so an extended
    band at the top would be plainly visible. A cover-filled 16:9 backdrop is
    exactly ``height`` tall, so it has no upward travel at all until ``zoom`` > 1
    — that is the geometry, not a clamp we could lift.

    ``zoom`` (0.5..3.0) scales relative to the cover-fill baseline. 1.0 = plain
    cover (unchanged). >1 crops tighter (punch in). <1 scales the art *below* the
    fill so more of a high-resolution source stays visible — the art is then
    centred on black and the freed bands merge into the CL2K gradient/border.
    """
    zoom = max(geo.ZOOM_MIN, min(float(zoom or 1.0), geo.ZOOM_MAX))
    scale = max(width / img.width, height / img.height) * zoom
    img.resize(
        max(1, int(round(img.width * scale))), max(1, int(round(img.height * scale)))
    )

    # Zoom-out: the scaled art no longer fills the frame. Crop whichever axis
    # still overflows, then centre on black and pad the deficient axis/axes.
    if img.width < width or img.height < height:
        if img.width > width:
            cx = int(round(focus_x * img.width - width / 2))
            cx = max(0, min(cx, img.width - width))
            img.crop(cx, 0, width=width, height=img.height)
        if img.height > height:
            cy = _v_pos_top(img.height, height, v_pos)
            img.crop(0, cy, width=img.width, height=height)
        img.background_color = Color("black")
        off_x = -((width - img.width) // 2) if img.width < width else 0
        off_y = -((height - img.height) // 2) if img.height < height else 0
        img.extent(width=width, height=height, x=off_x, y=off_y)
        return
    left = int(round(focus_x * img.width - width / 2))
    left = max(0, min(left, img.width - width))
    centre_top = max(0, min(int(round(0.5 * img.height - height / 2)), img.height - height))
    v_pos = max(geo.V_POS_MIN, min(float(v_pos or 0.0), geo.V_POS_MAX))
    if v_pos <= 0:
        # Up is source-only (see the docstring): scale into whatever sits above.
        img.crop(
            left,
            centre_top + int(round(v_pos * centre_top)),
            width=width,
            height=height,
        )
        return
    # Pan down through the source still below the crop, then up to ~30% of the
    # canvas past its bottom edge (that band sits in the black gradient zone).
    remaining = img.height - height - centre_top
    black_allow = int(round(height * 0.30))
    top = centre_top + int(round(v_pos * (remaining + black_allow)))
    avail = max(1, min(height, img.height - top))
    img.crop(left, min(top, img.height - 1), width=width, height=avail)
    if avail >= height:
        return
    # Source ran out: edge-extend the (now bottom) row faded to black and pad.
    fill_h = height - avail
    fill = _extend_fill(img, width, fill_h, from_top=False)
    img.background_color = Color("black")
    img.extent(width=width, height=height, x=0, y=0)
    with Image(blob=fill) as b:
        img.composite(b, left=0, top=avail)
    _blend_seam(img, width, avail)


def _apply_crop(img: Image, crop: Optional[Tuple[float, float, float, float]]) -> None:
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
            with Image(
                width=width, height=fill_h, pseudo="gradient:white-black"
            ) as ramp:
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


def _zoom_fit(img: Image, width: int, zoom: float) -> int:
    """Scale ``img`` to ``width`` × ``zoom`` and crop the horizontal overflow back
    to ``width`` (centred). ``zoom`` 1.0 = plain fit-to-width; >1 enlarges the
    subject (the sides spill past the canvas and are trimmed). Returns the scaled
    height. Shared by the fit + extend framings so a wide backdrop's subject isn't
    forced down to the full-width (tiny) size."""
    zoom = max(1.0, min(float(zoom or 1.0), 3.0))
    target_w = int(round(width * zoom))
    new_h = int(round(img.height * target_w / img.width))
    img.resize(target_w, new_h, filter="lanczos")
    if target_w > width:
        img.crop(int(round((target_w - width) / 2)), 0, width=width, height=new_h)
    return new_h


def _fit_resize(
    img: Image,
    width: int,
    height: int,
    crop: Optional[Tuple[float, float, float, float]] = None,
    v_pos: float = 0.0,
    zoom: float = 1.0,
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
    the subjects. Deliberately NOT :func:`_cover_resize`'s -1..1-centred-on-0
    scale: here the photo is *anchored*, not panned, so 0 means top and there is
    nothing for a negative value to name. The freed space is edge-extended —
    **sky upward** above the photo (no black fade; the CL2K top has no gradient)
    and **faded to black downward** below it (so it merges into the gradient/logo
    zone). ``crop`` (``x, y, w, h`` 0..1) optionally isolates the subject region
    before fitting. ``zoom`` (>=1) enlarges the subject above the full-width fit
    (sides crop), so a wide backdrop doesn't shrink to a tiny strip.
    """
    _apply_crop(img, crop)
    new_h = _zoom_fit(img, width, zoom)
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
    zoom: float = 1.0,
    v_pos: float = 0.0,
) -> Tuple[bytes, Optional[bytes]]:
    """Prepare the canvas + mask for AI outpaint ("extend" framing).

    Fits the (optionally cropped) backdrop to the canvas *width* and top-anchors it,
    leaving the empty bottom band for an AI inpainter to fill so the subjects stay
    full-size (no shrink, no side-crop) — the artist's "extend the bottom, crop the
    wasted top" trick. ``zoom`` (>=1) enlarges the subject above the full-width fit
    (sides crop) so it isn't a tiny strip; the AI then fills only the smaller gap.
    Returns ``(canvas_png, mask_png)`` where the mask is white (=generate) over the
    empty band and black (=keep) over the photo, feathered at the seam. Returns
    ``(canvas_png, None)`` when the fitted photo already fills the height — nothing
    to extend, the caller should just fit/cover it (``v_pos`` picks the slice).
    ``v_pos`` is top-anchored 0..1 here, matching :func:`_fit_resize` rather than
    :func:`_cover_resize`.

    The mask convention matches :mod:`text_removal` (white = fill), so the canvas +
    mask feed straight into ``text_removal.remove_text`` for any provider.
    """
    with Image(blob=backdrop_bytes) as img:
        _apply_crop(img, crop)
        new_h = _zoom_fit(img, width, zoom)
        if new_h >= height:
            top = int(round(max(0.0, min(1.0, v_pos)) * (new_h - height)))
            img.crop(0, top, width=width, height=height)
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


def _whiten(logo: Image, flat_fallback: bool = True) -> bool:
    """Recolour the logo to the CL2K two-tone: white fills, black keylines.

    Per-pixel key + a local-contrast pass (constants and rationale in
    :mod:`geometry`, "logo whitening"). Alpha is preserved throughout; a logo
    that would come out mostly black falls back to the flat white silhouette
    (suppressed via ``flat_fallback=False`` when the invert pass follows — a
    flat silhouette inverts to full transparency, i.e. nothing).

    Returns True when the flat-white fallback fired — the caller then skips the
    colour-edge / dark-body post-passes, which would re-mark that clean silhouette.
    """
    q = logo.quantum_range
    with logo.clone() as alpha:
        alpha.alpha_channel = "extract"
        # 1. two-tone key: max(saturation, lightness), leveled near-binary.
        with logo.clone() as hsl:
            hsl.alpha_channel = "off"
            hsl.transform_colorspace("hsl")
            with hsl.channel_images["green"] as sat:
                key = sat.clone()
            try:
                with hsl.channel_images["blue"] as light:
                    key.composite(light, operator="lighten")
            except Exception:
                key.close()
                raise
        try:
            # NB: Wand level() points are fractions of quantum range (0..1).
            key.level(black=geo.WHITEN_KEY_BLACK, white=geo.WHITEN_KEY_WHITE)
            # 2. flip pixels much darker (luma) than their neighborhood to black.
            with logo.clone() as luma:
                luma.alpha_channel = "off"
                luma.transform_colorspace("gray")
                with luma.clone() as detail:
                    detail.blur(
                        radius=0, sigma=max(2.0, logo.width * geo.WHITEN_DETAIL_SIGMA)
                    )
                    detail.composite(luma, operator="minus_src")  # blurred - luma
                    detail.level(black=geo.WHITEN_DETAIL_LO, white=geo.WHITEN_DETAIL_HI)
                    detail.negate()
                    key.composite(detail, operator="multiply")
            # Mostly-black result? The flat silhouette is the only readable option.
            a_mean = alpha.mean / q
            with key.clone() as masked:
                masked.composite(alpha, operator="multiply")
                k_mean = masked.mean / q
            if (
                flat_fallback
                and a_mean > 0.001
                and k_mean / a_mean < geo.WHITEN_FALLBACK_MEAN
            ):
                logo.colorize(color=Color("white"), alpha=Color("white"))
                return True  # fell back to the flat silhouette
            key.transform_colorspace("srgb")
            key.alpha_channel = "off"
            key.composite(alpha, operator=_COPY_ALPHA)
            logo.composite(key, left=0, top=0, operator="copy")
            return False
        finally:
            key.close()


def _flip_regions(logo: Image, mask_bytes: bytes) -> None:
    """Invert black↔white inside the brushed regions (logo touch-up), in place.

    The mask is brushed over the PROCESSED (trimmed + whitened) logo — white
    strokes on transparency, at display resolution — and is resized to the
    logo here. A global two-tone map fundamentally cannot decide interior
    accents that share saturation AND luma with their surroundings (the same
    red is fill in one place and accent in another on real logos), so the user
    paints the few regions the keymap gets wrong. Alpha is untouched — the
    flip only swaps fill colours, never reshapes the logo. Decode failures are
    a no-op (the un-flipped logo renders).
    """
    try:
        mask = Image(blob=mask_bytes)
    except Exception:
        return
    try:
        # Brush strokes are white-on-transparent: flatten onto black so the
        # mask reads white=flip / black=keep, then match the logo's size.
        mask.background_color = Color("black")
        mask.alpha_channel = "remove"
        mask.transform_colorspace("gray")
        mask.resize(logo.width, logo.height)
        with logo.clone() as flipped:
            flipped.negate()  # RGB only; alpha untouched
            # Confine the flip: flipped's alpha := original alpha × mask.
            with logo.clone() as alpha:
                alpha.alpha_channel = "extract"
                alpha.composite(mask, operator="multiply")
                flipped.composite(alpha, operator=_COPY_ALPHA)
            logo.composite(flipped, left=0, top=0)
    except Exception:
        pass  # fail open: an unreadable mask must not break the render
    finally:
        mask.close()


def _erase_regions(logo: Image, mask_bytes: bytes) -> None:
    """Make brushed regions transparent (manual logo cleanup), in place.

    The mask is brushed over the PROCESSED logo — white strokes on transparency,
    at display resolution — and is resized here. Extraction and whitening can keep
    stray bits a clean logo shouldn't have (a leftover glyph, a ® mark, edge
    speckle); the user paints those away. White = erase; everything unpainted
    keeps its alpha. Colours are untouched — only alpha is reduced. Decode
    failures are a no-op (the un-erased logo renders).
    """
    try:
        mask = Image(blob=mask_bytes)
    except Exception:
        return
    try:
        # Brush strokes are white-on-transparent: flatten onto black so the mask
        # reads white=erase / black=keep, match the logo's size, then negate so it
        # becomes an alpha multiplier (erase->0, keep->full).
        mask.background_color = Color("black")
        mask.alpha_channel = "remove"
        mask.transform_colorspace("gray")
        mask.resize(logo.width, logo.height)
        mask.negate()
        with logo.clone() as alpha:
            alpha.alpha_channel = "extract"
            alpha.composite(mask, operator="multiply")  # zero alpha where erased
            logo.composite(alpha, operator=_COPY_ALPHA)
    except Exception:
        pass  # fail open: an unreadable mask must not break the render
    finally:
        mask.close()


def _invert_to_clear(logo: Image) -> None:
    """Invert logo: white → transparent, black → white, in place.

    For plate-style logos (a solid light plate with dark text — e.g. sticker
    art), the two-tone whiten correctly yields a white box with black text,
    which is the OPPOSITE of a clearlogo. This pass makes darkness the
    opacity: black text/keylines come out solid white, the white plate
    vanishes, and grey anti-aliased edges feather naturally. Runs AFTER the
    whiten + touch-up flip, so the brush still rescues mis-keyed regions.
    """
    with logo.clone() as blackness:
        blackness.alpha_channel = "off"
        blackness.transform_colorspace("gray")
        blackness.negate()
        # New alpha = blackness × the original alpha (transparent stays out).
        with logo.clone() as alpha:
            alpha.alpha_channel = "extract"
            blackness.composite(alpha, operator="multiply")
        logo.colorize(color=Color("white"), alpha=Color("white"))  # RGB only
        logo.composite(blackness, operator=_COPY_ALPHA)


def _flat_white(logo: Image) -> None:
    """Paint every opaque pixel pure white, keeping alpha — a flat silhouette.

    Unlike :func:`_whiten` (the two-tone key + keyline pass), this does no
    keying: it is the right tool for already-stylised logos the two-tone pass
    mangles — outline wordmarks and rings, where thin strokes are almost all
    "edge" so the keyline pass blackens them instead of leaving clean fills.
    The result is exactly :func:`_whiten`'s mostly-black fallback, forced.
    """
    logo.colorize(color=Color("white"), alpha=Color("white"))  # RGB only


def _face_only(logo: Image) -> None:
    """Keep a 3D/extruded logo's lit face as a flat white wordmark, in place.

    Unsplittable art falls back to the flat silhouette — never the two-tone pass,
    which is what this mode exists to avoid.
    """
    faced = flatten_3d_logo(logo.make_blob("png"))
    if faced is None:
        _flat_white(logo)
        return
    with Image(blob=faced) as face:
        logo.composite(face, left=0, top=0, operator="copy")
    _trim_logo(logo)  # callers trimmed the OLD silhouette; the extrusion's padding is now free


def _apply_whiten(logo: Image, *, invert: bool) -> None:
    """Two-tone whiten + colour-edge keylines + dark-body fill, in place.

    :func:`_whiten` whitens saturated/light fills and inks thin luma keylines
    crisply. Two post-passes finish the two-tone for cases a per-pixel key can't:
    :func:`ink_color_edges` adds a black separator where two differently-coloured
    fills meet with no outline (else they merge to one white blob), and
    :func:`fill_dark_bodies` blacks in a WIDE dark shape the small keyline blur
    leaves white-cored. Both are no-ops on an already-clean logo (Dragon Ball GT).

    Skipped entirely on the invert path (it makes a clearlogo differently) and
    when the flat-white fallback fired (the post-passes would re-mark that clean
    silhouette). The pre-whiten original is captured only when the passes can run.
    """
    if invert:
        _whiten(logo, flat_fallback=False)
        return
    original_png = logo.make_blob("png")  # colours the post-passes key against
    if _whiten(logo, flat_fallback=True):
        return  # flat-white fallback — leave the clean silhouette untouched
    stepped = ink_color_edges(logo.make_blob("png"), original_png)
    stepped = fill_dark_bodies(stepped, original_png)
    with Image(blob=stepped) as img2:
        logo.composite(img2, left=0, top=0, operator="copy")


def _rasterize_svg_logo(svg_bytes: bytes, target_width: int = 2000) -> bytes:
    """Rasterize an SVG clear-logo to PNG bytes at ~``target_width`` content width.

    CL2K's logo pipeline is raster (Wand). Relying on ImageMagick's own SVG
    delegate is fragile — it is absent from the runtime image (ImageMagick then
    raises ``no decode delegate for image format 'SVG'``), which would 500 any
    title whose best logo is an SVG, and :func:`select_logo` *prefers* SVGs. We
    rasterize with cairosvg instead (pure-Python, the same rasterizer the holiday
    borders use; needs only libcairo2, already present via librsvg2-2). Vectors
    are resolution-free, so ~2000px keeps the logo sharp once scaled to the box.

    Imported lazily so a build without cairosvg surfaces the ImportError to the
    caller's decode-failure fallback (the typeset wordmark) instead of breaking
    module import. cairosvg's default (``unsafe=False``) blocks external-resource
    loading, so a hostile SVG can't read local files or reach the network."""
    import cairosvg

    return cairosvg.svg2png(bytestring=svg_bytes, output_width=target_width)


def _read_logo_image(logo_bytes: bytes) -> Image:
    """Decode logo bytes, rasterizing SVG sources at high density.

    SVG logos are rasterized to PNG via cairosvg at ~2000px content width (see
    :func:`_rasterize_svg_logo`) — Wand's own SVG delegate is unavailable in the
    runtime image. Raster formats pass through untouched.
    """
    head = logo_bytes[:512].lstrip().lower()
    is_svg = head.startswith(b"<svg") or (
        head.startswith(b"<?xml") and b"<svg" in logo_bytes[:2048].lower()
    )
    if not is_svg:
        return Image(blob=logo_bytes)
    return Image(blob=_rasterize_svg_logo(logo_bytes, target_width=2000))


def _trim_logo(logo: Image) -> None:
    """Crop to visible content (alpha > geo.LOGO_TRIM_ALPHA), in place.

    The ONE logo trim — process_logo, logo_is_usable and _place_logo must agree.
    """
    # trim() reports the box in canvas coords, so a source carrying a page offset
    # would push `left` past the image and make crop raise.
    logo.reset_coords()
    with logo.clone() as probe:
        probe.alpha_channel = "extract"  # alpha -> greyscale, so trim sees it
        probe.threshold(geo.LOGO_TRIM_ALPHA / 255.0)
        # All sub-threshold: IM trims a uniform image to 1x1, not to nothing —
        # bail out here (matches the Pillow PSD path's None bbox).
        if probe.mean_channel()[0] <= 0:
            return
        probe.background_color = Color("black")
        probe.trim(color=Color("black"))
        left, top = probe.page_x, probe.page_y
        width, height = probe.width, probe.height
    if width > 0 and height > 0:
        logo.crop(left=left, top=top, width=width, height=height)


def process_logo(
    logo_bytes: bytes,
    *,
    whiten: bool = True,
    flat_white: bool = False,
    logo_3d: bool = False,
    flip_mask_bytes: Optional[bytes] = None,
    erase_mask_bytes: Optional[bytes] = None,
    invert: bool = False,
) -> Tuple[bytes, int, int]:
    """Trim transparent padding and (optionally) whiten a clear logo.

    Returns ``(png_bytes, width, height)`` for the *trimmed* result — the exact
    bytes and dimensions :func:`_place_logo` would size and place. The frontend
    uses this for the live logo overlay: drawing these bytes at the box derived
    from ``width``/``height`` + the logo geometry matches the rendered placement
    pixel-for-pixel, so the size/position sliders preview instantly without a
    server render per drag. ``flip_mask_bytes`` applies the user's black↔white
    touch-up regions (see :func:`_flip_regions`); ``invert`` turns plate-style
    logos into clearlogos (see :func:`_invert_to_clear`).

    Recolour modes rank ``logo_3d`` > ``flat_white`` > ``whiten``.
    """
    with _read_logo_image(logo_bytes) as logo:
        _trim_logo(logo)
        if logo_3d:
            _face_only(logo)
        elif flat_white:
            _flat_white(logo)
        elif whiten:
            _apply_whiten(logo, invert=invert)
        if flip_mask_bytes:
            _flip_regions(logo, flip_mask_bytes)
        # Both white-silhouette modes invert to full transparency, i.e. nothing.
        if invert and not flat_white and not logo_3d:
            _invert_to_clear(logo)
        if erase_mask_bytes:
            _erase_regions(logo, erase_mask_bytes)
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
        with _read_logo_image(logo_bytes) as logo:
            _trim_logo(logo)
            return logo.width >= min_width
    except Exception:
        return True


def _place_logo(
    base: Image,
    logo_bytes: bytes,
    baseline: int,
    max_width: Optional[int],
    whiten: bool,
    logo_scale: float = 1.0,
    logo_y_offset: int = 0,
    flip_mask_bytes: Optional[bytes] = None,
    erase_mask_bytes: Optional[bytes] = None,
    invert: bool = False,
    flat_white: bool = False,
    logo_3d: bool = False,
) -> None:
    """Whiten, size and bottom-align the clear logo onto ``base``.

    The guide-fit box targets ``max_width`` (the 700px recommended guide by
    default) with height clamped so the logo top never rises above
    ``LOGO_ZONE_TOP``. ``logo_scale`` then multiplies that whole box (1.0 =
    strict guides), clamped only to the canvas. The width guides (600/700/800)
    are guidelines, not limits — hand-made references run ~846-881px wide, and
    boxy/sticker designs break the y=1100 top guide rather than shrink to an
    unreadable stamp — so the slider can take ANY logo past the guide box.

    ``logo_y_offset`` shifts the placement (px; positive = down) without changing
    the size. At offset 0 the logo bottom sits exactly on the template's
    "Main Logo Bottom" guide (y=1352; collections use 1319) — finished creator
    PSDs in refs/ all bottom-align there pixel-exact (Deuce Bigalow measured
    y≈1349 too), so the offset is an escape hatch for odd logo artwork, not a
    routine adjustment.
    """
    logo_scale = max(
        geo.LOGO_SCALE_MIN, min(float(logo_scale or 1.0), geo.LOGO_SCALE_MAX)
    )
    logo_y_offset = max(
        geo.LOGO_Y_OFFSET_MIN, min(int(logo_y_offset or 0), geo.LOGO_Y_OFFSET_MAX)
    )
    with _read_logo_image(logo_bytes) as logo:
        _trim_logo(logo)  # drop padding -> width == visible content
        # Mode ranking mirrors process_logo — the overlay must match the render.
        if logo_3d:
            _face_only(logo)
        elif flat_white:
            _flat_white(logo)
        elif whiten:
            _apply_whiten(logo, invert=invert)
        if flip_mask_bytes:
            # Same trimmed/whitened space the touch-up brush was drawn over
            # (process_logo's output) — applied before the resize below.
            _flip_regions(logo, flip_mask_bytes)
        if invert and not flat_white and not logo_3d:
            _invert_to_clear(logo)
        if erase_mask_bytes:
            _erase_regions(logo, erase_mask_bytes)
        if max_width is None:
            # Auto: size from the logo's own shape (see geometry.auto_logo_size).
            target_w, target_h = geo.auto_logo_size(
                logo.width, logo.height, baseline
            )
        else:
            target_w = min(max_width, geo.LOGO_WIDTH_MAX)  # the guide box width
            target_h = int(round(logo.height * target_w / logo.width))
            max_h = baseline - geo.LOGO_ZONE_TOP
            if target_h > max_h:
                target_h = max_h
                target_w = int(round(logo.width * target_h / logo.height))
        # Scale the guide-fit box as a whole; keep it on the canvas (aspect kept).
        target_w = int(round(target_w * logo_scale))
        target_h = int(round(target_h * logo_scale))
        if target_w > base.width:
            target_h = int(round(target_h * base.width / target_w))
            target_w = base.width
        if target_h > base.height:
            target_w = int(round(target_w * base.height / target_h))
            target_h = base.height
        target_w, target_h = max(1, target_w), max(1, target_h)
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
    """Composite the template's BORDER LAYER — inner glow, then the white stroke.

    Reproduces the PSD effects-only layer in Photoshop's own order: the black
    Inner Glow ramps inward from the canvas edge first, then the 25px inside
    Stroke is painted over its innermost band.

    Bounds are given as right/bottom, NOT width/height: ImageMagick's rectangle
    primitive is inclusive of both corners, so ``width=bw`` paints bw+1 px. The
    top and left bands start at 0 so that extra pixel landed inside the canvas,
    while the bottom and right bands started at CANVAS-bw so theirs was clipped
    away — which is what made every poster 27px on the top/left and 26px on the
    bottom/right, and left a 1px white line behind when a downstream border strip
    cropped a symmetric 26.

    The glow is a canvas-sized field, so it is only composited when ``base`` is
    the CL2K canvas; the as-is paths can hand this an arbitrary size, and those
    still get a correctly-sized stroke on all four edges.
    """
    bw = geo.BORDER_WIDTH
    w, h = base.width, base.height
    if (w, h) == (geo.CANVAS_W, geo.CANVAS_H) and geo.INNER_GLOW_PNG.exists():
        with Image(filename=str(geo.INNER_GLOW_PNG)) as glow:
            base.composite(glow, left=0, top=0)
    with Drawing() as draw:
        draw.fill_color = Color(geo.BORDER_COLOR)
        draw.stroke_width = 0
        draw.rectangle(left=0, top=0, right=w - 1, bottom=bw - 1)
        draw.rectangle(left=0, top=h - bw, right=w - 1, bottom=h - 1)
        draw.rectangle(left=0, top=0, right=bw - 1, bottom=h - 1)
        draw.rectangle(left=w - bw, top=0, right=w - 1, bottom=h - 1)
        draw(base)


# ----- public ----------------------------------------------------------------
def _balance_lines(words: List[str], n: int, measure) -> List[str]:
    """Split ``words`` into ``n`` contiguous lines that minimise the widest line.

    ``measure(text)`` returns the rendered width of a string in the chosen font.
    Brute-forces the n-1 cut points (titles are short, so the count is tiny) and
    keeps the most balanced break — so a wrapped wordmark reads as even lines, not
    one long line + one orphan word.
    """
    if n <= 1 or len(words) <= 1:
        return [" ".join(words)]
    if n >= len(words):
        return list(words)
    best: Optional[List[str]] = None
    best_max: Optional[float] = None
    for cuts in itertools.combinations(range(1, len(words)), n - 1):
        groups, prev = [], 0
        for c in (*cuts, len(words)):
            groups.append(" ".join(words[prev:c]))
            prev = c
        widest = max(measure(g) for g in groups)
        if best_max is None or widest < best_max:
            best_max, best = widest, groups
    return best or [" ".join(words)]


def generate_text_logo(
    title: str,
    font_path: Optional[str] = None,
    font_px: int = 200,
    color: str = "white",
    stroke_width: int = 0,
    stroke_color: str = "black",
) -> bytes:
    """Render ``title`` as an ALL-CAPS transparent wordmark (text-logo fallback).

    Used only when no real clear logo is found (TMDB -> fanart -> here). The title
    is balance-wrapped onto 1–3 lines so the block roughly matches the CL2K logo
    box aspect (~3:1, the 600×200 guide) instead of a single tiny strip — a long
    title fills the box on two/three lines like a hand-made wordmark. The result is
    fed through the normal logo path (width-normalised to the 600px box), keeping
    every poster logo-shaped. ``stroke_width`` (px at the internal render size; 0 =
    none) adds a thin outline for legibility over busy art.
    """
    text = " ".join((title or "").upper().split())
    if not text:
        return b""
    font = font_path or geo.resolve_font(bold=True)
    words = text.split()
    # The box the wordmark is normalised into: width 600, height (baseline-zone_top).
    target_aspect = geo.LOGO_WIDTH_STD / max(
        1, geo.MAIN_LOGO_BOTTOM - geo.LOGO_ZONE_TOP
    )

    # Pick the line count whose block aspect (widest line : total height) is closest
    # to the box. Aspect is scale-independent, so measure at a fixed reference size.
    with Image(width=8000, height=2000, background=Color("transparent")) as probe:
        with Drawing() as md:
            if font:
                md.font = font
            md.font_size = 100

            def measure(s: str) -> float:
                return md.get_font_metrics(probe, s, False).text_width or 1.0

            best_lines = [text]
            best_score = None
            for n in range(1, min(3, len(words)) + 1):
                lines = _balance_lines(words, n, measure)
                block_w = max(measure(s) for s in lines)
                block_h = 100 * 1.15 * len(lines)  # line height incl. ~15% spacing
                score = abs(block_w / block_h - target_aspect)
                if best_score is None or score < best_score:
                    best_score, best_lines = score, lines

    # Render the chosen layout, centred, ALL-CAPS, with the optional stroke.
    line_h = int(round(font_px * 1.15))
    n = len(best_lines)
    with Image(
        width=8000, height=line_h * n + 400, background=Color("transparent")
    ) as img:
        with Drawing() as draw:
            if font:
                draw.font = font
            draw.font_size = font_px
            draw.fill_color = Color(color)
            draw.text_alignment = "center"
            if stroke_width > 0:
                draw.stroke_color = Color(stroke_color)
                draw.stroke_width = stroke_width
                draw.stroke_antialias = True
            cx = 4000
            y = 200 + int(font_px * 0.8)
            for s in best_lines:
                draw.text(cx, y, s)
                y += line_h
            draw(img)
        # reset_coords drops the 8000px canvas offset trim would otherwise bake
        # into the PNG — _trim_logo reads page coords and would crop out of bounds.
        img.trim(reset_coords=True)
        img.format = "png"
        return img.make_blob()


def render_framed_art(
    *,
    backdrop_bytes: bytes,
    width: int,
    height: int,
    focus_x: float = 0.5,
    fit_mode: str = "cover",
    v_pos: float = 0.0,
    zoom: float = 1.0,
) -> bytes:
    """Render plain framed artwork at ``width``×``height`` — no gradient/logo/label.

    ``fit_mode`` ``"cover"`` fills the canvas (cropping the overflowing edges);
    ``"fit"`` contains the whole image on black (letterbox). ``zoom`` (0.5–3.0)
    scales from that baseline — raise it in ``fit`` to punch in from contain toward
    a full crop, or in ``cover`` to crop tighter. ``focus_x`` (0..1) pans the window
    horizontally and ``v_pos`` (-1..1, 0 = centred) vertically, where the image
    overflows the canvas; plain black letterbox where it doesn't. There is no
    gradient here to hide an extended band, so ``v_pos`` is source-bounded both
    ways. Encoded at CL2K quality.
    """
    zoom = max(geo.ZOOM_MIN, min(float(zoom or 1.0), geo.ZOOM_MAX))
    with Image(blob=backdrop_bytes) as img:
        base = (
            min(width / img.width, height / img.height)
            if fit_mode == "fit"
            else max(width / img.width, height / img.height)
        )
        scale = base * zoom
        nw = max(1, int(round(img.width * scale)))
        nh = max(1, int(round(img.height * scale)))
        img.resize(nw, nh, filter="lanczos")
        # Place the focal point at the canvas centre; clamp so an axis the image
        # covers shows no needless black, and centre an axis it doesn't (letterbox).
        ox = int(round(width / 2 - focus_x * nw))
        ox = max(min(ox, 0), width - nw) if nw >= width else (width - nw) // 2
        oy = -_v_pos_top(nh, height, v_pos) if nh >= height else (height - nh) // 2
        with Image(width=width, height=height, background=Color("black")) as canvas:
            canvas.composite(img, left=ox, top=oy)
            return _encode_jpeg(canvas)


def render_square_art(
    *,
    backdrop_bytes: bytes,
    size: int = 1000,
    focus_x: float = 0.5,
    fit_mode: str = "cover",
    v_pos: float = 0.0,
    zoom: float = 1.0,
) -> bytes:
    """Render square (1:1) art from a backdrop/poster — just the framed artwork."""
    return render_framed_art(
        backdrop_bytes=backdrop_bytes,
        width=size,
        height=size,
        focus_x=focus_x,
        fit_mode=fit_mode,
        v_pos=v_pos,
        zoom=zoom,
    )


def _framed_inset_base(
    backdrop_bytes: bytes,
    *,
    focus_x: float,
    fit_mode: str,
    crop: Optional[Tuple[float, float, float, float]],
    v_pos: float,
    zoom: float,
) -> Image:
    """Frame the backdrop FULL-BLEED and return a full CANVAS image.

    The template's stroke is Style=Inside on a full-canvas layer, so it paints
    OVER the outer 25px of artwork rather than displacing it. Every finished
    creator poster in refs/ agrees: their POSTER group is (0, 0, 1000, 1500) —
    one is even (0, 0, 1000, 1502) — under a BORDER LAYER of (-2, 0, 1000, 1500).

    This used to inset the art to a 948x1448 inner rect on the theory that the
    border would otherwise clip it. It does clip it, and that is the intent: the
    art is meant to run under the frame at full scale, not be shrunk 5% to fit
    inside it. Insetting also broke the framing UI's contract, since CropFramer
    offers a 2:3 crop box while the inner rect is not 2:3.

    render_cl2k and frame_backdrop both go through here, so they stay
    pixel-identical (the PSD POSTER-layer parity the exporter relies on).
    """
    base = Image(
        width=geo.CANVAS_W, height=geo.CANVAS_H, background=Color(geo.BORDER_COLOR)
    )
    with Image(blob=backdrop_bytes) as art:
        if fit_mode == "fit":
            _fit_resize(art, geo.CANVAS_W, geo.CANVAS_H, crop, v_pos, zoom)
        else:
            _cover_resize(art, geo.CANVAS_W, geo.CANVAS_H, focus_x, v_pos, zoom)
        base.composite(art, left=0, top=0)
    return base


def frame_backdrop(
    *,
    backdrop_bytes: bytes,
    focus_x: float = 0.5,
    fit_mode: str = "cover",
    crop: Optional[Tuple[float, float, float, float]] = None,
    v_pos: float = 0.0,
    zoom: float = 1.0,
) -> bytes:
    """Frame a backdrop to the 2:3 canvas exactly as :func:`render_cl2k` would
    and return PNG bytes.

    The PSD exporter uses this for its POSTER layer so the exported document
    matches the rendered poster pixel-for-pixel — the fit/cover/v_pos framings
    (edge-extend fills, seam blending) live only in this module and must not be
    re-implemented elsewhere.
    """
    with _framed_inset_base(
        backdrop_bytes,
        focus_x=focus_x,
        fit_mode=fit_mode,
        crop=crop,
        v_pos=v_pos,
        zoom=zoom,
    ) as base:
        base.format = "png"
        return base.make_blob()


def render_cl2k(
    *,
    backdrop_bytes: bytes,
    kind: str,
    logo_bytes: Optional[bytes] = None,
    title: str = "",
    season_text: str = "",
    logo_max_width: Optional[int] = None,
    logo_scale: float = 1.0,
    logo_y_offset: int = 0,
    logo_flip_bytes: Optional[bytes] = None,  # B/W touch-up regions (mask PNG)
    logo_erase_bytes: Optional[bytes] = None,  # erase regions (mask PNG, white=erase)
    whiten: bool = True,
    flat_white: bool = False,  # paint the logo a flat pure-white silhouette
    logo_3d: bool = False,  # extruded art -> flat-white lit face
    invert: bool = False,  # plate logo -> clearlogo (white->transparent, black->white)
    font_path: Optional[str] = None,
    focus_x: float = 0.5,
    fit_mode: str = "cover",
    crop: Optional[Tuple[float, float, float, float]] = None,
    v_pos: float = 0.0,
    zoom: float = 1.0,
    band_label: str = "",
    place_logo: bool = True,
    text_logo_stroke: int = 0,
) -> bytes:
    """Render a CL2K poster and return JPEG bytes.

    ``kind`` is one of ``movie`` / ``show`` / ``collection`` / ``season``. A
    clear logo is preferred; when none is supplied (or usable) the ``title`` is
    drawn as all-caps text in the logo area (MM2K fallback).

    ``band_label`` draws an explicit banner in the bottom label band (e.g.
    ``COMPLETE LIMITED SERIES`` or ``SPECIALS``), overriding the automatic
    COLLECTION / season label. Long strings use the tighter PSD tracking.

    ``fit_mode`` controls how the backdrop fills the 2:3 canvas:

    - ``"cover"`` (default): scale up and crop to fill; ``focus_x`` (0..1) and
      ``v_pos`` (-1..1) choose which part is kept (0.5/0 = centre). Best when the
      subject already fills a roughly 2:3 region.
    - ``"fit"``: scale the backdrop *down* to the canvas width and top-anchor it
      on black, keeping the full width so subjects spread across a wide backdrop
      all stay in frame (the artist technique). ``crop`` (``x, y, w, h`` in 0..1)
      optionally isolates the subject region first; the black bottom band is the
      gradient/logo zone. ``v_pos`` applies here too, but on :func:`_fit_resize`'s
      0..1 top-anchored scale (0 = top), not cover's -1..1.
    """
    kind = kind.lower()
    baseline = geo.logo_baseline(kind)
    label_font = font_path or geo.resolve_font(bold=False)
    title_font = font_path or geo.resolve_font(bold=True)

    with _framed_inset_base(
        backdrop_bytes,
        focus_x=focus_x,
        fit_mode=fit_mode,
        crop=crop,
        v_pos=v_pos,
        zoom=zoom,
    ) as base:
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
                # poster stays logo-shaped. The wordmark is already white-on-
                # transparent — inverting it would erase it, so invert is real-
                # logo only.
                logo_bytes = generate_text_logo(
                    title, title_font, stroke_width=text_logo_stroke
                )
                invert = False
            if logo_bytes:
                try:
                    _place_logo(
                        base,
                        logo_bytes,
                        baseline,
                        logo_max_width,
                        whiten,
                        logo_scale,
                        logo_y_offset,
                        flip_mask_bytes=logo_flip_bytes,
                        erase_mask_bytes=logo_erase_bytes,
                        invert=invert,
                        flat_white=flat_white,
                        logo_3d=logo_3d,
                    )
                except Exception:
                    # A clear logo we can't decode/place (e.g. an SVG when the SVG
                    # rasterizer is unavailable, or corrupt logo bytes) must never
                    # fail the whole render. Fall back to the typeset wordmark,
                    # which is always placeable, so the poster keeps a title rather
                    # than 500ing. Per-logo brush strokes (flip/erase) belong to the
                    # dropped logo, so they don't carry over to the wordmark.
                    if title:
                        _place_logo(
                            base,
                            generate_text_logo(
                                title, title_font, stroke_width=text_logo_stroke
                            ),
                            baseline,
                            logo_max_width,
                            whiten,
                            logo_scale,
                            logo_y_offset,
                            invert=False,
                            flat_white=flat_white,
                            logo_3d=logo_3d,
                        )

        # Every branch derives its tracking from the label itself, exactly as the
        # PSD exporter does. Pinning collection/season to a flat LABEL_TRACKING
        # would agree today but diverge the moment a season string reaches the
        # long-banner length — 800 here, 600 in the .psd, for the same poster.
        def _label(txt: str, center_y: int) -> None:
            _draw_text(
                base,
                txt,
                center_y,
                label_font,
                geo.LABEL_FONT_PX,
                kerning=geo.tracking_to_kerning(geo.label_tracking(txt)),
            )

        if band_label:
            # Explicit banner (e.g. COMPLETE LIMITED SERIES), which the template
            # tracks tighter than every other label so it fits the width.
            _label(band_label.upper(), geo.SEASON_TEXT_Y)
        elif kind == "collection":
            _label("COLLECTION", geo.COLLECTION_LABEL_Y)
        elif kind == "season" and season_text:
            _label(season_text.upper(), geo.SEASON_TEXT_Y)

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
    txt = (text or "").upper()
    tracking = geo.label_tracking(txt)
    with Image(blob=image_bytes) as base:
        _draw_text(
            base,
            txt,
            int(center_y),
            font,
            geo.LABEL_FONT_PX,
            kerning=geo.tracking_to_kerning(tracking),
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
    logo_max_width: Optional[int] = None,
    logo_scale: float = 1.0,
    logo_y_offset: int = 0,
    whiten: bool = True,
    flat_white: bool = False,
    logo_3d: bool = False,  # extruded art -> flat-white lit face
    invert: bool = False,
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
            base,
            logo_bytes,
            baseline,
            logo_max_width,
            whiten,
            logo_scale,
            logo_y_offset,
            invert=invert,
            flat_white=flat_white,
            logo_3d=logo_3d,
        )
        return _encode_jpeg(base)


# ----- CLI harness (P1 visual check) -----------------------------------------
def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Render a CL2K poster (visual check).")
    ap.add_argument("--backdrop", required=True, help="source backdrop image")
    ap.add_argument("--logo", help="clear logo (PNG with alpha)")
    ap.add_argument(
        "--kind", default="movie", choices=["movie", "show", "collection", "season"]
    )
    ap.add_argument("--title", default="", help="title for the text fallback")
    ap.add_argument("--season-text", default="", help="e.g. 'Season 1'")
    ap.add_argument(
        "--width",
        type=int,
        default=geo.LOGO_WIDTH_RECOMMENDED,
        help="logo width (600 std / 700 recommended / 800 max)",
    )
    ap.add_argument(
        "--no-whiten", action="store_true", help="keep the logo's original colours"
    )
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
