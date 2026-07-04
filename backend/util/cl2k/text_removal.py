"""AI text removal for the CL2K maker — a provider-agnostic seam.

Default is ``none`` (the textless-art strategy needs no AI). When a provider is
configured AND a user-brushed mask is supplied, the masked regions are erased by
the chosen backend:

- ``lama_sidecar`` — POST image+mask to a self-hosted lama-sidecar/IOPaint
  server. FREE, private, the recommended default. ``ai_endpoint`` = the inpaint
  URL; ``api_key`` is sent as X-API-Key when set (for a sidecar running with
  LAMA_API_KEY). (LaMa is what we benchmarked; excellent over texture, weaker
  over faces.)
- ``openai`` — OpenAI ``images.edit`` (gpt-image-1). PAID; better over faces, can
  hallucinate. ``api_key`` (+ optional ``ai_model``).

Mask convention here is **white (255) = remove**, black = keep (what the brush UI
and LaMa/IOPaint use). Each backend takes the original image + mask and returns
cleaned image bytes. Pass-through (input returned unchanged) when the provider is
none/disabled or no mask is supplied. Exceptions propagate to the caller.
"""

from __future__ import annotations

import base64
import io
import time
from typing import Optional

_TIMEOUT_DEFAULT = 120


def is_enabled(config) -> bool:
    """True only when a real AI provider is configured."""
    return bool(config and getattr(config, "ai_provider", "none") not in ("", "none"))


def unavailable_reason(config) -> Optional[str]:
    """Why an explicit AI erase can't run, or None if it can.

    The /retext endpoint calls this so a user-triggered "Send to AI" fails
    loudly when the provider is misconfigured, instead of silently returning the
    image unchanged. (The generate path stays lenient and just skips — it must
    not fail a whole render over a missing key.)
    """
    provider = getattr(config, "ai_provider", "none") if config else "none"
    if provider in ("", "none"):
        return "AI provider is 'none' — set one in Module Settings → CL2K Maker."
    if provider == "openai" and not getattr(config, "api_key", ""):
        return (
            "No API key set for the 'openai' provider — "
            "add one in Module Settings → CL2K Maker."
        )
    if provider == "lama_sidecar" and not getattr(config, "ai_endpoint", ""):
        return (
            "No AI Endpoint set for the LaMa sidecar — "
            "add your container URL in Module Settings → CL2K Maker."
        )
    if provider not in ("lama_sidecar", "openai"):
        # e.g. a leftover 'huggingface' config from before that provider was
        # dropped (its payload never matched a real HF API).
        return (
            f"Unknown AI provider '{provider}' — "
            "choose one in Module Settings → CL2K Maker."
        )
    return None


def remove_text(
    image_bytes: bytes,
    *,
    config=None,
    mask_bytes: Optional[bytes] = None,
    prompt: Optional[str] = None,
    logger=None,
) -> bytes:
    """Erase the masked regions via the configured provider; else pass-through.

    ``prompt`` overrides the module-settings ``ai_prompt`` for this one call
    (used by the poster-editor so a per-edit prompt can be supplied while still
    defaulting to the configured prompt). ``logger`` (optional) receives
    start/elapsed/status lines so a slow or failing AI call is visible in the
    logs instead of timing out silently.
    """
    if not is_enabled(config):
        return image_bytes
    provider = getattr(config, "ai_provider", "none")
    # The brush canvas is sized to the *displayed* image (same aspect ratio,
    # fewer pixels), so the mask arrives at display resolution. LaMa / HF expect
    # mask dimensions == image dimensions and don't reliably resize server-side
    # — normalize once here for every provider (OpenAI re-resizes internally;
    # _composite_masked likewise — both harmless after this).
    if mask_bytes:
        mask_bytes = _mask_to_image_dims(image_bytes, mask_bytes)
    # LaMa / HF are blind — they only fill what is masked, so without a mask
    # there is nothing to do. OpenAI is a vision model and can remove text from
    # the prompt alone, so a mask is optional there.
    if provider == "lama_sidecar":
        if not mask_bytes:
            return image_bytes
        result = _lama_sidecar(image_bytes, mask_bytes, config)
    elif provider == "openai":
        result = _openai(image_bytes, mask_bytes, config, prompt=prompt, logger=logger)
    else:
        return image_bytes

    # Generative providers (OpenAI, and Firefly via handoff) re-render the WHOLE
    # canvas, which alters faces. When a mask is supplied, keep their fill ONLY
    # inside the masked region and restore the original pixels everywhere else,
    # so the artwork outside the text is preserved exactly. NEVER do this for
    # the LaMa sidecar: it dilates the mask server-side to erase the logo's
    # anti-aliased fringe/glow, so re-compositing with our tight brush mask
    # would paint that fringe right back (and it already guarantees only masked
    # pixels change).
    if mask_bytes and result is not image_bytes and provider != "lama_sidecar":
        result = _composite_masked(image_bytes, result, mask_bytes)
    return result


