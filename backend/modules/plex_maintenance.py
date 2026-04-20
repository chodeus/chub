# modules/plex_maintenance.py

import os
import time
from typing import Any, Dict, Optional

from backend.util.base_module import ChubModule
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


class PlexMaintenance(ChubModule):
    """Plex server-level maintenance tasks.

    Split out of poster_cleanarr so the UI can run these on their own cron
    (e.g. monthly VACUUM, weekly cache sweep) without touching poster state.

    Tasks:
        - empty_trash:       plex.library.emptyTrash() — purges Plex's internal trash
        - clean_bundles:     plex.library.cleanBundles() — removes orphaned .bundle dirs
        - optimize_db:       plex.library.optimize() — VACUUMs Plex's SQLite DB
        - photo_transcoder:  clears $PLEX/Cache/PhotoTranscoder/ files on disk
    """

    def __init__(self, logger: Optional[Logger] = None) -> None:
        super().__init__(logger=logger)
        self.plex_path: str = getattr(self.config, "plex_path", "")

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            start_time = time.time()

            tasks_selected = [
                name
                for name, flag in (
                    ("Empty Trash", self.config.empty_trash),
                    ("Clean Bundles", self.config.clean_bundles),
                    ("Optimize DB", self.config.optimize_db),
                    ("PhotoTranscoder", self.config.photo_transcoder),
                )
                if flag
            ]
            if not tasks_selected:
                self.logger.info(
                    "No maintenance tasks enabled. Toggle at least one of "
                    "empty_trash / clean_bundles / optimize_db / photo_transcoder "
                    "in the Plex Maintenance settings."
                )
                return

            self.logger.info(
                create_table(
                    [
                        ["Plex Maintenance"],
                        [f"Tasks: {', '.join(tasks_selected)}"],
                    ]
                )
            )

            # PhotoTranscoder clears a filesystem cache and doesn't need a
            # Plex API connection — run it even if Plex is unreachable.
            transcoder_stats = {"count": 0, "total_size": 0}
            if self.config.photo_transcoder and self.plex_path:
                transcoder_stats = self._clean_photo_transcoder()

            # The other three tasks all call Plex's REST API, so we need a
            # PlexServer connection.
            maintenance_results: Dict[str, Any] = {}
            if any(
                [
                    self.config.empty_trash,
                    self.config.clean_bundles,
                    self.config.optimize_db,
                ]
            ):
                plex_server = self._get_plex_server()
                if plex_server is None:
                    self.logger.error("Failed to connect to Plex server. Aborting.")
                else:
                    maintenance_results = self._run_plex_maintenance(plex_server)

            elapsed = time.time() - start_time
            output = {
                "photo_transcoder": {
                    "count": transcoder_stats["count"],
                    "size_human": format_bytes(transcoder_stats["total_size"]),
                },
                "maintenance": maintenance_results,
                "elapsed": f"{elapsed:.1f}s",
            }
            self._print_report(output)

            if transcoder_stats["count"] or maintenance_results:
                try:
                    manager = NotificationManager(
                        self.config, self.logger, module_name="plex_maintenance"
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

    # ------------------------------------------------------------------
    # Plex connection
    # ------------------------------------------------------------------

    def _get_plex_server(self):
        """Get a PlexServer connection using CHUB instance config with retry logic."""
        from plexapi.server import PlexServer

        instances = self.config.instances
        plex_instances = self.full_config.instances.plex

        if not instances:
            # Require an explicit instance selection. No auto-pick.
            self.logger.error(
                "No Plex instances selected for plex_maintenance. "
                "Pick one in Settings → Modules → Plex Maintenance → Plex Instances "
                f"(available: {sorted(plex_instances) or 'none'})."
            )
            return None
        instance_name = instances[0]

        if instance_name not in plex_instances:
            self.logger.error(
                f"Plex instance '{instance_name}' not found in CHUB instances config."
            )
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
                    f"Connecting to Plex '{instance_name}' at {url} "
                    f"(attempt {attempt}/{max_retries})..."
                )
                server = PlexServer(url, token, timeout=timeout)
                _ = server.version
                self.logger.info(f"Connected to Plex server v{server.version}")
                return server
            except Exception as e:
                err_msg = str(e).lower()
                if "unauthorized" in err_msg or "401" in err_msg:
                    self.logger.error(
                        f"Plex authentication failed for '{instance_name}': check api token."
                    )
                    return None
                if attempt < max_retries:
                    self.logger.warning(
                        f"Plex connection attempt {attempt} failed: {e}. "
                        f"Retrying in {backoff}s..."
                    )
                    time.sleep(backoff)
                else:
                    self.logger.error(
                        f"Plex connection failed after {max_retries} attempts: {e}"
                    )
                    return None

        return None

    # ------------------------------------------------------------------
    # Server-level maintenance tasks
    # ------------------------------------------------------------------

    def _run_plex_maintenance(self, plex_server) -> Dict[str, Any]:
        """Run the selected Plex library maintenance tasks with sleep between each."""
        results: Dict[str, Any] = {}
        sleep_seconds = self.config.sleep

        tasks = []
        if self.config.empty_trash:
            tasks.append(("Empty Trash", lambda: plex_server.library.emptyTrash()))
        if self.config.clean_bundles:
            tasks.append(("Clean Bundles", lambda: plex_server.library.cleanBundles()))
        if self.config.optimize_db:
            tasks.append(("Optimize DB", lambda: plex_server.library.optimize()))

        for i, (name, task_fn) in enumerate(tasks):
            try:
                self.logger.info(f"Running Plex maintenance: {name}...")
                task_fn()
                results[name] = "success"
                self.logger.info(f"  {name} completed.")
            except Exception as e:
                results[name] = f"failed: {e}"
                self.logger.error(f"  {name} failed: {e}")

            if i < len(tasks) - 1 and sleep_seconds > 0:
                self.logger.info(f"  Sleeping {sleep_seconds}s before next task...")
                time.sleep(sleep_seconds)

        return results

    # ------------------------------------------------------------------
    # PhotoTranscoder cache cleanup (filesystem, not Plex API)
    # ------------------------------------------------------------------

    def _clean_photo_transcoder(self) -> Dict[str, Any]:
        """Walk $PLEX/Cache/PhotoTranscoder/ and delete every file under it."""
        transcoder_dir = os.path.join(self.plex_path, "Cache", "PhotoTranscoder")

        if not os.path.isdir(transcoder_dir):
            self.logger.warning(
                f"PhotoTranscoder directory not found: {transcoder_dir}"
            )
            return {"count": 0, "total_size": 0}

        count = 0
        total_size = 0

        self.logger.info("Cleaning PhotoTranscoder cache...")

        for root, _dirs, files in os.walk(transcoder_dir):
            if self.is_cancelled():
                break
            for filename in files:
                filepath = os.path.join(root, filename)
                try:
                    total_size += os.path.getsize(filepath)
                    os.remove(filepath)
                    count += 1
                except Exception as e:
                    self.logger.error(f"Failed to remove {filepath}: {e}")

        self.logger.info(
            f"PhotoTranscoder: removed {count} files ({format_bytes(total_size)})"
        )
        return {"count": count, "total_size": total_size}

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def _print_report(self, output: Dict[str, Any]) -> None:
        rows = [["Plex Maintenance Summary"]]
        if output["photo_transcoder"]["count"]:
            rows.append(
                [
                    "PhotoTranscoder",
                    f"{output['photo_transcoder']['count']} files · "
                    f"{output['photo_transcoder']['size_human']}",
                ]
            )
        for name, status in (output.get("maintenance") or {}).items():
            rows.append([name, str(status)])
        rows.append(["Elapsed", output["elapsed"]])
        self.logger.info(create_table(rows))
