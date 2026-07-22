"""Tests for the DBNet probmap wrapper (scale-pyramid merge + fail-soft).

No ONNX inference: a fake session records the input dims per run and emits a
constant probmap, which pins the pyramid/dedupe/merge behaviour without the
model's weights in the loop.
"""

import io

import numpy as np
from PIL import Image

from backend.util.cl2k import text_detect


def _jpeg(size=(400, 600), color=(30, 40, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


class _FakeSession:
    """Records per-call input dims; emits a constant-1 probmap."""

    class _Input:
        name = "x"

    def __init__(self):
        self.sizes = []

    def get_inputs(self):
        return [self._Input()]

    def run(self, _outputs, feed):
        x = feed["x"]
        self.sizes.append((x.shape[3], x.shape[2]))  # (w, h)
        return [np.ones((1, 1, x.shape[2], x.shape[3]), np.float32)]


def test_probmap_runs_the_scale_pyramid_and_merges(monkeypatch):
    fake = _FakeSession()
    monkeypatch.setattr(text_detect, "_session", lambda: fake)
    prob = text_detect.detect_text_probmap(_jpeg((800, 1200)))
    assert prob is not None
    assert prob.shape == (1200, 800)  # image-sized, HxW
    assert prob.min() >= 0.99  # constant-1 inputs merge to a full map
    assert len(fake.sizes) == len(text_detect._SCALES)  # all scales distinct
    assert len(set(fake.sizes)) == len(fake.sizes)


def test_probmap_dedupes_collapsed_scales(monkeypatch):
    # A small image only-downscales to the SAME network dims for every limit —
    # the duplicate passes are skipped.
    fake = _FakeSession()
    monkeypatch.setattr(text_detect, "_session", lambda: fake)
    prob = text_detect.detect_text_probmap(_jpeg((100, 150)))
    assert prob is not None
    assert prob.shape == (150, 100)
    assert len(fake.sizes) < len(text_detect._SCALES)
    assert len(set(fake.sizes)) == len(fake.sizes)


def test_probmap_none_when_detector_unavailable(monkeypatch):
    monkeypatch.setattr(text_detect, "_session", lambda: None)
    assert text_detect.detect_text_probmap(_jpeg()) is None
