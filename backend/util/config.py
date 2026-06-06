import logging
import os
import pathlib
import sys
import tempfile
from typing import Any, Dict, List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

# Migrator + loader status messages go through this stdlib logger so callers
# can attach a handler that routes them into their own logging system. The
# default config of stdlib logging means these also print at WARNING+ unless
# a handler is installed.
_config_log = logging.getLogger("chub.config")

# ==== SECTION: MODELS FOR CONFIG STRUCTURE ====


class GDriveListEntry(BaseModel):
    id: Optional[str] = ""
    location: Optional[str] = ""
    name: Optional[str] = ""


class SyncGDriveToken(BaseModel):
    access_token: Optional[str] = ""
    token_type: Optional[str] = ""
    refresh_token: Optional[str] = ""
    expiry: Optional[str] = ""


class SyncGDriveConfig(BaseModel):
    log_level: str = "info"
    dry_run: bool = False
    verbose: bool = False
    client_id: str = ""
    client_secret: str = ""
    token: Union[str, SyncGDriveToken, None] = ""
    gdrive_sa_location: Optional[str] = Field(default=None)
    gdrive_list: List[GDriveListEntry] = Field(default_factory=list)


class InstanceDetail(BaseModel):
    url: Optional[str] = ""
    api: Optional[str] = ""
    enabled: bool = True
    # When True, webhook-triggered uploads from this instance bypass the
    # SHA-256 hash dedup in PosterUploader so an unchanged-on-disk poster
    # is still re-pushed to Plex. Useful when Plex itself has been wiped
    # or when the user is actively re-curating a particular library.
    # Only meaningful for radarr / sonarr / lidarr (the instances that
    # fire webhooks); harmless on plex entries.
    webhook_force_reupload: bool = False


class InstancesConfig(BaseModel):
    radarr: Dict[str, InstanceDetail] = Field(default_factory=dict)
    sonarr: Dict[str, InstanceDetail] = Field(default_factory=dict)
    lidarr: Dict[str, InstanceDetail] = Field(default_factory=dict)
    plex: Dict[str, InstanceDetail] = Field(default_factory=dict)


class PosterRenamerrPlexInstance(BaseModel):
    library_names: List[str] = Field(default_factory=list)
    add_posters: Optional[bool] = False


class PosterRenamerrConfig(BaseModel):
    log_level: str = "info"
    dry_run: bool = False
    sync_posters: bool = False
    # Where matched posters go (strict either/or):
    #   "kometa" — rename/copy into destination_dir for Kometa to apply (the
    #     destination_dir / action_type / asset_folders fields apply here).
    #   "plex"   — upload posters straight to Plex via plexapi for instances
    #     whose per-instance add_posters opt-in is set; no destination_dir write.
    # Default "kometa" preserves the historical file-output behaviour on upgrade.
    apply_method: str = "kometa"
    action_type: str = "copy"
    asset_folders: bool = False
    print_only_renames: bool = False
    run_border_replacerr: bool = False
    # When True, the asset phase (logo / squareart / background / banner)
    # runs inline at the end of a poster_renamerr run, reusing the same gdrive
    # sync, the single image_type-aware source-dir scan, and the loaded
    # media/Plex snapshot — so no second sync/scan/fetch is incurred. See
    # AssetRenamerrConfig and backend/modules/asset_renamerr.py.
    run_asset_renamerr: bool = False
    clean_orphan_assets: bool = False
    report_unmatched_assets: bool = False
    # Optional delay (milliseconds) inserted after each poster uploaded to Plex,
    # to be gentle on the server on large runs. 0 = no delay (default; unchanged
    # behaviour). Only sleeps after an actual upload, never after a skip.
    upload_delay_ms: int = Field(default=0, ge=0, le=5000)
    source_dirs: List[str] = Field(default_factory=list)
    destination_dir: str = ""
    instances: List[Union[str, Dict[str, PosterRenamerrPlexInstance]]] = Field(
        default_factory=list
    )

    @field_validator("action_type", mode="before")
    @classmethod
    def _validate_action_type(cls, value: Any) -> Any:
        # Reject unknown actions loudly instead of silently doing nothing:
        # process_file() is an if/elif chain with no else, so an unrecognized
        # value (or wrong case) performed no file op yet reported success.
        if not isinstance(value, str):
            return value
        v = value.strip().lower()
        allowed = {"copy", "move", "hardlink", "symlink"}
        if v not in allowed:
            raise ValueError(
                f"action_type must be one of {sorted(allowed)}, got {value!r}"
            )
        return v

    @field_validator("apply_method", mode="before")
    @classmethod
    def _validate_apply_method(cls, value: Any) -> Any:
        # Strict either/or: "plex" (direct upload) or "kometa" (destination_dir).
        # Accept legacy "direct" as an alias for "plex" so older asset-style
        # values don't break a poster config.
        if not isinstance(value, str):
            return value
        v = value.strip().lower()
        if v == "direct":
            v = "plex"
        allowed = {"plex", "kometa"}
        if v not in allowed:
            raise ValueError(
                f"apply_method must be one of {sorted(allowed)}, got {value!r}"
            )
        return v


