"""
Plex Metadata scanner — shared utilities for Poster Cleanarr workflows.

Reads the local Plex SQLite database (copy) and walks the Metadata/
directory tree to produce per-media-item poster variant listings and
flat bloat lists. A thread-safe in-memory TTL cache avoids re-scanning
the filesystem on every API request.

Mounts assumed (see Unraid container volume mapping):
    /plex/  →  Plex Media Server/
    Structure:
        /plex/Plug-in Support/Databases/com.plexapp.plugins.library.db
        /plex/Metadata/{Movies,TV Shows}/<first_char>/<rest>.bundle/
            Uploads/posters/<hash>   ← candidates (no file extension)
            Contents/                ← Plex-managed, ignored

A poster file is "in use" if its filename (the bytes between the last /
and EOF) appears as the suffix of any artwork URL in the Plex DB — on
`metadata_items` (IN_USE_IMAGE_COLUMNS) or on `tags`
(TAG_IN_USE_IMAGE_COLUMNS, collection/people/genre art). Values look like
`upload://posters/<hash>` or `metadata://posters/<hash>`. Anything else in
Uploads/posters/ is bloat.

Public surface:
    get_plex_metadata_dir(plex_path) -> str
    get_in_use_hashes(db_path) -> Set[str]
    copy_plex_db(plex_path, dest) -> Optional[str]
    scan_bundles(plex_path, *, force=False) -> Dict
    bloat_flat_from_scan(scan) -> List[Dict]
    get_cached_scan(plex_path) -> Optional[Dict]
    get_cached_transcoder(plex_path) -> Optional[Dict]
    scan_transcoder_cache(plex_path, *, force=False) -> Dict
    invalidate_cache()
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

PLEX_DB_NAME = "com.plexapp.plugins.library.db"

# metadata_items columns that reference an *in-use* (currently-applied) image.
# Canonical list shared by every "what artwork is Plex actively using" scan so
# the bloat cleaner can't flag an applied image as deletable. The "new
# experience" UI added user_clear_logo_url + user_square_art_url; omitting them
# made the bloat scanner treat custom logos / square art as orphans.
IN_USE_IMAGE_COLUMNS = (
    "user_thumb_url",
    "user_art_url",
    "user_banner_url",
    "user_clear_logo_url",
    "user_square_art_url",
)

# `tags` columns holding user-set artwork for collections, people and genres.
# Modern Plex stores collections as metadata_items (metadata_type 18), already
# covered above; `tags` is where legacy collections (tag_type 2) and tag artwork
# live, so a custom collection/actor image referenced ONLY from here would
# otherwise scan as bloat and be deleted.
#
# Deliberately NOT protected (measured against a live 250k-tag library):
#   taggings.thumb_url          — 0 upload://, all metadata:// under Contents/,
#                                 which the bundle walk never scans anyway.
#   metadata_item_views.thumb_url — watch-history snapshots of what the artwork
#                                 WAS; protecting them would pin superseded
#                                 posters forever and defeat the cleaner.
TAG_IN_USE_IMAGE_COLUMNS = (
    "user_thumb_url",
    "user_art_url",
    "user_music_url",
)

_CACHE_TTL_SEC = 300  # 5 minutes
_cache_lock = threading.Lock()
_cache: Dict[str, Dict[str, Any]] = {}


def get_plex_metadata_dir(plex_path: str) -> str:
    """Return absolute path to Plex's Metadata/ directory."""
    return os.path.join(plex_path, "Metadata")


def copy_plex_db(plex_path: str, dest: str) -> Optional[str]:
    """
    Copy Plex's live SQLite DB to `dest` for read-only querying.
    Returns dest on success, None on failure. Safe when Plex is running —
    SQLite's WAL mode allows concurrent reads, but we still copy to avoid
    holding a lock for the duration of long queries.
    """
    src = os.path.join(plex_path, "Plug-in Support", "Databases", PLEX_DB_NAME)
    if not os.path.exists(src):
        return None
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
        return dest
    except Exception:
        return None


