import html
import itertools
import sys
import time
from typing import Any, Dict, List, Optional

import plexapi
from plexapi import utils as plexutils
from plexapi.exceptions import NotFound
from pathvalidate import sanitize_filename
from plexapi.server import PlexServer
from unidecode import unidecode

from backend.util.helper import (
    YEAR_MATCH_TOLERANCE,
    generate_title_variants,
    progress,
)
from backend.util.normalization import normalize_titles
from backend.util.ssrf_guard import is_safe_url


def connect_plex_with_retry(
    url: str,
    token: str,
    logger: Any,
    *,
    instance_name: str = "",
    timeout: int = 30,
    max_retries: int = 5,
    backoff: int = 60,
    linear_backoff: bool = False,
) -> Optional[PlexServer]:
    """Connect to a Plex server with bounded retry; return the server or None.

    Single home for the server-level connect loop shared by the modules that
    need a raw ``PlexServer`` (poster_cleanarr, plex_maintenance) rather than the
    poster-upload-focused ``PlexClient``. An auth failure (401/unauthorized)
    returns None immediately — retrying won't help. ``linear_backoff=True`` waits
    ``backoff * attempt`` between tries (escalating); otherwise a flat ``backoff``.
    Instance *selection* stays with each caller (it differs by module); this only
    owns the connect+retry.
    """
    label = instance_name or url
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                f"Connecting to Plex '{label}' at {url} "
                f"(attempt {attempt}/{max_retries})..."
            )
            server = PlexServer(url, token, timeout=timeout)
            _ = server.version
            logger.info(f"Connected to Plex server v{server.version}")
            return server
        except Exception as e:
            err_msg = str(e).lower()
            if "unauthorized" in err_msg or "401" in err_msg:
                logger.error(
                    f"Authentication failed for Plex '{label}'. Check your API token."
                )
                return None
            if attempt < max_retries:
                wait = backoff * attempt if linear_backoff else backoff
                logger.warning(f"Plex connection failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                logger.error(
                    f"Failed to connect to Plex after {max_retries} attempts: {e}"
                )
                return None
    return None


