import html
import itertools
import sys
from typing import Any, Dict, List

import plexapi
from plexapi import utils as plexutils
from plexapi.exceptions import NotFound
from pathvalidate import sanitize_filename
from plexapi.server import PlexServer
from unidecode import unidecode

from backend.util.helper import generate_title_variants, progress
from backend.util.normalization import normalize_titles


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

    def get_media_by_libraries(
        self,
        library_names: list = None,
        logger=None,
        instance_name=None,
    ):
        """
        Fetch all media for specified libraries (all if None).
        Returns dict {library_name: [media]}.
        """
        result = {}
        libraries = library_names or self.get_libraries()
        for library_name in libraries:
            try:
                media = self.get_all_plex_media(
                    library_name=library_name,
                    logger=logger or self.logger,
                    instance_name=instance_name,
                )
                result[library_name] = media
            except Exception as e:
                (logger or self.logger).error(
                    f"Error fetching media for '{library_name}': {e}"
                )
        return result

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
                folder = sanitize_filename(title_unescaped, platform="universal") or title_unescaped
                year = getattr(collection, "year", None)
                tmdb_id = getattr(collection, "tmdb_id", None)
                imdb_id = getattr(collection, "imdb_id", None)
                tvdb_id = getattr(collection, "tvdb_id", None)
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

        self.logger.debug(
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
                                "year": str(getattr(item, "year", "")),
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
                                "year": str(getattr(item, "year", "")),
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
                                    "year": str(getattr(item, "year", "")),
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
                                "year": str(getattr(item, "year", "")),
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
        try:
            section = self.plex.library.section(library_name)

            if is_collection:
                items = section.search(title=item_title, libtype="collection")
                if not items:
                    self.logger.error(
                        f"Collection '{item_title}' not found in '{library_name}'"
                    )
                    return False
                item = items[0]
                if not dry_run:
                    item.uploadPoster(filepath=poster_path)
                return True

            # TV Shows / Movies
            items = section.search(title=item_title, year=year)
            if not items:
                self.logger.error(
                    f"Item '{item_title}' not found in '{library_name}' (year={year})"
                )
                return False

            # Edition-aware matching: if edition is specified, find the matching
            # edition and narrow targets to that one item.
            # Otherwise, if multiple items share the same title+year (e.g. a
            # 1080p and a 4K copy that Plex never merged), upload to ALL of
            # them so both copies get the same poster. Picking items[0]
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
                if (
                    candidate_edition
                    and candidate_edition.lower() != str(edition).lower()
                ):
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
                        f"uploading poster to all copies."
                    )

            if season_number is not None:
                # Upload to the matching season on every target show.
                uploaded = 0
                for tgt in targets:
                    try:
                        seasons = [
                            s
                            for s in tgt.seasons()
                            if int(s.index) == int(season_number)
                        ]
                    except Exception:
                        seasons = []
                    if not seasons:
                        continue
                    if not dry_run:
                        seasons[0].uploadPoster(filepath=poster_path)
                    uploaded += 1
                if uploaded == 0:
                    self.logger.error(
                        f"Season {season_number} not found for '{item_title}' in '{library_name}'"
                    )
                    return False
                return True

            # Otherwise, upload to the main show/movie poster on every target.
            if not dry_run:
                for tgt in targets:
                    tgt.uploadPoster(filepath=poster_path)
            return True

        except Exception as e:
            self.logger.error(
                f"Failed to upload poster for '{item_title}' in '{library_name}': {e}"
            )
            return False

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

    def add_label(
        self,
        matched_entry: Dict[str, Any],
        label_name: str = "Overlay",
        dry_run: bool = False,
    ) -> None:
        """
        Add a label to a Plex item (movie, show, collection) using matched_entry from the index/db.
        Does NOT attempt to add labels to seasons or episodes.
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
                    f"[DRY RUN] Would add label '{label_name}' to '{title}' in '{section.title}'"
                )
            else:
                item.addLabel(label_name)
                self.logger.debug(
                    f"Added label '{label_name}' to '{title}' in '{section.title}'"
                )
        except Exception as e:
            self.logger.error(
                f"Failed to add label '{label_name}' to '{matched_entry.get('title', '')}': {e}"
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