def get_in_use_hashes(db_path: str, logger: Any = None) -> Set[str]:
    """
    Extract the filenames currently referenced by any of IN_USE_IMAGE_COLUMNS on
    metadata_items, plus TAG_IN_USE_IMAGE_COLUMNS on tags (collection, people
    and genre artwork) — the images Plex is actively using. This is the single
    canonical "in-use" scan; both the API bloat report and poster_cleanarr use
    it, so the set of protected columns can't drift between them.

    Union-only by construction: adding a source can only ever protect more
    files, never mark more as bloat.

    `logger` is optional: when provided, per-column / DB errors are logged
    (poster_cleanarr wants this); otherwise failures are swallowed (the API
    scanner is best-effort and returns an empty set rather than 500ing).
    """
    in_use: Set[str] = set()
    try:
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()

            def _collect(table: str, columns: tuple) -> None:
                for col in columns:
                    try:
                        # fetchall() must stay inside this try: a read that
                        # fails after execute() succeeds would otherwise escape
                        # to the outer handler and truncate the protected set.
                        cur.execute(
                            f"SELECT {col} FROM {table} "
                            f"WHERE {col} LIKE 'upload://%' OR {col} LIKE 'metadata://%'"
                        )
                        for (value,) in cur.fetchall():
                            if not value:
                                continue
                            parsed = urlparse(value)
                            fname = (
                                parsed.path.rsplit("/", 1)[-1] if parsed.path else ""
                            )
                            if fname:
                                in_use.add(fname)
                    except sqlite3.OperationalError as e:
                        # Older Plex schemas may lack a column (e.g. the newer
                        # clear-logo/square-art ones) — skip it, don't abort.
                        if logger:
                            logger.warning(f"Failed to query {table}.{col}: {e}")
                        continue

            _collect("metadata_items", IN_USE_IMAGE_COLUMNS)

            # Collection / people / genre artwork. Probe first so the common
            # case of a schema without `tags` stays silent instead of logging a
            # warning per column.
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tags'"
            )
            if cur.fetchone():
                _collect("tags", TAG_IN_USE_IMAGE_COLUMNS)
        finally:
            conn.close()
    except Exception as e:
        # Scanner is best-effort: a corrupt/missing DB returns an empty
        # in-use set rather than crashing the API. Caller decides what to
        # do with zero results.
        if logger:
            logger.error(f"Failed to query Plex database: {e}")
    return in_use


def _load_metadata_item_index(db_path: str) -> Dict[str, Dict[str, Any]]:
    """
    Build a map of in-use filename → {id, title, year, type, library_section_id}.

    Walking the Metadata/ tree gives us every poster file on disk, but the
    bundle directory names are hashes we can't easily reverse. Instead, we
    use every item's active thumb/art/banner filename as an anchor: when
    we find that file on disk, we know the bundle it's in belongs to the
    matching metadata_item. All *other* files in the same bundle are that
    item's extra variants (bloat candidates).
    """
    index: Dict[str, Dict[str, Any]] = {}
    try:
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            # Anchor on EVERY in-use image column (the canonical
            # IN_USE_IMAGE_COLUMNS, same as get_in_use_hashes), not just
            # thumb/art/banner — otherwise an item whose only on-disk anchor is
            # a logo or square art is never matched and surfaces in the
            # cleanarr UI with empty title/year. Query each column separately so
            # an older Plex schema missing one skips it instead of dropping all.
            for col in IN_USE_IMAGE_COLUMNS:
                try:
                    cur.execute(
                        "SELECT id, title, year, metadata_type, "
                        f"library_section_id, {col} FROM metadata_items"
                    )
                    for item_id, title, year, mtype, section_id, url in cur.fetchall():
                        if not url:
                            continue
                        parsed = urlparse(url)
                        fname = parsed.path.rsplit("/", 1)[-1] if parsed.path else ""
                        if not fname:
                            continue
                        index[fname] = {
                            "id": item_id,
                            "title": title or "",
                            "year": year,
                            "metadata_type": mtype,
                            "library_section_id": section_id,
                        }
                except sqlite3.OperationalError:
                    # Older Plex schema lacks this column — skip it.
                    continue
        finally:
            conn.close()
    except Exception:
        # Same tolerance as get_in_use_hashes: empty index on DB failure,
        # which downstream treats as "titles unknown" not "error".
        pass
    return index


