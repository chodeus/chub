"""TMDB integration.

Resolves missing tmdb_id values for media_cache rows by calling TMDB's
`/3/find/{external_id}?external_source=tvdb_id|imdb_id` endpoint and
caching the result. Resolved IDs are written back to media_cache so
downstream consumers (poster matching, Plex GUID cross-join, unmatched
asset request links) can use them without further TMDB calls.

The persistent cache is critical because TMDB enforces ~50 req/s + per-day
quotas — every sync would otherwise re-resolve the same IDs and burn budget.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, List, Optional, Tuple

import requests

from backend.util.config import TMDBConfig
from backend.util.database import ChubDB


class TMDBAuthError(Exception):
    """API key was rejected by TMDB (HTTP 401)."""


class TMDBClient:
    """Thin, synchronous TMDB client scoped to ID resolution.

    Caches lookups in three layers:
      1. Per-instance memo dict — collapses duplicate work within a single
         resolver pass (e.g. the same show being unmatched on multiple
         instances).
      2. Persistent `tmdb_id_cache` table — survives restarts; respects
         the configured expiration window.
      3. Negative cache — TMDB-returned-no-match rows are stored too so we
         don't keep hammering /find for IDs that just don't exist.
    """

    BASE = "https://api.themoviedb.org/3"
    HTTP_TIMEOUT = 10
    MAX_RETRIES = 3
    BACKOFF_SECONDS = (1, 2)  # waits between attempts 1→2 and 2→3

    def __init__(self, cfg: TMDBConfig, db: ChubDB, logger) -> None:
        self.cfg = cfg
        self.db = db
        self.logger = logger
        self.session = requests.Session()
        self._memo: dict = {}
        self._auth_failed = False

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.apikey) and not self._auth_failed

    def find_tmdb_id(
        self, external_id: str, source: str, media_type: str
    ) -> Optional[int]:
        """Resolve a TMDB id for the given external id.

        source: 'tvdb_id' or 'imdb_id'
        media_type: 'movie' or 'tv' — selects which TMDB results list to read.
        Returns the TMDB id, or None if no match / disabled / error.
        """
        if not self.enabled or not external_id:
            return None

        ext_str = str(external_id)
        key = (ext_str, source, media_type)
        if key in self._memo:
            return self._memo[key]

        hit, cached = self.db.tmdb_id_cache.get(
            ext_str, source, media_type, self.cfg.cache_expiration
        )
        if hit:
            self._memo[key] = cached
            return cached

        tmdb_id = self._fetch(ext_str, source, media_type)
        try:
            self.db.tmdb_id_cache.put(ext_str, source, media_type, tmdb_id)
        except Exception as exc:
            self.logger.warning(f"TMDB cache write failed for {ext_str}: {exc}")
        self._memo[key] = tmdb_id
        return tmdb_id

    def _fetch(
        self, external_id: str, source: str, media_type: str
    ) -> Optional[int]:
        url = f"{self.BASE}/find/{external_id}"
        params = {
            "api_key": self.cfg.apikey,
            "external_source": source,
        }

        for attempt in range(self.MAX_RETRIES):
            try:
                resp = self.session.get(url, params=params, timeout=self.HTTP_TIMEOUT)
            except requests.RequestException as exc:
                if attempt == self.MAX_RETRIES - 1:
                    self.logger.warning(
                        f"TMDB request failed for {source}={external_id}: {exc}"
                    )
                    return None
                time.sleep(self.BACKOFF_SECONDS[attempt])
                continue

            if resp.status_code == 401:
                self._auth_failed = True
                self.logger.error(
                    "TMDB API rejected the configured key (401). "
                    "Disabling TMDB lookups for the remainder of this run."
                )
                return None
            if resp.status_code == 429:
                # Honor Retry-After once, then give up — interactive callers
                # can't wait minutes for a stats page.
                retry_after = min(int(resp.headers.get("Retry-After", "1") or 1), 5)
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(retry_after)
                    continue
                self.logger.warning("TMDB rate-limited; giving up after retries")
                return None
            if resp.status_code >= 500 and attempt < self.MAX_RETRIES - 1:
                time.sleep(self.BACKOFF_SECONDS[attempt])
                continue
            if not resp.ok:
                self.logger.warning(
                    f"TMDB returned {resp.status_code} for {source}={external_id}"
                )
                return None

            try:
                data = resp.json()
            except ValueError:
                return None

            bucket = "movie_results" if media_type == "movie" else "tv_results"
            results = data.get(bucket) or []
            if results and isinstance(results[0].get("id"), int):
                return results[0]["id"]
            return None

        return None


def backfill_missing_tmdb_ids(
    db: ChubDB,
    cfg: TMDBConfig,
    logger,
    *,
    asset_types: Iterable[str] = ("movie", "show"),
    instance_names: Optional[Iterable[str]] = None,
    max_rows: int = 2000,
    max_workers: int = 8,
) -> int:
    """Walk media_cache for rows missing tmdb_id and resolve via TMDB.

    Idempotent and a no-op when cfg.apikey is empty. Returns the number of
    rows that were newly resolved (excludes cache hits and negative-cache
    rows). Safe to call on every sync — repeat work is served from caches.
    """
    if not cfg.apikey:
        return 0

    asset_types_list = list(asset_types)
    if not asset_types_list:
        return 0

    placeholders = ",".join("?" for _ in asset_types_list)
    sql = (
        "SELECT id, asset_type, tvdb_id, imdb_id FROM media_cache "
        "WHERE tmdb_id IS NULL "
        "AND (tvdb_id IS NOT NULL OR imdb_id IS NOT NULL) "
        f"AND asset_type IN ({placeholders})"
    )
    params: List = list(asset_types_list)
    if instance_names:
        inst_list = list(instance_names)
        if inst_list:
            sql += f" AND instance_name IN ({','.join('?' for _ in inst_list)})"
            params.extend(inst_list)
    sql += " LIMIT ?"
    params.append(max_rows)

    rows = db.media.execute_query(sql, tuple(params), fetch_all=True) or []
    if not rows:
        return 0

    targets: List[Tuple[int, str, str, str]] = []  # (row_id, media_type, ext, source)
    for row in rows:
        media_type = "movie" if row["asset_type"] == "movie" else "tv"
        # Sonarr's primary external id is tvdb; Radarr's is tmdb (already set
        # if available) or imdb. Prefer tvdb for shows, imdb for movies.
        if media_type == "tv" and row.get("tvdb_id"):
            targets.append((row["id"], media_type, str(row["tvdb_id"]), "tvdb_id"))
        elif row.get("imdb_id"):
            targets.append((row["id"], media_type, row["imdb_id"], "imdb_id"))
        elif row.get("tvdb_id"):
            targets.append((row["id"], media_type, str(row["tvdb_id"]), "tvdb_id"))

    if not targets:
        return 0

    client = TMDBClient(cfg, db, logger)
    resolved = 0

    def _resolve(target):
        row_id, media_type, ext, source = target
        return row_id, client.find_tmdb_id(ext, source, media_type)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_resolve, t) for t in targets]
        for fut in as_completed(futures):
            try:
                row_id, tmdb_id = fut.result()
            except Exception as exc:
                logger.warning(f"TMDB resolve failed: {exc}")
                continue
            if tmdb_id is None:
                continue
            try:
                db.media.execute_query(
                    "UPDATE media_cache SET tmdb_id=? WHERE id=?",
                    (int(tmdb_id), row_id),
                )
                resolved += 1
            except Exception as exc:
                logger.warning(
                    f"Failed to persist tmdb_id={tmdb_id} for row {row_id}: {exc}"
                )

    return resolved
