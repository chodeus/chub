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


class _QuadrantSession(_FakeSession):
    """Emits a probmap hot in the top-left quadrant, for coordinate round-trips."""

    def run(self, _outputs, feed):
        x = feed["x"]
        h, w = x.shape[2], x.shape[3]
        self.sizes.append((w, h))
        prob = np.zeros((1, 1, h, w), np.float32)
        prob[0, 0, : h // 2, : w // 2] = 1.0
        return [prob]


def test_probmap_caps_its_working_resolution(monkeypatch):
    # A big source previously cost one FULL-resolution float buffer per pyramid
    # level (~900 MB at 10000^2); the map is built and returned at the cap now.
    fake = _FakeSession()
    monkeypatch.setattr(text_detect, "_session", lambda: fake)
    prob = text_detect.detect_text_probmap(_jpeg((2600, 3900)))
    assert prob is not None
    cap = text_detect._MAX_WORK_SIDE
    assert max(prob.shape) == cap
    assert prob.shape == (cap, round(2600 / 3900 * cap))  # aspect preserved
    assert prob.nbytes < cap * cap * 4


def test_capping_does_not_change_the_network_input_dims(monkeypatch):
    # The pyramid only ever downscales to <=960, so the working cap must not move
    # a single pass — accuracy is unchanged, only the buffers shrink.
    fake = _FakeSession()
    monkeypatch.setattr(text_detect, "_session", lambda: fake)
    text_detect.detect_text_probmap(_jpeg((2600, 3900)))
    capped = list(fake.sizes)
    monkeypatch.setattr(text_detect, "_MAX_WORK_SIDE", 100000)
    fake.sizes.clear()
    text_detect.detect_text_probmap(_jpeg((2600, 3900)))
    assert capped == fake.sizes


def test_probmap_coordinates_survive_the_round_trip_to_caller_space(monkeypatch):
    from backend.util.cl2k.logo_extract import _sized_probmap

    fake = _QuadrantSession()
    monkeypatch.setattr(text_detect, "_session", lambda: fake)
    image = _jpeg((2600, 3900))
    prob = _sized_probmap(image, (1300, 867))  # caller's own working array
    assert prob.shape == (1300, 867)
    assert prob[1300 // 8, 867 // 8] > 0.9  # hot quadrant still top-left...
    assert prob[1300 * 7 // 8, 867 * 7 // 8] < 0.1  # ...and cold stays cold