class AssetRenamerrPlexInstance(BaseModel):
    library_names: List[str] = Field(default_factory=list)
    # Per-instance opt-in for the "plex" apply path: only Plex instances with
    # add_posters=True receive direct uploads (mirrors PosterRenamerrPlexInstance).
    add_posters: Optional[bool] = False


class AssetRenamerrConfig(BaseModel):
    """Additional-asset support: logo, square art, background, banner.

    Mirrors poster_renamerr's scan/match flow but for non-poster image types.
    Images can come from two SOURCES and be applied two WAYS:

      sources (ORDERED — first match wins, encodes priority):
        - "local": files scanned from source_dirs, named like
          "Title (Year) {tmdb-N} - Logo.png" (the same convention as posters
          plus a " - Logo"/" - SquareArt"/" - Background"/" - Banner" suffix).
          source_dirs keep poster_renamerr's bottom-wins ordering within local.
        - "fanart": images fetched from fanart.tv (curated logos +
          backgrounds, ranked by community likes). Requires the user's
          personal fanart.tv key (fanart.client_key); the project key is
          embedded. Supplies logo + background only (no square art).

    Supported types per apply method (see backend/modules/asset_renamerr.py):
      apply_method ("plex" | "kometa"; legacy "direct" is an alias for "plex"):
        - "plex": upload straight to Plex via plexapi, for instances whose
          per-instance add_posters opt-in is set. Supports logo (uploadLogo),
          background (uploadArt), squareart (uploadSquareArt). plexapi has NO
          banner endpoint.
        - "kometa": rename/copy the file into destination_dir using Kometa's
          asset names for Kometa to apply. Per Kometa, asset directories read
          only logo (logo.ext) and background (background.ext) — NOT squareart
          or banner.

    Net capability matrix:
        logo       → plex ✓ / kometa ✓
        background → plex ✓ / kometa ✓
        squareart  → plex ✓ / kometa ✗ (Kometa ignores square art)

    (Banner is intentionally unsupported: Plex has no banner upload API and
    Kometa does not read banners from asset directories — there is no path.)

    An unsupported (type, apply_method) combination — squareart on the kometa
    path — is NOT a validation error (config must stay loadable while the user
    toggles apply_method); it is skipped with a warning during the run. Defaults
    to the two universally supported types so users who don't tune this never
    hit a no-op.
    """

    log_level: str = "info"
    dry_run: bool = False
    # Ordered source preference; first source yielding an image wins.
    sources: List[str] = Field(default_factory=lambda: ["local", "fanart"])
    # Which non-poster asset types to process. Defaults to the two types that
    # work on BOTH apply methods. squareart (direct only) can be added
    # explicitly. Valid values: "logo", "background", "squareart".
    asset_types: List[str] = Field(default_factory=lambda: ["logo", "background"])
    apply_method: str = "kometa"  # "plex" | "kometa" (legacy "direct" → "plex")
    action_type: str = "copy"  # copy | move | hardlink | symlink (kometa path)
    asset_folders: bool = False  # per-title folders (kometa path)
    destination_dir: str = ""  # kometa path
    source_dirs: List[str] = Field(default_factory=list)  # local source
    print_only_renames: bool = False
    sync_assets: bool = False  # run sync_gdrive first (standalone path)
    # Preferred languages for TMDB image selection, in priority order; the first
    # matching language wins (language-neutral / textless art is always allowed
    # as a fallback). A legacy single string (e.g. "en") is coerced to ["en"].
    tmdb_language: List[str] = Field(default_factory=lambda: ["en"])
    instances: List[Union[str, Dict[str, AssetRenamerrPlexInstance]]] = Field(
        default_factory=list
    )

    @field_validator("apply_method", mode="before")
    @classmethod
    def _validate_apply_method(cls, value: Any) -> Any:
        # "plex" uploads via plexapi; "kometa" writes files to destination_dir.
        # Legacy configs used "direct" for the Plex path — accept it as an alias
        # so they keep loading after the rename. Reject anything else loudly.
        if not isinstance(value, str):
            return value
        v = value.strip().lower()
        if v == "direct":
            v = "plex"
        allowed = {"plex", "kometa"}
        if v not in allowed:
            raise ValueError(
                f"apply_method must be one of {sorted(allowed)}, got {value!r}"
            )
        return v

    @field_validator("action_type", mode="before")
    @classmethod
    def _validate_action_type(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        v = value.strip().lower()
        allowed = {"copy", "move", "hardlink", "symlink"}
        if v not in allowed:
            raise ValueError(
                f"action_type must be one of {sorted(allowed)}, got {value!r}"
            )
        return v

    @field_validator("tmdb_language", mode="before")
    @classmethod
    def _coerce_tmdb_language(cls, value: Any) -> Any:
        # Accept a legacy single string ("en") or a comma-separated string and
        # normalise to an ordered list of lowercased 2-letter codes. Empty/blank
        # input falls back to ["en"] so image selection always has a preference.
        if value is None:
            return ["en"]
        if isinstance(value, str):
            parts = [p.strip().lower() for p in value.split(",")]
            value = [p for p in parts if p]
        elif isinstance(value, list):
            value = [str(p).strip().lower() for p in value if str(p).strip()]
        else:
            return value
        return value or ["en"]

    @field_validator("sources", mode="before")
    @classmethod
    def _migrate_sources(cls, value: Any) -> Any:
        # Logos/backgrounds now come from fanart.tv (curated + likes-ranked),
        # not TMDB. Migrate any legacy "tmdb" source to "fanart" so existing
        # configs keep working, drop unknown values, de-dupe (preserving order),
        # and fall back to the default when nothing valid remains.
        if not isinstance(value, list):
            return value
        out: List[str] = []
        for item in value:
            s = str(item).strip().lower()
            if s == "tmdb":
                s = "fanart"
            if s in ("local", "fanart") and s not in out:
                out.append(s)
        return out or ["local", "fanart"]


class BorderHoliday(BaseModel):
    name: str
    schedule: str
    colors: List[str] = Field(default_factory=list)
    borders: List[str] = Field(default_factory=list)


class BorderReplacerrConfig(BaseModel):
    log_level: str = "info"
    dry_run: bool = False
    source_dirs: List[str] = Field(default_factory=list)
    destination_dir: str = ""
    # Bounded so a misconfigured huge value can't invert the crop box
    # (border >= half the poster dimension), which silently turned every
    # poster into a no-op reported as success. 200px is far above any real
    # border and stays valid on normalized poster dimensions.
    border_width: int = Field(default=26, ge=0, le=200)
    skip: bool = False
    exclusion_list: Optional[List[str]] = None
    ignore_folders: List[str] = Field(default_factory=list)
    border_colors: List[str] = Field(default_factory=list)
    holidays: List[BorderHoliday] = Field(default_factory=list)


class Cl2kMakerConfig(BaseModel):
    log_level: str = "info"
    enabled: bool = False
    # Local source_dir where generated CL2K posters land (then matched by
    # poster_renamerr). Should be one of poster_renamerr.source_dirs.
    output_dir: str = ""
    language: str = "en"
    logo_max_width: int = Field(default=600, ge=100, le=800)  # guide 600 std / 800 max
    whiten_logo: bool = True
    text_logo_fallback: bool = True  # synth a typeset wordmark when no real logo
    skip_existing: bool = True
    style: str = "CL2K"  # poster_cache style tag
    priority: int = 0
    # Google Drive upload (rclone copy) — optional, off by default.
    upload_to_gdrive: bool = False
    gdrive_folder_id: str = ""
    gdrive_sa_location: str = ""
    # AI text removal (provider-agnostic; off by default = textless-art strategy).
    # Requires a user-brushed mask. lama_sidecar = free/local; openai = paid;
    # huggingface = free tier (rate-limited). Firefly/ChatGPT-free have no usable
    # API — use the manual export/import handoff for those.
    ai_provider: str = "none"  # none | lama_sidecar | openai | huggingface
    ai_endpoint: str = ""  # lama sidecar URL, or HF model inference URL
    ai_api_key: str = ""  # openai / huggingface token
    ai_model: str = ""  # openai model id (default gpt-image-1) / HF model id
    ai_timeout: int = 120
    # OpenAI/HF prompt. OpenAI can remove text from this prompt ALONE (no mask);
    # a brushed mask, when present, restricts the edit to that region.
    ai_prompt: str = (
        "Remove all text, titles, credits, logos and watermarks from this image. "
        "Seamlessly reconstruct the underlying artwork and background where the "
        "text was. Do not change anything else."
    )


class UpgradinatorrInstance(BaseModel):
    label: str = ""
    enabled: bool = True
    schedule: str = ""
    instance: str = ""
    count: int = 0
    tag_name: str = ""
    ignore_tag: str = ""
    unattended: bool = False
    season_monitored_threshold: Optional[float] = None
    search_mode: str = "upgrade"  # "upgrade" | "missing" | "cutoff"
    count_mode: str = "series_artist"  # "series_artist" | "season_album"


class UpgradinatorrConfig(BaseModel):
    log_level: str = "info"
    dry_run: bool = False
    instances_list: List[UpgradinatorrInstance] = Field(default_factory=list)


class RenameinatorrConfig(BaseModel):
    log_level: str = "info"
    dry_run: bool = False
    rename_folders: bool = True
    refresh_before_rename: bool = False
    count: Union[int, str] = 100
    radarr_count: int = 0
    sonarr_count: int = 0
    tag_name: str = ""
    ignore_tags: str = ""
    enable_batching: bool = False
    instances: List[str] = Field(default_factory=list)

    @field_validator("count", mode="before")
    @classmethod
    def _coerce_count(cls, value: Any) -> Any:
        # The str arm of count exists to allow an empty string meaning "all".
        # A numeric string ("50") would otherwise survive validation and then
        # crash the run at range(0, n, "50"). Coerce numeric strings to int,
        # keep "" as the "all" sentinel, and reject anything else.
        if value is None:
            return 100
        if isinstance(value, str):
            s = value.strip()
            if s == "":
                return ""
            try:
                return int(s)
            except ValueError:
                raise ValueError(
                    f"count must be an integer or an empty string (= all), "
                    f"got {value!r}"
                )
        return value


class NohlSourceDir(BaseModel):
    path: str
    mode: str = "resolve"


class NohlConfig(BaseModel):
    log_level: str = "info"
    dry_run: bool = False
    searches: int = 10
    print_files: bool = False
    source_dirs: List[Union[str, NohlSourceDir]] = Field(default_factory=list)
    exclude_profiles: List[str] = Field(default_factory=list)
    exclude_movies: List[str] = Field(default_factory=list)
    exclude_series: List[str] = Field(default_factory=list)
    instances: List[str] = Field(default_factory=list)


class LabelarrPlexInstance(BaseModel):
    instance: str = ""
    library_names: List[str] = Field(default_factory=list)


class LabelarrMapping(BaseModel):
    app_instance: str = ""
    labels: Union[List[str], str] = Field(default_factory=list)
    plex_instances: List[LabelarrPlexInstance] = Field(default_factory=list)


class LabelarrConfig(BaseModel):
    log_level: str = "info"
    dry_run: bool = False
    mappings: List[LabelarrMapping] = Field(default_factory=list)


class HealthCheckarrConfig(BaseModel):
    log_level: str = "info"
    dry_run: bool = False
    instances: Optional[List[str]] = None


class JduparrConfig(BaseModel):
    log_level: str = "info"
    dry_run: bool = False
    hash_database: Optional[str] = Field(
        default=None,
        description="Optional jdupes hash database file path.",
    )
    source_dirs: List[str] = Field(
        default_factory=list,
        description="Directories to scan together for duplicate media files.",
    )


class NestarrPlexInstance(BaseModel):
    instance: str = ""
    library_names: List[str] = Field(default_factory=list)


class NestarrMapping(BaseModel):
    arr_instance: str = ""
    plex_instances: List[NestarrPlexInstance] = Field(default_factory=list)


class NestarrConfig(BaseModel):
    log_level: str = "info"
    library_mappings: List[NestarrMapping] = Field(default_factory=list)
    path_mapping: Optional[List[Dict[str, str]]] = None
    instances: Optional[List[str]] = None  # Deprecated: kept for backward compat

    @model_validator(mode="after")
    def normalize_mappings(self):
        valid_mappings: List[NestarrMapping] = []
        for mapping in self.library_mappings or []:
            arr_instance = (mapping.arr_instance or "").strip()
            if not arr_instance:
                continue

            valid_plex_instances: List[NestarrPlexInstance] = []
            for plex_instance in mapping.plex_instances or []:
                instance_name = (plex_instance.instance or "").strip()
                library_names = [
                    name.strip()
                    for name in plex_instance.library_names or []
                    if isinstance(name, str) and name.strip()
                ]
                if instance_name and library_names:
                    plex_instance.instance = instance_name
                    plex_instance.library_names = library_names
                    valid_plex_instances.append(plex_instance)

            if valid_plex_instances:
                mapping.arr_instance = arr_instance
                mapping.plex_instances = valid_plex_instances
                valid_mappings.append(mapping)

        self.library_mappings = valid_mappings

        if self.path_mapping is not None:
            self.path_mapping = [
                {
                    "arr_path": entry["arr_path"].strip(),
                    "local_path": entry["local_path"].strip(),
                }
                for entry in self.path_mapping
                if isinstance(entry, dict)
                and isinstance(entry.get("arr_path"), str)
                and isinstance(entry.get("local_path"), str)
                and entry["arr_path"].strip()
                and entry["local_path"].strip()
            ]
        return self


class AuthConfig(BaseModel):
    username: str = ""
    password_hash: str = ""
    jwt_secret: str = ""
    token_expiry_hours: int = 24


class UserInterfaceConfig(BaseModel):
    theme: str = "dark"


class GeneralConfig(BaseModel):
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"
    # Deprecated config key kept for existing config.yml compatibility. The
    # frontend no longer exposes it because update checks are not wired at
    # runtime.
    update_notifications: bool = False
    max_logs: int = Field(default=9, ge=1, le=100)
    # Plex's recently-added scan can lag 5+ minutes behind a Sonarr/Radarr
    # import under load. Defaults give ~5.5 min of total search:
    #   30s warmup + 10 attempts × 30s = 330s
    webhook_initial_delay: int = Field(default=30, ge=0, le=3600)
    webhook_retry_delay: int = Field(default=30, ge=1, le=3600)
    webhook_max_retries: int = Field(default=10, ge=0, le=100)
    webhook_secret: str = ""
    duplicate_exclude_groups: List[Any] = Field(default_factory=list)
    # TTL (seconds) for reusing the plex_media_cache snapshot before a re-walk.
    # The "plex" apply path resolves artwork targets from this cache; when it
    # was refreshed within this window, chained/back-to-back runs skip a
    # redundant full Plex walk. 0 = always refresh. Default 5 minutes.
    plex_cache_ttl_seconds: int = Field(default=300, ge=0, le=86400)

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.lower()
        return value


class PosterCleanarrConfig(BaseModel):
    log_level: str = "info"
    mode: str = "report"
    plex_path: str = ""
    local_db: bool = False
    use_existing_db: bool = False
    ignore_running: bool = False
    overlays_only: bool = False
    sleep: int = 60
    timeout: int = 600
    instances: List[str] = Field(default_factory=list)
    # Populated only by per-job overrides from the Poster Cleanarr UI when the
    # user selects specific tiles. None => full library. Never persisted.
    target_paths: Optional[List[str]] = None
    # Orphan-asset cleanup: walk `asset_dirs` and report/move/remove asset
    # files whose title doesn't appear in any configured instance's library
    # (the asset has no "parent" media). The comparison set is read from
    # media_cache + collection_cache (populated by poster_renamerr's instance
    # sync), so freshness inherits whatever the last renamerr run produced.
    orphan_assets_enabled: bool = False
    orphan_assets_mode: str = "report"  # report | move | remove
    asset_dirs: List[str] = Field(default_factory=list)
    # Radarr/Sonarr instances whose libraries form the orphan comparison set.
    # Kept separate from `instances` (which selects the Plex instance for the
    # bloat pass) so the two passes don't share an overloaded field. Falls back
    # to `instances` when empty, preserving pre-split configs that listed ARR
    # names alongside Plex in `instances`.
    orphan_instances: List[str] = Field(default_factory=list)
    include_collections: bool = True
    # Titles that are never flagged as orphans, regardless of whether they
    # match a library entry. Matched on the same normalized key as the scan.
    orphan_ignore_titles: List[str] = Field(default_factory=list)


class PlexMaintenanceConfig(BaseModel):
    """Plex server-level maintenance tasks (moved out of poster_cleanarr)."""

    log_level: str = "info"
    plex_path: str = ""
    empty_trash: bool = False
    clean_bundles: bool = False
    optimize_db: bool = False
    photo_transcoder: bool = False
    sleep: int = 60
    timeout: int = 600
    instances: List[str] = Field(default_factory=list)


class UnmatchedAssetsConfig(BaseModel):
    log_level: str = "info"
    ignore_folders: List[str] = Field(default_factory=list)
    ignore_profiles: List[str] = Field(default_factory=list)
    ignore_titles: List[str] = Field(default_factory=list)
    ignore_tags: List[str] = Field(default_factory=list)
    ignore_collections: List[str] = Field(default_factory=list)
    ignore_unmonitored: bool = False
    instances: List[str] = Field(default_factory=list)


class TMDBConfig(BaseModel):
    """TMDB integration. When apikey is set, Chub resolves missing tmdb_id
    values in media_cache by looking up tvdb_id/imdb_id via TMDB's /find
    endpoint. Resolved IDs improve poster matching, Plex GUID cross-joins,
    and the Unmatched Assets request links.

    Note: TMDB enforces ~50 req/s + per-day quotas, so the cache_expiration
    here is what protects you from re-querying the same IDs and burning rate
    budget on every sync. Default 60 days matches Kometa."""

    apikey: str = ""
    cache_expiration: int = Field(default=60, ge=1, le=3650)  # days

    # Match-quality refinement (TMDB id verification, AKA hydration, and fuzzy
    # near-miss flagging) is automatic whenever `apikey` is set — there's no
    # separate toggle. Installs without a key skip it entirely and the related
    # UI is hidden.


class FanartConfig(BaseModel):
    """fanart.tv integration — the source for logos + backgrounds in
    asset_renamerr (curated art, ranked by community likes).

    A fanart.tv PERSONAL key (client_key) authenticates on its own, so it is all
    Chub needs — and Chub requires it for the "fanart" source (without it the
    asset run falls back to local files). It also gives the faster tier, cutting
    the delay for newly-added artwork from 7 days to 2 (immediate for VIP).
    Get one free at https://fanart.tv/get-an-api-key/ (Personal API Keys).
    Chub does not use a fanart.tv project key.

    cache_expiration: resolved logo/background URLs are cached this many days
    across runs (fanart.tv asks apps to make no more requests than necessary).
    The default of 2 days matches the personal key's own 2-day propagation delay
    for newly-added art — so re-fetching more often can't surface anything newer
    anyway, making the cache effectively freshness-free.
    """

    client_key: str = ""
    cache_expiration: int = Field(default=2, ge=1, le=3650)  # days


# Notifications is a dict of module_name to dicts (arbitrary structure, so keep Any)
class ConfigNotifications(BaseModel):
    poster_renamerr: Optional[Dict[str, Any]] = Field(default_factory=dict)
    asset_renamerr: Optional[Dict[str, Any]] = Field(default_factory=dict)
    unmatched_assets: Optional[Dict[str, Any]] = Field(default_factory=dict)
    health_checkarr: Optional[Dict[str, Any]] = Field(default_factory=dict)
    labelarr: Optional[Dict[str, Any]] = Field(default_factory=dict)
    upgradinatorr: Optional[Dict[str, Any]] = Field(default_factory=dict)
    renameinatorr: Optional[Dict[str, Any]] = Field(default_factory=dict)
    nohl: Optional[Dict[str, Any]] = Field(default_factory=dict)
    jduparr: Optional[Dict[str, Any]] = Field(default_factory=dict)
    nestarr: Optional[Dict[str, Any]] = Field(default_factory=dict)
    poster_cleanarr: Optional[Dict[str, Any]] = Field(default_factory=dict)
    plex_maintenance: Optional[Dict[str, Any]] = Field(default_factory=dict)
    border_replacerr: Optional[Dict[str, Any]] = Field(default_factory=dict)
    cl2k_maker: Optional[Dict[str, Any]] = Field(default_factory=dict)
    sync_gdrive: Optional[Dict[str, Any]] = Field(default_factory=dict)
    main: Optional[Dict[str, Any]] = Field(default_factory=dict)


# ==== ROOT CONFIG MODEL ====


class ChubConfig(BaseModel):
    schedule: Dict[str, Any] = Field(default_factory=dict)
    instances: InstancesConfig = Field(default_factory=InstancesConfig)
    notifications: ConfigNotifications = Field(default_factory=ConfigNotifications)
    sync_gdrive: SyncGDriveConfig = Field(default_factory=SyncGDriveConfig)
    unmatched_assets: UnmatchedAssetsConfig = Field(
        default_factory=UnmatchedAssetsConfig
    )
    poster_renamerr: PosterRenamerrConfig = Field(default_factory=PosterRenamerrConfig)
    asset_renamerr: AssetRenamerrConfig = Field(default_factory=AssetRenamerrConfig)
    border_replacerr: BorderReplacerrConfig = Field(
        default_factory=BorderReplacerrConfig
    )
    cl2k_maker: Cl2kMakerConfig = Field(default_factory=Cl2kMakerConfig)
    upgradinatorr: UpgradinatorrConfig = Field(default_factory=UpgradinatorrConfig)
    renameinatorr: RenameinatorrConfig = Field(default_factory=RenameinatorrConfig)
    nohl: NohlConfig = Field(default_factory=NohlConfig)
    labelarr: LabelarrConfig = Field(default_factory=LabelarrConfig)
    health_checkarr: HealthCheckarrConfig = Field(default_factory=HealthCheckarrConfig)
    jduparr: JduparrConfig = Field(default_factory=JduparrConfig)
    nestarr: NestarrConfig = Field(default_factory=NestarrConfig)
    poster_cleanarr: PosterCleanarrConfig = Field(default_factory=PosterCleanarrConfig)
    plex_maintenance: PlexMaintenanceConfig = Field(
        default_factory=PlexMaintenanceConfig
    )
    user_interface: UserInterfaceConfig = Field(default_factory=UserInterfaceConfig)
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    tmdb: TMDBConfig = Field(default_factory=TMDBConfig)
    fanart: FanartConfig = Field(default_factory=FanartConfig)


# ==== SECRET REDACTION ====

SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api",
        "api_key",
        "apikey",
        "client_key",
        "access_token",
        "refresh_token",
        "client_secret",
        "token",
        "password_hash",
        "jwt_secret",
        "webhook_secret",
    }
)

