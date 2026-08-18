# backend/util/cl2k/config.py
"""Pydantic config model for the CL2K maker.

Grafted onto ChubConfig by backend/extensions/cl2k/manifest.py
(config_fields), so ``load_config().cl2k_maker`` is typed exactly like the
core module sections. Lives here (not backend/util/config.py) because the
CL2K maker is part of the :full image.
"""

from typing import List

from pydantic import BaseModel, Field, model_validator

# Image types the CL2K maker can emit; a save location claims any subset of these.
CL2K_IMAGE_TYPES = ("poster", "logo", "background", "squareart")


class Cl2kLocalFolder(BaseModel):
    """One named local save target.

    Generated art whose ``image_type`` is in ``types`` is written into ``path``.
    A type may be claimed by any number of folders (every claimer gets a copy);
    a type nobody claims isn't auto-saved and stays downloadable from the maker
    page. Empty ``types`` = an inert row (keeps the path visible, saves nothing).
    """

    name: str = ""
    path: str = ""
    # Any of CL2K_IMAGE_TYPES.
    types: List[str] = Field(default_factory=list)


class Cl2kGdriveUpload(BaseModel):
    """One named Google Drive upload target (same claim semantics as
    :class:`Cl2kLocalFolder`). Uploads use the Sync GDrive OAuth token — a
    service account can't own files in a personal Drive, so there is no
    per-entry SA option."""

    name: str = ""
    folder_id: str = ""
    types: List[str] = Field(default_factory=list)


