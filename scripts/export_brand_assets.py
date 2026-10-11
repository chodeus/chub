#!/usr/bin/env python3
"""Export the CHUB vector artwork to the app's PNG and ICO assets.

Requires rsvg-convert (librsvg) and Pillow. Run from any directory:
    python scripts/export_brand_assets.py
"""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
BRANDING = ROOT / "assets" / "branding"
PUBLIC = ROOT / "frontend" / "public" / "img"


def render(source: Path, size: int) -> Image.Image:
    result = subprocess.run(
        ["rsvg-convert", "--width", str(size), "--height", str(size), str(source)],
        check=True,
        capture_output=True,
    )
    with Image.open(io.BytesIO(result.stdout)) as image:
        return image.convert("RGBA")


def main() -> None:
    if shutil.which("rsvg-convert") is None:
        raise SystemExit("Install librsvg (rsvg-convert) before exporting brand assets.")

    logo = ROOT / "assets" / "chub-logo.svg"
    render(logo, 1024).save(ROOT / "assets" / "chub-logo.png", optimize=True)
    shutil.copyfile(logo, PUBLIC / "chub-logo.svg")
    shutil.copyfile(ROOT / "assets" / "chub-logo.png", PUBLIC / "chub-logo.png")
    for name in ("chub-mascot-wink", "chub-mascot-white", "chub-mascot-indigo"):
        render(BRANDING / f"{name}.svg", 1024).save(
            BRANDING / f"{name}.png", optimize=True
        )

    favicon = BRANDING / "chub-favicon.svg"
    shutil.copyfile(favicon, PUBLIC / "favicon.svg")
    sizes = (16, 32, 48, 64)
    frames = [render(favicon if size <= 32 else logo, size) for size in sizes]
    for size, frame in zip(sizes, frames, strict=True):
        frame.save(PUBLIC / f"favicon-{size}x{size}.png", optimize=True)
    frames[-1].save(
        PUBLIC / "favicon.ico",
        sizes=[(size, size) for size in sizes],
        append_images=frames[:-1],
    )

    # Apple touch icons use an opaque tile; browsers use the transparent mark.
    tile = Image.new("RGBA", (180, 180), "#110b28")
    tile.alpha_composite(render(logo, 148), (16, 16))
    tile.convert("RGB").save(PUBLIC / "apple-touch-icon.png", optimize=True)

    for name, width in (
        ("chub-github-header", 1800),
        ("chub-github-header-light", 1800),
        ("chub-social-preview", 1280),
    ):
        result = subprocess.run(
            ["rsvg-convert", "--width", str(width), str(BRANDING / f"{name}.svg")],
            check=True,
            capture_output=True,
        )
        with Image.open(io.BytesIO(result.stdout)) as image:
            image.save(BRANDING / f"{name}.png", optimize=True)

    print("Exported mascots, GitHub headers/social preview, favicons and Apple touch icon.")


if __name__ == "__main__":
    main()
