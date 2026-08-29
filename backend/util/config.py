import logging
import os
import pathlib
import sys
import tempfile
import threading
from typing import Any, Dict, List, Literal, Optional, Union

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    create_model,
    field_validator,
    model_validator,
)

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
    # When True this drive is "browse only": its posters are indexed for Assets
    # Search but excluded from poster matching. Default False — drives are folded
    # into poster_renamerr's scan set automatically (see _scan_source_dirs). This
    # only flips an existing drive's behaviour if its location was NOT already a
    # source_dir, so old / DAPS-migrated configs (which list match dirs in
    # source_dirs) are unaffected.
    search_only: bool = False


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
    # Remove a departed drive's local folder when it holds no files; a
    # populated one is reported instead (it may still feed poster matching).
    prune_orphan_drives: bool = True


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
    # Instance-level Plex library opt-in ("allow-list"). Only meaningful for
    # plex entries; ignored on arr instances. Tri-state:
    #   None  — legacy / never configured. Treated as ALL libraries, then lazily
    #           SEEDED with the server's current libraries on the first sync (see
    #           seed_plex_enabled_libraries) so libraries ADDED to Plex later stay
    #           hidden until explicitly opted in.
    #   []    — opted out: nothing from this server is synced, cached, counted, or
    #           shown anywhere CHUB *manages* content.
    #   [...] — exactly these libraries are enabled.
    # Whole-server maintenance modules (plex_maintenance, poster_cleanarr) ignore
    # this by design and always operate on the entire Plex server.
    enabled_libraries: Optional[List[str]] = None


class InstancesConfig(BaseModel):
    radarr: Dict[str, InstanceDetail] = Field(default_factory=dict)
    sonarr: Dict[str, InstanceDetail] = Field(default_factory=dict)
    lidarr: Dict[str, InstanceDetail] = Field(default_factory=dict)
    plex: Dict[str, InstanceDetail] = Field(default_factory=dict)
    # How often CHUB reconciles its media cache from these instances (the
    # background media_sync job — steps through instances sequentially). A
    # safety-net behind real-time webhooks, so daily is plenty; "" disables it.
    # Set from the Instances page dropdown. Cron form so the scheduler's
    # per-name next-run guard prevents double-firing within the trigger minute.
    sync_schedule: str = "cron(0 4 * * *)"


class PlexScope(BaseModel):
    """A module's opt-in selection of a Plex instance + libraries.

    `library_names` empty == all libraries (only meaningful when collections
    are matched). `add_posters` and `match_collections` are honored only by
    uploader modules (poster_renamerr / asset_renamerr); unmatched_assets
    ignores both — it always reports collections for a selected instance.
    """

    instance: str
    library_names: List[str] = Field(default_factory=list)
    add_posters: bool = False
    match_collections: bool = False


