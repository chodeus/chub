"""Bake the CL2K gradient overlay -> backend/assets/cl2k/gradient.png.

Read straight out of the template's own flattened composite. The template's
POSTER group is empty, so below the glow band and away from the border the
composite alpha IS the gradient alpha — Photoshop's own rasterisation of the
BLACK GRADIENT fill layer, including its non-linear midpoint skew (the
descriptor's transparency stops are 100% @ 20.0% midpoint 50 and 0% @ 95.4%
midpoint 70, which no symmetric easing curve reproduces).

The layer is dithered (Dthr=true), so the profile is averaged across a wide band
of columns and forced monotonic rather than sampled from a single column.

An earlier version of this script generated a smoothstep from y=780 instead, on
the claim that the PSD's own gradient "blacks out at y~839" and contradicted its
"Gradient Darkest Line" guide. It does not: measured, it is clear through y=1037
and fully opaque from y=1374, matching the guide. The substitute ramp darkened
the poster 240px higher than the template.

Needs refs/CL2K_template.psd, which is gitignored (copyrighted, local only). The
generated PNG is committed; re-run this only if the template itself changes.

Run from the repo root:
    PYTHONPATH=. python scripts/gen_cl2k_gradient.py [path/to/template.psd]
"""

import sys

import numpy as np
from PIL import Image
from psd_tools import PSDImage

from backend.util.cl2k import geometry as geo

DEFAULT_PSD = "refs/CL2K_template.psd"


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PSD
    composite = PSDImage.open(src).topil()
    if composite is None:
        raise SystemExit(f"{src} has no flattened composite to read")
    alpha = np.asarray(composite.convert("RGBA"))[:, :, 3].astype(np.float64)

    w, h = geo.CANVAS_W, geo.CANVAS_H
    if alpha.shape != (h, w):
        raise SystemExit(f"{src} is {alpha.shape[1]}x{alpha.shape[0]}, expected {w}x{h}")
    # A composite flattened to RGB makes convert("RGBA") synthesise alpha 255
    # everywhere. Both guards above still pass, and this would then overwrite a
    # known-good committed asset with a fully opaque PNG that the renderer
    # composites as a solid black field over the whole poster. The template's
    # gradient is transparent through the artwork, so demand that.
    probe = alpha[geo.GLOW_REACH : geo.GRADIENT_START_Y - 1, w // 2]
    if probe.max() > 0:
        raise SystemExit(
            f"{src}: alpha is non-zero above y={geo.GRADIENT_START_Y} "
            "(max %.0f) — that is not the gradient's alpha channel; refusing to "
            "overwrite %s" % (probe.max(), geo.GRADIENT_PNG.name)
        )

    # Stay clear of the glow band on every side; average out the fill's dither.
    pad = geo.GLOW_REACH
    profile = alpha[:, pad : w - pad].mean(axis=1)

    ramp = np.zeros(h, np.float64)
    band = slice(pad, geo.GRADIENT_FULL_BLACK_Y)
    ramp[band] = profile[band]
    ramp[geo.GRADIENT_FULL_BLACK_Y :] = 255.0
    # Dither leaves the raw profile very slightly non-monotonic; the ramp itself
    # is monotonic by construction, so clamp it back.
    ramp = np.maximum.accumulate(ramp)

    col = np.rint(ramp).astype(np.uint8)
    field = np.repeat(col[:, None], w, axis=1)
    out = np.dstack([np.zeros(field.shape, np.uint8)] * 3 + [field])
    Image.fromarray(out).save(geo.GRADIENT_PNG)

    first = int(np.argmax(col > 0))
    full = int(np.argmax(col >= 255))
    print(f"wrote {geo.GRADIENT_PNG} ({w}x{h}, clear to y={first - 1}, full black y={full})")


if __name__ == "__main__":
    main()
