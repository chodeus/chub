"""Extract a title/logo from a poster into a transparent PNG.

Two keys, both confined by a brushed ``mask`` (white = look here), both pure
Pillow + numpy, both finishing with a 3x3 morphological despeckle + trim:

- :func:`extract_title_logo` — for *white* titles: keys bright / near-white pixels
  via the minimum RGB channel (high only for white/grey). Outputs white pixels.
- :func:`extract_subject_logo` — for *coloured* titles the brightness key can't
  catch: keys each pixel by its colour distance from the backdrop (sampled just
  outside the brush), and keeps the title's ORIGINAL colours so the downstream
  CL2K whiten pass can recolour it like any fetched logo.

Both are best-effort fallbacks for titles with no official clearlogo — a title
baked into poster art can't be recovered pixel-perfect, so prefer a real
TMDB/fanart/Plex logo when one exists.
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


def _load_mask(mask_bytes: Optional[bytes], size) -> Optional[np.ndarray]:
    """Decode a brush PNG to a bool array (white = keep), resized to ``size``."""
    if not mask_bytes:
        return None
    m = Image.open(io.BytesIO(mask_bytes)).convert("L")
    if m.size != size:
        m = m.resize(size, Image.NEAREST)
    return np.asarray(m) > 127


def _local_background(arr: np.ndarray, mask: Optional[np.ndarray]) -> np.ndarray:
    """Median RGB of the backdrop the title sits on — the colour to key against.

    Within the brushed swath the backdrop (sky/plate/scene) covers more area than
    the thin title strokes, so the per-channel *median* of the brushed pixels
    lands on the backdrop and shrugs off the title minority. Without a brush (or
    too few pixels), fall back to the image border.
    """
    if mask is not None and int(mask.sum()) >= 16:
        return np.median(arr[mask].reshape(-1, 3), axis=0)
    b = 4
    edges = np.concatenate(
        [
            arr[:b].reshape(-1, 3),
            arr[-b:].reshape(-1, 3),
            arr[:, :b].reshape(-1, 3),
            arr[:, -b:].reshape(-1, 3),
        ],
        axis=0,
    )
    return np.median(edges, axis=0)


def _kmeans(pts: np.ndarray, k: int, iters: int = 12):
    """Tiny deterministic Lloyd's k-means on RGB samples (no RNG, so reproducible).

    Seeds are spread across the luma-sorted samples; empty clusters keep their
    seed. Returns ``(centroids[k,3], counts[k])``.
    """
    order = np.argsort(pts.sum(axis=1))
    cent = pts[order[np.linspace(0, len(pts) - 1, k).astype(int)]].astype(np.float32)
    lab = np.zeros(len(pts), dtype=int)
    for _ in range(iters):
        d = ((pts[:, None, :] - cent[None]) ** 2).sum(axis=2)
        lab = d.argmin(axis=1)
        for j in range(k):
            m = lab == j
            if m.any():
                cent[j] = pts[m].mean(axis=0)
    return cent, np.bincount(lab, minlength=k)


def _background_colors(arr: np.ndarray, mask: Optional[np.ndarray]) -> np.ndarray:
    """Backdrop palette (n, 3): the colours the title sits ON.

    Sampled from a ring just *outside* the brush — that's the artwork around the
    title, which is unambiguously background (the title is inside the brush). A
    k-means of that ring captures a multi-toned backdrop (cityscape, wood plate)
    as several colours rather than one muddy average. Sampling outside, not
    inside, sidesteps having to guess which inside-brush colour is the title — so
    a title that spans several tones (highlight + shadow) is never mistaken for
    backdrop and erased. Falls back to a single border colour with no brush.
    """
    if mask is not None and mask.any():
        m = Image.fromarray((mask.astype(np.uint8)) * 255)
        ring = (np.asarray(m.filter(ImageFilter.MaxFilter(45))) > 127) & ~mask  # ~22px out
        pts = arr[ring]
        if len(pts) >= 50:
            sub = pts.astype(np.float32)[:: max(1, len(pts) // 4000)]  # subsample, cheap
            cent, counts = _kmeans(sub, 5)
            return cent[counts > 0]
    return _local_background(arr, mask)[None, :]


def _background_distance(arr: np.ndarray, mask: Optional[np.ndarray]) -> np.ndarray:
    """Per-pixel colour distance to the *nearest* backdrop colour (see
    :func:`_background_colors`) — small where a pixel matches the backdrop, large
    on the title."""
    bg = _background_colors(arr, mask)
    diff = arr[..., None, :] - bg[None, None]
    return np.sqrt((diff * diff).sum(axis=-1)).min(axis=-1)


# Cap the input so the (H×W×N×3) float buffers below can't OOM the worker on an
# oversized/decompression-bomb image. Posters are well under this.
_MAX_SIDE = 3000


def _open_rgb_bounded(image_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if max(img.size) > _MAX_SIDE:
        img.thumbnail((_MAX_SIDE, _MAX_SIDE), Image.LANCZOS)
    return img


def extract_subject_logo(
    image_bytes: bytes,
    mask_bytes: Optional[bytes] = None,
    *,
    lo: float = 40.0,
    hi: float = 90.0,
) -> bytes:
    """Poster bytes -> transparent *original-colour* logo PNG, trimmed to content.

    The companion to :func:`extract_title_logo` for titles the white key can't
    catch — coloured ones. Instead of brightness, it keys on each pixel's colour
    *distance from the local background* (see :func:`_background_distance`, which
    models a multi-toned backdrop as a colour palette), so a red or green title
    separates from a cityscape or a wood-grain plate while keeping its own
    colours. The CL2K whiten pass downstream then turns that colour into the
    two-tone look, exactly as it does for a fetched TMDB/fanart logo — so this
    must NOT pre-whiten the way the white key does.

    mask_bytes: brush PNG, white = the title region; brush close around the title
    so the backdrop palette is sampled from real backdrop, not other artwork.
    lo/hi: colour-distance smoothstep band; raise lo to reject more background.
    """
    img = _open_rgb_bounded(image_bytes)
    arr = np.asarray(img).astype(np.float32)
    mask = _load_mask(mask_bytes, img.size)

    dist = _background_distance(arr, mask)
    t = np.clip((dist - lo) / max(hi - lo, 1.0), 0.0, 1.0)
    alpha = (t * t * (3.0 - 2.0 * t) * 255.0).astype(np.uint8)  # smoothstep soft edges

    if mask is not None:
        alpha = (alpha * mask).astype(np.uint8)

    alpha = _despeckle(alpha)

    out = np.zeros((img.height, img.width, 4), dtype=np.uint8)
    out[..., 0:3] = arr.astype(np.uint8)  # keep ORIGINAL colours; whiten happens later
    out[..., 3] = alpha
    logo = Image.fromarray(out)
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)

    buf = io.BytesIO()
    logo.save(buf, "PNG")
    return buf.getvalue()


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
    img = _open_rgb_bounded(image_bytes)
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
