# modules/asset_renamerr.py

import json
import os
import shutil
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.util.base_module import ChubModule
from backend.util.connector import Connector
from backend.util.database import ChubDB
from backend.util.helper import create_table, print_settings
from backend.util.logger import Logger
from backend.util.notification import NotificationManager
from backend.util.plex import PlexClient
from backend.util.fanart import FanartClient
from backend.util.release_readiness import is_release_ready

# The additional (non-poster) asset types this module manages. Banner is
# deliberately absent: Plex has no banner upload API and Kometa does not read
# banners from asset directories, so there is no path to apply one. ` - Banner`
# files are still *recognized* by asset_type_regex (so they're classified as
# banners and ignored, not mis-parsed as posters) but are never processed here.
ALL_ASSET_TYPES = ["logo", "squareart", "background"]

# image_type -> PlexClient method for the direct-upload path. Banner has no
# entry: plexapi exposes no uploadBanner.
IMAGE_TYPE_TO_PLEX_METHOD = {
    "logo": "upload_logo",
    "squareart": "upload_square_art",
    "background": "upload_art",
}

# image_type -> Kometa asset-name stem. Per Kometa (PR #2681), asset directories
# read only logo and background (+ Season##_logo / Season##_background for
# seasons). squareart is NOT read from asset directories, so it has no entry and
# is skipped on the kometa path (use apply_method "plex" for square art).
IMAGE_TYPE_TO_KOMETA_NAME = {
    "logo": "logo",
    "background": "background",
}


def apply_capability(image_type: str, apply_method: str) -> Tuple[bool, str]:
    """Whether (image_type, apply_method) is actually applicable.

    Capability matrix (Plex API + Kometa PR #2681):
        logo/background → plex ✓ / kometa ✓
        squareart       → plex ✓ / kometa ✗ (Kometa ignores square art)

    (Banner is not a processable type — see ALL_ASSET_TYPES — but the generic
    branches below still return False for it defensively.)
    """
    if apply_method == "plex":
        if image_type in IMAGE_TYPE_TO_PLEX_METHOD:
            return True, ""
        return False, f"{image_type} is not uploadable to Plex directly"
    # kometa
    if image_type in IMAGE_TYPE_TO_KOMETA_NAME:
        return True, ""
    return False, (
        f"{image_type} is not read from Kometa asset directories "
        "(use apply method 'plex')"
    )


# image_type -> the key returned by FanartClient.get_images(). squareart and
# banner are absent from fanart.tv, so those types only ever resolve from local
# files even when "fanart" is a configured source.
FANART_IMAGE_KEY = {
    "logo": "logo",
    "background": "background",
}


