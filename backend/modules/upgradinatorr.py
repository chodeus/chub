# modules/upgradinatorr.py

import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

from backend.util.arr import BaseARRClient, create_arr_client
from backend.util.base_module import ChubModule
from backend.util.database import ChubDB
from backend.util.database.upgradinatorr_progress import UpgradinatorrProgress
from backend.util.helper import create_table, print_settings
from backend.util.logger import Logger
from backend.util.notification import NotificationManager

VALID_STATUSES = {"continuing", "airing", "ended", "canceled", "released"}
VALID_SEARCH_MODES = {"upgrade", "missing", "cutoff"}
VALID_COUNT_MODES = {"series_artist", "season_album"}


class _BufferingLogger:
    """Captures log calls in memory so parallel instances don't interleave
    their output. ``flush_to()`` replays them to the real logger in order.

    Thread-safe: an instance's DB worker thread can log through the same
    buffer concurrently, so appends are guarded by a lock.
    """

    def __init__(self, real_logger: Any = None) -> None:
        self._records: List[Tuple[str, Any, tuple, dict]] = []
        self._lock = threading.Lock()
        # Kept only so __getattr__ can delegate introspection/config calls
        # (isEnabledFor, setLevel, name, ...). The explicit logging methods
        # below are found via normal lookup and never reach __getattr__, so
        # they stay buffered.
        self._real_logger = real_logger

    def _store(self, level: str, msg: Any, args: tuple, kwargs: dict) -> None:
        with self._lock:
            self._records.append((level, msg, args, kwargs))

    def debug(self, msg: Any, *args, **kwargs) -> None:
        self._store("debug", msg, args, kwargs)

    def info(self, msg: Any, *args, **kwargs) -> None:
        self._store("info", msg, args, kwargs)

    def warning(self, msg: Any, *args, **kwargs) -> None:
        self._store("warning", msg, args, kwargs)

    def error(self, msg: Any, *args, **kwargs) -> None:
        self._store("error", msg, args, kwargs)

    def exception(self, msg: Any, *args, **kwargs) -> None:
        kwargs.setdefault("exc_info", True)
        self._store("error", msg, args, kwargs)

    def get_adapter(self, extra: Any = None) -> "_BufferingLogger":
        """Stand in for Logger.get_adapter. The source context
        (DATABASE/WORKER/...) is ignored — it is dropped on flush anyway,
        since records replay through the real logger's plain level methods.
        Returning self keeps every chained call buffered and in order, and is
        chainable because self also provides get_adapter."""
        return self

    def heartbeat(self, msg: Any, *args, **kwargs) -> None:
        self.info(f"[hb] {msg}", *args, **kwargs)

    def log_outro(self) -> None:
        # Only meaningful on the real logger; no-op while buffering.
        pass

    def __getattr__(self, name: str) -> Any:
        """Delegate anything not explicitly defined (e.g. isEnabledFor,
        setLevel, name) to the real logger so the buffer is a faithful
        drop-in. Reads __dict__ directly to avoid recursing through
        __getattr__ before _real_logger is set."""
        real = self.__dict__.get("_real_logger")
        if real is not None:
            return getattr(real, name)
        raise AttributeError(name)

    def flush_to(self, logger: Any) -> None:
        with self._lock:
            records = list(self._records)
            self._records.clear()
        for level, msg, args, kwargs in records:
            getattr(logger, level)(msg, *args, **kwargs)


