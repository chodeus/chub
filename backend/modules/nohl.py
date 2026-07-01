# modules/nohl.py

import os
import re
from typing import Any, Dict, List, Optional

from backend.util.arr import create_arr_client
from backend.util.base_module import ChubModule
from backend.util.constants import episode_regex, season_number_regex
from backend.util.helper import (
    create_table,
    normalize_titles,
    print_json,
    print_settings,
    progress,
)
from backend.util.logger import Logger
from backend.util.notification import NotificationManager

VIDEO_EXTS = (".mkv", ".mp4")
VALID_SOURCE_MODES = {"scan", "resolve"}
SEASON_EPISODE_REGEX = re.compile(r"\b[Ss](\d{1,4})[Ee](\d{1,2})\b")


class Nohl(ChubModule):
    def __init__(self, logger: Optional[Logger] = None) -> None:
        super().__init__(logger=logger)

    @staticmethod
    def _video_files_in_dir(path: str, logger: Logger) -> List[str]:
        try:
            files = [
                file
                for file in os.listdir(path)
                if os.path.isfile(os.path.join(path, file))
                and not file.startswith(".")
                and file.lower().endswith(VIDEO_EXTS)
            ]
        except OSError as e:
            logger.error(f"Error reading directory '{path}': {e}")
            return []

        nohl_files = []
        for file in files:
            file_path = os.path.join(path, file)
            try:
                st = os.stat(file_path)
                if st.st_nlink == 1:
                    nohl_files.append(file_path)
            except OSError as e:
                logger.warning(f"Skipping file '{file_path}': {e}")
        return nohl_files

    @staticmethod
    def _season_number_from_folder(folder: str) -> Optional[int]:
        season = season_number_regex.search(folder)
        if not season:
            return None
        try:
            return int(season.group(1) or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _episode_number_from_file(file_path: str) -> Optional[int]:
        episode_match = re.search(episode_regex, os.path.basename(file_path))
        if episode_match is None:
            return None
        try:
            return int(episode_match.group(1))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _season_episode_from_file(file_path: str) -> Optional[tuple[int, int]]:
        episode_match = SEASON_EPISODE_REGEX.search(os.path.basename(file_path))
        if episode_match is None:
            return None
        try:
            return int(episode_match.group(1)), int(episode_match.group(2))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _root_hint(path: str) -> str:
        parts = [part for part in os.path.normpath(path).split(os.sep) if part]
        if len(parts) >= 2:
            return os.path.join(*parts[-2:])
        return os.path.normpath(path)

    @staticmethod
    def _config_list(value: Any) -> List[str]:
        if isinstance(value, str):
            return [
                item.strip()
                for item in re.split(r"[\n,]", value)
                if item and item.strip()
            ]
        if value is None:
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _search_operation_count(
        search_media: List[Dict[str, Any]], instance_type: str
    ) -> int:
        if instance_type == "sonarr":
            return sum(len(item.get("seasons", [])) for item in search_media)
        return len(search_media)

    @staticmethod
    def _apply_search_limit(
        data_list: Dict[str, List[Dict[str, Any]]],
        search_limit: Any,
        instance_type: str,
        logger: Logger,
    ) -> None:
        if search_limit is None:
            return
        try:
            limit = int(search_limit)
        except (TypeError, ValueError):
            logger.warning(f"Invalid search limit '{search_limit}', ignoring limit.")
            return

        search_media = data_list["search_media"]
        operation_count = Nohl._search_operation_count(search_media, instance_type)
        if operation_count <= limit:
            return

        logger.info(
            f"Search limit applied: reducing search operations from {operation_count} to {limit}."
        )
        if instance_type != "sonarr":
            data_list["search_media"] = search_media[: max(limit, 0)]
            return

        remaining = max(limit, 0)
        limited_items = []
        for item in search_media:
            if remaining <= 0:
                break
            seasons = item.get("seasons", [])
            limited_seasons = seasons[:remaining]
            if limited_seasons:
                limited_item = dict(item)
                limited_item["seasons"] = limited_seasons
                limited_items.append(limited_item)
                remaining -= len(limited_seasons)
        data_list["search_media"] = limited_items

    @staticmethod
    def _season_entry(season_number: int, nohl_files: List[str]) -> Dict[str, Any]:
        episodes = [
            episode
            for episode in (
                Nohl._episode_number_from_file(file_path) for file_path in nohl_files
            )
            if episode is not None
        ]
        episodes.sort(key=int)
        return {
            "season_number": season_number,
            "episodes": episodes,
            "season_pack": bool(nohl_files and not episodes),
            "nohl": nohl_files,
        }

    @staticmethod
    def find_nohl_files(
        path: str, logger: Logger
    ) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        path_basename = os.path.basename(path.rstrip("/"))
        nohl_data: Dict[str, List[Dict[str, Any]]] = {"movies": [], "series": []}
        logger.debug(f"Scanning directory: {path}")
        try:
            entries = [
                i for i in os.listdir(path) if os.path.isdir(os.path.join(path, i))
            ]
        except FileNotFoundError as e:
            logger.error(f"Error: {e}")
            return None
        for item in progress(
            entries,
            desc=f"Searching '{path_basename}'",
            unit="item",
            total=len(entries),
            logger=logger,
        ):
            if item.startswith("."):
                continue
            # Find and remove year from directory name for title
            year_match = re.search(r"(?:^|[. (_-])((?:19|20)\d{2})(?:$|[. )_-])", item)
            if year_match:
                try:
                    year = int(year_match.group(1))
                    title = item[: year_match.start(1)].rstrip(" .-_()")
                except ValueError:
                    year = 0
                    title = item
            else:
                year = 0
                title = item
            asset_list: Dict[str, Any] = {
                "title": title,
                "year": year,
                "normalized_title": normalize_titles(title),
                "root_path": Nohl._root_hint(path.rstrip(os.sep)),
                "source_path": path.rstrip(os.sep),
                "path": os.path.join(path, item),
            }
            item_path = os.path.join(path, item)
            try:
                child_names = os.listdir(item_path)
            except OSError as e:
                logger.error(f"Error reading directory '{item_path}': {e}")
                continue

            sub_folders = [
                sub_folder
                for sub_folder in child_names
                if os.path.isdir(os.path.join(item_path, sub_folder))
                and not sub_folder.startswith(".")
            ]
            season_folders = [
                (sub_folder, season_number)
                for sub_folder in sub_folders
                for season_number in [Nohl._season_number_from_folder(sub_folder)]
                if season_number is not None
            ]
            direct_nohl_files = Nohl._video_files_in_dir(item_path, logger)

            flat_episode_groups: Dict[int, Dict[str, Any]] = {}
            for file_path in direct_nohl_files:
                parsed = Nohl._season_episode_from_file(file_path)
                if parsed is None:
                    continue
                season_number, episode_number = parsed
                flat_episode_groups.setdefault(
                    season_number, {"episodes": [], "nohl": []}
                )
                flat_episode_groups[season_number]["episodes"].append(episode_number)
                flat_episode_groups[season_number]["nohl"].append(file_path)

            if season_folders or flat_episode_groups:
                asset_list["season_info"] = []
                for sub_folder, season_number in season_folders:
                    sub_folder_path = os.path.join(item_path, sub_folder)
                    nohl_files = Nohl._video_files_in_dir(sub_folder_path, logger)
                    if nohl_files:
                        logger.debug(
                            f"Found {len(nohl_files)} non-hardlinked files in '{sub_folder_path}'"
                        )
                    if nohl_files:
                        asset_list["season_info"].append(
                            Nohl._season_entry(season_number, nohl_files)
                        )
                for season_number, season_data in flat_episode_groups.items():
                    season_data["episodes"].sort(key=int)
                    asset_list["season_info"].append(
                        {
                            "season_number": season_number,
                            "episodes": season_data["episodes"],
                            "season_pack": False,
                            "nohl": season_data["nohl"],
                        }
                    )
                if asset_list["season_info"] and any(
                    season["nohl"] for season in asset_list["season_info"]
                ):
                    nohl_data["series"].append(asset_list)
            else:
                nohl_files = direct_nohl_files
                if nohl_files:
                    logger.debug(
                        f"Found {len(nohl_files)} non-hardlinked files in '{item_path}'"
                    )
                asset_list["nohl"] = nohl_files
                if nohl_files:
                    nohl_data["movies"].append(asset_list)
        for series in nohl_data["series"]:
            if "season_info" in series:
                series["season_info"].sort(key=lambda s: int(s["season_number"]))
                for season in series["season_info"]:
                    if "episodes" in season:
                        season["episodes"].sort(key=int)
        return nohl_data

    @staticmethod
    def build_instance_index(instances, instances_config):
        index = {}
        # Iterate over known ARR instance types from the InstancesConfig model
        for instance_type in ("radarr", "sonarr"):
            configs = getattr(instances_config, instance_type, {})
            if configs:
                for name, cfg in configs.items():
                    index[name] = (instance_type, cfg)
        for i in instances:
            if isinstance(i, dict):
                for name, value in i.items():
                    index[name] = ("plex", value)
        return index

    @staticmethod
    def parse_source_entries(config):
        source_entries = []
        for entry in config.source_dirs:
            if isinstance(entry, dict):
                path = entry.get("path", "")
                mode = entry.get("mode") or "resolve"
            elif hasattr(entry, "path"):
                path = entry.path
                mode = getattr(entry, "mode", None) or "resolve"
            else:
                path = str(entry)
                mode = "resolve"

            path = str(path).strip()
            mode = str(mode).strip().lower()
            if not path:
                continue
            if mode not in VALID_SOURCE_MODES:
                raise ValueError(
                    f"Invalid Nohl source directory mode '{mode}' for path '{path}'. "
                    "Expected 'scan' or 'resolve'."
                )
            source_entries.append({"path": path, "mode": mode})

        scan_entries = [e for e in source_entries if e["mode"] == "scan"]
        resolve_entries = [e for e in source_entries if e["mode"] == "resolve"]
        return scan_entries, resolve_entries

    @staticmethod
    def scan_entries(scan_entries, logger: Logger):
        scanned_results: Dict[str, Any] = {}
        for entry in scan_entries:
            path = entry["path"]
            results = Nohl.find_nohl_files(path, logger)
            scanned_results[path] = results or {"movies": [], "series": []}
        return scanned_results

    @staticmethod
    def aggregate_nohl_results(resolve_entries, logger: Logger):
        nohl_list: Dict[str, List[Dict[str, Any]]] = {"movies": [], "series": []}
        for entry in resolve_entries:
            path = entry["path"]
            results = Nohl.find_nohl_files(path, logger) or {"movies": [], "series": []}
            if results and (results["movies"] or results["series"]):
                nohl_list["movies"].extend(results["movies"])
                nohl_list["series"].extend(results["series"])
            else:
                logger.warning(
                    f"No non-hardlinked files found in {path}, skipping resolution for this path"
                )
                continue
        return nohl_list

    @staticmethod
    def handle_searches(app, search_list, instance_type, logger, config):
        logger.info(
            f"Initiating search for {len(search_list)} items in {instance_type.title()}."
        )
        searched_for: List[Dict[str, Any]] = []
        searches = 0
        per_item_info_logs = []

        for item in progress(
            search_list,
            desc="Searching...",
            unit="item",
            total=len(search_list),
            logger=logger,
        ):
            title = item["title"]
            year = item["year"]

            logger.debug(
                f"Processing [{instance_type}] '{title}' ({year}) [media_id={item.get('media_id')}]"
            )

            if instance_type == "radarr":
                if not item.get("file_ids"):
                    logger.warning(
                        f" No movie file ID found for '{title}' ({year}) - skipping."
                    )
                    continue
                if config.dry_run:
                    logger.debug(
                        f"[Dry Run] Would search and delete: '{title}' ({year}), file IDs: {item['file_ids']}"
                    )
                    searched_for.append(item)
                    searches += 1
                    per_item_info_logs.append(
                        f"[Dry Run] Would search and delete: '{title}' ({year}), file IDs: {item['file_ids']}"
                    )
                else:
                    logger.debug(
                        f" Deleting file IDs: {item['file_ids']} for '{title}' ({year}) [media_id={item.get('media_id')}]"
                    )
                    app.delete_movie_file(item["file_ids"])
                    logger.debug(
                        f" Refreshing movie: '{title}' ({year}) [media_id={item['media_id']}]"
                    )
                    results = app.refresh_items(item["media_id"])
                    command_id = (
                        results.get("id") if isinstance(results, dict) else None
                    )
                    ready = bool(command_id and app.wait_for_command(command_id))
                    if not ready:
                        logger.warning(
                            f" Refresh for '{title}' ({year}) was not confirmed in "
                            "time; searching anyway so the deleted file is not left "
                            "permanently missing."
                        )
                    logger.debug(
                        f" Initiating search for movie: '{title}' ({year}), media_id: {item['media_id']}"
                    )
                    app.search_media(item["media_id"])
                    searched_for.append(item)
                    searches += 1
                    per_item_info_logs.append(
                        f" Searched: '{title}' ({year}) [media_id={item['media_id']}]"
                    )
            elif instance_type == "sonarr":
                seasons = item["seasons"]
                if not seasons:
                    logger.warning(
                        f" No seasons found for '{title}' ({year}) - skipping."
                    )
                    continue
                searched_this_item = False
                for season in seasons:
                    snum = season["season_number"]
                    season_pack = season.get("season_pack", False)
                    file_ids = list(
                        {
                            ep.get("episode_file_id")
                            for ep in season["episode_data"]
                            if ep.get("episode_file_id")
                        }
                    )
                    episode_ids = [
                        ep.get("episode_id")
                        for ep in season["episode_data"]
                        if ep.get("episode_id")
                    ]
                    episode_numbers = [
                        ep.get("episode_number") for ep in season["episode_data"]
                    ]
                    if not file_ids:
                        logger.warning(
                            f" No episode file IDs found for '{title}' ({year}) Season {snum} - skipping."
                        )
                        continue
                    if season_pack:
                        if config.dry_run:
                            logger.debug(
                                f"[Dry Run] Would search season pack: '{title}' ({year}) Season {snum} [media_id={item.get('media_id')}]"
                            )
                            per_item_info_logs.append(
                                f"[Dry Run] Would search season pack: '{title}' ({year}) Season {snum} [media_id={item.get('media_id')}]"
                            )
                            searched_this_item = True
                        else:
                            logger.debug(
                                f" Deleting episode file IDs: {file_ids} for Season {snum} of '{title}' ({year}) [media_id={item.get('media_id')}]"
                            )
                            app.delete_episode_files(file_ids)
                            logger.debug(
                                f" Refreshing series: '{title}' ({year}) [media_id={item['media_id']}]"
                            )
                            results = app.refresh_items(item["media_id"])
                            command_id = (
                                results.get("id") if isinstance(results, dict) else None
                            )
                            ready = bool(
                                command_id and app.wait_for_command(command_id)
                            )
                            if not ready:
                                logger.warning(
                                    f" Refresh for season pack '{title}' ({year}) Season {snum} was not confirmed in time; searching anyway so the deleted files are not left permanently missing."
                                )
                            logger.debug(
                                f" Initiating season pack search for: '{title}' ({year}) Season {snum} [media_id={item['media_id']}]"
                            )
                            app.search_season(item["media_id"], snum)
                            per_item_info_logs.append(
                                f" Searched season pack: '{title}' ({year}) Season {snum} [media_id={item['media_id']}]"
                            )
                            searched_this_item = True
                    else:
                        if config.dry_run:
                            logger.debug(
                                f"[Dry Run] Would search episodes {episode_numbers} of '{title}' ({year}) Season {snum} [media_id={item.get('media_id')}]"
                            )
                            per_item_info_logs.append(
                                f"[Dry Run] Would search episodes {episode_numbers} of '{title}' ({year}) Season {snum} [media_id={item.get('media_id')}]"
                            )
                            searched_this_item = True
                        else:
                            if not episode_ids:
                                logger.warning(
                                    f" No episode IDs found for '{title}' ({year}) Season {snum} - skipping."
                                )
                                continue
                            logger.debug(
                                f" Deleting episode file IDs: {file_ids} for episodes {episode_numbers} in Season {snum} of '{title}' ({year}) [media_id={item.get('media_id')}]"
                            )
                            app.delete_episode_files(file_ids)
                            logger.debug(
                                f" Refreshing series: '{title}' ({year}) [media_id={item['media_id']}]"
                            )
                            results = app.refresh_items(item["media_id"])
                            command_id = (
                                results.get("id") if isinstance(results, dict) else None
                            )
                            ready = bool(
                                command_id and app.wait_for_command(command_id)
                            )
                            if not ready:
                                logger.warning(
                                    f" Refresh for episodes '{title}' ({year}) Season {snum} was not confirmed in time; searching anyway so the deleted files are not left permanently missing."
                                )
                            logger.debug(
                                f" Initiating episode search for: '{title}' ({year}) Episodes {episode_ids} in Season {snum} [media_id={item['media_id']}]"
                            )
                            app.search_episodes(episode_ids)
                            per_item_info_logs.append(
                                f" Searched episodes {episode_numbers} of '{title}' ({year}) Season {snum} [media_id={item['media_id']}]"
                            )
                            searched_this_item = True
                if searched_this_item:
                    searched_for.append(item)
                    searches += 1

        logger.debug(
            f"Total searches performed: {searches} for {instance_type.title()}."
        )
        if per_item_info_logs:
            logger.debug("Searched items summary:")
            for msg in per_item_info_logs:
                logger.debug(msg)
        return searched_for

    @staticmethod
    def filter_media(app, media_dict, nohl_data, instance_type, config, logger):
        logger.debug(
            f"Filtering {len(nohl_data)} non-hardlinked items against {len(media_dict)} media items from {instance_type.title()}."
        )
        quality_profiles = app.get_quality_profile_names() or {}
        exclude_profile_ids = [
            quality_profiles[profile]
            for profile in Nohl._config_list(getattr(config, "exclude_profiles", []))
            if profile in quality_profiles
        ]

        excluded_movies = set(Nohl._config_list(getattr(config, "exclude_movies", [])))
        excluded_series = set(Nohl._config_list(getattr(config, "exclude_series", [])))

        def title_matches(media_item, nohl_item):
            nohl_title = nohl_item.get("normalized_title")
            candidates = {
                media_item.get("normalized_title"),
                media_item.get("normalized_folder"),
            }
            candidates.update(media_item.get("normalized_alternate_titles") or [])
            return nohl_title in {candidate for candidate in candidates if candidate}

        def year_matches(media_item, nohl_item):
            nohl_year = nohl_item.get("year") or 0
            if not nohl_year:
                return True
            years = {
                media_item.get("year"),
                media_item.get("secondary_year"),
            }
            return nohl_year in {year for year in years if year}

        def root_matches(media_item, nohl_item):
            media_root = media_item.get("root_folder") or ""
            if not media_root:
                return True

            item_path = nohl_item.get("path") or ""
            try:
                root_norm = os.path.normcase(os.path.normpath(media_root))
                item_norm = os.path.normcase(os.path.normpath(item_path))
                if item_norm == root_norm or item_norm.startswith(root_norm + os.sep):
                    return True
            except (TypeError, ValueError):
                pass

            root_hint = nohl_item.get("root_path") or ""
            return bool(root_hint and root_hint in media_root)

        def build_season_filtering(media_season, file_season):
            season_data = []
            filtered_seasons = []
            if not media_season.get("monitored"):
                filtered_seasons.append(
                    {
                        "season_number": media_season["season_number"],
                        "monitored": False,
                    }
                )
            else:
                if file_season.get("season_pack"):
                    # season_pack = non-hardlinked files with unparseable episode
                    # numbers. Only delete the whole season when every on-disk
                    # episode is non-hardlinked; else skip so hardlinked (seeding)
                    # files are not destroyed too.
                    nohl_count = len(file_season.get("nohl") or [])
                    ondisk_episodes = [
                        episode
                        for episode in media_season.get("episode_data", [])
                        if episode.get("episode_file_id")
                    ]
                    if nohl_count < len(ondisk_episodes):
                        logger.warning(
                            f"Season {media_season['season_number']} of "
                            f"'{media_item.get('title', '')}' has {nohl_count} "
                            f"non-hardlinked file(s) but {len(ondisk_episodes)} "
                            "episode file(s) on disk and no parseable episode "
                            "numbers — skipping to avoid deleting hardlinked "
                            "(seeding) episodes. Rename files to SxxExx or handle "
                            "this season manually."
                        )
                        episode_data = []
                    else:
                        episode_data = [
                            episode
                            for episode in media_season.get("episode_data", [])
                            if episode.get("monitored")
                            and episode.get("episode_file_id")
                            and episode.get("episode_id")
                        ]
                    filtered_episodes = [
                        episode
                        for episode in media_season.get("episode_data", [])
                        if not episode.get("monitored")
                    ]
                    if filtered_episodes:
                        filtered_seasons.append(
                            {
                                "season_number": media_season["season_number"],
                                "monitored": True,
                                "episodes": filtered_episodes,
                            }
                        )
                    if episode_data:
                        season_data.append(
                            {
                                "season_number": media_season["season_number"],
                                "season_pack": True,
                                "episode_data": episode_data,
                            }
                        )
                else:
                    episode_set = set(file_season.get("episodes", []))
                    filtered_episodes = []
                    episode_data = []
                    for episode in media_season.get("episode_data", []):
                        if episode.get("episode_number") not in episode_set:
                            continue
                        if not episode.get("monitored"):
                            filtered_episodes.append(episode)
                        elif episode.get("episode_file_id") and episode.get(
                            "episode_id"
                        ):
                            episode_data.append(episode)
                    if filtered_episodes:
                        filtered_seasons.append(
                            {
                                "season_number": media_season["season_number"],
                                "monitored": True,
                                "episodes": filtered_episodes,
                            }
                        )
                    if episode_data:
                        season_data.append(
                            {
                                "season_number": media_season["season_number"],
                                "season_pack": False,
                                "episode_data": episode_data,
                            }
                        )
            return season_data, filtered_seasons

        data_list = {"search_media": [], "filtered_media": []}

        # Index media by every normalized title variant (title, folder,
        # alternate titles) so each nohl item only examines plausible matches
        # instead of scanning the whole library — was O(n_nohl × n_media).
        # title_matches() is still called below as a guard, so semantics are
        # identical; this only narrows which media items it runs against.
        title_index = {}
        for media_item in media_dict:
            variants = {
                media_item.get("normalized_title"),
                media_item.get("normalized_folder"),
            }
            variants.update(media_item.get("normalized_alternate_titles") or [])
            for variant in {v for v in variants if v}:
                title_index.setdefault(variant, []).append(media_item)

        for nohl_item in progress(
            nohl_data,
            desc="Filtering media...",
            unit="item",
            total=len(nohl_data),
            logger=logger,
        ):
            for media_item in title_index.get(nohl_item.get("normalized_title"), ()):
                if title_matches(media_item, nohl_item) and year_matches(
                    media_item, nohl_item
                ):
                    if not root_matches(media_item, nohl_item):
                        logger.debug(
                            f"Skipped: '{media_item['title']}' ({media_item['year']}) [root folder mismatch]"
                        )
                        continue

                    reasons = []
                    if not media_item.get("monitored", True):
                        reasons.append("not monitored")
                    if (
                        instance_type == "radarr"
                        and excluded_movies
                        and media_item["title"] in excluded_movies
                    ):
                        reasons.append("excluded by title")
                    if (
                        instance_type == "sonarr"
                        and excluded_series
                        and media_item["title"] in excluded_series
                    ):
                        reasons.append("excluded by title")
                    if media_item.get("quality_profile") in exclude_profile_ids:
                        reasons.append("excluded by quality profile")

                    if reasons:
                        data_list["filtered_media"].append(
                            {
                                "title": media_item["title"],
                                "year": media_item["year"],
                                "monitored": media_item["monitored"],
                                "excluded": any(
                                    x in reasons for x in ["excluded by title"]
                                ),
                                "quality_profile": (
                                    next(
                                        (
                                            name
                                            for name, pid in quality_profiles.items()
                                            if pid == media_item.get("quality_profile")
                                        ),
                                        str(media_item.get("quality_profile")),
                                    )
                                    if media_item.get("quality_profile")
                                    in exclude_profile_ids
                                    else None
                                ),
                            }
                        )
                        logger.debug(
                            f"Filtered out: '{media_item['title']}' ({media_item['year']}), reasons: {', '.join(reasons)}"
                        )
                        continue

                    if instance_type == "radarr":
                        file_ids = media_item["file_id"]
                        if not file_ids:
                            data_list["filtered_media"].append(
                                {
                                    "title": media_item["title"],
                                    "year": media_item["year"],
                                    "monitored": media_item["monitored"],
                                    "excluded": False,
                                    "quality_profile": None,
                                    "missing_file_id": True,
                                }
                            )
                            logger.warning(
                                f"Filtered out: '{media_item['title']}' ({media_item['year']}), missing movie file ID"
                            )
                            continue
                        data_list["search_media"].append(
                            {
                                "media_id": media_item["media_id"],
                                "title": media_item["title"],
                                "year": media_item["year"],
                                "file_ids": file_ids,
                            }
                        )
                        logger.debug(
                            f"Will process '{media_item['title']}' ({media_item['year']}), file_ids={file_ids}, media_id={media_item['media_id']}"
                        )
                    elif instance_type == "sonarr":
                        media_seasons_info = media_item.get("seasons") or []
                        file_season_info = nohl_item.get("season_info") or []
                        season_data = []
                        filtered_seasons = []
                        for media_season in media_seasons_info:
                            for file_season in file_season_info:
                                if (
                                    media_season["season_number"]
                                    == file_season["season_number"]
                                ):
                                    sdata, sfiltered = build_season_filtering(
                                        media_season, file_season
                                    )
                                    season_data.extend(sdata)
                                    filtered_seasons.extend(sfiltered)
                        if filtered_seasons:
                            data_list["filtered_media"].append(
                                {
                                    "title": media_item["title"],
                                    "year": media_item["year"],
                                    "seasons": filtered_seasons,
                                }
                            )
                            logger.debug(
                                f"Filtered out: '{media_item['title']}' ({media_item['year']}) -- unmonitored/filtered seasons: {[s['season_number'] for s in filtered_seasons]}"
                            )
                        if season_data:
                            data_list["search_media"].append(
                                {
                                    "media_id": media_item["media_id"],
                                    "title": media_item["title"],
                                    "year": media_item["year"],
                                    "monitored": media_item["monitored"],
                                    "seasons": season_data,
                                }
                            )
                            logger.debug(
                                f" Will process '{media_item['title']}' ({media_item['year']}), seasons: {[s['season_number'] for s in season_data]}, media_id={media_item['media_id']}"
                            )

        Nohl._apply_search_limit(
            data_list, getattr(config, "searches", None), instance_type, logger
        )

        logger.debug(
            f"Filtering complete. Searchable items: {len(data_list['search_media'])}, "
            f"search operations: {Nohl._search_operation_count(data_list['search_media'], instance_type)}, "
            f"Filtered/excluded items: {len(data_list['filtered_media'])}"
        )
        return data_list

    @staticmethod
    def handle_messages(
        output: Dict[str, Any], logger: Logger, print_files: bool = True
    ) -> None:
        # Print scanned section
        if output.get("scanned", {}):
            logger.info(create_table([["Scanned Non-Hardlinked Files"]]))
            for path, results in output.get("scanned", {}).items():
                logger.info(f"Scanning results for: {path}")
                for item in results.get("movies", []):
                    nohl_count = len(item.get("nohl", []))
                    logger.info(
                        f"{item['title']} ({item['year']}) [{nohl_count} file(s)]"
                    )
                    if print_files and item.get("nohl"):
                        for file_path in item["nohl"]:
                            logger.info(f"\t{os.path.basename(file_path)}")
                    logger.info("")
                for item in results.get("series", []):
                    logger.info(f"{item['title']} ({item['year']})")
                    for season in item.get("season_info", []):
                        if season.get("nohl"):
                            nohl_count = len(season["nohl"])
                            logger.info(
                                f"\tSeason {season['season_number']} [{nohl_count} file(s)]"
                            )
                            if print_files:
                                for file_path in season["nohl"]:
                                    logger.info(f"\t\t{os.path.basename(file_path)}")
                    logger.info("")
        # Output resolved and summary
        has_results = any(
            instance.get("data", {}).get("search_media")
            or instance.get("data", {}).get("filtered_media")
            for instance in output.get("resolved", {}).values()
        )
        if has_results:
            logger.info(create_table([["Resolved ARR Actions"]]))
            for instance, instance_data in output.get("resolved", {}).items():
                search_media = instance_data["data"]["search_media"]
                filtered_media = instance_data["data"]["filtered_media"]
                # Output searched ARR media
                if search_media:
                    for search_item in search_media:
                        if instance_data["instance_type"] == "radarr":
                            logger.info(
                                f"{search_item['title']} ({search_item['year']})"
                            )
                            logger.info("\tDeleted and searched.\n")
                        else:
                            logger.info(
                                f"{search_item['title']} ({search_item['year']})"
                            )
                            if search_item.get("seasons", None):
                                for season in search_item["seasons"]:
                                    if season["season_pack"]:
                                        logger.info(
                                            f"\tSeason {season['season_number']}, deleted and searched."
                                        )
                                    else:
                                        logger.info(
                                            f"\tSeason {season['season_number']}"
                                        )
                                        for episode in season["episode_data"]:
                                            logger.info(
                                                f"\t   Episode {episode['episode_number']}, deleted and searched."
                                            )
                                    logger.info("")
                table = [["Filtered Media"]]
                if filtered_media:
                    logger.debug(create_table(table))
                    for filtered_item in filtered_media:
                        monitored = filtered_item.get("monitored", None)
                        logger.debug(
                            f"{filtered_item['title']} ({filtered_item['year']})"
                        )
                        if monitored is False:
                            logger.debug("\tSkipping, not monitored.")
                        elif filtered_item.get("excluded", None):
                            logger.debug("\tSkipping, excluded.")
                        elif filtered_item.get("quality_profile", None):
                            logger.debug(
                                f"\tSkipping, quality profile: {filtered_item['quality_profile']}"
                            )
                        elif filtered_item.get("seasons", None):
                            for season in filtered_item["seasons"]:
                                if season["monitored"] is False:
                                    logger.debug(
                                        f"\tSeason {season['season_number']}, skipping, not monitored."
                                    )
                                elif season.get("episodes", None):
                                    logger.debug(f"\tSeason {season['season_number']}")
                                    for episode in season["episodes"]:
                                        logger.debug(
                                            f"\t   Episode {episode['episode_number']}, skipping, not monitored."
                                        )
                                    logger.debug("")
                else:
                    logger.debug(
                        f"No filtered files for {instance_data['server_name']}"
                    )
                logger.debug("")
        summary = output.get("summary", {})
        if not all(value == 0 for value in summary.values()):
            logger.info(
                create_table(
                    [
                        ["Metric", "Count"],
                        [
                            "Total Non-Hardlinked Movies",
                            summary.get("total_scanned_movies", 0),
                        ],
                        [
                            "Total Non-Hardlinked Episodes",
                            summary.get("total_scanned_series", 0),
                        ],
                        [
                            "Total Resolved Movies",
                            summary.get("total_resolved_movies", 0),
                        ],
                        [
                            "Total Resolved Episodes",
                            summary.get("total_resolved_series", 0),
                        ],
                    ]
                )
            )
        else:
            logger.info("\n\n\t\t✅ Congratulations, there is nothing to report.\n\n")

    @staticmethod
    def build_summary(scanned_results, output_dict):
        total_scanned_movies = sum(
            len(movie.get("nohl", []))
            for path, results in scanned_results.items()
            for movie in results.get("movies", [])
        )
        total_scanned_series = sum(
            sum(len(season.get("nohl", [])) for season in series.get("season_info", []))
            for path, results in scanned_results.items()
            for series in results.get("series", [])
        )
        resolved_movies = 0
        resolved_episodes = 0
        for instance, instance_data in output_dict.items():
            search_media = instance_data["data"].get("search_media", [])
            if instance_data["instance_type"] == "radarr":
                resolved_movies += len(search_media)
            elif instance_data["instance_type"] == "sonarr":
                for search_item in search_media:
                    if "seasons" in search_item:
                        for season in search_item["seasons"]:
                            resolved_episodes += len(season.get("episode_data", []))
        summary = {
            "total_scanned_movies": total_scanned_movies,
            "total_scanned_series": total_scanned_series,
            "total_resolved_movies": resolved_movies,
            "total_resolved_series": resolved_episodes,
        }
        return summary

    @staticmethod
    def dump_debug_json(output_dict, logger: Logger):
        table = [["Debug JSON Payloads"]]
        logger.debug(create_table(table))
        print_json(output_dict, logger, "nohl", "output_dict")

    @classmethod
    def process_arr_instances(
        cls, config, nohl_list, logger, full_config_instances=None
    ):
        output_dict: Dict[str, Any] = {}
        if config.instances:
            instance_index = cls.build_instance_index(
                config.instances, full_config_instances
            )
            for instance in config.instances:
                instance_name = (
                    instance if isinstance(instance, str) else list(instance.keys())[0]
                )
                if instance_name not in instance_index:
                    logger.warning(
                        f"Instance '{instance_name}' not found in config. Skipping."
                    )
                    continue
                instance_type, instance_settings = instance_index[instance_name]
                if instance_type not in ("radarr", "sonarr"):
                    continue
                # Use attribute access for Pydantic InstanceDetail models
                inst_url = getattr(instance_settings, "url", None) or (
                    instance_settings.get("url")
                    if isinstance(instance_settings, dict)
                    else None
                )
                inst_api = getattr(instance_settings, "api", None) or (
                    instance_settings.get("api")
                    if isinstance(instance_settings, dict)
                    else None
                )
                app = create_arr_client(inst_url, inst_api, logger)
                if not (app and app.connect_status):
                    logger.warning(f"Skipping {instance_name} (not connected)")
                    continue
                server_name = app.get_instance_name()
                table = [[f"{server_name}"]]
                logger.info(create_table(table))
                nohl_data = (
                    nohl_list["movies"]
                    if instance_type == "radarr"
                    else nohl_list["series"]
                    if instance_type == "sonarr"
                    else None
                )
                if not nohl_data:
                    logger.info(
                        f"No non-hardlinked files found for server: {server_name}"
                    )
                    continue
                media_dict = (
                    app.get_all_media(include_episode=True)
                    if instance_type == "sonarr"
                    else app.get_all_media()
                )
                if not media_dict:
                    logger.info(f"No media found for server: {server_name}")
                    continue
                data_list = cls.filter_media(
                    app, media_dict, nohl_data, instance_type, config, logger
                )
                search_list = data_list.get("search_media", [])
                if search_list:
                    search_list = cls.handle_searches(
                        app, search_list, instance_type, logger, config
                    )
                    data_list["search_media"] = search_list
                output_dict[instance_name] = {
                    "server_name": server_name,
                    "instance_type": instance_type,
                    "data": data_list,
                }
                logger.debug(
                    f"{server_name} processing complete. Search media: {len(data_list['search_media'])}, Filtered: {len(data_list['filtered_media'])}"
                )
        return output_dict

    def run(self):
        try:
            if self.config.log_level.lower() == "debug":
                print_settings(self.logger, self.config)
            if self.config.dry_run:
                table = [["Dry Run"], ["NO CHANGES WILL BE MADE"]]
                self.logger.info(create_table(table))
            self.logger.debug("Logger initialized. Starting main process.")

            scan_entries_list, resolve_entries_list = self.parse_source_entries(
                self.config
            )
            if self.is_cancelled():
                self.logger.info("Cancellation requested, stopping nohl.")
                return
            scanned_results = self.scan_entries(scan_entries_list, self.logger)
            if self.is_cancelled():
                self.logger.info("Cancellation requested after scan phase.")
                return
            nohl_list = self.aggregate_nohl_results(resolve_entries_list, self.logger)
            if self.is_cancelled():
                self.logger.info("Cancellation requested before ARR phase.")
                return
            output_dict = self.process_arr_instances(
                self.config,
                nohl_list,
                self.logger,
                full_config_instances=self.full_config.instances,
            )
            if self.config.log_level.lower() == "debug":
                self.dump_debug_json(output_dict, self.logger)
            summary = self.build_summary(scanned_results, output_dict)
            final_output = {
                "scanned": scanned_results,
                "resolved": output_dict,
                "summary": summary,
            }
            self.handle_messages(
                final_output, self.logger, print_files=self.config.print_files
            )
            manager = NotificationManager(self.full_config, self.logger, module_name="nohl")
            manager.send_notification(final_output)
        except KeyboardInterrupt:
            self.logger.info("Keyboard Interrupt detected. Exiting...")
            raise
        except Exception:
            self.logger.error("\n\nAn error occurred:\n", exc_info=True)
            self.logger.error("\n\n")
            raise
        finally:
            self.logger.log_outro()
