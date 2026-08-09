"""Bake the CL2K inner-glow field -> backend/assets/cl2k/inner_glow.png.

The template's BORDER LAYER carries a black Inner Glow (Multiply, 70%, technique
Softer, source Edge, choke 50, size 45px, range 50%). Photoshop's Softer curve is
a blurred distance field reshaped by choke and range, and fitting it with a
gaussian is not good enough — a least-squares fit through the measured endpoints
is still ~6% out mid-ramp. So the field is read straight out of the template's own
flattened composite instead, which is Photoshop's own answer.

That works because the template's POSTER group is empty: everywhere the gradient
is still clear (y < GRADIENT_START_Y) the composite alpha IS the glow alpha. The
field is symmetric under both mirrors, so a single clean edge profile plus the
top-left corner block reconstructs the whole canvas.

Compositing black at this alpha is mathematically identical to Photoshop's
multiply-black-at-70%: multiply gives B*(1-o) + o*(B*0/255) = B*(1-o), and a
plain `over` of black at alpha a gives B*(1-a). The 70% opacity is already folded
into the stored alpha, so the renderer needs no blend-mode plumbing.

Needs refs/CL2K_template.psd, which is gitignored (copyrighted, local only). The
generated PNG is committed; re-run this only if the template itself changes.

Run from the repo root:
    PYTHONPATH=. python scripts/gen_cl2k_inner_glow.py [path/to/template.psd]
"""

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
    """Glow alpha for the first ``reach`` px in from an edge.

    The outer ``stroke`` px read 255 because the white Stroke is painted over the
    glow there. Their true value is unknowable and irrelevant — the renderer
    repaints the stroke on top — so they are clamped to the first visible glow
    sample rather than left as opaque white.
    """
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
    # A composite flattened to RGB makes convert("RGBA") synthesise alpha 255
    # everywhere; the guards above still pass and this would overwrite a
    # known-good committed asset with a fully opaque field the renderer then
    # composites as solid black. The glow only reaches GLOW_REACH in from each
    # edge, so the interior at the clean row must be fully transparent.
    interior = alpha[CLEAN_ROW, geo.GLOW_REACH : w - geo.GLOW_REACH]
    if interior.max() > 0:
        raise SystemExit(
            f"{src}: alpha is non-zero {geo.GLOW_REACH}px in from the edge "
            f"(max {interior.max():.0f}) — that is not the glow's alpha channel; "
            f"refusing to overwrite {geo.INNER_GLOW_PNG.name}"
        )

    reach, stroke = geo.GLOW_REACH, geo.BORDER_WIDTH
    prof = _edge_profile(alpha, reach, stroke)

    # Corners are NOT max(edge, edge): the Softer blur pools two edges together,
    # so A[25,25] measures 178 where the 1-D profile would predict 139. Take the
    # real corner block (clean — the gradient starts far below it) and clamp the
    # stroke rows/columns the same way.
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