class Upgradinatorr(ChubModule):
    def __init__(self, logger: Optional[Logger] = None) -> None:
        # Set up the thread-local logger override before super().__init__ runs,
        # since it assigns self.logger (routed through the property setter).
        self._thread_local = threading.local()
        self._real_logger: Any = None
        super().__init__(logger=logger)

    @property
    def logger(self) -> Any:
        """Return the per-thread buffering logger when one is active (parallel
        instance processing), otherwise the real module logger."""
        thread_local = getattr(self, "_thread_local", None)
        if thread_local is not None:
            buffered = getattr(thread_local, "logger", None)
            if buffered is not None:
                return buffered
        return getattr(self, "_real_logger", None)

    @logger.setter
    def logger(self, value: Any) -> None:
        self._real_logger = value

    @staticmethod
    def _get_setting(settings: Any, key: str, default: Any = None) -> Any:
        if isinstance(settings, dict):
            return settings.get(key, default)
        return getattr(settings, key, default)

    @staticmethod
    def _tag_names(item: Dict[str, Any]) -> set:
        return {
            str(tag).strip().lower()
            for tag in item.get("tags", [])
            if tag is not None and str(tag).strip()
        }

    def filter_media(
        self,
        media_dict: List[Dict[str, Any]],
        checked_tag_name: str,
        ignore_tag_name: Optional[str],
        count: int,
        season_monitored_threshold: int,
    ) -> List[Dict[str, Any]]:
        filtered_media_dict: List[Dict[str, Any]] = []
        filter_count: int = 0
        checked_tag = (checked_tag_name or "").strip().lower()
        ignore_tag = (ignore_tag_name or "").strip().lower()
        for item in media_dict:
            if filter_count == count:
                break
            item_tags = self._tag_names(item)
            if (
                checked_tag in item_tags
                or (ignore_tag and ignore_tag in item_tags)
                or not item["monitored"]
                or item["status"] not in VALID_STATUSES
            ):
                reasons = []
                if checked_tag in item_tags:
                    reasons.append("tagged")
                if ignore_tag and ignore_tag in item_tags:
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
                    elif season.get("monitored"):
                        # Lidarr albums (and other leaf-level seasons) carry no
                        # sub-items — the season's own monitored flag is the
                        # authoritative signal.
                        monitored_percentage = 100
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
            self.logger.debug(
                f"Candidate: {item['title']} ({item['year']}) [ID: {item['media_id']}]"
            )
            filter_count += 1
        return filtered_media_dict

    def process_search_response(
        self,
        search_response: Optional[Dict[str, Any]],
        media_id: int,
        app: BaseARRClient,
    ) -> bool:
        if search_response:
            self.logger.debug(
                f"    [CMD] Waiting for command to complete for search response ID: {search_response['id']}"
            )
            ready = app.wait_for_command(search_response["id"])
            if ready:
                self.logger.debug(
                    f"    [CMD] Command completed successfully for search response ID: {search_response['id']}"
                )
                return True
            else:
                self.logger.warning(
                    f"    [CMD] Command did not complete successfully for search response ID: {search_response['id']}"
                )
                return False
        else:
            self.logger.warning(f"No search response for media ID: {media_id}")
            return False

    @staticmethod
    def _history_records(history_response: Any) -> Optional[List[Dict[str, Any]]]:
        if history_response is None:
            return None
        if isinstance(history_response, dict):
            return history_response.get("records", [])
        if isinstance(history_response, list):
            return history_response
        return []

    @staticmethod
    def _download_key(download: Dict[str, Any]) -> Tuple[str, str]:
        return (
            str(download.get("download_id") or ""),
            str(download.get("download") or ""),
        )

    def _history_record_to_download(
        self, record: Dict[str, Any], media_id: int
    ) -> Optional[Dict[str, Any]]:
        data = record.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        download = (
            record.get("sourceTitle")
            or record.get("title")
            or data.get("sourceTitle")
            or data.get("releaseTitle")
            or data.get("downloadClientName")
        )
        if not download:
            return None

        score = record.get("customFormatScore")
        if score is None:
            score = data.get("customFormatScore")

        return {
            "download_id": record.get("downloadId")
            or data.get("downloadId")
            or f"history:{record.get('id', download)}",
            "media_id": media_id,
            "download": download,
            "torrent_custom_format_score": score,
        }

    @staticmethod
    def _is_grabbed_history(record: Dict[str, Any]) -> bool:
        event_type = record.get("eventType")
        if event_type is None:
            return True
        return str(event_type).strip().lower() in {"grabbed", "1"}

    @staticmethod
    def _record_search_attempt(
        search_stats: Optional[Dict[str, int]], success: bool
    ) -> None:
        if search_stats is None:
            return
        search_stats["searches_attempted"] = (
            search_stats.get("searches_attempted", 0) + 1
        )
        key = "searches_succeeded" if success else "searches_failed"
        search_stats[key] = search_stats.get(key, 0) + 1

    @staticmethod
    def _record_search_failure(
        failed_searches: Optional[Dict[int, List[str]]],
        media_id: int,
        label: str,
    ) -> None:
        if failed_searches is None:
            return
        failed_searches.setdefault(media_id, []).append(label)

    def _get_grabbed_downloads(
        self,
        app: BaseARRClient,
        media_id: int,
        instance_type: str,
        season_number: Optional[int] = None,
        album_id: Optional[int] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        try:
            if (
                instance_type == "sonarr"
                and season_number is not None
                and hasattr(app, "get_season_grab_history")
            ):
                history_response = app.get_season_grab_history(media_id, season_number)
            elif (
                instance_type == "lidarr"
                and album_id is not None
                and hasattr(app, "get_album_grab_history")
            ):
                history_response = app.get_album_grab_history(album_id)
            elif hasattr(app, "get_grab_history"):
                history_response = app.get_grab_history(media_id)
            else:
                return None
        except Exception as e:
            self.logger.warning(
                f"Failed to fetch grab history for media ID {media_id}: {e}",
                exc_info=True,
            )
            return None

        records = self._history_records(history_response)
        if records is None:
            return None

        downloads: List[Dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            if not self._is_grabbed_history(record):
                continue
            download = self._history_record_to_download(record, media_id)
            if download:
                downloads.append(download)
        return downloads

    def _capture_new_grabs(
        self,
        grabbed_downloads: Optional[Dict[int, List[Dict[str, Any]]]],
        before_downloads: Optional[List[Dict[str, Any]]],
        after_downloads: Optional[List[Dict[str, Any]]],
        media_id: int,
    ) -> None:
        if (
            grabbed_downloads is None
            or before_downloads is None
            or after_downloads is None
        ):
            return

        before_keys = {self._download_key(download) for download in before_downloads}
        existing_keys = {
            self._download_key(download)
            for download in grabbed_downloads.get(media_id, [])
        }
        for download in after_downloads:
            key = self._download_key(download)
            if key in before_keys or key in existing_keys:
                continue
            grabbed_downloads.setdefault(media_id, []).append(download)
            existing_keys.add(key)

    def _process_sonarr_item(
        self,
        item: Dict[str, Any],
        app: BaseARRClient,
        checked_tag_id: int,
        count: int,
        granular: bool,
        progress_db: Optional[UpgradinatorrProgress],
        search_count: int,
        grabbed_downloads: Optional[Dict[int, List[Dict[str, Any]]]] = None,
        failed_searches: Optional[Dict[int, List[str]]] = None,
        search_stats: Optional[Dict[str, int]] = None,
    ) -> Tuple[int, bool]:
        """Handle one Sonarr series. Returns (new_search_count, budget_hit).

        In series_artist mode: searches every monitored season then tags the
        series once, counting it as a single search toward the budget.

        In season_album mode: each monitored season is a separate search counted
        against the budget. Already-processed seasons (from a previous run) are
        skipped via the progress table. The series is only tagged once every
        monitored season has been searched in this rotation."""
        if not granular:
            searched = False
            all_successful = True
            for season in item["seasons"]:
                if season["monitored"]:
                    season_number = season["season_number"]
                    self.logger.debug(
                        f"[SEARCH] {item['title']} S{season_number}"
                    )
                    before_downloads = self._get_grabbed_downloads(
                        app, item["media_id"], "sonarr", season_number
                    )
                    search_response = app.search_season(item["media_id"], season_number)
                    success = self.process_search_response(
                        search_response, item["media_id"], app
                    )
                    self._record_search_attempt(search_stats, success)
                    if success:
                        after_downloads = self._get_grabbed_downloads(
                            app, item["media_id"], "sonarr", season_number
                        )
                        self._capture_new_grabs(
                            grabbed_downloads,
                            before_downloads,
                            after_downloads,
                            item["media_id"],
                        )
                    else:
                        all_successful = False
                        self._record_search_failure(
                            failed_searches, item["media_id"], f"Season {season_number}"
                        )
                    searched = True
            if searched:
                search_count += 1
                if all_successful:
                    self.logger.debug(
                        f"[TAG] {item['title']} += {checked_tag_id}"
                    )
                    app.add_tags(item["media_id"], checked_tag_id)
                    if progress_db is not None:
                        # Clean up any stale progress rows from a prior granular run.
                        progress_db.clear_for_media(app.instance_name, item["media_id"])
                else:
                    self.logger.warning(
                        f"Not tagging {self._format_item_title(item)} because one or more "
                        "season searches failed."
                    )
            return search_count, search_count >= count

        # Granular: per-season counting + resume support.
        processed = (
            progress_db.get_processed_children(app.instance_name, item["media_id"])
            if progress_db is not None
            else set()
        )
        monitored_seasons = sorted(
            (s for s in item["seasons"] if s.get("monitored")),
            key=lambda s: s.get("season_number", 0),
        )
        remaining = [
            s for s in monitored_seasons if str(s["season_number"]) not in processed
        ]
        if not monitored_seasons:
            return search_count, False
        if not remaining:
            # All monitored seasons searched in earlier runs — finalize.
            self.logger.debug(
                f"[TAG] {item['title']} += {checked_tag_id} (all seasons already processed)"
            )
            app.add_tags(item["media_id"], checked_tag_id)
            if progress_db is not None:
                progress_db.clear_for_media(app.instance_name, item["media_id"])
            return search_count, False

        for season in remaining:
            season_number = season["season_number"]
            # Per-season detail stays at DEBUG — at INFO this is one line per
            # season and floods the log on large libraries.
            self.logger.debug(
                f"  [SEASON] {item['title']} S{season_number}: Searching..."
            )
            before_downloads = self._get_grabbed_downloads(
                app, item["media_id"], "sonarr", season_number
            )
            search_response = app.search_season(item["media_id"], season_number)
            success = self.process_search_response(
                search_response, item["media_id"], app
            )
            self._record_search_attempt(search_stats, success)
            if success:
                after_downloads = self._get_grabbed_downloads(
                    app, item["media_id"], "sonarr", season_number
                )
                self._capture_new_grabs(
                    grabbed_downloads,
                    before_downloads,
                    after_downloads,
                    item["media_id"],
                )
            else:
                self._record_search_failure(
                    failed_searches, item["media_id"], f"Season {season_number}"
                )
            if success and progress_db is not None:
                progress_db.record_processed_child(
                    app.instance_name, item["media_id"], str(season_number)
                )
            search_count += 1
            if search_count >= count:
                # Cut off mid-series: leave untagged so next run resumes here.
                return search_count, True

        if failed_searches and failed_searches.get(item["media_id"]):
            self.logger.warning(
                f"Not tagging {self._format_item_title(item)} because one or more "
                "season searches failed."
            )
            return search_count, False

        # Finished every monitored season this rotation — tag and clear progress.
        self.logger.debug(
            f"[TAG] {item['title']} += {checked_tag_id} (all seasons searched)"
        )
        app.add_tags(item["media_id"], checked_tag_id)
        if progress_db is not None:
            progress_db.clear_for_media(app.instance_name, item["media_id"])
        return search_count, search_count >= count

    def _process_lidarr_item(
        self,
        item: Dict[str, Any],
        app: BaseARRClient,
        checked_tag_id: int,
        count: int,
        granular: bool,
        progress_db: Optional[UpgradinatorrProgress],
        search_count: int,
        grabbed_downloads: Optional[Dict[int, List[Dict[str, Any]]]] = None,
        failed_searches: Optional[Dict[int, List[str]]] = None,
        search_stats: Optional[Dict[str, int]] = None,
    ) -> Tuple[int, bool]:
        """Handle one Lidarr artist. Returns (new_search_count, budget_hit).
        Mirrors _process_sonarr_item but operates on albums (album_id is the
        child key in the progress table)."""
        if not granular:
            searched = False
            all_successful = True
            for album in item["seasons"]:
                if album.get("monitored", False):
                    album_id = album.get("album_id")
                    album_title = album.get(
                        "album_title", f"Album #{album.get('season_number', '?')}"
                    )
                    if album_id:
                        self.logger.debug(
                            f"[SEARCH] {item['title']} — {album_title}"
                        )
                        before_downloads = self._get_grabbed_downloads(
                            app, item["media_id"], "lidarr", album_id=album_id
                        )
                        search_response = app.search_album(album_id)
                        success = self.process_search_response(
                            search_response, item["media_id"], app
                        )
                        self._record_search_attempt(search_stats, success)
                        if success:
                            after_downloads = self._get_grabbed_downloads(
                                app, item["media_id"], "lidarr", album_id=album_id
                            )
                            self._capture_new_grabs(
                                grabbed_downloads,
                                before_downloads,
                                after_downloads,
                                item["media_id"],
                            )
                        else:
                            all_successful = False
                            self._record_search_failure(
                                failed_searches,
                                item["media_id"],
                                f"Album {album_title}",
                            )
                        searched = True
            if searched:
                search_count += 1
                if all_successful:
                    self.logger.debug(
                        f"[TAG] {item['title']} += {checked_tag_id}"
                    )
                    app.add_tags(item["media_id"], checked_tag_id)
                    if progress_db is not None:
                        progress_db.clear_for_media(app.instance_name, item["media_id"])
                else:
                    self.logger.warning(
                        f"Not tagging {item['title']} because one or more album searches failed."
                    )
            return search_count, search_count >= count

        # Granular: per-album counting + resume support.
        processed = (
            progress_db.get_processed_children(app.instance_name, item["media_id"])
            if progress_db is not None
            else set()
        )
        monitored_albums = [
            a for a in item["seasons"] if a.get("monitored") and a.get("album_id")
        ]
        remaining = [a for a in monitored_albums if str(a["album_id"]) not in processed]
        if not monitored_albums:
            return search_count, False
        if not remaining:
            self.logger.debug(
                f"[TAG] {item['title']} += {checked_tag_id} (all albums already processed)"
            )
            app.add_tags(item["media_id"], checked_tag_id)
            if progress_db is not None:
                progress_db.clear_for_media(app.instance_name, item["media_id"])
            return search_count, False

        for album in remaining:
            album_id = album["album_id"]
            album_title = album.get(
                "album_title", f"Album #{album.get('season_number', '?')}"
            )
            self.logger.debug(
                f"  [ALBUM] {item['title']} — {album_title}: Searching..."
            )
            before_downloads = self._get_grabbed_downloads(
                app, item["media_id"], "lidarr", album_id=album_id
            )
            search_response = app.search_album(album_id)
            success = self.process_search_response(
                search_response, item["media_id"], app
            )
            self._record_search_attempt(search_stats, success)
            if success:
                after_downloads = self._get_grabbed_downloads(
                    app, item["media_id"], "lidarr", album_id=album_id
                )
                self._capture_new_grabs(
                    grabbed_downloads,
                    before_downloads,
                    after_downloads,
                    item["media_id"],
                )
            else:
                self._record_search_failure(
                    failed_searches, item["media_id"], f"Album {album_title}"
                )
            if success and progress_db is not None:
                progress_db.record_processed_child(
                    app.instance_name, item["media_id"], str(album_id)
                )
            search_count += 1
            if search_count >= count:
                return search_count, True

        if failed_searches and failed_searches.get(item["media_id"]):
            self.logger.warning(
                f"Not tagging {item['title']} because one or more album searches failed."
            )
            return search_count, False

        self.logger.debug(
            f"[TAG] {item['title']} += {checked_tag_id} (all albums searched)"
        )
        app.add_tags(item["media_id"], checked_tag_id)
        if progress_db is not None:
            progress_db.clear_for_media(app.instance_name, item["media_id"])
        return search_count, search_count >= count

    def process_queue(
        self, queue: Dict[str, Any], instance_type: str, media_ids: List[int]
    ) -> List[Dict[str, Any]]:
        id_type = {"radarr": "movieId", "sonarr": "seriesId", "lidarr": "artistId"}[
            instance_type
        ]
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

    def _get_all_wanted(
        self, app: BaseARRClient, search_mode: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch all pages from the wanted/missing or wanted/cutoff endpoint.

        Page 1 is fetched first (it reports totalRecords); the remaining pages
        are fetched concurrently on private sessions (threadsafe=True) since
        they're independent and the client's shared session is not thread-safe.
        """
        page_size = 200
        fetch_fn = (
            app.get_wanted_missing
            if search_mode == "missing"
            else app.get_wanted_cutoff
        )

        first = fetch_fn(page=1, page_size=page_size)
        if first is None:
            self.logger.warning(
                f"Failed to fetch {search_mode} page 1 from {app.instance_name}; "
                "aborting this Upgradinatorr profile."
            )
            return None
        if not first:
            return []

        all_records: List[Dict[str, Any]] = list(first.get("records", []))
        total = first.get("totalRecords", 0)
        # A page shorter than page_size is the definitive end-of-list signal and
        # does not depend on totalRecords (which the ARR endpoints can report
        # stale or under-counted for the monitored-filtered view).
        if len(all_records) < page_size:
            return all_records

        # Use totalRecords only as a hint for how many pages to fetch
        # concurrently; always fetch at least page 2 so an under-reported total
        # can't truncate the list, and verify the tail sequentially below.
        last_page = max(2, -(-total // page_size))  # ceil division
        remaining_pages = list(range(2, last_page + 1))

        pages: Dict[int, List[Dict[str, Any]]] = {}
        failed = False

        def fetch(page: int):
            return page, fetch_fn(page=page, page_size=page_size, threadsafe=True)

        workers = min(8, len(remaining_pages))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch, p): p for p in remaining_pages}
            for future in as_completed(futures):
                page, result = future.result()
                if result is None:
                    self.logger.warning(
                        f"Failed to fetch {search_mode} page {page} from "
                        f"{app.instance_name}; aborting this Upgradinatorr profile."
                    )
                    failed = True
                else:
                    pages[page] = result.get("records", [])

        if failed:
            return None

        # Reassemble in page order so output is deterministic.
        for p in remaining_pages:
            all_records.extend(pages.get(p, []))

        # Guard against an under-reported totalRecords: if the last computed
        # page still came back full, more records may exist beyond it. Page
        # sequentially until a short/empty page confirms the true end.
        tail = pages.get(last_page, [])
        next_page = last_page + 1
        while len(tail) >= page_size:
            result = fetch_fn(page=next_page, page_size=page_size, threadsafe=True)
            if result is None:
                self.logger.warning(
                    f"Failed to fetch {search_mode} page {next_page} from "
                    f"{app.instance_name}; aborting this Upgradinatorr profile."
                )
                return None
            tail = result.get("records", [])
            all_records.extend(tail)
            next_page += 1

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

            # Prefetch every series' episodes in parallel (one call per series)
            # instead of one blocking call per season inside normalization.
            episode_map: Dict[int, Dict[int, List[Dict[str, Any]]]] = {}
            if hasattr(app, "_fetch_episodes_by_series"):
                episode_map = app._fetch_episodes_by_series(list(series_map.keys()))

            def _wanted_episode_lookup(sid, sn, _map=episode_map):
                return _map.get(sid, {}).get(sn, [])

            result = []
            for series_data in series_map.values():
                wanted_seasons = series_data.pop("_wanted_seasons", set())
                normalized = normalize_arr_media(
                    series_data,
                    tags,
                    arr_type="sonarr",
                    include_episode=True,
                    episode_lookup=_wanted_episode_lookup,
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
                    album_list.append(
                        {
                            "season_number": idx,
                            "album_id": album.get("id"),
                            "album_title": album.get("title", ""),
                            "foreign_album_id": album.get("foreignAlbumId", ""),
                            "monitored": album.get("monitored", True),
                            "episode_data": [],
                        }
                    )
                normalized = normalize_arr_media(
                    artist_data,
                    tags,
                    arr_type="lidarr",
                    logger=self.logger,
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
        count: int = self._get_setting(instance_settings, "count", 0) or 0
        checked_tag_name: str = (
            self._get_setting(instance_settings, "tag_name", "") or "checked"
        ).strip()
        ignore_tag_name: str = (
            self._get_setting(instance_settings, "ignore_tag", "") or "ignore"
        ).strip()
        unattended: bool = bool(
            self._get_setting(instance_settings, "unattended", False)
        )
        season_monitored_threshold = (
            self._get_setting(instance_settings, "season_monitored_threshold", None)
            or 0
        )
        search_mode: str = (
            self._get_setting(instance_settings, "search_mode", "upgrade") or "upgrade"
        )
        count_mode: str = (
            self._get_setting(instance_settings, "count_mode", "series_artist")
            or "series_artist"
        )

        if count <= 0:
            self.logger.warning(
                f"Skipping {app.instance_name}: count must be greater than 0."
            )
            return None

        if search_mode not in VALID_SEARCH_MODES:
            self.logger.warning(
                f"Invalid search_mode '{search_mode}', falling back to 'upgrade'."
            )
            search_mode = "upgrade"

        if count_mode not in VALID_COUNT_MODES:
            self.logger.warning(
                f"Invalid count_mode '{count_mode}', falling back to 'series_artist'."
            )
            count_mode = "series_artist"
        # Granular mode only meaningful for sonarr/lidarr; radarr items always
        # cost 1 search regardless.
        granular = count_mode == "season_album" and instance_type in (
            "sonarr",
            "lidarr",
        )

        self.logger.info(
            f"Gathering media from {app.instance_name} ({instance_type}) "
            f"[mode: {search_mode}]"
        )

        wanted_count: Optional[int] = None
        if search_mode in ("missing", "cutoff"):
            wanted_records = self._get_all_wanted(app, search_mode)
            if wanted_records is None:
                return None
            wanted_count = len(wanted_records)
            media_dict = self._convert_wanted_to_media_dict(
                wanted_records, instance_type, app
            )
        elif app.instance_type.lower() in ("sonarr", "lidarr"):
            media_dict = app.get_all_media(include_episode=True)
        else:
            media_dict = app.get_all_media()
        checked_tag_id: int = app.get_tag_id_from_name(checked_tag_name)
        if ignore_tag_name:
            app.get_tag_id_from_name(ignore_tag_name)

        # In granular mode, `count` caps season/album searches, not parents — so
        # we need to keep the parent cap loose enough that we can consume the
        # budget even when each parent only contributes a few unprocessed children.
        filter_cap = len(media_dict) if granular else count

        filtered_media_dict: List[Dict[str, Any]] = self.filter_media(
            media_dict,
            checked_tag_name,
            ignore_tag_name,
            filter_cap,
            season_monitored_threshold,
        )
        if not filtered_media_dict and unattended:
            self.logger.info(
                f"All media for {app.instance_name} is already tagged—removing tags for unattended operation."
            )
            media_ids = [item["media_id"] for item in media_dict]
            if self.config.dry_run:
                self.logger.info(
                    "[DRY RUN] Would remove checked tags for unattended operation."
                )
            else:
                self.logger.info("All media is tagged. Removing tags...")
                app.remove_tags(media_ids, checked_tag_id)
                if instance_type in ("sonarr", "lidarr"):
                    try:
                        with ChubDB(logger=self.logger) as db:
                            db.upgradinatorr_progress.clear_for_instance(
                                app.instance_name
                            )
                            self.logger.debug(
                                f"Cleared upgradinatorr_progress rows for {app.instance_name} (unattended reset)."
                            )
                    except Exception as e:
                        self.logger.warning(
                            f"Failed to clear upgradinatorr_progress for {app.instance_name}: {e}"
                        )
            if search_mode in ("missing", "cutoff"):
                wanted_records = self._get_all_wanted(app, search_mode)
                if wanted_records is None:
                    return None
                media_dict = self._convert_wanted_to_media_dict(
                    wanted_records, instance_type, app
                )
            elif app.instance_type.lower() in ("sonarr", "lidarr"):
                media_dict = app.get_all_media(include_episode=True)
            else:
                media_dict = app.get_all_media()
            filter_cap = len(media_dict) if granular else count
            filtered_media_dict = self.filter_media(
                media_dict,
                checked_tag_name,
                ignore_tag_name,
                filter_cap,
                season_monitored_threshold,
            )

        if not filtered_media_dict and not unattended:
            self.logger.info(f"No media left to process for {app.instance_name}.")
            self.logger.warning(
                f"No media found for {app.instance_name}. Reason: nothing left to tag."
            )
            return None

        if wanted_count is not None:
            self.logger.info(
                f"Found {wanted_count} {search_mode} item(s); "
                f"selected {len(filtered_media_dict)} candidate(s) (search budget: {count})."
            )
        else:
            self.logger.info(
                f"Selected {len(filtered_media_dict)} candidate(s) from "
                f"{len(media_dict)} total (search budget: {count})."
            )
        if media_dict:
            total_count = len(media_dict)
            for item in media_dict:
                if checked_tag_name.strip().lower() in self._tag_names(item):
                    tagged_count += 1
                else:
                    untagged_count += 1

        output_dict: Dict[str, Any] = {
            "server_name": app.instance_name,
            "tagged_count": tagged_count,
            "untagged_count": untagged_count,
            "total_count": total_count,
            "searches_attempted": 0,
            "searches_succeeded": 0,
            "searches_failed": 0,
            "data": [],
        }

        if not self.config.dry_run:
            search_count: int = 0
            searched_items: List[Dict[str, Any]] = []
            grabbed_downloads: Dict[int, List[Dict[str, Any]]] = {}
            failed_searches: Dict[int, List[str]] = {}
            search_stats: Dict[str, int] = {
                "searches_attempted": 0,
                "searches_succeeded": 0,
                "searches_failed": 0,
            }
            progress_db: Optional[UpgradinatorrProgress] = None
            db_ctx: Optional[ChubDB] = None
            # Open the progress DB for any sonarr/lidarr run so that leftover
            # rows from a previous granular run get cleared when those parents
            # are tagged in series_artist mode.
            if instance_type in ("sonarr", "lidarr"):
                db_ctx = ChubDB(logger=self.logger)
                db_ctx.__enter__()
                progress_db = db_ctx.upgradinatorr_progress

            try:
                for item in filtered_media_dict:
                    if self.is_cancelled():
                        break
                    self.logger.debug("")  # Blank line before block
                    self.logger.debug("═" * 70)
                    self.logger.debug(
                        f"[PROCESSING] {item['title']} ({item['year']}) | ID: {item['media_id']}"
                    )
                    self.logger.debug("═" * 70)
                    self.logger.info(
                        f"Processing: {self._format_item_title(item)} [ID: {item['media_id']}]"
                    )
                    searched_items.append(item)

                    budget_hit = False

                    if item["seasons"] is None:
                        # Movies (Radarr) or artists without album data
                        self.logger.debug(f"[SEARCH] {item['title']}")
                        before_downloads = self._get_grabbed_downloads(
                            app, item["media_id"], instance_type
                        )
                        search_response = app.search_media(item["media_id"])
                        success = self.process_search_response(
                            search_response, item["media_id"], app
                        )
                        self._record_search_attempt(search_stats, success)
                        if success:
                            after_downloads = self._get_grabbed_downloads(
                                app, item["media_id"], instance_type
                            )
                            self._capture_new_grabs(
                                grabbed_downloads,
                                before_downloads,
                                after_downloads,
                                item["media_id"],
                            )
                            self.logger.debug(
                                f"[TAG] {item['title']} += {checked_tag_id}"
                            )
                            app.add_tags(item["media_id"], checked_tag_id)
                        else:
                            self._record_search_failure(
                                failed_searches, item["media_id"], "Media search"
                            )
                            self.logger.warning(
                                f"Not tagging {self._format_item_title(item)} "
                                "because the media search failed."
                            )
                        search_count += 1
                        if search_count >= count:
                            budget_hit = True
                    elif instance_type == "lidarr":
                        search_count, budget_hit = self._process_lidarr_item(
                            item,
                            app,
                            checked_tag_id,
                            count,
                            granular,
                            progress_db,
                            search_count,
                            grabbed_downloads,
                            failed_searches,
                            search_stats,
                        )
                    else:
                        search_count, budget_hit = self._process_sonarr_item(
                            item,
                            app,
                            checked_tag_id,
                            count,
                            granular,
                            progress_db,
                            search_count,
                            grabbed_downloads,
                            failed_searches,
                            search_stats,
                        )

                    if budget_hit:
                        self.logger.debug(
                            f"Reached search count limit ({search_count} >= {count}), breaking."
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
            finally:
                if db_ctx is not None:
                    db_ctx.__exit__(None, None, None)

            self.logger.debug(
                f"Completed upgrade operations for {app.instance_name}. "
                "Now reconciling grabbed downloads and current queue..."
            )
            searched_ids = [item["media_id"] for item in searched_items]
            # get_queue() returns None on an API failure — don't discard this
            # instance's already-completed searches over a crash on None.
            queue = app.get_queue() or {}
            self.logger.debug(f"Queue item count: {len(queue.get('records', []))}")
            queue_dict: List[Dict[str, Any]] = self.process_queue(
                queue, instance_type, searched_ids
            )
            self.logger.debug(f"Queue dict item count: {len(queue_dict)}")

            queue_map: Dict[int, List[Dict[str, Any]]] = {}
            for q in queue_dict:
                queue_map.setdefault(q["media_id"], []).append(q)

            for item in searched_items:
                downloads = {}
                for q in grabbed_downloads.get(item["media_id"], []):
                    downloads[q["download"]] = q["torrent_custom_format_score"]
                for q in queue_map.get(item["media_id"], []):
                    downloads.setdefault(
                        q["download"], q["torrent_custom_format_score"]
                    )
                output_dict["data"].append(
                    {
                        "media_id": item["media_id"],
                        "title": item["title"],
                        "year": item["year"],
                        "download": downloads,
                        "search_failures": failed_searches.get(item["media_id"], []),
                    }
                )
            output_dict.update(search_stats)
            tagged_in_run = len(searched_items) - sum(
                1 for v in failed_searches.values() if v
            )
            self.logger.info(
                f"   → {search_stats['searches_attempted']} searched, "
                f"{max(tagged_in_run, 0)} tagged"
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
                        "search_failures": [],
                    }
                )
        return output_dict

    @staticmethod
    def _format_item_title(item: Dict[str, Any]) -> str:
        year = item.get("year")
        if year:
            return f"{item['title']} ({year})"
        return str(item["title"])

    def print_output(self, output_dict: Dict[str, Any]) -> None:
        for instance, run_data in output_dict.items():
            if not run_data:
                continue
            instance_data = run_data.get("data", None)
            if not instance_data:
                self.logger.info(f"No items found for {instance}.")
                continue

            table = [[f"{run_data['server_name']}"]]
            self.logger.info(create_table(table))
            self.logger.info(
                f"Searches: {run_data.get('searches_attempted', 0)} attempted, "
                f"{run_data.get('searches_succeeded', 0)} completed, "
                f"{run_data.get('searches_failed', 0)} failed | "
                f"Parents: {run_data.get('untagged_count', 0)} untagged, "
                f"{run_data.get('tagged_count', 0)} tagged, "
                f"{run_data.get('total_count', 0)} total."
            )

            with_grabs = [it for it in instance_data if it.get("download")]
            with_failures = [it for it in instance_data if it.get("search_failures")]
            no_grabs = [
                it
                for it in instance_data
                if not it.get("download") and not it.get("search_failures")
            ]

            if with_grabs:
                grab_total = sum(len(it["download"]) for it in with_grabs)
                self.logger.info(
                    f"[GRABBED] {grab_total} download(s) across {len(with_grabs)} item(s):"
                )
                for item in with_grabs:
                    self.logger.info(f"  {self._format_item_title(item)}")
                    for download, format_score in item["download"].items():
                        self.logger.info(f"    Score {format_score} — {download}")

            if with_failures:
                self.logger.info(f"[FAILED] {len(with_failures)} item(s):")
                for item in with_failures:
                    failures = ", ".join(item["search_failures"])
                    self.logger.warning(
                        f"  {self._format_item_title(item)} — {failures}"
                    )

            if no_grabs:
                titles = ", ".join(self._format_item_title(it) for it in no_grabs)
                self.logger.info(
                    f"[NO GRABS] {len(no_grabs)} item(s) searched, nothing grabbed: {titles}"
                )

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

            # Phase 1: resolve config + connect to every enabled instance
            # sequentially, so connection/skip logging stays ordered.
            jobs: List[Tuple[str, str, Any, BaseARRClient]] = []
            for instance_entry in self.config.instances_list:
                if not self._get_setting(instance_entry, "enabled", True):
                    label = self._get_setting(
                        instance_entry, "label", ""
                    ) or self._get_setting(instance_entry, "instance", "unknown")
                    self.logger.info(
                        f"Skipping disabled Upgradinatorr profile: {label}"
                    )
                    continue

                instance_name = self._get_setting(instance_entry, "instance", "")
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
                    jobs.append((instance_name, instance_type, instance_entry, app))

            # Phase 2: process instances in parallel. Each instance writes to
            # its own buffered logger (via the thread-local override) so their
            # log lines don't interleave; buffers are flushed in config order
            # once every instance finishes, keeping output grouped per instance.
            output: Dict[str, Any] = {}
            if jobs:

                def _run_instance(
                    index: int,
                    instance_name: str,
                    instance_type: str,
                    instance_entry: Any,
                    app: BaseARRClient,
                ) -> Tuple[int, str, Optional[Dict[str, Any]], _BufferingLogger]:
                    buf = _BufferingLogger(self._real_logger)
                    self._thread_local.logger = buf
                    # Route the ARR client's own logging (incl. its nested
                    # prefetch threads) through this instance's buffer too, so
                    # concurrent instances' client log lines don't interleave.
                    # Each job has its own client, so this rebind is per-instance.
                    prev_app_logger = getattr(app, "logger", None)
                    app.logger = buf
                    try:
                        result = self.process_instance(
                            instance_type, instance_entry, app
                        )
                    except Exception:
                        buf.error(
                            f"An error occurred processing {instance_name}:\n"
                            f"{traceback.format_exc()}"
                        )
                        result = None
                    finally:
                        # Worker threads are reused by the pool — clear the
                        # override so the next task starts with a fresh buffer.
                        app.logger = prev_app_logger
                        self._thread_local.logger = None
                    return index, instance_name, result, buf

                results: Dict[
                    int, Tuple[str, Optional[Dict[str, Any]], _BufferingLogger]
                ] = {}
                with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
                    futures = [
                        pool.submit(_run_instance, i, name, typ, entry, app)
                        for i, (name, typ, entry, app) in enumerate(jobs)
                    ]
                    for future in as_completed(futures):
                        index, name, result, buf = future.result()
                        results[index] = (name, result, buf)

                for i in range(len(jobs)):
                    name, result, buf = results[i]
                    buf.flush_to(self._real_logger)
                    if result:
                        output[name] = result

            self.logger.debug(f"Processed instances: {list(output.keys())}")
            if output:
                self.print_output(output)
                manager = NotificationManager(
                    self.full_config, self.logger, module_name="upgradinatorr"
                )
                manager.send_notification(output)
        except KeyboardInterrupt:
            self.logger.info("Keyboard Interrupt detected. Exiting...")
            return
        except Exception:
            self.logger.error("\n\nAn error occurred:\n", exc_info=True)
            self.logger.error("\n\n")
        finally:
            self.logger.log_outro()