def _mask_to_image_dims(image_bytes: bytes, mask_bytes: bytes) -> bytes:
    """Resize the brushed mask to the image's pixel dimensions (PNG bytes).

    Pass-through when the sizes already match or either decode fails (the
    provider call then behaves exactly as before this normalization existed).
    """
    from PIL import Image

    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            size = im.size
        mask = Image.open(io.BytesIO(mask_bytes)).convert("L")
        if mask.size == size:
            return mask_bytes
        buf = io.BytesIO()
        mask.resize(size).save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return mask_bytes


def _composite_masked(
    original_bytes: bytes, result_bytes: bytes, mask_bytes: bytes
) -> bytes:
    """Keep ``result`` only where the mask is white; original pixels elsewhere."""
    from PIL import Image, ImageFilter

    orig = Image.open(io.BytesIO(original_bytes)).convert("RGB")
    res = (
        Image.open(io.BytesIO(result_bytes))
        .convert("RGB")
        .resize(orig.size, Image.Resampling.LANCZOS)
    )
    mask = (
        Image.open(io.BytesIO(mask_bytes))
        .convert("L")
        .resize(orig.size)
        .filter(ImageFilter.GaussianBlur(4))  # feather for a seamless blend
    )
    out = Image.composite(res, orig, mask)
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


def _timeout(config) -> int:
    return int(getattr(config, "ai_timeout", _TIMEOUT_DEFAULT) or _TIMEOUT_DEFAULT)


def _lama_url(endpoint: str) -> str:
    """Resolve the sidecar inpaint URL (see :func:`_lama_route`)."""
    return _lama_route(endpoint, "/api/v1/inpaint")


def _lama_route(endpoint: str, path: str) -> str:
    """Resolve a sidecar route URL from whatever the user typed.

    Users set ``ai_endpoint`` to their container's address — ``host:8080`` or
    ``http://host:8080`` — and we fill in the sidecar ``path`` so they don't have
    to know it. A scheme is added when missing; an endpoint that already carries
    a path (custom sidecar behind a proxy) is left as-is. Every route (inpaint,
    upscale, detect) resolves the same way, so a custom path is honoured
    consistently instead of only for inpaint.
    """
    from urllib.parse import urlparse, urlunparse

    raw = (endpoint or "").strip().rstrip("/")
    if not raw:
        return raw
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    if parsed.path in ("", "/"):
        parsed = parsed._replace(path=path)
    return urlunparse(parsed)


def _lama_headers(config) -> dict:
    """X-API-Key for a sidecar running with LAMA_API_KEY; empty when keyless
    (the sidecar ignores the header unless it has a key configured)."""
    key = getattr(config, "api_key", "")
    return {"X-API-Key": key} if key else {}


def _lama_sidecar(image_bytes: bytes, mask_bytes: bytes, config) -> bytes:
    """IOPaint/LaMa server: {image, mask} (base64, white=remove) -> cleaned image."""
    import requests

    url = _lama_url(getattr(config, "ai_endpoint", ""))
    if not url:
        return image_bytes
    payload = {
        "image": base64.b64encode(image_bytes).decode(),
        "mask": base64.b64encode(mask_bytes).decode(),
    }
    # Per-request dilation override (>=0); -1 leaves the sidecar's own default.
    # Older sidecars ignore unknown JSON fields, so this is backwards-compatible.
    # 0 is a real value (dilation OFF) — only None falls back, never `or`.
    raw_dilate = getattr(config, "ai_mask_dilate", -1)
    dilate = -1 if raw_dilate is None else int(raw_dilate)
    if dilate >= 0:
        payload["dilate"] = dilate
    resp = requests.post(
        url, json=payload, headers=_lama_headers(config), timeout=_timeout(config)
    )
    resp.raise_for_status()
    return resp.content


