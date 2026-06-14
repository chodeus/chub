"""Extract a white title/logo from a poster into a transparent PNG.

Keys bright / near-white pixels (the title) out of the artwork using the minimum
RGB channel — high only for white/grey, low for any saturated colour — then drops
tiny speckle and trims to content. A brushed ``mask`` (white = look here) confines
the key so bright areas *outside* the title can't leak in; keep the brush off
bright background, since white-on-bright isn't separable by keying.

Pure Pillow + numpy (no scipy): despeckle is a 3x3 morphological opening, which is
enough once the brush mask has excluded the big bright regions.
"""

from __future__ import annotations

import io
from typing import Optional

import numpy as np
from PIL import Image, ImageFilter


def _despeckle(alpha: np.ndarray) -> np.ndarray:
    """Drop isolated specks via a 3x3 opening on the binary alpha.

    The opening (erode then dilate) removes tiny bright bits the key caught in the
    background while leaving the title strokes (>=3px) intact. Anti-aliased edges
    survive because the soft alpha is only *masked* by the opened binary, not
    replaced by it.
    """
    binary = Image.fromarray(((alpha > 40) * 255).astype(np.uint8))
    opened = binary.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    keep = np.asarray(opened) > 0
    return (alpha * keep).astype(np.uint8)


def extract_title_logo(
    image_bytes: bytes,
    mask_bytes: Optional[bytes] = None,
    *,
    lo: float = 165.0,
    hi: float = 215.0,
) -> bytes:
    """Poster bytes -> transparent white logo PNG bytes, trimmed to content.

    mask_bytes: optional PNG mask, white = keep region (resized to the image).
    lo/hi: min-channel smoothstep band; raise lo to reject more background.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    arr = np.asarray(img).astype(np.float32)
    mn = np.minimum(np.minimum(arr[..., 0], arr[..., 1]), arr[..., 2])
    t = np.clip((mn - lo) / max(hi - lo, 1.0), 0.0, 1.0)
    alpha = (t * t * (3.0 - 2.0 * t) * 255.0).astype(np.uint8)  # smoothstep keeps soft edges

    if mask_bytes:
        m = Image.open(io.BytesIO(mask_bytes)).convert("L")
        if m.size != img.size:
            m = m.resize(img.size, Image.NEAREST)
        alpha = (alpha.astype(np.float32) * (np.asarray(m).astype(np.float32) / 255.0)).astype(np.uint8)

    alpha = _despeckle(alpha)

    out = np.zeros((img.height, img.width, 4), dtype=np.uint8)
    out[..., 0:3] = 255
    out[..., 3] = alpha
    logo = Image.fromarray(out)
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)

    buf = io.BytesIO()
    logo.save(buf, "PNG")
    return buf.getvalue()