def _split_legacy_instances(value: Any) -> Any:
    """Coerce the legacy `instances: List[Union[str, Dict]]` shape into the
    split {instances, plex_scope} shape, in a Pydantic `before` validator.

    Shape-based (no registry needed): string entries -> ARR `instances`;
    dict entries `{name: {library_names, add_posters}}` -> `plex_scope`.
    `match_collections` is derived from whether libraries were listed
    (non-empty old libraries == collections were matched). Idempotent: a
    payload already in the new shape (instances all strings) is returned
    unchanged.
    """
    if not isinstance(value, dict):
        return value
    instances = value.get("instances")
    if not isinstance(instances, list):
        return value
    if all(isinstance(i, str) for i in instances):
        return value

    arr: List[str] = []
    scopes: List[dict] = list(value.get("plex_scope") or [])
    for item in instances:
        if isinstance(item, str):
            arr.append(item)
        elif isinstance(item, dict) and item:
            name = next(iter(item))
            body = item[name] if isinstance(item[name], dict) else {}
            libs = body.get("library_names") or []
            scopes.append(
                {
                    "instance": name,
                    "library_names": libs,
                    "add_posters": bool(body.get("add_posters", False)),
                    "match_collections": bool(libs),
                }
            )
    new = dict(value)
    new["instances"] = arr
    new["plex_scope"] = scopes
    return new


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
    # Plex apply path only: skip re-staging (copy + border + upload) a poster
    # whose SOURCE is unchanged since it was last successfully uploaded, instead
    # of re-copying every poster into the temp staging dir on every run. Makes a
    # scheduled run a near no-op for a stable library. Caveat: because the skip
    # keys on the source file, adding a new Plex library or changing border
    # settings won't re-apply to unchanged posters until their source changes —
    # run once with this off (or a forced run) to backfill in that case.
    skip_unchanged_uploads: bool = True
    source_dirs: List[str] = Field(default_factory=list)
    # Source dirs whose contents are custom MUSIC art (artist posters / album
    # covers). Files here are classified as artist/album by folder depth
    # (<dir>/<Artist>/poster|artist.jpg, <dir>/<Artist>/<Album>/cover.jpg) or by
    # a flat "Artist.jpg" / "Artist - Album.jpg" name; an {mbid-<uuid>} tag in
    # the filename/folder overrides identity. (An {mbid-} tag is also honored in
    # the regular source_dirs.) Kept separate so a flat "Title.jpg" is never
    # mistaken for a movie poster.
    music_source_dirs: List[str] = Field(default_factory=list)
    destination_dir: str = ""
    instances: List[str] = Field(default_factory=list)
    plex_scope: List[PlexScope] = Field(default_factory=list)

    # --- Music (Lidarr) artwork options ---
    # Only meaningful when a Lidarr instance is configured; the frontend gates
    # them on that. All are image-only / Plex-metadata operations — none ever
    # touches audio, so seeded music torrents are never endangered.
    #
    # After a Plex-direct artist poster upload, lock thumb/art so Plex's music
    # agent can't re-derive the artist image from album art on refresh.
    # Artist-only; album covers are sticky and never need it.
    music_lock_artist_art: bool = False
    # Also write image-only sidecars (cover.jpg for albums, artist-poster.jpg /
    # background.jpg for artists) into the Plex music library folders for
    # refresh-proof art. Writes image files only; never audio.
    music_lma_sidecars: bool = False

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
    # Music art source dirs (artist backgrounds/logos), classified by folder
    # depth / flat name / {mbid-} tag — see PosterRenamerrConfig.music_source_dirs.
    music_source_dirs: List[str] = Field(default_factory=list)
    print_only_renames: bool = False
    sync_assets: bool = False  # run sync_gdrive first (standalone path)
    # Preferred languages for TMDB image selection, in priority order; the first
    # matching language wins (language-neutral / textless art is always allowed
    # as a fallback). A legacy single string (e.g. "en") is coerced to ["en"].
    tmdb_language: List[str] = Field(default_factory=lambda: ["en"])
    instances: List[str] = Field(default_factory=list)
    plex_scope: List[PlexScope] = Field(default_factory=list)

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
    exclusion_list: Optional[List[str]] = None
    ignore_folders: List[str] = Field(default_factory=list)
    border_colors: List[str] = Field(default_factory=list)
    holidays: List[BorderHoliday] = Field(default_factory=list)
    # Thread pool size for the border re-encode pass; None = min(8, cpu count).
    # Without this field pydantic drops the key from config.yml before the
    # module's getattr ever sees it.
    border_workers: Optional[int] = Field(default=None, ge=1)


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
    # Hours an unresolved queue row suppresses re-searching its item. 0 = never
    # suppress. Past the cap a forgotten row stops blocking the item forever.
    queue_block_hours: int = 72


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
    # When False the mapping is configured but skipped on each run — lets a
    # user pause a mapping without deleting it. Defaults True for back-compat
    # with existing configs that have no `enabled` key.
    enabled: bool = True

    @field_validator("labels", mode="before")
    @classmethod
    def _coerce_labels(cls, value: Any) -> List[str]:
        """Normalise labels to a list so the UI always edits them as chips.

        Accepts a legacy comma-separated string ("4k,remux") or a plain single
        label and splits it; an existing list is cleaned of blanks. Old configs
        keep loading unchanged while new saves round-trip a list.
        """
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [p.strip() for p in value.split(",") if p.strip()]
        if isinstance(value, list):
            return [str(p).strip() for p in value if str(p).strip()]
        return []


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
    # Delete rotated log files older than this many days (0 = disabled; rely on
    # count-based rotation via max_logs only). Pruned by the daily maintenance
    # thread.
    log_retention_days: int = Field(default=0, ge=0, le=365)
    # When true, the maintenance thread writes a config+db backup once a day and
    # prunes the backups directory to the newest `auto_backup_keep` archives.
    auto_backup: bool = False
    auto_backup_keep: int = Field(default=12, ge=1, le=100)
    # Empty = CONFIG_DIR/backups, the same volume as the data it protects —
    # prefer an external one. Resolved by backend/api/system.py::_get_backup_dir.
    backup_dir: str = ""
    # Modules the user has hard-disabled on the Modules page. A disabled module
    # is skipped by the scheduler AND blocked from manual / webhook runs. Names
    # are the module keys in backend.modules.MODULES (e.g. "poster_renamerr").
    disabled_modules: List[str] = Field(default_factory=list)
    # Plex's recently-added scan can lag 5+ minutes behind a Sonarr/Radarr
    # import under load. Defaults give ~5.5 min of total search:
    #   30s warmup + 10 attempts × 30s = 330s
    webhook_initial_delay: int = Field(default=30, ge=0, le=3600)
    webhook_retry_delay: int = Field(default=30, ge=1, le=3600)
    webhook_max_retries: int = Field(default=10, ge=0, le=100)
    webhook_secret: str = ""
    # CHUB's own base URL as reachable *from an *arr container* (e.g.
    # "http://192.168.1.10:8060" or "https://chub.example.com"). Used only when
    # auto-provisioning the poster webhook into Radarr/Sonarr: it's the address
    # CHUB writes into each arr's Connect entry, so it must be what the arr can
    # reach — NOT necessarily the browser origin (a reverse-proxy hostname or a
    # different docker network can differ). Empty = fall back to the base_url the
    # provisioning request supplies. Not a secret (never redacted).
    public_url: str = ""
    # Reverse-proxy trust for inbound webhooks. When CHUB sits behind a proxy
    # (Traefik/nginx/Caddy), the connection's peer IP is the proxy's, not the
    # arr's, which defeats peer-IP instance matching. If the immediate peer
    # matches an entry here, CHUB honors `X-Forwarded-For` and uses the
    # forwarded client IP to identify the sending instance. Entries are IPs or
    # CIDRs (e.g. "10.0.0.0/8", "192.168.1.5"); the token "private" trusts any
    # RFC1918 / loopback / link-local peer (the default — covers homelab Docker
    # proxies while ignoring forged XFF from public callers). Empty = never
    # trust XFF (peer IP only).
    trusted_proxies: List[str] = Field(default_factory=lambda: ["private"])
    duplicate_exclude_groups: List[Any] = Field(default_factory=list)
    # TTL (seconds) for reusing the plex_media_cache snapshot before a re-walk.
    # The "plex" apply path resolves artwork targets from this cache; when it
    # was refreshed within this window, chained/back-to-back runs skip a
    # redundant full Plex walk. 0 = always refresh. Default 5 minutes.
    plex_cache_ttl_seconds: int = Field(default=300, ge=0, le=86400)
    # Module keys (see backend.modules.MODULES) to show on the dashboard, in
    # the given order. Empty = show all modules. Drives only which cards the
    # dashboard renders; does not affect scheduling or execution.
    dashboard_modules: List[str] = Field(default_factory=list)
    # Dashboard section keys (health, modules, scheduler, quick_start) to show,
    # in the given order. Empty = show all in the default order.
    dashboard_sections: List[str] = Field(default_factory=list)
    # How often (seconds) the dashboard re-polls when live SSE updates are not
    # connected, and how often its countdowns tick. 0 = no auto-refresh.
    dashboard_refresh_seconds: int = Field(default=30, ge=0, le=3600)
    # How many upcoming scheduled runs the dashboard Scheduler panel lists.
    dashboard_upcoming_limit: int = Field(default=5, ge=1, le=50)
    # First-run setup wizard gate. False routes the UI into the wizard; set True
    # once it completes. For pre-existing installs the key is absent from
    # config.yml, so load_config backfills it True when the config already shows
    # use (see _backfill_setup_completed) — only a genuinely fresh install stays
    # False and sees the wizard.
    setup_completed: bool = False

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
    # Stale-duplicate cleanup: a Kometa asset folder whose {tvdb/tmdb} id
    # matches a live item but whose name != the item's canonical folder.
    stale_duplicates_enabled: bool = False
    stale_duplicates_mode: str = "report"  # report | move | remove
    # Plex libraries (by name, matched case-insensitively) to EXCLUDE from the
    # bloat pass — their custom images are neither shown in the by-media view
    # nor treated as deletion candidates. Deny-list ONLY: the in-use hash set
    # stays global (get_in_use_hashes is never library-scoped), so an excluded
    # library's LIVE artwork can never be misread as bloat. Empty (the default)
    # = every library is in scope, exactly as before. A bloat file whose bundle
    # can't be resolved to a library fails OPEN (treated as not-excluded), so
    # this can only ever REDUCE what gets deleted, never widen it. Does NOT
    # affect the orphan/stale passes (they key on Kometa asset dirs, not Plex
    # libraries).
    excluded_libraries: List[str] = Field(default_factory=list)


