# modules/asset_renamerr.py

import json
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

from backend.util.base_module import ChubModule
from backend.util.connector import Connector
from backend.util.database import ChubDB
from backend.util.helper import create_table, print_settings
from backend.util.logger import Logger
from backend.util.notification import NotificationManager
from backend.util.plex import PlexClient
from backend.util.ssrf_guard import is_safe_url
from backend.util.tmdb import TMDBClient

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
# is skipped on the kometa path (use apply_method "direct" for square art).
IMAGE_TYPE_TO_KOMETA_NAME = {
    "logo": "logo",
    "background": "background",
}


def apply_capability(image_type: str, apply_method: str) -> Tuple[bool, str]:
    """Whether (image_type, apply_method) is actually applicable.

    Capability matrix (Plex API + Kometa PR #2681):
        logo/background → direct ✓ / kometa ✓
        squareart       → direct ✓ / kometa ✗ (Kometa ignores square art)

    (Banner is not a processable type — see ALL_ASSET_TYPES — but the generic
    branches below still return False for it defensively.)
    """
    if apply_method == "direct":
        if image_type in IMAGE_TYPE_TO_PLEX_METHOD:
            return True, ""
        return False, f"{image_type} is not uploadable to Plex directly"
    # kometa
    if image_type in IMAGE_TYPE_TO_KOMETA_NAME:
        return True, ""
    return False, (
        f"{image_type} is not read from Kometa asset directories "
        "(use apply method 'direct')"
    )


# image_type -> the TMDB image class get_images() can supply. squareart and
# banner are absent from TMDB, so those types only ever resolve from local
# files even when "tmdb" is a configured source.
TMDB_IMAGE_KEY = {
    "logo": "logo",
    "background": "background",
}