def _load_library_sections(db_path: str) -> Dict[int, Dict[str, Any]]:
    """Map library_section_id → {name, section_type}.

    Plex's `library_sections.section_type` is 1 (movie), 2 (show), 8 (artist),
    18 (photo). We only care about the name for UI display and whether it's a
    movie or show library for filtering.
    """
    sections: Dict[int, Dict[str, Any]] = {}
    try:
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            try:
                cur.execute("SELECT id, name, section_type FROM library_sections")
                for row in cur.fetchall():
                    sid, name, stype = row
                    sections[sid] = {"name": name or "", "section_type": stype}
            except sqlite3.OperationalError:
                # Older Plex schemas may be missing the section_type column —
                # return whatever rows we read so far.
                pass
        finally:
            conn.close()
    except Exception:
        # Same tolerance as get_in_use_hashes: empty sections map on DB
        # failure, which downstream treats as "library names unknown"
        # rather than propagating a 500.
        pass
    return sections


def build_bundle_section_map(db_path: str, metadata_dir: str) -> Dict[str, str]:
    """Map each on-disk ``.bundle`` directory to its owning Plex library NAME.

    Used by poster_cleanarr's library opt-out to drop bloat files that belong
    to an excluded library. Resolution mirrors ``scan_bundles``: a bundle is
    tagged with the library of the first of its files that matches an in-use
    anchor. Best-effort by design — a bundle whose files never anchor stays
    UNMAPPED (absent from the result), so the caller treats it as "library
    unknown" and, per the fail-open rule, does NOT exclude it. Keys are
    ``os.path.realpath``'d bundle dirs so they compare equal to the caller's
    resolved bloat-file bundle roots.

    NEVER used to build or narrow the in-use set — this only labels
    already-classified bloat candidates by library.
    """
    if not db_path or not metadata_dir:
        return {}
    anchor_index = _load_metadata_item_index(db_path)
    if not anchor_index:
        return {}
    sections = _load_library_sections(db_path)

    # Group every file by its enclosing .bundle dir (same walk shape as
    # scan_bundles), then resolve each bundle's library via an anchored file.
    bundle_files: Dict[str, List[str]] = {}
    for root, _dirs, files in os.walk(metadata_dir):
        bundle_root = root
        while bundle_root and not bundle_root.endswith(".bundle"):
            parent = os.path.dirname(bundle_root)
            if parent == bundle_root or len(parent) < len(metadata_dir):
                bundle_root = None
                break
            bundle_root = parent
        if not bundle_root:
            continue
        bundle_files.setdefault(bundle_root, []).extend(files)

    section_map: Dict[str, str] = {}
    for bundle_root, files in bundle_files.items():
        for fname in files:
            hit = anchor_index.get(fname)
            if not hit:
                continue
            sid = hit.get("library_section_id")
            sec = sections.get(sid) if sid is not None else None
            name = sec.get("name") if sec else None
            if name:
                section_map[os.path.realpath(bundle_root)] = name
            break
    return section_map


# Plex metadata_type enum (subset we care about).
METADATA_TYPE_LABELS = {
    1: "movie",
    2: "show",
    3: "season",
    4: "episode",
    8: "artist",
    9: "album",
    10: "track",
    18: "collection",
}

# Metadata types we skip wholesale — music libraries are walked by Plex but
# nobody uploads custom artwork for them, so including them bloats the scan
# payload with tens of thousands of bundles that the UI would only ever hide.
EXCLUDED_METADATA_TYPES = frozenset({8, 9, 10})


def _classify_variant_kind(path: str) -> str:
    """Heuristic classifier for a variant file path.

    Plex organizes per-item artwork under subdirectories that correlate
    with the kind: `Uploads/posters`, `Uploads/art`, `Uploads/banners`,
    `Contents/Posters`, `Contents/Art`, `Contents/Thumbnails`, etc.
    """
    p = path.lower()
    if "/posters/" in p or p.endswith("/posters"):
        return "poster"
    if "/art/" in p or p.endswith("/art"):
        return "art"
    if "/banners/" in p or "/banner/" in p or p.endswith("/banners"):
        return "banner"
    if "/thumbnails/" in p or "/thumbs/" in p:
        return "thumb"
    if "/chapterimages/" in p or "/chapterthumbs/" in p:
        return "chapter"
    if "/themes/" in p:
        return "theme"
    return "other"


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        entry = _cache.get(key)
        if entry and (time.time() - entry.get("_ts", 0)) < _CACHE_TTL_SEC:
            return entry
    return None


