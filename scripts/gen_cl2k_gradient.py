"""Generate the CL2K gradient overlay -> backend/assets/cl2k/gradient.png.

The CL2K_template.psd raster gradient blacks out too high (y~839), which
contradicts both its own "Gradient Darkest Line" guide (y=1375) and real creator
output (finished CL2K posters keep the backdrop visible to ~90%, measured from
reference posters). This reproduces the reference-matched ramp instead:
transparent until GRADIENT_START_Y, smoothstep to fully black by
GRADIENT_FULL_BLACK_Y, solid to the bottom.

Run from the repo root:  python scripts/gen_cl2k_gradient.py
"""

from PIL import Image

from backend.util.cl2k import geometry as geo


def _smoothstep(y: int, y0: int, y1: int) -> int:
    t = max(0.0, min(1.0, (y - y0) / (y1 - y0)))
    return round(t * t * (3 - 2 * t) * 255)


def main() -> None:
    w, h = geo.CANVAS_W, geo.CANVAS_H
    y0, y1 = geo.GRADIENT_START_Y, geo.GRADIENT_FULL_BLACK_Y
    alpha = Image.new("L", (1, h))
    alpha.putdata([_smoothstep(y, y0, y1) for y in range(h)])
    alpha = alpha.resize((w, h))
    grad = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    grad.putalpha(alpha)
    grad.save(geo.GRADIENT_PNG)
    print(f"wrote {geo.GRADIENT_PNG} ({w}x{h}, full black by y={y1})")


if __name__ == "__main__":
    main()