class Cl2kMakerConfig(BaseModel):
    log_level: str = "info"
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
    # Save locations — two routed lists, nothing mandatory. Each entry claims a
    # subset of CL2K_IMAGE_TYPES; a type may route to any number of locations
    # (every claimer gets a copy). Zero locations is valid: unrouted types
    # simply aren't auto-saved and stay downloadable from the maker page.
    local_folders: List[Cl2kLocalFolder] = Field(default_factory=list)
    gdrive_uploads: List[Cl2kGdriveUpload] = Field(default_factory=list)
    # AI text removal (provider-agnostic; off by default = textless-art strategy).
    # Requires a user-brushed mask. lama_sidecar = free/local; openai = paid.
    # Firefly/ChatGPT-free have no usable API — use the manual export/import
    # handoff for those.
    ai_provider: str = "none"  # none | lama_sidecar | openai
    ai_endpoint: str = ""  # lama sidecar URL
    # openai token. Name is redaction-driven (the core secret list matches exact
    # leaf keys) — don't re-prefix it to ai_api_key.
    api_key: str = ""
    # Sidecar's LAMA_API_KEY, sent as X-API-Key. Own field so both providers'
    # credentials coexist; same redaction-driven naming.
    client_key: str = ""
    ai_model: str = ""  # openai model id (default gpt-image-1)
    # The sidecar's quality passes (snap + native boundary refine, v1.6+) add
    # roughly one extra inference per erase, which can push a busy CPU box
    # well past the old 120s.
    ai_timeout: int = 300
    # Per-request mask dilation sent to the lama sidecar; -1 = the sidecar's own
    # default (5). The ghost-fringe knob: raise for glowing/beveled logos, lower
    # when masks are already generous — tunable here without a container restart.
    ai_mask_dilate: int = Field(default=-1, ge=-1, le=64)
    # Rescue auto-sourced logos that are too small for the logo box by 2x/4x
    # super-resolution on the sidecar (/api/v1/upscale) before falling back to
    # the typeset text wordmark. Best-effort: any failure keeps old behaviour.
    ai_logo_upscale: bool = True
    # OpenAI prompt. OpenAI can remove text from this prompt ALONE (no mask);
    # a brushed mask, when present, restricts the edit to that region.
    ai_prompt: str = (
        "Remove all text, titles, credits, logos and watermarks from this image. "
        "Seamlessly reconstruct the underlying artwork and background where the "
        "text was. Do not change anything else."
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_sidecar_key(cls, data):
        """Move a pre-split sidecar secret out of the shared ``api_key``."""
        if not isinstance(data, dict):
            return data
        # No-ops once client_key is set, which the first save persists.
        if data.get("client_key") or data.get("ai_provider") != "lama_sidecar":
            return data
        legacy = (data.get("api_key") or "").strip()
        # Never an openai token left behind by an earlier provider choice.
        if legacy and not legacy.startswith("sk-"):
            data = dict(data)
            data["client_key"], data["api_key"] = legacy, ""
        return data

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_save_fields(cls, data):
        """Migrate the pre-redesign save fields to the two routed lists.

        Old shape: a mandatory ``output_dir``, a single ``upload_to_gdrive`` /
        ``gdrive_folder_id`` pair, and optional ``destinations`` rows where the
        FIRST destination claiming an image_type won (per-field fallback to the
        top-level dir/folder; upload was additive: global switch OR the matched
        destination's own flag).

        This rewrites that into ``local_folders`` / ``gdrive_uploads`` claims
        that route each type exactly where the old first-match logic sent it.
        Paths/folder-ids the old config carried but never routed anywhere (e.g.
        a folder id with uploads switched off) are kept as inert ``types: []``
        entries so nothing the user typed is lost.

        Runs on every validate (load and POST /api/config merge), so it must be
        idempotent: it no-ops as soon as either new list is present-and-truthy,
        and never resurrects entries the user has since deleted (a post-redesign
        save strips the legacy keys from disk — ``extra='ignore'`` drops them at
        validation, so they can't reappear).
        """
        if not isinstance(data, dict):
            return data
        if data.get("local_folders") or data.get("gdrive_uploads"):
            return data

        def _get(obj, key):
            val = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
            return val

        def _text(obj, key):
            return (_get(obj, key) or "").strip() if obj is not None else ""

        out_dir = (data.get("output_dir") or "").strip()
        folder_id = (data.get("gdrive_folder_id") or "").strip()
        upload_on = bool(data.get("upload_to_gdrive"))
        dests = data.get("destinations") or []
        if not (out_dir or folder_id or dests):
            return data

        def first_dest(image_type):
            for d in dests:
                if image_type in (_get(d, "image_types") or []):
                    return d
            return None

        def claim(entries, id_key, id_value, name, image_type):
            for entry in entries:
                if entry[id_key] == id_value:
                    if image_type and image_type not in entry["types"]:
                        entry["types"].append(image_type)
                    return
            entries.append(
                {
                    "name": name,
                    id_key: id_value,
                    "types": [image_type] if image_type else [],
                }
            )

        folders: List[dict] = []
        drives: List[dict] = []
        for image_type in CL2K_IMAGE_TYPES:
            dest = first_dest(image_type)
            dest_dir = _text(dest, "output_dir")
            dest_fid = _text(dest, "gdrive_folder_id")
            dest_name = _text(dest, "name")
            eff_dir = dest_dir or out_dir
            if eff_dir:
                claim(
                    folders,
                    "path",
                    eff_dir,
                    dest_name if dest_dir else "Output",
                    image_type,
                )
            upload_active = upload_on or bool(
                dest is not None and _get(dest, "upload_to_gdrive")
            )
            eff_fid = dest_fid or folder_id
            if upload_active and eff_fid:
                claim(
                    drives,
                    "folder_id",
                    eff_fid,
                    dest_name if dest_fid else "Drive",
                    image_type,
                )

        # Inert leftovers: keep every path / folder id the old config named, even
        # if the routing above never used it, so nothing silently disappears.
        if out_dir:
            claim(folders, "path", out_dir, "Output", None)
        if folder_id:
            claim(drives, "folder_id", folder_id, "Drive", None)
        for d in dests:
            if _text(d, "output_dir"):
                claim(folders, "path", _text(d, "output_dir"), _text(d, "name"), None)
            if _text(d, "gdrive_folder_id"):
                claim(
                    drives,
                    "folder_id",
                    _text(d, "gdrive_folder_id"),
                    _text(d, "name"),
                    None,
                )

        data = dict(data)
        data["local_folders"] = folders
        data["gdrive_uploads"] = drives
        return data
