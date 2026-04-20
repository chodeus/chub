# modules/poster_cleanarr.py

import glob
import os
import shutil
import sqlite3
import time
import zipfile
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from backend.util.base_module import ChubModule
from backend.util.database import ChubDB
from backend.util.helper import create_table
from backend.util.logger import Logger
from backend.util.notification import NotificationManager


def format_bytes(size: int) -> str:
    """Format byte count into human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"

VALID_MODES = {"report", "move", "remove", "restore", "clear", "nothing"}
RESTORE_DIR_NAME = "Poster Cleanarr Restore"
PLEX_DB_NAME = "com.plexapp.plugins.library.db"
DB_MAX_AGE_HOURS = 2

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

            metadata_dir = os.path.join(self.plex_path, "Metadata") if self.plex_path else ""
            restore_dir = os.path.join(self.plex_path, RESTORE_DIR_NAME) if self.plex_path else ""

            # Check restore dir conflict
            if self.mode in ("move", "remove", "report") and os.path.isdir(restore_dir):
                self.logger.error(
                    f"Cannot run in '{self.mode}' mode while '{RESTORE_DIR_NAME}' directory exists. "
                    f"Run in 'restore' mode to recover files or 'clear' mode to delete them first."
                )
                return

            # Banner
            label = MODE_LABELS.get(self.mode, {})
            table = [["Poster Cleanarr"], [f"Mode: {self.mode.capitalize()} — {label.get('ing', '')} bloat images"]]
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
                    self.logger.error("Failed to retrieve Plex database. Aborting image scan.")
                else:
                    # Query in-use images
                    db_start = time.time()
                    in_use = self._query_in_use_images(db_path)
                    db_elapsed = time.time() - db_start
                    self.logger.info(f"Found {len(in_use)} in-use images in Plex DB ({db_elapsed:.1f}s)")

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
                            b for b in bloat_list
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
                    bloat_stats = self._execute_mode(bloat_list, self.mode, metadata_dir, restore_dir)

            elif self.mode == "restore":
                bloat_stats = self._execute_restore(restore_dir, metadata_dir)

            elif self.mode == "clear":
                bloat_stats = self._execute_clear(restore_dir)

            # === CHUB orphaned poster cleanup ===
            with ChubDB(logger=self.logger) as db:
                orphaned_stats = self._clean_chub_orphaned(
                    db, self.mode in ("report", "nothing")
                )

            # PhotoTranscoder + server maintenance (empty_trash / clean_bundles
            # / optimize_db) live in the plex_maintenance module now. Keep
            # empty stats here so the existing report shape is preserved.
            transcoder_stats = {"count": 0, "total_size": 0}
            maintenance_results: Dict[str, Any] = {}

            # === Clean empty directories ===
            empty_dirs = 0
            if self.mode not in ("report", "nothing") and metadata_dir:
                empty_dirs = self._clean_empty_dirs(metadata_dir)

            # === Report ===
            elapsed = time.time() - start_time
            output = self._build_output(
                bloat_stats, orphaned_stats, transcoder_stats,
                maintenance_results, empty_dirs, elapsed
            )
            self._print_report(output)

            # === Notify ===
            has_activity = (
                bloat_stats.get("count", 0) > 0
                or orphaned_stats.get("count", 0) > 0
            )
            if has_activity:
                try:
                    manager = NotificationManager(
                        self.config, self.logger, module_name="poster_cleanarr"
                    )
                    manager.send_notification(output)
                except Exception as e:
                    self.logger.error(f"Failed to send notification: {e}")

        except KeyboardInterrupt:
            print("Keyboard Interrupt detected. Exiting...")
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
            self.logger.error("plex_path is not configured. Set it in poster_cleanarr config.")
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
        """Get a PlexServer connection using CHUB instance config with retry logic."""
        from plexapi.server import PlexServer

        instances = self.config.instances
        plex_instances = self.full_config.instances.plex

        if not instances:
            # UX fallback: if the user only has one Plex instance configured
            # globally, auto-select it. Users commonly assume the global
            # instance covers this module too because the scan already works
            # off `plex_path` from disk. Only fall back when there's no
            # ambiguity — if multiple instances exist, still require an
            # explicit choice so we don't guess wrong.
            if len(plex_instances) == 1:
                instance_name = next(iter(plex_instances))
                self.logger.info(
                    f"No 'instances' configured for poster_cleanarr; "
                    f"auto-selecting the single configured Plex instance "
                    f"'{instance_name}'."
                )
            else:
                self.logger.error(
                    "No Plex instances configured for poster_cleanarr. "
                    "Add instance names to the 'instances' list in config "
                    f"(available: {sorted(plex_instances) or 'none'})."
                )
                return None
        else:
            instance_name = instances[0]

        if instance_name not in plex_instances:
            self.logger.error(f"Plex instance '{instance_name}' not found in CHUB instances config.")
            return None

        instance_detail = plex_instances[instance_name]
        url = instance_detail.url
        token = instance_detail.api
        timeout = self.config.timeout

        if not url or not token:
            self.logger.error(
                f"Plex instance '{instance_name}' is missing url or api token."
            )
            return None

        max_retries = 5
        backoff = 60

        for attempt in range(1, max_retries + 1):
            try:
                self.logger.info(
                    f"Connecting to Plex '{instance_name}' at {url} (attempt {attempt}/{max_retries})..."
                )
                server = PlexServer(url, token, timeout=timeout)
                _ = server.version
                self.logger.info(f"Connected to Plex server v{server.version}")
                return server
            except Exception as e:
                err_msg = str(e).lower()
                if "unauthorized" in err_msg or "401" in err_msg:
                    self.logger.error(f"Authentication failed for Plex '{instance_name}'. Check your API token.")
                    return None
                if attempt < max_retries:
                    wait = backoff * attempt
                    self.logger.warning(
                        f"Plex connection failed: {e}. Retrying in {wait}s..."
                    )
                    time.sleep(wait)
                else:
                    self.logger.error(f"Failed to connect to Plex after {max_retries} attempts: {e}")
                    return None

        return None

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
            response = requests.get(url, headers=headers, stream=True, timeout=self.config.timeout)
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
                        n for n in zf.namelist()
                        if "com.plexapp.plugins.library.db" in n
                        or n.startswith("databaseBackup")
                    ]
                    if db_files:
                        # Validate extracted path stays within temp_dir (zip traversal protection)
                        target_path = os.path.realpath(os.path.join(temp_dir, db_files[0]))
                        if not target_path.startswith(os.path.realpath(temp_dir) + os.sep):
                            self.logger.error(f"Zip path traversal detected: {db_files[0]}")
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
        """Query Plex database for in-use image filenames."""
        in_use: Set[str] = set()

        try:
            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.cursor()

                for column in ("user_thumb_url", "user_art_url", "user_banner_url"):
                    query = (
                        f"SELECT {column} FROM metadata_items "
                        f"WHERE {column} LIKE 'upload://%' OR {column} LIKE 'metadata://%'"
                    )
                    try:
                        cursor.execute(query)
                        for (url_value,) in cursor.fetchall():
                            if url_value:
                                parsed = urlparse(url_value)
                                filename = parsed.path.split("/")[-1] if parsed.path else ""
                                if filename:
                                    in_use.add(filename)
                    except sqlite3.OperationalError as e:
                        self.logger.warning(f"Failed to query {column}: {e}")
            finally:
                conn.close()
        except Exception as e:
            self.logger.error(f"Failed to query Plex database: {e}")

        return in_use

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

        if not bloat_list:
            self.logger.info("No bloat images found. Plex metadata is clean!")
            return {"count": 0, "total_size": 0, "mode": mode}

        self.logger.info(f"{label.get('ing', 'Processing')} {len(bloat_list)} bloat images...")

        for item in bloat_list:
            if self.is_cancelled():
                break

            filepath = item["path"]
            size = item["size"]

            if mode == "report":
                self.logger.info(f"  [REPORT] {filepath} ({format_bytes(size)})")
                count += 1
                total_size += size

            elif mode == "move":
                try:
                    self._move_file(filepath, metadata_dir, restore_dir)
                    # Log per-file so the Logs tab shows a full audit trail of
                    # what was touched — matches ImageMaid's MOVE: <path> output.
                    self.logger.info(f"  [MOVE] {filepath} ({format_bytes(size)})")
                    count += 1
                    total_size += size
                except Exception as e:
                    self.logger.error(f"Failed to move {filepath}: {e}")

            elif mode == "remove":
                try:
                    os.remove(filepath)
                    self.logger.info(f"  [REMOVE] {filepath} ({format_bytes(size)})")
                    count += 1
                    total_size += size
                except Exception as e:
                    self.logger.error(f"Failed to remove {filepath}: {e}")

        self.logger.info(
            f"{label.get('ed', 'Processed')} {count} bloat images ({format_bytes(total_size)})"
        )
        return {"count": count, "total_size": total_size, "mode": mode}

    def _execute_restore(self, restore_dir: str, metadata_dir: str) -> Dict[str, Any]:
        """Restore previously moved files from restore directory."""
        if not os.path.isdir(restore_dir):
            self.logger.info(f"No '{RESTORE_DIR_NAME}' directory found. Nothing to restore.")
            return {"count": 0, "total_size": 0, "mode": "restore"}

        count = 0
        total_size = 0
        restore_files = list(glob.iglob(os.path.join(restore_dir, "**", "*.jpg"), recursive=True))

        if not restore_files:
            self.logger.info("Restore directory is empty. Nothing to restore.")
            return {"count": 0, "total_size": 0, "mode": "restore"}

        self.logger.info(f"Restoring {len(restore_files)} files...")

        failed = 0
        for filepath in restore_files:
            try:
                size = os.path.getsize(filepath)
                self._restore_file(filepath, restore_dir, metadata_dir)
                self.logger.info(f"  [RESTORE] {filepath} ({format_bytes(size)})")
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
            self.logger.info(f"No '{RESTORE_DIR_NAME}' directory found. Nothing to clear.")
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
    # CHUB orphaned poster cleanup
    # =========================================================================

    def _clean_chub_orphaned(self, db: ChubDB, dry_run: bool) -> Dict[str, Any]:
        """Clean orphaned posters tracked by CHUB."""
        orphaned = db.orphaned.list_orphaned_posters()
        count = len(orphaned)

        if count == 0:
            self.logger.info("No CHUB orphaned posters found.")
            return {"count": 0}

        self.logger.info(f"Found {count} CHUB orphaned posters.")
        pr_cfg = getattr(self.full_config, "poster_renamerr", None)
        allowed_roots = []
        if pr_cfg is not None:
            allowed_roots = [
                r for r in (
                    [getattr(pr_cfg, "destination_dir", "")]
                    + list(getattr(pr_cfg, "source_dirs", []) or [])
                ) if r
            ]
        db.orphaned.handle_orphaned_posters(
            self.logger, dry_run, allowed_roots=allowed_roots
        )
        return {"count": count}

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
                except OSError:  # noqa: S110 -- skip dirs that vanished or are non-empty
                    pass
        return count

    # =========================================================================
    # Reporting
    # =========================================================================

    def _build_output(
        self,
        bloat_stats: Dict[str, Any],
        orphaned_stats: Dict[str, Any],
        transcoder_stats: Dict[str, Any],
        maintenance_results: Dict[str, Any],
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
            },
            "orphaned": {
                "count": orphaned_stats.get("count", 0),
            },
            "photo_transcoder": {
                "count": transcoder_stats.get("count", 0),
                "size": transcoder_stats.get("total_size", 0),
                "size_human": format_bytes(transcoder_stats.get("total_size", 0)),
            },
            "maintenance": maintenance_results,
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
            [
                "CHUB Orphaned Posters",
                str(output["orphaned"]["count"]),
                "—",
            ],
        ]

        if self.config.photo_transcoder:
            summary_rows.append([
                "PhotoTranscoder Cache",
                str(output["photo_transcoder"]["count"]),
                output["photo_transcoder"]["size_human"],
            ])

        if output["empty_dirs"] > 0:
            summary_rows.append([
                "Empty Directories",
                str(output["empty_dirs"]),
                "—",
            ])

        self.logger.info(create_table(summary_rows))

        # Maintenance results
        if output["maintenance"]:
            self.logger.info("Plex Maintenance:")
            for task_name, status in output["maintenance"].items():
                icon = "✅" if status == "success" else "❌"
                self.logger.info(f"  {icon} {task_name}: {status}")

        self.logger.info(f"\nCompleted in {output['elapsed']}s")
