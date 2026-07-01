# backend/util/cl2k/config.py
"""Pydantic config model for the CL2K maker.

Grafted onto ChubConfig by backend/extensions/cl2k/manifest.py
(config_fields), so ``load_config().cl2k_maker`` is typed exactly like the
core module sections. Lives here (not backend/util/config.py) because the
CL2K maker is a develop-only extension.
"""

from typing import List

from pydantic import BaseModel, Field

# Image types the CL2K maker can emit; a destination routes any subset of these.
CL2K_IMAGE_TYPES = ("poster", "logo", "background", "squareart")


class Cl2kDestination(BaseModel):
    """One optional named routing target.

    Generated art whose ``image_type`` is in ``image_types`` is written to this
    ``output_dir`` and (when ``upload_to_gdrive``) uploaded to this
    ``gdrive_folder_id`` — instead of the single default fields on
    ``Cl2kMakerConfig``. Purely additive: an empty ``destinations`` list keeps
    the original single-dir / single-folder behaviour.
    """

    name: str = ""
    # Any of CL2K_IMAGE_TYPES. Empty = matches nothing (an inert row).
    image_types: List[str] = Field(default_factory=list)
    output_dir: str = ""
    upload_to_gdrive: bool = False
    gdrive_folder_id: str = ""


class Cl2kMakerConfig(BaseModel):
    log_level: str = "info"
    # Local source_dir where generated CL2K posters land (then matched by
    # poster_renamerr). Should be one of poster_renamerr.source_dirs.
    output_dir: str = ""
    language: str = "en"
    whiten_logo: bool = True
    text_logo_fallback: bool = True  # synth a typeset wordmark when no real logo
    # Outline width (px at the internal render scale) for the text-logo wordmark;
    # 0 = none (clean white, the CL2K default). A small value (~4) adds legibility
    # over busy art. The wordmark itself is balance-wrapped to fill the logo box.
    text_logo_stroke: int = Field(default=0, ge=0, le=20)
    skip_existing: bool = True
    style: str = "CL2K"  # poster_cache style tag
    priority: int = 0
    # Google Drive upload (rclone copy) — optional, off by default. Uploads use
    # the Sync GDrive OAuth token (a service account can't own files in a personal
    # Drive — "Service Accounts do not have storage quota"), so there is no
    # per-module SA option here.
    upload_to_gdrive: bool = False
    gdrive_folder_id: str = ""
    # Optional per-image-type routing. When a generated file's image_type
    # matches a destination, that destination's output_dir + Drive folder are
    # used instead of the single default fields above. Empty = default
    # behaviour (everything to output_dir / gdrive_folder_id). Opt-in only.
    destinations: List[Cl2kDestination] = Field(default_factory=list)
    # AI text removal (provider-agnostic; off by default = textless-art strategy).
    # Requires a user-brushed mask. lama_sidecar = free/local; openai = paid;
    # huggingface = free tier (rate-limited). Firefly/ChatGPT-free have no usable
    # API — use the manual export/import handoff for those.
    ai_provider: str = "none"  # none | lama_sidecar | openai | huggingface
    ai_endpoint: str = ""  # lama sidecar URL, or HF model inference URL
    # openai / huggingface token. Named ``api_key`` (not ``ai_api_key``) so the
    # core secret-redaction list — which matches on exact leaf key names — masks
    # it on GET /api/config like every other secret. Don't re-prefix it.
    api_key: str = ""
    ai_model: str = ""  # openai model id (default gpt-image-1) / HF model id
    ai_timeout: int = 120
    # OpenAI/HF prompt. OpenAI can remove text from this prompt ALONE (no mask);
    # a brushed mask, when present, restricts the edit to that region.
    ai_prompt: str = (
        "Remove all text, titles, credits, logos and watermarks from this image. "
        "Seamlessly reconstruct the underlying artwork and background where the "
        "text was. Do not change anything else."
    )
