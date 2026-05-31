# modules/asset_renamerr.py

import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple

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
    """Apply additional Plex asset types — clear logo, square art, background,
    banner — to matched media.

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
        all_media: List[dict] = []
        for inst in self.config.instances:
            if isinstance(inst, str):
                media = db.media.get_by_instance(inst)
                if media:
                    all_media.extend(media)
            elif isinstance(inst, dict):
                for instance_name, params in inst.items():
                    for library_name in params.library_names or []:
                        collections = db.collection.get_by_instance_and_library(
                            instance_name, library_name
                        )
                        if collections:
                            all_media.extend(collections)
        return all_media

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

    def _apply_direct(
        self,
        media: dict,
        image_type: str,
        file: Optional[str],
        url: Optional[str],
        is_collection: bool,
    ) -> Tuple[bool, str]:
        method_name = IMAGE_TYPE_TO_PLEX_METHOD.get(image_type)
        if not method_name:
            return False, "banner is not uploadable via Plex; use Kometa apply"

        title = media.get("title")
        year = self._media_year(media)
        season_number = media.get("season_number")

        if is_collection:
            targets = [(media.get("instance_name"), [media.get("library_name")])]
        else:
            targets = self._enabled_plex_instances()

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
                    return True, f"{instance_name}/{lib}"
        return False, "not found in any configured Plex library"

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
                pass

    # ----- orchestration --------------------------------------------------

    def match_and_apply_assets(self, db: ChubDB) -> Dict[str, List[dict]]:
        """Match every configured image_type for every media item and apply it.

        Assumes poster_cache (asset rows) and media_cache are already populated
        — run() / the poster_renamerr chain hook are responsible for that.
        Returns an output dict grouped by image_type for notifications.
        """
        output: Dict[str, List[dict]] = {t: [] for t in self._active_asset_types()}
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

        apply_method = self.config.apply_method
        for media in all_media:
            if self.is_cancelled():
                break
            is_collection = media.get("asset_type") == "collection"
            target_kind = "collection" if is_collection else "media"
            target_id = media.get("id")

            for image_type in self._active_asset_types():
                # Skip (type, apply_method) combinations the platforms can't
                # apply (banner anywhere; squareart on the kometa path). Report
                # once so the user sees why, then move on — no source lookup.
                capable, why = apply_capability(image_type, apply_method)
                if not capable:
                    output[image_type].append(
                        {
                            "title": media.get("title"),
                            "year": self._media_year(media),
                            "applied": False,
                            "reason": why,
                        }
                    )
                    continue

                resolved = self._resolve_source(
                    media, db, image_type, is_collection, tmdb_client
                )
                if not resolved:
                    continue
                source, file, url = resolved

                if apply_method == "direct":
                    applied, detail = self._apply_direct(
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
                        applied_method=apply_method,
                        applied_path=detail if applied else None,
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
        for image_type in self._active_asset_types():
            entries = output.get(image_type, [])
            applied = [e for e in entries if e.get("applied")]
            self.logger.info(create_table([[image_type.capitalize()]]))
            if not entries:
                self.logger.info(f"No {image_type} assets matched\n")
                continue
            self.logger.info(
                f"{len(applied)}/{len(entries)} {image_type} assets applied"
            )
            for e in entries:
                title = e.get("title") or ""
                year = e.get("year")
                display = f"{title} ({year})" if year else title
                mark = "✓" if e.get("applied") else "✗"
                self.logger.info(f"\t{mark} {display} — {e.get('reason')}")
            self.logger.info("")

    def run(self) -> None:
        try:
            with ChubDB(logger=self.logger) as db:
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

                instance_map = {
                    "arrs": [i for i in self.config.instances if isinstance(i, str)],
                    "plex": {
                        name: (opts.library_names or [])
                        for i in self.config.instances
                        if isinstance(i, dict)
                        for name, opts in i.items()
                    },
                }
                connector = Connector(
                    db=db, logger=self.logger, instance_map=instance_map
                )
                connector.update_arr_database()
                connector.update_collections_database()

                output = self.match_and_apply_assets(db)
                self.handle_output(output)

                manager = NotificationManager(
                    self.full_config, self.logger, module_name="asset_renamerr"
                )
                manager.send_notification(output)
        except KeyboardInterrupt:
            self.logger.info("Asset Renamerr interrupted. Exiting...")
        except Exception:
            self.logger.error("\n\nAn error occurred:\n", exc_info=True)
