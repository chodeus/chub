"""Bake the CL2K gradient overlay -> backend/assets/cl2k/gradient.png."""

# Reads the template's own composite alpha; needs refs/CL2K_template.psd (gitignored).
# Run from repo root: PYTHONPATH=. python scripts/gen_cl2k_gradient.py [template.psd]

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
    # An RGB-flattened composite gets synthetic alpha 255 and would bake a solid black
    # field; every row above GRADIENT_START_Y (slice end is exclusive) must be clear.
    probe = alpha[geo.GLOW_REACH : geo.GRADIENT_START_Y, w // 2]
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
    if not profile[band].any():
        raise SystemExit(
            f"{src}: no gradient alpha above y={geo.GRADIENT_FULL_BLACK_Y}; "
            f"refusing to overwrite {geo.GRADIENT_PNG.name}"
        )
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
