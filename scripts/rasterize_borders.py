#!/usr/bin/env python3
"""Rasterize holiday border SVGs to 1000x1500 PNGs at Docker build time."""

# PNGs are gitignored build artifacts, not committed sources; cairosvg is
# installed and removed inside the builder stage (deploy/docker/Dockerfile).

from __future__ import annotations

import sys
from pathlib import Path

try:
    import cairosvg
except ImportError:
    print("cairosvg not installed. Run: pip install cairosvg", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
BORDERS_DIR = REPO_ROOT / "backend" / "assets" / "borders"
TARGET_W, TARGET_H = 1000, 1500


def main() -> int:
    if not BORDERS_DIR.exists():
        print(f"No borders directory at {BORDERS_DIR}", file=sys.stderr)
        return 1

    svgs = sorted(BORDERS_DIR.rglob("*.svg"))
    if not svgs:
        print(f"No SVGs found in {BORDERS_DIR}", file=sys.stderr)
        return 1

    converted = 0
    skipped = 0
    for svg in svgs:
        png = svg.with_suffix(".png")
        if png.exists() and png.stat().st_mtime >= svg.stat().st_mtime:
            skipped += 1
            continue
        cairosvg.svg2png(
            url=str(svg),
            write_to=str(png),
            output_width=TARGET_W,
            output_height=TARGET_H,
        )
        rel = svg.relative_to(REPO_ROOT)
        print(f"  rasterized {rel}")
        converted += 1

    print(f"Done. {converted} converted, {skipped} up-to-date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
