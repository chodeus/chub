# modules/renameinatorr.py

import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from backend.util.arr import BaseARRClient, create_arr_client
from backend.util.base_module import ChubModule
from backend.util.constants import season_regex
from backend.util.helper import create_table, print_settings, progress
from backend.util.logger import Logger
from backend.util.notification import NotificationManager


class Renameinatorr(ChubModule):
    def __init__(self, logger: Optional[Logger] = None) -> None:
        super().__init__(logger=logger)

    @staticmethod
    def print_output(output: Dict[str, Dict[str, Any]], logger: Logger) -> None:
        for instance, instance_data in output.items():
            table = [[f"{instance_data['server_name'].capitalize()} Rename List"]]
            logger.info(create_table(table))
            for item in instance_data["data"]:
                if item["file_info"] or item["new_path_name"]:
                    logger.info(f"{item['title']} ({item['year']})")
                if item["new_path_name"]:
                    logger.info(
                        f"\tFolder Renamed: {item['path_name']} -> {item['new_path_name']}"
                    )
                if item["file_info"]:
                    logger.info("\tFiles:")
                    for existing_path, new_path in item["file_info"].items():
                        logger.info(
                            f"\t\tOriginal: {existing_path}\n\t\tNew: {new_path}\n"
                        )
            logger.info("")
            total_items = len(instance_data["data"])
            total_rename_items = len(
                [v["file_info"] for v in instance_data["data"] if v["file_info"]]
            )
            total_folder_rename = len(
                [
                    v["new_path_name"]
                    for v in instance_data["data"]
                    if v["new_path_name"]
                ]
            )
            if any(v["file_info"] or v["new_path_name"] for v in instance_data["data"]):
                table = [
                    [f"{instance_data['server_name'].capitalize()} Rename Summary"],
                    [f"Total Items: {total_items}"],
                ]
                if any(v["file_info"] for v in instance_data["data"]):
                    table.append([f"Total Renamed Items: {total_rename_items}"])
                if any(v["new_path_name"] for v in instance_data["data"]):
                    table.append([f"Total Folder Renames: {total_folder_rename}"])
                logger.info(create_table(table))
            else:
                logger.info(f"No items renamed in {instance_data['server_name']}.")
            logger.info("")

    @staticmethod
    def get_count_for_instance_type(
        config: Any, instance_type: str, logger: Logger
    ) -> int:
        count = config.count
        if instance_type == "radarr" and getattr(config, "radarr_count", None):
            logger.debug(
                f"radarr_count found! overriding count from {config.count} to {config.radarr_count}"
            )
            count = config.radarr_count
        elif instance_type == "sonarr" and getattr(config, "sonarr_count", None):
            logger.debug(
                f"sonarr_count found! overriding count from {config.count} to {config.sonarr_count}"
            )
            count = config.sonarr_count
        logger.info(f"using count= {count} for instance_type= {instance_type}")
        return count

    @staticmethod
    def get_chunks_for_run(
        media_dict: List[Dict[str, Any]], chunk_size: int, logger: Logger
    ) -> List[List[Dict[str, Any]]]:
        chunks: List[List[Dict[str, Any]]] = []
        for i in range(0, len(media_dict), chunk_size):
            chunks.append(media_dict[i : i + chunk_size])
        return chunks

    @staticmethod
    def get_untagged_chunks_for_run(
        media_dict: List[Dict[str, Any]],
        tag_id: int,
        chunk_size: int,
        all_in_single_run: bool,
        logger: Logger,
    ) -> List[List[Dict[str, Any]]]:
        all_items_without_tags = [
            item for item in media_dict if tag_id not in item["tags"]
        ]
        if all_in_single_run or not chunk_size:
            return [all_items_without_tags] if all_items_without_tags else []
        return Renameinatorr.get_chunks_for_run(
            all_items_without_tags, chunk_size, logger
        )

    @staticmethod
    def resolve_ignore_tag_ids(app: BaseARRClient, config: Any) -> set:
        """Resolve the configured (comma-separated) ignore tag names to the set
        of existing tag ids.

        Lookup-only — unlike get_tag_id_from_name this never creates a missing
        tag; an absent ignore tag simply means there is nothing to skip.
        """
        if not getattr(config, "ignore_tags", None):
            return set()
        ignore_names = {
            t.strip().lower() for t in str(config.ignore_tags).split(",") if t.strip()
        }
        if not ignore_names:
            return set()
        all_tags = app.get_all_tags() or []
        return {tag["id"] for tag in all_tags if tag["label"] in ignore_names}

    @staticmethod
    def filter_ignored(
        media_dict: List[Dict[str, Any]], ignore_tag_ids: set
    ) -> List[Dict[str, Any]]:
        """Drop items carrying any of the ignore tag ids."""
        if not ignore_tag_ids:
            return media_dict
        return [
            item
            for item in media_dict
            if not ignore_tag_ids & set(item.get("tags", []))
        ]

    def process_instance(
        self,
        app: BaseARRClient,
        instance_type: str,
        config: Any,
        logger: Logger,
    ) -> List[Dict[str, Any]]:
        table = [[f"Processing {app.instance_name}"]]
        logger.debug(create_table(table))
        default_batch_size: int = 100
        instance_start_time: float = time.time()
        media_dict: List[Dict[str, Any]] = app.get_all_media()
        count: int = self.get_count_for_instance_type(config, instance_type, logger)
        tag_id: Any = None

        # Ignore-tag filtering: skip items carrying any of the (comma-
        # separated) ignore tags. Resolve the tag ids once and re-apply the
        # filter after every re-fetch below (e.g. the tag-cycle reset) so an
        # ignored item can never be swept back into processing.
        ignore_tag_ids = self.resolve_ignore_tag_ids(app, config)
        if ignore_tag_ids:
            before_count = len(media_dict)
            media_dict = self.filter_ignored(media_dict, ignore_tag_ids)
            skipped_count = before_count - len(media_dict)
            if skipped_count > 0:
                logger.info(
                    f"Skipped {skipped_count} items due to ignore tags '{config.ignore_tags}'."
                )

        # Tagging logic: filter untagged, clear if all tagged, then chunk
        enable_batching = getattr(config, "enable_batching", False)
        if getattr(config, "tag_name", None):
            tag_id = app.get_tag_id_from_name(config.tag_name)
            if tag_id:
                chunk_size = (
                    count if count else (default_batch_size if enable_batching else 0)
                )
                all_in_single_run = not enable_batching and not count
                chunks_to_process_this_run = self.get_untagged_chunks_for_run(
                    media_dict, tag_id, chunk_size, all_in_single_run, logger
                )
                if not chunks_to_process_this_run or not any(
                    chunks_to_process_this_run
                ):
                    # All tagged — clear tags and re-fetch
                    media_ids = [item["media_id"] for item in media_dict]
                    logger.info("All media is tagged. Removing tags...")
                    app.remove_tags(media_ids, tag_id)
                    media_dict = self.filter_ignored(
                        app.get_all_media(), ignore_tag_ids
                    )
                    chunks_to_process_this_run = self.get_untagged_chunks_for_run(
                        media_dict, tag_id, chunk_size, all_in_single_run, logger
                    )
                if not enable_batching and chunks_to_process_this_run:
                    # Non-batched: only process the first chunk
                    chunks_to_process_this_run = [chunks_to_process_this_run[0]]
            else:
                # tag_name set but tag doesn't exist yet — process all media
                chunks_to_process_this_run = [media_dict] if media_dict else []
        else:
            # No tagging — chunk all media
            if not enable_batching:
                if not count:
                    chunks_to_process_this_run: List[List[Dict[str, Any]]] = [
                        media_dict
                    ]
                else:
                    chunks_to_process_this_run = self.get_chunks_for_run(
                        media_dict, count, logger
                    )
                    chunks_to_process_this_run = (
                        [chunks_to_process_this_run[0]]
                        if chunks_to_process_this_run
                        else []
                    )
            else:
                count = count if count else default_batch_size
                chunks_to_process_this_run = self.get_chunks_for_run(
                    media_dict, count, logger
                )
        logger.info(f"num_chunks= {len(chunks_to_process_this_run)}")
        final_media_dict: List[Dict[str, Any]] = []
        chunk_progress_bar = progress(
            chunks_to_process_this_run,
            desc=f"Processing batches for '{app.instance_name}'...",
            unit="items",
            logger=logger,
            leave=True,
        )
        for chunk in chunk_progress_bar:
            if self.is_cancelled():
                break
            chunk_start_time: float = time.time()
            media_dict = chunk
            logger.debug(f"Processing {len(media_dict)} media items in current chunk")
            if media_dict:
                logger.info("Processing data... This may take a while.")
                # Optional pre-rename metadata refresh. When enabled, force a
                # refresh for every item in the chunk and wait for it to finish
                # before reading the rename list, so the rename reflects the
                # latest episode/movie titles from TVDB/TMDB (e.g. a Sonarr
                # "TBA" episode that has since been named). Unlike the upstream
                # script, which only sleeps, we wait on the command for
                # correctness. Skipped on dry runs.
                if getattr(config, "refresh_before_rename", False) and not getattr(
                    config, "dry_run", False
                ):
                    refresh_ids = [it["media_id"] for it in media_dict]
                    logger.info(
                        f"Refreshing metadata for {len(refresh_ids)} item(s) "
                        f"before rename check..."
                    )
                    refresh_resp = app.refresh_items(refresh_ids)
                    if refresh_resp and "id" in refresh_resp:
                        if app.wait_for_command(refresh_resp["id"]):
                            logger.info(
                                "Metadata refresh complete; checking rename list..."
                            )
                        else:
                            logger.warning(
                                "Metadata refresh did not complete cleanly; "
                                "proceeding with rename check anyway."
                            )
                progress_bar = progress(
                    media_dict,
                    desc=f"Processing single batch for '{app.instance_name}'...",
                    unit="items",
                    logger=logger,
                    leave=True,
                )
                grouped_root_folders: Dict[str, List[int]] = defaultdict(list)
                media_ids: List[int] = []
                any_renamed: bool = False

                # Prefetch rename previews concurrently — these are read-only
                # GETs and were the per-item bottleneck (one blocking call per
                # item in the chunk). Each runs on a private session
                # (threadsafe=True); all state mutation stays in the sequential
                # loop below so no locking is needed.
                rename_lists: Dict[int, Any] = {}
                fetch_ids = [it["media_id"] for it in media_dict]
                if fetch_ids:

                    def _fetch_rename(mid):
                        return mid, app.get_rename_list(mid, threadsafe=True)

                    with ThreadPoolExecutor(
                        max_workers=min(10, len(fetch_ids))
                    ) as pool:
                        futures = {
                            pool.submit(_fetch_rename, mid): mid for mid in fetch_ids
                        }
                        for future in as_completed(futures):
                            mid, resp = future.result()
                            rename_lists[mid] = resp

                for item in progress_bar:
                    if self.is_cancelled():
                        break
                    file_info: Dict[str, str] = {}
                    rename_response = rename_lists.get(item["media_id"]) or []
                    for items in rename_response:
                        existing_path = items.get("existingPath")
                        new_path = items.get("newPath")
                        # Remove season info from path if present
                        if existing_path and re.search(season_regex, existing_path):
                            existing_path = re.sub(season_regex, "", existing_path)
                        if new_path and re.search(season_regex, new_path):
                            new_path = re.sub(season_regex, "", new_path)
                        if existing_path:
                            existing_path = existing_path.lstrip("/")
                        if new_path:
                            new_path = new_path.lstrip("/")
                        if existing_path is not None:
                            file_info[existing_path] = new_path
                    item["new_path_name"] = None
                    item["file_info"] = file_info
                    if file_info:
                        any_renamed = True
                    media_ids.append(item["media_id"])
                    if getattr(config, "rename_folders", False):
                        grouped_root_folders[item["root_folder"]].append(
                            item["media_id"]
                        )
                if not getattr(config, "dry_run", False):
                    # Perform file renaming
                    if media_ids:
                        app.rename_media(media_ids)
                        if any_renamed:
                            logger.info(f"Refreshing {app.instance_name}...")
                            response = app.refresh_items(media_ids)
                            if response and "id" in response:
                                ready = app.wait_for_command(response["id"])
                                if ready:
                                    logger.info(
                                        f"Media refreshed on {app.instance_name}..."
                                    )
                    else:
                        logger.info(f"No media to rename on {app.instance_name}...")
                    # Tagging after rename
                    if tag_id and getattr(config, "tag_name", None):
                        logger.info(
                            f"Adding tag '{config.tag_name}' to items in {app.instance_name}..."
                        )
                        app.add_tags(media_ids, tag_id)
                    # Folder rename steps
                    if (
                        getattr(config, "rename_folders", False)
                        and grouped_root_folders
                    ):
                        logger.info(f"Renaming folders in {app.instance_name}...")
                        for (
                            root_folder,
                            folder_media_ids,
                        ) in grouped_root_folders.items():
                            logger.debug(f"renaming root folder {root_folder}")
                            app.rename_folders(folder_media_ids, root_folder)
                        logger.info(f"Refreshing {app.instance_name}...")
                        response = app.refresh_items(media_ids)
                        logger.info(f"Waiting for {app.instance_name} to refresh...")
                        ready = (
                            response
                            and "id" in response
                            and app.wait_for_command(response["id"])
                        )
                        logger.info(f"Folders renamed in {app.instance_name}...")
                        # Update items with new path names if changed
                        if ready:
                            logger.info(
                                f"Fetching updated data for {app.instance_name}..."
                            )
                            new_media_dict = app.get_all_media()
                            old_by_id = {
                                old_item["media_id"]: old_item
                                for old_item in media_dict
                            }
                            for new_item in new_media_dict:
                                old_item = old_by_id.get(new_item["media_id"])
                                if old_item is None:
                                    continue
                                logger.debug(
                                    f"Checking if item {new_item['media_id']} changed..."
                                )
                                if new_item["path_name"] != old_item["path_name"]:
                                    logger.debug(
                                        f"item {new_item['media_id']} changed from {old_item['path_name']} to {new_item['path_name']}"
                                    )
                                    old_item["new_path_name"] = new_item["path_name"]
                final_media_dict.extend(media_dict)
                total_renamed = sum(
                    len(i["file_info"]) for i in media_dict if i.get("file_info")
                )
                total_folder_renamed = sum(bool(i["new_path_name"]) for i in media_dict)
                logger.info(
                    f"Chunk completed in {time.time() - chunk_start_time:.2f} seconds | "
                    f"Files renamed: {total_renamed} | Folders renamed: {total_folder_renamed}"
                )
        logger.info(
            f"Finished processing {app.instance_name} in {time.time() - instance_start_time:.2f} seconds."
        )
        final_media_dict.sort(key=lambda it: it.get("new_path_name") or it["path_name"])
        trimmed: List[Dict[str, Any]] = []
        for item in final_media_dict:
            raw_info = item.get("file_info", {})
            sorted_info = {old: raw_info[old] for old in sorted(raw_info.keys())}
            trimmed.append(
                {
                    "title": item["title"],
                    "year": item["year"],
                    "path_name": item["path_name"],
                    "new_path_name": item.get("new_path_name"),
                    "file_info": sorted_info,
                }
            )
        return trimmed

    def run(self):
        try:
            if self.config.log_level.lower() == "debug":
                print_settings(self.logger, self.config)
            if self.config.dry_run:
                table = [["Dry Run"], ["NO CHANGES WILL BE MADE"]]
                self.logger.info(create_table(table))
                self.logger.info("")

            output = {}
            for instance_type in ["radarr", "sonarr"]:
                instance_dict = getattr(self.full_config.instances, instance_type, {})
                for instance_name, instance_cfg in instance_dict.items():
                    if instance_name in self.config.instances:
                        app = create_arr_client(
                            instance_cfg.url,
                            instance_cfg.api,
                            self.logger,
                        )
                        if app and app.connect_status:
                            data = self.process_instance(
                                app, instance_type, self.config, self.logger
                            )
                            output[instance_name] = {
                                "server_name": app.instance_name,
                                "data": data,
                            }
            if any(value["data"] for value in output.values()):
                self.print_output(output, self.logger)
                manager = NotificationManager(
                    self.full_config, self.logger, module_name="renameinatorr"
                )
                manager.send_notification(output)
            else:
                self.logger.info("No media items to rename.")
        except KeyboardInterrupt:
            self.logger.info("Keyboard Interrupt detected. Exiting...")
            return
        except Exception:
            self.logger.error("\n\nAn error occurred:\n", exc_info=True)
            self.logger.error("\n\n")
        finally:
            self.logger.log_outro()
