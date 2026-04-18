# util/webhook_processor.py

import hashlib
import json
import threading
import time
from typing import Optional, Tuple
from urllib.parse import urlparse

from backend.util.config import load_config
from backend.util.database import ChubDB


class WebhookProcessor:
    """
    Clean webhook processor that only handles validation and routing.
    Business logic is delegated to other components.
    """

    # Simple deduplication cache
    _cache = {}
    _cache_lock = threading.Lock()

    def __init__(self, logger):
        self.logger = logger
        self.config = load_config()
        general = getattr(self.config, "general", None)
        self.initial_delay = getattr(general, "webhook_initial_delay", 30)
        self.retry_delay = getattr(general, "webhook_retry_delay", 60)
        self.max_retries = getattr(general, "webhook_max_retries", 3)

    def process_webhook(
        self, webhook_data: dict, client_info: Optional[dict] = None
    ) -> dict:
        """
        Process webhook and enqueue job for background processing.

        Args:
            webhook_data: Raw webhook data from ARR
            client_info: Optional client info from API layer

        Returns:
            dict: Standardized success/failure response
        """
        log = self.logger.get_adapter("WEBHOOK")

        # Validate and extract basic info
        validation_result = self._validate_webhook(webhook_data, client_info)
        if not validation_result["success"]:
            return validation_result

        # Check for duplicates (simple debouncing)
        if self._is_duplicate(validation_result["cache_key"], webhook_data):
            log.debug("Skipping duplicate webhook (debounced)")
            return {
                "success": True,
                "message": "Webhook debounced (duplicate)",
                "data": {"debounced": True},
            }

        # Enqueue job for background processing
        job_payload = {
            "webhook_data": webhook_data,
            "client_info": client_info,
            "instance_info": validation_result["instance_info"],
        }

        with ChubDB(logger=self.logger) as db:
            enqueue_result = db.worker.enqueue_job(
                table_name="jobs", payload=job_payload, job_type="webhook"
            )

        if enqueue_result["success"]:
            job_id = enqueue_result["data"]["job_id"]
            log.info(f"Webhook enqueued as job {job_id}")
            return {
                "success": True,
                "message": "Webhook enqueued for processing",
                "data": {"job_id": job_id},
            }
        else:
            log.error(f"Failed to enqueue webhook: {enqueue_result['message']}")
            return {
                "success": False,
                "message": "Failed to enqueue webhook",
                "error_code": "ENQUEUE_FAILED",
            }

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

        # Create cache key for deduplication
        cache_key = (instance_info["type"], instance_info["name"], media_type, media_id)

        return {
            "success": True,
            "message": "Webhook validated successfully",
            "media_block": media_block,
            "media_type": media_type,
            "media_id": media_id,
            "instance_info": instance_info,
            "cache_key": cache_key,
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

    def _is_duplicate(self, cache_key: tuple, webhook_data: dict) -> bool:
        """
        Check if this webhook is a duplicate (simple debouncing).

        Args:
            cache_key: Unique cache key for this webhook
            webhook_data: Raw webhook data

        Returns:
            bool: True if duplicate
        """
        media_block, _, _ = self._extract_media_block(webhook_data)
        if not media_block:
            return False

        # Simple hash of relevant fields
        hash_data = {
            k: media_block.get(k)
            for k in ["title", "year", "tmdb_id", "tvdb_id", "imdb_id"]
            if k in media_block
        }
        content_hash = hashlib.sha256(
            json.dumps(hash_data, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

        debounce_window = getattr(self, "initial_delay", 5)
        if debounce_window > 10:
            debounce_window = (
                5  # Keep dedup window short, use initial_delay for processing
            )

        now = time.time()
        with self._cache_lock:
            if cache_key in self._cache:
                prev_hash, prev_time = self._cache[cache_key]
                if prev_hash == content_hash and (now - prev_time) < debounce_window:
                    return True

            self._cache[cache_key] = (content_hash, now)

            # Simple cleanup - remove entries older than 30 seconds
            cutoff = now - 30
            expired_keys = [k for k, (_, t) in self._cache.items() if t < cutoff]
            for k in expired_keys:
                del self._cache[k]

        return False

    def wait_for_plex_availability(self, media_title: str, year=None) -> bool:
        """
        Wait for a media item to appear in Plex's recently added items.
        Uses configurable initial delay and retry logic.

        Args:
            media_title: Title of the media to look for
            year: Optional year for matching

        Returns:
            bool: True if item was found in Plex
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

            # Try each Plex instance
            for name, details in plex_instances.items():
                url = details.url
                token = details.api
                if not url or not token:
                    continue

                for attempt in range(self.max_retries + 1):
                    try:
                        plex = PlexServer(url, token, timeout=10)
                        for section in plex.library.sections():
                            recent = section.recentlyAdded(maxresults=50)
                            for item in recent:
                                if item.title.lower() == media_title.lower() and (
                                    year is None or getattr(item, "year", None) == year
                                ):
                                    log.info(
                                        f"Found '{media_title}' in Plex recently added"
                                    )
                                    return True
                    except Exception as e:
                        log.debug(f"Plex check attempt {attempt + 1} failed: {e}")

                    if attempt < self.max_retries:
                        log.debug(
                            f"Item not found in Plex, retrying in {self.retry_delay}s "
                            f"(attempt {attempt + 1}/{self.max_retries})"
                        )
                        time.sleep(self.retry_delay)

            log.debug(
                f"'{media_title}' not found in Plex after {self.max_retries} retries"
            )
            return False

        except ImportError:
            log.debug("plexapi not available, skipping Plex availability check")
            return True
        except Exception as e:
            log.error(f"Error checking Plex availability: {e}")
            return True  # Don't block processing on Plex check failure
