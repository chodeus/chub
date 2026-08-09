"""Shared sRGB ICC profile for CL2K output.

The render inputs (TMDB, fanart.tv) are sRGB and the pipeline never widens the
gamut, so the output pixels are sRGB. Embedding a standard sRGB ICC profile is a
truthful self-description of those pixels: it keeps colours correct on colour-
managed / wide-gamut displays, which can otherwise stretch an *untagged* JPEG
into the display gamut and render it oversaturated. On ordinary sRGB-assuming
viewers (Plex, browsers) it changes nothing visible.

The profile is generated locally via littleCMS (no authoring data is copied from
any source file) and cached, so the embedded bytes are identical every call.
"""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def srgb_icc_bytes() -> bytes:
    """Return a standard sRGB ICC profile as bytes (cached, ~0.5 KB)."""
    from PIL import ImageCms

    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