def upscale_image(
    image_bytes: bytes, config, scale: int = 0, logger=None
) -> Optional[bytes]:
    """2x/4x super-resolution via the sidecar's /api/v1/upscale (logos only).

    Best-effort: returns the upscaled PNG bytes, or None on ANY failure —
    provider not lama_sidecar, endpoint unset, an older sidecar without the
    endpoint (404), timeout, or a server error — so callers can fall back to
    exactly the behaviour they had before this endpoint existed.
    ``scale`` 0 picks automatically: 4x for very small art, else 2x.
    """
    import requests

    if getattr(config, "ai_provider", "none") != "lama_sidecar":
        return None
    endpoint = getattr(config, "ai_endpoint", "")
    if not endpoint:
        return None
    url = _lama_route(endpoint, "/api/v1/upscale")
    if scale not in (2, 4):
        try:
            from PIL import Image

            with Image.open(io.BytesIO(image_bytes)) as im:
                scale = 4 if im.width < 200 else 2
        except Exception:
            scale = 2
    try:
        resp = requests.post(
            url,
            json={"image": base64.b64encode(image_bytes).decode(), "scale": scale},
            headers=_lama_headers(config),
            timeout=_timeout(config),
        )
        if resp.status_code != 200:
            if logger:
                logger.info(
                    f"CL2K AI: logo upscale unavailable ({resp.status_code}) — "
                    "using the original"
                )
            return None
        return resp.content
    except Exception as exc:
        if logger:
            logger.info(f"CL2K AI: logo upscale failed ({exc}) — using the original")
        return None


def _openai(
    image_bytes: bytes,
    mask_bytes: Optional[bytes],
    config,
    prompt: Optional[str] = None,
    logger=None,
) -> bytes:
    """OpenAI images.edit (gpt-image-1).

    Mask-optional: with no mask, the prompt alone drives removal (the model finds
    the text — but it regenerates the whole image, so fidelity isn't pixel-exact).
    With a mask, only that region is edited; OpenAI marks the edit area with
    TRANSPARENCY, so we invert our white=remove mask to alpha-0-where-remove.

    ``prompt`` (per-call) overrides ``config.ai_prompt`` when provided. ``logger``
    (optional) logs the model, image size, elapsed time and HTTP status so a slow
    or failing edit is diagnosable (gpt-image-1 edits routinely take 30–120s).
    """
    import requests
    from PIL import Image

    key = getattr(config, "api_key", "")
    if not key:
        if logger:
            logger.warning("CL2K AI (openai): no api_key set — skipping text removal")
        return image_bytes
    model = getattr(config, "ai_model", "") or "gpt-image-1"
    prompt = (
        (prompt or "").strip()
        or getattr(config, "ai_prompt", "")
        or ("Remove all text from this image and reconstruct the background.")
    )

    src = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img_buf = io.BytesIO()
    src.save(img_buf, "PNG")  # gpt-image-1 edits expect PNG input
    files = {"image": ("image.png", img_buf.getvalue(), "image/png")}
    data = {"model": model, "prompt": prompt, "size": "auto"}

    if mask_bytes:
        m = Image.open(io.BytesIO(mask_bytes)).convert("L").resize(src.size)
        rgba = Image.new("RGBA", src.size, (0, 0, 0, 255))
        rgba.putalpha(Image.eval(m, lambda px: 255 - px))  # white(remove) -> alpha 0
        mask_buf = io.BytesIO()
        rgba.save(mask_buf, "PNG")
        files["mask"] = ("mask.png", mask_buf.getvalue(), "image/png")

    timeout = _timeout(config)
    if not mask_bytes and logger:
        logger.warning(
            "CL2K AI (openai): no mask supplied — the WHOLE poster is regenerated "
            "(faces altered, fidelity not pixel-exact, resolution capped at the "
            "model's native size). Brush a mask to preserve the artwork outside "
            "the text."
        )
    if logger:
        logger.info(
            f"CL2K AI (openai): images.edit start — model={model}, "
            f"image={src.width}x{src.height}, mask={'yes' if mask_bytes else 'no'}, "
            f"timeout={timeout}s"
        )
    started = time.time()
    try:
        resp = requests.post(
            "https://api.openai.com/v1/images/edits",
            headers={"Authorization": f"Bearer {key}"},
            files=files,
            data=data,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        elapsed = time.time() - started
        if logger:
            logger.error(
                f"CL2K AI (openai): images.edit failed after {elapsed:.1f}s "
                f"(network/timeout): {exc}"
            )
        raise
    elapsed = time.time() - started
    if logger:
        logger.info(
            f"CL2K AI (openai): images.edit responded {resp.status_code} "
            f"in {elapsed:.1f}s"
        )
    if not resp.ok:
        # Surface the API's own error message (e.g. quota/content-policy) so it
        # lands in the logs rather than a bare status code.
        body = (resp.text or "")[:300]
        if logger:
            logger.error(
                f"CL2K AI (openai): images.edit returned {resp.status_code}: {body}"
            )
        resp.raise_for_status()
    return base64.b64decode(resp.json()["data"][0]["b64_json"])


