# util/webhook_processor.py

import time
from typing import Optional, Tuple
from urllib.parse import urlparse

from backend.util.config import load_config


class WebhookProcessor:
    """
    Clean webhook processor that only handles validation and routing.
    Business logic is delegated to other components.

    Dedup lives in `db.webhook_cache` (persistent, restart-safe) and is
    handled at the API layer in `backend/api/webhooks.py` before a job is
    ever enqueued. This class only validates payloads and waits for Plex
    availability.
    """

    def __init__(self, logger):
        self.logger = logger
        self.config = load_config()
        general = getattr(self.config, "general", None)
        self.initial_delay = getattr(general, "webhook_initial_delay", 30)
        self.retry_delay = getattr(general, "webhook_retry_delay", 30)
        self.max_retries = getattr(general, "webhook_max_retries", 10)

    def _validate_webhook(
        self, webhook_data: dict, client_info: Optional[dict] = None
    ) -> dict:
        """
        Validate webhook and extract instance information.

        Args:
            webhook_data: Raw webhook data
            client_info: Client connection info

        Returns:
            dict: Validation result with instance info
        """
        log = self.logger.get_adapter("WEBHOOK")

        # Extract media block
        media_block, media_type, media_id = self._extract_media_block(webhook_data)
        if not media_block or not media_type or media_id is None:
            return {
                "success": False,
                "message": "Invalid webhook data - no media block found",
                "error_code": "INVALID_WEBHOOK_DATA",
            }

        # Find matching ARR instance
        instance_info = self._find_arr_instance(client_info)
        if not instance_info["found"]:
            log.error("No matching ARR instance found")
            return {
                "success": False,
                "message": "No matching ARR instance found",
                "error_code": "NO_INSTANCE",
            }

        season_number = self._extract_season_number(webhook_data)

        return {
            "success": True,
            "message": "Webhook validated successfully",
            "media_block": media_block,
            "media_type": media_type,
            "media_id": media_id,
            "instance_info": instance_info,
            "season_number": season_number,
        }

    def _extract_media_block(
        self, webhook_data: dict
    ) -> Tuple[Optional[dict], Optional[str], Optional[int]]:
        """
        Extract media information from webhook data.

        Args:
            webhook_data: Raw webhook data

        Returns:
            tuple: (media_block, media_type, media_id)
        """
        if "series" in webhook_data:
            return webhook_data["series"], "series", webhook_data["series"].get("id")
        elif "movie" in webhook_data:
            return webhook_data["movie"], "movie", webhook_data["movie"].get("id")
        else:
            return None, None, None

    @staticmethod
    def _extract_season_number(webhook_data: dict) -> Optional[int]:
        """
        For Sonarr Download / EpisodeFileImported events, pull the season
        number from `episodes[0].seasonNumber` so downstream processing can
        focus the asset match on the correct season instead of re-matching
        the whole show.

        Returns None for movies, series-add events, or payloads without an
        episodes list — callers treat None as "not season-scoped".
        """
        episodes = webhook_data.get("episodes") or []
        if not episodes:
            return None
        season = episodes[0].get("seasonNumber")
        try:
            return int(season) if season is not None else None
        except (TypeError, ValueError):
            return None

    def _find_arr_instance(self, client_info: Optional[dict] = None) -> dict:
        """
        Find matching ARR instance from client info.

        Args:
            client_info: Client connection information

        Returns:
            dict: Instance lookup result
        """

        def normalize_host(h):
            if not h:
                return h
            h = str(h).lower()
            if h in ("127.0.0.1", "::1", "localhost"):
                return "localhost"
            return h

        # Extract client info
        if client_info:
            host = client_info.get("client_host")
            port = client_info.get("client_port")
            scheme = client_info.get("scheme", "http")
        else:
            return {"found": False, "error": "No client info provided"}

        norm_host = normalize_host(host)
        norm_port = int(port) if port is not None else None

        # Search through configured instances
        instances_config = self.config.instances

        for media_type in ("radarr", "sonarr", "lidarr"):
            media_dict = getattr(instances_config, media_type, {})
            for name, info in media_dict.items():
                if not info.url:
                    continue

                parsed = urlparse(info.url)
                parsed_host = normalize_host(parsed.hostname)

                try:
                    parsed_port = int(parsed.port) if parsed.port is not None else None
                except Exception:
                    parsed_port = None

                if parsed_host == norm_host and parsed_port == norm_port:
                    return {
                        "found": True,
                        "name": name,
                        "type": media_type,
                        "api": info.api,
                        "url": info.url,
                        "host": host,
                        "port": port,
                        "scheme": scheme or parsed.scheme or "http",
                    }

        return {"found": False, "error": "No matching instance"}

    @staticmethod
    def _season_present(plex, media_title: str, year, season_number: int) -> bool:
        """True when `media_title` exists as a show in Plex AND its season
        `season_number` is present with at least one episode (i.e. Plex has
        actually scanned the newly-grabbed season folder, not just the show)."""
        for section in plex.library.sections():
            if getattr(section, "type", None) != "show":
                continue
            try:
                results = section.search(title=media_title)
            except Exception:
                results = []
            for show in results:
                if show.title.lower() != media_title.lower():
                    continue
                if year is not None and getattr(show, "year", None) not in (None, year):
                    continue
                try:
                    seasons = [
                        s
                        for s in show.seasons()
                        if int(getattr(s, "index", -1)) == int(season_number)
                    ]
                    if seasons and seasons[0].episodes():
                        return True
                except Exception:
                    continue
        return False

    def wait_for_plex_availability(
        self, media_title: str, year=None, season_number=None
    ) -> bool:
        """
        Wait for a media item to appear in Plex before processing its posters.
        Uses configurable initial delay and retry logic.

        Args:
            media_title: Title of the media to look for
            year: Optional year for matching
            season_number: When set (Sonarr Download / EpisodeFileImported), wait
                until that specific season folder is scanned — a webhook often
                fires before Plex has indexed a freshly-grabbed season, leaving
                the season poster nowhere to land. When None, falls back to the
                item-level "recently added" check.

        Returns:
            bool: True if the item (or season) was found in Plex
        """
        log = self.logger.get_adapter("WEBHOOK")

        try:
            from plexapi.server import PlexServer

            # Get Plex instances from config
            plex_instances = getattr(self.config.instances, "plex", {})
            if not plex_instances:
                log.debug("No Plex instances configured, skipping availability check")
                return True  # No Plex to check, proceed anyway

            # Wait initial delay before first check
            if self.initial_delay > 0:
                log.debug(f"Waiting {self.initial_delay}s for Plex to scan new media")
                time.sleep(self.initial_delay)

            from backend.util.ssrf_guard import is_safe_url

            # Try each Plex instance
            for name, details in plex_instances.items():
                url = details.url
                token = details.api
                if not url or not token:
                    continue

                safe, reason = is_safe_url(url)
                if not safe:
                    log.warning(f"Refused Plex lookup for instance {name}: {reason}")
                    continue

                for attempt in range(self.max_retries + 1):
                    try:
                        plex = PlexServer(url, token, timeout=10)
                        if season_number is not None:
                            # Season-aware: the show usually already exists, so a
                            # recently-added title check won't fire — verify the
                            # specific season folder has been scanned instead.
                            if self._season_present(
                                plex, media_title, year, season_number
                            ):
                                log.info(
                                    f"Found '{media_title}' Season {season_number} "
                                    "in Plex"
                                )
                                return True
                        else:
                            for section in plex.library.sections():
                                recent = section.recentlyAdded(maxresults=50)
                                for item in recent:
                                    if item.title.lower() == media_title.lower() and (
                                        year is None
                                        or getattr(item, "year", None) == year
                                    ):
                                        log.info(
                                            f"Found '{media_title}' in Plex "
                                            "recently added"
                                        )
                                        return True
                    except Exception as e:
                        log.debug(f"Plex check attempt {attempt + 1} failed: {e}")

                    if attempt < self.max_retries:
                        log.debug(
                            f"Not found in Plex yet, retrying in {self.retry_delay}s "
                            f"(attempt {attempt + 1}/{self.max_retries})"
                        )
                        time.sleep(self.retry_delay)

            target = (
                f"'{media_title}' Season {season_number}"
                if season_number is not None
                else f"'{media_title}'"
            )
            log.debug(f"{target} not found in Plex after {self.max_retries} retries")
            return False

        except ImportError:
            log.debug("plexapi not available, skipping Plex availability check")
            return True
        except Exception as e:
            log.error(f"Error checking Plex availability: {e}")
            return True  # Don't block processing on Plex check failure