class PlexClient:
    def __init__(self, url: str, api_token: str, logger: Any):
        """
        Handles connection to Plex and all API operations.
        """
        self.url = url
        self.api_token = api_token
        self.logger = logger
        self.plex = None
        self.connect()

    def connect(self) -> None:
        """
        Attempts to connect to the Plex server.
        """
        safe, reason = is_safe_url(self.url)
        if not safe:
            self.logger.error(f"Refused Plex connection to {self.url}: {reason}")
            self.plex = None
            return
        try:
            self.plex = PlexServer(self.url, self.api_token)

            _ = self.plex.version
            self.logger.debug(f"Connected to Plex at {self.url}")
        except Exception as e:
            self.logger.error(f"Failed to connect to Plex: {e}")
            self.plex = None

    def is_connected(self) -> bool:
        return self.plex is not None

    def get_libraries(self) -> list:
        """
        Returns a list of all library names on this Plex server.
        """
        try:
            return [section.title for section in self.plex.library.sections()]
        except Exception as e:
            self.logger.error(f"Failed to fetch libraries: {e}")
            return []

    def section_type(self, library_name: str) -> Optional[str]:
        """Return a library's Plex content type ('movie', 'show', 'artist', …),
        or None if it can't be resolved. Cached per client so callers can cheaply
        skip type-incompatible libraries (e.g. a movie against a 'show' library)
        instead of issuing a doomed search. None = "unknown, don't filter".
        """
        if not hasattr(self, "_section_type_cache"):
            self._section_type_cache: Dict[str, Optional[str]] = {}
        if library_name in self._section_type_cache:
            return self._section_type_cache[library_name]
        typ = None
        try:
            typ = self.plex.library.section(library_name).type
        except Exception as e:
            self.logger.debug(f"Could not resolve type for library '{library_name}': {e}")
        self._section_type_cache[library_name] = typ
        return typ

    def get_collections(
        self,
        library_name: str,
        include_smart: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves all collections (optionally including smart) from the specified library,
        with a progress bar.
        Returns a list of dicts (one per collection).
        """
        collections_data: List[Dict[str, Any]] = []
        try:
            library = self.plex.library.section(library_name)
        except NotFound:
            self.logger.error(
                f"Error: Library '{library_name}' not found, check your settings and try again."
            )
            return []
        collections = library.search(libtype="collection")
        if not include_smart:
            collections = [c for c in collections if not c.smart]

        with progress(
            collections,
            desc=f"Processing Plex collections in '{library_name}'",
            total=len(collections),
            unit="collection",
            logger=self.logger,
            leave=False,
        ) as inner:
            for collection in inner:
                title_unescaped = unidecode(html.unescape(collection.title))
                normalized_title = normalize_titles(title_unescaped)
                alternate_titles = generate_title_variants(title_unescaped)
                # Use pathvalidate rather than the bare regex so the folder name
                # is safe across Linux + Windows + Samba shares (handles
                # reserved names like CON/AUX, max-length truncation, and
                # trailing dots/spaces on top of the illegal-char strip).
                folder = (
                    sanitize_filename(title_unescaped, platform="universal")
                    or title_unescaped
                )
                # plexapi's Collection exposes neither a flat `year` nor
                # tmdb/imdb/tvdb attributes (only minYear/maxYear + .guids), so
                # those getattrs always returned None — collections are matched
                # by title. Take the earliest-item year from minYear when Plex
                # provides it; leave the external ids null.
                year = getattr(collection, "minYear", None)
                tmdb_id = None
                imdb_id = None
                tvdb_id = None
                media_item = {
                    "title": title_unescaped,
                    "normalized_title": normalized_title,
                    "location": library_name,
                    "year": year,
                    "folder": folder,
                    "alternate_titles": alternate_titles["alternate_titles"],
                    "normalized_alternate_titles": alternate_titles[
                        "normalized_alternate_titles"
                    ],
                    "library_name": library_name,
                    "asset_type": "collection",
                    "tmdb_id": tmdb_id,
                    "imdb_id": imdb_id,
                    "tvdb_id": tvdb_id,
                }
                collections_data.append(media_item)

        self.logger.info(
            f"Processed {len(collections)} collections in '{library_name}'"
        )

        return collections_data

    def get_all_plex_media(
        self,
        library_name: str,
        logger: Any,
        instance_name: str,
    ) -> list:
        """
        Indexes and caches a single Plex library for a Plex instance.
        Returns a list of dicts ready for DB upsert, matching the latest schema.
        """
        section = self.plex.library.section(library_name)
        typ = section.type
        all_entries = self.fetch_all_plex_media_with_paging(logger, section)
        items = []

        with progress(
            all_entries,
            desc=f"Indexing '{library_name}'",
            total=len(all_entries),
            unit=typ,
            logger=logger,
        ) as bar:
            for item in bar:
                guids = {
                    g.id.split("://")[0]: g.id.split("://")[1]
                    for g in getattr(item, "guids", [])
                    if "://" in g.id
                }
                # plexapi exposes `year` even when unset (as None) — coerce to
                # an empty string so downstream matchers don't compare against
                # the literal "None". Hits hardest on artists, which never
                # carry a year.
                item_year = str(getattr(item, "year", None) or "")
                try:
                    if typ == "movie":
                        file_paths = []
                        for media in getattr(item, "media", []) or []:
                            for part in getattr(media, "parts", []) or []:
                                f = getattr(part, "file", None)
                                if f:
                                    file_paths.append(f)
                        items.append(
                            {
                                "plex_id": str(item.ratingKey),
                                "instance_name": instance_name,
                                "asset_type": typ,
                                "library_name": library_name,
                                "title": item.title,
                                "normalized_title": normalize_titles(item.title),
                                "season_number": None,
                                "year": item_year,
                                "guids": guids,
                                "labels": [
                                    label.tag for label in getattr(item, "labels", [])
                                ],
                                "edition_title": getattr(item, "editionTitle", None),
                                "file_paths": file_paths,
                            }
                        )
                    elif typ in ("show", "tvshow"):
                        # Series-level folder locations — used by _find_plex_match
                        # to disambiguate duplicate series (e.g. 1080p + 4K libs
                        # that share GUIDs but live under different roots).
                        # Seasons inherit the parent's locations so that
                        # season-level matches disambiguate the same way.
                        show_paths = list(getattr(item, "locations", []) or [])

                        # Main show row (season_number=None)
                        items.append(
                            {
                                "plex_id": str(item.ratingKey),
                                "instance_name": instance_name,
                                "asset_type": typ,
                                "library_name": library_name,
                                "title": item.title,
                                "normalized_title": normalize_titles(item.title),
                                "season_number": None,
                                "year": item_year,
                                "guids": guids,
                                "labels": [
                                    label.tag for label in getattr(item, "labels", [])
                                ],
                                "file_paths": show_paths,
                            }
                        )
                        # Add a row for every season (with correct season_number)
                        for season in item.seasons():
                            items.append(
                                {
                                    "plex_id": str(season.ratingKey),
                                    "instance_name": instance_name,
                                    "asset_type": typ,
                                    "library_name": library_name,
                                    "title": item.title,
                                    "normalized_title": normalize_titles(item.title),
                                    "season_number": (
                                        int(season.index)
                                        if season.index is not None
                                        else None
                                    ),
                                    "year": item_year,
                                    "guids": guids,
                                    "labels": [
                                        label.tag
                                        for label in getattr(item, "labels", [])
                                    ],
                                    "file_paths": show_paths,
                                }
                            )
                    elif typ == "artist":
                        # Artist-level folder locations, same role as show_paths.
                        # Music libraries rarely have duplicates, but this
                        # closes the ingest gap consistently.
                        artist_paths = list(getattr(item, "locations", []) or [])
                        items.append(
                            {
                                "plex_id": str(item.ratingKey),
                                "instance_name": instance_name,
                                "asset_type": typ,
                                "library_name": library_name,
                                "title": item.title,
                                "normalized_title": normalize_titles(item.title),
                                "season_number": None,
                                "year": item_year,
                                "guids": guids,
                                "labels": [
                                    label.tag for label in getattr(item, "labels", [])
                                ],
                                "file_paths": artist_paths,
                            }
                        )
                except Exception as e:
                    logger.error(
                        f"Error processing item '{getattr(item, 'title', '')}': {e}"
                    )

        return items

    def fetch_all_plex_media_with_paging(self, logger, section):
        all_entries = []
        key = f"/library/sections/{section.key}/all?includeGuids=1&type={plexutils.searchType(section.type)}"
        container_start = 0
        container_size = plexapi.X_PLEX_CONTAINER_SIZE
        total_size = 1
        spinner = itertools.cycle(["-", "\\", "|", "/"])  # A simple rotating spinner

        while total_size > len(all_entries) and container_start <= total_size:
            # Your normal loading logic
            data = section._server.query(
                key,
                headers={
                    "X-Plex-Container-Start": str(container_start),
                    "X-Plex-Container-Size": str(container_size),
                },
            )
            subresults = section.findItems(data, initpath=key)
            total_size = plexutils.cast(
                int, data.attrib.get("totalSize") or data.attrib.get("size")
            ) or len(subresults)

            librarySectionID = plexutils.cast(int, data.attrib.get("librarySectionID"))
            if librarySectionID:
                for item in subresults:
                    item.librarySectionID = librarySectionID

            all_entries.extend(subresults)
            container_start += container_size

            # --- Spinner/Status line ---
            spin = next(spinner)
            msg = f"{spin} Loading: {len(all_entries)}/{total_size} items from {section.type.title()} for '{section.title}'..."
            sys.stdout.write("\r" + msg.ljust(60))
            sys.stdout.flush()

        print()  # Move to next line after done
        return all_entries

    def _locate_targets(
        self,
        library_name: str,
        item_title: str,
        year: Any = None,
        is_collection: bool = False,
        season_number: Any = None,
        edition: Any = None,
    ) -> list:
        """Cached front for :meth:`_locate_targets_uncached`.

        Plex library contents don't change mid-run, yet a single item is
        resolved over and over — logo, background, square art, and each season
        all pass the SAME locate parameters, differing only in which upload
        method runs afterwards. Re-searching each time is wasted work and was
        the source of the duplicated "not found" log spam. Memoize per client
        (asset/poster runs build a fresh client each time, so the cache is
        naturally per-run) so every (library, title, year, season, edition) is
        searched — and logged — at most once.
        """
        if not hasattr(self, "_locate_cache"):
            self._locate_cache: Dict[tuple, list] = {}
        key = (library_name, item_title, year, bool(is_collection), season_number, edition)
        if key not in self._locate_cache:
            self._locate_cache[key] = self._locate_targets_uncached(
                library_name,
                item_title,
                year=year,
                is_collection=is_collection,
                season_number=season_number,
                edition=edition,
            )
        return self._locate_cache[key]

    def _locate_targets_uncached(
        self,
        library_name: str,
        item_title: str,
        year: Any = None,
        is_collection: bool = False,
        season_number: Any = None,
        edition: Any = None,
    ) -> list:
        """Return the plexapi objects artwork should be uploaded to.

        Shared by every upload_* method so they apply the SAME item-location
        rules: collections by title; movies/shows by title+year (all unmerged
        copies, or edition-narrowed); a specific Season across the target shows
        when season_number is given. Returns [] (and logs) when nothing matches.
        """
        section = self.plex.library.section(library_name)

        if is_collection:
            items = section.search(title=item_title, libtype="collection")
            if not items:
                # Not an error: _locate_targets is called per-library across every
                # library on the instance, so a miss just means the item lives in
                # a different library. The caller handles "no targets anywhere".
                self.logger.debug(
                    f"Collection '{item_title}' not found in '{library_name}'"
                )
                return []
            return [items[0]]

        # TV Shows / Movies
        items = section.search(title=item_title, year=year)
        if not items and year is not None:
            # Year drift: Plex's year can differ from *arr/TMDB by a year
            # (production vs. release year), so a strict year= search misses an
            # item that IS in this library. Retry title-only and accept a
            # confident match: an unambiguous single hit, or same-title hits
            # within ±1 year. The library is already type-correct, so this
            # won't pull a same-named item of the wrong kind.
            candidates = section.search(title=item_title)
            if len(candidates) == 1:
                items = candidates
            elif candidates:
                try:
                    target_year = int(year)
                    items = [
                        c
                        for c in candidates
                        if getattr(c, "year", None) is not None
                        and abs(int(c.year) - target_year) <= YEAR_MATCH_TOLERANCE
                    ]
                except (TypeError, ValueError):
                    items = []
            if items:
                self.logger.debug(
                    f"'{item_title}' matched in '{library_name}' via year-tolerant "
                    f"fallback (requested year={year})"
                )
        if not items:
            # Debug, not error — expected when the item is in another library on
            # this instance (e.g. a Film searched against TV Programmes / Anime).
            self.logger.debug(
                f"Item '{item_title}' not found in '{library_name}' (year={year})"
            )
            return []

        # Edition-aware matching: if edition is specified, find the matching
        # edition and narrow targets to that one item.
        # Otherwise, if multiple items share the same title+year (e.g. a
        # 1080p and a 4K copy that Plex never merged), upload to ALL of
        # them so both copies get the same artwork. Picking items[0]
        # silently skipped the sibling.
        if edition and len(items) > 1:
            edition_match = next(
                (
                    c
                    for c in items
                    if getattr(c, "editionTitle", None)
                    and c.editionTitle.lower() == str(edition).lower()
                ),
                None,
            )
            targets = [edition_match] if edition_match else [items[0]]
        elif edition:
            candidate_edition = getattr(items[0], "editionTitle", None)
            if candidate_edition and candidate_edition.lower() != str(edition).lower():
                self.logger.debug(
                    f"Edition mismatch for '{item_title}': wanted '{edition}', "
                    f"found '{candidate_edition}'"
                )
            targets = [items[0]]
        else:
            targets = items
            if len(items) > 1:
                self.logger.debug(
                    f"'{item_title}' ({year}) has {len(items)} Plex items; "
                    f"uploading artwork to all copies."
                )

        if season_number is not None:
            # Narrow to the matching season on every target show.
            seasons_out = []
            for tgt in targets:
                try:
                    seasons_out.extend(
                        s
                        for s in tgt.seasons()
                        if int(s.index) == int(season_number)
                    )
                except Exception:
                    continue
            if not seasons_out:
                # Debug, not error: the show may simply not have this season in
                # this library (e.g. a missing Season 0 / specials), or it lives
                # in another library. Caller aggregates across libraries.
                self.logger.debug(
                    f"Season {season_number} not found for '{item_title}' in '{library_name}'"
                )
            return seasons_out

        return targets

    def _upload_artwork(
        self,
        method_name: str,
        art_label: str,
        library_name: str,
        item_title: str,
        *,
        filepath: Optional[str] = None,
        url: Optional[str] = None,
        year: Any = None,
        is_collection: bool = False,
        season_number: Any = None,
        edition: Any = None,
        dry_run: bool = False,
    ) -> bool:
        """Locate the target(s) and invoke a plexapi upload method on each.

        ``method_name`` is the plexapi method to call (uploadPoster / uploadArt
        / uploadLogo / uploadSquareArt); ``art_label`` is used only for logging.
        Provide exactly one of ``filepath`` (local file) or ``url`` (remote).
        """
        try:
            targets = self._locate_targets(
                library_name,
                item_title,
                year=year,
                is_collection=is_collection,
                season_number=season_number,
                edition=edition,
            )
            if not targets:
                return False
            if not dry_run:
                for tgt in targets:
                    method = getattr(tgt, method_name)
                    if url:
                        method(url=url)
                    else:
                        method(filepath=filepath)
            return True
        except Exception as e:
            self.logger.error(
                f"Failed to upload {art_label} for '{item_title}' in '{library_name}': {e}"
            )
            return False

    def upload_poster(
        self,
        library_name: str,
        item_title: str,
        poster_path: str,
        year: Any = None,
        is_collection: bool = False,
        season_number: Any = None,
        edition: Any = None,
        dry_run: bool = False,
    ) -> bool:
        """
        Upload a poster to Plex using plexapi's built-in methods.
        Supports uploading to a series season if season_number is given,
        and targeting a specific movie edition via editionTitle.
        """
        return self._upload_artwork(
            "uploadPoster",
            "poster",
            library_name,
            item_title,
            filepath=poster_path,
            year=year,
            is_collection=is_collection,
            season_number=season_number,
            edition=edition,
            dry_run=dry_run,
        )

    def upload_logo(
        self,
        library_name: str,
        item_title: str,
        *,
        filepath: Optional[str] = None,
        url: Optional[str] = None,
        year: Any = None,
        is_collection: bool = False,
        season_number: Any = None,
        edition: Any = None,
        dry_run: bool = False,
    ) -> bool:
        """Upload a clear logo (plexapi uploadLogo). Accepts a local filepath or
        a remote url (e.g. a TMDB image URL)."""
        return self._upload_artwork(
            "uploadLogo",
            "logo",
            library_name,
            item_title,
            filepath=filepath,
            url=url,
            year=year,
            is_collection=is_collection,
            season_number=season_number,
            edition=edition,
            dry_run=dry_run,
        )

    def upload_art(
        self,
        library_name: str,
        item_title: str,
        *,
        filepath: Optional[str] = None,
        url: Optional[str] = None,
        year: Any = None,
        is_collection: bool = False,
        season_number: Any = None,
        edition: Any = None,
        dry_run: bool = False,
    ) -> bool:
        """Upload background/fanart (plexapi uploadArt). Local filepath or url."""
        return self._upload_artwork(
            "uploadArt",
            "background",
            library_name,
            item_title,
            filepath=filepath,
            url=url,
            year=year,
            is_collection=is_collection,
            season_number=season_number,
            edition=edition,
            dry_run=dry_run,
        )

    def upload_square_art(
        self,
        library_name: str,
        item_title: str,
        *,
        filepath: Optional[str] = None,
        url: Optional[str] = None,
        year: Any = None,
        is_collection: bool = False,
        season_number: Any = None,
        edition: Any = None,
        dry_run: bool = False,
    ) -> bool:
        """Upload square art (plexapi uploadSquareArt). Local filepath or url."""
        return self._upload_artwork(
            "uploadSquareArt",
            "squareart",
            library_name,
            item_title,
            filepath=filepath,
            url=url,
            year=year,
            is_collection=is_collection,
            season_number=season_number,
            edition=edition,
            dry_run=dry_run,
        )

    def remove_label(
        self,
        matched_entry: Dict[str, Any],
        label_name: str = "Overlay",
        dry_run: bool = False,
    ) -> None:
        """
        Remove a label from a Plex item (movie, show, collection) using matched_entry from the index/db.
        Assumes the label is present—does NOT check labels (this should be done by caller).
        Does NOT attempt to remove labels from seasons or episodes.
        """
        try:
            section = self.plex.library.section(matched_entry["library_name"])
            asset_type = matched_entry.get("asset_type")
            title = matched_entry.get("title")
            year = matched_entry.get("year")
            if asset_type == "collection":
                items = section.search(title=title, libtype="collection")
                if not items:
                    self.logger.error(
                        f"Collection '{title}' not found in '{section.title}'"
                    )
                    return
                item = items[0]
            else:
                items = section.search(title=title, year=year)
                if not items:
                    self.logger.error(f"Item '{title}' not found in '{section.title}'")
                    return
                item = items[0]

            if dry_run:
                self.logger.info(
                    f"[DRY RUN] Would remove label '{label_name}' from '{title}' in '{section.title}'"
                )
            else:
                item.removeLabel(label_name)
                self.logger.debug(
                    f"Removed label '{label_name}' from '{title}' in '{section.title}'"
                )
        except Exception as e:
            self.logger.error(
                f"Failed to remove label '{label_name}' from '{matched_entry.get('title', '')}': {e}"
            )

    def batch_update_labels(
        self,
        matched_entry: Dict[str, Any],
        labels_to_add: List[str],
        labels_to_remove: List[str],
        dry_run: bool = False,
    ) -> None:
        """
        Apply multiple label changes to a single Plex item in one search operation.
        Avoids race conditions from separate search calls per label change.
        """
        try:
            section = self.plex.library.section(matched_entry["library_name"])
            asset_type = matched_entry.get("asset_type")
            title = matched_entry.get("title")
            year = matched_entry.get("year")

            if asset_type == "collection":
                items = section.search(title=title, libtype="collection")
            else:
                items = section.search(title=title, year=year)

            if not items:
                self.logger.error(f"Item '{title}' not found in '{section.title}'")
                return

            item = items[0]

            if dry_run:
                for label in labels_to_add:
                    self.logger.info(
                        f"[DRY RUN] Would add label '{label}' to '{title}' in '{section.title}'"
                    )
                for label in labels_to_remove:
                    self.logger.info(
                        f"[DRY RUN] Would remove label '{label}' from '{title}' in '{section.title}'"
                    )
            else:
                for label in labels_to_add:
                    item.addLabel(label)
                    self.logger.debug(
                        f"Added label '{label}' to '{title}' in '{section.title}'"
                    )
                for label in labels_to_remove:
                    item.removeLabel(label)
                    self.logger.debug(
                        f"Removed label '{label}' from '{title}' in '{section.title}'"
                    )
        except Exception as e:
            self.logger.error(
                f"Failed to update labels for '{matched_entry.get('title', '')}': {e}"
            )
