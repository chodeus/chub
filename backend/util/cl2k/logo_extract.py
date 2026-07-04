"""Extract a title/logo from a poster into a transparent PNG.

Three keys, all confined by a brushed ``mask`` (white = look here), all pure
Pillow + numpy, all finishing with an area-filter despeckle + trim:

- :func:`extract_title_logo` — for *white* titles: keys bright / near-white pixels
  via the minimum RGB channel (high only for white/grey). Outputs white pixels.
- :func:`extract_subject_logo` — for *coloured* titles the brightness key can't
  catch: keys each pixel by its Lab colour distance from the backdrop (sampled
  just outside the brush), and keeps the title's ORIGINAL colours so the
  downstream CL2K whiten pass can recolour it like any fetched logo.
- :func:`extract_logo_by_diff` — after an AI erase: keys wherever the original
  and the cleaned result differ inside the erase mask. The most faithful of the
  three (it catches glows/soft shadows no colour key can), but only usable once
  an erase has run.

All are best-effort fallbacks for titles with no official clearlogo — a title
baked into poster art can't be recovered pixel-perfect, so prefer a real
TMDB/fanart/Plex logo when one exists.
"""

from __future__ import annotations

import io
from typing import Optional

import numpy as np
from PIL import Image, ImageFilter


def _despeckle(alpha: np.ndarray, min_area: int = 12) -> np.ndarray:
    """Drop isolated specks by connected-component area on the binary alpha.

    A morphological opening erases any stroke under its kernel width — serif
    hairlines and thin connectors died with the old 3x3 version. Area filtering
    instead labels the 8-connected components of ``alpha > 40`` (run-based
    union-find, no scipy/cv2) and zeroes only components under ``min_area`` px:
    a 1-2px hairline survives as long as it touches its glyph, while isolated
    speckle dies. Kept components retain their original soft alpha.
    """
    binary = alpha > 40
    h, _w = binary.shape
    parent: dict = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    next_id = 0
    prev_runs = []  # (col_start, col_end_inclusive, label)
    all_runs = []  # (row, col_start, col_end_inclusive, label)
    for y in range(h):
        idx = np.flatnonzero(binary[y])
        if idx.size == 0:
            prev_runs = []
            continue
        breaks = np.flatnonzero(np.diff(idx) > 1)
        starts = np.concatenate(([0], breaks + 1))
        ends = np.concatenate((breaks, [idx.size - 1]))
        cur_runs = []
        for s, e in zip(starts, ends):
            cs, ce = int(idx[s]), int(idx[e])
            lbl = next_id
            next_id += 1
            parent[lbl] = lbl
            for ps, pe, plbl in prev_runs:  # 8-connectivity: overlap within 1 col
                if pe >= cs - 1 and ps <= ce + 1:
                    union(lbl, plbl)
            cur_runs.append((cs, ce, lbl))
            all_runs.append((y, cs, ce, lbl))
        prev_runs = cur_runs

    area: dict = {}
    for _y, cs, ce, lbl in all_runs:
        r = find(lbl)
        area[r] = area.get(r, 0) + (ce - cs + 1)
    keep = np.zeros_like(binary)
    for y, cs, ce, lbl in all_runs:
        if area[find(lbl)] >= min_area:
            keep[y, cs : ce + 1] = True
    return (alpha * keep).astype(np.uint8)


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Binary dilation by ``radius`` px (square kernel) via separable shifted
    ORs — pad + shift, no scipy/cv2."""
    w = mask.shape[1]
    padded = np.pad(mask, ((0, 0), (radius, radius)))
    out = np.zeros_like(mask)
    for d in range(2 * radius + 1):
        out |= padded[:, d : d + w]
    h = mask.shape[0]
    padded = np.pad(out, ((radius, radius), (0, 0)))
    out = np.zeros_like(mask)
    for d in range(2 * radius + 1):
        out |= padded[d : d + h, :]
    return out


def _load_mask(mask_bytes: Optional[bytes], size) -> Optional[np.ndarray]:
    """Decode a brush PNG to a bool array (white = keep), resized to ``size``."""
    if not mask_bytes:
        return None
    m = Image.open(io.BytesIO(mask_bytes)).convert("L")
    if m.size != size:
        m = m.resize(size, Image.NEAREST)
    return np.asarray(m) > 127


def _srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0-255, shape ``[..., 3]``) -> CIE Lab, D65. Euclidean distance in
    this space is ΔE76 — roughly perceptual, unlike raw RGB distance which
    over-weights luminance shifts and under-weights hue flips at low light."""
    c = rgb.astype(np.float32) / 255.0
    lin = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ],
        dtype=np.float32,
    )
    xyz = lin @ m.T
    xyz = xyz / np.array([0.95047, 1.0, 1.08883], dtype=np.float32)  # D65 white
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    lab = np.empty_like(xyz)
    lab[..., 0] = 116.0 * f[..., 1] - 16.0
    lab[..., 1] = 500.0 * (f[..., 0] - f[..., 1])
    lab[..., 2] = 200.0 * (f[..., 1] - f[..., 2])
    return lab