class PlexMaintenanceConfig(BaseModel):
    """Plex server-level maintenance tasks (moved out of poster_cleanarr)."""

    log_level: str = "info"
    dry_run: bool = False
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
    plex_scope: List[PlexScope] = Field(default_factory=list)


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
# extra="allow" keeps notification sections owned by self-registering
# extensions (backend/extensions) — unknown module keys round-trip instead of
# being dropped on parse.
class NotificationEvents(BaseModel):
    """Which run outcomes a destination reports on. `success` = run-completion
    summaries (fired by the per-module dispatch calls); `failure` = error alerts
    (fired by the global ERROR-log handler)."""

    success: bool = True
    failure: bool = False


# Sentinel stored in a destination's `modules` list meaning "every module".
ALL_MODULES_SENTINEL = "__ALL__"


class NotificationDestination(BaseModel):
    """One outbound notification channel. A single Discord webhook / Notifiarr
    alert fans out to every module listed in `modules` (or all of them via the
    `__ALL__` sentinel), reporting on the outcomes enabled in `events`.

    `config` holds the method-specific credentials (Discord: webhook/bot_name/
    color; Notifiarr: webhook/channel_id/color) — same leaf shape as the old
    per-module structure, so `redact_secrets` still masks `webhook` by name."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    method: str = "discord"  # "discord" | "notifiarr"
    name: str = ""
    enabled: bool = True
    events: NotificationEvents = Field(default_factory=NotificationEvents)
    modules: List[str] = Field(default_factory=list)
    config: Dict[str, Any] = Field(default_factory=dict)


class ConfigNotifications(BaseModel):
    # extra="allow" preserves any legacy/extension keys that slip through before
    # the migrator reshapes them into `destinations`.
    model_config = ConfigDict(extra="allow")

    destinations: List[NotificationDestination] = Field(default_factory=list)


# ==== ROOT CONFIG MODEL ====


class ScheduleBlock(BaseModel):
    """One entry in a module's multi-block schedule. Each block fires on its own
    `schedule` string and injects `overrides` into that scheduled run's config,
    so a single module can e.g. report daily and remove weekly. Overrides reuse
    the same job-payload mechanism as Upgradinatorr's per-profile schedules."""

    label: str = ""
    enabled: bool = True
    schedule: str = ""
    overrides: Dict[str, Any] = Field(default_factory=dict)


