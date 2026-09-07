"""Decode-size caps for the CL2K image paths — one owner for "how big an image
may we decode", in Pillow (header-checked ceiling) and ImageMagick (wand limits)."""

from __future__ import annotations

import io

from PIL import Image

# Hard decode ceiling. Real art tops out around 8 MP (a 4K backdrop); posters are
# well under 10. Anything past this is a bomb, not artwork.
MAX_MEGAPIXELS = 64
_MAX_PIXELS = MAX_MEGAPIXELS * 1_000_000

# Process-global IM budget: area/memory/map spill to disk past the cap;
# width/height are IM's only hard rejections, so they double as the bomb guard.
_MAGICK_MEMORY = 512 * 1024 * 1024
_MAGICK_MAP = 1024 * 1024 * 1024
_MAGICK_AREA = 512 * 1024 * 1024
_MAGICK_DISK = 4 * 1024 * 1024 * 1024
_MAGICK_MAX_SIDE = 16384


class ImageTooLargeError(ValueError):
    """An image whose header dimensions exceed ``MAX_MEGAPIXELS``."""


def open_bounded(data: bytes, mode: str) -> Image.Image:
    """Decode ``data`` to ``mode``, rejecting oversized headers before any decode."""
    try:
        img = Image.open(io.BytesIO(data))  # lazy — .size is the header, no pixels
    except Image.DecompressionBombError as exc:  # past Pillow's own 2x ceiling
        raise ImageTooLargeError(str(exc)) from exc
    w, h = img.size
    if w * h > _MAX_PIXELS:
        raise ImageTooLargeError(
            f"image is {w}x{h} ({w * h / 1e6:.1f} MP), over the "
            f"{MAX_MEGAPIXELS} MP decode cap"
        )
    return img.convert(mode)


def apply_magick_limits() -> None:
    """Cap ImageMagick's pixel-cache and dimension budget for this process."""
    from wand.resource import limits as magick_limits

    magick_limits["memory"] = _MAGICK_MEMORY
    magick_limits["map"] = _MAGICK_MAP
    magick_limits["area"] = _MAGICK_AREA
    magick_limits["disk"] = _MAGICK_DISK
    magick_limits["width"] = _MAGICK_MAX_SIDE
    magick_limits["height"] = _MAGICK_MAX_SIDE
