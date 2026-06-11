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

import difflib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union

import requests

from backend.util.config import TMDBConfig
from backend.util.database import ChubDB
from backend.util.normalization import normalize_titles


# Sentinel returned by _fetch_details for a genuine HTTP 404 (TMDB truly has
# no such id). Distinct from None, which means a *transient* failure (rate
# limit, network error, 5xx, auth) — those must NOT be negative-cached or
# reported as "not found", or a real id gets mislabelled when the bulk verify
# pass hits a blip.
_TMDB_NOT_FOUND = object()


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
        # requests.Session isn't safe to share across threads, and this client
        # is driven concurrently by backfill_missing_tmdb_ids' ThreadPoolExecutor.
        # Give each worker thread its own session, and guard the in-process memo.
        self._local = threading.local()
        self._memo: dict = {}
        self._memo_lock = threading.Lock()
        self._auth_failed = False

    @property
    def session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            self._local.session = s
        return s

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
        with self._memo_lock:
            if key in self._memo:
                return self._memo[key]

        hit, cached = self.db.tmdb_id_cache.get(
            ext_str, source, media_type, self.cfg.cache_expiration
        )
        if hit:
            with self._memo_lock:
                self._memo[key] = cached
            return cached

        tmdb_id = self._fetch(ext_str, source, media_type)
        try:
            self.db.tmdb_id_cache.put(ext_str, source, media_type, tmdb_id)
        except Exception as exc:
            self.logger.warning(f"TMDB cache write failed for {ext_str}: {exc}")
        with self._memo_lock:
            self._memo[key] = tmdb_id
        return tmdb_id

    def _request_with_retry(self, url: str, params: dict, *, what: str):
        """Single GET-with-retry used by every TMDB call.

        Returns a `requests.Response` for any *terminal* status (2xx, 404, other
        non-retryable codes) for the caller to interpret, or None on an auth
        failure / exhausted transient retries. Handles the shared ladder once:
        network errors and 5xx → backoff+retry; 429 → honor Retry-After once;
        401 → disable TMDB for the run and bail. The caller owns status-specific
        logic (404 semantics, JSON parsing) and the not-ok warning. `what` is a
        short label for log messages (e.g. "tvdb_id=123", "movie/55/images").
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = self.session.get(url, params=params, timeout=self.HTTP_TIMEOUT)
            except requests.RequestException as exc:
                if attempt == self.MAX_RETRIES - 1:
                    self.logger.warning(f"TMDB request failed for {what}: {exc}")
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
                # can't wait minutes for a stats page. Retry-After is usually
                # delta-seconds, but RFC 7231 also permits an HTTP-date; int()
                # on a date string would raise and abort the whole retry loop,
                # so fall back to a small fixed delay.
                try:
                    retry_after = min(
                        int(resp.headers.get("Retry-After", "1") or 1), 5
                    )
                except (ValueError, TypeError):
                    retry_after = 1
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(retry_after)
                    continue
                self.logger.warning("TMDB rate-limited; giving up after retries")
                return None
            if resp.status_code >= 500 and attempt < self.MAX_RETRIES - 1:
                time.sleep(self.BACKOFF_SECONDS[attempt])
                continue
            # Terminal status (2xx / 404 / other 4xx) — hand back to the caller.
            return resp

        return None

    def _fetch(
        self, external_id: str, source: str, media_type: str
    ) -> Optional[int]:
        url = f"{self.BASE}/find/{external_id}"
        params = {
            "api_key": self.cfg.apikey,
            "external_source": source,
        }

        resp = self._request_with_retry(url, params, what=f"{source}={external_id}")
        if resp is None:
            return None
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

    def get_details(self, tmdb_id: int, media_type: str) -> Optional[dict]:
        """Fetch canonical title/original_title/year/alternative_titles for a
        TMDB id via GET /3/{movie|tv}/{id}, with caching.

        Returns one of:
          - a details dict with verified=True   (id resolved)
          - a dict with verified=False          (genuine 404 — TMDB has no
                                                  such id; negative-cached)
          - None                                (disabled, or a TRANSIENT
                                                  failure — rate limit, network,
                                                  5xx, auth; NOT cached, so the
                                                  caller skips and retries later
                                                  rather than mislabelling it)
        """
        if not self.enabled or not tmdb_id:
            return None

        mt = "movie" if media_type == "movie" else "tv"
        try:
            hit, cached = self.db.tmdb_details_cache.get(
                int(tmdb_id), mt, self.cfg.cache_expiration
            )
            if hit:
                return cached
        except Exception as exc:
            self.logger.warning(f"TMDB details cache read failed for {tmdb_id}: {exc}")

        details = self._fetch_details(int(tmdb_id), mt)

        # Transient failure — do NOT cache and do NOT report not-found.
        if details is None:
            return None

        if details is _TMDB_NOT_FOUND:
            try:
                self.db.tmdb_details_cache.put(int(tmdb_id), mt, verified=False)
            except Exception as exc:
                self.logger.warning(
                    f"TMDB details cache write failed for {tmdb_id}: {exc}"
                )
            return {
                "title": None,
                "original_title": None,
                "year": None,
                "alternative_titles": [],
                "verified": False,
            }

        try:
            self.db.tmdb_details_cache.put(
                int(tmdb_id),
                mt,
                title=details.get("title"),
                original_title=details.get("original_title"),
                year=details.get("year"),
                alternative_titles=details.get("alternative_titles"),
                verified=True,
            )
        except Exception as exc:
            self.logger.warning(f"TMDB details cache write failed for {tmdb_id}: {exc}")
        details["verified"] = True
        return details

    def _fetch_details(self, tmdb_id: int, mt: str) -> Any:
        """Returns a details dict, _TMDB_NOT_FOUND (genuine 404), or None
        (transient failure — caller must not treat as not-found)."""
        url = f"{self.BASE}/{mt}/{tmdb_id}"
        params = {
            "api_key": self.cfg.apikey,
            "append_to_response": "alternative_titles",
        }

        resp = self._request_with_retry(url, params, what=f"{mt}/{tmdb_id}")
        if resp is None:
            return None
        if resp.status_code == 404:
            return _TMDB_NOT_FOUND  # genuine no-such-id
        if not resp.ok:
            self.logger.warning(f"TMDB returned {resp.status_code} for {mt}/{tmdb_id}")
            return None

        try:
            data = resp.json()
        except ValueError:
            return None

        if mt == "movie":
            title = data.get("title")
            original_title = data.get("original_title")
            date = data.get("release_date") or ""
            alt_block = (data.get("alternative_titles") or {}).get("titles") or []
        else:
            title = data.get("name")
            original_title = data.get("original_name")
            date = data.get("first_air_date") or ""
            alt_block = (data.get("alternative_titles") or {}).get("results") or []

        year = None
        if isinstance(date, str) and len(date) >= 4 and date[:4].isdigit():
            year = int(date[:4])
        akas = [
            t.get("title") for t in alt_block if isinstance(t, dict) and t.get("title")
        ]

        return {
            "title": title,
            "original_title": original_title,
            "year": year,
            "alternative_titles": akas,
        }

    # TMDB serves images from a CDN; "original" is the full-resolution size.
    IMAGE_BASE = "https://image.tmdb.org/t/p/original"

    @staticmethod
    def _pick_image(items: list, preferred_langs: list) -> Optional[str]:
        """Return the best file_path from a TMDB image list.

        `preferred_langs` is an ordered list of acceptable ``iso_639_1`` values
        (use ``None`` for language-neutral / textless art). Items whose language
        is in the list rank first by that list's order; everything else falls to
        the end. Within a tier, higher vote_average then vote_count wins.
        """
        if not items:
            return None

        def tier(it):
            lang = it.get("iso_639_1")
            try:
                return preferred_langs.index(lang)
            except ValueError:
                return len(preferred_langs)

        best = sorted(
            items,
            key=lambda it: (
                tier(it),
                -(it.get("vote_average") or 0),
                -(it.get("vote_count") or 0),
            ),
        )[0]
        return best.get("file_path")

    @staticmethod
    def _normalize_langs(language: Union[str, List[str], None]) -> List[str]:
        """Coerce a single code, comma-string, or list into an ordered list of
        lowercased non-empty language codes. Falls back to ['en']."""
        if isinstance(language, str):
            parts = [p.strip().lower() for p in language.split(",")]
        elif isinstance(language, (list, tuple)):
            parts = [str(p).strip().lower() for p in language]
        else:
            parts = []
        # Preserve order, drop blanks and duplicates.
        seen: Set[str] = set()
        langs = [p for p in parts if p and not (p in seen or seen.add(p))]
        return langs or ["en"]

    def get_images(
        self,
        tmdb_id: int,
        media_type: str,
        language: Union[str, List[str]] = "en",
    ) -> Optional[Dict[str, Optional[str]]]:
        """Fetch the best logo + background image URLs for a TMDB id.

        ``language`` is a preferred-language priority list (a single string is
        accepted and treated as a one-element list); the first matching language
        wins, with language-neutral / textless art always allowed as a fallback.

        Returns ``{"logo": url|None, "background": url|None}`` (absolute CDN
        URLs), or None when disabled / on a transient failure. Results are
        cached in tmdb_images_cache to respect TMDB rate limits across runs.

        Note: TMDB has no "square art" image class, so squareart is never
        returned here — the asset pipeline falls back to local files for that
        type.
        """
        if not self.enabled or not tmdb_id:
            return None

        langs = self._normalize_langs(language)

        mt = "movie" if media_type == "movie" else "tv"
        key = ("images", str(tmdb_id), mt)
        with self._memo_lock:
            if key in self._memo:
                return self._memo[key]

        try:
            hit, cached = self.db.tmdb_images_cache.get(
                int(tmdb_id), mt, self.cfg.cache_expiration
            )
            if hit:
                with self._memo_lock:
                    self._memo[key] = cached
                return cached
        except Exception as exc:
            self.logger.warning(f"TMDB images cache read failed for {tmdb_id}: {exc}")

        raw = self._fetch_images(int(tmdb_id), mt, langs)
        if raw is None:
            return None  # transient — don't cache, let caller retry later

        # Logos: prefer the requested languages in order, then textless art.
        logo_path = self._pick_image(raw.get("logos") or [], [*langs, None])
        # Backdrops: prefer textless (language-neutral) art, then the requested
        # languages in order.
        backdrop_path = self._pick_image(raw.get("backdrops") or [], [None, *langs])
        images = {
            "logo": f"{self.IMAGE_BASE}{logo_path}" if logo_path else None,
            "background": f"{self.IMAGE_BASE}{backdrop_path}" if backdrop_path else None,
        }
        try:
            self.db.tmdb_images_cache.put(int(tmdb_id), mt, images)
        except Exception as exc:
            self.logger.warning(f"TMDB images cache write failed for {tmdb_id}: {exc}")
        with self._memo_lock:
            self._memo[key] = images
        return images

    def _fetch_images(
        self, tmdb_id: int, mt: str, languages: Union[str, List[str]]
    ) -> Any:
        """GET /3/{movie|tv}/{id}/images. Returns the raw dict, or None on a
        transient failure / 404 (callers treat None as 'no images available')."""
        url = f"{self.BASE}/{mt}/{tmdb_id}/images"
        langs = self._normalize_langs(languages)
        # include_image_language pulls the requested languages plus textless
        # (null-language) art in one call so _pick_image has every tier.
        params = {
            "api_key": self.cfg.apikey,
            "include_image_language": ",".join([*langs, "null"]),
        }

        resp = self._request_with_retry(url, params, what=f"{mt}/{tmdb_id}/images")
        if resp is None:
            return None
        if resp.status_code == 404:
            return {"logos": [], "backdrops": []}  # no such id → no images
        if not resp.ok:
            self.logger.warning(
                f"TMDB returned {resp.status_code} for {mt}/{tmdb_id}/images"
            )
            return None

        try:
            return resp.json()
        except ValueError:
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


# Fuzzy match acceptance threshold (difflib ratio, 0–1). A near-but-not-exact
# normalized-title match at or above this is *suggested* for review, never
# auto-applied.
FUZZY_REVIEW_THRESHOLD = 0.86


def _norm_set(values: Iterable[Optional[str]]) -> Set[str]:
    """Normalized, non-empty set of titles for overlap comparison."""
    out: Set[str] = set()
    for v in values:
        if not v:
            continue
        n = normalize_titles(str(v))
        if n:
            out.add(n)
    return out


def _json_list(value) -> List:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []


def run_match_quality(
    db: ChubDB,
    cfg: TMDBConfig,
    logger,
    *,
    instance_names: Optional[Iterable[str]] = None,
    max_rows: int = 2000,
) -> Dict[str, int]:
    """Automatic match-quality pass.

      - fuzzy   : flag unmatched rows that have a near-miss poster for review.
                  Local-only (no API calls) — ALWAYS runs, so installs without
                  a TMDB key still get near-miss suggestions.
      - verify  : confirm each row's tmdb_id resolves to its title; flag
                  mismatches for review. (TMDB — only when apikey is set)
      - hydrate : merge TMDB alternate titles into media_cache so future
                  matches catch regional/AKA names. (TMDB — only when keyed)

    Returns a counts summary.
    """
    summary = {
        "verified": 0,
        "id_mismatches": 0,
        "akas_hydrated": 0,
        "fuzzy_flagged": 0,
    }
    # Local near-miss flagging runs regardless of TMDB configuration.
    summary["fuzzy_flagged"] = _fuzzy_flag_unmatched(db, logger, max_rows)
    # TMDB id verification + AKA hydration only when a key is configured.
    if cfg.apikey:
        client = TMDBClient(cfg, db, logger)
        summary.update(
            _verify_and_hydrate(db, client, logger, instance_names, max_rows)
        )
    return summary


def _verify_and_hydrate(
    db: ChubDB,
    client: "TMDBClient",
    logger,
    instance_names: Optional[Iterable[str]],
    max_rows: int,
) -> Dict[str, int]:
    counts = {"verified": 0, "id_mismatches": 0, "akas_hydrated": 0}

    sql = (
        "SELECT id, asset_type, title, normalized_title, alternate_titles, "
        "normalized_alternate_titles, tmdb_id, match_status "
        "FROM media_cache WHERE tmdb_id IS NOT NULL "
        "AND asset_type IN ('movie','show')"
    )
    params: List = []
    if instance_names:
        inst = list(instance_names)
        if inst:
            sql += f" AND instance_name IN ({','.join('?' for _ in inst)})"
            params.extend(inst)
    sql += " LIMIT ?"
    params.append(max_rows)

    rows = db.media.execute_query(sql, tuple(params), fetch_all=True) or []
    for row in rows:
        media_type = "movie" if row["asset_type"] == "movie" else "tv"
        details = client.get_details(row["tmdb_id"], media_type)
        if details is None:
            continue  # transport error / disabled — leave row untouched

        # Verify the id resolves to this row's title.
        counts["verified"] += 1
        if not details.get("verified"):
            _flag_review(
                db,
                row["id"],
                f"TMDB id {row['tmdb_id']} not found on TMDB",
            )
            counts["id_mismatches"] += 1
        else:
            tmdb_titles = _norm_set(
                [details.get("title"), details.get("original_title")]
                + list(details.get("alternative_titles") or [])
            )
            row_titles = _norm_set(
                [row.get("title"), row.get("normalized_title")]
                + _json_list(row.get("alternate_titles"))
            )
            # row's normalized_title is already normalized; include raw too
            row_titles |= {n for n in [row.get("normalized_title")] if n}
            if tmdb_titles and row_titles and not (tmdb_titles & row_titles):
                _flag_review(
                    db,
                    row["id"],
                    f"TMDB id {row['tmdb_id']} resolves to "
                    f"'{details.get('title')}', not '{row.get('title')}'",
                )
                counts["id_mismatches"] += 1

        # Hydrate AKAs so future matches catch regional/alternate names.
        if details.get("verified"):
            if _merge_akas(db, row, details.get("alternative_titles") or []):
                counts["akas_hydrated"] += 1

    return counts


def _flag_review(db: ChubDB, media_id: int, reason: str) -> None:
    """Downgrade a row to needs_review with a reason, without touching whether
    its poster is applied (the `matched` flag is left as-is)."""
    db.media.update(
        asset_type="",
        title="",
        year=None,
        instance_name="",
        match_status="needs_review",
        match_reason=reason,
        id=media_id,
    )


def _merge_akas(db: ChubDB, row: dict, tmdb_akas: List[str]) -> bool:
    """Union TMDB AKAs into a row's alternate_titles / normalized_alternate_titles.
    Returns True if anything new was added."""
    existing = _json_list(row.get("alternate_titles"))
    existing_norm = set(_json_list(row.get("normalized_alternate_titles")))
    added = False
    for aka in tmdb_akas:
        n = normalize_titles(aka)
        if n and n not in existing_norm:
            existing.append(aka)
            existing_norm.add(n)
            added = True
    if not added:
        return False
    db.media.execute_query(
        "UPDATE media_cache SET alternate_titles=?, normalized_alternate_titles=? "
        "WHERE id=?",
        (json.dumps(existing), json.dumps(sorted(existing_norm)), row["id"]),
    )
    return True


def _fuzzy_flag_unmatched(db: ChubDB, logger, max_rows: int) -> int:
    """For each unmatched media row, find the closest poster by normalized
    title and, if it's a strong near-miss, flag the row needs_review with the
    suggestion. Never applies a poster (matched stays 0)."""
    # Key on match_status (not the transient `matched` flag, which the rename
    # phase clears to NULL once a poster is applied). match_status='unmatched'
    # precisely targets rows the matcher found no poster for; NULL covers rows
    # that predate the column / haven't been matched yet.
    rows = (
        db.media.execute_query(
            "SELECT id, asset_type, title, normalized_title, year FROM media_cache "
            "WHERE (match_status='unmatched' OR match_status IS NULL) "
            "AND (ignored IS NULL OR ignored=0) "
            "AND normalized_title IS NOT NULL AND normalized_title != '' "
            "LIMIT ?",
            (max_rows,),
            fetch_all=True,
        )
        or []
    )
    flagged = 0
    for row in rows:
        norm = row.get("normalized_title") or ""
        expected_type = "collection" if row["asset_type"] == "collection" else row["asset_type"]
        try:
            candidates = db.poster.get_candidates_by_prefix(
                row.get("title") or "", length=2, asset_type=expected_type
            )
        except Exception:
            candidates = []
        best = None
        best_ratio = 0.0
        for cand in candidates:
            cand_norm = cand.get("normalized_title") or ""
            if not cand_norm:
                continue
            ratio = difflib.SequenceMatcher(None, norm, cand_norm).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best = cand
        if best is not None and best_ratio >= FUZZY_REVIEW_THRESHOLD and norm != (
            best.get("normalized_title") or ""
        ):
            _flag_review(
                db,
                row["id"],
                f"Fuzzy suggestion: '{best.get('title')}' "
                f"({int(best_ratio * 100)}% similar)",
            )
            flagged += 1
    return flagged