def _otsu(values: np.ndarray) -> Optional[float]:
    """Otsu threshold over 1-D samples, or None when the split is degenerate —
    too few samples, a flat histogram, or one class near-empty. None means the
    brushed region isn't really bimodal and a fixed band is safer."""
    v = values.astype(np.float32).ravel()
    if v.size < 256:
        return None
    vmin, vmax = float(v.min()), float(v.max())
    if vmax - vmin < 1e-3:
        return None
    hist, edges = np.histogram(v, bins=128, range=(vmin, vmax))
    p = hist / hist.sum()
    centers = ((edges[:-1] + edges[1:]) / 2.0).astype(np.float64)
    omega = np.cumsum(p)
    mu = np.cumsum(p * centers)
    denom = omega * (1.0 - omega)
    denom[denom < 1e-9] = np.inf
    between = (mu[-1] * omega - mu) ** 2 / denom
    k = int(np.argmax(between))
    if not 0.05 <= omega[k] <= 0.95:
        return None
    return float(centers[k])


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
    """Per-pixel ΔE76 (Lab) to the *nearest* backdrop colour (see
    :func:`_background_colors`) — small where a pixel matches the backdrop, large
    on the title. Lab, not raw RGB: a dark-red title on a dark backdrop is a hue
    flip RGB distance barely scores, while ΔE tracks what the eye separates."""
    bg = _background_colors(arr, mask)
    diff = _srgb_to_lab(arr)[..., None, :] - _srgb_to_lab(bg)[None, None]
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
    lo/hi: ΔE76 smoothstep band; raise lo to reject more background. Left at the
    defaults, the band is fitted per poster: Otsu over the in-brush distance
    histogram splits backdrop-like from title-like, and the ramp straddles that
    split — a degenerate histogram (no real bimodality, or a split outside the
    plausible ΔE range) falls back to the fixed 40/90.
    """
    img = _open_rgb_bounded(image_bytes)
    arr = np.asarray(img).astype(np.float32)
    mask = _load_mask(mask_bytes, img.size)

    dist = _background_distance(arr, mask)
    if (lo, hi) == (40.0, 90.0):  # untouched defaults -> fit the band per poster
        split = _otsu(dist[mask] if mask is not None else dist)
        if split is not None and 8.0 <= split <= 80.0:
            lo, hi = 0.7 * split, 1.3 * split
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
    lo/hi: min-channel smoothstep band; raise lo to reject more background. Left
    at the defaults, ``lo`` is fitted per poster: Otsu over the brushed pixels'
    min-channel histogram splits background from title, clamped to 120-200 so a
    cream/ivory title (min channel below the fixed 165) isn't holed out; a
    degenerate histogram keeps the fixed 165. Output stays forced-white — the
    downstream whiten/flip passes and the "original colours" toggle expect this
    mode to already BE the white logo (subject mode is the keep-colours path).
    """
    img = _open_rgb_bounded(image_bytes)
    arr = np.asarray(img).astype(np.float32)
    mn = np.minimum(np.minimum(arr[..., 0], arr[..., 1]), arr[..., 2])
    if (lo, hi) == (165.0, 215.0):  # untouched defaults -> fit lo per poster
        m = _load_mask(mask_bytes, img.size)
        split = _otsu(mn[m] if m is not None else mn)
        if split is not None:
            lo = float(np.clip(split, 120.0, 200.0))
            hi = lo + 50.0  # keep the band width (edge softness) of 165/215
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


def extract_logo_by_diff(
    original_bytes: bytes,
    cleaned_bytes: bytes,
    mask_bytes: Optional[bytes] = None,
    *,
    lo: float = 12.0,
    hi: float = 45.0,
) -> bytes:
    """Original + AI-erased poster -> transparent original-colour logo PNG.

    Keys wherever the cleaned result differs from the original: the eraser only
    repaints the title (plus its glow/soft shadow), so the per-pixel RGB
    distance IS the title's footprint — no brightness or colour model to fool.
    Confined to the erase mask dilated ~6px (the sidecar dilates its mask too,
    so the repaint bleeds slightly past the brush); any difference outside that
    is inpainting drift, not title.

    lo/hi: RGB-distance smoothstep band — below ``lo`` reads as encoder/inpaint
    jitter (transparent), above ``hi`` is confidently title (opaque). RGB keeps
    original colours; the CL2K whiten pass recolours downstream, as with
    :func:`extract_subject_logo`.
    """
    orig_img = _open_rgb_bounded(original_bytes)
    clean_img = _open_rgb_bounded(cleaned_bytes)
    if clean_img.size != orig_img.size:
        clean_img = clean_img.resize(orig_img.size, Image.LANCZOS)
    orig = np.asarray(orig_img).astype(np.float32)
    clean = np.asarray(clean_img).astype(np.float32)
    mask = _load_mask(mask_bytes, orig_img.size)

    diff = orig - clean
    dist = np.sqrt((diff * diff).sum(axis=-1))
    t = np.clip((dist - lo) / max(hi - lo, 1.0), 0.0, 1.0)
    alpha = (t * t * (3.0 - 2.0 * t) * 255.0).astype(np.uint8)  # smoothstep soft edges
    if mask is not None:
        alpha = (alpha * _dilate(mask, 6)).astype(np.uint8)

    alpha = _despeckle(alpha)

    out = np.zeros((orig_img.height, orig_img.width, 4), dtype=np.uint8)
    out[..., 0:3] = orig.astype(np.uint8)  # keep ORIGINAL colours; whiten happens later
    out[..., 3] = alpha
    logo = Image.fromarray(out)
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)

    buf = io.BytesIO()
    logo.save(buf, "PNG")
    return buf.getvalue()