class ChubConfig(BaseModel):
    # Set only by load_config() when config.yml is absent — see has_config_file.
    # Private, so it never serializes into the file save_config writes.
    _no_config_file: bool = PrivateAttr(default=False)

    schedule: Dict[str, Any] = Field(default_factory=dict)
    # Optional multi-block schedules keyed by module name. Additive to
    # `schedule` above (the single-string-per-module form, untouched); a module
    # may use either or both. Each block carries its own override set (e.g.
    # {"mode": "remove"}) applied only to that scheduled run.
    schedule_blocks: Dict[str, List[ScheduleBlock]] = Field(default_factory=dict)
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


# Graft extension-owned config sections onto the root model (typed, with
# defaults), so `load_config().<section>` works for extension modules exactly
# as for core ones. create_model subclasses ChubConfig under the same name;
# with no extensions installed (main) this block is a no-op.
def _apply_extension_config_fields() -> None:
    from backend.extensions import extension_config_fields

    fields = extension_config_fields()
    if fields:
        globals()["ChubConfig"] = create_model(
            "ChubConfig", __base__=ChubConfig, **fields
        )


_apply_extension_config_fields()


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
        # Outbound notification webhook URLs are themselves credentials: a
        # Discord webhook URL grants posting rights, and a Notifiarr passthrough
        # URL embeds the user's API key. Exact-leaf-name match, so the unrelated
        # `webhook_secret` / `webhook_force_reupload` / `webhook_*_delay` fields
        # are unaffected.
        "webhook",
    }
)