REDACTED_PLACEHOLDER = "********"


def redact_secrets(data: Any, _parent_key: str = "") -> Any:
    """
    Recursively walk a config dict and replace sensitive field values
    with a redacted placeholder. Returns a new structure (does not mutate).
    """
    if isinstance(data, dict):
        return {
            k: (
                REDACTED_PLACEHOLDER
                if k in SENSITIVE_FIELD_NAMES and isinstance(v, str) and v
                else redact_secrets(v, _parent_key=k)
            )
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [redact_secrets(item, _parent_key=_parent_key) for item in data]
    return data


def strip_redacted_placeholders(incoming: dict, current: dict) -> dict:
    """
    Merge *incoming* config over *current*, but preserve current values
    wherever incoming still contains the redacted placeholder.
    Returns a new dict.
    """
    merged = {}
    for k, v in incoming.items():
        cur_v = current.get(k)
        if isinstance(v, dict) and isinstance(cur_v, dict):
            merged[k] = strip_redacted_placeholders(v, cur_v)
        elif v == REDACTED_PLACEHOLDER and isinstance(cur_v, str):
            merged[k] = cur_v  # keep the real secret
        else:
            merged[k] = v
    # include keys only present in current (not overwritten)
    for k, v in current.items():
        if k not in merged:
            merged[k] = v
    return merged


# ==== CONFIG EXCEPTIONS ====


class ConfigError(Exception):
    """Base class for configuration errors."""


class ConfigNotFoundError(ConfigError):
    """Raised when the config file does not exist."""


class ConfigParseError(ConfigError):
    """Raised when the config file contains invalid YAML."""


class ConfigValidationError(ConfigError):
    """Raised when config content fails Pydantic validation."""

    def __init__(
        self, message: str, validation_error: Optional[ValidationError] = None
    ):
        super().__init__(message)
        self.validation_error = validation_error


# ==== CONFIG LOADER ====


def get_config_path() -> str:
    """Get configuration file path from environment or default location."""
    config_dir = os.environ.get("CONFIG_DIR") or str(
        pathlib.Path(__file__).parent.parent.parent / "config"
    )
    config_file_path = os.path.join(config_dir, "config.yml")
    return config_file_path


def format_validation_errors(validation_error: ValidationError) -> List[str]:
    """Return one humanized "loc: msg" line per Pydantic field error.

    Used by both the CLI error printer and runtime loggers so the user sees
    the same per-field detail regardless of which path surfaced the failure.
    """
    lines: List[str] = []
    for error in validation_error.errors():
        location = " -> ".join(str(loc) for loc in error["loc"])
        msg = error["msg"]

        # Simplify common Pydantic phrasing for non-developer readers
        if "field required" in msg or "Field required" in msg:
            msg = "missing required field"
        elif "not a valid integer" in msg or "valid integer" in msg:
            msg = "must be a number"
        elif "not a valid boolean" in msg or "valid boolean" in msg:
            msg = "must be true or false"
        elif "not a valid string" in msg or "valid string" in msg:
            msg = "must be text"
        elif "invalid or missing URL scheme" in msg:
            msg = "must be a valid URL (http:// or https://)"

        input_value = error.get("input")
        if input_value is not None and not isinstance(input_value, (dict, list)):
            lines.append(f"{location}: {msg} (got: {input_value!r})")
        else:
            lines.append(f"{location}: {msg}")
    return lines


def _print_cli_validation_errors(validation_error: ValidationError) -> None:
    """Print simplified validation errors for CLI users."""
    print("❌ Configuration validation failed:")
    for line in format_validation_errors(validation_error):
        print(f"   • {line}")
    print("💡 Check your config.yml file and fix the issues above")


def load_config(path: Optional[str] = None) -> ChubConfig:
    """
    Load and validate configuration from YAML.

    If the file is detected as a legacy-format config (see
    config_migrator.is_legacy_config), the original is backed up alongside
    the live path as ``config.yml.legacy-<ISO-timestamp>.yml`` and the
    migrated YAML is written back to ``config.yml`` before validation.
    Migration notes are emitted to stdout so users see what changed.

    Raises ConfigError subclasses on failure so callers can handle
    errors appropriately (API returns HTTP errors, CLI prints and exits).
    """
    from backend.util.config_migrator import is_legacy_config

    config_path = path or get_config_path()

    if not os.path.exists(config_path):
        return ChubConfig()

    try:
        with open(config_path, "r") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigParseError(f"Invalid YAML syntax in {config_path}: {e}") from e
    except Exception as e:
        raise ConfigParseError(f"Failed to read {config_path}: {e}") from e

    if raw is None:
        raise ConfigParseError(f"Configuration file is empty: {config_path}")

    if is_legacy_config(raw):
        raw = _auto_migrate_and_persist(raw, config_path)

    try:
        return ChubConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigValidationError(
            f"Configuration validation failed in {config_path}",
            validation_error=e,
        ) from e
    except Exception as e:
        raise ConfigError(f"Unexpected configuration error: {e}") from e


def _auto_migrate_and_persist(raw: dict, config_path: str) -> dict:
    """Back up the original, migrate, write the migrated YAML back, log notes.

    Returns the migrated dict. If anything goes wrong writing files, the
    in-memory migration still takes effect so the load can proceed.

    Status messages go to both stdout (so they appear in container logs
    before the chub Logger exists) and the `chub.config` stdlib logger
    (so they appear in the chub log file once a handler is attached).
    """
    from datetime import datetime

    from backend.util.config_migrator import migrate

    migrated, notes = migrate(raw)
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_path = f"{config_path}.legacy-{timestamp}.yml"

    try:
        with open(backup_path, "w") as f:
            yaml.safe_dump(raw, f, sort_keys=False)
    except Exception as e:  # pragma: no cover - best-effort backup
        _emit(f"⚠️  Failed to write legacy backup {backup_path}: {e}", "warning")
        backup_path = "(backup write failed)"

    try:
        with open(config_path, "w") as f:
            yaml.safe_dump(migrated, f, sort_keys=False)
    except Exception as e:  # pragma: no cover - best-effort write
        _emit(
            f"⚠️  Failed to rewrite migrated config to {config_path}: {e}", "warning"
        )

    _emit(
        f"🔄 Legacy config detected at {config_path}. "
        f"Applying migration rules; validation will run next."
    )
    _emit(f"   Original preserved at {backup_path}")
    for note in notes:
        level = "warning" if note.level == "warning" else "info"
        icon = "⚠️ " if note.level == "warning" else "•"
        _emit(f"   {icon} {note.message}", level)
    _emit(
        "   ⚠️  Verify file/directory paths in this config "
        "(sync_gdrive.gdrive_sa_location, poster_renamerr.source_dirs, "
        "poster_cleanarr.asset_dirs, nohl.source_dirs, etc.) still resolve "
        "inside this container — your volume mounts may differ from the "
        "previous setup.",
        "warning",
    )

    return migrated


def _emit(message: str, level: str = "info") -> None:
    """Send a config-related status message to both stdout and `chub.config`.

    Stdout keeps the message visible at very early startup (before any
    chub Logger exists). The stdlib logger lets a handler installed by
    the main app route the same message into the chub log file.
    """
    print(message)
    if level == "warning":
        _config_log.warning(message)
    elif level == "error":
        _config_log.error(message)
    else:
        _config_log.info(message)


def load_config_cli(path: Optional[str] = None) -> ChubConfig:
    """
    CLI wrapper around load_config that prints friendly errors and exits.
    Use this in CLI entry points; use load_config() in API handlers.
    """
    try:
        return load_config(path)
    except ConfigNotFoundError as e:
        print(f"\u274c {e}")
        print("\U0001f4a1 Create a config.yml file in the config directory")
        sys.exit(1)
    except ConfigParseError as e:
        print(f"\u274c {e}")
        print("\U0001f4a1 Check your YAML formatting")
        sys.exit(1)
    except ConfigValidationError as e:
        if e.validation_error:
            _print_cli_validation_errors(e.validation_error)
        else:
            print(f"\u274c {e}")
        sys.exit(1)
    except ConfigError as e:
        print(f"\u274c {e}")
        sys.exit(1)


def save_config(config: ChubConfig, path: Optional[str] = None) -> None:
    """Save configuration to YAML file atomically (write tmp + rename)."""
    config_path = path or get_config_path()
    config_dir = os.path.dirname(config_path)
    try:
        os.makedirs(config_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(suffix=".yml.tmp", dir=config_dir)
        try:
            with os.fdopen(fd, "w") as f:
                yaml.safe_dump(config.model_dump(mode="python"), f, sort_keys=False)
            os.replace(tmp_path, config_path)
        except BaseException:
            # Clean up temp file on any failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # Best-effort cleanup; re-raise original error
            raise
    except Exception as e:
        raise ConfigError(f"Failed to save configuration: {e}") from e
