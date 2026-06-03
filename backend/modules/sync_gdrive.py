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
    # python-dotenv is optional; running without it just means env vars
    # aren't auto-populated from a .env file.
    pass


# rclone stdout progress/stats lines — pure repetitive noise. Always
# routed through logger.heartbeat() regardless of verbose so they never
# flood the default log view.
_RCLONE_HEARTBEAT_PATTERN = re.compile(
    r"^("
    r"Transferred:"  # progress heartbeat (fires every --stats interval)
    r"|Checks:"  # check-phase heartbeat
    r"|Elapsed time:"  # progress heartbeat
    r")"
)

# rclone per-file action / per-directory cleanup lines. These carry
# actionable information (which file was deleted/copied/etc) so users
# can opt into surfacing them by enabling sync_gdrive.verbose — they go
# to logger.info(). Off by default they route to heartbeat so default
# log views stay readable on large syncs.
_RCLONE_FILE_ACTION_PATTERN = re.compile(
    r"^("
    r".*: (Deleted|Copied|Updated|Renamed|Removed|Skipped)\b"
    r"|.*: Removing( empty)? directory"
    r")"
)

# Per-file action lines we count for the sync notification: which files
# actually moved on disk this run. "Removed" is collapsed into "deleted"
# since rclone uses both depending on version/operation. "Skipped" is
# intentionally not counted — it represents files that were already in
# sync and would inflate the summary without conveying activity.
_RCLONE_ACTION_PATTERN = re.compile(r": (Copied|Deleted|Updated|Renamed|Removed)\b")


def _empty_counters() -> dict:
    """Zeroed delta counter dict used as the sync_folder default return."""
    return {"copied": 0, "deleted": 0, "updated": 0, "renamed": 0}


def _rclone_line_level(
    line: str, rclone_level: str, *, verbose: bool
) -> str:
    """
    Decide which logger method should emit an rclone output line.

    Returns one of: ``"error"``, ``"heartbeat"``, ``"info"``.

    Rules (kept in one place so the verbose / heartbeat contract is testable):
    - rclone-reported ERROR lines always go to error().
    - rclone --stats progress lines (Transferred:/Checks:/Elapsed time:)
      always go to heartbeat(), regardless of verbose.
    - rclone per-file action lines ("X: Copied (new)", "X: Deleted", etc.)
      go to info() when ``verbose`` is True, heartbeat() otherwise. This is
      what the user opts into via ``sync_gdrive.verbose: true``.
    - Anything else (one-off setup / completion lines) goes to info().
    """
    if rclone_level == "ERROR":
        return "error"
    if _RCLONE_HEARTBEAT_PATTERN.match(line):
        return "heartbeat"
    if _RCLONE_FILE_ACTION_PATTERN.match(line):
        return "info" if verbose else "heartbeat"
    return "info"


