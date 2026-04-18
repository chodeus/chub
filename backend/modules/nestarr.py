# modules/nestarr.py

import os
from typing import Any, Dict, List, Optional

from backend.util.arr import create_arr_client
from backend.util.base_module import ChubModule
from backend.util.database import ChubDB
from backend.util.helper import create_table, print_settings, progress
from backend.util.logger import Logger
from backend.util.notification import NotificationManager


class _NestScanner:
    """
    Scans for media mismatches and path nesting:

    Phase 1 — Database comparison: finds media in ARR but not in Plex
    (and vice versa) using the media_cache and plex_media_cache tables.

    Phase 2 — Path nesting: detects tracked media items whose paths are
    nested inside other tracked media items.
    """

    VIDEO_EXTS = frozenset({".mkv", ".mp4", ".avi", ".m4v", ".wmv", ".ts", ".m2ts"})

    def __init__(self, instances_config, logger, db=None, instance_filter=None,
                 library_mappings=None, path_mapping=None):
        self.instances_config = instances_config
        self.logger = logger
        self.db = db
        self.instance_filter = instance_filter
        self.library_mappings = library_mappings
        self.path_mapping = path_mapping or []
        self._cancelled = lambda: False

    def set_cancel_check(self, fn):
        self._cancelled = fn

    def scan(self) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        radarr_media: List[Dict[str, Any]] = []
        sonarr_media: List[Dict[str, Any]] = []
        lidarr_media: List[Dict[str, Any]] = []

        # Derive effective instance filter from library_mappings if configured
        effective_filter = self.instance_filter
        if self.library_mappings and not effective_filter:
            effective_filter = [
                m.arr_instance if hasattr(m, "arr_instance") else m.get("arr_instance", "")
                for m in self.library_mappings
                if (m.arr_instance if hasattr(m, "arr_instance") else m.get("arr_instance"))
            ]

        # Connect to ARR instances and collect tracked media paths for nesting detection
        for instance_type in ["radarr", "sonarr", "lidarr"]:
            if self._cancelled():
                return issues

            instances = getattr(self.instances_config, instance_type, {})
            if not instances:
                continue

            for instance_name, instance_info in instances.items():
                if self._cancelled():
                    return issues
                if not instance_info.enabled:
                    continue
                if effective_filter and instance_name not in effective_filter:
                    continue

                app = create_arr_client(
                    instance_info.url, instance_info.api, self.logger
                )
                if not app or not app.is_connected():
                    self.logger.warning(
                        f"[{instance_type}] '{instance_name}': connection failed."
                    )
                    continue

                raw_media = app.get_media()
                if not raw_media:
                    self.logger.debug(
                        f"[{instance_type}] '{instance_name}': no media found."
                    )
                    continue

                self.logger.info(
                    f"[{instance_type}] '{instance_name}': "
                    f"loaded {len(raw_media)} tracked items"
                )

                # Log sample item structure for debugging path resolution
                if raw_media:
                    sample = raw_media[0]
                    path_field = (
                        "path" if "path" in sample
                        else "folderPath" if "folderPath" in sample
                        else "MISSING"
                    )
                    self.logger.debug(
                        f"[{instance_type}] '{instance_name}': "
                        f"path field='{path_field}', "
                        f"sample path='{sample.get('path') or sample.get('folderPath', 'N/A')}', "
                        f"rootFolderPath='{sample.get('rootFolderPath', 'N/A')}'"
                    )

                media_items = []
                for item in raw_media:
                    path = item.get("path") or item.get("folderPath") or ""
                    if not path:
                        continue
                    normed = os.path.normpath(path)
                    # Capture download state so Phase 1 can skip
                    # monitored-but-not-downloaded entries (they can't be
                    # in Plex by definition).
                    if instance_type == "radarr":
                        has_file = bool(item.get("hasFile"))
                    elif instance_type == "sonarr":
                        stats = item.get("statistics") or {}
                        has_file = (stats.get("episodeFileCount") or 0) > 0
                    elif instance_type == "lidarr":
                        stats = item.get("statistics") or {}
                        has_file = (stats.get("trackFileCount") or 0) > 0
                    else:
                        has_file = True
                    media_items.append({
                        "media_id": item.get("id"),
                        "title": item.get("title", "Unknown"),
                        "year": item.get("year"),
                        "path": normed,
                        "root_folder": item.get("rootFolderPath", ""),
                        "instance_type": instance_type,
                        "instance_name": instance_name,
                        "has_file": has_file,
                    })

                if instance_type == "radarr":
                    radarr_media.extend(media_items)
                elif instance_type == "sonarr":
                    sonarr_media.extend(media_items)
                elif instance_type == "lidarr":
                    lidarr_media.extend(media_items)

        # Phase 1: Database comparison — ARR vs Plex
        if self.db and not self._cancelled():
            # Build set of (instance_name, arr_id) for items that actually
            # have a file on disk. Monitored-but-not-downloaded items get
            # skipped from ARR→Plex comparison (they can't be in Plex).
            live_with_file = {
                (m["instance_name"], m["media_id"])
                for m in (*radarr_media, *sonarr_media, *lidarr_media)
                if m.get("has_file") and m.get("media_id") is not None
            }
            issues.extend(self._detect_unmatched(live_with_file))

        # Phase 2: Path nesting among tracked items
        if not self._cancelled():
            issues.extend(self._detect_nesting(radarr_media, "movie"))
        if not self._cancelled():
            issues.extend(self._detect_nesting(sonarr_media, "series"))
        if not self._cancelled():
            issues.extend(self._detect_nesting(lidarr_media, "artist"))
        if not self._cancelled():
            issues.extend(self._detect_cross_nesting(radarr_media, sonarr_media))
        # Cross-nesting with Lidarr
        if lidarr_media and not self._cancelled():
            issues.extend(self._cross_check(lidarr_media, radarr_media, "artist_in_movie"))
        if lidarr_media and not self._cancelled():
            issues.extend(self._cross_check(radarr_media, lidarr_media, "movie_in_artist"))
        if lidarr_media and not self._cancelled():
            issues.extend(self._cross_check(lidarr_media, sonarr_media, "artist_in_series"))
        if lidarr_media and not self._cancelled():
            issues.extend(self._cross_check(sonarr_media, lidarr_media, "series_in_artist"))

        # Phase 3: Filesystem scan for stray/misplaced files
        if not self._cancelled():
            all_media = {
                "movie": radarr_media,
                "series": sonarr_media,
                "artist": lidarr_media,
            }
            issues.extend(self._detect_stray_files(all_media))

        return issues

    # ------------------------------------------------------------------
    # Phase 1: Database comparison — ARR media vs Plex media
    # ------------------------------------------------------------------

    def _build_mapping_lookups(self):
        """
        Build lookup structures from library_mappings config.

        Returns:
            arr_to_libraries: {arr_instance: set((plex_inst, lib_name), ...)}
                For each ARR instance, which Plex libraries to compare against.
            mapped_libraries: set((plex_inst, lib_name), ...)
                All mapped library pairs — Plex items outside this set are excluded.
        """
        arr_to_libraries = {}
        mapped_libraries = set()

        for mapping in (self.library_mappings or []):
            arr_inst = (
                getattr(mapping, "arr_instance", None)
                if hasattr(mapping, "arr_instance")
                else mapping.get("arr_instance", "")
            )
            if not arr_inst:
                continue

            plex_instances = (
                getattr(mapping, "plex_instances", [])
                if hasattr(mapping, "plex_instances")
                else mapping.get("plex_instances", [])
            ) or []

            if arr_inst not in arr_to_libraries:
                arr_to_libraries[arr_inst] = set()

            for pi in plex_instances:
                inst = (
                    getattr(pi, "instance", None)
                    if hasattr(pi, "instance")
                    else (pi.get("instance") if isinstance(pi, dict) else None)
                )
                libs = (
                    getattr(pi, "library_names", None)
                    if hasattr(pi, "library_names")
                    else (pi.get("library_names") if isinstance(pi, dict) else None)
                )
                if not inst or not libs:
                    continue
                for lib_name in libs:
                    if isinstance(lib_name, str) and lib_name.strip():
                        pair = (inst, lib_name)
                        arr_to_libraries[arr_inst].add(pair)
                        mapped_libraries.add(pair)

        return arr_to_libraries, mapped_libraries

    def _detect_unmatched(
        self, live_with_file: Optional[set] = None
    ) -> List[Dict[str, Any]]:
        """
        Compare media_cache against plex_media_cache to find:
        - Items in ARR with no Plex match (plex_mapping_id is NULL/invalid)
        - Items in Plex with no ARR entry pointing to them

        When library_mappings is configured, only mapped libraries are
        compared and unmapped libraries (e.g. Music) are excluded entirely.

        If live_with_file is provided, ARR→Plex comparison skips media_cache
        rows whose (instance_name, arr_id) is not in the set — i.e. items
        that are monitored in the ARR but have no file on disk yet. Those
        can't be in Plex, so they're not real mismatches.
        """
        issues: List[Dict[str, Any]] = []

        # Build mapping lookups if configured
        has_mappings = bool(self.library_mappings)
        if has_mappings:
            arr_to_libraries, mapped_libraries = self._build_mapping_lookups()
            effective_instance_filter = set(arr_to_libraries.keys())
            self.logger.debug(
                f"[Phase 1] Library mappings active — "
                f"ARR instances: {sorted(arr_to_libraries.keys())}"
            )
            for arr_inst, libs in arr_to_libraries.items():
                self.logger.debug(
                    f"  {arr_inst} → {len(libs)} Plex libraries: "
                    f"{sorted(f'{inst}/{lib}' for inst, lib in libs)}"
                )
        else:
            mapped_libraries = set()
            effective_instance_filter = (
                set(self.instance_filter) if self.instance_filter else None
            )
            self.logger.debug(
                f"[Phase 1] No library mappings — "
                f"instance filter: {sorted(effective_instance_filter) if effective_instance_filter else 'ALL'}"
            )

        # Get all Plex items
        plex_items_raw = self.db.plex.get_all() or []

        # When mappings exist, filter Plex items to only mapped libraries
        if has_mappings:
            plex_items = [
                item for item in plex_items_raw
                if (item.get("instance_name"), item.get("library_name")) in mapped_libraries
            ]
        else:
            plex_items = plex_items_raw

        self.logger.debug(
            f"[Phase 1] Plex items: {len(plex_items_raw)} total, "
            f"{len(plex_items)} after filtering"
        )

        valid_plex_ids = {item.get("id") for item in plex_items if item.get("id")}

        # Pre-build plex_id -> (instance_name, library_name) lookup for O(n) performance
        plex_lookup = {}
        for p in plex_items_raw:
            pid = p.get("id")
            if pid is not None:
                plex_lookup[pid] = (p.get("instance_name"), p.get("library_name"))

        # Get all media cache items (used for both directions of comparison)
        all_media_unfiltered = self.db.media.get_all() or []

        # Filter by effective instances for ARR-not-in-Plex direction
        if effective_instance_filter:
            all_media = [
                m for m in all_media_unfiltered
                if m.get("instance_name") in effective_instance_filter
            ]
        else:
            all_media = all_media_unfiltered

        self.logger.debug(
            f"[Phase 1] Media cache: {len(all_media_unfiltered)} total, "
            f"{len(all_media)} after instance filtering"
        )

        if self._cancelled():
            return issues

        # Build set of plex IDs referenced by ANY media_cache entry
        # (used for Plex-not-in-ARR direction — unfiltered so we don't
        # report Plex items matched by a different ARR instance)
        matched_plex_ids = set()
        for item in all_media_unfiltered:
            mid = item.get("plex_mapping_id")
            if mid is not None:
                matched_plex_ids.add(mid)

        self.logger.debug(
            f"[Phase 1] {len(matched_plex_ids)} Plex IDs referenced by media_cache entries"
        )

        # Find ARR items not matched to Plex
        arr_matched = 0
        arr_unmatched = 0
        arr_skipped_no_file = 0
        for item in all_media:
            if self._cancelled():
                return issues

            # Skip items the live ARR pull says have no file on disk.
            # They can't possibly be in Plex, so reporting them as
            # "ARR→Plex unmatched" is noise.
            if live_with_file is not None:
                arr_id = item.get("arr_id")
                inst_name = item.get("instance_name", "")
                if arr_id is not None and (inst_name, arr_id) not in live_with_file:
                    arr_skipped_no_file += 1
                    continue

            mapping_id = item.get("plex_mapping_id")

            if has_mappings:
                # With mappings: check if mapping_id points to a Plex item
                # from a library mapped to THIS specific ARR instance
                inst_name = item.get("instance_name", "")
                mapped_libs_for_arr = arr_to_libraries.get(inst_name, set())

                if mapping_id is not None:
                    plex_pair = plex_lookup.get(mapping_id)
                    if plex_pair and plex_pair in mapped_libs_for_arr:
                        arr_matched += 1
                        continue  # Matched within a mapped library
                    # Unmatched — log reason
                    reason = (
                        f"plex_mapping_id={mapping_id} not in plex_lookup"
                        if plex_pair is None
                        else f"plex_mapping_id={mapping_id} maps to {plex_pair[0]}/{plex_pair[1]} "
                             f"which is not in mapped libraries for {inst_name}"
                    )
                else:
                    reason = "plex_mapping_id is NULL"
            else:
                # Without mappings: original behavior
                if mapping_id is not None and mapping_id in valid_plex_ids:
                    arr_matched += 1
                    continue  # Already matched
                reason = (
                    "plex_mapping_id is NULL"
                    if mapping_id is None
                    else f"plex_mapping_id={mapping_id} not in {len(valid_plex_ids)} valid Plex IDs"
                )

            # Skip season entries to avoid duplicating show-level issues
            if item.get("season_number") is not None:
                continue

            arr_unmatched += 1
            instance_name = item.get("instance_name", "unknown")
            media_id = item.get("id", 0)

            self.logger.debug(
                f"  [ARR→Plex] UNMATCHED: {instance_name} "
                f"'{item.get('title', '?')}' ({item.get('year', '?')}) "
                f"id={media_id} — {reason}"
            )

            issue_id = f"arr_unmatched_{instance_name}_{media_id}".replace(" ", "_")

            issues.append({
                "id": issue_id,
                "type": "arr_not_in_plex",
                "name": item.get("title", "Unknown"),
                "year": item.get("year"),
                "path": item.get("folder", ""),
                "instance": instance_name,
                "instance_type": item.get("source", ""),
                "parent": None,
                "nested": None,
                "suggested_path": None,
                "suggested_action": "review",
            })

        self.logger.debug(
            f"[Phase 1] ARR→Plex: {arr_matched} matched, {arr_unmatched} unmatched, "
            f"{arr_skipped_no_file} skipped (no file on disk)"
        )

        if self._cancelled():
            return issues

        # Find Plex items not matched to ARR
        # plex_items already filtered to mapped libraries when mappings exist
        plex_matched = 0
        plex_unmatched = 0
        for plex_item in plex_items:
            if self._cancelled():
                return issues

            plex_id = plex_item.get("id")
            if plex_id in matched_plex_ids:
                plex_matched += 1
                continue  # An ARR item points to this Plex item

            # Skip season entries
            if plex_item.get("season_number") is not None:
                continue

            plex_unmatched += 1
            instance_name = plex_item.get("instance_name", "unknown")

            self.logger.debug(
                f"  [Plex→ARR] UNMATCHED: {instance_name} "
                f"[{plex_item.get('library_name', '?')}] "
                f"'{plex_item.get('title', '?')}' ({plex_item.get('year', '?')}) "
                f"plex_id={plex_id} — no media_cache entry references this ID"
            )

            issue_id = f"plex_unmatched_{instance_name}_{plex_id}".replace(" ", "_")

            issues.append({
                "id": issue_id,
                "type": "plex_not_in_arr",
                "name": plex_item.get("title", "Unknown"),
                "year": plex_item.get("year"),
                "instance": instance_name,
                "instance_type": "plex",
                "library_name": plex_item.get("library_name", ""),
                "path": None,
                "parent": None,
                "nested": None,
                "suggested_path": None,
                "suggested_action": "review",
            })

        self.logger.debug(
            f"[Phase 1] Plex→ARR: {plex_matched} matched, {plex_unmatched} unmatched"
        )
        self.logger.debug(
            f"[Phase 1] Total unmatched issues: {len(issues)}"
        )

        return issues

    # ------------------------------------------------------------------
    # Phase 2: Path nesting among tracked items
    # ------------------------------------------------------------------

    def _detect_nesting(
        self, media_list: List[Dict[str, Any]], media_type: str
    ) -> List[Dict[str, Any]]:
        if len(media_list) < 2:
            return []

        sorted_media = sorted(media_list, key=lambda m: m["path"])
        issues: List[Dict[str, Any]] = []

        self.logger.debug(
            f"[Phase 2] Nesting check ({media_type}): {len(sorted_media)} items"
        )
        # Log first few paths for context
        for sample in sorted_media[:5]:
            self.logger.debug(
                f"  {sample['instance_name']}: "
                f"'{sample['title']}' → {sample['path']}"
            )
        if len(sorted_media) > 5:
            self.logger.debug(f"  ... and {len(sorted_media) - 5} more")

        for i in range(len(sorted_media) - 1):
            parent = sorted_media[i]
            for j in range(i + 1, len(sorted_media)):
                child = sorted_media[j]
                if child["path"].startswith(parent["path"] + os.sep):
                    nesting_type = {
                        "movie": "movie_in_movie",
                        "series": "series_in_series",
                        "artist": "artist_in_artist",
                    }.get(media_type, f"{media_type}_in_{media_type}")
                    self.logger.debug(
                        f"  [NESTED] {nesting_type}: "
                        f"'{child['title']}' ({child['instance_name']}) "
                        f"is inside '{parent['title']}' ({parent['instance_name']})"
                    )
                    self.logger.debug(
                        f"    parent: {parent['path']}"
                    )
                    self.logger.debug(
                        f"    child:  {child['path']}"
                    )
                    issues.append(self._build_nesting_issue(
                        child, parent, nesting_type
                    ))
                elif not child["path"].startswith(parent["path"]):
                    # Once we pass all paths sharing the parent prefix,
                    # no later (sorted) path can be nested under it.
                    break

        self.logger.debug(
            f"[Phase 2] {media_type} nesting: {len(issues)} issues found"
        )

        return issues

    def _detect_cross_nesting(
        self,
        radarr_media: List[Dict[str, Any]],
        sonarr_media: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        issues.extend(
            self._cross_check(radarr_media, sonarr_media, "movie_in_series")
        )
        issues.extend(
            self._cross_check(sonarr_media, radarr_media, "series_in_movie")
        )
        return issues

    def _cross_check(
        self,
        children: List[Dict[str, Any]],
        parents: List[Dict[str, Any]],
        nesting_type: str,
    ) -> List[Dict[str, Any]]:
        if not children or not parents:
            return []

        issues: List[Dict[str, Any]] = []
        sorted_parents = sorted(parents, key=lambda m: m["path"])

        for child in children:
            for parent in sorted_parents:
                if child["path"].startswith(parent["path"] + os.sep):
                    self.logger.debug(
                        f"  [CROSS-NESTED] {nesting_type}: "
                        f"'{child['title']}' ({child['instance_name']}) "
                        f"inside '{parent['title']}' ({parent['instance_name']})"
                    )
                    issues.append(self._build_nesting_issue(
                        child, parent, nesting_type
                    ))
                    break

        if issues:
            self.logger.debug(
                f"[Phase 2] {nesting_type}: {len(issues)} cross-nesting issues"
            )

        return issues

    # ------------------------------------------------------------------
    # Phase 3: Filesystem scan for stray / misplaced media files
    # ------------------------------------------------------------------

    def _translate_path(self, path: str) -> str:
        """Apply path_mapping prefix replacements (ARR path → CHUB-accessible path)."""
        for mapping in self.path_mapping:
            arr_prefix = mapping.get("arr_path", "")
            local_prefix = mapping.get("local_path", "")
            if arr_prefix and local_prefix and path.startswith(arr_prefix):
                return local_prefix + path[len(arr_prefix):]
        return path

    def _is_video_file(self, filename: str) -> bool:
        return os.path.splitext(filename)[1].lower() in self.VIDEO_EXTS

    def _detect_stray_files(
        self, media_by_type: Dict[str, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """
        Phase 3: Walk ARR root folders on the filesystem and detect:
        - Directories not tracked by any media item (stray_folder)
        - Video files sitting directly in a root folder (stray_file)
        - Extra video files inside a tracked media folder (extra_video_in_folder)
        """
        issues: List[Dict[str, Any]] = []

        for media_type, media_items in media_by_type.items():
            if self._cancelled() or not media_items:
                continue

            # Group items by root folder
            root_to_items: Dict[str, List[Dict[str, Any]]] = {}
            for item in media_items:
                root = os.path.normpath(item["root_folder"])
                root_to_items.setdefault(root, []).append(item)

            for arr_root, items_in_root in root_to_items.items():
                if self._cancelled():
                    break

                local_root = self._translate_path(arr_root)

                if not os.path.isdir(local_root):
                    self.logger.debug(
                        f"[Phase 3] Root folder not accessible: {arr_root}"
                        + (f" (translated to {local_root})" if local_root != arr_root else "")
                        + " — skipping filesystem scan"
                    )
                    continue

                # Build set of expected folder basenames for this root
                expected_folders = set()
                path_to_item: Dict[str, Dict[str, Any]] = {}
                for item in items_in_root:
                    basename = os.path.basename(item["path"])
                    expected_folders.add(basename)
                    local_path = self._translate_path(item["path"])
                    path_to_item[local_path] = item

                self.logger.debug(
                    f"[Phase 3] Scanning root '{arr_root}' ({media_type}): "
                    f"{len(expected_folders)} tracked folders"
                )

                # Scan root folder children
                try:
                    children = os.listdir(local_root)
                except OSError as e:
                    self.logger.warning(
                        f"[Phase 3] Cannot list root '{local_root}': {e}"
                    )
                    continue

                stray_count = 0
                for child in children:
                    if self._cancelled():
                        break
                    child_path = os.path.join(local_root, child)

                    if os.path.isdir(child_path):
                        if child not in expected_folders:
                            stray_count += 1
                            # Map back to ARR path for display
                            arr_child_path = os.path.join(arr_root, child)
                            issue_id = (
                                f"stray_{media_type}_{child}"
                            ).replace(" ", "_")[:120]
                            self.logger.debug(
                                f"  [STRAY FOLDER] {arr_child_path}"
                            )
                            issues.append({
                                "id": issue_id,
                                "type": "stray_folder",
                                "name": child,
                                "path": arr_child_path,
                                "root_folder": arr_root,
                                "instance": items_in_root[0]["instance_name"],
                                "instance_type": items_in_root[0]["instance_type"],
                                "parent": None,
                                "nested": None,
                                "suggested_path": None,
                                "suggested_action": "review",
                            })
                    elif os.path.isfile(child_path) and self._is_video_file(child):
                        stray_count += 1
                        arr_child_path = os.path.join(arr_root, child)
                        issue_id = f"stray_file_{media_type}_{child}".replace(" ", "_")[:120]
                        self.logger.debug(
                            f"  [STRAY FILE] {arr_child_path}"
                        )
                        issues.append({
                            "id": issue_id,
                            "type": "stray_file",
                            "name": child,
                            "path": arr_child_path,
                            "root_folder": arr_root,
                            "instance": items_in_root[0]["instance_name"],
                            "instance_type": items_in_root[0]["instance_type"],
                            "parent": None,
                            "nested": None,
                            "suggested_path": None,
                            "suggested_action": "review",
                        })

                # Check tracked media folders for extra video files
                # (only for movies — series/artists legitimately have multiple video files)
                if media_type == "movie":
                    for local_path, item in path_to_item.items():
                        if self._cancelled():
                            break
                        if not os.path.isdir(local_path):
                            continue
                        try:
                            video_files = [
                                f for f in os.listdir(local_path)
                                if os.path.isfile(os.path.join(local_path, f))
                                and self._is_video_file(f)
                            ]
                        except OSError:
                            continue
                        if len(video_files) > 1:
                            stray_count += 1
                            arr_item_path = item["path"]
                            issue_id = (
                                f"extra_video_{item['instance_name']}"
                                f"_{item['media_id']}"
                            ).replace(" ", "_")
                            self.logger.debug(
                                f"  [EXTRA VIDEO] {arr_item_path} has "
                                f"{len(video_files)} video files: {video_files}"
                            )
                            issues.append({
                                "id": issue_id,
                                "type": "extra_video_in_folder",
                                "name": item["title"],
                                "year": item.get("year"),
                                "path": arr_item_path,
                                "root_folder": item["root_folder"],
                                "instance": item["instance_name"],
                                "instance_type": item["instance_type"],
                                "video_files": video_files,
                                "parent": {
                                    "title": item["title"],
                                    "year": item.get("year"),
                                    "path": arr_item_path,
                                    "media_id": item["media_id"],
                                    "instance": item["instance_name"],
                                    "instance_type": item["instance_type"],
                                },
                                "nested": None,
                                "suggested_path": None,
                                "suggested_action": "review",
                            })

                self.logger.debug(
                    f"[Phase 3] {arr_root}: {stray_count} issues found"
                )

        self.logger.debug(
            f"[Phase 3] Total filesystem issues: {len(issues)}"
        )
        return issues

    @staticmethod
    def _build_nesting_issue(
        child: Dict[str, Any], parent: Dict[str, Any], nesting_type: str
    ) -> Dict[str, Any]:
        nested_folder = os.path.basename(child["path"])
        root = os.path.normpath(child["root_folder"])
        suggested_path = os.path.join(root, nested_folder)

        issue_id = (
            f"{child['instance_type']}_{child['instance_name']}"
            f"_{child['media_id']}"
        ).replace(" ", "_")

        return {
            "id": issue_id,
            "type": nesting_type,
            "path": child["path"],
            "name": child["title"],
            "root_folder": child["root_folder"],
            "instance": child["instance_name"],
            "instance_type": child["instance_type"],
            "suggested_action": "move",
            "suggested_path": suggested_path,
            "parent": {
                "title": parent["title"],
                "year": parent.get("year"),
                "path": parent["path"],
                "media_id": parent["media_id"],
                "instance": parent["instance_name"],
                "instance_type": parent["instance_type"],
            },
            "nested": {
                "title": child["title"],
                "year": child.get("year"),
                "path": child["path"],
                "media_id": child["media_id"],
                "root_folder": child["root_folder"],
                "instance": child["instance_name"],
                "instance_type": child["instance_type"],
            },
        }


class Nestarr(ChubModule):
    def __init__(self, logger: Optional[Logger] = None) -> None:
        super().__init__(logger=logger)

    def run(self) -> None:
        """
        Compare ARR media against Plex to find unmatched items,
        and detect incorrectly nested media paths.
        """
        try:
            if self.config.log_level.lower() == "debug":
                print_settings(self.logger, self.config)

            if self.config.dry_run:
                table = [["Dry Run"], ["NO CHANGES WILL BE MADE"]]
                self.logger.info(create_table(table))
                self.logger.info("")

            with ChubDB(logger=self.logger, quiet=True) as db:
                scanner = _NestScanner(
                    self.full_config.instances,
                    self.logger,
                    db=db,
                    instance_filter=self.config.instances if not self.config.library_mappings else None,
                    library_mappings=self.config.library_mappings if self.config.library_mappings else None,
                    path_mapping=self.config.path_mapping if self.config.path_mapping else None,
                )
                scanner.set_cancel_check(self.is_cancelled)

                self.logger.info("Scanning for unmatched and nested media...")
                self.logger.info("")
                all_issues = scanner.scan()

            if self.is_cancelled():
                self.logger.info("Scan cancelled.")
                return

            if all_issues:
                # Tally by type
                FILESYSTEM_TYPES = {"stray_folder", "stray_file", "extra_video_in_folder"}
                UNMATCHED_TYPES = {"arr_not_in_plex", "plex_not_in_arr"}
                arr_not_in_plex = [i for i in all_issues if i["type"] == "arr_not_in_plex"]
                plex_not_in_arr = [i for i in all_issues if i["type"] == "plex_not_in_arr"]
                nesting_issues = [
                    i for i in all_issues
                    if i["type"] not in UNMATCHED_TYPES and i["type"] not in FILESYSTEM_TYPES
                ]
                filesystem_issues = [i for i in all_issues if i["type"] in FILESYSTEM_TYPES]

                summary = [["Issue Type", "Count"]]
                if arr_not_in_plex:
                    summary.append(["In ARR, Not in Plex", str(len(arr_not_in_plex))])
                if plex_not_in_arr:
                    summary.append(["In Plex, Not in ARR", str(len(plex_not_in_arr))])
                if nesting_issues:
                    summary.append(["Nested Media", str(len(nesting_issues))])
                if filesystem_issues:
                    summary.append(["Stray/Misplaced Files", str(len(filesystem_issues))])
                summary.append(["Total", str(len(all_issues))])

                self.logger.info(create_table(summary))
                self.logger.info("")

                # Report unmatched content
                if arr_not_in_plex:
                    self.logger.info("--- In ARR but Not in Plex ---")
                    self.logger.info("")
                    with progress(
                        arr_not_in_plex,
                        desc="ARR unmatched",
                        unit="items",
                        logger=self.logger,
                        leave=True,
                    ) as pbar:
                        for issue in pbar:
                            if self.is_cancelled():
                                break
                            year = f" ({issue['year']})" if issue.get("year") else ""
                            self.logger.info(
                                f"  [NOT IN PLEX] {issue['name']}{year}"
                                f" — {issue['instance']}"
                            )

                if plex_not_in_arr and not self.is_cancelled():
                    self.logger.info("")
                    self.logger.info("--- In Plex but Not in ARR ---")
                    self.logger.info("")
                    with progress(
                        plex_not_in_arr,
                        desc="Plex unmatched",
                        unit="items",
                        logger=self.logger,
                        leave=True,
                    ) as pbar:
                        for issue in pbar:
                            if self.is_cancelled():
                                break
                            year = f" ({issue['year']})" if issue.get("year") else ""
                            lib = f" [{issue.get('library_name', '')}]" if issue.get("library_name") else ""
                            self.logger.info(
                                f"  [NOT IN ARR] {issue['name']}{year}"
                                f" — {issue['instance']}{lib}"
                            )

                # Report nesting issues
                if nesting_issues and not self.is_cancelled():
                    self.logger.info("")
                    self.logger.info("--- Nested Media ---")
                    self.logger.info("")
                    with progress(
                        nesting_issues,
                        desc="Nested items",
                        unit="items",
                        logger=self.logger,
                        leave=True,
                    ) as pbar:
                        for issue in pbar:
                            if self.is_cancelled():
                                break
                            self._log_nesting_issue(issue)

                # Report filesystem issues
                if filesystem_issues and not self.is_cancelled():
                    self.logger.info("")
                    self.logger.info("--- Stray / Misplaced Files ---")
                    self.logger.info("")
                    for issue in filesystem_issues:
                        if self.is_cancelled():
                            break
                        itype = issue["type"].replace("_", " ").upper()
                        path = issue.get("path", "?")
                        name = issue.get("name", "?")
                        if issue["type"] == "extra_video_in_folder":
                            files = issue.get("video_files", [])
                            self.logger.info(
                                f"  [{itype}] {name} — {path}"
                            )
                            self.logger.info(
                                f"    Contains {len(files)} video files: {', '.join(files)}"
                            )
                        else:
                            self.logger.info(
                                f"  [{itype}] {path}"
                            )

                manager = NotificationManager(
                    self.config, self.logger, module_name="nestarr"
                )
                manager.send_notification(all_issues)
            else:
                self.logger.info(
                    "No unmatched or nesting issues found."
                )

        except KeyboardInterrupt:
            print("Keyboard Interrupt detected. Exiting...")
            return
        except Exception:
            self.logger.error("\n\nAn error occurred:\n", exc_info=True)
            self.logger.error("\n\n")
        finally:
            self.logger.log_outro()

    def _log_nesting_issue(self, issue: Dict[str, Any]) -> None:
        parent = issue["parent"]
        nested = issue["nested"]
        nesting_type = issue["type"].replace("_", " ").title()

        self.logger.info(f"  [{nesting_type}]")
        self.logger.info(
            f"    Parent: {parent['title']} ({parent.get('year', '?')})"
            f" — {parent['instance']} — {parent['path']}"
        )
        self.logger.info(
            f"    Nested: {nested['title']} ({nested.get('year', '?')})"
            f" — {nested['instance']} — {nested['path']}"
        )
        self.logger.info(
            f"    Suggested fix: move to {issue.get('suggested_path', '?')}"
        )
        self.logger.info("")

    @staticmethod
    def scan_instances(
        instances_config, logger, db=None, instance_filter: Optional[List[str]] = None,
        library_mappings=None, path_mapping=None,
    ) -> List[Dict[str, Any]]:
        """
        Static scan method for use by the API layer.
        Returns a list of all issues (unmatched + nesting + filesystem).
        """
        scanner = _NestScanner(
            instances_config, logger, db=db,
            instance_filter=instance_filter,
            library_mappings=library_mappings,
            path_mapping=path_mapping,
        )
        return scanner.scan()
