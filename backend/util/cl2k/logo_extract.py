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
        ring = (
            np.asarray(m.filter(ImageFilter.MaxFilter(45))) > 127
        ) & ~mask  # ~22px out
        pts = arr[ring]
        if len(pts) >= 50:
            sub = pts.astype(np.float32)[
                :: max(1, len(pts) // 4000)
            ]  # subsample, cheap
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


def _detect_title(image_bytes, arr, lab, block, width):
    """Title INK colour (Lab) via the DBNet detector, or ``None``.

    The detector localises the text LINE (colour-agnostic) as a filled box — it
    does NOT resolve individual strokes, so its band alone can't tell ink from the
    inter-glyph background. The robust anchor keys the ink against the TRUE
    background, sampled from just OUTSIDE the user's block (which bounds the
    title, so outside is real background — unlike a ring around the shrunk band,
    which the kernel contaminates). Within the box, the pixels FARTHEST from that
    background palette are the ink; their dominant colour cluster is the title
    colour — WHITE for white text, blue for blue, black for black, at any brush
    tightness. Returns ``None`` when the detector is unavailable, finds no text,
    or the ink is not clearly distinct from the background (no real title to key).

    KNOWN LIMIT (multi-region background): "farthest from the outside-block
    background" mis-picks the local plate as ink when the title sits on a distinct
    colour BAND that is itself farther (in Lab) from the surrounding field than
    the ink is, AND the brush spans both band and field. Then the plate is keyed
    (an inversion). Narrow and input-dependent; the tighten result is a reviewable
    prefill so the harm is a visible wrong mask the user re-brushes. Brushing
    within the band avoids it. Closing it needs an ink cue independent of the
    outside background (local contrast / inter-glyph cluster) — deliberately left
    out to avoid re-introducing the fragility of earlier band-based anchors.
    """
    from backend.util.cl2k.text_detect import detect_text_probmap

    prob = detect_text_probmap(image_bytes)
    if prob is None:
        return None
    if prob.shape != block.shape:  # e.g. _open_rgb_bounded downscaled a huge image
        prob = (
            np.asarray(
                Image.fromarray((np.clip(prob, 0, 1) * 255).astype(np.uint8)).resize(
                    (block.shape[1], block.shape[0]), Image.BILINEAR
                ),
                dtype=np.float32,
            )
            / 255.0
        )
    box = (prob > 0.3) & block
    if int(box.sum()) < 100:
        return None
    bg = _outside_background(lab, block, width)
    if bg is None:
        return None
    bg_cent, _bg_frac = bg

    # Ink = box pixels farthest from that background; dominant cluster = ink colour.
    box_lab = lab[box]
    dmin = np.sqrt(((box_lab[:, None, :] - bg_cent[None]) ** 2).sum(-1)).min(axis=1)
    ink = box_lab[dmin > np.median(dmin)]
    if ink.shape[0] < 50:
        return None
    ink = ink.astype(np.float32)[:: max(1, len(ink) // 4000)]
    cent, counts = _kmeans(ink, 3)
    title_lab = cent[int(np.argmax(counts))]

    if _matches_background(title_lab, bg):
        return None  # ink == a dominant background -> no real title; use colour-key
    return title_lab


def _outside_background(lab, block, width):
    """k-means Lab palette of the background sampled just OUTSIDE the brush.

    The block bounds the title, so a ring outside it is real background at any
    brush tightness. Returns ``None`` when there's no usable outside (a block that
    fills the frame). Used to key the title INK against — and to reject an anchor
    (detector or colour-key) that merely IS the background, i.e. an inversion.
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
    return bg_cent[keep], bg_counts[keep] / int(bg_counts.sum())


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
    color_tol: float = 33.0,
) -> Optional[bytes]:
    """Shrink a brushed *block* erase-mask down to the title's glyph strokes.

    A filled block hands the inpainter one big contiguous hole it can only fill
    with low-frequency mush (LaMa blurs the middle of a wide mask). Keying the
    block down to just the strokes leaves the real backdrop *between* the letters
    for the inpainter to sample, so the fill stays sharp.

    The title colour is found two ways, best first:

    1. **DBNet text detector** (:func:`_detect_title`) — localises the title by
       appearance and keys the ink against the background sampled outside the
       brush, so it isolates white/black/coloured titles the colour-key's
       most-saturated guess can't (and never inverts onto a saturated plate).
    2. **Fallback colour-key** — when the detector is unavailable/off, finds no
       text, or can't separate ink from background: anchor the colour from the
       most-saturated brushed pixels. Works for coloured titles; guarded by a
       stroke-shape gate so a plate-shaped result (an inversion) is rejected.

    Either way, every brushed pixel within ``color_tol`` ΔE76 of the title colour
    is kept — a uniform glyph body fills SOLID, a differently-coloured plate drops
    out — then ``grow`` re-dilates for anti-aliasing.

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

    # 1. Title colour — detector first (polarity-agnostic; keys the ink against
    #    the background sampled outside the brush). If it can't isolate a title
    #    (unavailable, no text, or ink == background) it returns None and we fall
    #    through to the colour-key, which handles a saturated title offline.
    title_lab = _detect_title(image_bytes, arr, lab, block, width)
    from_detector = title_lab is not None
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
        bg = _outside_background(lab, block, width)
        if bg is not None and _matches_background(title_lab, bg):
            return None

    # 2. Colour-distance segmentation (shared).
    d = lab - title_lab
    color_dist = np.sqrt((d * d).sum(axis=-1))
    letter = block & (color_dist < color_tol)
    letter = _despeckle((letter.astype(np.uint8)) * 255, min_area=40) > 0
    if not letter.any():
        return None

    # 3. Stroke-shape gate — only on the colour-key fallback. That path can key a
    #    saturated plate (a light title over colour) into a backwards mask; a
    #    plate survives erosion, letters vanish, so reject a plate-shaped result.
    #    The detector anchor is validated distinct-from-background, so its path
    #    skips this (and its false-reject of legitimately bold titles).
    if not from_detector:
        er = max(3, round(0.006 * width))
        strokiness = 1.0 - int(_erode(letter, er).sum()) / int(letter.sum())
        if strokiness < 0.42:
            return None

    if grow is None:
        # Margin around the colour-keyed strokes. Sized to swallow a title's
        # anti-aliased / semi-transparent GLOW and drop shadow, which fade a few
        # px past the solid-colour core — too tight a margin leaves that soft
        # fringe behind as a faint "ghost" of the title after the erase. A uniform
        # ring of nearby background is harmless to the inpaint (it fills from
        # context); the blur we avoid comes from big contiguous holes, not a rim.
        grow = max(3, round(0.008 * width))
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
