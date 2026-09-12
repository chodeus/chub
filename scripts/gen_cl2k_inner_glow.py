"""Bake the CL2K inner-glow field -> backend/assets/cl2k/inner_glow.png."""

# Needs refs/CL2K_template.psd (gitignored): composite alpha = glow while POSTER is empty.
# Run from repo root: PYTHONPATH=. python scripts/gen_cl2k_inner_glow.py [template.psd]

import sys

import numpy as np
from PIL import Image
from psd_tools import PSDImage

from backend.util.cl2k import geometry as geo

DEFAULT_PSD = "refs/CL2K_template.psd"
# A row that is inside the artwork area but above the gradient, so the only thing
# contributing alpha is the left/right glow.
CLEAN_ROW = 700


def _edge_profile(alpha: np.ndarray, reach: int, stroke: int) -> np.ndarray:
    """Edge glow alpha; the stroke px (opaque white) clamp to the first glow sample."""
    prof = alpha[CLEAN_ROW, :reach].astype(np.int16).copy()
    prof[:stroke] = prof[stroke]
    return prof


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PSD
    composite = PSDImage.open(src).topil()
    if composite is None:
        raise SystemExit(f"{src} has no flattened composite to read")
    alpha = np.asarray(composite.convert("RGBA"))[:, :, 3]

    w, h = geo.CANVAS_W, geo.CANVAS_H
    if alpha.shape != (h, w):
        raise SystemExit(f"{src} is {alpha.shape[1]}x{alpha.shape[0]}, expected {w}x{h}")
    # An RGB-flattened composite gets synthetic alpha 255 and would overwrite the
    # asset with solid black; the glow never reaches the interior, so it must be 0.
    interior = alpha[CLEAN_ROW, geo.GLOW_REACH : w - geo.GLOW_REACH]
    if interior.max() > 0:
        raise SystemExit(
            f"{src}: alpha is non-zero {geo.GLOW_REACH}px in from the edge "
            f"(max {interior.max():.0f}) — that is not the glow's alpha channel; "
            f"refusing to overwrite {geo.INNER_GLOW_PNG.name}"
        )

    reach, stroke = geo.GLOW_REACH, geo.BORDER_WIDTH
    prof = _edge_profile(alpha, reach, stroke)

    # Corners are NOT max(edge, edge) (the blur pools both edges): use the measured
    # corner block, with stroke rows/columns clamped like the edge profile.
    corner = alpha[:reach, :reach].astype(np.int16).copy()
    corner[:stroke, :] = corner[stroke, :][None, :]
    corner[:, :stroke] = corner[:, stroke][:, None]

    quad = np.zeros((h // 2, w // 2), np.int16)
    quad[:, :reach] = prof[None, :]
    quad[:reach, :] = np.maximum(quad[:reach, :], prof[:, None])
    quad[:reach, :reach] = corner

    field = np.zeros((h, w), np.int16)
    field[: h // 2, : w // 2] = quad
    field[: h // 2, w // 2 :] = quad[:, ::-1]
    field[h // 2 :, :] = field[: h // 2, :][::-1, :]

    out = np.dstack([np.zeros(field.shape, np.uint8)] * 3 + [field.astype(np.uint8)])
    Image.fromarray(out).save(geo.INNER_GLOW_PNG)
    print(
        f"wrote {geo.INNER_GLOW_PNG} ({w}x{h}, reach {reach}px, "
        f"peak alpha {int(field.max())})"
    )


if __name__ == "__main__":
    main()