REDACTED_PLACEHOLDER = "********"

# Secrets that must NEVER be revealed to the frontend, even though they are in
# SENSITIVE_FIELD_NAMES. The password hash and JWT signing secret are pure
# server-side credentials with no legitimate "show me the value" use.
NEVER_REVEAL_FIELD_NAMES = frozenset({"password_hash", "jwt_secret"})


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


def strip_redacted_placeholders(incoming: Any, current: Any) -> Any:
    """
    Merge *incoming* config over *current*, but preserve the real *current* value
    wherever *incoming* still carries the redacted placeholder. Recurses through
    nested dicts AND lists (element-wise by position). Returns a new structure.

    List recursion matters: the notifications ``destinations`` list holds a
    per-destination ``webhook`` secret. Without it, a round-trip save of the
    redacted config would persist the ``********`` placeholder over the real
    webhook (breaking notification dispatch). The old per-module shape was all
    nested dicts, so this only surfaced once destinations became a list.
    """
    if isinstance(incoming, dict) and isinstance(current, dict):
        merged = {
            k: strip_redacted_placeholders(v, current.get(k))
            for k, v in incoming.items()
        }
        for k, v in current.items():  # keys only present in current
            if k not in merged:
                merged[k] = v
        return merged
    if isinstance(incoming, list) and isinstance(current, list):
        # Prefer matching by a stable ``id`` so a reordered/edited secret-bearing
        # list (e.g. notification destinations) resolves each redacted secret
        # against the SAME item — not whatever now sits at that position, which
        # would leak one item's secret onto another. Fall back to positional
        # matching for id-less lists.
        current_by_id = {
            item["id"]: item
            for item in current
            if isinstance(item, dict) and item.get("id")
        }
        merged_list = []
        for i, item in enumerate(incoming):
            if isinstance(item, dict) and item.get("id") in current_by_id:
                match = current_by_id[item["id"]]
            else:
                match = current[i] if i < len(current) else None
            merged_list.append(strip_redacted_placeholders(item, match))
        return merged_list
    if incoming == REDACTED_PLACEHOLDER and isinstance(current, str):
        return current  # keep the real secret
    return incoming


