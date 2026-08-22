"""Locked CL2K poster geometry — the single source of truth for the layout.

Every value here was extracted directly from the community ``CL2K_template.psd``
(canvas 1000x1500 @ 72dpi): layer bounds, Photoshop ruler guides, and the
gradient alpha ramp (sampled down the centre column). The DAPS "create posters
the right way" rules and the CL2K style notes (DAPS gdrives.md) are encoded
alongside so the renderer and the frontend guideline overlay both read from one
place and never drift.

Do not hand-tune these values — if the template ever changes, re-extract from
the PSD. See memory ``cl2k-poster-maker-spec`` for the extraction method.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

# ----- canvas ----------------------------------------------------------------
CANVAS_W = 1000
CANVAS_H = 1500
DPI = 72
ASPECT = (2, 3)

# ----- logo placement (px on the 1000x1500 canvas) ---------------------------
CENTER_X = 500
LOGO_WIDTH_STD = 600  # guide "Main Logo Width" (x200->800). Refs render ~666.
LOGO_WIDTH_RECOMMENDED = 700  # creator's own extra guide (x150->850) — "the one I
#                                use the most for logo width"; the maker's default.
LOGO_WIDTH_MAX = 800  # guide "Max Logo Width" (x100->900) — hard cap
# CL2K rule: "only leave the Main-Logo *text* area if the logo is too small or
# unreadable". A clear logo whose trimmed content is narrower than this would need
# heavy upscaling to reach the logo box and render fuzzy, so we reject it and draw
# the title wordmark instead. ~0.57x the default 700px box, i.e. up to ~1.75x
# plain upscale; below the gate the sidecar's super-resolution rescue
# (ai_logo_upscale) gets a shot before the text fallback.
LOGO_MIN_WIDTH = 400

# Logo-trim cutoff: alpha <= this is padding, above is content. An explicit
# threshold, NOT ImageMagick trim fuzz (HDRI builds cut fuzz at sqrt(2)x).
LOGO_TRIM_ALPHA = 8

# ----- automatic logo sizing --------------------------------------------------
# Ported from PosterFlow's Photopea panel (dweagle/posterflow, computeLogoGeometry),
# which sizes a logo from its own pixel area and projected height instead of a flat
# width. That matters because a flat LOGO_WIDTH_RECOMMENDED under-sizes wide
# wordmarks — hand-made CL2K references run ~846-881px — while over-sizing tall
# or square artwork, which then gets height-clamped anyway. PosterFlow feeds a
# NEUTRAL density constant rather than measuring ink coverage (aspect and pixel
# area dominate the result), and this mirrors that; the parameter is kept so a
# caller can pass a measured value later.
LOGO_AUTO_CEILING_SMALL = 0.85  # source below 0.2 MP
LOGO_AUTO_CEILING_MID = 0.84
LOGO_AUTO_CEILING_LARGE = 0.93  # source above 1.5 MP
LOGO_AUTO_REF_H = 90  # reference projected height, px on a 1000px-wide canvas
LOGO_AUTO_FALLOFF = 0.40  # exponent applied to refH / projected height
LOGO_AUTO_FLOOR = 0.58  # never narrower than this fraction of the canvas
LOGO_AUTO_DENSITY = 0.30  # the neutral ink fraction the curve is tuned around
LOGO_AUTO_WIDE_FRAC = 0.60  # past this width the height cap tightens
LOGO_AUTO_WIDE_MAX_H = 225  # px on a 1500px-tall canvas


def auto_logo_size(
    src_w: int, src_h: int, baseline: int, density: float = LOGO_AUTO_DENSITY
) -> tuple:
    """Target ``(width, height)`` for a clear logo, from its own shape.

    Wide artwork is allowed out toward the 800px max guide but capped shorter;
    tall artwork is pulled narrower by the projected-height falloff so it fits
    the 1100->baseline zone without being clipped. Aspect ratio is preserved.
    """
    if src_w <= 0 or src_h <= 0:
        return LOGO_WIDTH_RECOMMENDED, 0
    px = src_w * src_h
    if px < 200_000:
        ceiling = LOGO_AUTO_CEILING_SMALL
    elif px > 1_500_000:
        ceiling = LOGO_AUTO_CEILING_LARGE
    else:
        ceiling = LOGO_AUTO_CEILING_MID

    proj_h = src_h * (LOGO_WIDTH_MAX / src_w)  # height if drawn at the max guide
    ref_h = CANVAS_W * (LOGO_AUTO_REF_H / 1000.0)
    ratio = ceiling * (ref_h / max(proj_h, ref_h)) ** LOGO_AUTO_FALLOFF
    floor = LOGO_AUTO_FLOOR + max(0.0, density - LOGO_AUTO_DENSITY) * 0.10
    target_w = round(CANVAS_W * max(floor, min(ceiling, ratio)))

    zone_h = baseline - LOGO_ZONE_TOP
    wide = target_w > round(CANVAS_W * LOGO_AUTO_WIDE_FRAC)
    max_h = round(CANVAS_H * (LOGO_AUTO_WIDE_MAX_H / 1500.0)) if wide else zone_h
    if density < LOGO_AUTO_DENSITY:  # sparse artwork carries a larger box
        mult = 1.0 + ((LOGO_AUTO_DENSITY - density) / LOGO_AUTO_DENSITY) * 0.15
        target_w = min(round(target_w * mult), LOGO_WIDTH_MAX)
        max_h = min(round(max_h * mult), zone_h)
    elif density > 0.60:  # dense artwork reads heavy, so tighten it
        t = (density - 0.60) / 0.40
        target_w = round(target_w * (1.0 - t * 0.10))
        max_h = round(CANVAS_H * (LOGO_AUTO_WIDE_MAX_H / 1500.0) * (1.0 - t * 0.55))

    scale = target_w / src_w
    if src_h * scale > max_h:
        scale = max_h / src_h
    if src_w * scale > LOGO_WIDTH_MAX:
        scale = LOGO_WIDTH_MAX / src_w
    return max(1, round(src_w * scale)), max(1, round(src_h * scale))
# Verified against the PSDs in refs/ (template + 3 finished posters, 2026-06-13):
# all four embed identical guides — y = 1100 ("Main Logo Height"), 1319
# ("Collection Logo Bottom"), 1352 ("Main Logo Bottom"), 1375 ("Gradient
# Darkest") — and every finished poster's LOGO layer bottoms out at EXACTLY
# 1352 (Wonka's boxy logo fills the full 1100→1352 zone). The old 1300 came
# from measuring two off-template JPG refs; don't regress to it.
LOGO_ZONE_TOP = 1100  # "Main Logo Height" — logos must not extend above this y
MAIN_LOGO_BOTTOM = 1352  # "Main Logo Bottom" — movie/show/season clear-logo bottom
COLLECTION_LOGO_BOTTOM = 1319  # "Collection Logo Bottom" (COLLECTION label below it)

# ----- interactive control ranges --------------------------------------------
# One source of truth for the maker's size/position/zoom sliders: the API request
# models validate against these (pydantic Field/Form ge/le), the renderers clamp
# to them, and the frontend mirrors them (CONTROL_RANGES in Cl2kMakerPage.jsx —
# keep both in sync). logo_scale relaxes the height clamp; logo_y_offset shifts the
# logo off its baseline; zoom enlarges/shrinks the framed backdrop.
LOGO_SCALE_MIN, LOGO_SCALE_MAX = 0.25, 3.0
LOGO_Y_OFFSET_MIN, LOGO_Y_OFFSET_MAX = -600, 200
ZOOM_MIN, ZOOM_MAX = 0.5, 3.0
# The one vertical framing control; 0 = centred crop. Negative pans up into real
# source only, positive pans down and may edge-extend into the gradient zone.
V_POS_MIN, V_POS_MAX = -1.0, 1.0


@dataclass(frozen=True)
class Framing:
    """How a backdrop is fitted to the canvas — one bundle for every art path.

    These travel together and are only meaningful together: the identical set
    crosses api -> module -> renderer untouched. Bundled because they were
    threaded as six separate parameters through four layers, so each new knob
    cost a signature edit at ~29 sites; add the seventh here instead.

    The API wire format stays FLAT (the frontend posts focus_x/zoom/... as
    scalars) — the request models keep their own fields and build one of these
    at the endpoint boundary.
    """

    focus_x: float = 0.5  # 0..1 horizontal focal point; 0.5 = centre
    fit_mode: str = "cover"  # cover (crop to fill) | fit (contain) | extend (AI)
    v_pos: float = 0.0  # -1..1, 0 = centred (fit/extend read it 0..1 top-anchored)
    zoom: float = 1.0  # scale relative to the cover/fit baseline
    mirror: bool = False  # flip the artwork horizontally, at the end of framing
    # fit/extend only: isolates the subject region before the fit. render_framed_art
    # (square + background art) has no crop stage and ignores this.
    crop: Optional[Tuple[float, float, float, float]] = None

# ----- logo whitening (CL2K two-tone) -----------------------------------------
# Real CL2K logos are black & white, not flat white silhouettes: coloured/bright
# fills go pure white while the artwork's dark keylines and interior accents stay
# black (verified against a creator poster: the colored TMDB DBS-Broly logo with
# exactly this mapping reproduces their white logo, including the black SUPER
# badge). Two passes over the colored clear logo:
#  1. key = max(HSL saturation, lightness), leveled to near-binary — saturated or
#     bright pixels white, dark unsaturated keylines black.
#  2. local-contrast: pixels much darker in luma than their gaussian-blurred
#     neighborhood flip back to black — recovers same-saturation interior details
#     a per-pixel rule can't see (the star inside the Dragon Ball "O").
# If the result would be mostly black (a dark unsaturated logo would vanish into
# the gradient) fall back to the flat white silhouette.
WHITEN_KEY_BLACK = 0.30  # level black point of the max(sat,light) key
WHITEN_KEY_WHITE = 0.40  # level white point (steep ramp = two-tone)
# Neighborhood blur sigma (fraction of logo width) for the keyline pass. Kept
# small so the "darker-than-neighborhood" test resolves a CRISP thin keyline; a
# wide blur (the old 0.025 ≈ 45px) turned every tonal transition on a busy
# multicoloured logo — e.g. Dragon Ball GT — into a soft muddy black halo. Wide
# dark BODIES (which a small blur would leave white-cored) are instead filled by
# logo_extract.fill_dark_bodies, a shape-based post-pass, not by widening this.
WHITEN_DETAIL_SIGMA = 0.008
WHITEN_DETAIL_LO = 0.14  # darker-than-neighborhood ramp start (luma delta)
WHITEN_DETAIL_HI = 0.22  # ...and full-black point
WHITEN_FALLBACK_MEAN = 0.30  # opaque-area key mean below this -> flat white

# ----- text bands ------------------------------------------------------------
# Template type layers (refs/ PSDs): COLLECTION bbox y=1338-1362 → centre 1350;
# SEASON/SPECIALS/LIMITED bbox y=1428-1452 → centre 1440.
COLLECTION_LABEL_Y = 1350  # centre of "COLLECTION", just below the collection logo
SEASON_TEXT_Y = 1440  # centre of the season/specials band

# ----- gradient --------------------------------------------------------------
# Vertical transparent->black ramp, sampled straight out of the template's own
# flattened composite (its POSTER group is empty, so above the border the
# composite alpha IS the gradient). Measured 2026-07-28: fully opaque from
# y=1374, which agrees with the PSD's "Gradient Darkest Line" guide (y=1375) to
# within a pixel. The fill layer is dithered, so a single column first lifts off
# zero at y=1038 while the column-averaged ramp the asset ships does so at
# y=1037; these constants describe the ASSET, which is what actually renders.
#
# An earlier comment here claimed the PSD "blacks out from y~839" and therefore
# contradicted its own guide, and gradient.png was hand-generated from a
# smoothstep starting at y=780 to work around that. No reading of the template
# reproduces y~839; the substitute ramp darkened 240px higher than the template
# (alpha 79/255 at y=1000 where the template is still perfectly clear). Don't
# reinstate it. Regenerate with scripts/gen_cl2k_gradient.py.
GRADIENT_START_Y = 1037
GRADIENT_FULL_BLACK_Y = 1374

# ----- typography ------------------------------------------------------------
# Exact values read from the PSD type layers.
#  - Labels (COLLECTION / SEASON / SPECIALS) from CL2K_template.psd: Arial
#    *Regular*, 32px @72dpi, white, centred, tracking 800 (600 for the long
#    "COMPLETE LIMITED SERIES"). Tracking is Photoshop's 1/1000-em unit.
#  - Title fallback from the MM2K poster.psd ("MIDDLE BOTTOM" slot): Arial
#    *Bold*, 97px main / 48px secondary, white, centred, tracking 0.
# Real Arial is provided in-container by ttf-mscorefonts-installer and is
# already present on macOS dev. Arial is proprietary — never commit it.
LABEL_FONT_PX = 32
LABEL_TRACKING = 800  # COLLECTION / SEASON / SPECIALS
LABEL_TRACKING_LONG = 600  # "COMPLETE LIMITED SERIES" (longer string)
LABEL_BANNER_LONG = "COMPLETE LIMITED SERIES"  # the one template label at 600
TITLE_FONT_PX = 97  # main title line (logo-less fallback)
TITLE_FONT_PX_SMALL = 48  # secondary title line
TITLE_CENTER_Y = 1319  # centre of the MM2K "MIDDLE BOTTOM" band (1284-1354)
TEXT_COLOR = "white"

# Real-Arial candidates, first existing wins (mscorefonts in-container, macOS dev).
# Liberation Sans is Arial-metric-compatible — a guaranteed last resort so a host
# without mscorefonts doesn't silently render ImageMagick's default typeface.
_ARIAL_REGULAR_CANDIDATES = (
    "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
)
_ARIAL_BOLD_CANDIDATES = (
    "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
)


def resolve_font(bold: bool = False) -> Optional[str]:
    """Return the first available real-Arial path (bold or regular), else None.

    None lets ImageMagick fall back to its default font.
    """
    for path in _ARIAL_BOLD_CANDIDATES if bold else _ARIAL_REGULAR_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def tracking_to_kerning(tracking: int, font_px: int = LABEL_FONT_PX) -> float:
    """Convert Photoshop tracking (1/1000 em) to ImageMagick pixel kerning."""
    return tracking / 1000.0 * font_px


def label_tracking(text: str) -> int:
    """Photoshop tracking for a bottom-band label.

    Every type layer in the template is tracked 800 EXCEPT
    ``COMPLETE LIMITED SERIES``, which drops to 600 so it fits the width. This
    used to be approximated with ``len(text) > 16``, which is wrong in both
    directions: the template's own spelled-out season labels are longer than
    that ("SEASON FIFTY-NINE" is 17), so roughly a third of all seasons were
    silently tightened to 600. Anything AS LONG AS the template's own long
    banner falls back to 600 — a different 23-character label is at least as
    wide as COMPLETE LIMITED SERIES and needs the same relief — so this is a
    length test, not a name match.
    """
    txt = (text or "").upper()
    if len(txt) >= len(LABEL_BANNER_LONG):
        return LABEL_TRACKING_LONG
    return LABEL_TRACKING


# ----- border ----------------------------------------------------------------
# The template's BORDER LAYER is an effects-only layer (fill opacity 0) carrying
# TWO effects: a white Stroke (Style=Inside, Size=25px, Normal, 100%) and a black
# Inner Glow (Multiply, 70%, technique Softer, source Edge, choke 50, size 45px,
# range 50%, contour Linear). The glow is what makes the frame read as a window
# cut into the art rather than a decal laid on top of it; it ships as a pre-baked
# alpha field (INNER_GLOW_PNG) because a gaussian fit does not reproduce
# Photoshop's Softer/choke curve. 26 was borrowed from border_replacerr's own
# config default, which is unrelated to the CL2K stroke — don't restore it.
BORDER_WIDTH = 25  # PSD FrFX Stroke: Style=Inside, Size=25px
BORDER_COLOR = "white"
GLOW_REACH = 48  # glow alpha reaches 0 exactly 48px in from the canvas edge

# ----- output (DAPS rules) ---------------------------------------------------
OUTPUT_EXT = ".jpg"  # lowercase, per DAPS
# Real CL2K community posters encode at ~q99 with NO chroma subsampling (4:4:4).
# The old q88 (+ libjpeg's default 4:2:0) made our output visibly softer and ~3x
# smaller than a hand-made poster. q99 + 4:4:4 matches the hand-made reference
# encode exactly.
OUTPUT_QUALITY = 99  # was 88→95; match hand-made CL2K reference exactly
JPEG_SAMPLING_FACTOR = "1x1,1x1,1x1"  # 4:4:4 — no chroma subsampling (full colour)
JPEG_PROGRESSIVE = True  # progressive scan (SOF2), as hand-made refs encode.
# Purely the storage byte-order, NOT a quality change (same pixels); matches the
# reference convention and is often marginally smaller.
TEXT_UPPERCASE = True  # text is ALWAYS all-caps

# ----- bundled assets --------------------------------------------------------
ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "cl2k"
GRADIENT_PNG = ASSET_DIR / "gradient.png"
INNER_GLOW_PNG = ASSET_DIR / "inner_glow.png"

# ----- guideline overlay (consumed by the frontend preview) ------------------
# Each entry: (label, orientation, position). "x" = vertical line, "y" = horizontal.
GUIDES = (
    ("Max logo width", "x", 100),
    ("Recommended logo width 700", "x", 150),
    ("Logo width 600", "x", 200),
    ("Centre", "x", CENTER_X),
    ("Logo width 600", "x", 800),
    ("Recommended logo width 700", "x", 850),
    ("Max logo width", "x", 900),
    ("Logo zone top", "y", LOGO_ZONE_TOP),
    ("Main logo bottom", "y", MAIN_LOGO_BOTTOM),
    ("Collection logo bottom", "y", COLLECTION_LOGO_BOTTOM),
    ("Gradient darkest", "y", GRADIENT_FULL_BLACK_Y),
)


def logo_baseline(kind: str) -> int:
    """Return the logo bottom baseline for a media kind."""
    return COLLECTION_LOGO_BOTTOM if kind.lower() == "collection" else MAIN_LOGO_BOTTOM
