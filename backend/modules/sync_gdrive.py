# modules/sync_gdrive.py

import json
import os
import re
import shlex
import subprocess
import time
from shutil import which
from typing import List, Optional

from backend.util.base_module import ChubModule
from backend.util.database import ChubDB
from backend.util.helper import print_settings
from backend.util.logger import Logger
from backend.util.notification import NotificationManager

try:
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass


class SyncGDrive(ChubModule):
    def __init__(self, logger: Optional[Logger] = None) -> None:
        super().__init__(logger=logger)
        self.rclone_path = self.get_rclone_path()
        self.db = None
        # Track current job ID for progress updates
        self.current_job_id = None

    def set_job_id(self, job_id):
        """Set the current job ID for progress tracking"""
        self.current_job_id = job_id

    def parse_rclone_progress(self, line):
        """
        Extract percent progress from rclone --stats output line.
        Returns integer percent or None.
        """
        # Typical: Transferred:    1.234 GiB / 8.000 GiB, 15%, 1.23 MiB/s, ETA 01:36:20
        match = re.search(
            r"Transferred:.*?([\d.]+\s\w+) / ([\d.]+\s\w+),\s*(\d+)%", line
        )
        if match:
            return int(match.group(3))
        # Alternate: Transferred:  14 / 100, 14%
        match2 = re.search(r"Transferred:\s+\d+ / \d+,\s*(\d+)%", line)
        if match2:
            return int(match2.group(1))
        return None

    def get_rclone_path(self) -> str:
        env_path = os.getenv("RCLONE_PATH")
        if env_path:
            if os.path.isfile(env_path) and os.access(env_path, os.X_OK):
                return env_path
            else:
                raise FileNotFoundError(
                    f"RCLONE_PATH is set to '{env_path}', but it is not an executable file."
                )
        rclone_path = which("rclone")
        if rclone_path is None:
            raise FileNotFoundError(
                "rclone binary not found in PATH. Ensure it is installed and accessible, or set RCLONE_PATH."
            )
        return rclone_path

    def ensure_remote(self):
        """Ensure the rclone remote 'posters' exists by creating it if missing."""
        try:
            self.logger.debug("Ensuring rclone remote 'posters' exists")
            subprocess.run(
                [
                    self.rclone_path,
                    "config",
                    "create",
                    "posters",
                    "drive",
                    "config_is_local=false",
                ],
                check=False,
            )
        except Exception as e:
            self.logger.error(f"Error ensuring rclone remote 'posters' exists: {e}")

    @staticmethod
    def _reject_unsafe_arg(value: str, field_name: str, logger) -> bool:
        """
        Block CLI-option smuggling and null bytes on values passed to
        rclone. List-form subprocess doesn't invoke a shell, but a value
        starting with '-' would still be parsed by rclone as a flag.
        """
        if not isinstance(value, str) or "\x00" in value or value.startswith("-"):
            logger.error(f"Refusing unsafe {field_name} value: {value!r}")
            return False
        return True

    def sync_folder(self, sync_location, sync_id, progress_cb=lambda pct: None):
        """Run rclone sync for a single folder. Returns True on success, False on failure."""
        if not sync_location or not sync_id:
            self.logger.error("Sync location or GDrive folder ID not provided.")
            progress_cb(100)
            return False

        if not self._reject_unsafe_arg(sync_location, "sync_location", self.logger):
            progress_cb(100)
            return False
        if not self._reject_unsafe_arg(sync_id, "gdrive_id", self.logger):
            progress_cb(100)
            return False

        try:
            os.makedirs(sync_location, exist_ok=True)
            self.logger.info(f"Ensured sync location exists: {sync_location}")
        except OSError as e:
            self.logger.error(f"Could not create sync location '{sync_location}': {e}")
            progress_cb(100)
            return False

        # Starting sync
        progress_cb(10)
        # FIXED: Direct call to update_progress, no redundant wrapper
        if self.current_job_id and self.db:
            try:
                self.db.worker.update_progress("jobs", self.current_job_id, 10)
            except Exception as e:
                self.logger.debug(f"Failed to update progress: {e}")

        last_pct = [10]

        def guarded_progress_cb(pct):
            if pct > last_pct[0]:
                progress_cb(pct)
                # FIXED: Direct call to update_progress, no redundant wrapper
                if self.current_job_id and self.db:
                    try:
                        self.db.worker.update_progress("jobs", self.current_job_id, pct)
                    except Exception as e:
                        self.logger.debug(f"Failed to update progress: {e}")
                last_pct[0] = pct

        cmd = [
            self.rclone_path,
            "sync",
            "--drive-root-folder-id",
            sync_id,
            "--fast-list",
            "--tpslimit=5",
            "--no-update-modtime",
            "--drive-use-trash=false",
            "--drive-chunk-size=512M",
            "--exclude=**.partial",
            "--check-first",
            "--bwlimit=80M",
            "--size-only",
            "--delete-after",
            "-v",
            "--stats=1s",
        ]

        # Respect dry_run config — rclone will show what would change without doing it
        if self.config.dry_run:
            cmd.append("--dry-run")
            self.logger.info("[Dry Run] Rclone will report changes without applying them")

        # Use service account if configured, otherwise use OAuth token
        sa_path = getattr(self.config, "gdrive_sa_location", None)
        if sa_path:
            if not self._reject_unsafe_arg(sa_path, "gdrive_sa_location", self.logger):
                progress_cb(100)
                return False
            cmd.extend(["--drive-service-account-file", sa_path])
        else:
            cmd.extend([
                "--drive-client-id",
                self.config.client_id or "",
                "--drive-client-secret",
                self.config.client_secret or "",
                "--drive-token",
                (
                    self.config.token
                    if isinstance(self.config.token, str)
                    else json.dumps(
                        self.config.token.model_dump()
                        if hasattr(self.config.token, "model_dump")
                        else dict(self.config.token)
                    )
                )
                if self.config.token
                else "",
            ])

        cmd.extend(["posters:", sync_location])

        try:
            self.logger.debug("Running rclone command:")
            self.logger.debug("\n" + " \\\n    ".join(shlex.quote(arg) for arg in cmd))
            if self.is_cancelled():
                self.logger.info("Sync cancelled before starting rclone.")
                progress_cb(100)
                return False

            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            for line in process.stdout:
                if self.is_cancelled():
                    process.terminate()
                    self.logger.info("Sync cancelled during rclone execution.")
                    return False
                cleaned_line = re.sub(
                    r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} (INFO|ERROR|DEBUG) *:?",
                    "",
                    line,
                ).strip()
                if cleaned_line:
                    self.logger.info(cleaned_line)
                    pct = self.parse_rclone_progress(cleaned_line)
                    if pct is not None:
                        guarded_progress_cb(pct)
            process.wait()
            if process.returncode == 0:
                self.logger.info("✅ RClone sync completed successfully.")
                guarded_progress_cb(95)
                return True
            else:
                self.logger.error(
                    f"❌ RClone sync failed with return code {process.returncode}"
                )
                progress_cb(100)
                if self.current_job_id and self.db:
                    try:
                        self.db.worker.update_progress("jobs", self.current_job_id, 100)
                    except Exception as e:
                        self.logger.debug(f"Failed to update progress: {e}")
                return False
        except Exception as e:
            self.logger.error(f"Exception occurred while running rclone: {e}")
            progress_cb(100)
            if self.current_job_id and self.db:
                try:
                    self.db.worker.update_progress("jobs", self.current_job_id, 100)
                except Exception as e:
                    self.logger.debug(f"Failed to update progress: {e}")
            return False

    def gather_folder_stats(self, folder_path):
        """
        Returns (file_count, size_bytes, last_updated) for all files under folder_path.
        last_updated is the most recent mtime (as ISO string), or '' if no files.
        """
        file_count = 0
        size_bytes = 0
        latest_mtime = 0
        for root, dirs, files in os.walk(folder_path):
            for fname in files:
                try:
                    fpath = os.path.join(root, fname)
                    stat = os.stat(fpath)
                    file_count += 1
                    size_bytes += stat.st_size
                    if stat.st_mtime > latest_mtime:
                        latest_mtime = stat.st_mtime
                except Exception:
                    continue
        last_updated = (
            time.strftime("%Y%m%d", time.localtime(latest_mtime))
            if latest_mtime
            else ""
        )
        return file_count, size_bytes, last_updated

    def refresh_all_poster_stats(self):
        """
        Gather stats and upsert for all gdrive entries in config.gdrive_list.
        """
        # Use quiet mode for stats gathering
        with ChubDB(logger=self.logger, quiet=True) as db:
            sync_list = (
                self.config.gdrive_list
                if isinstance(self.config.gdrive_list, list)
                else [self.config.gdrive_list]
            )
            for sync_item in sync_list:
                owner = sync_item.name
                sync_location = sync_item.location
                file_count, size_bytes, last_updated = self.gather_folder_stats(
                    sync_location
                )
                db.stats.upsert_gdrive_stat(
                    location=sync_location,
                    folder_name=owner,
                    owner=owner,
                    file_count=file_count,
                    size_bytes=size_bytes,
                    last_updated=last_updated,
                )
                self.logger.debug(
                    f"Updated gdrive_stats for {sync_location}: "
                    f"{file_count} files, {size_bytes} bytes, last updated {last_updated}"
                )

    def sync_folder_adhoc(
        self, gdrive_name: str, progress_cb=lambda pct: None, job_id=None
    ):
        """
        Sync a single GDrive folder (by its config 'name') on demand.

        Args:
            gdrive_name: Name of the GDrive folder to sync
            progress_cb: Progress callback function
            job_id: Job ID for progress tracking

        Returns:
            bool: Success status
        """
        try:
            # Set job ID for progress tracking
            if job_id:
                self.set_job_id(job_id)

            with ChubDB(logger=self.logger) as self.db:
                sync_list = (
                    self.config.gdrive_list
                    if isinstance(self.config.gdrive_list, list)
                    else [self.config.gdrive_list]
                )
                for sync_item in sync_list:
                    owner = sync_item.name
                    if owner == gdrive_name:
                        sync_location = sync_item.location
                        sync_id = sync_item.id

                        progress_cb(5)  # Starting ad-hoc sync
                        if self.current_job_id and self.db:
                            try:
                                self.db.worker.update_progress(
                                    "jobs", self.current_job_id, 5
                                )
                            except Exception as e:
                                self.logger.debug(f"Failed to update progress: {e}")

                        sync_ok = self.sync_folder(
                            sync_location, sync_id, progress_cb=progress_cb
                        )

                        # GATHER STATS AND UPSERT
                        progress_cb(90)
                        if self.current_job_id and self.db:
                            try:
                                self.db.worker.update_progress(
                                    "jobs", self.current_job_id, 90
                                )
                            except Exception as e:
                                self.logger.debug(f"Failed to update progress: {e}")

                        file_count, size_bytes, last_updated = self.gather_folder_stats(
                            sync_location
                        )
                        self.db.stats.upsert_gdrive_stat(
                            location=sync_location,
                            folder_name=owner,
                            owner=owner,
                            file_count=file_count,
                            size_bytes=size_bytes,
                            last_updated=last_updated,
                        )
                        self.logger.info(
                            f"Synced and updated gdrive_stats for {sync_location}: "
                            f"{file_count} files, {size_bytes} bytes, last updated {last_updated}"
                        )
                        progress_cb(100)
                        if self.current_job_id and self.db:
                            try:
                                self.db.worker.update_progress(
                                    "jobs", self.current_job_id, 100
                                )
                            except Exception as e:
                                self.logger.debug(f"Failed to update progress: {e}")
                        return sync_ok
                self.logger.error(
                    f"GDrive name '{gdrive_name}' not found in config.gdrive_list."
                )
                progress_cb(100)
                if self.current_job_id and self.db:
                    try:
                        self.db.worker.update_progress("jobs", self.current_job_id, 100)
                    except Exception as e:
                        self.logger.debug(f"Failed to update progress: {e}")
                return False
        except KeyboardInterrupt:
            print("Keyboard Interrupt detected. Exiting...")
            return
        except Exception as exc:
            self.logger.error(f"\n\nAn error occurred: {exc}\n", exc_info=True)
            progress_cb(100)
            if self.current_job_id and self.db:
                try:
                    self.db.worker.update_progress("jobs", self.current_job_id, 100)
                except Exception as e:
                    self.logger.debug(f"Failed to update progress: {e}")
            return False

    def run(self, progress_cb=lambda pct: None):
        start_time = time.time()
        try:
            with ChubDB(logger=self.logger) as self.db:
                if self.config.log_level.lower() == "debug":
                    print_settings(self.logger, self.config)

                if self.config.dry_run:
                    from backend.util.helper import create_table
                    table = [["Dry Run"], ["NO FILES WILL BE MODIFIED"]]
                    self.logger.info(create_table(table))

                sync_list: List[dict] = (
                    self.config.gdrive_list
                    if isinstance(self.config.gdrive_list, list)
                    else [self.config.gdrive_list]
                )

                if getattr(
                    self.config, "gdrive_sa_location", None
                ) and not os.path.isfile(self.config.gdrive_sa_location):
                    self.logger.warning(
                        f"\nGoogle service account file '{self.config.gdrive_sa_location}' does not exist\n"
                        "Please verify the path or remove it from config\n"
                    )
                    self.config.gdrive_sa_location = None

                self.ensure_remote()
                total = len(sync_list)
                failed_count = 0
                synced_items = []  # captured for the notification payload

                for idx, sync_item in enumerate(sync_list, 1):
                    if self.is_cancelled():
                        self.logger.info("Cancellation requested, stopping sync_gdrive.")
                        break
                    progress_pct = int(10 + 80 * (idx - 1) / total)
                    progress_cb(progress_pct)  # Start for each
                    if self.current_job_id and self.db:
                        try:
                            self.db.worker.update_progress(
                                "jobs", self.current_job_id, progress_pct
                            )
                        except Exception as e:
                            self.logger.debug(f"Failed to update progress: {e}")

                    sync_location = sync_item.location
                    sync_id = sync_item.id
                    success = self.sync_folder(sync_location, sync_id, progress_cb=progress_cb)
                    if not success:
                        failed_count += 1

                    # GATHER STATS AND UPSERT
                    progress_pct = int(10 + 80 * (idx - 0.5) / total)
                    progress_cb(progress_pct)
                    if self.current_job_id and self.db:
                        try:
                            self.db.worker.update_progress(
                                "jobs", self.current_job_id, progress_pct
                            )
                        except Exception as e:
                            self.logger.debug(f"Failed to update progress: {e}")

                    file_count, size_bytes, last_updated = self.gather_folder_stats(
                        sync_location
                    )
                    owner = sync_item.name
                    self.db.stats.upsert_gdrive_stat(
                        location=sync_location,
                        folder_name=owner,
                        owner=owner,
                        file_count=file_count,
                        size_bytes=size_bytes,
                        last_updated=last_updated,
                    )
                    self.logger.info(
                        f"Updated gdrive_stats for {sync_location}: {file_count} files, {size_bytes} bytes, last updated {last_updated}"
                    )
                    synced_items.append({
                        "location": sync_location,
                        "owner": owner,
                        "file_count": file_count,
                        "size_bytes": size_bytes,
                        "success": success,
                    })

                    progress_pct = int(10 + 80 * idx / total)
                    progress_cb(progress_pct)  # Step up after folder done
                    if self.current_job_id and self.db:
                        try:
                            self.db.worker.update_progress(
                                "jobs", self.current_job_id, progress_pct
                            )
                        except Exception as e:
                            self.logger.debug(f"Failed to update progress: {e}")

                progress_cb(100)
                if self.current_job_id and self.db:
                    try:
                        self.db.worker.update_progress("jobs", self.current_job_id, 100)
                    except Exception as e:
                        self.logger.debug(f"Failed to update progress: {e}")

                # Notify — skipped on dry-run, empty lists (nothing to say),
                # and when the user has no sources configured.
                if (
                    not getattr(self.config, "dry_run", False)
                    and total > 0
                    and synced_items
                ):
                    try:
                        manager = NotificationManager(
                            self.config, self.logger, module_name="sync_gdrive"
                        )
                        manager.send_notification({
                            "total": total,
                            "succeeded": total - failed_count,
                            "failed": failed_count,
                            "elapsed": f"{time.time() - start_time:.1f}s",
                            "items": synced_items,
                        })
                    except Exception as e:
                        self.logger.debug(f"sync_gdrive notification failed: {e}")

                if failed_count > 0:
                    msg = f"GDrive sync failed for {failed_count}/{total} folders"
                    self.logger.error(msg)
                    raise RuntimeError(msg)
        except KeyboardInterrupt:
            print("Keyboard Interrupt detected. Exiting...")
            return
        except Exception as exc:
            self.logger.error(f"\n\nAn error occurred: {exc}\n", exc_info=True)
            progress_cb(100)
            if self.current_job_id and self.db:
                try:
                    self.db.worker.update_progress("jobs", self.current_job_id, 100)
                except Exception as e:
                    self.logger.debug(f"Failed to update progress: {e}")
