"""AI text removal for the CL2K maker — a provider-agnostic seam.

Default is ``none`` (the textless-art strategy needs no AI). When a provider is
configured AND a user-brushed mask is supplied, the masked regions are erased by
the chosen backend:

- ``lama_sidecar`` — POST image+mask to a self-hosted IOPaint/LaMa server. FREE,
  private, the recommended default. ``ai_endpoint`` = the inpaint URL. (LaMa is
  what we benchmarked; excellent over texture, weaker over faces.)
- ``openai`` — OpenAI ``images.edit`` (gpt-image-1). PAID; better over faces, can
  hallucinate. ``ai_api_key`` (+ optional ``ai_model``).
- ``huggingface`` — HF inference API inpainting. Free tier, rate-limited.
  ``ai_endpoint`` = model URL, ``ai_api_key`` = HF token.

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
    # LaMa / HF are blind — they only fill what is masked, so without a mask
    # there is nothing to do. OpenAI is a vision model and can remove text from
    # the prompt alone, so a mask is optional there.
    if provider == "lama_sidecar":
        if not mask_bytes:
            return image_bytes
        result = _lama_sidecar(image_bytes, mask_bytes, config)
    elif provider == "huggingface":
        if not mask_bytes:
            return image_bytes
        result = _huggingface(image_bytes, mask_bytes, config)
    elif provider == "openai":
        result = _openai(image_bytes, mask_bytes, config, prompt=prompt, logger=logger)
    else:
        return image_bytes

    # Generative providers (OpenAI, and Firefly via handoff) re-render the WHOLE
    # canvas, which alters faces. When a mask is supplied, keep their fill ONLY
    # inside the masked region and restore the original pixels everywhere else,
    # so the artwork outside the text is preserved exactly. (LaMa already
    # preserves; compositing is harmless for it.)
    if mask_bytes and result is not image_bytes:
        result = _composite_masked(image_bytes, result, mask_bytes)
    return result


def _composite_masked(original_bytes: bytes, result_bytes: bytes, mask_bytes: bytes) -> bytes:
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


def _lama_sidecar(image_bytes: bytes, mask_bytes: bytes, config) -> bytes:
    """IOPaint/LaMa server: {image, mask} (base64, white=remove) -> cleaned image."""
    import requests

    endpoint = getattr(config, "ai_endpoint", "")
    if not endpoint:
        return image_bytes
    payload = {
        "image": base64.b64encode(image_bytes).decode(),
        "mask": base64.b64encode(mask_bytes).decode(),
    }
    resp = requests.post(endpoint, json=payload, timeout=_timeout(config))
    resp.raise_for_status()
    return resp.content


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

    key = getattr(config, "ai_api_key", "")
    if not key:
        if logger:
            logger.warning("CL2K AI (openai): no ai_api_key set — skipping text removal")
        return image_bytes
    model = getattr(config, "ai_model", "") or "gpt-image-1"
    prompt = (prompt or "").strip() or getattr(config, "ai_prompt", "") or (
        "Remove all text from this image and reconstruct the background."
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


def _huggingface(image_bytes: bytes, mask_bytes: bytes, config) -> bytes:
    """HF inference API inpainting (free tier, rate-limited)."""
    import requests

    endpoint = getattr(config, "ai_endpoint", "")
    if not endpoint:
        return image_bytes
    key = getattr(config, "ai_api_key", "")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    payload = {
        "inputs": base64.b64encode(image_bytes).decode(),
        "mask": base64.b64encode(mask_bytes).decode(),
        "parameters": {"prompt": "clean background, no text"},
    }
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=_timeout(config))
    resp.raise_for_status()
    return resp.content
