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
and EOF) appears as the suffix of any `metadata_items.user_thumb_url`
in the Plex DB (values look like `upload://posters/<hash>` or
`metadata://posters/<hash>`). Anything else in Uploads/posters/ is bloat.

Public surface:
    get_plex_metadata_dir(plex_path) -> str
    get_in_use_hashes(db_path) -> Set[str]
    copy_plex_db(plex_path, dest) -> Optional[str]
    scan_bundles(plex_path, *, force=False) -> Dict
    get_bloat_flat(plex_path, *, force=False) -> List[Dict]
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
_CACHE_TTL_SEC = 300  # 5 minutes
_cache_lock = threading.Lock()
_cache: Dict[str, Dict[str, Any]] = {}


def get_plex_metadata_dir(plex_path: str) -> str:
    """Return absolute path to Plex's Metadata/ directory."""
    return os.path.join(plex_path, "Metadata")


def _plex_is_running(plex_path: str) -> bool:
    db_dir = os.path.join(plex_path, "Plug-in Support", "Databases")
    return os.path.exists(os.path.join(db_dir, f"{PLEX_DB_NAME}-shm")) or os.path.exists(
        os.path.join(db_dir, f"{PLEX_DB_NAME}-wal")
    )


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


def get_in_use_hashes(db_path: str) -> Set[str]:
    """
    Extract filenames currently referenced by any metadata_items.{user_thumb_url,
    user_art_url, user_banner_url}. These are the files Plex is actively using.
    """
    in_use: Set[str] = set()
    try:
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            for col in ("user_thumb_url", "user_art_url", "user_banner_url"):
                try:
                    cur.execute(
                        f"SELECT {col} FROM metadata_items "
                        f"WHERE {col} LIKE 'upload://%' OR {col} LIKE 'metadata://%'"
                    )
                    for (value,) in cur.fetchall():
                        if not value:
                            continue
                        parsed = urlparse(value)
                        fname = parsed.path.rsplit("/", 1)[-1] if parsed.path else ""
                        if fname:
                            in_use.add(fname)
                except sqlite3.OperationalError:
                    continue
        finally:
            conn.close()
    except Exception:
        # Scanner is best-effort: a corrupt/missing DB returns an empty
        # in-use set rather than crashing the API. Caller decides what to
        # do with zero results.
        pass
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
            try:
                cur.execute(
                    "SELECT id, title, year, metadata_type, library_section_id, "
                    "user_thumb_url, user_art_url, user_banner_url FROM metadata_items"
                )
                for row in cur.fetchall():
                    item_id, title, year, mtype, section_id, thumb, art, banner = row
                    for url in (thumb, art, banner):
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
                # metadata_items may be missing some columns on older Plex
                # schemas — swallow and return whatever we have so far.
                pass
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
                pass
        finally:
            conn.close()
    except Exception:
        pass
    return sections


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
        return {"bundles": [], "stats": {"bundle_count": 0, "variant_count": 0, "bloat_count": 0, "bloat_size": 0, "scanned_at": time.time()}}

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

        # Sort: active variants first, then largest bloat first.
        variants.sort(key=lambda v: (not v["active"], -v["size"]))
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
                "metadata_type_label": METADATA_TYPE_LABELS.get(mtype) if mtype else None,
                "library_section_id": section_id,
                "library_name": section["name"] if section else None,
                "variants": variants,
            }
        )

    # Sort bundles alphabetically by title (case-insensitive). Untitled
    # bundles sort to the bottom so the list reads naturally in the UI.
    bundles.sort(key=lambda b: ((b["title"] or "\uffff").lower(), b.get("year") or 0))

    # Include libraries referenced by at least one bundle — lets the frontend
    # populate a filter dropdown without a second call.
    referenced_lib_ids = {b["library_section_id"] for b in bundles if b["library_section_id"]}
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
    present_media_types = sorted({b["metadata_type_label"] for b in bundles if b.get("metadata_type_label")})
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
    _cache_put(cache_key, result)
    return result


def get_bloat_flat(plex_path: str, *, force: bool = False) -> List[Dict[str, Any]]:
    """
    Return a flat list of bloat variants across all bundles, sorted by size desc.
    Each entry: {filename, path, size, bundle_path, rating_key, title, year}.
    """
    scan = scan_bundles(plex_path, force=force)
    flat: List[Dict[str, Any]] = []
    for b in scan["bundles"]:
        for v in b["variants"]:
            if v["active"]:
                continue
            # Plex-sourced variants are surfaced for display/swap only; they're
            # not deletable and so don't belong in the bloat-cleanup list.
            if v.get("source") == "plex":
                continue
            flat.append({
                "filename": v["filename"],
                "path": v["path"],
                "size": v["size"],
                "bundle_path": b["bundle_path"],
                "rating_key": b["rating_key"],
                "title": b["title"],
                "year": b["year"],
            })
    flat.sort(key=lambda e: -e["size"])
    return flat


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