def _format_counter_summary(counters: dict) -> str:
    """
    One-line user-facing summary of rclone action counters.

    Returns a comma-joined "N action" list with zero-count actions
    elided, or "already in sync, no changes" when nothing moved.

    Extracted so the post-sync summary log can be tested without
    spinning up the rclone subprocess.
    """
    if not counters or not any(counters.values()):
        return "already in sync, no changes"
    return ", ".join(
        f"{n} {action}" for action, n in sorted(counters.items()) if n
    )


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
        """Run rclone sync for a single folder.

        Returns (success, counters) where counters is a dict with
        {copied, deleted, updated, renamed} parsed from rclone's per-file
        action lines. Empty counters dict accompanies all failure paths
        so the caller can unpack without conditionals.
        """
        counters = _empty_counters()

        if not sync_location or not sync_id:
            self.logger.error("Sync location or GDrive folder ID not provided.")
            progress_cb(100)
            return False, counters

        if not self._reject_unsafe_arg(sync_location, "sync_location", self.logger):
            progress_cb(100)
            return False, counters
        if not self._reject_unsafe_arg(sync_id, "gdrive_id", self.logger):
            progress_cb(100)
            return False, counters

        try:
            os.makedirs(sync_location, exist_ok=True)
            self.logger.info(f"Ensured sync location exists: {sync_location}")
        except OSError as e:
            self.logger.error(f"Could not create sync location '{sync_location}': {e}")
            progress_cb(100)
            return False, counters

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
            self.logger.info(
                "[Dry Run] Rclone will report changes without applying them"
            )

        # Use service account if configured, otherwise use OAuth token
        sa_path = getattr(self.config, "gdrive_sa_location", None)
        if sa_path:
            if not self._reject_unsafe_arg(sa_path, "gdrive_sa_location", self.logger):
                progress_cb(100)
                return False, counters
            cmd.extend(["--drive-service-account-file", sa_path])
        else:
            cmd.extend(
                [
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
                ]
            )

        cmd.extend(["posters:", sync_location])

        try:
            self.logger.debug("Running rclone command:")
            self.logger.debug("\n" + " \\\n    ".join(shlex.quote(arg) for arg in cmd))
            if self.is_cancelled():
                self.logger.info("Sync cancelled before starting rclone.")
                progress_cb(100)
                return False, counters

            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            for line in process.stdout:
                if self.is_cancelled():
                    process.terminate()
                    self.logger.info("Sync cancelled during rclone execution.")
                    return False, counters
                level_match = re.match(
                    r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} (INFO|ERROR|DEBUG) *:?",
                    line,
                )
                rclone_level = level_match.group(1) if level_match else "INFO"
                cleaned_line = re.sub(
                    r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} (INFO|ERROR|DEBUG) *:?",
                    "",
                    line,
                ).strip()
                if cleaned_line:
                    # Routing contract lives in _rclone_line_level() so the
                    # verbose / heartbeat behaviour is testable in isolation.
                    level = _rclone_line_level(
                        cleaned_line,
                        rclone_level,
                        verbose=getattr(self.config, "verbose", False),
                    )
                    getattr(self.logger, level)(cleaned_line)
                    # Count actual per-file activity for the notification
                    # summary. "Removed" is normalized to "deleted" since
                    # rclone uses both labels depending on operation and
                    # version. Skipped/no-op lines aren't counted — they
                    # represent files already in sync.
                    action_match = _RCLONE_ACTION_PATTERN.search(cleaned_line)
                    if action_match:
                        action = action_match.group(1).lower()
                        if action == "removed":
                            action = "deleted"
                        counters[action] = counters.get(action, 0) + 1
                    pct = self.parse_rclone_progress(cleaned_line)
                    if pct is not None:
                        guarded_progress_cb(pct)
            process.wait()
            if process.returncode == 0:
                self.logger.info("✅ RClone sync completed successfully.")
                # Per-folder action summary — visible even when verbose is off,
                # so users can see "this run did X copies and Y deletes"
                # without scrolling through the rclone per-file noise.
                self.logger.info(f"   → {_format_counter_summary(counters)}")
                guarded_progress_cb(95)
                return True, counters
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
                return False, counters
        except Exception as e:
            self.logger.error(f"Exception occurred while running rclone: {e}")
            progress_cb(100)
            if self.current_job_id and self.db:
                try:
                    self.db.worker.update_progress("jobs", self.current_job_id, 100)
                except Exception as e:
                    self.logger.debug(f"Failed to update progress: {e}")
            return False, counters

    def _refresh_poster_cache_for_folder(self, sync_location: str) -> None:
        """Re-index a single source-dir's slice of poster_cache after rclone.

        Triggered at the end of an ad-hoc per-folder sync so Assets Search
        reflects the on-disk state immediately, without waiting for the
        next scheduled poster_renamerr run. Scoped to this folder's path
        prefix — other contributors' rows are untouched.

        A folder that's a renamer source_dir is re-indexed as before — its
        priority looked up from poster_renamerr.source_dirs so the per-folder
        refresh preserves the bottom-wins source_dir contract (see
        poster_cache.py CONTRACT block). A gdrive_list folder OUTSIDE every
        source_dir is indexed across all image types as search_only=1:
        findable in Assets Search but excluded from poster matching.
        """
        if not self.db:
            return
        try:
            # Reuse poster_renamerr's parser/classifier so per-folder
            # refresh and the full merge produce byte-identical records.
            from backend.modules.poster_renamerr import PosterRenamerr

            pr = PosterRenamerr(logger=self.logger)

            # Is this folder owned by a renamer source_dir (poster_renamerr or
            # asset_renamerr)? Owned folders are matchable; a gdrive_list folder
            # outside every source_dir (e.g. an "Extras" drive) is search-only.
            owned = pr._matchable_source_dirs()
            target = os.path.realpath(sync_location).rstrip("/")
            is_owned = any(
                target == sd or target.startswith(sd + os.sep) for sd in owned
            )

            if is_owned:
                # Existing behaviour: matchable row, priority from the matching
                # source_dir (bottom-wins contract); assets gated on the feature.
                priority = 0
                for idx, sd in enumerate(getattr(pr.config, "source_dirs", []) or []):
                    if os.path.realpath(sd).rstrip("/") == target:
                        priority = idx
                        break
                assets = pr._get_assets_files(
                    sync_location,
                    priority=priority,
                    include_assets=getattr(pr.config, "run_asset_renamerr", False),
                )
            else:
                # gdrive-only folder: index ALL image types as search-only so
                # Assets Search shows them without making them match candidates.
                assets = pr._get_assets_files(
                    sync_location,
                    priority=0,
                    include_assets=True,
                    search_only=1,
                )

            self.db.poster.delete_by_path_prefix(sync_location)
            for asset in assets:
                self.db.poster.upsert(asset)
            self.logger.info(
                f"Refreshed poster_cache for {sync_location}: {len(assets)} rows (priority={priority})"
            )
        except Exception as e:
            # Cache refresh is a best-effort follow-up to the sync; a
            # failure here mustn't fail the sync job itself.
            self.logger.error(
                f"Failed to refresh poster_cache for {sync_location}: {e}"
            )

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

    def run(
        self,
        progress_cb=lambda pct: None,
        only_folders: Optional[List[str]] = None,
        notify: bool = True,
    ):
        """Sync configured gdrive folders to local disk.

        Args:
            progress_cb: Callback for 0-100 progress updates.
            only_folders: Optional list of gdrive entry names. When set,
                restricts the sync to entries whose `name` matches one
                in the list. Used by /api/posters/gdrive/sync to express
                "sync just these folders" through the same code path as
                "sync all" — a missing/empty value means sync everything.
            notify: When True (default) send the aggregate
                Discord/Notifiarr/Email summary at the end. Callers that
                represent a single-folder targeted UI action set this to
                False — UI feedback already covers them and a per-click
                Discord ping would be noise.
        """
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

                if only_folders:
                    requested = set(only_folders)
                    filtered = [s for s in sync_list if s.name in requested]
                    missing = requested - {s.name for s in sync_list}
                    if missing:
                        self.logger.warning(
                            f"only_folders requested unknown gdrive names: "
                            f"{sorted(missing)} — ignoring"
                        )
                    sync_list = filtered
                    self.logger.info(
                        f"Filtered sync_list to {len(sync_list)} folder(s): "
                        f"{[s.name for s in sync_list]}"
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
                        self.logger.info(
                            "Cancellation requested, stopping sync_gdrive."
                        )
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
                    success, counters = self.sync_folder(
                        sync_location, sync_id, progress_cb=progress_cb
                    )
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
                    synced_items.append(
                        {
                            "location": sync_location,
                            "owner": owner,
                            "file_count": file_count,
                            "size_bytes": size_bytes,
                            "success": success,
                            "counters": counters,
                        }
                    )

                    # Refresh this folder's slice of poster_cache so a
                    # standalone bulk run() (e.g. triggered via module_run
                    # from the Modules or Schedule page) keeps Assets
                    # Search aligned with disk. When run() is wrapped by
                    # poster_renamerr, the parent does a full clear() +
                    # merge_assets afterward, so this per-folder refresh
                    # becomes redundant — still fine, just briefly
                    # duplicated work.
                    if success:
                        self._refresh_poster_cache_for_folder(sync_location)

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

                # Aggregate per-folder counters into a single dict for
                # the notification top-line. Per-item counters stay on
                # each synced_items entry so the formatter can still
                # show per-folder activity.
                agg_counters = _empty_counters()
                for it in synced_items:
                    for k, v in (it.get("counters") or {}).items():
                        agg_counters[k] = agg_counters.get(k, 0) + v

                # Notify — skipped on dry-run, empty lists (nothing to say),
                # when the user has no sources configured, and when the
                # caller explicitly opts out (e.g. single-folder UI sync
                # where the toast is enough feedback).
                if (
                    notify
                    and not getattr(self.config, "dry_run", False)
                    and total > 0
                    and synced_items
                ):
                    try:
                        manager = NotificationManager(
                            self.full_config, self.logger, module_name="sync_gdrive"
                        )
                        manager.send_notification(
                            {
                                "total": total,
                                "succeeded": total - failed_count,
                                "failed": failed_count,
                                "elapsed": f"{time.time() - start_time:.1f}s",
                                "items": synced_items,
                                "agg_counters": agg_counters,
                            }
                        )
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
