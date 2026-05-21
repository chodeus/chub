import os
import pathlib
import sys
import tempfile
from typing import Any, Dict, List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

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
    action_type: str = "copy"
    asset_folders: bool = False
    print_only_renames: bool = False
    run_border_replacerr: bool = False
    clean_orphan_assets: bool = False
    report_unmatched_assets: bool = False
    source_dirs: List[str] = Field(default_factory=list)
    destination_dir: str = ""
    instances: List[Union[str, Dict[str, PosterRenamerrPlexInstance]]] = Field(
        default_factory=list
    )


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
    border_width: int = 26
    skip: bool = False
    exclusion_list: Optional[List[str]] = None
    ignore_folders: List[str] = Field(default_factory=list)
    border_colors: List[str] = Field(default_factory=list)
    holidays: List[BorderHoliday] = Field(default_factory=list)


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
    count: Union[int, str] = 100
    radarr_count: int = 0
    sonarr_count: int = 0
    tag_name: str = ""
    ignore_tags: str = ""
    enable_batching: bool = False
    instances: List[str] = Field(default_factory=list)


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
    include_collections: bool = True


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


# Notifications is a dict of module_name to dicts (arbitrary structure, so keep Any)
class ConfigNotifications(BaseModel):
    poster_renamerr: Optional[Dict[str, Any]] = Field(default_factory=dict)
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


# ==== SECRET REDACTION ====

SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api",
        "api_key",
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


def _print_cli_validation_errors(validation_error: ValidationError) -> None:
    """Print simplified validation errors for CLI users."""
    print("❌ Configuration validation failed:")
    for error in validation_error.errors():
        location = " -> ".join(str(loc) for loc in error["loc"])
        msg = error["msg"]

        # Simplify common error messages
        if "field required" in msg:
            msg = "missing required field"
        elif "not a valid integer" in msg:
            msg = "must be a number"
        elif "not a valid boolean" in msg:
            msg = "must be true or false"
        elif "not a valid string" in msg:
            msg = "must be text"
        elif "invalid or missing URL scheme" in msg:
            msg = "must be a valid URL (http:// or https://)"

        print(f"   • {location}: {msg}")
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
        print(f"⚠️  Failed to write legacy backup {backup_path}: {e}")
        backup_path = "(backup write failed)"

    try:
        with open(config_path, "w") as f:
            yaml.safe_dump(migrated, f, sort_keys=False)
    except Exception as e:  # pragma: no cover - best-effort write
        print(f"⚠️  Failed to rewrite migrated config to {config_path}: {e}")

    print(f"🔄 Legacy config detected at {config_path}. Migrated automatically.")
    print(f"   Original preserved at {backup_path}")
    for note in notes:
        icon = "⚠️ " if note.level == "warning" else "•"
        print(f"   {icon} {note.message}")
    print(
        "   ⚠️  Verify file/directory paths in this config (sync_gdrive.gdrive_sa_location, "
        "poster_renamerr.source_dirs, poster_cleanarr.asset_dirs, nohl.source_dirs, etc.) "
        "still resolve inside this container — your volume mounts may differ from the previous setup."
    )

    return migrated


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
