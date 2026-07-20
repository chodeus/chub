import hashlib
import json
import os
import shutil
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional, Tuple

from backend.util.config import load_config
from backend.util.database import ChubDB
from backend.util.helper import progress, YEAR_MATCH_TOLERANCE
from backend.util.logger import Logger
from backend.util.normalization import normalize_titles
from backend.util.plex_index import PlexMediaIndex, _coerce_year
from backend.util.plex import PlexClient


class PosterUploadError(Exception):
    """Base exception for poster upload operations"""

    pass


class PlexConnectionError(PosterUploadError):
    """Raised when Plex connection fails"""

    pass


@dataclass
class UploadResult:
    """Result of a single upload operation"""

    asset_title: str
    asset_type: str
    success: bool
    action: str  # 'updated', 'skipped', 'failed'
    reason: str
    library_name: Optional[str] = None
    match_type: Optional[str] = None
    # Carried so the caller's notification can render "Title (Year)" /
    # "Season NN" for genuinely uploaded posters without re-querying the DB.
    year: Optional[Any] = None
    season_number: Optional[Any] = None


@dataclass
class InstanceResult:
    """Result for a single Plex instance"""

    instance_name: str
    enabled: bool
    connected: bool
    uploads: List[UploadResult]
    error_message: Optional[str] = None


