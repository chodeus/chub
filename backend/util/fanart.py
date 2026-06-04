"""fanart.tv integration — logos + backgrounds for asset_renamerr.

fanart.tv is the curated, community-ranked source for logos and backgrounds
(the equivalent of what posters get from local asset packs). Every fanart.tv
image carries a ``likes`` count, so we pick the community-preferred one instead
of an arbitrary candidate.

Auth (https://fanart.tv/get-an-api-key/): a fanart.tv PERSONAL key
(``client_key``) authenticates on its own — that is all Chub uses. Each user
supplies their own free personal key, and Chub REQUIRES it (the client is only
``enabled`` when a client_key is configured). A personal key also gives the
faster tier (2-day vs 7-day delay for newly-added art). Chub does not use a
project key.

Resolved URLs are cached in ``fanart_images_cache`` so repeated runs don't
re-hit fanart — required by their "no more requests than necessary" terms. The
default 2-day window matches the personal key's own 2-day propagation delay for
newly-added art, so the cache costs no real freshness.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Union

import requests

from backend.util.config import FanartConfig
from backend.util.database import ChubDB

# fanart image-type fields, in preference order (HD/clear variants first).
_MOVIE_LOGO_KEYS = ("hdmovielogo", "movielogo")
_MOVIE_BG_KEYS = ("moviebackground",)
_TV_LOGO_KEYS = ("hdtvlogo", "clearlogo")
_TV_BG_KEYS = ("showbackground",)

# Neutral / textless language token used by fanart.tv.
_NEUTRAL_LANGS = ("00", "")


class FanartClient:
    """Thin, synchronous fanart.tv v3 client for logo + background lookup.

    Caches in two layers: a per-instance memo dict (collapses duplicate work in
    one run) and the persistent ``fanart_images_cache`` table (survives restarts;
    respects the configured expiration window, default 2 days — matching the
    personal key's own propagation delay so it costs no real freshness).
    """

    BASE = "https://webservice.fanart.tv/v3"
    HTTP_TIMEOUT = 10
    MAX_RETRIES = 3
    BACKOFF_SECONDS = (1, 2)  # waits between attempts 1→2 and 2→3

    def __init__(self, cfg: FanartConfig, db: ChubDB, logger) -> None:
        self.cfg = cfg
        self.db = db
        self.logger = logger
        self.session = requests.Session()
        self._memo: dict = {}
        self._auth_failed = False

    @property
    def enabled(self) -> bool:
        # The personal client_key is required — it authenticates on its own and
        # gives the faster image tier. No project key is used.
        return bool(self.cfg.client_key) and not self._auth_failed

    # ----- public ---------------------------------------------------------

    def get_images(
        self, media: dict, language: Union[str, List[str]] = "en"
    ) -> Optional[Dict[str, Optional[str]]]:
        """Return ``{"logo": url|None, "background": url|None}`` for a media row,
        or None when disabled / on a transient failure.

        Movies are looked up by tmdb (then imdb) id; TV by tvdb id. For a season
        row, the background is narrowed to that season (or fanart's "all"); the
        logo is the show-level logo (fanart has no per-season logos).
        squareart is never returned — fanart.tv has no square-art type, so the
        asset pipeline falls back to local files for it.
        """
        if not self.enabled:
            return None

        asset_type = media.get("asset_type")
        season_number = media.get("season_number")
        if asset_type == "movie":
            kind = "movie"
            lookup_id = media.get("tmdb_id") or media.get("imdb_id")
            season_key = -1
        elif asset_type == "show":
            kind = "tv"
            lookup_id = media.get("tvdb_id")
            season_key = (
                int(season_number)
                if season_number not in (None, "", "None")
                else -1
            )
        else:
            return None  # collections / other types not sourced from fanart
        if not lookup_id:
            return None

        langs = self._normalize_langs(language)
        memo_key = ("images", kind, str(lookup_id), season_key)
        if memo_key in self._memo:
            return self._memo[memo_key]

        try:
            hit, cached = self.db.fanart_images_cache.get(
                lookup_id, kind, self.cfg.cache_expiration, season=season_key
            )
            if hit:
                self._memo[memo_key] = cached
                return cached
        except Exception as exc:
            self.logger.warning(f"fanart images cache read failed for {lookup_id}: {exc}")

        raw = self._fetch(kind, str(lookup_id))
        if raw is None:
            return None  # transient — don't cache, let a later run retry

        images = {
            "logo": self._pick_logo(raw, kind, langs),
            "background": self._pick_background(raw, kind, langs, season_key),
        }
        try:
            self.db.fanart_images_cache.put(lookup_id, kind, images, season=season_key)
        except Exception as exc:
            self.logger.warning(
                f"fanart images cache write failed for {lookup_id}: {exc}"
            )
        self._memo[memo_key] = images
        return images

    # ----- selection ------------------------------------------------------

    @staticmethod
    def _normalize_langs(language: Union[str, List[str], None]) -> List[str]:
        if isinstance(language, str):
            parts = [p.strip().lower() for p in language.split(",")]
        elif isinstance(language, (list, tuple)):
            parts = [str(p).strip().lower() for p in language]
        else:
            parts = []
        seen: set = set()
        langs = [p for p in parts if p and not (p in seen or seen.add(p))]
        return langs or ["en"]

    @staticmethod
    def _collect(raw: dict, keys: tuple) -> List[dict]:
        """First non-empty image list among ``keys`` (HD variant preferred)."""
        for k in keys:
            items = raw.get(k)
            if items:
                return [i for i in items if isinstance(i, dict) and i.get("url")]
        return []

    @staticmethod
    def _best(items: List[dict], lang_priority: List[str]) -> Optional[str]:
        """Pick the best image url: language tier first, then most ``likes``."""
        if not items:
            return None

        def lang_tier(it: dict) -> int:
            lang = (it.get("lang") or "").strip().lower()
            if lang in _NEUTRAL_LANGS:
                lang = "00"
            try:
                return lang_priority.index(lang)
            except ValueError:
                return len(lang_priority)

        def likes(it: dict) -> int:
            try:
                return int(it.get("likes") or 0)
            except (TypeError, ValueError):
                return 0

        best = sorted(items, key=lambda it: (lang_tier(it), -likes(it)))[0]
        return best.get("url")

    def _pick_logo(self, raw: dict, kind: str, langs: List[str]) -> Optional[str]:
        keys = _MOVIE_LOGO_KEYS if kind == "movie" else _TV_LOGO_KEYS
        # Logos carry text → prefer the requested language, then neutral.
        return self._best(self._collect(raw, keys), [*langs, "00"])

    def _pick_background(
        self, raw: dict, kind: str, langs: List[str], season_key: int
    ) -> Optional[str]:
        keys = _MOVIE_BG_KEYS if kind == "movie" else _TV_BG_KEYS
        items = self._collect(raw, keys)
        if kind == "tv":
            generic = [
                i
                for i in items
                if str(i.get("season") or "").lower() in ("all", "")
            ]
            if season_key >= 0:
                # Season row: prefer that exact season, then "all"/unseasoned.
                exact = [
                    i for i in items if str(i.get("season") or "") == str(season_key)
                ]
                items = exact or generic or items
            else:
                # Show-level row: prefer series-wide ("all"/unseasoned) art over a
                # season-specific background.
                items = generic or items
        # Backgrounds are usually textless → prefer neutral, then languages.
        return self._best(items, ["00", *langs])

    # ----- http -----------------------------------------------------------

    def _fetch(self, kind: str, lookup_id: str) -> Any:
        """GET /v3/{movies|tv}/{id}. Returns the raw dict, or None on a
        transient failure; {} on a 404 (no art for this id)."""
        path = "movies" if kind == "movie" else "tv"
        url = f"{self.BASE}/{path}/{lookup_id}"
        # Personal key only — it authenticates on its own (no project key).
        params: Dict[str, str] = {"client_key": self.cfg.client_key}

        resp = self._request_with_retry(url, params, what=f"{path}/{lookup_id}")
        if resp is None:
            return None
        if resp.status_code == 404:
            return {}  # fanart has no entry for this id
        if not resp.ok:
            self.logger.warning(
                f"fanart.tv returned {resp.status_code} for {path}/{lookup_id}"
            )
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def _request_with_retry(self, url: str, params: dict, *, what: str):
        """GET-with-retry. Returns a terminal Response (2xx/404/other) for the
        caller, or None on auth failure / exhausted transient retries. Network
        errors and 5xx → backoff+retry; 429 → honor Retry-After once; 401/403 →
        disable fanart for the run."""
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = self.session.get(url, params=params, timeout=self.HTTP_TIMEOUT)
            except requests.RequestException as exc:
                if attempt == self.MAX_RETRIES - 1:
                    self.logger.warning(f"fanart.tv request failed for {what}: {exc}")
                    return None
                time.sleep(self.BACKOFF_SECONDS[attempt])
                continue

            if resp.status_code in (401, 403):
                self._auth_failed = True
                self.logger.error(
                    "fanart.tv rejected the configured key "
                    f"({resp.status_code}). Disabling fanart for this run."
                )
                return None
            if resp.status_code == 429:
                try:
                    retry_after = min(int(resp.headers.get("Retry-After", "1") or 1), 5)
                except (ValueError, TypeError):
                    retry_after = 1
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(retry_after)
                    continue
                self.logger.warning("fanart.tv rate-limited; giving up after retries")
                return None
            if resp.status_code >= 500 and attempt < self.MAX_RETRIES - 1:
                time.sleep(self.BACKOFF_SECONDS[attempt])
                continue
            return resp

        return None
