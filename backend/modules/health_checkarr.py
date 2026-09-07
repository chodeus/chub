# modules/health_checkarr.py

import re
from typing import Any, Dict, List, Optional, Set

from backend.util.arr import create_arr_client
from backend.util.base_module import ChubModule
from backend.util.constants import tmdb_id_regex, tvdb_id_regex
from backend.util.helper import create_table, print_settings, progress
from backend.util.logger import Logger
from backend.util.notification import NotificationManager


class HealthCheckarr(ChubModule):
    def __init__(self, logger: Optional[Logger] = None) -> None:
        """
        Standard constructor using dependency injection.

        Args:
            config: Complete CHUB configuration object
            logger: Logger instance
        """
        super().__init__(logger=logger)

    @staticmethod
    def _extract_removed_ids(
        health: List[Dict[str, Any]], instance_type: str
    ) -> Set[int]:
        """Extract removed TMDB/TVDB IDs from ARR health messages."""
        wanted_source = (
            "RemovedMovieCheck" if instance_type == "radarr" else "RemovedSeriesCheck"
        )
        id_regex = tmdb_id_regex if instance_type == "radarr" else tvdb_id_regex
        ids: Set[int] = set()

        for health_item in health:
            if health_item.get("source") != wanted_source:
                continue
            message = health_item.get("message") or ""
            for match in re.finditer(id_regex, message):
                ids.add(int(match.group(1)))

        return ids

    def run(self) -> None:
        """
        Process Radarr and Sonarr instances to identify and delete media items flagged by health checks
        as removed from TMDB or TVDB. Supports dry-run mode and logs all actions.
        """
        try:
            if self.config.log_level.lower() == "debug":
                print_settings(self.logger, self.config)

            if self.config.dry_run:
                table = [["Dry Run"], ["NO CHANGES WILL BE MADE"]]
                self.logger.info(create_table(table))
                self.logger.info("")

            selected_instances = set(getattr(self.config, "instances", None) or [])
            if not selected_instances:
                self.logger.warning(
                    "No Health Checkarr instances configured. Skipping run."
                )
                return

            # Supported instance types: radarr/sonarr
            for instance_type in ["radarr", "sonarr"]:
                instances = getattr(self.full_config.instances, instance_type, {}) or {}
                if not instances:
                    continue
                for instance_name, instance_info in instances.items():
                    if instance_name not in selected_instances:
                        continue
                    if not getattr(instance_info, "enabled", True):
                        self.logger.info(
                            f"[{instance_type}] '{instance_name}': disabled; skipping."
                        )
                        continue

                    app = None
                    try:
                        app = create_arr_client(
                            instance_info.url,
                            instance_info.api,
                            self.logger,
                        )
                        if not app or not app.is_connected():
                            self.logger.warning(
                                f"[{instance_type}] '{instance_name}': connection failed."
                            )
                            continue

                        health = app.get_health() or []
                        removed_ids = self._extract_removed_ids(health, instance_type)
                        self.logger.debug(
                            f"[{instance_type}] '{instance_name}' removed IDs: "
                            f"{sorted(removed_ids)}"
                        )
                        if not removed_ids:
                            self.logger.info(
                                f"No removed TMDB/TVDB health items found for "
                                f"{app.instance_name or instance_name}."
                            )
                            continue

                        media_dict = app.get_all_media()  # List of dicts
                        output: List[Dict[str, Any]] = []

                        # Match health-check IDs with media library entries
                        with progress(
                            media_dict,
                            desc=f"Processing {instance_type}",
                            unit="items",
                            logger=self.logger,
                            leave=True,
                        ) as pbar:
                            for item in pbar:
                                if self.is_cancelled():
                                    return

                                db_id = item.get(
                                    "tmdb_id"
                                    if instance_type == "radarr"
                                    else "tvdb_id"
                                )
                                if db_id not in removed_ids:
                                    continue

                                self.logger.debug(
                                    f"Found {item.get('title', 'Untitled')} with: {db_id}"
                                )
                                enriched_item = dict(item)
                                enriched_item.update(
                                    {
                                        "config_instance_name": instance_name,
                                        "instance_name": app.instance_name
                                        or instance_name,
                                        "instance_type": instance_type,
                                        "db_id": db_id,
                                        "dry_run": bool(self.config.dry_run),
                                    }
                                )
                                output.append(enriched_item)

                        if not output:
                            self.logger.info(
                                f"Removed IDs were reported for "
                                f"{app.instance_name or instance_name}, but no matching "
                                "local media entries were found."
                            )
                            continue

                        if self.config.dry_run:
                            action = "Would delete"
                            progress_desc = f"Reviewing {instance_type} items"
                        else:
                            action = "Deleting"
                            progress_desc = f"Deleting {instance_type} items"

                        self.logger.info(
                            f"{action} {len(output)} {instance_type} items from "
                            f"{app.instance_name or instance_name}"
                        )
                        deleted_count = 0
                        resolved_instance_name = app.instance_name or instance_name
                        with progress(
                            output,
                            desc=progress_desc,
                            unit="items",
                            logger=self.logger,
                            leave=True,
                        ) as pbar:
                            for item in pbar:
                                if self.is_cancelled():
                                    return
                                media_id = item.get("media_id")
                                if media_id is None:
                                    self.logger.warning(
                                        f"Skipping {item.get('title', 'Untitled')}: "
                                        "missing ARR media id."
                                    )
                                    continue
                                title = item.get("title", "Untitled")
                                if self.config.dry_run:
                                    self.logger.info(
                                        f"[WOULD DELETE] {instance_type} "
                                        f"'{title}' (id={media_id}) from "
                                        f"{resolved_instance_name}"
                                    )
                                    deleted_count += 1
                                else:
                                    app.delete_media(media_id)
                                    self.logger.info(
                                        f"[DELETED] {instance_type} "
                                        f"'{title}' (id={media_id}) from "
                                        f"{resolved_instance_name}"
                                    )
                                    deleted_count += 1

                        if deleted_count:
                            verb = "would be deleted" if self.config.dry_run else "deleted"
                            self.logger.info(
                                f"   → {deleted_count} {verb} from "
                                f"{resolved_instance_name}"
                            )
                        else:
                            self.logger.info(
                                f"   → no deletions from {resolved_instance_name}"
                            )

                        # Send notification with deleted/flagged items.
                        manager = NotificationManager(
                            self.full_config, self.logger, module_name="health_checkarr"
                        )
                        manager.send_notification(output)
                    finally:
                        if (
                            app is not None
                            and hasattr(app, "session")
                            and app.session is not None
                        ):
                            try:
                                app.session.close()
                            except Exception:
                                # Cleanup-only path; a session-close error
                                # must not mask any in-flight exception.
                                pass
        except KeyboardInterrupt:
            self.logger.info("Keyboard Interrupt detected. Exiting...")
            return
        except Exception:
            self.logger.error("\n\nAn error occurred:\n", exc_info=True)
            self.logger.error("\n\n")
            raise
        finally:
            self.logger.log_outro()
