"""PP-OCRv4 DBNet text detector (ONNX) — a colour/polarity-agnostic text
localiser for the CL2K "tighten to letters" anchor.

The colour-key alone has to GUESS which colour is the title (it assumes the
most-saturated thing in the brush is the text), which inverts on a light title
over a saturated plate. A DBNet detector localises text by appearance, not
colour, so it pins the title regardless of polarity — the tighten anchors then
read the true ink colours from the detected strokes.

Fail-soft by design: every entry point returns ``None`` if onnxruntime or the
vendored model is unavailable, or on any inference error, so ``tighten_text_mask``
degrades to the colour-key rather than breaking. The model
(``models/ppocr_v4_det.onnx``, ~4.7 MB) is a ':full'-image vendored asset;
``onnxruntime`` is in requirements-cl2k.txt.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

import numpy as np
from PIL import Image

from backend.util.cl2k.limits import open_bounded

_log = logging.getLogger(__name__)

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "ppocr_v4_det.onnx")
# DBNet preprocessing (PP-OCR): ImageNet mean/std, /255, NCHW.
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
# Long-side pyramid, max-merged. DBNet misses display type that is LARGE relative
# to its input (the glyphs outgrow the receptive field), and a single 960 pass
# skipped whole title lines on real posters; the smaller passes bring huge
# lettering back into range. Only-downscale, so tiny images dedupe to one pass.
_SCALES = (960, 640, 448, 320)
# Working long side the map is built (and returned) at. Every pass downsamples to
# 960 or less anyway, so 2x that costs no accuracy and bounds the float buffers.
_MAX_WORK_SIDE = 2048


_SESSION = None
_SESSION_LOCK = threading.Lock()


def _session():
    """Cached ORT session, or None when onnxruntime/model is unavailable.
    A failed init is transient — never cached, so it retries next call."""
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    if not os.path.exists(_MODEL_PATH):
        return None
    try:
        import onnxruntime as ort  # optional dep — absent => colour-key fallback
    except Exception:
        return None
    # Build inside the lock (double-checked) so a request burst spawns ONE session,
    # not several racing InferenceSessions (OOM / provider-init failure).
    with _SESSION_LOCK:
        if _SESSION is not None:  # another caller built it while we waited
            return _SESSION
        try:
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2  # gentle on the shared worker
            _SESSION = ort.InferenceSession(
                _MODEL_PATH, sess_options=opts, providers=["CPUExecutionProvider"]
            )
        except Exception as exc:
            _log.warning(
                "cl2k text detector unavailable this call (will retry): %s", exc
            )
            return None
        return _SESSION


def available() -> bool:
    """Whether the detector can run (onnxruntime importable + model present)."""
    return _session() is not None


def detect_text_probmap(image_bytes: bytes) -> Optional[np.ndarray]:
    """DBNet text-probability heatmap for ``image_bytes``.

    Returns an ``HxW`` float array in ``[0, 1]`` (high on text, low elsewhere),
    or ``None`` when the detector is unavailable or errors. High values are
    text-line cores (DBNet predicts a shrunk kernel), so a threshold gives a
    polarity-agnostic text-line mask, not per-glyph. Runs the ``_SCALES`` pyramid
    and max-merges, so both huge display titles and small credit lines register
    in one map.

    The map is at the ``_MAX_WORK_SIDE`` working size, NOT the source's: a big
    source would otherwise cost a full-resolution float buffer per pyramid level.
    Callers scale it to their own array (see ``logo_extract._sized_probmap``).
    """
    sess = _session()
    if sess is None:
        return None
    try:
        img = open_bounded(image_bytes, "RGB")
        if max(img.size) > _MAX_WORK_SIDE:
            img.thumbnail((_MAX_WORK_SIDE, _MAX_WORK_SIDE), Image.LANCZOS)
        w, h = img.size
        name = sess.get_inputs()[0].name
        merged = None
        seen = set()
        for limit in _SCALES:
            scale = min(limit / max(w, h), 1.0)  # only downscale
            nw = max(32, int(round(w * scale)) // 32 * 32)  # DBNet needs /32 dims
            nh = max(32, int(round(h * scale)) // 32 * 32)
            if (nw, nh) in seen:  # small image — several limits collapse to one
                continue
            seen.add((nw, nh))
            x = (
                np.asarray(img.resize((nw, nh), Image.BILINEAR), dtype=np.float32)
                / 255.0
            )
            x = ((x - _MEAN) / _STD).transpose(2, 0, 1)[None]
            prob = sess.run(None, {name: x})[0][0, 0]  # HxW in [0, 1]
            up = Image.fromarray(
                (np.clip(prob, 0.0, 1.0) * 255).astype(np.uint8)
            ).resize((w, h), Image.BILINEAR)
            arr = np.asarray(up, dtype=np.float32) / 255.0
            merged = arr if merged is None else np.maximum(merged, arr)
        return merged
    except Exception:
        return None
