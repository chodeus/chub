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

# Cache of an instance's self-reported `instanceName` (arr /system/status),
# keyed by URL. Used only to tell apart several instances that share a peer IP
# (same host, different listen ports) — the connection can't reveal the listen
# port, so the payload's instanceName is the disambiguator. Only successful
# lookups are cached, so a transient arr outage never suppresses a valid name.
_NAME_CACHE: dict = {}
_NAME_TTL_SECONDS = 300


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


def _peer_is_trusted(peer_ip: Optional[str], trusted_proxies) -> bool:
    """True when ``peer_ip`` matches a configured trusted-proxy entry. Entries
    are IPs/CIDRs, or the token ``"private"`` for any RFC1918 / loopback /
    link-local address (the safe default for homelab Docker proxies)."""
    if not peer_ip:
        return False
    try:
        ip = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    for entry in trusted_proxies or []:
        e = (entry or "").strip().lower()
        if not e:
            continue
        if e == "private":
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return True
            continue
        try:
            net = ipaddress.ip_network(e, strict=False)
        except ValueError:
            continue
        if ip.version == net.version and ip in net:
            return True
    return False


def resolve_client_host(peer_ip, forwarded_for, trusted_proxies):
    """The effective client IP for instance matching.

    Honors ``X-Forwarded-For`` only when the immediate peer is a trusted proxy,
    so a reverse proxy (Traefik/nginx/Caddy) forwards the arr's real IP instead
    of masking every webhook behind the proxy's own IP. Uses the left-most XFF
    entry (the original client). Falls back to the peer IP when there is no
    proxy, no XFF header, or the peer is not trusted — so a forged XFF from an
    untrusted (e.g. public) caller is ignored.
    """
    if not peer_ip or not forwarded_for:
        return peer_ip
    if not _peer_is_trusted(peer_ip, trusted_proxies):
        return peer_ip
    parts = [p.strip() for p in str(forwarded_for).split(",") if p.strip()]
    return parts[0] if parts else peer_ip


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

        # Find matching ARR instance (scoped to the payload's media type;
        # instanceName / applicationUrl break a same-IP, different-port tie).
        instance_info = self._find_arr_instance(
            client_info,
            media_type,
            webhook_data.get("instanceName"),
            webhook_data.get("applicationUrl"),
        )
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
        self,
        client_info: Optional[dict] = None,
        media_type: Optional[str] = None,
        instance_name: Optional[str] = None,
        application_url: Optional[str] = None,
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
          3. Same peer IP, several instances (same host, *different ports*):
             the listen port can't be recovered from the connection (its source
             port is ephemeral), so disambiguate by the payload's ``instanceName``
             — matched against the CHUB label, then each candidate's live
             ``instanceName``. A unique name match wins; otherwise fail closed.
          4. Single-instance fallback: if the payload's media type has exactly
             one configured instance, use it — covers single-instance
             reverse-proxy setups the IP match can't see.

        Anything still ambiguous returns not-found: the arr media id is
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
            instance_name: The payload's ``instanceName`` (Sonarr/Radarr's own
                instance name), used only to break a same-IP tie.
            application_url: The payload's ``applicationUrl`` (the arr's own base
                URL, when the user has set it). Carries the listen PORT, so it
                can tell apart same-IP/different-port instances and can identify
                the sender behind a reverse proxy that masks the peer IP.

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

        # 3) Same IP, several instances (different ports): the listen port isn't
        # in the connection, but the payload's applicationUrl carries host+port,
        # so try that first, then the arr's own instanceName.
        if len(matches) > 1:
            picked = self._match_by_application_url(
                matches, application_url
            ) or self._disambiguate_by_name(matches, instance_name)
            if picked is not None:
                return _resolved(*picked)
            return {"found": False, "error": "peer IP matched multiple instances"}

        # 4) No peer-IP match (e.g. behind a reverse proxy that masks the peer):
        # applicationUrl can still identify the sender by host+port.
        picked = self._match_by_application_url(pool, application_url)
        if picked is not None:
            return _resolved(*picked)

        # 5) Exactly one instance of this media type → unambiguous target.
        if len(pool) == 1:
            return _resolved(*pool[0])

        return {"found": False, "error": "No matching instance"}

    def _match_by_application_url(self, candidates, application_url):
        """Pick the sole candidate whose configured URL matches the payload's
        ``applicationUrl`` (the arr's own base URL). It carries the listen PORT —
        the one discriminator the raw connection can't provide — so it tells
        apart instances sharing an IP but differing by port. Ports must agree
        when both are known; hosts are compared literally and via DNS resolution
        so a service name matches its container IP. Returns the sole match, or
        None when it's missing, matches none, or matches more than one."""
        if not application_url:
            return None
        try:
            au = urlparse(str(application_url))
            a_port = au.port
        except ValueError:
            return None
        a_host = _normalize_host(au.hostname)
        if not a_host:
            return None
        hits = []
        for cand in candidates:
            try:
                cu = urlparse(cand[2].url or "")
                c_port = cu.port
            except ValueError:
                continue
            if a_port is not None and c_port is not None and a_port != c_port:
                continue
            c_host = _normalize_host(cu.hostname)
            if (
                c_host == a_host
                or _host_matches(cand[2].url, a_host)
                or _host_matches(str(application_url), c_host)
            ):
                hits.append(cand)
        return hits[0] if len(hits) == 1 else None

    def _disambiguate_by_name(self, candidates, instance_name):
        """Pick the one candidate whose name equals the webhook's ``instanceName``.

        Several instances share the connection's peer IP (same host, different
        ports) and the listen port can't be read from the socket, so the arr's
        own instance name is the only automatic signal. Compares against the
        CHUB label first (free) and then each candidate's live ``instanceName``
        (cached). Returns the sole match, or ``None`` when the name is missing,
        matches none, or matches more than one (caller then fails closed).
        """
        target = (instance_name or "").strip().lower()
        if not target:
            return None

        by_label = [c for c in candidates if c[0].strip().lower() == target]
        if len(by_label) == 1:
            return by_label[0]

        by_live = [
            c
            for c in candidates
            if (self._live_instance_name(c[2].url, c[2].api) or "").strip().lower()
            == target
        ]
        return by_live[0] if len(by_live) == 1 else None

    def _live_instance_name(self, url, api):
        """The arr's self-reported ``instanceName``, briefly cached by URL. Only
        successful lookups are cached so a transient outage isn't sticky."""
        if not url or not api:
            return None
        now = time.time()
        cached = _NAME_CACHE.get(url)
        if cached and cached[0] > now:
            return cached[1]
        name = None
        try:
            from backend.util.arr import create_arr_client

            client = create_arr_client(url, api, self.logger)
            if client:
                name = (
                    getattr(client, "instance_name", None) or client.get_instance_name()
                )
                try:
                    client.session.close()
                except Exception:
                    pass
        except Exception:
            name = None
        if name:
            _NAME_CACHE[url] = (now + _NAME_TTL_SECONDS, name)
        return name

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

    @staticmethod
    def _item_present(plex, media_title: str, year) -> bool:
        """True when a movie/show titled `media_title` (matching `year` when
        given) already exists in ANY Plex library section. A direct title search,
        so an item scanned long ago is found immediately — unlike a
        `recentlyAdded` scan, which only sees the last N additions and so misses
        an already-present item, forcing the old code to burn the full retry
        budget on re-imports and existing shows."""
        for section in plex.library.sections():
            try:
                results = section.search(title=media_title)
            except Exception:
                results = []
            for item in results:
                try:
                    if item.title.lower() != media_title.lower():
                        continue
                except Exception:
                    continue
                if year is None or getattr(item, "year", None) in (None, year):
                    return True
        return False

    def wait_for_plex_availability(
        self, media_title: str, year=None, season_number=None, is_added_event=False
    ) -> bool:
        """
        Ensure a media item is in Plex before processing its posters, without
        blocking longer than necessary.

        Returns immediately when the item (or the specific season) is ALREADY in
        Plex — a re-import, quality upgrade, or a long-present show needs no wait.
        Only a genuinely new import Plex hasn't scanned yet falls through to the
        initial-delay + retry loop. Previously the non-season path only checked
        `recentlyAdded`, so an existing item was never "found" and every such
        webhook waited the full ~5.5 min budget.

        Pre-download "added" events (Sonarr SeriesAdd / Radarr MovieAdded) have
        no new file to wait for, so when `is_added_event` is set and the item is
        not already present it returns at once instead of waiting for a scan this
        event will never trigger.

        Args:
            media_title: Title of the media to look for.
            year: Optional year for matching.
            season_number: When set (Sonarr import), require that specific season
                folder to be scanned, not just the show.
            is_added_event: True for pre-download SeriesAdd / MovieAdded events.

        Returns:
            bool: True if the item (or season) is present in Plex.
        """
        log = self.logger.get_adapter("WEBHOOK")

        try:
            from plexapi.server import PlexServer

            plex_instances = getattr(self.config.instances, "plex", {})
            if not plex_instances:
                log.debug("No Plex instances configured, skipping availability check")
                return True  # No Plex to check, proceed anyway

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

            if not targets:
                return True  # Nothing checkable — don't block.

            def _present() -> bool:
                # One pass across every instance; True on the first hit. Sharing a
                # single budget (vs a retry loop nested per instance) keeps M
                # instances from multiplying the wait to M × retries × delay.
                for name, url, token in targets:
                    try:
                        plex = PlexServer(url, token, timeout=10)
                        if season_number is not None:
                            if self._season_present(
                                plex, media_title, year, season_number
                            ):
                                return True
                        elif self._item_present(plex, media_title, year):
                            return True
                    except Exception as e:
                        log.debug(f"Plex check failed for {name}: {e}")
                return False

            label = (
                f"'{media_title}' Season {season_number}"
                if season_number is not None
                else f"'{media_title}'"
            )

            # Already in Plex → no wait at all.
            if _present():
                log.info(f"Found {label} in Plex")
                return True

            # A pre-download add produces no new scan; don't wait for one.
            if is_added_event:
                log.debug(f"{label} not in Plex (pre-download add) — not waiting")
                return False

            # Genuinely new import Plex hasn't scanned yet: wait, then retry.
            if self.initial_delay > 0:
                log.debug(f"Waiting {self.initial_delay}s for Plex to scan new media")
                time.sleep(self.initial_delay)

            for attempt in range(self.max_retries + 1):
                if _present():
                    log.info(f"Found {label} in Plex")
                    return True
                if attempt < self.max_retries:
                    log.debug(
                        f"Not found in Plex yet, retrying in {self.retry_delay}s "
                        f"(attempt {attempt + 1}/{self.max_retries})"
                    )
                    time.sleep(self.retry_delay)

            log.debug(f"{label} not found in Plex after {self.max_retries} retries")
            return False

        except ImportError:
            log.debug("plexapi not available, skipping Plex availability check")
            return True
        except Exception as e:
            log.error(f"Error checking Plex availability: {e}")
            return True  # Don't block processing on Plex check failure