class SecretNotRevealable(Exception):
    """The requested path does not point at a revealable secret field."""


def resolve_secret_path(data: Any, path: str) -> str:
    """
    Resolve a dotted config *path* against an UNREDACTED config dump and return
    the real secret string at the leaf. Powers the on-demand "reveal" endpoint.

    Traversal supports dict keys and lists. A list segment matches the item
    whose ``id`` equals the segment (mirroring ``strip_redacted_placeholders``,
    so a reordered ``notifications.destinations`` list still resolves the right
    item), falling back to a positional index for id-less lists.

    Defense in depth: the leaf field name must be in ``SENSITIVE_FIELD_NAMES``
    and not in ``NEVER_REVEAL_FIELD_NAMES`` — so this can only ever surface an
    actual, revealable secret, never an arbitrary config value.

    Raises ``SecretNotRevealable`` if the leaf is not a revealable secret, and
    ``KeyError`` if the path does not resolve.
    """
    segments = [s for s in path.split(".") if s != ""]
    if not segments:
        raise KeyError("empty path")

    leaf = segments[-1]
    if leaf not in SENSITIVE_FIELD_NAMES or leaf in NEVER_REVEAL_FIELD_NAMES:
        raise SecretNotRevealable(leaf)

    node: Any = data
    for seg in segments:
        if isinstance(node, dict):
            if seg not in node:
                raise KeyError(seg)
            node = node[seg]
        elif isinstance(node, list):
            match = next(
                (
                    item
                    for item in node
                    if isinstance(item, dict) and str(item.get("id")) == seg
                ),
                None,
            )
            if match is None and seg.isdigit() and int(seg) < len(node):
                match = node[int(seg)]
            if match is None:
                raise KeyError(seg)
            node = match
        else:
            raise KeyError(seg)

    if node is None:
        return ""
    if not isinstance(node, str):
        raise KeyError(f"{leaf} is not a string secret")
    return node


# ==== CONFIG EXCEPTIONS ====


class ConfigError(Exception):
    """Base class for configuration errors; `.message` is response-safe text."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message = message


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


# Parsed configs keyed by path -> (file version, config). AuthMiddleware calls
# load_config() per request; re-reading + revalidating 35 models costs ~3ms.
_config_cache: Dict[str, tuple] = {}
_config_cache_lock = threading.Lock()
_CONFIG_CACHE_MAX = 8


def _config_file_version(path: str) -> Optional[tuple]:
    """Stat signature identifying a config file's contents; None if unreadable."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _cached_config(path: str, version: tuple) -> Optional[ChubConfig]:
    """Return a private copy of the cached config for this file version, if any."""
    with _config_cache_lock:
        entry = _config_cache.get(path)
    if entry is None or entry[0] != version:
        return None
    # A copy, not the cached object: callers (auth/setup/notifications) mutate
    # what load_config returns before saving, and must not poison the cache.
    return entry[1].model_copy(deep=True)


def _cache_config(path: str, version: tuple, config: ChubConfig) -> None:
    """Cache `config` under the file version it was parsed from."""
    if _config_file_version(path) != version:
        return  # rewritten while we read it (e.g. legacy migration) — don't cache
    with _config_cache_lock:
        if len(_config_cache) >= _CONFIG_CACHE_MAX:
            _config_cache.clear()
        _config_cache[path] = (version, config.model_copy(deep=True))


def clear_config_cache() -> None:
    """Drop every cached config (call after config.yml changes out of band)."""
    with _config_cache_lock:
        _config_cache.clear()


def _humanize_validation_msg(msg: str) -> str:
    """Rewrite common Pydantic phrasing for non-developer readers."""
    if "field required" in msg or "Field required" in msg:
        return "missing required field"
    if "not a valid integer" in msg or "valid integer" in msg:
        return "must be a number"
    if "not a valid boolean" in msg or "valid boolean" in msg:
        return "must be true or false"
    if "not a valid string" in msg or "valid string" in msg:
        return "must be text"
    if "invalid or missing URL scheme" in msg:
        return "must be a valid URL (http:// or https://)"
    return msg