class PosterUploader:
    """Enhanced poster uploader with improved error handling and logging"""

    def __init__(
        self,
        db: ChubDB,
        logger: Optional[Logger] = None,
        manifest: Optional[Dict] = None,
        force: bool = False,
        refresh_plex: bool = True,
    ):
        self.full_config = load_config()
        self.config = self.full_config.poster_renamerr
        self.db = db
        self.logger = logger or Logger(self.config.log_level, "poster_uploader")
        self.logger = self.logger.get_adapter("poster_uploader")
        self.manifest = manifest or {}
        self.force = force
        # When False, reuse the existing plex_media_cache snapshot instead of
        # re-fetching the whole Plex library. Used by the interactive manual
        # "apply this one poster now" path so a click doesn't trigger a full
        # library sync; the cached snapshot from the last run is good enough,
        # and if it can't locate the item the match is still saved + locked and
        # applies on the next run.
        self.refresh_plex = refresh_plex

        # Cache for connections and indexes
        self._plex_clients = {}
        self._media_indexes = {}
        # Live library-type map per instance, for the webhook/manual LIVE
        # fallback when an item isn't in the cached snapshot. Filled on first use.
        self._live_lib_types: Dict[str, Dict[str, Optional[str]]] = {}

        # ID-matched uploads whose on-disk folder year (from *arr) disagrees
        # with the Plex item's year by more than the normal lag. Accumulated
        # across instances within a run and surfaced in the final summary.
        self._year_discrepancies: List[Dict[str, Any]] = []

    def run(self) -> Dict[str, Any]:
        """
        Main entry point for poster uploading with improved error handling.

        Returns:
            Dict with comprehensive results and minimal verbose logging
        """
        try:
            # Parse instance configuration
            enabled_instances = self._get_enabled_instances()

            if not enabled_instances:
                self.logger.info("No Plex instances enabled for poster upload")
                return self._create_result(
                    success=False,
                    message="No Plex instances enabled for poster upload",
                    error_code="NO_ENABLED_INSTANCES",
                )

            # Update Plex database once for all instances (skippable for the
            # interactive single-item apply, which reuses the cached snapshot).
            if self.refresh_plex:
                self._update_plex_database(enabled_instances)

            # Process each enabled instance
            instance_results = []
            for instance_name, library_names in enabled_instances.items():
                result = self._process_instance(instance_name, library_names)
                instance_results.append(result)

            # Generate final result
            return self._compile_final_result(instance_results)

        except Exception as e:
            self.logger.error(f"Poster upload failed: {e}", exc_info=True)
            return self._create_result(
                success=False,
                message=f"Poster upload failed: {e}",
                error_code="UPLOAD_EXCEPTION",
            )
        finally:
            self._cleanup_connections()

    def _get_enabled_instances(self) -> Dict[str, List[str]]:
        """Get enabled Plex instances with their library names"""
        enabled_instances = {}
        disabled_instances = []

        for scope in self.config.plex_scope or []:
            if scope.add_posters:
                enabled_instances[scope.instance] = list(scope.library_names or [])
            else:
                disabled_instances.append(scope.instance)

        # Log disabled instances once, concisely
        if disabled_instances:
            self.logger.debug(f"Disabled instances: {', '.join(disabled_instances)}")

        return enabled_instances

    def _update_plex_database(self, enabled_instances: Dict[str, List[str]]):
        """Refresh the Plex snapshot for enabled instances.

        Routed through the shared TTL guard (general.plex_cache_ttl_seconds)
        so a chained run that just walked Plex — e.g. poster_renamerr →
        upload — reuses the fresh snapshot instead of re-walking the whole
        library. A lazy per-item live lookup at apply time still covers items
        added in the gap.
        """
        from backend.util.plex_refresh import refresh_plex_cache_if_stale

        try:
            refresh_plex_cache_if_stale(
                self.db, self.full_config, self.logger, enabled_instances
            )
        except Exception as e:
            raise PosterUploadError(f"Failed to update Plex database: {e}")

    def _process_instance(
        self, instance_name: str, library_names: List[str]
    ) -> InstanceResult:
        """Process a single Plex instance"""
        try:
            # Get Plex configuration
            plex_config = self.full_config.instances.plex.get(instance_name)
            if not plex_config:
                return InstanceResult(
                    instance_name=instance_name,
                    enabled=True,
                    connected=False,
                    uploads=[],
                    error_message=f"Configuration not found for instance '{instance_name}'",
                )

            # Connect to Plex
            with self._get_plex_client(
                instance_name, plex_config.url, plex_config.api
            ) as plex_client:
                if not plex_client.is_connected():
                    return InstanceResult(
                        instance_name=instance_name,
                        enabled=True,
                        connected=False,
                        uploads=[],
                        error_message=f"Failed to connect to Plex instance '{instance_name}'",
                    )

                # Build media indexes
                indexes = self._get_media_indexes(instance_name)
                if not indexes:
                    return InstanceResult(
                        instance_name=instance_name,
                        enabled=True,
                        connected=True,
                        uploads=[],
                        error_message=f"No media cache found for instance '{instance_name}'",
                    )

                # Process assets
                assets = self._get_assets_from_manifest()
                upload_results = self._sync_all_assets(
                    assets, plex_client, indexes, self.config.dry_run
                )

                return InstanceResult(
                    instance_name=instance_name,
                    enabled=True,
                    connected=True,
                    uploads=upload_results,
                )

        except Exception as e:
            self.logger.error(f"Error processing instance '{instance_name}': {e}")
            return InstanceResult(
                instance_name=instance_name,
                enabled=True,
                connected=False,
                uploads=[],
                error_message=str(e),
            )

    @contextmanager
    def _get_plex_client(
        self, instance_name: str, url: str, api: str
    ) -> Generator[PlexClient, None, None]:
        """Get or create Plex client with connection caching"""
        if instance_name not in self._plex_clients:
            client = PlexClient(url, api, self.logger)
            if not client.is_connected():
                raise PlexConnectionError(
                    f"Failed to connect to Plex instance '{instance_name}'"
                )
            self._plex_clients[instance_name] = client

        yield self._plex_clients[instance_name]

    def _get_media_indexes(
        self, instance_name: str
    ) -> Optional[Tuple[Dict, Dict, Dict, Dict, Dict, Dict]]:
        """Get or build media indexes for an instance"""
        if instance_name in self._media_indexes:
            return self._media_indexes[instance_name]

        plex_media_cache = self.db.plex.get_by_instance(instance_name)
        if not plex_media_cache:
            return None

        indexes = self._build_indexes(plex_media_cache)
        self._media_indexes[instance_name] = indexes
        return indexes

    def _get_assets_from_manifest(self) -> List[Dict]:
        """Get assets from manifest with error handling"""
        assets = []

        # Process media assets
        for asset_id in self.manifest.get("media_cache", []):
            try:
                asset = self.db.media.get_by_id(asset_id)
                if asset:
                    assets.append(asset)
                else:
                    self.logger.warning(f"Media asset ID {asset_id} not found")
            except Exception as e:
                self.logger.error(f"Error retrieving media asset {asset_id}: {e}")

        # Process collection assets
        for asset_id in self.manifest.get("collections_cache", []):
            try:
                asset = self.db.collection.get_by_id(asset_id)
                if asset:
                    assets.append(asset)
                else:
                    self.logger.warning(f"Collection asset ID {asset_id} not found")
            except Exception as e:
                self.logger.error(f"Error retrieving collection asset {asset_id}: {e}")

        return assets

    def _sync_all_assets(
        self,
        assets: List[Dict],
        plex_client: PlexClient,
        indexes: Tuple[Dict, Dict, Dict, Dict, Dict, Dict],
        dry_run: bool,
    ) -> List[UploadResult]:
        """Sync all assets with consolidated progress reporting"""
        (
            movie_index,
            show_index,
            season_index,
            collection_index,
            artist_index,
            album_index,
        ) = indexes
        all_results = []

        # Group assets by type for efficient processing
        movies = [
            a
            for a in assets
            if a.get("asset_type") == "movie" and a.get("matched") == 1
        ]
        series = [
            a
            for a in assets
            if a.get("asset_type") == "show"
            and a.get("matched") == 1
            and a.get("season_number") is None
        ]
        seasons = [
            a
            for a in assets
            if a.get("asset_type") == "show"
            and a.get("matched") == 1
            and a.get("season_number") is not None
        ]
        collections = [
            a
            for a in assets
            if a.get("asset_type") == "collection" and a.get("matched") == 1
        ]
        artists = [
            a
            for a in assets
            if a.get("asset_type") == "artist" and a.get("matched") == 1
        ]
        albums = [
            a
            for a in assets
            if a.get("asset_type") == "album" and a.get("matched") == 1
        ]

        # Process each type with progress bars
        if movies:
            all_results.extend(
                self._sync_movies(movies, plex_client, movie_index, dry_run)
            )

        if series:
            all_results.extend(
                self._sync_series(series, plex_client, show_index, dry_run)
            )

        if seasons:
            all_results.extend(
                self._sync_seasons(seasons, plex_client, season_index, dry_run)
            )

        if collections:
            all_results.extend(
                self._sync_collections(
                    collections, plex_client, collection_index, dry_run
                )
            )

        if artists:
            all_results.extend(
                self._sync_artists(artists, plex_client, artist_index, dry_run)
            )

        if albums:
            all_results.extend(
                self._sync_albums(albums, plex_client, album_index, dry_run)
            )

        return all_results

    def _sync_movies(
        self,
        movies: List[Dict],
        plex_client: PlexClient,
        movie_index: Dict,
        dry_run: bool,
    ) -> List[UploadResult]:
        """Sync movie posters"""
        results = []

        with progress(
            movies,
            desc="Syncing movie posters",
            total=len(movies),
            unit="movie",
            logger=self.logger,
        ) as bar:
            for movie in bar:
                try:
                    result = self._sync_single_asset(
                        asset=movie,
                        plex_client=plex_client,
                        index=movie_index,
                        priority_keys=["tmdb", "imdb", "title"],
                        dry_run=dry_run,
                    )
                    results.append(result)
                except Exception as e:
                    self.logger.warning(
                        f"Error syncing movie '{movie.get('title')}': {e}"
                    )
                    results.append(
                        UploadResult(
                            asset_title=movie.get("title", "Unknown"),
                            asset_type="movie",
                            success=False,
                            action="failed",
                            reason=f"Processing error: {e}",
                        )
                    )

        return results

    def _sync_series(
        self,
        series: List[Dict],
        plex_client: PlexClient,
        show_index: Dict,
        dry_run: bool,
    ) -> List[UploadResult]:
        """Sync TV series posters"""
        results = []

        with progress(
            series,
            desc="Syncing series posters",
            total=len(series),
            unit="series",
            logger=self.logger,
        ) as bar:
            for show in bar:
                try:
                    result = self._sync_single_asset(
                        asset=show,
                        plex_client=plex_client,
                        index=show_index,
                        priority_keys=["tvdb", "tmdb", "imdb", "title"],
                        dry_run=dry_run,
                    )
                    results.append(result)
                except Exception as e:
                    self.logger.warning(
                        f"Error syncing series '{show.get('title')}': {e}"
                    )
                    results.append(
                        UploadResult(
                            asset_title=show.get("title", "Unknown"),
                            asset_type="series",
                            success=False,
                            action="failed",
                            reason=f"Processing error: {e}",
                        )
                    )

        return results

    def _sync_seasons(
        self,
        seasons: List[Dict],
        plex_client: PlexClient,
        season_index: Dict,
        dry_run: bool,
    ) -> List[UploadResult]:
        """Sync season posters"""
        results = []

        with progress(
            seasons,
            desc="Syncing season posters",
            total=len(seasons),
            unit="season",
            logger=self.logger,
        ) as bar:
            for season in bar:
                try:
                    # Modify search key for season matching
                    season_num = season.get("season_number")
                    norm_title = normalize_titles(season.get("title", ""))

                    result = self._sync_single_asset(
                        asset=season,
                        plex_client=plex_client,
                        index=season_index,
                        priority_keys=["tvdb", "tmdb", "imdb", "title"],
                        dry_run=dry_run,
                        season_number=season_num,
                        title_override=f"{norm_title}:S{season_num}",
                    )
                    results.append(result)
                except Exception as e:
                    season_num = season.get("season_number", "?")
                    self.logger.warning(
                        f"Error syncing season {season_num} of '{season.get('title')}': {e}"
                    )
                    results.append(
                        UploadResult(
                            asset_title=f"{season.get('title', 'Unknown')} S{season_num}",
                            asset_type="season",
                            success=False,
                            action="failed",
                            reason=f"Processing error: {e}",
                        )
                    )

        return results

    def _sync_collections(
        self,
        collections: List[Dict],
        plex_client: PlexClient,
        collection_index: Dict,
        dry_run: bool,
    ) -> List[UploadResult]:
        """Sync collection posters"""
        results = []

        with progress(
            collections,
            desc="Syncing collection posters",
            total=len(collections),
            unit="collection",
            logger=self.logger,
        ) as bar:
            for collection in bar:
                try:
                    result = self._sync_single_asset(
                        asset=collection,
                        plex_client=plex_client,
                        index=collection_index,
                        priority_keys=["title"],
                        dry_run=dry_run,
                        is_collection=True,
                    )
                    results.append(result)
                except Exception as e:
                    self.logger.warning(
                        f"Error syncing collection '{collection.get('title')}': {e}"
                    )
                    results.append(
                        UploadResult(
                            asset_title=collection.get("title", "Unknown"),
                            asset_type="collection",
                            success=False,
                            action="failed",
                            reason=f"Processing error: {e}",
                        )
                    )

        return results

    def _sync_artists(
        self,
        artists: List[Dict],
        plex_client: PlexClient,
        artist_index: Dict,
        dry_run: bool,
    ) -> List[UploadResult]:
        """Sync artist posters (music). MusicBrainz id first, then title."""
        results = []

        with progress(
            artists,
            desc="Syncing artist posters",
            total=len(artists),
            unit="artist",
            logger=self.logger,
        ) as bar:
            for artist in bar:
                try:
                    result = self._sync_single_asset(
                        asset=artist,
                        plex_client=plex_client,
                        index=artist_index,
                        priority_keys=["mbid", "title"],
                        dry_run=dry_run,
                    )
                    results.append(result)
                except Exception as e:
                    self.logger.warning(
                        f"Error syncing artist '{artist.get('title')}': {e}"
                    )
                    results.append(
                        UploadResult(
                            asset_title=artist.get("title", "Unknown"),
                            asset_type="artist",
                            success=False,
                            action="failed",
                            reason=f"Processing error: {e}",
                        )
                    )

        return results

    def _sync_albums(
        self,
        albums: List[Dict],
        plex_client: PlexClient,
        album_index: Dict,
        dry_run: bool,
    ) -> List[UploadResult]:
        """Sync album covers (music). MBID first, else parent-scoped title.

        Album covers are uploaded to the same "poster" slot as everything else
        (upload_poster targets by ratingKey, type-agnostic). The title key is
        scoped under the parent artist ("{artist}::{album}") so identically
        named albums across artists don't collide.
        """
        results = []

        with progress(
            albums,
            desc="Syncing album covers",
            total=len(albums),
            unit="album",
            logger=self.logger,
        ) as bar:
            for album in bar:
                try:
                    album_norm = normalize_titles(album.get("title") or "")
                    parent_norm = normalize_titles(album.get("parent_title") or "")
                    scoped = (
                        f"{parent_norm}::{album_norm}" if parent_norm else album_norm
                    )
                    result = self._sync_single_asset(
                        asset=album,
                        plex_client=plex_client,
                        index=album_index,
                        priority_keys=["mbid", "title"],
                        dry_run=dry_run,
                        title_override=scoped,
                    )
                    results.append(result)
                except Exception as e:
                    self.logger.warning(
                        f"Error syncing album '{album.get('title')}': {e}"
                    )
                    results.append(
                        UploadResult(
                            asset_title=album.get("title", "Unknown"),
                            asset_type="album",
                            success=False,
                            action="failed",
                            reason=f"Processing error: {e}",
                        )
                    )

        return results

    def _sync_single_asset(
        self,
        asset: Dict,
        plex_client: PlexClient,
        index: Dict,
        priority_keys: List[str],
        dry_run: bool,
        season_number: Optional[int] = None,
        title_override: Optional[str] = None,
        is_collection: bool = False,
    ) -> UploadResult:
        """Sync a single asset with comprehensive error handling"""

        asset_title = asset.get("title", "Unknown")
        asset_type = asset.get("asset_type", "unknown")
        poster_path = asset.get("renamed_file")

        try:
            # Find matching Plex entry
            search_values = {
                "tmdb": str(asset.get("tmdb_id")) if asset.get("tmdb_id") else None,
                "imdb": asset.get("imdb_id"),
                "tvdb": str(asset.get("tvdb_id")) if asset.get("tvdb_id") else None,
                "mbid": (
                    str(asset.get("musicbrainz_id")).lower()
                    if asset.get("musicbrainz_id")
                    else None
                ),
                "title": title_override or normalize_titles(asset_title),
                # Year-disambiguates title-only matches so a same-title/different-
                # year collision can't upload the wrong release (see
                # PlexMediaIndex._match). Inert for guid hits.
                "year": asset.get("year"),
            }

            # Season entries are indexed with a ":S{n}" suffix on EVERY key
            # (tmdb:123:S2, title:show:S2). title_override already carries it,
            # but the guid values were left bare, so the guid priority keys
            # never matched and season posters silently fell back to title-only
            # matching (wrong-show collisions). Suffix the guid values too.
            if season_number is not None:
                for _k in ("tmdb", "imdb", "tvdb"):
                    if search_values.get(_k):
                        search_values[_k] = f"{search_values[_k]}:S{season_number}"

            matched_entries, match_type = self.match_asset(
                index, priority_keys, search_values
            )

            if not matched_entries:
                # LIVE per-item fallback. The cached plex_media_cache snapshot
                # doesn't have this item — the common case for a webhook fired on
                # a BRAND-NEW import that Plex just scanned but the TTL-guarded
                # cache hasn't picked up. Resolve against LIVE Plex instead:
                # target every library of the matching type and let
                # upload_poster's live title+year search find it (no-op in the
                # libraries that don't hold it). Keeps the real-time path off the
                # stale snapshot; mirrors asset_renamerr's live fallback.
                matched_entries = self._live_fallback_targets(
                    plex_client, asset, asset_type, asset_title
                )
                if matched_entries:
                    match_type = "LIVE"

            if not matched_entries:
                return UploadResult(
                    asset_title=asset_title,
                    asset_type=asset_type,
                    success=False,
                    action="failed",
                    reason="No matching Plex entry found",
                )

            # The same title can be in more than one enabled library on this
            # instance (e.g. an HD and a 4K library) — every library gets the
            # poster. Within a library: ratingKey resolution fetches exactly
            # ONE item, so distinct un-merged copies (distinct plex_ids) in the
            # SAME library each need their own upload call. Only entries
            # WITHOUT a plex_id resolve via title search, which covers every
            # copy in the library — those dedupe per library.
            targets: List[Dict] = []
            seen = set()
            for entry in matched_entries:
                lib = entry.get("library_name")
                pid = entry.get("plex_id")
                key = (lib, pid) if pid else lib
                if key in seen:
                    continue
                seen.add(key)
                targets.append(entry)
            lib_label = ", ".join(
                dict.fromkeys(str(t.get("library_name")) for t in targets)
            )

            # Per-library skip: "unchanged" is judged per (file × library), not
            # per file. recorded_libs is the set of libraries this exact hash has
            # already reached; missing_libs is what's still owed. A title that
            # gains a new library copy (e.g. a fresh 4K library) is backfilled on
            # the next run even though the poster bytes never changed — no forced
            # run required.
            target_libs = {str(t.get("library_name")) for t in targets}
            recorded_libs = self._parse_uploaded_libraries(
                asset.get("uploaded_libraries")
            )
            missing_libs = target_libs - recorded_libs

            # mtime fast-path: a single stat() tells us whether the file changed
            # since the last successful upload. When it matches, skip the sha256
            # read entirely — reading every poster file on each run was a major
            # source of page-cache churn on large libraries.
            current_mtime: Optional[float] = None
            try:
                current_mtime = os.stat(poster_path).st_mtime
            except OSError:
                current_mtime = None

            record_mtime = asset.get("file_mtime")
            record_hash = asset.get("file_hash")
            mtime_unchanged = (
                not self.force
                and record_mtime is not None
                and current_mtime is not None
                and float(record_mtime) == float(current_mtime)
            )

            # sha256 of the RAW source poster (original_file, unlike file_hash
            # which is the staged/bordered output). Persisted alongside the
            # upload record so the plex apply path can skip re-staging a poster
            # whose source is unchanged. Computed lazily; never in dry-run.
            source_path = asset.get("original_file")
            source_file_hash = (
                self._compute_file_hash(source_path)
                if source_path and not dry_run
                else None
            )

            # reset_record=True means the poster bytes are new (or forced): push
            # to EVERY matched library and reset the covered-library record.
            # reset_record=False means bytes are unchanged: only backfill the
            # libraries still missing it, growing the existing record.
            reset_record: bool
            if mtime_unchanged:
                if not missing_libs:
                    # Unchanged file, every library already has it — true skip.
                    return UploadResult(
                        asset_title=asset_title,
                        asset_type=asset_type,
                        success=True,
                        action="skipped",
                        reason="File unchanged (mtime)",
                        library_name=lib_label,
                        match_type=match_type,
                    )
                # Unchanged bytes but some libraries are missing it — backfill
                # without re-reading the file.
                current_file_hash = record_hash
                upload_targets = [
                    t for t in targets if str(t.get("library_name")) in missing_libs
                ]
                reset_record = False
            else:
                # mtime missing/changed — fall back to the sha256 comparison.
                current_file_hash = self._compute_file_hash(poster_path, dry_run)

                if not current_file_hash:
                    return UploadResult(
                        asset_title=asset_title,
                        asset_type=asset_type,
                        success=False,
                        action="failed",
                        reason="Could not read poster file",
                    )

                if current_file_hash == record_hash and not self.force:
                    if not missing_libs:
                        # Same bytes, every library covered: refresh the mtime
                        # fast-path key (preserving the record) and skip.
                        # Never persist in dry-run — a pretend run must not
                        # touch the hash/mtime record (unreachable today since
                        # the dry-run hash can't equal a real record hash, but
                        # keep the guard structural).
                        if not dry_run:
                            self._update_asset_database(
                                asset,
                                current_file_hash,
                                current_mtime,
                                uploaded_libraries=json.dumps(sorted(recorded_libs)),
                                source_file_hash=source_file_hash,
                            )
                        return UploadResult(
                            asset_title=asset_title,
                            asset_type=asset_type,
                            success=True,
                            action="skipped",
                            reason="File unchanged",
                            library_name=lib_label,
                            match_type=match_type,
                        )
                    # Same bytes, some libraries missing — backfill those.
                    upload_targets = [
                        t for t in targets if str(t.get("library_name")) in missing_libs
                    ]
                    reset_record = False
                else:
                    # New bytes (or forced): (re)push to every matched library.
                    upload_targets = targets
                    reset_record = True

            # Upload the poster to the resolved target libraries.
            uploaded_libs: List[str] = []
            for entry in upload_targets:
                ok = plex_client.upload_poster(
                    library_name=entry["library_name"],
                    item_title=entry["title"],
                    poster_path=poster_path,
                    year=entry.get("year"),
                    is_collection=is_collection,
                    season_number=season_number,
                    dry_run=dry_run,
                    plex_id=entry.get("plex_id"),
                )
                if not ok:
                    continue
                uploaded_libs.append(str(entry.get("library_name")))
                # Artist art reversion hedge: Plex's music agent re-derives an
                # artist's image from album art on refresh, which would revert a
                # custom poster. When opted in, lock thumb/art after the upload.
                # Artist-only (albums are sticky); Plex-metadata only, no files.
                if asset_type == "artist" and getattr(
                    self.config, "music_lock_artist_art", False
                ):
                    plex_client.lock_field(
                        library_name=entry["library_name"],
                        item_title=entry["title"],
                        fields=["thumb", "art"],
                        year=entry.get("year"),
                        dry_run=dry_run,
                        plex_id=entry.get("plex_id"),
                    )
                # Optional LMA disk sidecars (image-only, refresh-proof).
                if asset_type in ("artist", "album") and getattr(
                    self.config, "music_lma_sidecars", False
                ):
                    self._write_music_sidecar(asset_type, poster_path, entry, dry_run)
                # Remove overlay label if present (per-library item).
                if self._has_overlay(entry):
                    plex_client.remove_label(entry, "Overlay", dry_run)
                # Be gentle on Plex: optional inter-upload delay between each
                # real upload (never after a skip, never in dry-run).
                if not dry_run:
                    self._throttle()

            if uploaded_libs:
                # Never persist in dry-run — a pretend upload must not write the
                # hash/mtime or covered-library set, or a later real run would
                # skip the asset as already done.
                if not dry_run:
                    # Grow (backfill) or reset (new bytes) the covered set.
                    base = set() if reset_record else recorded_libs
                    covered = base | set(uploaded_libs)
                    self._update_asset_database(
                        asset,
                        current_file_hash,
                        current_mtime,
                        uploaded_libraries=json.dumps(sorted(covered)),
                        source_file_hash=source_file_hash,
                    )

                self._note_year_discrepancy(asset, matched_entries, match_type)

                return UploadResult(
                    asset_title=asset_title,
                    asset_type=asset_type,
                    success=True,
                    action="updated",
                    reason="Successfully uploaded",
                    library_name=", ".join(dict.fromkeys(uploaded_libs)),
                    match_type=match_type,
                    year=asset.get("year"),
                    season_number=asset.get("season_number"),
                )
            else:
                return UploadResult(
                    asset_title=asset_title,
                    asset_type=asset_type,
                    success=False,
                    action="failed",
                    reason=(
                        "Season not found in Plex yet"
                        if season_number is not None
                        else "Upload to Plex failed"
                    ),
                    library_name=lib_label,
                    match_type=match_type,
                )

        except Exception as e:
            self.logger.warning(f"Error processing asset '{asset_title}': {e}")
            return UploadResult(
                asset_title=asset_title,
                asset_type=asset_type,
                success=False,
                action="failed",
                reason=f"Processing error: {e}",
            )

    # Plex section type(s) an asset of each type can live in — targets the LIVE
    # fallback at only the right kind of library.
    _PLEX_TYPE_FOR_ASSET = {
        "movie": ("movie",),
        "show": ("show",),
        "artist": ("artist",),
        "album": ("artist",),
        "collection": ("movie", "show"),
    }

    def _live_fallback_targets(
        self,
        plex_client: PlexClient,
        asset: Dict,
        asset_type: str,
        asset_title: str,
    ) -> List[Dict]:
        """Resolve an item against LIVE Plex when the cached index misses.

        Returns one synthetic target per instance library of the matching type,
        each carrying the raw *arr title/year and NO plex_id — so upload_poster
        does a live title+year search per library, pushing to the one(s) that
        hold the item and no-opping the rest. This is the instant path a webhook
        needs: a just-scanned import absent from the TTL-guarded plex_media_cache
        is still found and pushed, with zero reliance on the snapshot."""
        plex_types = self._PLEX_TYPE_FOR_ASSET.get(asset_type)
        if not plex_types or not asset_title:
            return []
        cache_key = str(asset.get("instance_name") or getattr(plex_client, "url", ""))
        libs = self._live_libraries_of_types(plex_client, cache_key, plex_types)
        year = asset.get("year")
        return [
            {"library_name": lib, "title": asset_title, "year": year, "plex_id": None}
            for lib in libs
        ]

    def _live_libraries_of_types(
        self, plex_client: PlexClient, cache_key: str, plex_types: Tuple[str, ...]
    ) -> List[str]:
        """Instance library names whose Plex section type is in ``plex_types``.
        The (library → type) map is fetched live once per instance and reused for
        the rest of the run."""
        type_map = self._live_lib_types.get(cache_key)
        if type_map is None:
            type_map = {}
            for name in plex_client.get_libraries() or []:
                try:
                    type_map[name] = plex_client.section_type(name)
                except Exception:
                    type_map[name] = None
            self._live_lib_types[cache_key] = type_map
        return [name for name, typ in type_map.items() if typ in plex_types]

    def _note_year_discrepancy(
        self,
        asset: Dict,
        matched_entries: List[Dict],
        match_type: Optional[str],
    ) -> None:
        """Warn when a poster was matched to Plex by a unique ID (tmdb/tvdb/imdb)
        but the on-disk folder year (from Radarr/Sonarr) disagrees with the Plex
        item's year by more than the normal ±tolerance lag.

        The upload itself is correct — a guid match is authoritative (see
        ``PlexMediaIndex._match``), so we trust the ID over the folder year. But
        a large year gap signals stale metadata on one side (a wrong ID entered,
        or an un-refreshed Plex item) that the user may want to reconcile. A
        TITLE match is already year-disambiguated upstream and can never reach
        here with a mismatch, so only guid matches are inspected. Recorded once
        per asset and only on an actual upload, so unchanged files don't re-warn
        every run."""
        if not match_type or match_type.upper() in ("TITLE", "LIVE"):
            return
        folder_year = _coerce_year(asset.get("year"))
        if folder_year is None:
            return
        for entry in matched_entries:
            plex_year = _coerce_year(entry.get("year"))
            if (
                plex_year is None
                or abs(plex_year - folder_year) <= YEAR_MATCH_TOLERANCE
            ):
                continue
            title = str(asset.get("title") or "Unknown")
            descriptor = {
                "title": title,
                "folder_year": folder_year,
                "plex_year": plex_year,
                "match_type": match_type,
            }
            if descriptor not in self._year_discrepancies:
                self._year_discrepancies.append(descriptor)
            self.logger.warning(
                f"Year discrepancy: matched '{title}' by {match_type} and uploaded, "
                f"but Plex year {plex_year} differs from the Radarr/Sonarr folder "
                f"year {folder_year} — uploaded by ID, review for stale metadata"
            )
            return

    def _throttle(self) -> None:
        """Sleep the configured inter-upload delay (poster_renamerr.upload_delay_ms)."""
        delay_ms = int(getattr(self.config, "upload_delay_ms", 0) or 0)
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

    def _update_asset_database(
        self,
        asset: Dict,
        file_hash: str,
        file_mtime: Optional[float] = None,
        uploaded_libraries: Optional[str] = None,
        source_file_hash: Optional[str] = None,
    ):
        """Persist the uploaded poster's hash (and mtime fast-path key), plus
        the JSON list of libraries this hash has now reached (per-library skip)
        and the raw-source hash (for the plex "skip unchanged" fast-path)."""
        try:
            if asset.get("asset_type") == "collection":
                self.db.collection.update(
                    title=asset.get("title"),
                    year=asset.get("year"),
                    library_name=asset.get("library_name"),
                    instance_name=asset.get("instance_name"),
                    matched_value=None,
                    original_file=None,
                    renamed_file=None,
                    file_hash=file_hash,
                    file_mtime=file_mtime,
                    uploaded_libraries=uploaded_libraries,
                    source_file_hash=source_file_hash,
                )
            else:
                self.db.media.update(
                    asset_type=asset.get("asset_type"),
                    title=asset.get("title"),
                    year=asset.get("year"),
                    instance_name=asset.get("instance_name"),
                    matched_value=None,
                    season_number=asset.get("season_number"),
                    original_file=None,
                    renamed_file=None,
                    file_hash=file_hash,
                    file_mtime=file_mtime,
                    uploaded_libraries=uploaded_libraries,
                    source_file_hash=source_file_hash,
                )
        except Exception as e:
            self.logger.error(
                f"Failed to update database for asset '{asset.get('title')}': {e}"
            )

    def _compile_final_result(
        self, instance_results: List[InstanceResult]
    ) -> Dict[str, Any]:
        """Compile final result with clean summary logging"""
        total_updated = 0
        total_skipped = 0
        total_failed = 0
        successful_instances = 0
        # Per-poster record of every GENUINE upload this run (action ==
        # 'updated'), across instances. The scheduled plex path notifies from
        # this — never from the staged/rename output — so a skipped or failed
        # poster can't masquerade as an upload in Discord/Notifiarr.
        uploaded_records: List[Dict[str, Any]] = []

        for instance_result in instance_results:
            if instance_result.connected and not instance_result.error_message:
                successful_instances += 1

                updated_results = [
                    r for r in instance_result.uploads if r.action == "updated"
                ]
                updated = len(updated_results)
                skipped = len(
                    [r for r in instance_result.uploads if r.action == "skipped"]
                )
                failed = len(
                    [r for r in instance_result.uploads if r.action == "failed"]
                )
                uploaded_records.extend(
                    {
                        "title": r.asset_title,
                        "year": r.year,
                        "asset_type": r.asset_type,
                        "season_number": r.season_number,
                        "library_name": r.library_name,
                        "instance": instance_result.instance_name,
                    }
                    for r in updated_results
                )

                total_updated += updated
                total_skipped += skipped
                total_failed += failed

                # Log instance summary concisely
                self.logger.info(
                    f"{instance_result.instance_name}: {updated} updated, {skipped} skipped, {failed} failed"
                )

        # Log overall summary
        self.logger.info(
            f"Upload summary: {total_updated} updated, {total_skipped} skipped, {total_failed} failed"
        )

        # Surface ID-matched uploads whose *arr folder year disagrees with Plex.
        # These uploaded correctly (the ID is authoritative); the warning just
        # flags stale metadata worth reconciling.
        if self._year_discrepancies:
            self.logger.warning(
                f"{len(self._year_discrepancies)} ID-matched upload(s) had a year "
                "mismatch between the Radarr/Sonarr folder and Plex (uploaded "
                "correctly by ID — review for stale metadata):\n"
                + "\n".join(
                    f"  • {d['title']}: folder {d['folder_year']} vs Plex "
                    f"{d['plex_year']} ({d['match_type']})"
                    for d in self._year_discrepancies
                )
            )

        # Log detailed failures only if there are failures
        if total_failed > 0:
            failed_details = []
            for instance_result in instance_results:
                for upload in instance_result.uploads:
                    if upload.action == "failed":
                        failed_details.append(f"{upload.asset_title}: {upload.reason}")
            if failed_details:
                self.logger.info(
                    "Failed uploads:\n"
                    + "\n".join(f"  • {detail}" for detail in failed_details)
                )

        # Determine overall success
        overall_success = total_failed == 0 and successful_instances > 0

        return self._create_result(
            success=overall_success,
            message=f"Upload complete: {total_updated} updated, {total_skipped} skipped, {total_failed} failed",
            error_code=None if overall_success else "UPLOAD_FAILURES",
            payload={
                "updated": total_updated,
                "skipped": total_skipped,
                "failed": total_failed,
                "uploaded": uploaded_records,
                "year_discrepancies": list(self._year_discrepancies),
                "instances_processed": successful_instances,
                "instance_results": [
                    {
                        "instance": r.instance_name,
                        "enabled": r.enabled,
                        "connected": r.connected,
                        "uploads": len(r.uploads),
                        "error": r.error_message,
                    }
                    for r in instance_results
                ],
            },
        )

    def _create_result(
        self,
        success: bool,
        message: str,
        error_code: Optional[str],
        payload: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Create standardized result dictionary"""
        return {
            "success": success,
            "message": message,
            "error_code": error_code,
            "payload": {"manifest": self.manifest, **(payload or {})},
        }

    def _cleanup_connections(self):
        """Clean up cached connections"""
        self._plex_clients.clear()
        self._media_indexes.clear()

    # Static/utility methods (keeping existing implementations but with improvements)
    @staticmethod
    def _build_indexes(
        media_cache: List[Dict],
    ) -> Tuple[Dict, Dict, Dict, Dict, Dict, Dict]:
        """Build the type-separated lookup indexes for fast asset matching.

        Thin wrapper over the shared :class:`PlexMediaIndex` (single source of
        truth for the guid-first keying, shared with asset_renamerr's plex
        apply path). Returns the six raw dicts so the existing _sync_* call
        sites stay unchanged; each key maps to a *list* of entries (the same
        title can live in more than one enabled library on a server, e.g. a
        "Movies" and a "Movies 4K" library — every copy must get the poster).
        """
        idx = PlexMediaIndex(media_cache)
        return (
            idx.movies,
            idx.shows,
            idx.seasons,
            idx.collections,
            idx.artists,
            idx.albums,
        )

    @staticmethod
    def match_asset(
        index: Dict, priority_keys: List[str], values: Dict
    ) -> Tuple[List[Dict], Optional[str]]:
        """Match asset using index with priority keys.

        Returns the *list* of cache entries (one per Plex library that holds
        the item) for the highest-priority key that hits, plus that key's name.
        Returns ([], None) when nothing matches. Delegates to the shared
        PlexMediaIndex matcher so poster and asset paths key identically.
        """
        return PlexMediaIndex._match(index, priority_keys, values)

    def _write_music_sidecar(
        self, asset_type: str, poster_path: str, entry: Dict, dry_run: bool
    ) -> None:
        """Copy a poster/cover into the Plex music library folder as a Local
        Media Assets sidecar — ``cover.jpg`` for albums, ``artist-poster.jpg``
        for artists. Writes an image file ONLY (never audio), into a folder that
        must already exist inside the Plex library. Non-fatal on any error.
        """
        try:
            paths = entry.get("file_paths")
            if isinstance(paths, str):
                paths = json.loads(paths or "[]")
            folders = [p for p in (paths or []) if p and os.path.isdir(p)]
            if not folders:
                return
            name = "cover.jpg" if asset_type == "album" else "artist-poster.jpg"
            for folder in folders:
                dest = os.path.join(folder, name)
                if dry_run:
                    self.logger.debug(f"[DRY RUN] Would write music sidecar {dest}")
                    continue
                # Copy to a temp name then os.replace so a crash mid-copy can't
                # truncate an existing user cover (mirrors process_file).
                tmp = f"{dest}.chub-tmp-{os.getpid()}"
                try:
                    shutil.copyfile(poster_path, tmp)
                    os.replace(tmp, dest)
                except OSError:
                    with suppress(OSError):
                        os.remove(tmp)
                    raise
                self.logger.debug(f"[MUSIC_SIDECAR] {dest}")
        except Exception as e:
            self.logger.warning(
                f"Music sidecar write failed for '{entry.get('title')}': {e}"
            )

    @staticmethod
    def _compute_file_hash(poster_path: str, dry_run: bool = False) -> Optional[str]:
        """Compute file hash with proper error handling"""
        if dry_run:
            return "dry_run_hash"

        try:
            with open(poster_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except (FileNotFoundError, PermissionError, OSError):
            return None

    @staticmethod
    def _parse_uploaded_libraries(value: Any) -> set:
        """Parse the stored JSON list of libraries a poster's hash has reached.

        Tolerates None / empty / malformed values (returns an empty set), so a
        legacy row with no record is simply treated as "no library covered yet".
        """
        if not value:
            return set()
        if isinstance(value, (list, set, tuple)):
            return {str(v) for v in value}
        try:
            parsed = json.loads(value)
            return {str(v) for v in parsed} if isinstance(parsed, list) else set()
        except (json.JSONDecodeError, TypeError):
            return set()

    @staticmethod
    def _has_overlay(item: Dict) -> bool:
        """Check if item has overlay label"""
        labels = item.get("labels", [])
        if isinstance(labels, str):
            try:
                labels = json.loads(labels)
            except (json.JSONDecodeError, TypeError):
                labels = []
        return "Overlay" in labels
