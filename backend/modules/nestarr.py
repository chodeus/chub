# modules/nestarr.py

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.util.arr import create_arr_client, normalize_arr_media
from backend.util.base_module import ChubModule
from backend.util.connector import Connector
from backend.util.database import ChubDB
from backend.util.helper import create_table, print_settings, progress
from backend.util.logger import Logger
from backend.util.notification import NotificationManager
from backend.util.plex_refresh import walk_plex_libraries

SCAN_TYPE = "nestarr"


def _scan_cache_db(db: ChubDB):
    return db.media


def nestarr_config_fingerprint(nestarr_config: Any) -> str:
    """Return a stable fingerprint for settings that affect Nestarr results."""
    if hasattr(nestarr_config, "model_dump"):
        raw = nestarr_config.model_dump(mode="python")
    elif isinstance(nestarr_config, dict):
        raw = nestarr_config
    else:
        raw = {}
    payload = json.dumps(raw, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def save_scan_results(
    db: ChubDB,
    issues: list,
    instances_checked: list,
    logger=None,
    config_hash: Optional[str] = None,
    warnings: Optional[List[str]] = None,
) -> None:
    """Persist Nestarr scan results to the scan_cache table so both the
    module run path and the UI scan endpoint hydrate the same cache."""
    try:
        scanned_at = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(
            {
                "issues": issues,
                "total": len(issues),
                "instances_checked": instances_checked,
                "config_hash": config_hash,
                "warnings": warnings or [],
            },
            default=str,
        )
        _scan_cache_db(db).execute_query(
            "INSERT OR REPLACE INTO scan_cache (scan_type, data, scanned_at) VALUES (?, ?, ?)",
            (SCAN_TYPE, payload, scanned_at),
        )
        if logger:
            logger.debug(f"Saved {len(issues)} scan results to cache")
    except Exception as e:
        if logger:
            logger.error(f"Failed to save scan cache: {e}")


def load_scan_results(db: ChubDB, logger=None) -> Optional[Dict[str, Any]]:
    try:
        row = _scan_cache_db(db).execute_query(
            "SELECT data, scanned_at FROM scan_cache WHERE scan_type = ?",
            (SCAN_TYPE,),
            fetch_one=True,
        )
        if row and row.get("data"):
            result = json.loads(row["data"])
            result["scanned_at"] = row.get("scanned_at")
            return result
    except Exception as e:
        if logger:
            logger.error(f"Failed to load scan cache: {e}")
    return None


def clear_scan_results(db: ChubDB, logger=None) -> None:
    """Remove cached Nestarr scan results after config or filesystem changes."""
    try:
        _scan_cache_db(db).execute_query(
            "DELETE FROM scan_cache WHERE scan_type = ?",
            (SCAN_TYPE,),
        )
        if logger:
            logger.debug("Cleared Nestarr scan cache")
    except Exception as e:
        if logger:
            logger.error(f"Failed to clear scan cache: {e}")


def enabled_arr_instances(instances_config) -> List[str]:
    found = set()
    for inst_type in ("radarr", "sonarr", "lidarr"):
        for name, info in getattr(instances_config, inst_type, {}).items():
            if info.enabled:
                found.add(name)
    return sorted(found)


class _NestScanner:
    """
    Scans for media mismatches and path nesting:

    Phase 1 — Live comparison: finds media in ARR but not in Plex (and vice
    versa) by matching live ARR items against a fresh walk of the mapped Plex libraries.

    Phase 2 — Path nesting: detects tracked media items whose paths are
    nested inside other tracked media items.
    """

    VIDEO_EXTS = frozenset(
        {".mkv", ".mp4", ".avi", ".m4v", ".wmv", ".ts", ".m2ts", ".mov", ".mpg", ".mpeg",
         ".webm", ".vob", ".iso", ".flv", ".ogm", ".divx", ".xvid", ".3gp", ".asf", ".wtv"}
    )
    # Folders and files Sonarr's disk scan skips (DiskScanService), so never "untracked"
    SKIPPED_DIR_RE = re.compile(
        r"^(?:extras|extrafanart|behind the scenes|deleted scenes|featurettes|interviews"
        r"|other|scenes|samples|shorts|trailers|theme[-_. ]music|backdrops|@eadir"
        r"|plex versions|\..+)$",
        re.IGNORECASE,
    )
    SKIPPED_FILE_RE = re.compile(
        r"^\.(?:_|unmanic|DS_Store$)|^Thumbs\.db$"
        r"|-(?:trailer|other|behindthescenes|deleted|featurette|interview|scene|short)\.[^.]+$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        instances_config,
        logger,
        db=None,
        instance_filter=None,
        library_mappings=None,
        path_mapping=None,
    ):
        self.instances_config = instances_config
        self.logger = logger
        self.db = db
        self.instance_filter = instance_filter
        self.library_mappings = library_mappings
        self.path_mapping = path_mapping or []
        self.warnings: List[str] = []
        self._unread_folders: List[str] = []
        self._cancelled = lambda: False

    def set_cancel_check(self, fn):
        self._cancelled = fn

    def _warn(self, message: str) -> None:
        self.warnings.append(message)
        self.logger.warning(message)

    def scan(self) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        radarr_media: List[Dict[str, Any]] = []
        sonarr_media: List[Dict[str, Any]] = []
        lidarr_media: List[Dict[str, Any]] = []
        # Phase 1 inputs: normalized live rows per mapped instance, and the pulls that failed
        arr_rows: Dict[str, List[Dict[str, Any]]] = {}
        loaded_instances: set = set()
        failed_instances: set = set()

        arr_to_libraries, mapped_libraries = self._build_mapping_lookups()

        # Derive effective instance filter from valid library_mappings if configured
        effective_filter = self.instance_filter
        if self.library_mappings and not effective_filter:
            if mapped_libraries:
                effective_filter = sorted(arr_to_libraries.keys())
            else:
                self.logger.warning(
                    "[Phase 1] Ignoring library_mappings because no valid Plex "
                    "libraries were configured."
                )

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
                    failed_instances.add(instance_name)
                    continue

                raw_media = app.get_media()
                if raw_media is None:
                    self.logger.warning(
                        f"[{instance_type}] '{instance_name}': could not load media."
                    )
                    failed_instances.add(instance_name)
                    continue
                loaded_instances.add(instance_name)
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
                        "path"
                        if "path" in sample
                        else "folderPath"
                        if "folderPath" in sample
                        else "MISSING"
                    )
                    self.logger.debug(
                        f"[{instance_type}] '{instance_name}': "
                        f"path field='{path_field}', "
                        f"sample path='{sample.get('path') or sample.get('folderPath', 'N/A')}', "
                        f"rootFolderPath='{sample.get('rootFolderPath', 'N/A')}'"
                    )

                file_paths = self._file_paths_by_item(app, instance_type, raw_media)
                unknown = sum(1 for paths in file_paths.values() if paths is None)
                if unknown:
                    self._warn(
                        f"File check skipped for {unknown} item(s) in {instance_name}: "
                        "their file records could not be loaded."
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
                    if instance_name in arr_to_libraries:
                        row = normalize_arr_media(item, [], arr_type=instance_type)
                        row.update(
                            instance_name=instance_name,
                            instance_type=instance_type,
                            has_file=has_file,
                        )
                        arr_rows.setdefault(instance_name, []).append(row)
                    media_items.append(
                        {
                            "media_id": item.get("id"),
                            "title": item.get("title", "Unknown"),
                            "year": item.get("year"),
                            "path": normed,
                            "root_folder": item.get("rootFolderPath") or "",
                            "instance_type": instance_type,
                            "instance_name": instance_name,
                            "has_file": has_file,
                            "file_paths": file_paths.get(item.get("id")),
                        }
                    )

                if instance_type == "radarr":
                    radarr_media.extend(media_items)
                elif instance_type == "sonarr":
                    sonarr_media.extend(media_items)
                elif instance_type == "lidarr":
                    lidarr_media.extend(media_items)

        # Phase 1: Live comparison — ARR vs Plex.
        # Opt-in only: runs when valid library_mappings scope the comparison
        # to specific Plex libraries. Without that scope the diff would flag
        # the entire library as unmatched, so it stays off until configured.
        if self.db and not self._cancelled():
            if mapped_libraries:
                issues.extend(
                    self._detect_unmatched(arr_rows, loaded_instances, failed_instances)
                )
            else:
                self.logger.info(
                    "[Phase 1] Skipping ARR/Plex unmatched comparison — no "
                    "valid library_mappings configured. Add library mappings "
                    "in Nestarr settings to enable unmatched detection."
                )

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
            issues.extend(
                self._cross_check(lidarr_media, radarr_media, "artist_in_movie")
            )
        if lidarr_media and not self._cancelled():
            issues.extend(
                self._cross_check(radarr_media, lidarr_media, "movie_in_artist")
            )
        if lidarr_media and not self._cancelled():
            issues.extend(
                self._cross_check(lidarr_media, sonarr_media, "artist_in_series")
            )
        if lidarr_media and not self._cancelled():
            issues.extend(
                self._cross_check(sonarr_media, lidarr_media, "series_in_artist")
            )

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
    # Phase 1: Live comparison — ARR media vs Plex media
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

        for mapping in self.library_mappings or []:
            arr_inst = (
                getattr(mapping, "arr_instance", None)
                if hasattr(mapping, "arr_instance")
                else mapping.get("arr_instance", "")
            )
            if isinstance(arr_inst, str):
                arr_inst = arr_inst.strip()
            if not arr_inst:
                continue

            plex_instances = (
                getattr(mapping, "plex_instances", [])
                if hasattr(mapping, "plex_instances")
                else mapping.get("plex_instances", [])
            ) or []

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
                        pair = (inst.strip(), lib_name.strip())
                        arr_to_libraries.setdefault(arr_inst, set())
                        arr_to_libraries[arr_inst].add(pair)
                        mapped_libraries.add(pair)

        return arr_to_libraries, mapped_libraries

    def _detect_unmatched(
        self,
        arr_rows: Dict[str, List[Dict[str, Any]]],
        loaded_instances: set,
        failed_instances: set,
    ) -> List[Dict[str, Any]]:
        """Match live ARR rows against a fresh walk of their mapped Plex libraries, both ways."""
        issues: List[Dict[str, Any]] = []
        arr_to_libraries, mapped_libraries = self._build_mapping_lookups()

        libraries_by_plex: Dict[str, List[str]] = {}
        for plex_inst, lib_name in sorted(mapped_libraries):
            libraries_by_plex.setdefault(plex_inst, []).append(lib_name)
        try:
            usable = walk_plex_libraries(self.db, self.logger, libraries_by_plex)
        except Exception as e:
            self.logger.error(f"[Phase 1] Plex walk failed: {e}")
            usable = set()
        for plex_inst, lib_name in sorted(mapped_libraries - usable):
            self._warn(
                f"Unmatched check skipped for {plex_inst}/{lib_name}: "
                "Plex could not be refreshed."
            )
        # A library whose ARR pull failed would report every Plex item as "Not in ARR"
        for arr_inst in sorted(failed_instances & arr_to_libraries.keys()):
            for plex_inst, lib_name in sorted(arr_to_libraries[arr_inst] & usable):
                self._warn(
                    f"Unmatched check skipped for {plex_inst}/{lib_name}: "
                    f"{arr_inst} could not be loaded."
                )
            usable -= arr_to_libraries[arr_inst]
        if not usable or self._cancelled():
            return issues

        plex_rows = [
            row
            for row in self.db.plex.get_all()
            if (row.get("instance_name"), row.get("library_name")) in usable
        ]
        # logger=None keeps the matcher's per-item lines out of the Nestarr log
        matcher = Connector(db=self.db, logger=None, instance_map={})
        live_instances = loaded_instances & arr_to_libraries.keys()
        indexes: Dict[frozenset, tuple] = {}
        referenced: set = set()
        arr_matched = 0

        for arr_inst in sorted(live_instances):
            libs = frozenset(arr_to_libraries[arr_inst] & usable)
            if not libs:
                continue
            if libs not in indexes:
                candidates = [
                    row
                    for row in plex_rows
                    if (row.get("instance_name"), row.get("library_name")) in libs
                ]
                indexes[libs] = (candidates, matcher._prepare_plex_index(candidates))
            candidates, index = indexes[libs]
            for row in arr_rows.get(arr_inst, []):
                if self._cancelled():
                    return issues
                plex_row_id = matcher._find_plex_match(row, candidates, index)
                if plex_row_id is not None:
                    referenced.add(plex_row_id)
                    arr_matched += 1
                elif row.get("has_file"):  # no file yet = can't be in Plex
                    issues.append(self._arr_not_in_plex_issue(row))

        # Instances not pulled live still own Plex items: count their stored links too
        referenced.update(
            row["plex_mapping_id"]
            for row in self.db.media.get_all()
            if row.get("plex_mapping_id") is not None
            and row.get("instance_name") not in live_instances
        )

        arr_unmatched = len(issues)
        for plex_item in plex_rows:
            if plex_item.get("id") in referenced:
                continue
            if plex_item.get("season_number") is not None:
                continue
            issues.append(self._plex_not_in_arr_issue(plex_item))

        self.logger.debug(
            f"[Phase 1] ARR→Plex: {arr_matched} matched, {arr_unmatched} unmatched; "
            f"Plex→ARR: {len(issues) - arr_unmatched} unmatched "
            f"across {len(usable)} refreshed libraries"
        )
        return issues

    def _arr_not_in_plex_issue(self, row: Dict[str, Any]) -> Dict[str, Any]:
        instance_name = row.get("instance_name", "unknown")
        self.logger.debug(
            f"  [ARR→Plex] UNMATCHED: {instance_name} "
            f"'{row.get('title', '?')}' ({row.get('year', '?')}) "
            f"arr_id={row.get('arr_id')}"
        )
        return {
            "id": f"arr_unmatched_{instance_name}_{row.get('arr_id')}".replace(" ", "_"),
            "type": "arr_not_in_plex",
            "name": row.get("title") or "Unknown",
            "year": row.get("year"),
            "path": row.get("folder", ""),
            "instance": instance_name,
            "instance_type": row.get("instance_type", ""),
            "parent": None,
            "nested": None,
            "suggested_path": None,
            "suggested_action": "review",
        }

    def _plex_not_in_arr_issue(self, plex_item: Dict[str, Any]) -> Dict[str, Any]:
        instance_name = plex_item.get("instance_name", "unknown")
        row_id = plex_item.get("id")
        self.logger.debug(
            f"  [Plex→ARR] UNMATCHED: {instance_name} "
            f"[{plex_item.get('library_name', '?')}] "
            f"'{plex_item.get('title', '?')}' ({plex_item.get('year', '?')}) "
            f"plex_id={plex_item.get('plex_id', '?')} (cache row {row_id})"
        )
        return {
            "id": f"plex_unmatched_{instance_name}_{row_id}".replace(" ", "_"),
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
        }

    # ------------------------------------------------------------------
    # Phase 2: Path nesting among tracked items
    # ------------------------------------------------------------------

    @staticmethod
    def _is_nested_path(child_path: str, parent_path: str) -> bool:
        return _NestScanner._is_nested_norm(
            _NestScanner._norm(child_path), _NestScanner._norm(parent_path)
        )

    @staticmethod
    def _norm(path: str) -> str:
        """normpath that also collapses the "//" it keeps, so both sides agree."""
        norm = os.path.normpath(path)
        if norm.startswith("//") and not norm.startswith("///"):
            return norm[1:]
        return norm

    @staticmethod
    def _is_nested_norm(child_norm: str, parent_norm: str) -> bool:
        """Nesting test over `_norm` output; never normalise here (O(n^2) callers)."""
        if child_norm == parent_norm:
            return False
        # rstrip: a "/" parent must become "/", not "//"
        return child_norm.startswith(parent_norm.rstrip(os.sep) + os.sep)

    def _detect_nesting(
        self, media_list: List[Dict[str, Any]], media_type: str
    ) -> List[Dict[str, Any]]:
        if len(media_list) < 2:
            return []

        # Sort on the normalised path: the loop only takes earlier entries as parents.
        paired = sorted(
            ((_NestScanner._norm(m["path"]), m) for m in media_list),
            key=lambda pair: pair[0],
        )
        norms = [norm for norm, _ in paired]
        sorted_media = [m for _, m in paired]
        issues: List[Dict[str, Any]] = []

        self.logger.debug(
            f"[Phase 2] Nesting check ({media_type}): {len(sorted_media)} items"
        )
        # Log first few paths for context
        for sample in sorted_media[:5]:
            self.logger.debug(
                f"  {sample['instance_name']}: '{sample['title']}' → {sample['path']}"
            )
        if len(sorted_media) > 5:
            self.logger.debug(f"  ... and {len(sorted_media) - 5} more")

        for child_index, child in enumerate(sorted_media):
            best_parent = None
            child_norm = norms[child_index]
            for parent_index in range(child_index):
                if not self._is_nested_norm(child_norm, norms[parent_index]):
                    continue
                parent = sorted_media[parent_index]
                if best_parent is None or len(parent["path"]) > len(
                    best_parent["path"]
                ):
                    best_parent = parent
            if best_parent is None:
                continue

            nesting_type = {
                "movie": "movie_in_movie",
                "series": "series_in_series",
                "artist": "artist_in_artist",
            }.get(media_type, f"{media_type}_in_{media_type}")
            self.logger.debug(
                f"  [NESTED] {nesting_type}: "
                f"'{child['title']}' ({child['instance_name']}) "
                f"is inside '{best_parent['title']}' ({best_parent['instance_name']})"
            )
            self.logger.debug(f"    parent: {best_parent['path']}")
            self.logger.debug(f"    child:  {child['path']}")
            issues.append(self._build_nesting_issue(child, best_parent, nesting_type))

        self.logger.debug(f"[Phase 2] {media_type} nesting: {len(issues)} issues found")

        return issues

    def _detect_cross_nesting(
        self,
        radarr_media: List[Dict[str, Any]],
        sonarr_media: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        issues.extend(self._cross_check(radarr_media, sonarr_media, "movie_in_series"))
        issues.extend(self._cross_check(sonarr_media, radarr_media, "series_in_movie"))
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
        parent_norms = [_NestScanner._norm(p["path"]) for p in parents]

        for child in children:
            best_parent = None
            child_norm = _NestScanner._norm(child["path"])
            for parent, parent_norm in zip(parents, parent_norms):
                if not self._is_nested_norm(child_norm, parent_norm):
                    continue
                if best_parent is None or len(parent["path"]) > len(
                    best_parent["path"]
                ):
                    best_parent = parent
            if best_parent is None:
                continue

            self.logger.debug(
                f"  [CROSS-NESTED] {nesting_type}: "
                f"'{child['title']}' ({child['instance_name']}) "
                f"inside '{best_parent['title']}' ({best_parent['instance_name']})"
            )
            issues.append(self._build_nesting_issue(child, best_parent, nesting_type))

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
        candidates = []
        for mapping in self.path_mapping:
            arr_prefix = (
                mapping.get("arr_path", "")
                if isinstance(mapping, dict)
                else getattr(mapping, "arr_path", "")
            )
            local_prefix = (
                mapping.get("local_path", "")
                if isinstance(mapping, dict)
                else getattr(mapping, "local_path", "")
            )
            if not arr_prefix or not local_prefix:
                continue
            arr_prefix = os.path.normpath(arr_prefix)
            local_prefix = os.path.normpath(local_prefix)
            if self._is_same_or_child_path(path, arr_prefix):
                candidates.append((arr_prefix, local_prefix))
        if candidates:
            arr_prefix, local_prefix = max(candidates, key=lambda item: len(item[0]))
            remainder = os.path.relpath(os.path.normpath(path), arr_prefix)
            return (
                local_prefix
                if remainder == "."
                else os.path.join(local_prefix, remainder)
            )
        return path

    @staticmethod
    def _is_same_or_child_path(path: str, prefix: str) -> bool:
        path_norm = os.path.normpath(path)
        prefix_norm = os.path.normpath(prefix)
        if path_norm == prefix_norm:
            return True
        try:
            return os.path.commonpath([path_norm, prefix_norm]) == prefix_norm
        except ValueError:
            return False

    def _is_video_file(self, filename: str) -> bool:
        return os.path.splitext(filename)[1].lower() in self.VIDEO_EXTS

    @staticmethod
    def _normalize_fs_name(name: str) -> str:
        """Normalize a folder/file basename for cross-source comparison.

        ARR-API paths are typically NFC while os.listdir() can return NFD on
        some filesystems, so a byte-for-byte `==` flags accented or
        special-character folders as stray even when ARR tracks them. NFC +
        whitespace trim makes the two comparable.
        """
        return unicodedata.normalize("NFC", name).strip()

    @staticmethod
    def _path_key(path: str) -> str:
        """normpath + NFC, so an NFD name on disk equals the NFC path the ARR API returns."""
        return unicodedata.normalize("NFC", os.path.normpath(path))

    def _file_paths_by_item(self, app, instance_type: str, raw_media: list) -> Dict[Any, Any]:
        """ARR file-record paths per media id; None or absent means unknown (file check skipped)."""

        def record_paths(records):
            if not isinstance(records, list):
                return None
            return [r.get("path") for r in records if isinstance(r, dict) and r.get("path")]

        def visible(item):
            # Only folders Phase 3 can walk are worth a request
            path = item.get("path") or item.get("folderPath") or ""
            return bool(path) and os.path.isdir(self._translate_path(path))

        if instance_type == "sonarr":
            ids = [
                item["id"]
                for item in raw_media
                if item.get("id") is not None and visible(item)
            ]
            fetched = app.get_episode_files_by_series(ids) if ids else {}
            return {sid: record_paths(records) for sid, records in fetched.items()}
        if instance_type != "radarr":
            return {}
        paths: Dict[Any, Any] = {}
        for item in raw_media:
            movie_file = item.get("movieFile") or {}
            if movie_file.get("path"):
                paths[item.get("id")] = [movie_file["path"]]
            elif item.get("hasFile") and item.get("id") is not None and visible(item):
                paths[item["id"]] = record_paths(app.get_movie_data(item["id"]))
            elif not item.get("hasFile"):
                paths[item.get("id")] = []
        return paths

    def _detect_file_mismatches(self, item: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Compare a tracked folder's video files with the ARR's file records, both ways."""
        records = item.get("file_paths")
        local_folder = self._translate_path(item["path"])
        if records is None or not os.path.isdir(local_folder):
            return []

        walk_errors: List[OSError] = []
        present: set = set()
        scannable: Dict[str, str] = {}
        for dirpath, _dirnames, filenames in os.walk(
            local_folder, onerror=walk_errors.append
        ):
            relative_dir = os.path.relpath(dirpath, local_folder)
            skipped_dir = relative_dir != "." and any(
                self.SKIPPED_DIR_RE.match(part) for part in relative_dir.split(os.sep)
            )
            for name in filenames:
                full = os.path.join(dirpath, name)
                key = self._path_key(full)
                present.add(key)
                if skipped_dir or self.SKIPPED_FILE_RE.search(name):
                    continue
                if self._is_video_file(name):
                    scannable[key] = os.path.relpath(full, local_folder)
        if walk_errors:
            # A partial walk would report every unread file as missing
            self.logger.debug(
                f"[Phase 3] Skipping file check for {item['path']}: {walk_errors[0]}"
            )
            self._unread_folders.append(item["path"])
            return []

        tracked = {
            self._path_key(self._translate_path(record)): record for record in records
        }
        untracked = sorted(rel for key, rel in scannable.items() if key not in tracked)
        missing = sorted(
            os.path.relpath(record, item["path"])
            for key, record in tracked.items()
            if key not in present and not os.path.exists(self._translate_path(record))
        )

        issue_key = f"{item['instance_name']}_{item['media_id']}".replace(" ", "_")
        base = {
            "name": item["title"],
            "year": item.get("year"),
            "path": item["path"],
            "root_folder": item["root_folder"],
            "instance": item["instance_name"],
            "instance_type": item["instance_type"],
            "parent": {
                "title": item["title"],
                "year": item.get("year"),
                "path": item["path"],
                "media_id": item["media_id"],
                "instance": item["instance_name"],
                "instance_type": item["instance_type"],
            },
            "nested": None,
            "suggested_path": None,
            "suggested_action": "review",
        }
        issues: List[Dict[str, Any]] = []
        if untracked:
            self.logger.debug(f"  [UNTRACKED VIDEO] {item['path']}: {untracked}")
            issues.append(
                {
                    **base,
                    "id": f"extra_video_{issue_key}",
                    "type": "extra_video_in_folder",
                    "video_files": untracked,
                }
            )
        if missing:
            self.logger.debug(f"  [MISSING FILE] {item['path']}: {missing}")
            issues.append(
                {
                    **base,
                    "id": f"missing_file_{issue_key}",
                    "type": "missing_file",
                    "missing_files": missing,
                }
            )
        return issues

    def _detect_stray_files(
        self, media_by_type: Dict[str, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """
        Phase 3: Walk ARR root folders on the filesystem and detect:
        - Directories not tracked by any media item (stray_folder)
        - Video files sitting directly in a root folder (stray_file)
        - Video files in a tracked movie/series folder the ARR has no record of (extra_video_in_folder)
        - ARR file records whose file is gone from disk (missing_file)
        """
        issues: List[Dict[str, Any]] = []

        for media_type, media_items in media_by_type.items():
            if self._cancelled() or not media_items:
                continue

            # Group items by root folder
            root_to_items: Dict[str, List[Dict[str, Any]]] = {}
            for item in media_items:
                raw_root = item.get("root_folder") or ""
                if not raw_root:
                    self.logger.warning(
                        f"[Phase 3] Skipping '{item.get('title', 'Unknown')}' "
                        "because ARR did not provide rootFolderPath."
                    )
                    continue
                root = os.path.normpath(raw_root)
                root_to_items.setdefault(root, []).append(item)

            for arr_root, items_in_root in root_to_items.items():
                if self._cancelled():
                    break

                local_root = self._translate_path(arr_root)

                if not os.path.isdir(local_root):
                    self.logger.debug(
                        f"[Phase 3] Root folder not accessible: {arr_root}"
                        + (
                            f" (translated to {local_root})"
                            if local_root != arr_root
                            else ""
                        )
                        + " — skipping filesystem scan"
                    )
                    continue

                # Build set of expected folder basenames for this root
                expected_folders = set()
                for item in items_in_root:
                    basename = self._normalize_fs_name(os.path.basename(item["path"]))
                    expected_folders.add(basename)

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
                        if self._normalize_fs_name(child) not in expected_folders:
                            stray_count += 1
                            # Map back to ARR path for display
                            arr_child_path = os.path.join(arr_root, child)
                            issue_key = f"{media_type}|folder|{arr_child_path}"
                            digest = hashlib.sha1(issue_key.encode("utf-8")).hexdigest()
                            issue_id = (f"stray_{media_type}_{digest[:12]}").replace(
                                " ", "_"
                            )
                            self.logger.debug(f"  [STRAY FOLDER] {arr_child_path}")
                            issues.append(
                                {
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
                                }
                            )
                    elif os.path.isfile(child_path) and self._is_video_file(child):
                        stray_count += 1
                        arr_child_path = os.path.join(arr_root, child)
                        issue_key = f"{media_type}|file|{arr_child_path}"
                        digest = hashlib.sha1(issue_key.encode("utf-8")).hexdigest()
                        issue_id = f"stray_file_{media_type}_{digest[:12]}".replace(
                            " ", "_"
                        )
                        self.logger.debug(f"  [STRAY FILE] {arr_child_path}")
                        issues.append(
                            {
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
                            }
                        )

                if media_type in ("movie", "series"):
                    for item in items_in_root:
                        if self._cancelled():
                            break
                        found = self._detect_file_mismatches(item)
                        stray_count += len(found)
                        issues.extend(found)

                self.logger.debug(f"[Phase 3] {arr_root}: {stray_count} issues found")

        if self._unread_folders:
            self._warn(
                f"File check skipped for {len(self._unread_folders)} folder(s) CHUB "
                f"could not fully read, e.g. {self._unread_folders[0]}."
            )
        self.logger.debug(f"[Phase 3] Total filesystem issues: {len(issues)}")
        return issues

    @staticmethod
    def _build_nesting_issue(
        child: Dict[str, Any], parent: Dict[str, Any], nesting_type: str
    ) -> Dict[str, Any]:
        nested_folder = os.path.basename(child["path"])
        root = child.get("root_folder") or ""
        suggested_path = (
            os.path.join(os.path.normpath(root), nested_folder) if root else None
        )

        issue_key = (
            f"{nesting_type}|{child['instance_type']}|{child['instance_name']}|"
            f"{child['media_id']}|{parent['instance_type']}|{parent['instance_name']}|"
            f"{parent['media_id']}|{child['path']}|{parent['path']}"
        )
        digest = hashlib.sha1(issue_key.encode("utf-8")).hexdigest()
        issue_id = (
            f"{nesting_type}_{child['instance_name']}_{child['media_id']}_{digest[:10]}"
        ).replace(" ", "_")

        return {
            "id": issue_id,
            "type": nesting_type,
            "path": child["path"],
            "name": child["title"],
            "root_folder": child["root_folder"],
            "instance": child["instance_name"],
            "instance_type": child["instance_type"],
            "suggested_action": "move" if suggested_path else "review",
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

            with ChubDB(logger=self.logger, quiet=True) as db:
                scanner = _NestScanner(
                    self.full_config.instances,
                    self.logger,
                    db=db,
                    instance_filter=self.config.instances
                    if not self.config.library_mappings
                    else None,
                    library_mappings=self.config.library_mappings
                    if self.config.library_mappings
                    else None,
                    path_mapping=self.config.path_mapping
                    if self.config.path_mapping
                    else None,
                )
                scanner.set_cancel_check(self.is_cancelled)

                self.logger.info("Scanning for unmatched and nested media...")
                self.logger.info("")
                all_issues = scanner.scan()

                if not self.is_cancelled():
                    save_scan_results(
                        db,
                        all_issues,
                        enabled_arr_instances(self.full_config.instances),
                        logger=self.logger,
                        config_hash=nestarr_config_fingerprint(self.config),
                        warnings=scanner.warnings,
                    )

            if self.is_cancelled():
                self.logger.info("Scan cancelled.")
                return

            if all_issues:
                # Tally by type
                FILESYSTEM_TYPES = {
                    "stray_folder",
                    "stray_file",
                    "extra_video_in_folder",
                    "missing_file",
                }
                UNMATCHED_TYPES = {"arr_not_in_plex", "plex_not_in_arr"}
                arr_not_in_plex = [
                    i for i in all_issues if i["type"] == "arr_not_in_plex"
                ]
                plex_not_in_arr = [
                    i for i in all_issues if i["type"] == "plex_not_in_arr"
                ]
                nesting_issues = [
                    i
                    for i in all_issues
                    if i["type"] not in UNMATCHED_TYPES
                    and i["type"] not in FILESYSTEM_TYPES
                ]
                filesystem_issues = [
                    i for i in all_issues if i["type"] in FILESYSTEM_TYPES
                ]

                summary = [["Issue Type", "Count"]]
                if arr_not_in_plex:
                    summary.append(["In ARR, Not in Plex", str(len(arr_not_in_plex))])
                if plex_not_in_arr:
                    summary.append(["In Plex, Not in ARR", str(len(plex_not_in_arr))])
                if nesting_issues:
                    summary.append(["Nested Media", str(len(nesting_issues))])
                if filesystem_issues:
                    summary.append(
                        ["Stray/Misplaced Files", str(len(filesystem_issues))]
                    )
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
                            lib = (
                                f" [{issue.get('library_name', '')}]"
                                if issue.get("library_name")
                                else ""
                            )
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
                            self.logger.info(f"  [{itype}] {name} — {path}")
                            self.logger.info(
                                f"    {len(files)} video file(s) {issue.get('instance')} has no record of: "
                                f"{', '.join(files)}"
                            )
                        elif issue["type"] == "missing_file":
                            files = issue.get("missing_files", [])
                            self.logger.info(f"  [{itype}] {name} — {path}")
                            self.logger.info(
                                f"    {len(files)} recorded file(s) not on disk: {', '.join(files)}"
                            )
                        else:
                            self.logger.info(f"  [{itype}] {path}")

                manager = NotificationManager(
                    self.full_config, self.logger, module_name="nestarr"
                )
                manager.send_notification(all_issues)
            elif scanner.warnings:
                self.logger.warning(
                    "No issues found, but some checks were skipped (see warnings above)."
                )
            else:
                self.logger.info("No unmatched or nesting issues found.")

        except KeyboardInterrupt:
            self.logger.info("Keyboard Interrupt detected. Exiting...")
            return
        except Exception:
            self.logger.error("\n\nAn error occurred:\n", exc_info=True)
            self.logger.error("\n\n")
            raise
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
        instances_config,
        logger,
        db=None,
        instance_filter: Optional[List[str]] = None,
        library_mappings=None,
        path_mapping=None,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Static scan method for use by the API layer.
        Returns (issues, warnings): unmatched + nesting + filesystem issues, and skipped checks.
        """
        scanner = _NestScanner(
            instances_config,
            logger,
            db=db,
            instance_filter=instance_filter,
            library_mappings=library_mappings,
            path_mapping=path_mapping,
        )
        return scanner.scan(), scanner.warnings