def format_validation_errors(validation_error: ValidationError) -> List[str]:
    """Return one humanized "loc: msg (got: value)" line per Pydantic field error.

    Server-side only — the input values make this unsafe to return in a
    response. Use ``format_validation_errors_public`` for that.
    """
    lines: List[str] = []
    for error in validation_error.errors():
        location = " -> ".join(str(loc) for loc in error["loc"])
        msg = _humanize_validation_msg(error["msg"])

        input_value = error.get("input")
        if input_value is not None and not isinstance(input_value, (dict, list)):
            lines.append(f"{location}: {msg} (got: {input_value!r})")
        else:
            lines.append(f"{location}: {msg}")
    return lines


def format_validation_errors_public(validation_error: ValidationError) -> List[str]:
    """Return response-safe "loc: msg" lines — no input values, secrets masked."""
    lines: List[str] = []
    for error in validation_error.errors():
        loc = error["loc"]
        location = " -> ".join(str(part) for part in loc)
        leaf = str(loc[-1]) if loc else ""
        # A sensitive leaf gets a fixed msg too: Pydantic phrasing can quote the
        # offending value (enum/pattern errors), which would echo the secret.
        msg = (
            "invalid value"
            if leaf in SENSITIVE_FIELD_NAMES
            else _humanize_validation_msg(error["msg"])
        )
        lines.append(f"{location}: {msg}")
    return lines


def _print_cli_validation_errors(validation_error: ValidationError) -> None:
    """Print simplified validation errors for CLI users."""
    print("❌ Configuration validation failed:")
    for line in format_validation_errors(validation_error):
        print(f"   • {line}")
    print("💡 Check your config.yml file and fix the issues above")


def _backfill_setup_completed(raw: Dict[str, Any]) -> None:
    """Mark pre-existing installs as setup-complete so only genuinely fresh
    configs see the first-run wizard.

    Runs on EVERY load (not just legacy migration): a chub-native config written
    before this field existed simply lacks the key, and pydantic would otherwise
    default it to False and wrongly re-trigger the wizard for existing users.
    Mutates ``raw`` in place; a no-op once ``general.setup_completed`` is present
    (so an explicit true/false is always respected).
    """
    general = raw.get("general")
    if not isinstance(general, dict):
        general = {}
        raw["general"] = general
    if "setup_completed" in general:
        return  # explicit value wins

    auth = raw.get("auth") or {}
    instances = raw.get("instances") or {}
    tmdb = raw.get("tmdb") or {}
    used = bool(
        (auth.get("username") and auth.get("password_hash"))
        or instances.get("radarr")
        or instances.get("sonarr")
        or instances.get("lidarr")
        or instances.get("plex")
        or tmdb.get("apikey")
    )
    general["setup_completed"] = used


