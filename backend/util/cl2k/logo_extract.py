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
from PIL import Image


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


# A near-ring cluster with no colour within this ΔE in the FAR ring is title
# bleed (grunge spray / glow hugging the glyphs), not backdrop — see _drop_bleed.
_BLEED_FAR_SUPPORT = 14.0


def _far_ring_palette(
    space: np.ndarray, mask: np.ndarray, near_px: int
) -> Optional[np.ndarray]:
    """k-means palette of the 40-80px far ring, in ``space``'s own colour space.

    None when the ring is too small to trust — absolutely, or relative to the
    near ring (a brush close to the frame edge leaves a one-SIDED far ring that
    would wrongly condemn colours legitimately present near the other sides).
    """
    d40 = _dilate(mask, 40)
    far = _dilate(d40, 40) & ~d40  # square dilations compose: 40+40 = 80
    fpts = space[far]
    if len(fpts) < max(200, near_px // 2):
        return None
    fsub = fpts.astype(np.float32)[:: max(1, len(fpts) // 4000)]
    fcent, fcounts = _kmeans(fsub, 5)
    return fcent[fcounts > 0]


def _drop_bleed(
    arr: np.ndarray, mask: np.ndarray, cent: np.ndarray, near_px: int
) -> np.ndarray:
    """Drop near-ring clusters with no far-ring colour support — title bleed
    (spray/glow), not backdrop. Keeps all clusters when validation can't run."""
    fcent = _far_ring_palette(arr, mask, near_px)
    if fcent is None:
        return cent
    diff = _srgb_to_lab(cent[None])[0][:, None] - _srgb_to_lab(fcent[None])[0][None]
    de = np.sqrt((diff * diff).sum(axis=2)).min(axis=1)
    keep = de <= _BLEED_FAR_SUPPORT
    return cent[keep] if keep.any() else cent


def _background_colors(arr: np.ndarray, mask: Optional[np.ndarray]) -> np.ndarray:
    """Backdrop palette (n, 3): the colours the title sits ON.

    Sampled from a ring just *outside* the brush — that's the artwork around the
    title, which is unambiguously background (the title is inside the brush). A
    k-means of that ring captures a multi-toned backdrop (cityscape, wood plate)
    as several colours rather than one muddy average. Sampling outside, not
    inside, sidesteps having to guess which inside-brush colour is the title — so
    a title that spans several tones (highlight + shadow) is never mistaken for
    backdrop and erased. Clusters that are title bleed rather than backdrop are
    dropped (see :func:`_drop_bleed`). Falls back to a single border colour with
    no brush.
    """
    if mask is not None and mask.any():
        ring = _dilate(mask, 22) & ~mask
        pts = arr[ring]
        if len(pts) >= 50:
            sub = pts.astype(np.float32)[
                :: max(1, len(pts) // 4000)
            ]  # subsample, cheap
            cent, counts = _kmeans(sub, 5)
            return _drop_bleed(arr, mask, cent[counts > 0], int(ring.sum()))
    return _local_background(arr, mask)[None, :]


def _background_distance(arr: np.ndarray, bg: np.ndarray) -> np.ndarray:
    """Per-pixel ΔE76 (Lab) to the *nearest* backdrop colour (see
    :func:`_background_colors`) — small where a pixel matches the backdrop, large
    on the title. Lab, not raw RGB: a dark-red title on a dark backdrop is a hue
    flip RGB distance barely scores, while ΔE tracks what the eye separates."""
    diff = _srgb_to_lab(arr)[..., None, :] - _srgb_to_lab(bg)[None, None]
    return np.sqrt((diff * diff).sum(axis=-1)).min(axis=-1)


# Cap the input so the (H×W×N×3) float buffers below can't OOM the worker on an
# oversized/decompression-bomb image. Posters are well under this.
_MAX_SIDE = 3000

# White-union guard: reject when the union would cover more of the brush than a
# title plausibly does (a pale FIELD keyed white).
_UNION_MAX_COVER = 0.60


def _white_union_alpha(
    arr: np.ndarray, mask: np.ndarray, color_alpha: np.ndarray
) -> np.ndarray:
    """Brightness-key alpha for the WHITE part of a mixed title, or zeros.
    Guards: border-spill flood (bright content crossing the brush edge is
    backdrop) and the ``_UNION_MAX_COVER`` cap (a pale field, not letters)."""
    mn = np.minimum(np.minimum(arr[..., 0], arr[..., 1]), arr[..., 2])
    split = _otsu(mn[mask])
    lo = float(np.clip(split, 120.0, 200.0)) if split is not None else 165.0
    hi = lo + 50.0
    t = np.clip((mn - lo) / (hi - lo), 0.0, 1.0)
    walpha = ((t * t * (3.0 - 2.0 * t)) * 255.0).astype(np.uint8)
    walpha = (walpha * mask).astype(np.uint8)

    add = (walpha > 128) & (color_alpha <= 128)
    if not add.any():
        return np.zeros_like(walpha)

    bright_out = (_dilate(mask, 2) & ~mask) & (mn >= lo)
    spill = _geodesic_flood(add, bright_out)
    if spill.any():
        walpha[_dilate(spill, 2)] = 0

    union = (color_alpha > 128) | (walpha > 128)
    if int(union.sum()) / max(int(mask.sum()), 1) > _UNION_MAX_COVER:
        return np.zeros_like(walpha)
    return walpha


def _geodesic_flood(add: np.ndarray, seed: np.ndarray) -> np.ndarray:
    """Geodesic flood of ``seed`` through ``add`` (connected reachability at
    4px/pass). Bound = max possible travel; the loop exits early on stability."""
    spill = add & _dilate(seed, 3)
    for _ in range((add.shape[0] + add.shape[1]) // 4 + 2):
        grown = add & _dilate(spill, 4)
        if int(grown.sum()) == int(spill.sum()):
            break
        spill = grown
    return spill


def _anchor_rescue_alpha(
    arr: np.ndarray, mask: np.ndarray, base_alpha: np.ndarray, bg: np.ndarray
) -> np.ndarray:
    """Per-anchor key bands for pale non-white words the fitted band drops
    (band clamped to ``0.6 x`` backdrop distance, as in :func:`_detect_anchors`).
    Same border-spill and coverage guards as the white union; zeros if unsafe."""
    zeros = np.zeros(arr.shape[:2], dtype=np.uint8)
    pts = arr[mask]
    if len(pts) < 200:
        return zeros
    sub = pts.astype(np.float32)[:: max(1, len(pts) // 4000)]
    cent, counts = _kmeans(sub, 5)
    frac = counts / max(1, int(counts.sum()))
    lab = _srgb_to_lab(arr)
    cent_lab = _srgb_to_lab(cent[None])[0]
    bg_lab = _srgb_to_lab(bg[None])[0]

    rim_out = _dilate(mask, 2) & ~mask
    rescue = zeros.copy()
    seed = np.zeros(arr.shape[:2], dtype=bool)
    for c, f in zip(cent_lab, frac):
        if f < _ANCHOR_MIN_FRAC:
            continue
        d = float(np.sqrt(((c - bg_lab) ** 2).sum(axis=1)).min())
        if d < _BG_NEAR:
            continue  # backdrop-like, or too close to separate safely
        tol = min(_COLOR_TOL_MAX, max(_BG_SAME, 0.6 * d))
        de = np.sqrt(((lab - c) ** 2).sum(axis=-1))
        t = np.clip((tol - de) / max(0.3 * tol, 1.0), 0.0, 1.0)
        rescue = np.maximum(rescue, (t * t * (3.0 - 2.0 * t) * 255.0).astype(np.uint8))
        seed |= rim_out & (de < tol)
    rescue = (rescue * mask).astype(np.uint8)

    add = (rescue > 128) & (base_alpha <= 128)
    if not add.any():
        return zeros
    spill = _geodesic_flood(add, seed)
    if spill.any():
        rescue[_dilate(spill, 2)] = 0

    union = (base_alpha > 128) | (rescue > 128)
    if int(union.sum()) / max(int(mask.sum()), 1) > _UNION_MAX_COVER:
        return zeros
    return rescue


# The detector must account for at least this share of the keyed area before the
# zone filter may remove anything — below it, it likely missed the wordmark.
_ZONE_MIN_KEEP = 0.5


def _text_zone_filter(
    image_bytes: bytes, mask: np.ndarray, alpha: np.ndarray
) -> np.ndarray:
    """Drop keyed content with no connection to a detected text line — scene
    junk the colour key can't tell from title. Fail-safe: no detector, no boxes,
    or a keep under ``_ZONE_MIN_KEEP`` of the keyed area leaves alpha unchanged."""
    prob = _sized_probmap(image_bytes, alpha.shape)
    if prob is None:
        return alpha
    width = alpha.shape[1]
    zone = _dilate((prob > 0.3) & _dilate(mask, 8), max(12, round(0.025 * width)))
    keyed = alpha > 40
    if not (zone.any() and keyed.any()):
        return alpha
    keep = _geodesic_flood(keyed, keyed & zone)
    if int(keep.sum()) < _ZONE_MIN_KEEP * int(keyed.sum()):
        return alpha
    return (alpha * _dilate(keep, 2)).astype(np.uint8)


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
    colours. A MIXED title (white words + coloured words) additionally unions in
    the brightness key (see :func:`_white_union_alpha`). The CL2K whiten pass
    downstream then turns that colour into the two-tone look, exactly as it does
    for a fetched TMDB/fanart logo — so this must NOT pre-whiten the way the
    white key does.

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

    bg = _background_colors(arr, mask)
    dist = _background_distance(arr, bg)
    if (lo, hi) == (40.0, 90.0):  # untouched defaults -> fit the band per poster
        split = _otsu(dist[mask] if mask is not None else dist)
        if split is not None and 8.0 <= split <= 80.0:
            lo, hi = 0.7 * split, 1.3 * split
    t = np.clip((dist - lo) / max(hi - lo, 1.0), 0.0, 1.0)
    alpha = (t * t * (3.0 - 2.0 * t) * 255.0).astype(np.uint8)  # smoothstep soft edges

    if mask is not None:
        alpha = (alpha * mask).astype(np.uint8)
        # Mixed titles: union in the white part (see _white_union_alpha) — the
        # colour key alone drops it when the backdrop palette has a white-ish
        # tone — then rescue pale non-white words the band-fit dropped.
        alpha = np.maximum(alpha, _white_union_alpha(arr, mask, alpha))
        alpha = np.maximum(alpha, _anchor_rescue_alpha(arr, mask, alpha, bg))

    alpha = _despeckle(alpha)
    if mask is not None:
        alpha = _text_zone_filter(image_bytes, mask, alpha)

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
    alpha = (t * t * (3.0 - 2.0 * t) * 255.0).astype(
        np.uint8
    )  # smoothstep keeps soft edges

    if mask_bytes:
        m = Image.open(io.BytesIO(mask_bytes)).convert("L")
        if m.size != img.size:
            m = m.resize(img.size, Image.NEAREST)
        alpha = (
            alpha.astype(np.float32) * (np.asarray(m).astype(np.float32) / 255.0)
        ).astype(np.uint8)

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
    if mask is not None:
        # The eraser repaints everything the brush covered, so scene detail caught
        # by a loose brush diffs just as strongly as the title — same cure as
        # subject mode's.
        alpha = _text_zone_filter(original_bytes, mask, alpha)

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


def _sized_probmap(image_bytes, shape):
    """Detector probmap resized to the working-array ``shape``, or ``None``."""
    from backend.util.cl2k.text_detect import detect_text_probmap

    prob = detect_text_probmap(image_bytes)
    if prob is None:
        return None
    if prob.shape != shape:  # e.g. _open_rgb_bounded downscaled a huge image
        prob = (
            np.asarray(
                Image.fromarray((np.clip(prob, 0, 1) * 255).astype(np.uint8)).resize(
                    (shape[1], shape[0]), Image.BILINEAR
                ),
                dtype=np.float32,
            )
            / 255.0
        )
    return prob


# Anchor/background separation tiers (ΔE76 in Lab, against the DOMINANT outside
# clusters only — ``_BG_DOMINANT_FRAC`` mirrors _matches_background's min_frac).
_BG_SAME = 8.0  # closer than this = the background itself, not ink
_COLOR_TOL_MAX = 33.0  # cap on any per-anchor key band (tighten + rescue paths)
_BG_NEAR = 20.0  # closer than this = "suspect" ink (white title on a pale field)
_BG_DOMINANT_FRAC = 0.15
_ANCHOR_MIN_FRAC = 0.08  # smaller clusters are anti-aliasing blends, not ink


def _detect_anchors(prob, lab, block, bg, color_tol):
    """Title INK anchors ``[(lab, tol, suspect)]`` from the detector box, or ``[]``.

    The detector localises text LINES (colour-agnostic) as filled boxes — it does
    NOT resolve strokes, so the box holds ink AND inter-glyph background. A
    k-means over the box pixels separates them, and each cluster is judged by its
    ΔE to the DOMINANT background clusters sampled just OUTSIDE the user's block
    (which bounds the title, so outside is real background):

    - closer than ``_BG_SAME``: it IS the background between the glyphs — drop.
    - ``_BG_SAME``..``_BG_NEAR``: "suspect" — plausibly real ink that merely
      resembles the field (a white title on pale fog). Kept only when LIGHT
      (L >= 50): a dark near-background cluster is scenery/shadow inside the box,
      and keying it swallows the artwork. The caller additionally demands a
      suspect-built mask stay concentrated in the detector box.
    - farther: clean ink.

    Every kept cluster becomes an anchor, so a MULTI-COLOUR title (cream "A TO" +
    red "DAY DIE"), a fill-plus-outline title, or a detect-prefill block spanning
    differently-coloured elements all key as the union — the old single dominant
    anchor kept exactly one colour and dropped the rest. Per anchor, the key band
    is clamped to ``0.6 x`` its background distance (floored at ``_BG_SAME``) so
    the key can never reach the field it sits on — an unclamped band pulled in
    most of a pale field between the letters of a white title.

    REMAINING LIMIT: text that is not colour-separable from its own plate (a
    dark-red badge on a red box) yields no anchor there — those regions keep the
    user's block, which is also the right erase shape for them.
    """
    if prob is None or bg is None:
        return []
    box = (prob > 0.3) & block
    if int(box.sum()) < 100:
        return []
    bg_cent, bg_frac = bg
    dom = bg_cent[bg_frac >= _BG_DOMINANT_FRAC]
    pts = lab[box].astype(np.float32)
    pts = pts[:: max(1, len(pts) // 4000)]
    cent, counts = _kmeans(pts, 5)
    frac = counts / max(1, int(counts.sum()))

    anchors = []
    for c, f in zip(cent, frac):
        if f < _ANCHOR_MIN_FRAC:
            continue
        d = float(np.sqrt(((c - dom) ** 2).sum(axis=1)).min()) if len(dom) else np.inf
        if d < _BG_SAME:
            continue
        suspect = d < _BG_NEAR
        if suspect and c[0] < 50.0:
            continue
        tol = min(color_tol, max(_BG_SAME, 0.6 * d))
        anchors.append((c, tol, suspect))
    return anchors


def _outside_background(lab, block, width):
    """k-means Lab palette of the background sampled just OUTSIDE the brush.

    The block bounds the title, so a ring outside it is real background at any
    brush tightness. Returns ``None`` when there's no usable outside (a block that
    fills the frame). Used to key the title INK against — and to reject an anchor
    (detector or colour-key) that merely IS the background, i.e. an inversion.
    Title bleed clusters (spray hugging the glyphs, no far-ring support) are
    dropped, as in :func:`_drop_bleed`; kept fractions stay un-renormalised so
    the dominance gates still measure share of the full outside area.
    """
    outside = _dilate(block, max(8, round(0.02 * width))) & ~block
    if int(outside.sum()) < 50:
        outside = ~block
    obg = lab[outside]
    if obg.shape[0] < 50:
        return None
    obg = obg.astype(np.float32)[:: max(1, len(obg) // 4000)]
    bg_cent, bg_counts = _kmeans(obg, 5)
    keep = bg_counts > 0
    cent, frac = bg_cent[keep], bg_counts[keep] / int(bg_counts.sum())
    fcent = _far_ring_palette(lab, block, int(outside.sum()))
    if fcent is not None:
        diff = cent[:, None] - fcent[None]
        de = np.sqrt((diff * diff).sum(axis=2)).min(axis=1)
        keeps = de <= _BLEED_FAR_SUPPORT
        if keeps.any():
            cent, frac = cent[keeps], frac[keeps]
    return cent, frac


def _matches_background(title_lab, bg, tol=20.0, min_frac=0.15):
    """True if the anchor is within ``tol`` ΔE of a DOMINANT background cluster.

    A plate (an inversion) is a large fraction of the background outside the
    brush; a title whose colour merely resembles a MINOR background element (a
    small window reflection, a shadow) is not — so only clusters covering at
    least ``min_frac`` of the outside area count. ``bg`` is ``(centroids, frac)``
    from :func:`_outside_background`.
    """
    bg_cent, bg_frac = bg
    de = np.sqrt(((title_lab - bg_cent) ** 2).sum(axis=1))
    return bool(((de < tol) & (bg_frac >= min_frac)).any())


def tighten_text_mask(
    image_bytes: bytes,
    mask_bytes: Optional[bytes],
    *,
    grow: Optional[int] = None,
    color_tol: float = _COLOR_TOL_MAX,
) -> Optional[bytes]:
    """Shrink a brushed *block* erase-mask down to the title's glyph strokes.

    A filled block hands the inpainter one big contiguous hole it can only fill
    with low-frequency mush (LaMa blurs the middle of a wide mask). Keying the
    block down to just the strokes leaves the real backdrop *between* the letters
    for the inpainter to sample, so the fill stays sharp.

    The title colours are found two ways, best first:

    1. **DBNet text detector** (:func:`_detect_anchors`) — localises the text by
       appearance and keys EVERY ink cluster in the detected boxes against the
       background sampled outside the brush, so white/black/multi-coloured/
       outlined titles all key (and it never inverts onto a saturated plate).
    2. **Fallback colour-key** — when the detector is unavailable/off, finds no
       text, or can't separate ink from background: anchor the colour from the
       most-saturated brushed pixels. Works for coloured titles; guarded by a
       stroke-shape gate so a plate-shaped result (an inversion) is rejected.

    Either way, every brushed pixel within an anchor's key band is kept — a
    uniform glyph body fills SOLID, a differently-coloured plate drops out —
    then ``grow`` re-dilates for anti-aliasing. ``color_tol`` caps the band;
    the detector path narrows it per anchor (see :func:`_detect_anchors`).

    Returns a white-on-black PNG mask (white = remove, image-sized), or ``None``
    to signal "keep the caller's block": no title could be isolated, or the
    result was degenerate. It never returns a mask worse than the block.
    """
    img = _open_rgb_bounded(image_bytes)
    width = img.width
    arr = np.asarray(img).astype(np.float32)
    block = _load_mask(mask_bytes, img.size)
    if block is None or int(block.sum()) < 200:
        return None
    lab = _srgb_to_lab(arr)
    bg = _outside_background(lab, block, width)
    prob = _sized_probmap(image_bytes, block.shape)

    # 1. Ink anchors — detector first (polarity-agnostic, multi-colour). If it
    #    can't isolate any ink (unavailable, no text, or everything matches the
    #    background) fall through to the single-anchor colour-key, which handles
    #    a saturated title offline.
    anchors = _detect_anchors(prob, lab, block, bg, color_tol)
    from_detector = bool(anchors)
    if not from_detector:
        chroma = np.sqrt(lab[..., 1] ** 2 + lab[..., 2] ** 2)
        cthr = float(np.quantile(chroma[block], 0.92))
        if cthr < 18.0:
            return None  # no saturated title to key on — keep the block
        conf = block & (chroma >= cthr)
        if int(conf.sum()) < 200:
            return None
        title_lab = np.median(lab[conf], axis=0)
        # A fallback anchor that equals the DOMINANT background outside the brush
        # IS the plate, not the title — this is how the colour-key inverts on a
        # light title over saturated colour when the block clips the letters.
        if bg is not None and _matches_background(title_lab, bg):
            return None
        anchors = [(title_lab, color_tol, False)]

    # 2. Colour-distance segmentation — the union over the accepted anchors.
    letter = np.zeros_like(block)
    for cent, tol, _suspect in anchors:
        d = lab - cent
        letter |= block & (np.sqrt((d * d).sum(axis=-1)) < tol)
    letter = _despeckle((letter.astype(np.uint8)) * 255, min_area=40) > 0
    if not letter.any():
        return None

    # 3. Shape gates. Colour-key fallback: a plate survives erosion, letters
    #    vanish, so reject a plate-shaped result (the detector path skips this —
    #    its anchors are background-validated, and the erosion test false-rejects
    #    legitimately bold titles). Detector path with a SUSPECT anchor (ink that
    #    resembles the field): real ink stays concentrated in the detector box;
    #    a field-key spills across the block, so reject a spilled result.
    if not from_detector:
        er = max(3, round(0.006 * width))
        strokiness = 1.0 - int(_erode(letter, er).sum()) / int(letter.sum())
        if strokiness < 0.42:
            return None
    elif any(suspect for _cent, _tol, suspect in anchors):
        zone = _dilate(prob > 0.3, max(8, round(0.03 * width)))
        if int((letter & zone).sum()) / int(letter.sum()) < 0.6:
            return None

    if grow is None:
        # Small margin around the keyed strokes to cover anti-aliasing. Kept tight
        # so the mask hugs the letters (the wider the margin, the less precise);
        # to swallow a heavy glow/shadow, raise "Mask Dilation" (ai_mask_dilate),
        # which dilates the mask at erase time.
        grow = max(2, round(0.004 * width))
    grown = _dilate(letter, grow) if grow > 0 else letter
    grown &= block  # never mask more than the user brushed

    frac = int(grown.sum()) / int(block.sum())
    if not (0.03 <= frac <= 0.90):
        return None  # near-empty / near-full -> the model didn't fit; keep block

    out = Image.fromarray((grown.astype(np.uint8)) * 255)  # 2-D uint8 -> L PNG
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


# --- Colour-edge inking (a whiten helper, called from renderer.process_logo) ---
_INK_EDGE_THR = 0.16  # normalized Lab-gradient magnitude that reads as a keyline
_INK_WHITE_MIN = 0.60  # only ink where the whitened result is at least this light
_INK_BLACK_MAX = 0.35  # whitened luma below this is an EXISTING keyline


def _grad_mag(ch: np.ndarray) -> np.ndarray:
    """Central-difference gradient magnitude (numpy-only, no scipy/cv2)."""
    gx = np.zeros_like(ch)
    gy = np.zeros_like(ch)
    gx[:, 1:-1] = ch[:, 2:] - ch[:, :-2]
    gy[1:-1, :] = ch[2:, :] - ch[:-2, :]
    return np.sqrt(gx * gx + gy * gy)


def _erode(mask: np.ndarray, radius: int) -> np.ndarray:
    """Binary erosion = invert, dilate, invert (reuses :func:`_dilate`)."""
    return ~_dilate(~mask, radius)


def ink_color_edges(whitened_png: bytes, original_png: bytes) -> bytes:
    """Add crisp black keylines at COLOUR boundaries the two-tone whiten missed.

    The two-tone whiten turns every saturated/light region white, so two
    differently-*coloured* fills with no black outline between them merge into
    one white blob (a red swoosh under a white "GT"). This keys the ORIGINAL
    logo's colour edges — a ΔE gradient in Lab, so a hue flip at equal luma still
    registers — and inks a thin black line wherever (a) there's a strong interior
    colour edge and (b) the whitened result is currently white there (NO existing
    keyline). Edges sitting on the logo's own outlines are suppressed, so an
    already-outlined logo (Dragon Ball GT) is a NO-OP; only outline-less colour
    boundaries gain a separator.

    Both PNGs must be the same (trimmed) size. Returns the inked whitened PNG,
    or the input unchanged when there is nothing to add or on any decode failure
    (fail open — a bad decode must never break the render).
    """
    try:
        white = Image.open(io.BytesIO(whitened_png)).convert("RGBA")
        orig = Image.open(io.BytesIO(original_png)).convert("RGBA")
    except Exception:
        return whitened_png
    if white.size != orig.size:
        white = white.resize(orig.size, Image.LANCZOS)
    width = orig.width

    lab = _srgb_to_lab(np.asarray(orig.convert("RGB")).astype(np.float32))
    mag = (
        _grad_mag(lab[..., 0])
        + 1.5 * _grad_mag(lab[..., 1])
        + 1.5 * _grad_mag(lab[..., 2])
    )
    peak = float(mag.max())
    if peak <= 1e-6:
        return whitened_png  # flat original — nothing to separate
    edge = (mag / peak) > _INK_EDGE_THR

    opaque = np.asarray(orig)[..., 3] > 128
    interior = _erode(opaque, max(2, round(0.004 * width)))  # drop silhouette edge

    warr = np.asarray(white)
    wl = (0.299 * warr[..., 0] + 0.587 * warr[..., 1] + 0.114 * warr[..., 2]) / 255.0
    wa = warr[..., 3] > 128
    # Suppress ink near an existing keyline so an outlined logo stays a no-op.
    near_keyline = _dilate((wl < _INK_BLACK_MAX) & wa, max(3, round(0.006 * width)))

    add = edge & interior & (wl > _INK_WHITE_MIN) & wa & ~near_keyline
    add = _dilate(add, max(1, round(0.0015 * width))) & wa & ~near_keyline
    if not add.any():
        return whitened_png

    out = warr.copy()
    out[add, 0:3] = 0  # black keyline; alpha untouched
    buf = io.BytesIO()
    Image.fromarray(out).save(buf, "PNG")
    return buf.getvalue()


_DARK_BODY_LUMA = 0.20  # original luma below this is a candidate dark body
_DARK_BODY_CHROMA = 18.0  # ...and only if NEAR-NEUTRAL (vivid darks stay white)


def fill_dark_bodies(whitened_png: bytes, original_png: bytes) -> bytes:
    """Fill wide DARK bodies black — the companion to the small keyline blur.

    The keyline pass uses a small neighbourhood blur so it stays crisp (no muddy
    halos), but that means it only blackens dark pixels within a few px of an
    edge — a WIDE dark shape (a dark star body, a thick dark stroke) keeps a white
    core, because the sat/light key whitens it and nothing pulls the middle back.
    This fills genuinely dark ORIGINAL regions that are THICK — a morphological
    opening drops thin outlines and soft halos, so only real bodies fill. An
    already-crisp logo whose only darks are thin outlines (Dragon Ball GT) is a
    no-op. Both PNGs same (trimmed) size; input returned unchanged on any decode
    failure or when there is nothing thick and dark to fill.
    """
    try:
        white = Image.open(io.BytesIO(whitened_png)).convert("RGBA")
        orig = Image.open(io.BytesIO(original_png)).convert("RGBA")
    except Exception:
        return whitened_png
    if white.size != orig.size:
        white = white.resize(orig.size, Image.LANCZOS)
    width = orig.width

    o = np.asarray(orig)
    rgb = o[..., :3].astype(np.float32)
    luma = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]) / 255.0
    lab = _srgb_to_lab(rgb)
    chroma = np.sqrt(lab[..., 1] ** 2 + lab[..., 2] ** 2)
    # Only NEAR-NEUTRAL dark shapes fill (a shadow/silhouette that reads black). A
    # wide dark-but-VIVID fill — navy, maroon, deep teal — is a coloured fill the
    # two-tone key deliberately whitens, so it is spared here.
    dark = (luma < _DARK_BODY_LUMA) & (chroma < _DARK_BODY_CHROMA) & (o[..., 3] > 128)
    r = max(4, round(0.0075 * width))
    thick = _dilate(_erode(dark, r), r)  # opening: only bodies thicker than ~2r
    if not thick.any():
        return whitened_png

    out = np.asarray(white).copy()
    out[thick, 0:3] = 0  # black fill; alpha untouched
    buf = io.BytesIO()
    Image.fromarray(out).save(buf, "PNG")
    return buf.getvalue()


# --- 3D / extruded logos (a whiten MODE, called from renderer.process_logo) -----
_FACE_SOFT = 0.06  # +/- luma either side of the split, ramped for antialiasing
_FACE_MIN_FRAC = 0.12  # kept fraction of the opaque area below this -> not a face
_FACE_MAX_FRAC = 0.95  # ...and above this nothing was dropped -> not a 3D logo
_FACE_MIN_AREA = 64  # despeckle: drop kept components smaller than this (px)


def flatten_3d_logo(logo_png: bytes) -> Optional[bytes]:
    """Otsu-split an extruded logo's lit face from its extrusion; white-fill the face.

    None = not splittable (flat histogram, or a face too small/large to be the
    letterforms); the caller falls back to the flat silhouette.
    """
    try:
        src = Image.open(io.BytesIO(logo_png)).convert("RGBA")
    except Exception:
        return None
    arr = np.asarray(src).astype(np.float32) / 255.0
    rgb, alpha = arr[..., :3], arr[..., 3]
    luma = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    opaque = alpha > 0.5
    if not opaque.any():
        return None
    vals = luma[opaque]
    split = _otsu(vals)
    if split is None:
        return None
    # _otsu returns the FIRST bin that separates the classes, which on strongly
    # bimodal art sits on the dark class itself. Re-centre between the class means
    # so the ramp straddles the valley (one intermeans step).
    dark, lit = vals[vals <= split], vals[vals > split]
    if not dark.size or not lit.size:
        return None
    d_mean, l_mean = float(dark.mean()), float(lit.mean())
    if l_mean - d_mean <= 2 * _FACE_SOFT:
        return None  # planes too close to separate — the ramp would swallow both
    split = (d_mean + l_mean) / 2.0
    lo, hi = split - _FACE_SOFT, split + _FACE_SOFT
    ramp = np.clip((luma - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
    kept = _despeckle((ramp * alpha * 255).astype(np.uint8), min_area=_FACE_MIN_AREA)
    frac = float((kept > 128).sum()) / float(opaque.sum())
    if not _FACE_MIN_FRAC <= frac <= _FACE_MAX_FRAC:
        return None
    out = np.full(arr.shape, 255, dtype=np.uint8)  # white RGB...
    out[..., 3] = kept  # ...shaped by the face alone
    buf = io.BytesIO()
    Image.fromarray(out).save(buf, "PNG")
    return buf.getvalue()
