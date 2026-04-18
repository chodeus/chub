# modules/upgradinatorr.py

from typing import Any, Dict, List, Optional

from backend.util.arr import BaseARRClient, create_arr_client
from backend.util.base_module import ChubModule
from backend.util.helper import create_table, print_settings
from backend.util.logger import Logger
from backend.util.notification import NotificationManager

VALID_STATUSES = {"continuing", "airing", "ended", "canceled", "released"}
VALID_SEARCH_MODES = {"upgrade", "missing", "cutoff"}


class Upgradinatorr(ChubModule):
    def __init__(self, logger: Optional[Logger] = None) -> None:
        super().__init__(logger=logger)

    def filter_media(
        self,
        media_dict: List[Dict[str, Any]],
        checked_tag_id: int,
        ignore_tag_id: int,
        count: int,
        season_monitored_threshold: int,
    ) -> List[Dict[str, Any]]:
        filtered_media_dict: List[Dict[str, Any]] = []
        filter_count: int = 0
        for item in media_dict:
            if filter_count == count:
                break
            if (
                checked_tag_id in item["tags"]
                or ignore_tag_id in item["tags"]
                or not item["monitored"]
                or item["status"] not in VALID_STATUSES
            ):
                reasons = []
                if checked_tag_id in item["tags"]:
                    reasons.append("tagged")
                if ignore_tag_id in item["tags"]:
                    reasons.append("ignore")
                if not item["monitored"]:
                    reasons.append("unmonitored")
                if item["status"] not in VALID_STATUSES:
                    reasons.append(f"status={item['status']}")
                self.logger.debug(
                    f"Skipping {item['title']} ({item['year']}), Reason: {', '.join(reasons)}"
                )
                continue
            if item["seasons"]:
                series_monitored = False
                for i, season in enumerate(item["seasons"]):
                    monitored_count = 0
                    for episode in season["episode_data"]:
                        if episode["monitored"]:
                            monitored_count += 1
                    if len(season["episode_data"]) > 0:
                        monitored_percentage = (
                            monitored_count / len(season["episode_data"])
                        ) * 100
                    else:
                        self.logger.debug(
                            f"Skipping {item['title']} ({item['year']}), Season {season.get('season_number', i)} unmonitored. Reason: No episodes in season."
                        )
                        continue
                    if (
                        season_monitored_threshold is not None
                        and monitored_percentage < season_monitored_threshold
                    ):
                        item["seasons"][i]["monitored"] = False
                        self.logger.debug(
                            f"{item['title']}, Season {season.get('season_number', i)} unmonitored. Reason: monitored percentage {int(monitored_percentage)}% less than season_monitored_threshold {int(season_monitored_threshold)}%"
                        )
                    if item["seasons"][i]["monitored"]:
                        series_monitored = True
                if not series_monitored:
                    self.logger.debug(
                        f"Skipping {item['title']} ({item['year']}), Status: {item['status']}, Monitored: {item['monitored']}, Tags: {item['tags']}"
                    )
                    continue
            filtered_media_dict.append(item)
            self.logger.info(
                f"Queued for upgrade: {item['title']} ({item['year']}) [ID: {item['media_id']}]"
            )
            filter_count += 1
        return filtered_media_dict

    def process_search_response(
        self,
        search_response: Optional[Dict[str, Any]],
        media_id: int,
        app: BaseARRClient,
    ) -> None:
        if search_response:
            self.logger.debug(
                f"    [CMD] Waiting for command to complete for search response ID: {search_response['id']}"
            )
            ready = app.wait_for_command(search_response["id"])
            if ready:
                self.logger.debug(
                    f"    [CMD] Command completed successfully for search response ID: {search_response['id']}"
                )
            else:
                self.logger.debug(
                    f"    [CMD] Command did not complete successfully for search response ID: {search_response['id']}"
                )
        else:
            self.logger.warning(f"No search response for media ID: {media_id}")

    def process_queue(
        self, queue: Dict[str, Any], instance_type: str, media_ids: List[int]
    ) -> List[Dict[str, Any]]:
        id_type = {"radarr": "movieId", "sonarr": "seriesId", "lidarr": "artistId"}[instance_type]
        queue_dict: List[Dict[str, Any]] = []
        records = queue.get("records", [])
        for item in records:
            media_id = item.get(id_type)
            if media_id not in media_ids:
                continue
            if "downloadId" not in item:
                continue
            queue_dict.append(
                {
                    "download_id": item["downloadId"],
                    "media_id": media_id,
                    "download": item.get("title"),
                    "torrent_custom_format_score": item.get("customFormatScore"),
                }
            )
        queue_dict = [dict(t) for t in {tuple(d.items()) for d in queue_dict}]
        return queue_dict

    def _get_all_wanted(self, app: BaseARRClient, search_mode: str) -> List[Dict[str, Any]]:
        """Fetch all pages from the wanted/missing or wanted/cutoff endpoint."""
        fetch_fn = app.get_wanted_missing if search_mode == "missing" else app.get_wanted_cutoff
        all_records: List[Dict[str, Any]] = []
        page = 1
        while True:
            result = fetch_fn(page=page, page_size=200)
            if not result:
                break
            records = result.get("records", [])
            all_records.extend(records)
            total = result.get("totalRecords", 0)
            if len(all_records) >= total or not records:
                break
            page += 1
        return all_records

    def _convert_wanted_to_media_dict(
        self,
        wanted_records: List[Dict[str, Any]],
        instance_type: str,
        app: BaseARRClient,
    ) -> List[Dict[str, Any]]:
        """Convert wanted/missing or wanted/cutoff records into the same dict format
        that filter_media() expects. For Sonarr, groups episodes by series.
        For Radarr, records are already movie-level. For Lidarr, records are album-level
        and get grouped by artist."""
        if instance_type == "radarr":
            tags = app.get_all_tags() or []
            from backend.util.arr import normalize_arr_media
            return [
                normalize_arr_media(item, tags, arr_type="radarr", logger=self.logger)
                for item in wanted_records
            ]

        elif instance_type == "sonarr":
            # Sonarr wanted endpoints return episodes — group by series
            series_map: Dict[int, Dict[str, Any]] = {}
            for ep in wanted_records:
                series_data = ep.get("series", {})
                series_id = series_data.get("id")
                if series_id is None:
                    continue
                if series_id not in series_map:
                    series_map[series_id] = series_data
                    series_map[series_id]["_wanted_seasons"] = set()
                season_num = ep.get("seasonNumber")
                if season_num is not None:
                    series_map[series_id]["_wanted_seasons"].add(season_num)

            # Normalize each unique series
            tags = app.get_all_tags() or []
            from backend.util.arr import normalize_arr_media
            result = []
            for series_data in series_map.values():
                wanted_seasons = series_data.pop("_wanted_seasons", set())
                normalized = normalize_arr_media(
                    series_data, tags, arr_type="sonarr", include_episode=True,
                    episode_lookup=lambda sid, sn, _app=app: _app.get_episode_data_by_season(sid, sn),
                    logger=self.logger,
                )
                # Mark only the wanted seasons as monitored, rest as unmonitored
                if normalized.get("seasons"):
                    for season in normalized["seasons"]:
                        if season["season_number"] not in wanted_seasons:
                            season["monitored"] = False
                result.append(normalized)
            return result

        elif instance_type == "lidarr":
            # Lidarr wanted endpoints return albums — group by artist
            artist_map: Dict[int, Dict[str, Any]] = {}
            for album in wanted_records:
                artist_data = album.get("artist", {})
                artist_id = artist_data.get("id")
                if artist_id is None:
                    continue
                if artist_id not in artist_map:
                    artist_map[artist_id] = artist_data
                    artist_map[artist_id]["_wanted_albums"] = []
                artist_map[artist_id]["_wanted_albums"].append(album)

            tags = app.get_all_tags() or []
            from backend.util.arr import normalize_arr_media
            result = []
            for artist_data in artist_map.values():
                wanted_albums = artist_data.pop("_wanted_albums", [])
                # Build album list for the normalize function
                album_list = []
                for idx, album in enumerate(wanted_albums):
                    album_list.append({
                        "season_number": idx,
                        "album_id": album.get("id"),
                        "album_title": album.get("title", ""),
                        "foreign_album_id": album.get("foreignAlbumId", ""),
                        "monitored": album.get("monitored", True),
                        "episode_data": [],
                    })
                normalized = normalize_arr_media(
                    artist_data, tags, arr_type="lidarr", logger=self.logger,
                )
                normalized["seasons"] = album_list if album_list else None
                result.append(normalized)
            return result

        return []

    def process_instance(
        self,
        instance_type: str,
        instance_settings: Dict[str, Any],
        app: BaseARRClient,
    ) -> Optional[Dict[str, Any]]:
        tagged_count: int = 0
        untagged_count: int = 0
        total_count: int = 0
        count: int = instance_settings.count
        checked_tag_name: str = instance_settings.tag_name or "checked"
        ignore_tag_name: str = instance_settings.ignore_tag or "ignore"
        unattended: bool = instance_settings.unattended
        season_monitored_threshold = instance_settings.season_monitored_threshold or 0
        search_mode: str = getattr(instance_settings, "search_mode", "upgrade") or "upgrade"

        if search_mode not in VALID_SEARCH_MODES:
            self.logger.warning(
                f"Invalid search_mode '{search_mode}', falling back to 'upgrade'."
            )
            search_mode = "upgrade"

        self.logger.info(
            f"Gathering media from {app.instance_name} ({instance_type}) "
            f"[mode: {search_mode}]"
        )

        if search_mode in ("missing", "cutoff"):
            wanted_records = self._get_all_wanted(app, search_mode)
            self.logger.info(
                f"Found {len(wanted_records)} {search_mode} items from {app.instance_name}"
            )
            media_dict = self._convert_wanted_to_media_dict(
                wanted_records, instance_type, app
            )
        elif app.instance_type.lower() in ("sonarr", "lidarr"):
            media_dict = app.get_all_media(include_episode=True)
        else:
            media_dict = app.get_all_media()
        ignore_tag_id = None
        checked_tag_id: int = app.get_tag_id_from_name(checked_tag_name)
        if ignore_tag_name:
            ignore_tag_id: int = app.get_tag_id_from_name(ignore_tag_name)

        filtered_media_dict: List[Dict[str, Any]] = self.filter_media(
            media_dict,
            checked_tag_id,
            ignore_tag_id,
            count,
            season_monitored_threshold,
        )
        if not filtered_media_dict and unattended:
            self.logger.info(
                f"All media for {app.instance_name} is already tagged—removing tags for unattended operation."
            )
            media_ids = [item["media_id"] for item in media_dict]
            self.logger.info("All media is tagged. Removing tags...")
            app.remove_tags(media_ids, checked_tag_id)
            if search_mode in ("missing", "cutoff"):
                wanted_records = self._get_all_wanted(app, search_mode)
                media_dict = self._convert_wanted_to_media_dict(
                    wanted_records, instance_type, app
                )
            elif app.instance_type.lower() in ("sonarr", "lidarr"):
                media_dict = app.get_all_media(include_episode=True)
            else:
                media_dict = app.get_all_media()
            filtered_media_dict = self.filter_media(
                media_dict,
                checked_tag_id,
                ignore_tag_id,
                count,
                season_monitored_threshold,
            )

        if not filtered_media_dict and not unattended:
            self.logger.info(f"No media left to process for {app.instance_name}.")
            self.logger.warning(
                f"No media found for {app.instance_name}. Reason: nothing left to tag."
            )
            return None

        self.logger.debug(f"Filtered media count: {len(filtered_media_dict)}")
        if media_dict:
            total_count = len(media_dict)
            for item in media_dict:
                if checked_tag_id in item["tags"]:
                    tagged_count += 1
                else:
                    untagged_count += 1

        output_dict: Dict[str, Any] = {
            "server_name": app.instance_name,
            "tagged_count": tagged_count,
            "untagged_count": untagged_count,
            "total_count": total_count,
            "data": [],
        }

        if not self.config.dry_run:
            search_count: int = 0
            media_ids: List[int] = [item["media_id"] for item in filtered_media_dict]
            for item in filtered_media_dict:
                if self.is_cancelled():
                    break
                self.logger.debug("")  # Blank line before block
                self.logger.debug("═" * 70)
                self.logger.debug(
                    f"[PROCESSING] {item['title']} ({item['year']}) | ID: {item['media_id']}"
                )
                self.logger.debug("═" * 70)

                if item["seasons"] is None:
                    # Movies (Radarr) or artists without album data
                    self.logger.debug(
                        f"Searching media without seasons for media ID: {item['media_id']}"
                    )
                    search_response = app.search_media(item["media_id"])
                    self.process_search_response(search_response, item["media_id"], app)
                    self.logger.debug(
                        f"  [TAG] Adding tag {checked_tag_id} to media ID: {item['media_id']}"
                    )
                    app.add_tags(item["media_id"], checked_tag_id)
                    search_count += 1
                    if search_count >= count:
                        self.logger.debug(
                            f"Reached search count limit after non-season search ({search_count} >= {count}), breaking."
                        )
                        self.logger.debug("─" * 70)
                        self.logger.debug(
                            f"[END] Finished: {item['title']} ({item['year']}) | ID: {item['media_id']}"
                        )
                        self.logger.debug("─" * 70)
                        self.logger.debug("")
                        break
                elif instance_type == "lidarr":
                    # Lidarr: search monitored albums individually
                    searched = False
                    for album in item["seasons"]:
                        if album.get("monitored", False):
                            album_id = album.get("album_id")
                            album_title = album.get("album_title", f"Album #{album.get('season_number', '?')}")
                            if album_id:
                                self.logger.debug(
                                    f"  [ALBUM] {album_title}: Searching..."
                                )
                                search_response = app.search_album(album_id)
                                self.process_search_response(
                                    search_response, item["media_id"], app
                                )
                                searched = True

                    if searched:
                        self.logger.debug(
                            f"  [TAG] Adding tag {checked_tag_id} to media ID: {item['media_id']}"
                        )
                        app.add_tags(item["media_id"], checked_tag_id)
                        search_count += 1
                        if search_count >= count:
                            self.logger.debug(
                                f"Reached album-based search count limit ({search_count} >= {count}), breaking."
                            )
                            self.logger.debug("─" * 70)
                            self.logger.debug(
                                f"[END] Finished: {item['title']} ({item['year']}) | ID: {item['media_id']}"
                            )
                            self.logger.debug("─" * 70)
                            self.logger.debug("")
                            break
                else:
                    # Sonarr: search monitored seasons individually
                    searched = False
                    for season in item["seasons"]:
                        if season["monitored"]:
                            self.logger.debug(
                                f"  [SEASON] {season['season_number']}: Searching..."
                            )
                            search_response = app.search_season(
                                item["media_id"], season["season_number"]
                            )
                            self.process_search_response(
                                search_response, item["media_id"], app
                            )
                            searched = True

                    if searched:
                        self.logger.debug(
                            f"  [TAG] Adding tag {checked_tag_id} to media ID: {item['media_id']}"
                        )
                        app.add_tags(item["media_id"], checked_tag_id)
                        search_count += 1
                        if search_count >= count:
                            self.logger.debug(
                                f"Reached series-based search count limit ({search_count} >= {count}), breaking."
                            )
                            self.logger.debug("─" * 70)
                            self.logger.debug(
                                f"[END] Finished: {item['title']} ({item['year']}) | ID: {item['media_id']}"
                            )
                            self.logger.debug("─" * 70)
                            self.logger.debug("")
                            break

                self.logger.debug("─" * 70)
                self.logger.debug(
                    f"[END] Finished: {item['title']} ({item['year']}) | ID: {item['media_id']}"
                )
                self.logger.debug("─" * 70)
                self.logger.debug("")  # Blank line after block
                self.logger.info(
                    f"Finished processing: {item['title']} ({item['year']})"
                )

            self.logger.info(
                f"Completed upgrade operations for {app.instance_name}. Now retrieving download queue..."
            )
            queue = app.get_queue()
            self.logger.debug(f"Queue item count: {len(queue.get('records', []))}")
            queue_dict: List[Dict[str, Any]] = self.process_queue(
                queue, instance_type, media_ids
            )
            self.logger.debug(f"Queue dict item count: {len(queue_dict)}")

            queue_map: Dict[int, List[Dict[str, Any]]] = {}
            for q in queue_dict:
                queue_map.setdefault(q["media_id"], []).append(q)

            for item in filtered_media_dict:
                downloads = {
                    q["download"]: q["torrent_custom_format_score"]
                    for q in queue_map.get(item["media_id"], [])
                }
                output_dict["data"].append(
                    {
                        "media_id": item["media_id"],
                        "title": item["title"],
                        "year": item["year"],
                        "download": downloads,
                    }
                )
        else:
            for item in filtered_media_dict:
                output_dict["data"].append(
                    {
                        "media_id": item["media_id"],
                        "title": item["title"],
                        "year": item["year"],
                        "download": None,
                        "torrent_custom_format_score": None,
                    }
                )
        return output_dict

    def print_output(self, output_dict: Dict[str, Any]) -> None:
        for instance, run_data in output_dict.items():
            if run_data:
                instance_data = run_data.get("data", None)
                if instance_data:
                    table = [[f"{run_data['server_name']}"]]
                    self.logger.info(create_table(table))
                    self.logger.info(
                        f"Upgrade summary for {run_data['server_name']}: {run_data.get('untagged_count', 0)} untagged, {run_data.get('tagged_count', 0)} tagged, {run_data.get('total_count', 0)} total."
                    )
                    for item in instance_data:
                        self.logger.info(f"{item['title']} ({item['year']})")
                        if item["download"]:
                            for download, format_score in item["download"].items():
                                self.logger.info(f"\t{download}\tScore: {format_score}")
                        else:
                            self.logger.info("\tNo upgrades found for this item.")
                        self.logger.info("")
                else:
                    self.logger.info(f"No items found for {instance}.")

    def run(self):
        try:
            if getattr(self.config, "log_level", "INFO").lower() == "debug":
                print_settings(self.logger, self.config)
            if self.config.dry_run:
                table = [["Dry Run"], ["NO CHANGES WILL BE MADE"]]
                self.logger.info(create_table(table))
            if not getattr(self.config, "instances_list", None):
                self.logger.error("No instances found in config file.")
                return
            output: Dict[str, Any] = {}
            for instance_entry in self.config.instances_list:
                instance_name = instance_entry.instance
                if not instance_name:
                    continue

                # Find the instance type and connection details in full_config.instances
                instance_type = None
                instance_cfg = None
                for typ in ["radarr", "sonarr", "lidarr"]:
                    type_dict = getattr(self.full_config.instances, typ, {})
                    if instance_name in type_dict:
                        instance_type = typ
                        instance_cfg = type_dict[instance_name]
                        break

                if not instance_cfg or not instance_type:
                    self.logger.warning(
                        f"Instance '{instance_name}' not found in config!"
                    )
                    continue

                app = create_arr_client(
                    instance_cfg.url,
                    instance_cfg.api,
                    self.logger,
                )
                if app and app.connect_status:
                    result = self.process_instance(instance_type, instance_entry, app)
                    if result:
                        output[instance_name] = result
            self.logger.debug(f"Processed instances: {list(output.keys())}")
            if output:
                self.print_output(output)
                manager = NotificationManager(
                    self.config, self.logger, module_name="upgradinatorr"
                )
                manager.send_notification(output)
        except KeyboardInterrupt:
            print("Keyboard Interrupt detected. Exiting...")
            return
        except Exception:
            self.logger.error("\n\nAn error occurred:\n", exc_info=True)
            self.logger.error("\n\n")
        finally:
            self.logger.log_outro()
