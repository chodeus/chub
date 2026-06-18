# modules/poster_cleanarr.py

import glob
import json
import os
import shutil
import time
import zipfile
from typing import Any, Dict, List, Optional, Set, Tuple

from PIL import Image, UnidentifiedImageError

from backend.util.base_module import ChubModule
from backend.util.constants import asset_type_regex, tmdb_id_regex, tvdb_id_regex
from backend.util.database import ChubDB
from backend.util.helper import create_table
from backend.util.logger import Logger
from backend.util.notification import NotificationManager
from backend.util.normalization import normalize_titles, parse_asset_filename

# EXIF tag id Kometa writes onto its generated overlay images. Used by the
# overlays_only mode to skip user-uploaded customs (which lack the tag).
KOMETA_OVERLAY_EXIF_TAG = 0x04BC
KOMETA_OVERLAY_EXIF_VALUE = "overlay"


def _first_int_id(regex, names: Tuple[str, ...]) -> Optional[int]:
    """Return the first integer id `regex` finds across `names` (filename then
    folder), or None. Used to pull {tmdb-N}/{tvdb-N} off a raw asset path
    BEFORE normalization strips the id block."""
    for name in names:
        match = regex.search(name)
        if match:
            try:
                return int(match.group(1))
            except (ValueError, TypeError):
                return None
    return None


