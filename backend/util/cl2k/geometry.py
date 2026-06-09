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
LOGO_WIDTH_STD = 600           # guide "Main Logo Width" (x200->800). Refs render ~666.
LOGO_WIDTH_MAX = 800           # guide "Max Logo Width" (x100->900) — hard cap
LOGO_ZONE_TOP = 1100           # logos must not extend above this y
MAIN_LOGO_BOTTOM = 1300        # movie/show clear-logo bottom (refs measured ~1298)
COLLECTION_LOGO_BOTTOM = 1300  # collection logo bottom (COLLECTION label below it)

# ----- text bands ------------------------------------------------------------
COLLECTION_LABEL_Y = 1345      # centre of "COLLECTION", just below the logo (measured)
SEASON_TEXT_Y = 1440           # centre of season/specials band (PSD; unverified vs refs)

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
LABEL_TRACKING = 800            # COLLECTION / SEASON / SPECIALS
LABEL_TRACKING_LONG = 600       # "COMPLETE LIMITED SERIES" (longer string)
TITLE_FONT_PX = 97              # main title line (logo-less fallback)
TITLE_FONT_PX_SMALL = 48        # secondary title line
TITLE_CENTER_Y = 1319           # centre of the MM2K "MIDDLE BOTTOM" band (1284-1354)
TEXT_COLOR = "white"

# Real-Arial candidates, first existing wins (mscorefonts in-container, macOS dev).
_ARIAL_REGULAR_CANDIDATES = (
    "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)
_ARIAL_BOLD_CANDIDATES = (
    "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def resolve_font(bold: bool = False) -> Optional[str]:
    """Return the first available real-Arial path (bold or regular), else None.

    None lets ImageMagick fall back to its default font.
    """
    for path in (_ARIAL_BOLD_CANDIDATES if bold else _ARIAL_REGULAR_CANDIDATES):
        if Path(path).exists():
            return path
    return None


def tracking_to_kerning(tracking: int, font_px: int = LABEL_FONT_PX) -> float:
    """Convert Photoshop tracking (1/1000 em) to ImageMagick pixel kerning."""
    return tracking / 1000.0 * font_px


# ----- border ----------------------------------------------------------------
BORDER_WIDTH = 26              # default white frame (matches border_replacerr)
BORDER_COLOR = "white"

# ----- output (DAPS rules) ---------------------------------------------------
OUTPUT_EXT = ".jpg"            # lowercase, per DAPS
# Real CL2K community posters encode at ~q99 with NO chroma subsampling (4:4:4).
# The old q88 (+ libjpeg's default 4:2:0) made our output visibly softer and ~3x
# smaller than a hand-made poster. q99 + 4:4:4 matches the hand-made reference
# encode exactly.
OUTPUT_QUALITY = 99            # was 88→95; match hand-made CL2K reference exactly
JPEG_SAMPLING_FACTOR = "1x1,1x1,1x1"  # 4:4:4 — no chroma subsampling (full colour)
JPEG_PROGRESSIVE = True        # progressive scan (SOF2), as hand-made refs encode.
# Purely the storage byte-order, NOT a quality change (same pixels); matches the
# reference convention and is often marginally smaller.
TEXT_UPPERCASE = True          # text is ALWAYS all-caps

# ----- bundled assets --------------------------------------------------------
ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "cl2k"
GRADIENT_PNG = ASSET_DIR / "gradient.png"

# ----- guideline overlay (consumed by the frontend preview) ------------------
# Each entry: (label, orientation, position). "x" = vertical line, "y" = horizontal.
GUIDES = (
    ("Max logo width", "x", 100),
    ("Logo width 600", "x", 200),
    ("Centre", "x", CENTER_X),
    ("Logo width 600", "x", 800),
    ("Max logo width", "x", 900),
    ("Logo zone top", "y", LOGO_ZONE_TOP),
    ("Main logo bottom", "y", MAIN_LOGO_BOTTOM),
    ("Collection logo bottom", "y", COLLECTION_LOGO_BOTTOM),
    ("Gradient darkest", "y", GRADIENT_FULL_BLACK_Y),
)


def logo_baseline(kind: str) -> int:
    """Return the logo bottom baseline for a media kind."""
    return COLLECTION_LOGO_BOTTOM if kind.lower() == "collection" else MAIN_LOGO_BOTTOM