def _cache_put(key: str, value: Dict[str, Any]) -> None:
    with _cache_lock:
        value["_ts"] = time.time()
        _cache[key] = value


def invalidate_cache() -> None:
    """Clear all cached scans. Call after a cleanup job mutates the filesystem."""
    with _cache_lock:
        _cache.clear()


def scan_bundles(plex_path: str, *, force: bool = False) -> Dict[str, Any]:
    """
    Scan the Plex Metadata directory and group poster variants by media item.

    Returns {
        "bundles": [
            {
                "bundle_path": str,          # absolute path to .bundle dir
                "rating_key": int | None,    # metadata_items.id, if known
                "title": str,
                "year": int | None,
                "metadata_type": int | None, # 1=movie, 2=show
                "variants": [
                    {"filename": str, "path": str, "size": int, "active": bool},
                    ...
                ],
            },
            ...
        ],
        "stats": {
            "bundle_count": int,
            "variant_count": int,
            "bloat_count": int,
            "bloat_size": int,
            "scanned_at": float,    # unix ts
        }
    }

    Cached for _CACHE_TTL_SEC unless force=True.
    """
    cache_key = f"scan::{plex_path}"
    if not force:
        cached = _cache_get(cache_key)
        if cached:
            return cached

    metadata_dir = get_plex_metadata_dir(plex_path)
    if not os.path.isdir(metadata_dir):
        return {
            "bundles": [],
            "stats": {
                "bundle_count": 0,
                "variant_count": 0,
                "bloat_count": 0,
                "bloat_size": 0,
                "scanned_at": time.time(),
            },
        }

    # Take a quick copy of the DB so we don't contend with Plex.
    # The sibling-of-plex_path location used to live at `/.chub_plex_db` when
    # plex_path was `/plex`, which is unwritable by the CHUB user. Prefer
    # `$CONFIG_DIR/plex-cache` which is always on a writable mount.
    config_dir = os.environ.get("CONFIG_DIR") or "/config"
    working_dir = os.path.join(config_dir, "plex-cache")
    try:
        os.makedirs(working_dir, exist_ok=True)
    except OSError:
        # Fall back to a tempdir if /config isn't writable (dev/local runs).
        import tempfile

        working_dir = tempfile.mkdtemp(prefix="chub-plex-cache-")
    db_copy = os.path.join(working_dir, "plex_scan.db")
    db_path = copy_plex_db(plex_path, db_copy) or None

    in_use: Set[str] = get_in_use_hashes(db_path) if db_path else set()
    anchor_index = _load_metadata_item_index(db_path) if db_path else {}
    sections_index = _load_library_sections(db_path) if db_path else {}

    # Walk metadata_dir, grouping files by their enclosing .bundle directory.
    # Both `Uploads/` (user-uploaded, deletable) and `Contents/` (Plex-sourced,
    # read-only) are surfaced — the frontend uses the `source` tag to offer
    # delete/selection only on uploads and the active swap on both.
    # bundle_files[bundle_path] = [{filename, path, size, mtime, kind, source}, ...]
    bundle_files: Dict[str, List[Dict[str, Any]]] = {}
    for root, dirs, files in os.walk(metadata_dir):
        bundle_root = root
        while bundle_root and not bundle_root.endswith(".bundle"):
            parent = os.path.dirname(bundle_root)
            if parent == bundle_root or len(parent) < len(metadata_dir):
                bundle_root = None
                break
            bundle_root = parent
        if not bundle_root:
            continue
        # source flag — anything under `<bundle>/Contents/` is Plex-managed
        # and we refuse to let the API delete it; anything under `Uploads/`
        # (or elsewhere inside the bundle) is user-uploaded bloat candidate.
        is_contents = f"{os.sep}Contents{os.sep}" in (root + os.sep)
        source = "plex" if is_contents else "uploads"
        for fname in files:
            # Plex stores custom variants as extension-less hash names.
            # Contents/ files may carry extensions (jpg/png); accept both.
            if not is_contents and "." in fname:
                continue
            fpath = os.path.join(root, fname)
            try:
                st = os.stat(fpath)
                size = st.st_size
                mtime = st.st_mtime
            except OSError:
                size = 0
                mtime = 0.0
            bundle_files.setdefault(bundle_root, []).append(
                {
                    "filename": fname,
                    "path": fpath,
                    "size": size,
                    "mtime": mtime,
                    "kind": _classify_variant_kind(fpath),
                    "source": source,
                }
            )

    # Resolve each bundle's owning metadata_item by matching any of its files
    # against the anchor index (Plex's known active filenames).
    bundles: List[Dict[str, Any]] = []
    variant_count = 0
    bloat_count = 0
    bloat_size = 0

    for bundle_path, files in bundle_files.items():
        info: Dict[str, Any] = {
            "rating_key": None,
            "title": "",
            "year": None,
            "metadata_type": None,
            "library_section_id": None,
        }
        for f in files:
            hit = anchor_index.get(f["filename"])
            if hit:
                info = {
                    "rating_key": hit["id"],
                    "title": hit["title"],
                    "year": hit["year"],
                    "metadata_type": hit["metadata_type"],
                    "library_section_id": hit.get("library_section_id"),
                }
                break

        # Drop music bundles — the UI has no tab for them and people don't
        # upload custom posters for individual tracks/albums. Keeps the
        # payload to movies/shows/seasons/episodes/collections only.
        if info.get("metadata_type") in EXCLUDED_METADATA_TYPES:
            continue

        # Drop unanchored, non-actionable bundles. When no file in a bundle
        # matches an in-use anchor, `info` stays at its defaults (rating_key
        # None, title "" -> rendered "(unknown)", metadata_type None), so the
        # music-type guard above can't fire. These are almost always Plex's own
        # music/library defaults under Contents/ that never matched an in-use
        # filename — they carry no deletable upload and can't be selected or
        # cleaned, so surfacing them is pure "(unknown)" clutter. An unanchored
        # bundle that DOES hold an uploads/ file is genuine orphaned bloat and
        # is kept so the user can still clean it.
        if info.get("rating_key") is None and not any(
            f["source"] == "uploads" for f in files
        ):
            continue

        variants = []
        for f in files:
            active = f["filename"] in in_use
            variants.append(
                {
                    "filename": f["filename"],
                    "path": f["path"],
                    "size": f["size"],
                    "mtime": f["mtime"],
                    "kind": f["kind"],
                    "source": f["source"],
                    "active": active,
                }
            )
            variant_count += 1
            # Plex-sourced variants are never bloat candidates — they're
            # read-only and can't be deleted through the cleanup pipeline.
            if not active and f["source"] != "plex":
                bloat_count += 1
                bloat_size += f["size"]

        # Tile order in the UI:
        #   1. Active variant(s)              — what Plex is currently using
        #   2. Bloat (user uploads), newest first by mtime
        #   3. Plex-sourced defaults          — read-only, pushed to the end
        def _variant_rank(v: Dict[str, Any]) -> tuple:
            if v["active"]:
                return (0, 0.0)
            if v.get("source") == "plex":
                return (2, 0.0)
            # Negate mtime so newest (largest mtime) comes first within bloat.
            return (1, -float(v.get("mtime") or 0))

        variants.sort(key=_variant_rank)
        mtype = info["metadata_type"]
        section_id = info["library_section_id"]
        section = sections_index.get(section_id) if section_id is not None else None
        bundles.append(
            {
                "bundle_path": bundle_path,
                "rating_key": info["rating_key"],
                "title": info["title"],
                "year": info["year"],
                "metadata_type": mtype,
                "metadata_type_label": METADATA_TYPE_LABELS.get(mtype)
                if mtype
                else None,
                "library_section_id": section_id,
                "library_name": section["name"] if section else None,
                "variants": variants,
            }
        )

    # Dedupe bundles that share a rating_key. Plex leaves orphaned .bundle
    # dirs on disk after metadata refreshes / agent changes, and the walk
    # above emits one row per directory — producing duplicate rows in the
    # UI (Avatar twice, Dunkirk twice, etc.). Collapse them by merging
    # their variants (deduped by path) under the canonical bundle: prefer
    # the path whose variants contain the currently-active one, else the
    # path with the most variants, else the lexicographically first path.
    if bundles:
        grouped: Dict[Any, List[Dict[str, Any]]] = {}
        ordered_keys: List[Any] = []
        for b in bundles:
            rk = b.get("rating_key")
            if rk is None:
                # Keep untyped/unmatched rows intact under a synthetic key
                # so they're never merged with each other.
                rk = ("__unmatched__", b["bundle_path"])
            if rk not in grouped:
                grouped[rk] = []
                ordered_keys.append(rk)
            grouped[rk].append(b)

        def _canonical_rank(b: Dict[str, Any]) -> tuple:
            has_active = any(v.get("active") for v in b["variants"])
            return (0 if has_active else 1, -len(b["variants"]), b["bundle_path"])

        deduped: List[Dict[str, Any]] = []
        for rk in ordered_keys:
            group = grouped[rk]
            if len(group) == 1:
                deduped.append(group[0])
                continue
            group.sort(key=_canonical_rank)
            canonical = group[0]
            seen_paths = {v["path"] for v in canonical["variants"]}
            merged_variants = list(canonical["variants"])
            for other in group[1:]:
                for v in other["variants"]:
                    if v["path"] not in seen_paths:
                        merged_variants.append(v)
                        seen_paths.add(v["path"])
            merged_variants.sort(key=_variant_rank)
            deduped.append({**canonical, "variants": merged_variants})
        bundles = deduped

    # Sort bundles alphabetically by title (case-insensitive). Untitled
    # bundles sort to the bottom so the list reads naturally in the UI.
    bundles.sort(key=lambda b: ((b["title"] or "\uffff").lower(), b.get("year") or 0))

    # Include libraries referenced by at least one bundle — lets the frontend
    # populate a filter dropdown without a second call.
    referenced_lib_ids = {
        b["library_section_id"] for b in bundles if b["library_section_id"]
    }
    libraries = [
        {
            "id": lib_id,
            "name": sections_index[lib_id]["name"],
            "section_type": sections_index[lib_id]["section_type"],
        }
        for lib_id in sorted(referenced_lib_ids)
        if lib_id in sections_index
    ]

    # Distinct media types + variant kinds present in this scan. Frontend
    # uses these to hide filter-dropdown options that would produce zero
    # results (e.g. hide "artist" when the user has no Lidarr library).
    present_media_types = sorted(
        {b["metadata_type_label"] for b in bundles if b.get("metadata_type_label")}
    )
    present_variant_kinds = sorted(
        {v["kind"] for b in bundles for v in b["variants"] if v.get("kind")}
    )

    result = {
        "bundles": bundles,
        "libraries": libraries,
        "media_types": present_media_types,
        "variant_kinds": present_variant_kinds,
        "stats": {
            "bundle_count": len(bundles),
            "variant_count": variant_count,
            "bloat_count": bloat_count,
            "bloat_size": bloat_size,
            "scanned_at": time.time(),
        },
    }
    # A failed Plex DB copy leaves in_use empty, so every poster on disk looks like
    # deletable bloat with a blank title. When that happens WITH posters present,
    # return an unavailable result and DON'T cache it: a transient DB blip must not
    # be negative-cached (the per-variant delete has no in-use guard, so a poisoned
    # cache could delete active artwork). An empty tree can't misclassify anything,
    # so it still caches normally.
    if db_path is None and bundles:
        return {
            "bundles": [],
            "libraries": [],
            "media_types": [],
            "variant_kinds": [],
            "unavailable": True,
            "reason": "Could not read Plex's database (it may be busy); run the scan again.",
            "stats": {
                "bundle_count": 0,
                "variant_count": 0,
                "bloat_count": 0,
                "bloat_size": 0,
                "scanned_at": time.time(),
            },
        }
    _cache_put(cache_key, result)
    return result