def format_bytes(size: int) -> str:
    """Format byte count into human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


VALID_MODES = {"report", "move", "remove", "restore", "clear", "nothing"}
VALID_ORPHAN_MODES = {"report", "move", "remove"}
VALID_STALE_MODES = {"report", "move", "remove"}
ASSET_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
RESTORE_DIR_NAME = "Poster Cleanarr Restore"
ORPHAN_RESTORE_DIR_NAME = ".chub_orphan_restore"
PLEX_DB_NAME = "com.plexapp.plugins.library.db"
DB_MAX_AGE_HOURS = 2

# Dead-symlink sweep circuit-breaker: if at least this many links are scanned
# and more than this fraction are broken, assume the link target volume is
# unmounted (which makes EVERY link look broken) rather than the assets being
# stale — skip the sweep instead of mass-flagging good links.
DEAD_LINK_MIN_FOR_RATIO = 20
DEAD_LINK_MAX_BROKEN_RATIO = 0.5

MODE_LABELS = {
    "report": {"ed": "Reported", "ing": "Reporting"},
    "move": {"ed": "Moved", "ing": "Moving"},
    "remove": {"ed": "Removed", "ing": "Removing"},
    "restore": {"ed": "Restored", "ing": "Restoring"},
    "clear": {"ed": "Cleared", "ing": "Clearing"},
    "nothing": {"ed": "Skipped", "ing": "Skipping"},
}


class PosterCleanarr(ChubModule):
    def __init__(self, logger: Optional[Logger] = None) -> None:
        super().__init__(logger=logger)
        self.plex_path: str = getattr(self.config, "plex_path", "")
        self.mode: str = getattr(self.config, "mode", "report")
        self.working_dir: str = self._get_working_dir()

    def _get_working_dir(self) -> str:
        """Get working directory for DB storage."""
        config_dir = os.environ.get("CONFIG_DIR") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config"
        )
        working = os.path.join(config_dir, "poster_cleanarr")
        os.makedirs(working, exist_ok=True)
        return working

    # =========================================================================
    # Main entry
    # =========================================================================

    def run(self) -> None:
        try:
            start_time = time.time()

            # Validate mode
            if self.mode not in VALID_MODES:
                self.logger.error(
                    f"Invalid mode '{self.mode}'. Must be one of: {', '.join(sorted(VALID_MODES))}"
                )
                return

            # Validate plex_path for modes that need it
            if self.mode not in ("nothing",) and not self._validate_plex_path():
                return

            metadata_dir = (
                os.path.join(self.plex_path, "Metadata") if self.plex_path else ""
            )
            restore_dir = (
                os.path.join(self.plex_path, RESTORE_DIR_NAME) if self.plex_path else ""
            )

            # Check restore dir conflict
            if self.mode in ("move", "remove", "report") and os.path.isdir(restore_dir):
                self.logger.error(
                    f"Cannot run in '{self.mode}' mode while '{RESTORE_DIR_NAME}' directory exists. "
                    f"Run in 'restore' mode to recover files or 'clear' mode to delete them first."
                )
                return

            # Banner
            label = MODE_LABELS.get(self.mode, {})
            table = [
                ["Poster Cleanarr"],
                [
                    f"Mode: {self.mode.capitalize()} — {label.get('ing', '')} bloat images"
                ],
            ]
            self.logger.info(create_table(table))

            # Get Plex connection if needed (only for DB retrieval via API now;
            # server-level maintenance tasks moved to the plex_maintenance module).
            plex_server = None
            needs_plex = not self.config.local_db and self.mode not in (
                "restore",
                "clear",
                "nothing",
            )
            if needs_plex:
                plex_server = self._get_plex_server()
                if plex_server is None:
                    self.logger.error("Failed to connect to Plex server. Aborting.")
                    return

            # === Bloat image operations ===
            bloat_stats = {"count": 0, "total_size": 0, "files": []}

            if self.mode in ("report", "move", "remove"):
                # Retrieve Plex database
                db_path = self._get_plex_database(plex_server)
                if db_path is None:
                    self.logger.error(
                        "Failed to retrieve Plex database. Aborting image scan."
                    )
                else:
                    # Query in-use images
                    db_start = time.time()
                    in_use = self._query_in_use_images(db_path)
                    db_elapsed = time.time() - db_start
                    self.logger.info(
                        f"Found {len(in_use)} in-use images in Plex DB ({db_elapsed:.1f}s)"
                    )

                    # Scan for bloat
                    scan_start = time.time()
                    bloat_list = self._scan_bloat_images(metadata_dir, in_use)
                    scan_elapsed = time.time() - scan_start

                    # target_paths override: the API enqueues jobs with a
                    # specific subset when the user selected tiles in the
                    # Poster Cleanarr UI. Filter the bloat list so only
                    # those files are processed. When unset, full library.
                    target_paths = getattr(self.config, "target_paths", None)
                    if isinstance(target_paths, list) and target_paths:
                        wanted = {os.path.realpath(p) for p in target_paths}
                        before = len(bloat_list)
                        bloat_list = [
                            b
                            for b in bloat_list
                            if os.path.realpath(b["path"]) in wanted
                        ]
                        self.logger.info(
                            f"target_paths restricted to {len(bloat_list)} of {before} bloat files"
                        )

                    total_size = sum(b["size"] for b in bloat_list)
                    self.logger.info(
                        f"Found {len(bloat_list)} bloat images ({format_bytes(total_size)}) "
                        f"in {scan_elapsed:.1f}s"
                    )

                    # Execute mode
                    bloat_stats = self._execute_mode(
                        bloat_list, self.mode, metadata_dir, restore_dir
                    )

            elif self.mode == "restore":
                bloat_stats = self._execute_restore(restore_dir, metadata_dir)

            elif self.mode == "clear":
                bloat_stats = self._execute_clear(restore_dir)

            # === Orphan asset cleanup ===
            orphan_stats: Dict[str, Any] = {"count": 0, "total_size": 0}
            if getattr(self.config, "orphan_assets_enabled", False):
                with ChubDB(logger=self.logger) as db:
                    orphan_stats = self._run_orphan_pass(
                        db=db,
                        instances=self._resolve_orphan_instances(self.config),
                        asset_dirs=list(getattr(self.config, "asset_dirs", []) or []),
                        mode=getattr(self.config, "orphan_assets_mode", "report"),
                        include_collections=bool(
                            getattr(self.config, "include_collections", True)
                        ),
                        logger=self.logger,
                        ignore_titles=list(
                            getattr(self.config, "orphan_ignore_titles", []) or []
                        ),
                    )

            # === Clean empty directories ===
            empty_dirs = 0
            if self.mode not in ("report", "nothing") and metadata_dir:
                empty_dirs = self._clean_empty_dirs(metadata_dir)

            # === Report ===
            elapsed = time.time() - start_time
            output = self._build_output(bloat_stats, orphan_stats, empty_dirs, elapsed)
            self._print_report(output)

            # === Notify ===
            has_activity = (
                bloat_stats.get("count", 0) > 0 or orphan_stats.get("count", 0) > 0
            )
            if has_activity:
                try:
                    manager = NotificationManager(
                        self.full_config, self.logger, module_name="poster_cleanarr"
                    )
                    manager.send_notification(output)
                except Exception as e:
                    self.logger.error(f"Failed to send notification: {e}")

        except KeyboardInterrupt:
            self.logger.info("Keyboard Interrupt detected. Exiting...")
            return
        except Exception:
            self.logger.error("\n\nAn error occurred:\n", exc_info=True)
        finally:
            self.logger.log_outro()

    # =========================================================================
    # Plex path validation
    # =========================================================================

    def _validate_plex_path(self) -> bool:
        """Validate plex_path exists and has expected structure."""
        if not self.plex_path:
            self.logger.error(
                "plex_path is not configured. Set it in poster_cleanarr config."
            )
            return False
        if not os.path.isdir(self.plex_path):
            self.logger.error(f"Plex path does not exist: {self.plex_path}")
            return False

        if self.mode in ("report", "move", "remove"):
            metadata_dir = os.path.join(self.plex_path, "Metadata")
            if not os.path.isdir(metadata_dir):
                self.logger.error(f"Metadata directory not found: {metadata_dir}")
                return False

        if self.config.local_db:
            db_dir = os.path.join(self.plex_path, "Plug-in Support", "Databases")
            if not os.path.isdir(db_dir):
                self.logger.error(f"Plex database directory not found: {db_dir}")
                return False

        return True

    # =========================================================================
    # Plex connection
    # =========================================================================

    def _get_plex_server(self):
        """Select the configured Plex instance and connect (with retry).

        Selection is module-specific (tolerates Radarr/Sonarr entries mixed into
        the same `instances` list for the orphan-asset comparison set); the
        connect+retry loop is the shared plex.connect_plex_with_retry.
        """
        instances = self.config.instances
        plex_instances = self.full_config.instances.plex

        if not instances:
            # Require an explicit instance selection — never auto-pick. Module
            # wiring should be intentional, not inferred from "there's only
            # one configured anyway."
            self.logger.error(
                "No Plex instances selected for poster_cleanarr. "
                "Pick one in Settings → Modules → Poster Cleanarr → Plex Instances "
                f"(available: {sorted(plex_instances) or 'none'})."
            )
            return None

        # Pick the first configured instance that is a Plex one.
        instance_name = next((n for n in instances if n in plex_instances), None)
        if instance_name is None:
            self.logger.error(
                "No Plex instance found among the selected instances "
                f"{list(instances)}. Available Plex instances: {sorted(plex_instances) or 'none'}."
            )
            return None

        instance_detail = plex_instances[instance_name]
        url = instance_detail.url
        token = instance_detail.api

        if not url or not token:
            self.logger.error(
                f"Plex instance '{instance_name}' is missing url or api token."
            )
            return None

        from backend.util.plex import connect_plex_with_retry

        return connect_plex_with_retry(
            url,
            token,
            self.logger,
            instance_name=instance_name,
            timeout=self.config.timeout,
            linear_backoff=True,  # preserve poster_cleanarr's escalating wait
        )

    # =========================================================================
    # Plex database retrieval
    # =========================================================================

    def _get_plex_database(self, plex_server=None) -> Optional[str]:
        """Retrieve Plex database for image analysis."""
        working_db = os.path.join(self.working_dir, PLEX_DB_NAME)

        # Check if we can reuse existing
        if self.config.use_existing_db:
            usable, age_str = self._check_db_age(working_db)
            if usable:
                self.logger.info(f"Reusing existing database ({age_str} old)")
                return working_db

        if self.config.local_db:
            return self._copy_local_db(working_db)
        else:
            return self._download_db(plex_server, working_db)

    def _check_db_age(self, db_path: str) -> Tuple[bool, str]:
        """Check if database file exists and is less than DB_MAX_AGE_HOURS old."""
        if not os.path.exists(db_path):
            return False, ""
        mtime = os.path.getmtime(db_path)
        age_seconds = time.time() - mtime
        age_hours = age_seconds / 3600
        age_minutes = int(age_seconds / 60)

        if age_hours < DB_MAX_AGE_HOURS:
            return True, f"{age_minutes}m"
        return False, f"{age_minutes}m"

    def _check_plex_running(self) -> bool:
        """Check for Plex DB temp files indicating Plex is running."""
        db_dir = os.path.join(self.plex_path, "Plug-in Support", "Databases")
        shm_file = os.path.join(db_dir, f"{PLEX_DB_NAME}-shm")
        wal_file = os.path.join(db_dir, f"{PLEX_DB_NAME}-wal")
        return os.path.exists(shm_file) or os.path.exists(wal_file)

    def _copy_local_db(self, dest_path: str) -> Optional[str]:
        """Copy Plex database locally."""
        if self._check_plex_running() and not self.config.ignore_running:
            self.logger.warning(
                "Plex appears to be running (temp files detected). "
                "Database may be locked. Use 'ignore_running: true' to bypass."
            )
            return None

        source_db = os.path.join(
            self.plex_path, "Plug-in Support", "Databases", PLEX_DB_NAME
        )
        if not os.path.exists(source_db):
            self.logger.error(f"Plex database not found: {source_db}")
            return None

        try:
            self.logger.info(f"Copying Plex database from {source_db}...")
            shutil.copy2(source_db, dest_path)
            self.logger.info("Database copied successfully.")
            return dest_path
        except Exception as e:
            self.logger.error(f"Failed to copy database: {e}")
            return None

    def _download_db(self, plex_server, dest_path: str) -> Optional[str]:
        """Download Plex database via API."""
        if plex_server is None:
            self.logger.error("No Plex server connection for database download.")
            return None

        try:
            self.logger.info("Downloading Plex database via API...")
            temp_dir = os.path.join(self.working_dir, "temp")
            os.makedirs(temp_dir, exist_ok=True)

            # Request database backup from Plex
            url = f"{plex_server._baseurl}/diagnostics/databases"
            headers = {
                "X-Plex-Token": plex_server._token,
                "Accept": "application/octet-stream",
            }

            import requests

            response = requests.get(
                url, headers=headers, stream=True, timeout=self.config.timeout
            )
            response.raise_for_status()

            # Save to temp file
            temp_file = os.path.join(temp_dir, "plex_db_download")
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            last_logged_pct = -1

            with open(temp_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = int(downloaded / total_size * 100)
                        if pct % 20 == 0 and pct != last_logged_pct:
                            self.logger.info(f"Downloading database... {pct}%")
                            last_logged_pct = pct

            # Check if it's a ZIP or raw DB
            try:
                with zipfile.ZipFile(temp_file, "r") as zf:
                    # Find the database file in the ZIP
                    db_files = [
                        n
                        for n in zf.namelist()
                        if "com.plexapp.plugins.library.db" in n
                        or n.startswith("databaseBackup")
                    ]
                    if db_files:
                        # Validate extracted path stays within temp_dir (zip traversal protection)
                        target_path = os.path.realpath(
                            os.path.join(temp_dir, db_files[0])
                        )
                        if not target_path.startswith(
                            os.path.realpath(temp_dir) + os.sep
                        ):
                            self.logger.error(
                                f"Zip path traversal detected: {db_files[0]}"
                            )
                            shutil.rmtree(temp_dir, ignore_errors=True)
                            return None
                        zf.extract(db_files[0], temp_dir)
                        extracted = os.path.join(temp_dir, db_files[0])
                        shutil.move(extracted, dest_path)
                    else:
                        self.logger.error("Database file not found in ZIP archive.")
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        return None
            except zipfile.BadZipFile:
                # Not a ZIP, treat as raw database
                shutil.move(temp_file, dest_path)

            # Cleanup temp
            shutil.rmtree(temp_dir, ignore_errors=True)

            self.logger.info("Database downloaded successfully.")
            return dest_path

        except Exception as e:
            self.logger.error(f"Failed to download database: {e}")
            return None

    # =========================================================================
    # Image analysis
    # =========================================================================

    def _query_in_use_images(self, db_path: str) -> Set[str]:
        """Query Plex for in-use image filenames.

        Delegates to the single canonical scan in plex_metadata so the set of
        protected columns (IN_USE_IMAGE_COLUMNS — thumb/art/banner/clear-logo/
        square-art) stays identical to the API-side bloat report and can't drift.
        """
        from backend.util.plex_metadata import get_in_use_hashes

        return get_in_use_hashes(db_path, logger=self.logger)

    def _scan_bloat_images(
        self, metadata_dir: str, in_use: Set[str]
    ) -> List[Dict[str, Any]]:
        """Walk Metadata directory and find bloat images."""
        bloat: List[Dict[str, Any]] = []

        for root, dirs, files in os.walk(metadata_dir):
            if self.is_cancelled():
                break

            # Skip Contents directories (Plex internal bundles)
            if "Contents" in root.split(os.sep):
                continue

            for filename in files:
                # Plex custom images have no file extension (no dot in name)
                if "." in filename:
                    continue

                # If filename is not in the in-use set, it's bloat
                if filename not in in_use:
                    filepath = os.path.join(root, filename)
                    try:
                        size = os.path.getsize(filepath)
                    except OSError:
                        size = 0
                    bloat.append({"path": filepath, "size": size, "name": filename})

        return bloat

    # =========================================================================
    # Mode execution
    # =========================================================================

    @staticmethod
    def _is_kometa_overlay(path: str) -> bool:
        """True if the image at `path` carries Kometa's overlay EXIF marker.

        Plex uploads are stored extensionless, which `Image.open` handles fine
        (PIL detects format from magic bytes). Anything we can't open or read
        EXIF from is treated as "not a Kometa overlay" so overlays_only mode
        leaves it alone — that's the conservative direction (skip rather than
        delete on uncertainty)."""
        try:
            with Image.open(path) as img:
                exif = img.getexif()
                return exif.get(KOMETA_OVERLAY_EXIF_TAG) == KOMETA_OVERLAY_EXIF_VALUE
        except (UnidentifiedImageError, OSError, ValueError):
            return False

    def _execute_mode(
        self,
        bloat_list: List[Dict[str, Any]],
        mode: str,
        metadata_dir: str,
        restore_dir: str,
    ) -> Dict[str, Any]:
        """Execute the chosen mode on bloat files."""
        count = 0
        total_size = 0
        label = MODE_LABELS.get(mode, {})
        overlays_only = bool(getattr(self.config, "overlays_only", False))
        ignored_non_overlay = 0

        if not bloat_list:
            self.logger.info("No bloat images found. Plex metadata is clean!")
            return {"count": 0, "total_size": 0, "mode": mode}

        if overlays_only:
            self.logger.info(
                f"overlays_only enabled — only files with the Kometa overlay "
                f"EXIF tag (0x{KOMETA_OVERLAY_EXIF_TAG:04x} == '{KOMETA_OVERLAY_EXIF_VALUE}') will be {label.get('ed', 'processed').lower()}."
            )
        self.logger.info(
            f"{label.get('ing', 'Processing')} {len(bloat_list)} bloat images..."
        )

        for item in bloat_list:
            if self.is_cancelled():
                break

            filepath = item["path"]
            size = item["size"]

            if overlays_only and not self._is_kometa_overlay(filepath):
                self.logger.debug(
                    f"  [SKIP non-overlay] {filepath} (no Kometa EXIF tag)"
                )
                ignored_non_overlay += 1
                continue

            if mode == "report":
                # Per-file audit at DEBUG only — at INFO this drowns the log
                # (3k+ lines per run). INFO carries summary + errors.
                self.logger.debug(f"  [REPORT] {filepath} ({format_bytes(size)})")
                count += 1
                total_size += size

            elif mode == "move":
                try:
                    self._move_file(filepath, metadata_dir, restore_dir)
                    # Destructive ops stay at INFO deliberately — users must be
                    # able to audit what was moved/deleted without debug mode
                    # (pinned by test_execute_mode_remove_logs_per_file_at_info).
                    self.logger.info(f"  [MOVE] {os.path.basename(filepath)}")
                    count += 1
                    total_size += size
                except Exception as e:
                    self.logger.error(f"Failed to move {filepath}: {e}")

            elif mode == "remove":
                try:
                    os.remove(filepath)
                    self.logger.info(f"  [REMOVE] {os.path.basename(filepath)}")
                    count += 1
                    total_size += size
                except Exception as e:
                    self.logger.error(f"Failed to remove {filepath}: {e}")

        if overlays_only and ignored_non_overlay:
            self.logger.info(
                f"overlays_only: skipped {ignored_non_overlay} non-overlay file(s)."
            )
        self.logger.info(
            f"{label.get('ed', 'Processed')} {count} bloat images ({format_bytes(total_size)})"
        )
        self.logger.info(f"   → bloat scan: {count} {mode}d")
        return {
            "count": count,
            "total_size": total_size,
            "mode": mode,
            "ignored_non_overlay": ignored_non_overlay,
        }

    def _execute_restore(self, restore_dir: str, metadata_dir: str) -> Dict[str, Any]:
        """Restore previously moved files from restore directory."""
        if not os.path.isdir(restore_dir):
            self.logger.info(
                f"No '{RESTORE_DIR_NAME}' directory found. Nothing to restore."
            )
            return {"count": 0, "total_size": 0, "mode": "restore"}

        count = 0
        total_size = 0
        restore_files = list(
            glob.iglob(os.path.join(restore_dir, "**", "*.jpg"), recursive=True)
        )

        if not restore_files:
            self.logger.info("Restore directory is empty. Nothing to restore.")
            return {"count": 0, "total_size": 0, "mode": "restore"}

        self.logger.info(f"Restoring {len(restore_files)} files...")

        failed = 0
        for filepath in restore_files:
            try:
                size = os.path.getsize(filepath)
                self._restore_file(filepath, restore_dir, metadata_dir)
                self.logger.debug(f"  [RESTORE] {filepath} ({format_bytes(size)})")
                count += 1
                total_size += size
            except Exception as e:
                failed += 1
                self.logger.error(f"Failed to restore {filepath}: {e}")

        # Remove restore directory only if all restores succeeded
        if failed == 0:
            try:
                shutil.rmtree(restore_dir)
                self.logger.info(f"Removed '{RESTORE_DIR_NAME}' directory.")
            except Exception as e:
                self.logger.error(f"Failed to remove restore directory: {e}")
        else:
            self.logger.warning(
                f"{failed} file(s) failed to restore. "
                f"Keeping '{RESTORE_DIR_NAME}' directory for retry."
            )

        self.logger.info(f"Restored {count} files ({format_bytes(total_size)})")
        return {"count": count, "total_size": total_size, "mode": "restore"}

    def _execute_clear(self, restore_dir: str) -> Dict[str, Any]:
        """Permanently delete the restore directory."""
        if not os.path.isdir(restore_dir):
            self.logger.info(
                f"No '{RESTORE_DIR_NAME}' directory found. Nothing to clear."
            )
            return {"count": 0, "total_size": 0, "mode": "clear"}

        count = 0
        total_size = 0

        # Count files and accumulate sizes before deletion
        for root, dirs, files in os.walk(restore_dir):
            for filename in files:
                filepath = os.path.join(root, filename)
                try:
                    total_size += os.path.getsize(filepath)
                    count += 1
                except OSError:
                    count += 1

        try:
            shutil.rmtree(restore_dir)
            self.logger.info(
                f"Cleared '{RESTORE_DIR_NAME}' directory: "
                f"{count} files ({format_bytes(total_size)})"
            )
        except Exception as e:
            self.logger.error(f"Failed to clear restore directory: {e}")

        return {"count": count, "total_size": total_size, "mode": "clear"}

    # =========================================================================
    # File operations
    # =========================================================================

    def _move_file(self, src: str, metadata_dir: str, restore_dir: str) -> None:
        """Move a file to restore directory preserving structure, appending .jpg suffix."""
        relative = os.path.relpath(src, metadata_dir)
        dest = os.path.join(restore_dir, relative) + ".jpg"
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)

    def _restore_file(self, src: str, restore_dir: str, metadata_dir: str) -> None:
        """Restore a file from restore directory, stripping .jpg suffix."""
        relative = os.path.relpath(src, restore_dir)
        # Strip .jpg suffix that was added during move
        if relative.endswith(".jpg"):
            relative = relative[:-4]
        dest = os.path.join(metadata_dir, relative)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(src, dest)

    # =========================================================================
    # Orphan asset cleanup
    # =========================================================================

    @staticmethod
    def _resolve_orphan_instances(config: Any) -> List[str]:
        """ARR instances whose libraries form the orphan comparison set.

        Reads the orphan-specific ``orphan_instances`` and falls back to
        ``instances`` when it's empty, so pre-split configs that listed ARR
        names alongside the Plex instance in ``instances`` keep working.
        """
        return list(getattr(config, "orphan_instances", []) or []) or list(
            getattr(config, "instances", []) or []
        )

    def _run_orphan_pass(
        self,
        db: ChubDB,
        instances: List[str],
        asset_dirs: List[str],
        mode: str,
        include_collections: bool,
        logger: Logger,
        ignore_titles: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Walk `asset_dirs` and report/move/remove files whose title doesn't
        match any media row cached for the configured `instances`.

        The comparison set is whatever poster_renamerr's last sync wrote to
        media_cache + collection_cache — no live Plex/*arr calls here.
        """
        if mode not in VALID_ORPHAN_MODES:
            logger.error(
                f"Invalid orphan_assets_mode '{mode}'. "
                f"Must be one of: {', '.join(sorted(VALID_ORPHAN_MODES))}"
            )
            return {"count": 0, "total_size": 0, "mode": mode}

        if not asset_dirs:
            logger.warning(
                "Orphan asset cleanup enabled but asset_dirs is empty; skipping."
            )
            return {"count": 0, "total_size": 0, "mode": mode}

        if not instances:
            logger.error(
                "Orphan asset cleanup enabled but no instances selected; "
                "cannot build a comparison set."
            )
            return {"count": 0, "total_size": 0, "mode": mode}

        valid_dirs = [d for d in asset_dirs if os.path.isdir(d)]
        for d in asset_dirs:
            if not os.path.isdir(d):
                logger.warning(f"asset_dir does not exist, skipping: {d}")
        if not valid_dirs:
            return {"count": 0, "total_size": 0, "mode": mode}

        titles = self._build_library_title_set(db, instances, include_collections)
        if not titles:
            logger.warning(
                "Library title set is empty for the configured instances — "
                "run poster_renamerr at least once to populate media_cache "
                "before enabling orphan cleanup. Skipping to avoid mass deletion."
            )
            return {"count": 0, "total_size": 0, "mode": mode}

        tmdb_ids, tvdb_ids = self._build_library_id_sets(db, instances)
        ignore_keys = {
            normalize_titles(t) for t in (ignore_titles or []) if t and t.strip()
        }
        ignore_keys.discard("")

        logger.info(
            f"Comparison set: {len(titles)} normalized titles, "
            f"{len(tmdb_ids)} tmdb / {len(tvdb_ids)} tvdb ids across "
            f"{len(instances)} instance(s)."
            + (f" Ignoring {len(ignore_keys)} title(s)." if ignore_keys else "")
        )

        orphans = self._scan_orphan_assets(
            valid_dirs, titles, tmdb_ids, tvdb_ids, ignore_keys
        )
        total_size = sum(item["size"] for item in orphans)
        logger.info(f"Found {len(orphans)} orphan assets ({format_bytes(total_size)}).")

        return self._execute_orphan_mode(orphans, mode, logger)

    def _build_library_title_set(
        self, db: ChubDB, instances: List[str], include_collections: bool
    ) -> Set[str]:
        """Union of normalized titles across media_cache + collection_cache
        filtered to the configured instances. Includes alternate titles when
        present so renames/translations don't false-positive into deletion."""
        wanted = set(instances)
        titles: Set[str] = set()

        def _absorb(row: dict) -> None:
            if row.get("instance_name") not in wanted:
                return
            nt = row.get("normalized_title")
            if nt:
                titles.add(nt)
            raw_alt = row.get("normalized_alternate_titles")
            if not raw_alt:
                return
            try:
                parsed_alt = (
                    json.loads(raw_alt) if isinstance(raw_alt, str) else raw_alt
                )
            except (ValueError, TypeError):
                parsed_alt = []
            if isinstance(parsed_alt, list):
                for piece in parsed_alt:
                    if isinstance(piece, str) and piece:
                        titles.add(piece)

        for row in db.media.get_all():
            _absorb(row)
        if include_collections:
            for row in db.collection.get_all():
                _absorb(row)

        return titles

    def _build_library_id_sets(
        self, db: ChubDB, instances: List[str]
    ) -> Tuple[Set[int], Set[int]]:
        """Sets of (tmdb_ids, tvdb_ids) across media_cache for the configured
        instances. Collections are deliberately excluded: a collection's
        tmdb_id is a TMDB *collection* id, a different namespace from a movie's
        tmdbId, so mixing them risks a false ID match."""
        wanted = set(instances)
        tmdb_ids: Set[int] = set()
        tvdb_ids: Set[int] = set()
        for row in db.media.get_all():
            if row.get("instance_name") not in wanted:
                continue
            tmdb = row.get("tmdb_id")
            tvdb = row.get("tvdb_id")
            try:
                if tmdb not in (None, "", 0):
                    tmdb_ids.add(int(tmdb))
            except (ValueError, TypeError):
                pass  # non-numeric / malformed id — skip it
            try:
                if tvdb not in (None, "", 0):
                    tvdb_ids.add(int(tvdb))
            except (ValueError, TypeError):
                pass  # non-numeric / malformed id — skip it
        return tmdb_ids, tvdb_ids

    def _build_canonical_folder_map(
        self, db: ChubDB, instances: List[str]
    ) -> Dict[Tuple[str, int], str]:
        """Map ('tvdb'|'tmdb', id) -> the media item's canonical folder name
        (media_cache.folder), scoped to `instances`. Only main (season-less)
        rows define the folder, so the show-level folder isn't shadowed by a
        season row. Used to tell a stale-duplicate asset folder (wrong name)
        from the canonical one."""
        wanted = set(instances)
        out: Dict[Tuple[str, int], str] = {}
        for row in db.media.get_all():
            if row.get("instance_name") not in wanted:
                continue
            if row.get("season_number") is not None:
                continue
            folder = row.get("folder")
            if not folder:
                continue
            for kind, raw in (
                ("tvdb", row.get("tvdb_id")),
                ("tmdb", row.get("tmdb_id")),
            ):
                try:
                    if raw not in (None, "", 0):
                        out[(kind, int(raw))] = folder
                except (ValueError, TypeError):
                    continue
        return out

    def _scan_stale_duplicates(
        self,
        asset_dirs: List[str],
        canonical_by_id: Dict[Tuple[str, int], str],
    ) -> List[Dict[str, Any]]:
        """Top-level asset folders whose {tvdb/tmdb} id matches a live media
        item but whose name != that item's canonical folder. Spare-only on the
        id: an id with no live match is left to the orphan pass, never flagged
        here. `canonical_present` records whether the correctly-named folder is
        already on disk — removal must keep the only copy (see
        _execute_stale_mode)."""
        out: List[Dict[str, Any]] = []
        for asset_dir in asset_dirs:
            if not os.path.isdir(asset_dir):
                continue
            try:
                entries = sorted(os.listdir(asset_dir))
            except OSError:
                continue
            for name in entries:
                full = os.path.join(asset_dir, name)
                if not os.path.isdir(full):
                    continue
                canonical = None
                ident = None
                mt = tmdb_id_regex.search(name)
                mv = tvdb_id_regex.search(name)
                if mv and ("tvdb", int(mv.group(1))) in canonical_by_id:
                    ident = ("tvdb", int(mv.group(1)))
                elif mt and ("tmdb", int(mt.group(1))) in canonical_by_id:
                    ident = ("tmdb", int(mt.group(1)))
                if ident is None:
                    continue  # no live id match -> orphan-pass territory, not stale
                canonical = canonical_by_id[ident]
                if name == canonical:
                    continue  # this IS the canonical folder
                size = 0
                for r, _d, files in os.walk(full):
                    for f in files:
                        try:
                            size += os.path.getsize(os.path.join(r, f))
                        except OSError:
                            pass
                out.append(
                    {
                        "folder": full,
                        "asset_dir": asset_dir,
                        "name": name,
                        "canonical": canonical,
                        "canonical_present": os.path.isdir(
                            os.path.join(asset_dir, canonical)
                        ),
                        "id": ident,
                        "size": size,
                    }
                )
        return out

    def _execute_stale_mode(
        self, dupes: List[Dict[str, Any]], mode: str
    ) -> Dict[str, Any]:
        """report/move/remove stale-duplicate FOLDERS. move/remove are skipped
        for an entry whose canonical folder is not yet on disk so the only
        staged copy is never destroyed (the renamer recreates the canonical
        folder on its next run, after which this dup is safe to drop)."""
        count = 0
        total_size = 0
        touched: Set[str] = set()
        for d in dupes:
            folder = d["folder"]
            size = d.get("size", 0)
            if mode == "report":
                self.logger.info(f"  [STALE DUP] {folder} (current: {d['canonical']})")
                count += 1
                total_size += size
                continue
            if not d.get("canonical_present"):
                self.logger.info(
                    f"  [STALE KEPT] {folder} — canonical '{d['canonical']}' "
                    "not staged yet; keeping the only copy"
                )
                continue
            if mode == "move":
                dest_root = os.path.join(d["asset_dir"], ORPHAN_RESTORE_DIR_NAME)
                dest = os.path.join(dest_root, d["name"])
                try:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.move(folder, dest)
                    self.logger.info(f"  [STALE MOVED] {folder} -> {dest}")
                    count += 1
                    total_size += size
                    touched.add(d["asset_dir"])
                except OSError as e:
                    self.logger.error(f"Failed to move {folder}: {e}")
            elif mode == "remove":
                try:
                    shutil.rmtree(folder)
                    self.logger.info(f"  [STALE REMOVED] {folder}")
                    count += 1
                    total_size += size
                    touched.add(d["asset_dir"])
                except OSError as e:
                    self.logger.error(f"Failed to remove {folder}: {e}")
        empty = sum(self._clean_empty_dirs(d) for d in touched)
        self.logger.info(
            f"   → stale duplicates: {count} {mode}d"
            + (f", {empty} empty dir(s) pruned" if empty else "")
        )
        return {"count": count, "total_size": total_size, "mode": mode}

    def _scan_orphan_assets(
        self,
        asset_dirs: List[str],
        library_titles: Set[str],
        tmdb_ids: Optional[Set[int]] = None,
        tvdb_ids: Optional[Set[int]] = None,
        ignore_keys: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Walk each asset_dir and collect images whose media can't be found in
        the library. A file is flagged as an orphan ONLY when nothing matches —
        every check below can only spare a file, never flag one, mirroring the
        upstream asset_cleanup script's spare-only matching.

        One exception precedes the spare-only checks: a SYMLINK whose target no
        longer exists (a stale link left after a rename, or one whose source was
        removed) is flagged regardless of title — a broken link is dead weight
        even if its name still matches the library. Broken links are tallied
        against total links so an unmounted target (every link looks broken)
        trips a circuit-breaker rather than mass-flagging good links.

        Matching, in priority order, per file:

          1. Ignore list — a normalized title in `ignore_keys` is always spared.
          2. ID match — a ``{tmdb-N}``/``{tvdb-N}`` tag on the filename or parent
             folder whose id is in the library's cached ids spares the file
             (the most reliable signal). An id MISS is neutral: it falls through
             to the title check rather than flagging, so a stale/renamed id
             whose title still matches is kept.
          3. Title — matched by EITHER the filename-derived title OR the parent
             folder's title (asset-type tag stripped first). This keeps Kometa
             asset_folders layouts safe: ``<Title (Year)>/logo.png`` resolves
             via the folder, ``<Title (Year)>_logo.png`` via the filename — so
             asset_renamerr's additional artwork and Kometa's own
             ``poster.jpg``/``logo.png`` aren't mis-flagged.
        """
        tmdb_ids = tmdb_ids or set()
        tvdb_ids = tvdb_ids or set()
        ignore_keys = ignore_keys or set()
        orphans: List[Dict[str, Any]] = []
        dead_links: List[Dict[str, Any]] = []
        total_links = 0
        for asset_dir in asset_dirs:
            restore_real = os.path.realpath(
                os.path.join(asset_dir, ORPHAN_RESTORE_DIR_NAME)
            )
            for root, dirs, files in os.walk(asset_dir):
                # Don't scan the restore subdir itself.
                root_real = os.path.realpath(root)
                if root_real == restore_real or root_real.startswith(
                    restore_real + os.sep
                ):
                    dirs[:] = []
                    continue
                folder_raw = os.path.basename(root.rstrip(os.sep))
                # Parent-folder title — in Kometa asset_folders layouts the media
                # title lives on the folder, not the bare asset filename.
                folder_key = normalize_titles(folder_raw)
                for fname in files:
                    if not fname.lower().endswith(ASSET_IMAGE_EXTS):
                        continue
                    # Strip an asset-type tag (" - Logo"/"_Background"/…) so a
                    # flat "Title (Year)_logo.png" keys on the media title, not
                    # "titlelogo".
                    parsed = asset_type_regex.sub("", parse_asset_filename(fname))
                    parsed = parsed.strip(" -_")
                    key = normalize_titles(parsed)
                    if not key and not folder_key:
                        continue

                    fpath = os.path.join(root, fname)

                    # 0. Dead symlink — flag a link whose target is gone BEFORE
                    # the spare-only checks below, so a stale link is caught even
                    # when its title still matches. Tallied for the circuit-
                    # breaker; healthy links fall through to normal matching.
                    if os.path.islink(fpath):
                        total_links += 1
                        if not os.path.exists(fpath):  # exists() follows the link
                            dead_links.append(
                                {
                                    "path": fpath,
                                    "asset_dir": asset_dir,
                                    "parsed": parsed,
                                    "key": key,
                                    "size": 0,
                                    "reason": "dead_link",
                                }
                            )
                            continue

                    # 1. Ignore list — always spared.
                    if key in ignore_keys or folder_key in ignore_keys:
                        continue

                    # 2. ID match — extract the id from the RAW filename
                    # (preferred) or folder, before normalization strips it.
                    # A hit spares the file; a miss falls through to the title
                    # check (spare-only — never flags on an id miss alone).
                    names = (fname, folder_raw)
                    tmdb_id = _first_int_id(tmdb_id_regex, names)
                    if tmdb_id is not None and tmdb_id in tmdb_ids:
                        continue
                    tvdb_id = _first_int_id(tvdb_id_regex, names)
                    if tvdb_id is not None and tvdb_id in tvdb_ids:
                        continue

                    # 3. Title — filename- or folder-derived.
                    if key in library_titles or folder_key in library_titles:
                        continue

                    try:
                        size = os.path.getsize(fpath)
                    except OSError:
                        size = 0
                    orphans.append(
                        {
                            "path": fpath,
                            "asset_dir": asset_dir,
                            "parsed": parsed,
                            "key": key,
                            "size": size,
                        }
                    )

        # Fold in confirmed dead links — unless an implausibly large share of
        # links are broken, which means the target volume is likely unmounted
        # (not that the links are stale): skip the sweep to avoid mass deletion.
        if dead_links:
            breaker_tripped = (
                total_links >= DEAD_LINK_MIN_FOR_RATIO
                and len(dead_links) / total_links > DEAD_LINK_MAX_BROKEN_RATIO
            )
            if breaker_tripped:
                self.logger.warning(
                    f"Dead-symlink sweep skipped: {len(dead_links)}/{total_links} "
                    "links appear broken — likely an unmounted link target, not "
                    "stale assets. Check the source mount and re-run."
                )
            else:
                self.logger.info(
                    f"Dead-symlink sweep: {len(dead_links)} broken link(s) flagged."
                )
                orphans.extend(dead_links)
        return orphans

    def _execute_orphan_mode(
        self, orphans: List[Dict[str, Any]], mode: str, logger: Logger
    ) -> Dict[str, Any]:
        """Dispatch report/move/remove on the orphan-asset list."""
        count = 0
        total_size = 0
        touched_dirs: Set[str] = set()

        for item in orphans:
            path = item["path"]
            size = item["size"]
            if mode == "report":
                label = "DEAD LINK" if item.get("reason") == "dead_link" else "ORPHAN"
                logger.info(f"  [{label}] {path} (parsed='{item['parsed']}')")
                count += 1
                total_size += size
                continue

            if mode == "move":
                dest_root = os.path.join(item["asset_dir"], ORPHAN_RESTORE_DIR_NAME)
                rel = os.path.relpath(path, item["asset_dir"])
                dest = os.path.join(dest_root, rel)
                try:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.move(path, dest)
                    # Destructive ops stay at INFO deliberately — audit trail
                    # without debug mode (mirrors the bloat-cleanup pass).
                    logger.info(f"  [MOVED] {path} -> {dest}")
                    count += 1
                    total_size += size
                    touched_dirs.add(item["asset_dir"])
                except OSError as e:
                    logger.error(f"Failed to move {path}: {e}")
                continue

            if mode == "remove":
                try:
                    os.remove(path)
                    logger.info(f"  [REMOVED] {path}")
                    count += 1
                    total_size += size
                    touched_dirs.add(item["asset_dir"])
                except OSError as e:
                    logger.error(f"Failed to remove {path}: {e}")

        # Prune empty dirs left behind by move/remove.
        empty_dirs = sum(self._clean_empty_dirs(d) for d in touched_dirs)

        logger.info(
            f"   → orphan scan: {count} {mode}d"
            + (f", {empty_dirs} empty dir(s) pruned" if empty_dirs else "")
        )
        return {"count": count, "total_size": total_size, "mode": mode}

    # =========================================================================
    # Empty directory cleanup
    # =========================================================================

    def _clean_empty_dirs(self, base_dir: str) -> int:
        """Remove empty directories bottom-up."""
        count = 0
        for root, dirs, files in os.walk(base_dir, topdown=False):
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                        count += 1
                except OSError as e:
                    # Dir vanished, became non-empty, or permissions — skip,
                    # but leave a trace so the count discrepancy is explainable.
                    self.logger.debug(f"Could not remove empty dir {dir_path}: {e}")
        return count

    # =========================================================================
    # Reporting
    # =========================================================================

    def _build_output(
        self,
        bloat_stats: Dict[str, Any],
        orphan_stats: Dict[str, Any],
        empty_dirs: int,
        elapsed: float,
    ) -> Dict[str, Any]:
        """Build structured output for logging and notifications."""
        return {
            "mode": self.mode,
            "bloat": {
                "count": bloat_stats.get("count", 0),
                "size": bloat_stats.get("total_size", 0),
                "size_human": format_bytes(bloat_stats.get("total_size", 0)),
                "ignored_non_overlay": bloat_stats.get("ignored_non_overlay", 0),
            },
            "orphan": {
                "count": orphan_stats.get("count", 0),
                "size": orphan_stats.get("total_size", 0),
                "size_human": format_bytes(orphan_stats.get("total_size", 0)),
                "mode": orphan_stats.get("mode", ""),
            },
            "empty_dirs": empty_dirs,
            "elapsed": round(elapsed, 1),
        }

    def _print_report(self, output: Dict[str, Any]) -> None:
        """Print formatted summary report."""
        mode_label = MODE_LABELS.get(output["mode"], {}).get("ed", "Processed")

        summary_rows = [
            ["Category", "Count", "Space Recovered"],
            [
                f"Bloat Images ({mode_label})",
                str(output["bloat"]["count"]),
                output["bloat"]["size_human"],
            ],
        ]

        if output["orphan"]["count"] > 0 or output["orphan"].get("mode"):
            orphan_label = MODE_LABELS.get(
                output["orphan"].get("mode", "report"), {}
            ).get("ed", "Processed")
            summary_rows.append(
                [
                    f"Orphan Assets ({orphan_label})",
                    str(output["orphan"]["count"]),
                    output["orphan"]["size_human"],
                ]
            )

        if output["empty_dirs"] > 0:
            summary_rows.append(
                [
                    "Empty Directories",
                    str(output["empty_dirs"]),
                    "—",
                ]
            )

        ignored_non_overlay = output["bloat"].get("ignored_non_overlay", 0)
        if ignored_non_overlay:
            summary_rows.append(
                [
                    "Skipped (non-overlay)",
                    str(ignored_non_overlay),
                    "—",
                ]
            )

        self.logger.info(create_table(summary_rows))

        self.logger.info(f"\nCompleted in {output['elapsed']}s")


def run_orphan_assets_pass(
    db: ChubDB,
    instances: List[str],
    asset_dirs: List[str],
    mode: str,
    logger: Logger,
    include_collections: bool = True,
    ignore_titles: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Shared entry point used by poster_renamerr (and any future caller) to
    invoke the orphan-asset cleanup without spinning up a full PosterCleanarr
    instance. Reuses the same implementation by binding a minimal shim that
    exposes the helper methods.
    """
    cleanarr = PosterCleanarr.__new__(PosterCleanarr)
    cleanarr.logger = logger
    return cleanarr._run_orphan_pass(
        db=db,
        instances=instances,
        asset_dirs=asset_dirs,
        mode=mode,
        include_collections=include_collections,
        logger=logger,
        ignore_titles=ignore_titles,
    )
