# util/webhook_processor.py

import ipaddress
import socket
import time
from typing import Optional, Tuple
from urllib.parse import urlparse

from backend.util.config import load_config

# Short-lived DNS cache for resolving a configured instance hostname (e.g. a
# Docker service name like "sonarr") to IP(s), so an inbound webhook's peer IP
# can be matched to the instance that sent it. A TTL keeps container-IP churn
# honest without doing a lookup on every webhook.
_DNS_CACHE: dict = {}
_DNS_TTL_SECONDS = 60


def _normalize_host(h):
    if not h:
        return h
    h = str(h).lower()
    if h in ("127.0.0.1", "::1", "localhost"):
        return "localhost"
    return h


def _resolve_ips(host: Optional[str]) -> frozenset:
    """Resolve ``host`` to a set of IP strings, with a short TTL cache.

    Returns the host itself when it is already an IP literal, and an empty set
    when it cannot be resolved — callers treat an empty set as "no match", never
    a crash, so a DNS blip fails closed rather than mis-routing.
    """
    if not host:
        return frozenset()
    try:
        ipaddress.ip_address(host)
        return frozenset({host})
    except ValueError:
        pass
    now = time.time()
    cached = _DNS_CACHE.get(host)
    if cached and cached[0] > now:
        return cached[1]
    try:
        ips = frozenset(info[4][0] for info in socket.getaddrinfo(host, None))
    except (socket.gaierror, OSError):
        ips = frozenset()
    _DNS_CACHE[host] = (now + _DNS_TTL_SECONDS, ips)
    return ips


def _host_matches(url: Optional[str], norm_peer_host) -> bool:
    """True when the connection's (normalized) peer host is the same machine the
    configured ``url`` points at — by literal host equality first (IP-configured,
    same-host, or localhost) and then by DNS-resolving the configured hostname
    (a Docker service name resolves to the container IP the webhook came from)."""
    if not url or not norm_peer_host:
        return False
    parsed = urlparse(url)
    if _normalize_host(parsed.hostname) == norm_peer_host:
        return True
    return any(
        _normalize_host(ip) == norm_peer_host for ip in _resolve_ips(parsed.hostname)
    )


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

        # Find matching ARR instance (scoped to the payload's media type)
        instance_info = self._find_arr_instance(client_info, media_type)
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

    def _find_arr_instance(
        self, client_info: Optional[dict] = None, media_type: Optional[str] = None
    ) -> dict:
        """
        Resolve which configured *arr instance a webhook came from.

        Ordered and fail-closed:
          1. Explicit ``?instance=<label>`` / ``X-Chub-Instance`` override →
             direct lookup. The reliable option behind a reverse proxy, where
             the peer IP is the proxy's, not the arr's.
          2. Peer-IP match: resolve each candidate instance's URL host (a Docker
             service name like ``sonarr`` included) to IP(s) and compare against
             the connection's peer IP. Exactly one match wins.
          3. Single-instance fallback: if the payload's media type has exactly
             one configured instance, use it — covers single-instance
             reverse-proxy setups the IP match can't see.

        Anything ambiguous (peer IP matches >1 instance, or no match with
        several candidates) returns not-found: the arr media id is
        instance-scoped, so mis-routing a webhook would fetch the wrong item or
        404 rather than fail loudly.

        The old host+port equality check is gone: a connection's *source* port is
        never the arr's *listen* port, and ``client_port`` was only ever
        populated from a non-standard ``X-Service-Port`` header, so it could not
        match a real Sonarr/Radarr webhook.

        Args:
            client_info: Client connection information.
            media_type: ``"series"`` or ``"movie"`` from the payload; scopes the
                candidate pool to sonarr / radarr respectively. When ``None``
                (legacy callers) all buckets are searched.

        Returns:
            dict: Instance lookup result.
        """
        if not client_info:
            return {"found": False, "error": "No client info provided"}

        peer_host = _normalize_host(client_info.get("client_host"))
        override = (client_info.get("instance_override") or "").strip()

        if media_type == "series":
            buckets = ("sonarr",)
        elif media_type == "movie":
            buckets = ("radarr",)
        else:
            buckets = ("radarr", "sonarr", "lidarr")

        instances_config = self.config.instances
        pool = []
        for bucket in buckets:
            for name, info in getattr(instances_config, bucket, {}).items():
                if not info.url or getattr(info, "enabled", True) is False:
                    continue
                pool.append((name, bucket, info))

        def _resolved(name, bucket, info):
            return {
                "found": True,
                "name": name,
                "type": bucket,
                "api": info.api,
                "url": info.url,
                "host": client_info.get("client_host"),
                "scheme": client_info.get("scheme") or "http",
            }

        # 1) Explicit override — fail closed if it names nothing eligible.
        if override:
            for name, bucket, info in pool:
                if name.lower() == override.lower():
                    return _resolved(name, bucket, info)
            return {
                "found": False,
                "error": f"instance override {override!r} not found",
            }

        # 2) Peer-IP match (DNS-resolved). Exactly one candidate must match.
        matches = [c for c in pool if _host_matches(c[2].url, peer_host)]
        if len(matches) == 1:
            return _resolved(*matches[0])
        if len(matches) > 1:
            return {"found": False, "error": "peer IP matched multiple instances"}

        # 3) Exactly one instance of this media type → unambiguous target.
        if len(pool) == 1:
            return _resolved(*pool[0])

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

            # Validate the configured Plex targets once.
            targets = []
            for name, details in plex_instances.items():
                url = details.url
                token = details.api
                if not url or not token:
                    continue
                safe, reason = is_safe_url(url)
                if not safe:
                    log.warning(f"Refused Plex lookup for instance {name}: {reason}")
                    continue
                targets.append((name, url, token))

            # Share ONE retry/sleep budget across all instances: each attempt
            # tries every instance and returns on the first hit. The retry loop
            # was previously nested INSIDE the per-instance loop, so M instances
            # multiplied the wait to M × max_retries × retry_delay — an item that
            # only ever lands on the last instance blocked the webhook thread for
            # (M-1) full retry cycles before even checking it.
            for attempt in range(self.max_retries + 1):
                for name, url, token in targets:
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
                        log.debug(
                            f"Plex check attempt {attempt + 1} failed for {name}: {e}"
                        )

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