def bloat_flat_from_scan(scan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build the flat bloat list from a scan dict (the result of `scan_bundles`
    or `get_cached_scan`), sorted by size desc. Split out so the API can derive
    it from the cached scan without re-walking the filesystem."""
    flat: List[Dict[str, Any]] = []
    for b in scan["bundles"]:
        for v in b["variants"]:
            if v["active"]:
                continue
            # Plex-sourced variants are surfaced for display/swap only; they're
            # not deletable and so don't belong in the bloat-cleanup list.
            if v.get("source") == "plex":
                continue
            flat.append(
                {
                    "filename": v["filename"],
                    "path": v["path"],
                    "size": v["size"],
                    "bundle_path": b["bundle_path"],
                    "rating_key": b["rating_key"],
                    "title": b["title"],
                    "year": b["year"],
                }
            )
    flat.sort(key=lambda e: -e["size"])
    return flat


def scan_transcoder_cache(plex_path: str, *, force: bool = False) -> Dict[str, int]:
    """
    Walk `<plex>/Cache/PhotoTranscoder/` and report total file count + byte size.

    Read-only; the matching wipe lives in `plex_maintenance._clean_photo_transcoder`
    and is exposed through the Plex Maintenance module. This helper exists so the
    Poster Cleanarr UI can surface the reclaimable cache size next to its other
    scan stats without invoking the cleanup module just to peek at the disk usage.

    Returns {"count": int, "size_bytes": int}. Missing directory → zeros (not an
    error). Cached for `_CACHE_TTL_SEC` unless `force=True`.
    """
    cache_key = f"tcache::{plex_path}"
    if not force:
        cached = _cache_get(cache_key)
        if cached:
            return {"count": cached["count"], "size_bytes": cached["size_bytes"]}

    transcoder_dir = os.path.join(plex_path, "Cache", "PhotoTranscoder")
    count = 0
    size_bytes = 0
    if os.path.isdir(transcoder_dir):
        for root, _dirs, files in os.walk(transcoder_dir):
            for filename in files:
                fpath = os.path.join(root, filename)
                try:
                    size_bytes += os.path.getsize(fpath)
                    count += 1
                except OSError:
                    # File vanished or unreadable mid-walk — skip silently; this
                    # is a stat-only report, not a critical path.
                    continue

    result = {"count": count, "size_bytes": size_bytes}
    _cache_put(cache_key, result)
    return result


def get_cached_scan(plex_path: str) -> Optional[Dict[str, Any]]:
    """Return the cached `scan_bundles` result, or None if no fresh scan is
    cached. NEVER walks the filesystem — this is the read path for the API,
    which must not do a cold scan on the event loop. A background job warms the
    cache via `scan_bundles(force=True)`; the API only ever reads it here.
    """
    return _cache_get(f"scan::{plex_path}")


def get_cached_transcoder(plex_path: str) -> Optional[Dict[str, int]]:
    """Return the cached `scan_transcoder_cache` result, or None if unscanned.
    Walk-free companion to `get_cached_scan` (same cold-read contract)."""
    cached = _cache_get(f"tcache::{plex_path}")
    if not cached:
        return None
    return {"count": cached["count"], "size_bytes": cached["size_bytes"]}


def delete_variant(file_path: str, *, plex_path: str) -> bool:
    """
    Delete one variant file from disk.

    Refuses paths that:
    - resolve outside Plex's Metadata dir, or
    - sit under any `.bundle/Contents/` subtree (Plex-managed — deleting
      these would have no lasting effect because Plex re-downloads them
      from its metadata agents, and would pollute the scan cache).
    Returns True on success.
    """
    metadata_dir = os.path.realpath(get_plex_metadata_dir(plex_path))
    real = os.path.realpath(file_path)
    if not real.startswith(metadata_dir + os.sep):
        return False
    # Plex-sourced variants sit under `<bundle>/Contents/…`. Refuse.
    if f"{os.sep}Contents{os.sep}" in real:
        return False
    try:
        os.remove(real)
        invalidate_cache()
        return True
    except Exception:
        return False