class AssetRenamerr(ChubModule):
    """Apply additional Plex asset types — clear logo, square art, background —
    to matched media. (Banner is intentionally unsupported: Plex has no banner
    upload API and Kometa does not read banners from asset directories.)

    Reuses poster_renamerr's scan/match machinery (assets live in poster_cache
    tagged with image_type) and PlexClient/TMDBClient. Images come from an
    ordered ``sources`` preference (local g-drive files and/or TMDB; first hit
    wins) and are applied either directly to Plex (uploadLogo/uploadSquareArt/
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
        return [s for s in (self.config.sources or ["local"]) if s in ("local", "tmdb")]

    def _enabled_plex_instances(self) -> List[Tuple[str, List[str]]]:
        """(instance_name, library_names) for each Plex entry in instances."""
        out: List[Tuple[str, List[str]]] = []
        for inst in self.config.instances:
            if isinstance(inst, dict):
                for name, opts in inst.items():
                    out.append((name, list(getattr(opts, "library_names", []) or [])))
        return out

    def _direct_target_lib_keys(self, media: dict, is_collection: bool) -> Set[str]:
        """The set of "instance/library" keys a direct apply should cover for
        this item — used both to upload and to decide whether a prior apply is
        still complete (per-library backfill)."""
        if is_collection:
            targets = [(media.get("instance_name"), [media.get("library_name")])]
        else:
            targets = self._enabled_plex_instances()
        keys: Set[str] = set()
        for instance_name, libraries in targets:
            for lib in libraries:
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
            db.poster.delete_asset_rows_by_path_prefix(source_dir)
            count = 0
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
                        db.poster.upsert(record)
                        count += 1
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
        tmdb_client: Optional[TMDBClient],
    ) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
        """Resolve one (media, image_type) to an image, honouring the ordered
        ``sources`` preference. Returns ``(source, file, url)`` for the first
        source that yields one, or None.
        """
        from backend.modules.poster_renamerr import PosterRenamerr

        for source in self._sources():
            if source == "local":
                found = PosterRenamerr.find_asset_candidate(
                    media, db, image_type=image_type, is_collection=is_collection
                )
                cand = found.get("candidate")
                if found.get("matched") and cand and cand.get("file"):
                    return ("local", cand["file"], None)
            elif source == "tmdb":
                tmdb_key = TMDB_IMAGE_KEY.get(image_type)
                tmdb_id = media.get("tmdb_id")
                if not tmdb_key or not tmdb_id or not tmdb_client:
                    continue
                media_type = "movie" if media.get("asset_type") == "movie" else "tv"
                images = tmdb_client.get_images(
                    int(tmdb_id), media_type, language=self.config.tmdb_language
                )
                url = (images or {}).get(tmdb_key)
                if url:
                    return ("tmdb", None, url)
        return None

    # ----- apply ----------------------------------------------------------

    def _already_applied(
        self,
        db: ChubDB,
        target_kind: str,
        target_id: int,
        image_type: str,
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
        dry run (we still want the would-do report)."""
        if self.config.dry_run:
            return False
        prev = db.media_asset_matches.get_one(target_kind, target_id, image_type)
        if not prev or prev.get("match_status") != "applied":
            return False
        if prev.get("applied_method") != apply_method or prev.get("source") != source:
            return False
        # For the kometa path, the destination file must still exist.
        if apply_method == "kometa":
            applied_path = prev.get("applied_path")
            if not applied_path or not os.path.lexists(applied_path):
                return False
        # For the direct path, only skip if EVERY currently-targeted library
        # already received it; otherwise re-apply so a newly-added or
        # previously-failed library copy gets backfilled (mirrors the poster
        # uploaded_libraries logic).
        if apply_method == "direct" and media is not None:
            expected = self._direct_target_lib_keys(media, is_collection)
            try:
                recorded = set(json.loads(prev.get("applied_libraries") or "[]"))
            except (ValueError, TypeError):
                recorded = set()
            if not expected.issubset(recorded):
                return False
        if source == "tmdb":
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

        if is_collection:
            targets = [(media.get("instance_name"), [media.get("library_name")])]
        else:
            targets = self._enabled_plex_instances()

        # Upload to EVERY matching library, not just the first — an item that
        # lives in both a 1080p and a 4K library should get the asset in both.
        applied_to: List[str] = []
        for instance_name, libraries in targets:
            client = self._plex_client_for(instance_name)
            if not client:
                continue
            for lib in libraries:
                if not lib:
                    continue
                ok = getattr(client, method_name)(
                    lib,
                    title,
                    filepath=file,
                    url=url,
                    year=year,
                    is_collection=is_collection,
                    season_number=season_number,
                    dry_run=self.config.dry_run,
                )
                if ok:
                    applied_to.append(f"{instance_name}/{lib}")
        if applied_to:
            return True, ", ".join(applied_to), applied_to
        return False, "not found in any configured Plex library", []

    def _download_to_temp(self, url: str) -> Optional[str]:
        ok, reason = is_safe_url(url, allow_private=False)
        if not ok:
            self.logger.warning(f"Refusing to download unsafe URL ({reason}): {url}")
            return None
        try:
            resp = requests.get(url, timeout=20, stream=True)
            if not resp.ok:
                self.logger.warning(f"Download failed ({resp.status_code}): {url}")
                return None
            ext = os.path.splitext(url.split("?")[0])[1] or ".png"
            fd, path = tempfile.mkstemp(suffix=ext)
            with os.fdopen(fd, "wb") as fh:
                for chunk in resp.iter_content(8192):
                    fh.write(chunk)
            return path
        except requests.RequestException as exc:
            self.logger.warning(f"Download error for {url}: {exc}")
            return None

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

        # Obtain a local source file (download TMDB urls first).
        temp_file = None
        src = file
        if source == "tmdb":
            if self.config.dry_run:
                src = "<tmdb>"  # placeholder; nothing is written in dry-run
            else:
                temp_file = self._download_to_temp(url) if url else None
                src = temp_file
                if not src:
                    return False, "tmdb download failed"

        ext = (
            os.path.splitext(src)[1]
            if src and src != "<tmdb>"
            else (os.path.splitext((url or "").split("?")[0])[1] or ".png")
        )
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
            self._cleanup(temp_file)
            return False, f"path traversal blocked for folder '{folder}'"

        new_path = os.path.join(dest_dir, new_name)
        if not self.config.dry_run:
            try:
                os.makedirs(dest_dir, exist_ok=True)
                self._file_op(src, new_path, self.config.action_type)
            except OSError as exc:
                self._cleanup(temp_file)
                return False, f"file op failed: {exc}"
            finally:
                # move/copy from a temp download leaves the temp behind on copy.
                if temp_file and self.config.action_type != "move":
                    self._cleanup(temp_file)
        else:
            self._cleanup(temp_file)
        return True, new_path

    def _file_op(self, src: str, dest: str, action_type: str) -> None:
        if action_type == "move":
            shutil.move(src, dest)
        elif action_type == "hardlink":
            if os.path.lexists(dest):
                os.remove(dest)
            os.link(src, dest)
        elif action_type == "symlink":
            if os.path.lexists(dest):
                os.remove(dest)
            os.symlink(src, dest)
        else:  # copy (default)
            shutil.copy(src, dest)
        self.logger.debug(f"[{action_type.upper()}] {dest} ← {src}")

    @staticmethod
    def _cleanup(path: Optional[str]) -> None:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                # Best-effort cleanup of an internally-generated temp file;
                # a missing or unremovable temp file is non-fatal.
                pass

    # ----- orchestration --------------------------------------------------

    def match_and_apply_assets(self, db: ChubDB) -> Dict[str, List[dict]]:
        """Match every configured image_type for every media item and apply it.

        Assumes poster_cache (asset rows) and media_cache are already populated
        — run() / the poster_renamerr chain hook are responsible for that.
        Returns an output dict grouped by image_type for notifications.
        """
        apply_method = self.config.apply_method

        # Resolve which configured types are actually applicable for this apply
        # method ONCE (banner is never applicable; squareart needs "direct").
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

        tmdb_client = None
        if "tmdb" in self._sources():
            tmdb_client = TMDBClient(self.full_config.tmdb, db, self.logger)
            if not tmdb_client.enabled:
                self.logger.info(
                    "TMDB source requested but no API key is configured; "
                    "falling back to local sources only."
                )
                tmdb_client = None

        total = len(all_media)
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

            for image_type in applicable:
                resolved = self._resolve_source(
                    media, db, image_type, is_collection, tmdb_client
                )
                if not resolved:
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
                if target_id is not None and self._already_applied(
                    db,
                    target_kind,
                    target_id,
                    image_type,
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
                if apply_method == "direct":
                    applied, detail, applied_libs = self._apply_direct(
                        media, image_type, file, url, is_collection
                    )
                else:
                    applied, detail = self._apply_kometa(
                        media, image_type, source, file, url
                    )

                if target_id is not None:
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
                    )

                output[image_type].append(
                    {
                        "title": media.get("title"),
                        "year": self._media_year(media),
                        "source": source,
                        "applied": applied,
                        "reason": detail,
                    }
                )
                if applied:
                    self.logger.debug(
                        f"✓ {image_type} [{source}] {media.get('title')} -> {detail}"
                    )
        return output

    def handle_output(self, output: Dict[str, List[dict]]) -> None:
        # When print_only_renames is set, list only the assets actually applied
        # (suppress the per-item lines for unchanged/failed) — the header +
        # "N/M applied" count is always shown so the run is still summarised.
        only_applied = bool(getattr(self.config, "print_only_renames", False))
        for image_type, entries in output.items():
            applied = [e for e in entries if e.get("applied")]
            self.logger.info(create_table([[image_type.capitalize()]]))
            if not entries:
                self.logger.info(f"No {image_type} assets matched\n")
                continue
            self.logger.info(
                f"{len(applied)}/{len(entries)} {image_type} assets applied"
            )
            shown = applied if only_applied else entries
            for e in shown:
                title = e.get("title") or ""
                year = e.get("year")
                display = f"{title} ({year})" if year else title
                mark = "✓" if e.get("applied") else "✗"
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

                if self.config.sync_assets:
                    self.logger.info("Running sync_gdrive")
                    try:
                        from backend.modules.sync_gdrive import SyncGDrive

                        SyncGDrive(logger=self.logger).run()
                        self.logger.info("Finished running sync_gdrive")
                    except Exception as exc:
                        self.logger.error(f"sync_gdrive failed: {exc}")

                if "local" in self._sources():
                    self._scan_local_sources(db)

                from backend.util.connector import build_instance_map

                connector = Connector(
                    db=db,
                    logger=self.logger,
                    instance_map=build_instance_map(self.config),
                )
                connector.update_arr_database()
                connector.update_collections_database()

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
