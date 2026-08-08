"""Tests for /cl2k-maker/extract-logo's erase mode.

``mode="erase"`` runs the AI eraser server-side and diffs the result, so it is
the only extract mode that can fail for reasons outside the image: no brush, no
provider, or a provider that quietly hands the poster back. Each of those must
surface as a readable error — a pass-through would diff to nothing and look
like a bad brush.
"""

import base64
import io
import json
import types

import pytest

pytest.importorskip("wand.image")  # backend.api.cl2k_maker pulls in the renderer

from PIL import Image, ImageDraw  # noqa: E402

import backend.api.cl2k_maker as cl2k_api  # noqa: E402
from backend.api.cl2k_maker import ExtractLogoRequest, extract_logo  # noqa: E402

_FIELD = (40, 45, 55)
_TITLE_BOX = (60, 100, 340, 140)


def _b64(img: Image.Image, mode="RGB") -> str:
    buf = io.BytesIO()
    img.convert(mode).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _poster() -> Image.Image:
    img = Image.new("RGB", (400, 240), _FIELD)
    ImageDraw.Draw(img).rectangle(_TITLE_BOX, fill=(255, 255, 255))
    return img


def _mask_b64() -> str:
    mask = Image.new("L", (400, 240), 0)
    ImageDraw.Draw(mask).rectangle((40, 80, 360, 160), fill=255)
    return _b64(mask, "L")


def _logger():
    noop = lambda *a, **k: None  # noqa: E731
    return types.SimpleNamespace(debug=noop, info=noop, warning=noop, error=noop)


@pytest.fixture
def provider(monkeypatch):
    """Set the configured AI provider; returns the erase call's recorded args."""
    seen = {}

    def _set(ai_provider="lama_sidecar", erased=None, raises=None):
        cfg = types.SimpleNamespace(
            ai_provider=ai_provider, ai_endpoint="http://sidecar:8418", api_key=""
        )
        monkeypatch.setattr(
            cl2k_api, "load_config", lambda: types.SimpleNamespace(cl2k_maker=cfg)
        )

        def fake_remove_text(image_bytes, *, config=None, mask_bytes=None, **kw):
            seen["mask_bytes"], seen["config"] = mask_bytes, config
            if raises:
                raise raises
            return image_bytes if erased is None else erased

        monkeypatch.setattr(cl2k_api.text_removal, "remove_text", fake_remove_text)
        return seen

    return _set


def _call(**kw):
    req = ExtractLogoRequest(image_b64=_b64(_poster()), mode="erase", **kw)
    return extract_logo(req, db=object(), logger=_logger())


def _body(resp):
    return json.loads(bytes(resp.body))


def test_erase_without_a_brush_is_rejected(provider):
    provider()
    resp = _call()
    assert resp.status_code == 400
    assert _body(resp)["error_code"] == "NO_MASK"


def test_erase_without_a_provider_says_so(provider):
    provider(ai_provider="none")
    resp = _call(mask_b64=_mask_b64())
    assert resp.status_code == 400
    assert _body(resp)["error_code"] == "CL2K_AI_UNAVAILABLE"


def test_erase_reports_a_provider_that_returns_the_poster_unchanged(provider):
    """remove_text passes the original through when the provider bails. Diffing
    that keys nothing, so this must error rather than return a blank logo."""
    provider(erased=None)
    resp = _call(mask_b64=_mask_b64())
    assert resp.status_code == 400
    assert _body(resp)["error_code"] == "CL2K_AI"


def test_erase_reports_a_failing_provider(provider):
    provider(raises=RuntimeError("sidecar timeout"))
    resp = _call(mask_b64=_mask_b64())
    assert resp.status_code == 400
    body = _body(resp)
    assert body["error_code"] == "CL2K_AI"
    assert "sidecar timeout" in body["message"]


def test_erase_keys_the_title_out_of_the_erased_result(provider, monkeypatch):
    from backend.util.cl2k import text_detect

    monkeypatch.setattr(text_detect, "detect_text_probmap", lambda _b: None)
    cleaned = Image.new("RGB", (400, 240), _FIELD)  # title fully inpainted away
    buf = io.BytesIO()
    cleaned.save(buf, "PNG")
    seen = provider(erased=buf.getvalue())

    resp = _call(mask_b64=_mask_b64())
    assert resp.status_code == 200
    assert resp.media_type == "image/png"
    assert seen["mask_bytes"], "the brush must reach the eraser — LaMa is blind"
    # The cl2k section, not the whole ChubConfig: remove_text reads ai_provider
    # off it and would silently pass the poster through given the wrong object.
    assert getattr(seen["config"], "ai_provider", None) == "lama_sidecar"
    res = Image.open(io.BytesIO(resp.body))
    assert res.mode == "RGBA"
    assert 250 <= res.width <= 320  # trimmed to the title bar
    assert res.getpixel((res.width // 2, res.height // 2))[3] > 200