class AssetRenamerr(ChubModule):
    """Apply additional Plex asset types — logo, square art, background —
    to matched media. (Banner is intentionally unsupported: Plex has no banner
    upload API and Kometa does not read banners from asset directories.)

    Reuses poster_renamerr's scan/match machinery (assets live in poster_cache
    tagged with image_type) and PlexClient/FanartClient. Images come from an
    ordered ``sources`` preference (local g-drive files and/or fanart.tv; first
    hit wins) and are applied either directly to Plex (uploadLogo/uploadSquareArt/
    uploadArt) or renamed into a Kometa assets directory.

    The core, ``match_and_apply_assets``, is callable two ways:
      - standalone via ``run()`` (does its own gdrive sync + scan + media load);
      - chained from poster_renamerr (``run_asset_renamerr``), which has already
        synced gdrive, scanned source_dirs into poster_cache (image_type-aware),
        and populated media_cache — so no second sync/scan/fetch is incurred.
    """

    # Report Jobs-page progress every N media items during match_and_apply.
    _PROGRESS_EVERY = 25

    def __init__(self, logger: Optional[Logger] = None) -> None:
        super().__init__(logger=logger)
        self._plex_clients: Dict[str, Optional[PlexClient]] = {}

    # ----- config helpers -------------------------------------------------

    def _active_asset_types(self) -> List[str]:
        configured = self.config.asset_types or ALL_ASSET_TYPES
        return [t for t in ALL_ASSET_TYPES if t in configured]

    def _sources(self) -> List[str]:
        """Ordered source preference (first match wins). Defaults to local."""
        return [
            s for s in (self.config.sources or ["local"]) if s in ("local", "fanart")
        ]

    def _enabled_plex_instances(self) -> List[Tuple[str, List[str]]]:
        """(instance_name, library_names) for each Plex entry that opted in.

        Mirrors poster_renamerr: only Plex instances whose per-instance
        ``add_posters`` flag is set receive direct uploads on the "plex" apply
        path. (Existing configs that predate this flag must tick it to keep
        uploading — surfaced in the module's settings UI.)
        """
        out: List[Tuple[str, List[str]]] = []
        for inst in self.config.instances:
            if isinstance(inst, dict):
                for name, opts in inst.items():
                    if getattr(opts, "add_posters", False):
                        out.append(
                            (name, list(getattr(opts, "library_names", []) or []))
                        )
        return out

    # media asset_type -> the Plex library type that can actually hold it.
    _PLEX_SECTION_TYPE = {"movie": "movie", "show": "show"}

    def _get_plex_index(self, db: ChubDB, instance_name: str):
        """Build (once per run, cached) a PlexMediaIndex over this instance's
        plex_media_cache snapshot. Returns None if the cache has no rows for the
        instance (callers then fall back to a live search)."""
        cache = getattr(self, "_plex_index_cache", None)
        if cache is None:
            cache = {}
            self._plex_index_cache = cache
        if instance_name not in cache:
            from backend.util.plex_index import PlexMediaIndex

            rows = db.plex.get_by_instance(instance_name) or []
            cache[instance_name] = PlexMediaIndex(rows) if rows else None
        return cache[instance_name]

    def _index_resolved_targets(
        self, db: ChubDB, instance_name: str, media: dict
    ) -> Optional[List[dict]]:
        """Use the guid-first PlexMediaIndex to return the Plex cache ENTRIES on
        this instance that ACTUALLY hold ``media`` (guid match beats title+year,
        so we upload only where the item exists). Each entry carries the Plex
        ``plex_id`` (ratingKey) plus the Plex-side title/year — so the upload can
        target the exact item by ratingKey instead of re-searching by the *arr
        title, which often differs from Plex's (e.g. Radarr 'Aliens vs Predator:
        Requiem' vs Plex 'AVPR: Aliens vs Predator - Requiem').

        Returns a list of entries (one per library, possibly empty = "indexed,
        not here"), or None when the index is unavailable (no snapshot) so the
        caller can fall back to a live type-filtered search.
        """
        index = self._get_plex_index(db, instance_name)
        if index is None:
            return None
        asset_type = media.get("asset_type")
        season_number = media.get("season_number")
        if asset_type == "movie":
            media_type = "movie"
        elif asset_type == "show":
            media_type = "season" if season_number is not None else "show"
        else:
            return None  # collections resolve via their own instance/library
        entries, _key = index.resolve(
            media, media_type=media_type, season_number=season_number
        )
        # One entry per library (the index lists every copy).
        seen: Set[str] = set()
        out: List[dict] = []
        for e in entries:
            lib = e.get("library_name")
            if lib and lib not in seen:
                seen.add(lib)
                out.append(e)
        return out

    def _resolve_apply_targets(
        self, db: ChubDB, media: dict, is_collection: bool
    ) -> List[Tuple[str, List[dict]]]:
        """(instance, [targets]) the direct apply should upload to, where each
        target is a dict ``{library_name, title, year, plex_id}`` describing how
        to locate the item in that library.

        Collections keep their stored instance/library. For movies/shows, prefer
        the PlexMediaIndex (guid-first) and carry the matched item's Plex
        ``plex_id`` (ratingKey) + Plex title/year — so the upload targets the
        EXACT item by ratingKey rather than re-searching by the *arr title,
        which frequently differs from Plex's (e.g. Radarr 'Aliens vs Predator:
        Requiem' vs Plex 'AVPR: Aliens vs Predator - Requiem'). Fall back
        per-instance to a live type-filtered search (by *arr title, no plex_id)
        when the index has no snapshot. Single source of truth for both the
        upload loop and the per-library idempotency key-set, so they can't drift.
        """
        media_title = media.get("title")
        media_year = self._media_year(media)
        if is_collection:
            return [
                (
                    media.get("instance_name"),
                    [
                        {
                            "library_name": media.get("library_name"),
                            "title": media_title,
                            "year": media_year,
                            "plex_id": None,
                        }
                    ],
                )
            ]

        expected = self._PLEX_SECTION_TYPE.get(media.get("asset_type"))
        out: List[Tuple[str, List[dict]]] = []
        for instance_name, opted_libs in self._enabled_plex_instances():
            resolved = self._index_resolved_targets(db, instance_name, media)
            if resolved is None:
                # No index snapshot → live type-filtered fallback (by *arr title).
                client = self._plex_client_for(instance_name)
                getter = getattr(client, "section_type", None) if client else None
                targets: List[dict] = []
                for lib in opted_libs:
                    if not lib:
                        continue
                    st = getter(lib) if (getter and expected) else None
                    if st is None or st == expected:
                        targets.append(
                            {
                                "library_name": lib,
                                "title": media_title,
                                "year": media_year,
                                "plex_id": None,
                            }
                        )
            else:
                # Index hit: keep entries whose library is opted-in, carrying the
                # Plex ratingKey + Plex title/year (falling back to *arr values
                # only when the cache row omits them).
                opted = {lib for lib in opted_libs if lib}
                targets = [
                    {
                        "library_name": e.get("library_name"),
                        "title": e.get("title") or media_title,
                        "year": (
                            e.get("year")
                            if e.get("year") not in (None, "", "None")
                            else media_year
                        ),
                        "plex_id": e.get("plex_id"),
                    }
                    for e in resolved
                    if not opted or e.get("library_name") in opted
                ]
            if targets:
                out.append((instance_name, targets))
        return out

    def _type_matched_targets(self, media: dict) -> List[Tuple[str, List[str]]]:
        """Opted-in (instance, libraries) targets, dropping libraries whose Plex
        type can't hold this item — e.g. a movie is never in a 'show' library, so
        searching one is a guaranteed miss (and was the source of noisy "not
        found" logs). A library is only excluded when its type is KNOWN and
        mismatches; if the type can't be resolved (no client / offline), the
        library is kept so behaviour degrades to the old "search everything".
        """
        expected = self._PLEX_SECTION_TYPE.get(media.get("asset_type"))
        out: List[Tuple[str, List[str]]] = []
        for instance_name, libraries in self._enabled_plex_instances():
            client = self._plex_client_for(instance_name)
            getter = getattr(client, "section_type", None) if client else None
            libs: List[str] = []
            for lib in libraries:
                if not lib:
                    continue
                st = getter(lib) if (getter and expected) else None
                if st is None or st == expected:
                    libs.append(lib)
            if libs:
                out.append((instance_name, libs))
        return out

    def _direct_target_lib_keys(
        self, db: ChubDB, media: dict, is_collection: bool
    ) -> Set[str]:
        """The set of "instance/library" keys a direct apply should cover for
        this item — used both to upload and to decide whether a prior apply is
        still complete (per-library backfill). Resolved via the same index-first
        path as the upload loop so the expected set matches what _apply_direct
        will actually attempt."""
        keys: Set[str] = set()
        for instance_name, targets in self._resolve_apply_targets(
            db, media, is_collection
        ):
            for tgt in targets:
                lib = tgt.get("library_name")
                if lib:
                    keys.add(f"{instance_name}/{lib}")
        return keys

    def _plex_client_for(self, instance_name: str) -> Optional[PlexClient]:
        """Build (and cache) a connected PlexClient for an instance, or None."""
        if instance_name in self._plex_clients:
            return self._plex_clients[instance_name]
        plex_cfg = self.full_config.instances.plex.get(instance_name)
        client = None
        if plex_cfg and plex_cfg.url and plex_cfg.api:
            candidate = PlexClient(plex_cfg.url, plex_cfg.api, self.logger)
            if candidate.is_connected():
                client = candidate
            else:
                self.logger.error(
                    f"Failed to connect to Plex instance '{instance_name}'"
                )
        self._plex_clients[instance_name] = client
        return client

    # ----- media gathering (mirrors poster_renamerr.match_assets_to_media) -

    def _gather_media(self, db: ChubDB) -> List[dict]:
        from backend.util.connector import gather_media_and_collections

        return gather_media_and_collections(self.config, db)

    @staticmethod
    def _media_year(media: dict) -> Any:
        year = media.get("year")
        try:
            return int(year) if year not in (None, "", "None") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _kometa_folder(media: dict) -> str:
        """Folder name Kometa expects for this item's assets.

        Prefer the *arr folder basename when present (matches how poster
        assets are foldered); otherwise fall back to "Title (Year)".
        """
        folder = media.get("folder")
        if folder:
            return os.path.basename(str(folder).rstrip("/"))
        title = media.get("title") or ""
        year = AssetRenamerr._media_year(media)
        return f"{title} ({year})" if year else title

    # ----- scan (standalone path only) ------------------------------------

    def _scan_local_sources(self, db: ChubDB) -> None:
        """Scan source_dirs and upsert asset rows (image_type != poster) into
        poster_cache. Standalone path only — when chained from poster_renamerr
        the shared merge_assets scan has already populated these rows.

        Posters (suffix-less files) are intentionally skipped here so this run
        never disturbs the poster rows that poster_renamerr owns. A full
        poster_renamerr run remains the authoritative clear-and-rebuild of the
        shared cache.
        """
        from backend.modules.poster_renamerr import build_asset_record

        active = set(self._active_asset_types())
        source_dirs = self.config.source_dirs or []
        for priority, source_dir in enumerate(source_dirs):
            if not source_dir or not os.path.isdir(source_dir):
                self.logger.warning(f"Source dir not found: '{source_dir}'")
                continue
            # Drop stale asset rows for this source_dir before re-inserting.
            deleted = db.poster.delete_asset_rows_by_path_prefix(source_dir)
            self.logger.debug(
                f"Cleared {deleted} stale asset rows for '{source_dir}'"
            )
            records = []
            for root, dirs, files in os.walk(source_dir):
                dirs.sort(key=str.lower)
                for fname in sorted(files, key=str.lower):
                    if not fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                        continue
                    record = build_asset_record(fname, root, priority=priority)
                    if record.get("image_type") in active:
                        # classify asset_type (movie/show/collection) per-record;
                        # season detection is already in the record.
                        record["asset_type"] = self._classify(record)
                        records.append(record)
            # Batch the upserts: one transaction per chunk, not per row.
            count = db.poster.bulk_upsert(records)
            self.logger.info(f"Scanned {count} asset files from '{source_dir}'")

    @staticmethod
    def _classify(record: dict) -> str:
        if record.get("season_number") is not None or record.get("tvdb_id"):
            return "show"
        if record.get("year") is None:
            return "collection"
        return "movie"

    # ----- source resolution ----------------------------------------------

    def _resolve_source(
        self,
        media: dict,
        db: ChubDB,
        image_type: str,
        is_collection: bool,
        fanart_client: Optional[FanartClient],
        conn=None,
    ) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
        """Resolve one (media, image_type) to an image, honouring the ordered
        ``sources`` preference. Returns ``(source, file, url)`` for the first
        source that yields one, or None.

        ``conn`` (optional) is a reused read-only poster_cache connection — the
        loop passes one so the per-item candidate lookups don't each open a
        fresh connection.
        """
        from backend.modules.poster_renamerr import PosterRenamerr

        for source in self._sources():
            if source == "local":
                found = PosterRenamerr.find_asset_candidate(
                    media,
                    db,
                    image_type=image_type,
                    is_collection=is_collection,
                    conn=conn,
                )
                cand = found.get("candidate")
                if found.get("matched") and cand and cand.get("file"):
                    return ("local", cand["file"], None)
            elif source == "fanart":
                fanart_key = FANART_IMAGE_KEY.get(image_type)
                # fanart has no squareart/banner; collections aren't supported.
                if not fanart_key or is_collection or not fanart_client:
                    continue
                images = fanart_client.get_images(
                    media, language=self.config.tmdb_language
                )
                url = (images or {}).get(fanart_key)
                if url:
                    return ("fanart", None, url)
        return None

    # ----- apply ----------------------------------------------------------

    def _already_applied(
        self,
        db: ChubDB,
        prev: Optional[dict],
        apply_method: str,
        source: str,
        file: Optional[str],
        url: Optional[str],
        src_mtime: Optional[float],
        media: Optional[dict] = None,
        is_collection: bool = False,
    ) -> bool:
        """True when this asset was already applied with the same source and the
        source hasn't changed — so we can skip re-applying it. Never skip on a
        dry run (we still want the would-do report).

        ``prev`` is the preloaded media_asset_matches row for this
        (target, image_type), or None — looked up from the run's applied_map so
        this is a per-item DB read no longer.
        """
        if self.config.dry_run:
            return False
        if not prev or prev.get("match_status") != "applied":
            return False
        if prev.get("applied_method") != apply_method or prev.get("source") != source:
            return False
        # For the kometa path, the destination file must still exist.
        if apply_method == "kometa":
            applied_path = prev.get("applied_path")
            if not applied_path or not os.path.lexists(applied_path):
                return False
        # For the plex path, only skip if EVERY currently-targeted library
        # already received it; otherwise re-apply so a newly-added or
        # previously-failed library copy gets backfilled (mirrors the poster
        # uploaded_libraries logic).
        if apply_method == "plex" and media is not None:
            expected = self._direct_target_lib_keys(db, media, is_collection)
            try:
                recorded = set(json.loads(prev.get("applied_libraries") or "[]"))
            except (ValueError, TypeError):
                self.logger.debug(
                    "Could not parse applied_libraries "
                    f"{prev.get('applied_libraries')!r}; treating as unapplied"
                )
                recorded = set()
            if not expected.issubset(recorded):
                return False
        if source == "fanart":
            return bool(url) and prev.get("matched_url") == url
        # local: same file + unchanged mtime
        return (
            bool(file)
            and prev.get("matched_file") == file
            and prev.get("source_mtime") is not None
            and src_mtime is not None
            and float(prev.get("source_mtime")) == float(src_mtime)
        )

    def _apply_direct(
        self,
        db: ChubDB,
        media: dict,
        image_type: str,
        file: Optional[str],
        url: Optional[str],
        is_collection: bool,
    ) -> Tuple[bool, str, List[str]]:
        method_name = IMAGE_TYPE_TO_PLEX_METHOD.get(image_type)
        if not method_name:
            return False, "banner is not uploadable via Plex; use Kometa apply", []

        title = media.get("title")
        year = self._media_year(media)
        season_number = media.get("season_number")

        # Index-first (guid-matched, only libraries that actually hold the item);
        # lazy live type-filtered fallback when no cache snapshot exists.
        targets = self._resolve_apply_targets(db, media, is_collection)

        # Upload to EVERY matching library, not just the first — an item that
        # lives in both a 1080p and a 4K library should get the asset in both.
        # Each target carries the Plex ratingKey (plex_id) + Plex title/year, so
        # the upload hits the exact item; fall back to the media's own
        # title/year when a target omits them (lazy/no-index path).
        applied_to: List[str] = []
        for instance_name, lib_targets in targets:
            client = self._plex_client_for(instance_name)
            if not client:
                continue
            for tgt in lib_targets:
                lib = tgt.get("library_name")
                if not lib:
                    continue
                ok = getattr(client, method_name)(
                    lib,
                    tgt.get("title") or title,
                    filepath=file,
                    url=url,
                    year=(tgt.get("year") if tgt.get("year") is not None else year),
                    is_collection=is_collection,
                    season_number=season_number,
                    dry_run=self.config.dry_run,
                    plex_id=tgt.get("plex_id"),
                )
                if ok:
                    applied_to.append(f"{instance_name}/{lib}")
        if applied_to:
            return True, ", ".join(applied_to), applied_to
        return False, "not found in any configured Plex library", []

    def _apply_kometa(
        self,
        media: dict,
        image_type: str,
        source: str,
        file: Optional[str],
        url: Optional[str],
    ) -> Tuple[bool, str]:
        dest_root = self.config.destination_dir
        if not dest_root:
            return False, "no destination_dir configured for Kometa apply"

        # Kometa applies LOCAL files only — fanart art is never downloaded to
        # disk (it's Plex-only, streamed straight to Plex). fanart is already
        # filtered out of the Kometa source set in match_and_apply_assets, so
        # this is a defensive guard.
        if source == "fanart":
            return False, "fanart art is Plex-only and is never downloaded for Kometa"
        src = file
        if not src:
            return False, "no local source file to apply"

        ext = os.path.splitext(src)[1] or ".png"
        folder = self._kometa_folder(media)

        # Kometa asset-name stem (logo/background). Season-level assets on a show
        # use Kometa's "Season##_<stem>" form (PR #2681).
        stem = IMAGE_TYPE_TO_KOMETA_NAME.get(image_type, image_type)
        season_number = media.get("season_number")
        if media.get("asset_type") == "show" and season_number is not None:
            stem = f"Season{int(season_number):02d}_{stem}"

        if self.config.asset_folders:
            dest_dir = os.path.join(dest_root, folder)
            new_name = f"{stem}{ext}"
        else:
            dest_dir = dest_root
            new_name = f"{folder}_{stem}{ext}"

        # Path-traversal guard (folder may come from external metadata).
        real_dest = os.path.realpath(dest_dir)
        real_base = os.path.realpath(dest_root)
        if not (real_dest == real_base or real_dest.startswith(real_base + os.sep)):
            return False, f"path traversal blocked for folder '{folder}'"

        new_path = os.path.join(dest_dir, new_name)
        if not self.config.dry_run:
            try:
                os.makedirs(dest_dir, exist_ok=True)
                self._file_op(src, new_path, self.config.action_type)
            except OSError as exc:
                return False, f"file op failed: {exc}"
        return True, new_path

    def apply_chosen_asset(
        self,
        db: ChubDB,
        target_kind: str,
        media: dict,
        image_type: str,
        file: str,
    ) -> Tuple[bool, str]:
        """Apply one user-chosen artwork file to a single (media, image_type)
        immediately, the same way a full run would, and lock it.

        Mirrors the poster picker's inline apply (api.posters.apply_match): copy
        to the Kometa destination or upload straight to Plex per the module's
        apply_method, record provenance in media_asset_matches, and set the
        user_confirmed lock so future runs reuse this exact file instead of
        re-resolving. Returns (applied, detail)."""
        is_collection = target_kind == "collection"
        apply_method = self.config.apply_method
        try:
            src_mtime: Optional[float] = os.stat(file).st_mtime
        except OSError as exc:
            self.logger.debug(f"Could not stat chosen asset '{file}': {exc}")
            src_mtime = None

        applied_libs: Optional[List[str]] = None
        if apply_method == "plex":
            applied, detail, applied_libs = self._apply_direct(
                db, media, image_type, file, None, is_collection
            )
        else:
            applied, detail = self._apply_kometa(
                media, image_type, "local", file, None
            )

        target_id = media.get("id")
        if target_id is not None:
            db.media_asset_matches.upsert(
                target_kind=target_kind,
                target_id=target_id,
                image_type=image_type,
                source="local",
                matched_file=file,
                matched_url=None,
                source_mtime=src_mtime,
                applied_method=apply_method,
                applied_path=detail if applied else None,
                applied_libraries=(
                    json.dumps(sorted(applied_libs)) if applied_libs else None
                ),
                match_status="applied" if applied else "failed",
                detail=detail,
            )
            # Lock the manual pick regardless of apply outcome — even if this
            # leg failed (e.g. Plex briefly unreachable), the chosen file is
            # saved and the next run reuses it instead of re-resolving.
            db.media_asset_matches.set_user_confirmed(
                target_kind, target_id, image_type, True
            )
        return applied, detail

    def _file_op(self, src: str, dest: str, action_type: str) -> None:
        if action_type == "move":
            shutil.move(src, dest)
        elif action_type in ("hardlink", "symlink"):
            # Create the link under a temp name and os.replace() it over the
            # destination — never remove dest first, so a failed link (source
            # vanished, ENOSPC, cross-device) can't destroy the existing file.
            tmp = f"{dest}.chub-tmp-{os.getpid()}"
            try:
                if action_type == "hardlink":
                    os.link(src, tmp)
                else:
                    os.symlink(src, tmp)
                os.replace(tmp, dest)
            except OSError:
                self._cleanup(tmp)
                raise
        else:  # copy (default)
            shutil.copy(src, dest)
        self.logger.debug(f"[{action_type.upper()}] {dest} ← {src}")

    def _cleanup(self, path: Optional[str]) -> None:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError as exc:
                # Best-effort cleanup of an internally-generated temp file;
                # non-fatal, but leave a trace so accumulation is explainable.
                self.logger.debug(f"Temp file cleanup failed: {path} — {exc}")

    # ----- orchestration --------------------------------------------------

    def match_and_apply_assets(self, db: ChubDB) -> Dict[str, List[dict]]:
        """Match every configured image_type for every media item and apply it.

        Assumes poster_cache (asset rows) and media_cache are already populated
        — run() / the poster_renamerr chain hook are responsible for that.
        Returns an output dict grouped by image_type for notifications.
        """
        apply_method = self.config.apply_method

        # Resolve which configured types are actually applicable for this apply
        # method ONCE (banner is never applicable; squareart needs "plex").
        # Warn once per skipped type rather than emitting a line per media item.
        applicable: List[str] = []
        for image_type in self._active_asset_types():
            capable, why = apply_capability(image_type, apply_method)
            if capable:
                applicable.append(image_type)
            else:
                self.logger.warning(f"Skipping '{image_type}': {why}")

        output: Dict[str, List[dict]] = {t: [] for t in applicable}
        if not applicable:
            self.logger.warning("No applicable asset types for this apply method.")
            return output

        all_media = self._gather_media(db)
        if not all_media:
            self.logger.warning("No media or collections found for asset matching.")
            return output

        # On the plex path, resolve upload targets from the plex_media_cache via
        # PlexMediaIndex (guid-first). Refresh that snapshot once up front (TTL-
        # guarded, so a chained poster_renamerr run that just walked Plex isn't
        # re-walked), then reset any stale per-run index so it rebuilds from the
        # fresh rows. A lazy live search still covers items added post-refresh.
        if apply_method == "plex" and not self.config.dry_run:
            self._plex_index_cache = {}
            try:
                from backend.util.plex_refresh import refresh_plex_cache_if_stale

                enabled = {
                    name: libs for name, libs in self._enabled_plex_instances()
                }
                refresh_plex_cache_if_stale(
                    db, self.full_config, self.logger, enabled
                )
            except Exception as exc:
                # Never fail the run on a refresh hiccup — the index falls back
                # to whatever snapshot exists, and per-item lazy search covers
                # misses.
                self.logger.warning(
                    f"Plex cache refresh skipped ({exc}); using existing snapshot."
                )

        # fanart.tv is a PLEX-ONLY source: its art is streamed straight to Plex
        # (Plex fetches the URL) and is never written to disk. Kometa needs
        # local files, so using fanart there would mean downloading/storing a
        # copy — against fanart.tv's API use — so Kometa uses local g-drive
        # assets only and the fanart client is simply never created for it.
        fanart_client = None
        if "fanart" in self._sources():
            if apply_method != "plex":
                self.logger.info(
                    "fanart.tv source ignored for Kometa apply — fanart art is "
                    "only applied via direct-to-Plex upload (never downloaded to "
                    "disk). Kometa uses local g-drive assets only; switch "
                    "apply_method to 'plex' to use fanart."
                )
            else:
                fanart_client = FanartClient(self.full_config.fanart, db, self.logger)
                if not fanart_client.enabled:
                    self.logger.info(
                        "fanart.tv source requested but no personal API key is "
                        "configured; add your fanart.tv key in settings. Falling "
                        "back to local sources only."
                    )
                    fanart_client = None

        # Preload every match row once into an in-memory map, keyed by
        # (target_kind, target_id, image_type). The idempotency check + the
        # missing-row guard used to do a single-row DB read (get_one) per
        # (item, image_type) — thousands of connections on a large library.
        # One query + dict lookups replaces all of them.
        applied_map: Dict[Tuple[str, int, str], dict] = {}
        for _row in db.media_asset_matches.get_all():
            _tid = _row.get("target_id")
            if _tid is not None:
                applied_map[
                    (_row.get("target_kind"), int(_tid), _row.get("image_type"))
                ] = _row

        total = len(all_media)
        # One reused read-only connection for the loop's poster_cache lookups
        # (find_asset_candidate fires several per item). This replaces the
        # per-query connect/PRAGMA/close churn with a single connect for the
        # whole loop. Read-only (query_only); closed after the loop — on an
        # exception it's reclaimed on GC, which is safe for a read connection.
        poster_conn = db.poster.open_read_connection()
        for idx, media in enumerate(all_media, 1):
            if self.is_cancelled():
                break
            # Report Jobs-page progress over the media loop (the dominant phase:
            # it hits Plex/TMDB per item). No-op when chained from poster_renamerr
            # (that instance has no job context); active on a standalone run.
            if idx % self._PROGRESS_EVERY == 0 or idx == total:
                self._report_progress(int(idx / total * 100))

            is_collection = media.get("asset_type") == "collection"
            target_kind = "collection" if is_collection else "media"
            target_id = media.get("id")

            # Release-readiness gate (Plex apply only): an unreleased or
            # undownloaded *arr item has nothing in Plex to attach artwork to,
            # so a direct upload can only ever fail with "not found in any
            # configured Plex library". Skip it instead of recording a noisy
            # false-positive failure — the unmatched report already hides these
            # via the same shared gate (release_readiness). The Kometa path is
            # exempt: it writes to asset folders by name regardless of Plex.
            if apply_method == "plex" and not is_release_ready(media):
                self.logger.debug(
                    f"↳ skipping {media.get('title')}: not released / no "
                    "downloaded file — nothing in Plex to apply artwork to"
                )
                continue

            for image_type in applicable:
                # Manual-pick lock: when the user chose a specific file in the
                # picker, reuse it verbatim instead of re-resolving — a re-run
                # must never overwrite a locked pick (mirrors poster_renamerr's
                # user_confirmed early-return). Falls back to auto-resolution if
                # the locked file has since vanished from disk.
                locked = (
                    applied_map.get((target_kind, int(target_id), image_type))
                    if target_id is not None
                    else None
                )
                if (
                    locked
                    and locked.get("user_confirmed")
                    and locked.get("matched_file")
                    and os.path.exists(locked["matched_file"])
                ):
                    resolved: Optional[Tuple[str, Optional[str], Optional[str]]] = (
                        "local",
                        locked["matched_file"],
                        None,
                    )
                else:
                    resolved = self._resolve_source(
                        media,
                        db,
                        image_type,
                        is_collection,
                        fanart_client,
                        conn=poster_conn,
                    )
                if not resolved:
                    # No source artwork anywhere for this (item, type). Record a
                    # "missing" row so the Unmatched view can derive coverage
                    # purely from this table — a reset empties it (→ all counts 0)
                    # and the next run repopulates it. Don't downgrade an item
                    # that's already applied (e.g. the art lives in Plex but the
                    # local source later vanished), and never persist on a dry run
                    # (media_asset_matches drives idempotency — see below).
                    if target_id is not None and not self.config.dry_run:
                        prev = applied_map.get(
                            (target_kind, int(target_id), image_type)
                        )
                        if not (prev and prev.get("match_status") == "applied"):
                            db.media_asset_matches.upsert(
                                target_kind=target_kind,
                                target_id=target_id,
                                image_type=image_type,
                                match_status="missing",
                                detail="no source artwork found",
                            )
                    continue
                source, file, url = resolved

                # Idempotency: skip when this exact asset was already applied and
                # hasn't changed since — so a scheduled run (or the chained
                # run_asset_renamerr) doesn't re-push every logo/art to Plex and
                # re-fetch every TMDB URL on every pass. Local files compare by
                # mtime; TMDB by URL.
                src_mtime = None
                if source == "local" and file:
                    try:
                        src_mtime = os.stat(file).st_mtime
                    except OSError:
                        src_mtime = None
                prev = (
                    applied_map.get((target_kind, int(target_id), image_type))
                    if target_id is not None
                    else None
                )
                if target_id is not None and self._already_applied(
                    db,
                    prev,
                    apply_method,
                    source,
                    file,
                    url,
                    src_mtime,
                    media=media,
                    is_collection=is_collection,
                ):
                    self.logger.debug(
                        f"↳ unchanged, skipping {image_type} for {media.get('title')}"
                    )
                    continue

                applied_libs: Optional[List[str]] = None
                if apply_method == "plex":
                    applied, detail, applied_libs = self._apply_direct(
                        db, media, image_type, file, url, is_collection
                    )
                else:
                    applied, detail = self._apply_kometa(
                        media, image_type, source, file, url
                    )

                # On a dry run, NEVER persist match state: media_asset_matches
                # drives idempotency (_already_applied), so recording a dry-run
                # as "applied" would make the next REAL run skip an item that
                # was never actually uploaded. We still report it in the output
                # (marked "would apply") so the dry-run preview is complete.
                if target_id is not None and not self.config.dry_run:
                    db.media_asset_matches.upsert(
                        target_kind=target_kind,
                        target_id=target_id,
                        image_type=image_type,
                        source=source,
                        matched_file=file,
                        matched_url=url,
                        source_mtime=src_mtime,
                        applied_method=apply_method,
                        applied_path=detail if applied else None,
                        applied_libraries=(
                            json.dumps(sorted(applied_libs)) if applied_libs else None
                        ),
                        match_status="applied" if applied else "failed",
                        # Persist the outcome detail on BOTH paths so a failed
                        # apply can explain itself in the Needs-Review view.
                        detail=detail,
                    )

                output[image_type].append(
                    {
                        "title": media.get("title"),
                        "year": self._media_year(media),
                        "source": source,
                        "applied": applied,
                        "dry_run": self.config.dry_run,
                        "reason": detail,
                    }
                )
                if applied:
                    prefix = "[DRY RUN] would apply" if self.config.dry_run else "✓"
                    self.logger.debug(
                        f"{prefix} {image_type} [{source}] "
                        f"{media.get('title')} -> {detail}"
                    )
        poster_conn.close()
        return output

    def handle_output(self, output: Dict[str, List[dict]]) -> None:
        # When print_only_renames is set, list only the assets actually applied
        # (suppress the per-item lines for unchanged/failed) — the header +
        # "N/M applied" count is always shown so the run is still summarised.
        only_applied = bool(getattr(self.config, "print_only_renames", False))
        dry = bool(getattr(self.config, "dry_run", False))
        for image_type, entries in output.items():
            applied = [e for e in entries if e.get("applied")]
            self.logger.info(create_table([[image_type.capitalize()]]))
            if not entries:
                self.logger.info(f"No {image_type} assets matched\n")
                continue
            verb = "would be applied" if dry else "applied"
            self.logger.info(
                f"{len(applied)}/{len(entries)} {image_type} assets {verb}"
            )
            shown = applied if only_applied else entries
            for e in shown:
                title = e.get("title") or ""
                year = e.get("year")
                display = f"{title} ({year})" if year else title
                # On a dry run an "applied" item is only a projection — show
                # "⊘ would apply" so the preview can't be mistaken for a real
                # upload (a genuine miss stays "✗").
                if e.get("applied"):
                    mark = "⊘ would apply" if dry else "✓"
                else:
                    mark = "✗"
                self.logger.info(f"\t{mark} {display} — {e.get('reason')}")
            self.logger.info("")

    def run(self) -> None:
        try:
            with ChubDB(logger=self.logger) as db:
                self._report_progress(0)
                if self.config.log_level == "debug":
                    print_settings(self.logger, self.config)

                if self.config.dry_run:
                    self.logger.info(
                        create_table([["Dry Run"], ["NO CHANGES WILL BE MADE"]])
                    )

                # Declare the phases this run will execute (gated by config) so
                # the Jobs page shows each sub-step and its timing.
                phase_plan = []
                if self.config.sync_assets:
                    phase_plan.append("sync_gdrive")
                if "local" in self._sources():
                    phase_plan.append("scan")
                phase_plan += ["arr/collections sync", "match & apply"]
                self._declare_phases(phase_plan)

                if self.config.sync_assets:
                    # try/except is OUTSIDE the phase so a sync failure marks the
                    # phase 'error' (accurate timeline) while the outer handler
                    # swallows it — sync is non-fatal, the run still continues.
                    try:
                        with self._phase("sync_gdrive"):
                            self.logger.info("Running sync_gdrive")
                            from backend.modules.sync_gdrive import SyncGDrive

                            sync = SyncGDrive(logger=self.logger)
                            # Sync drives the bar's 0..10 slice as folders
                            # complete; the rest of this run drives 10..100.
                            sync.set_job_context(
                                getattr(self, "_job_id", None),
                                getattr(self, "_job_db", None),
                            )
                            sync.set_progress_window(0, 10)
                            sync.run()
                            self.logger.info("Finished running sync_gdrive")
                    except Exception as exc:
                        self.logger.error(f"sync_gdrive failed: {exc}")
                    # Reserve the sync slice: the remaining phases (scan /
                    # arr-collections / match & apply) report into 10..100.
                    self.set_progress_window(10, 100)

                if "local" in self._sources():
                    with self._phase("scan"):
                        self._scan_local_sources(db)

                from backend.util.connector import build_instance_map

                with self._phase("arr/collections sync"):
                    connector = Connector(
                        db=db,
                        logger=self.logger,
                        instance_map=build_instance_map(self.config),
                    )
                    connector.update_arr_database()
                    connector.update_collections_database()

                with self._phase("match & apply"):
                    output = self.match_and_apply_assets(db)
                self.handle_output(output)

                manager = NotificationManager(
                    self.full_config, self.logger, module_name="asset_renamerr"
                )
                manager.send_notification(output)
                self._report_progress(100)
        except KeyboardInterrupt:
            self.logger.info("Asset Renamerr interrupted. Exiting...")
        except Exception:
            self.logger.error("\n\nAn error occurred:\n", exc_info=True)
        finally:
            # Mark any declared-but-unreached phases skipped so the Jobs
            # timeline doesn't leave them stuck pending after an early failure.
            self._finalize_phases()