def has_config_file(config: ChubConfig) -> bool:
    """False only for the placeholder load_config() returns when config.yml is absent."""
    return not getattr(config, "_no_config_file", False)


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

    Repeat loads are served from a cache keyed on the file's mtime/size, so an
    edit (or save_config) is picked up but an unchanged file isn't re-parsed.
    """
    from backend.util.config_migrator import is_legacy_config

    config_path = path or get_config_path()

    version = _config_file_version(config_path)
    if version is None:
        # First boot: defaults, but marked so privileged file access can fail
        # closed instead of trusting roots nobody configured (resolve_confined).
        unwritten = ChubConfig()
        unwritten._no_config_file = True
        return unwritten

    cached = _cached_config(config_path, version)
    if cached is not None:
        return cached

    try:
        with open(config_path, "r") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        # Position only — the raw text carries parser internals, plus the
        # offending source line whenever YAML is parsed from a string.
        mark = getattr(e, "problem_mark", None)
        where = (
            f" at line {mark.line + 1}, column {mark.column + 1}"
            if mark is not None
            else ""
        )
        raise ConfigParseError(f"Invalid YAML syntax in {config_path}{where}") from e
    except Exception as e:
        raise ConfigParseError(f"Failed to read {config_path}") from e

    if raw is None:
        raise ConfigParseError(f"Configuration file is empty: {config_path}")

    if is_legacy_config(raw):
        raw = _auto_migrate_and_persist(raw, config_path)

    _backfill_setup_completed(raw)

    try:
        config = ChubConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigValidationError(
            f"Configuration validation failed in {config_path}",
            validation_error=e,
        ) from e
    except Exception as e:
        raise ConfigError(f"Unexpected configuration error in {config_path}") from e

    _reconcile_gdrive_presets(config)

    _cache_config(config_path, version, config)
    return config


def _reconcile_gdrive_presets(config: "ChubConfig") -> None:
    """Repoint gdrive_list entries whose preset drive moved (in memory only).

    Not persisted here — the healed id reaches every consumer and the UI, and
    the user's next Settings save writes it through save_config's atomic path.
    """
    try:
        from backend.util.gdrive_presets import reconcile_gdrive_list

        reconcile_gdrive_list(getattr(config.sync_gdrive, "gdrive_list", None))
    except Exception as exc:  # pragma: no cover - never block a config load
        _config_log.error(f"GDrive preset reconcile skipped: {exc}")


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
        # Atomic write: a crash mid-write must never leave a truncated
        # config.yml — the original stays intact until the replace.
        tmp_path = f"{config_path}.migrating"
        with open(tmp_path, "w") as f:
            yaml.safe_dump(migrated, f, sort_keys=False)
        os.replace(tmp_path, config_path)
    except Exception as e:  # pragma: no cover - best-effort write
        _emit(f"⚠️  Failed to rewrite migrated config to {config_path}: {e}", "warning")

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


def module_is_disabled(module_name: str, config: Optional[ChubConfig] = None) -> bool:
    """True if `module_name` is hard-disabled (in general.disabled_modules).

    A disabled module is skipped by the scheduler and blocked from manual /
    webhook runs. Loads config if one isn't supplied; never raises."""
    try:
        cfg = config if config is not None else load_config()
        disabled = (
            getattr(getattr(cfg, "general", None), "disabled_modules", None) or []
        )
        return module_name in disabled
    except Exception as exc:
        # Fail CLOSED: these modules mutate the filesystem, so a config we
        # can't read must skip the run, not green-light it.
        _config_log.warning(
            f"Could not determine disabled state for '{module_name}' "
            f"({exc}); treating it as disabled"
        )
        return True


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
            # The stat key catches this too; clearing makes it immediate even on
            # a filesystem with coarse mtime granularity.
            clear_config_cache()
        except BaseException:
            # Clean up temp file on any failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # Best-effort cleanup; re-raise original error
            raise
    except Exception as e:
        raise ConfigError("Failed to save configuration") from e


def seed_plex_enabled_libraries(
    instance_name: str, live_libraries: List[str], path: Optional[str] = None
) -> bool:
    """One-time backfill of a Plex instance's ``enabled_libraries`` opt-in list.

    Only acts when the field is unset (``None`` — a legacy config predating the
    opt-in feature). It stamps the server's *currently present* libraries as the
    enabled set so that any library ADDED to Plex later is excluded until the user
    explicitly opts it in. Idempotent: a no-op once the field is a list (including
    an empty "opted out" list). Reads + writes a fresh config so a concurrent edit
    isn't clobbered by a stale in-memory snapshot.

    Returns True iff it seeded (persisted a change).
    """
    cfg = load_config(path)
    detail = cfg.instances.plex.get(instance_name)
    if detail is None or detail.enabled_libraries is not None:
        return False
    # Preserve order, drop dupes — library titles are the key everywhere else.
    detail.enabled_libraries = list(dict.fromkeys(live_libraries))
    save_config(cfg, path)
    return True
