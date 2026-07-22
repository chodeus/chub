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

from pathlib import Path
from typing import Optional

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
# Vertical transparent->black ramp. The PSD's raster gradient blacks out from
# y~839 — which contradicts both its own "Gradient Darkest Line" guide (y=1375)
# AND real creator output (finished CL2K posters keep the backdrop visible to
# ~90%, measured from references). So gradient.png is *generated* to match the
# references/guide: alpha 0 until ~y=780, smoothstep to fully black by y=1375,
# solid to the bottom. Regenerate with scripts/gen_cl2k_gradient.py.
GRADIENT_START_Y = 780
GRADIENT_FULL_BLACK_Y = 1375

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


# ----- border ----------------------------------------------------------------
BORDER_WIDTH = 26  # default white frame (matches border_replacerr)
BORDER_COLOR = "white"

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
