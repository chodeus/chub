# modules/poster_renamerr.py

import contextlib
import filecmp
import hashlib
import json
import os
import shutil
import tempfile
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.util.base_module import ChubModule
from backend.util.connector import Connector
from backend.util.constants import (
    ASSET_IMAGE_EXTENSIONS,
    illegal_chars_regex,
    parse_asset_type,
    season_number_regex,
)
from backend.util.database import ChubDB
from backend.util.helper import (
    as_list,
    classify_match,
    create_table,
    extract_ids,
    extract_mbid,
    extract_year,
    is_match,
    normalize_titles,
    print_settings,
    progress,
)
from backend.util.normalization import parse_asset_filename
from backend.util.logger import Logger
from backend.util.notification import NotificationManager
from backend.util.plex_index import PlexMediaIndex
from backend.util.upload_posters import PosterUploader

# Process-global lock serializing the destructive poster_cache clear()+rebuild.
# The scheduled run() and the webhook-driven run_poster_rename_adhoc() run on
# different worker pools (module-run vs webhook), each opening its own ChubDB
# with a distinct per-accessor lock — so without this, a webhook firing mid-run
# could DELETE rows the other path just inserted, leaving the matcher to read a
# half-empty cache and mark posters as unmatched. Both rebuild sites take this
# lock so the clear+rebuild is atomic with respect to each other.
_POSTER_CACHE_REBUILD_LOCK = threading.Lock()


# Filenames (sans extension/suffix) that denote artist-level art in a music
# folder layout; everything else at album depth is an album cover.
_MUSIC_ARTIST_STEMS = {
    "artist",
    "artist-poster",
    "poster",
    "folder",
    "fanart",
    "background",
    "banner",
    "logo",
    "clearlogo",
}


def _strip_mbid_tag(text: str) -> str:
    """Remove an ``{mbid-<uuid>}`` (or bare ``mbid-<uuid>``) tag from text."""
    from backend.util.constants import mbid_id_regex

    cleaned = mbid_id_regex.sub("", text)
    return cleaned.replace("{}", "").replace("[]", "").strip(" -_{}[]")


def _build_music_asset_record(
    fname: str,
    root: str,
    *,
    music_root: Optional[str],
    mbid: Optional[str],
    image_type: str,
    base: str,
    ext: str,
    style: Optional[str],
    priority: int,
    search_only: int,
) -> dict:
    """Parse one music image file (artist poster / album cover / asset) into a
    poster_cache record carrying asset_type + musicbrainz_id + parent linkage.

    Identity is resolved from (in priority): an ``{mbid-<uuid>}`` tag, then the
    folder layout under ``music_root`` (``<Artist>/`` = artist, ``<Artist>/
    <Album>/`` = album), then a flat ``Artist - Album`` / ``Artist`` filename.
    """
    folder = os.path.basename(root)
    stem = _strip_mbid_tag(base)
    artist_title: Optional[str] = None
    album_title: Optional[str] = None

    rel_parts: List[str] = []
    if music_root:
        rel = os.path.relpath(root, music_root)
        rel_parts = [p for p in rel.split(os.sep) if p not in (".", "")]

    if len(rel_parts) >= 2:
        # <music_root>/<Artist>/<Album>/<file>
        artist_title, album_title = rel_parts[0], rel_parts[1]
    elif len(rel_parts) == 1:
        # <music_root>/<Artist>/<file> — artist art, unless a clearly album-y
        # stem sits here (rare); default to artist at this depth.
        artist_title = rel_parts[0]
        if stem and stem.lower() not in _MUSIC_ARTIST_STEMS:
            # e.g. <Artist>/<Album>.jpg flat-in-artist-folder layout.
            album_title = stem
    else:
        # Flat file: "Artist - Album.jpg" => album; "Artist.jpg" => artist.
        if " - " in stem:
            artist_title, album_title = (p.strip() for p in stem.split(" - ", 1))
        else:
            artist_title = stem

    if album_title:
        asset_type = "album"
        title = album_title
        parent_title = artist_title
    else:
        asset_type = "artist"
        title = artist_title or stem
        parent_title = None

    return {
        "title": title,
        "normalized_title": normalize_titles(title or ""),
        "year": None,
        "tmdb_id": None,
        "tvdb_id": None,
        "imdb_id": None,
        "musicbrainz_id": mbid,
        "parent_musicbrainz_id": None,
        "parent_title": parent_title,
        "parent_normalized_title": (
            normalize_titles(parent_title) if parent_title else None
        ),
        "season_number": None,
        "music_kind": asset_type,
        "folder": folder,
        "file": os.path.join(root, fname),
        "style": style,
        "priority": priority,
        "image_type": image_type,
        "search_only": search_only,
    }


def build_asset_record(
    fname: str,
    root: str,
    style: Optional[str] = None,
    priority: int = 0,
    search_only: int = 0,
    music_root: Optional[str] = None,
) -> dict:
    """Parse one image file into a poster_cache record.

    Shared by poster_renamerr's scan and asset_renamerr's scan. Detects an
    additional-asset-type suffix (logo/squareart/background/banner) via
    ``asset_type_regex`` and stamps ``image_type`` accordingly; suffix-less
    files are plain posters. For asset files the suffix is stripped BEFORE the
    title/normalized_title are computed so the asset's match key equals the same
    media's poster key (e.g. "Movie (2023) - Logo.png" keys on "movie", exactly
    like "Movie (2023).png"). The poster path (no suffix) is byte-identical to
    the original inline logic — do not let it drift. ``asset_type``
    (movie/show/collection) is NOT set here; it is classified across the full
    record set by the caller (it needs cross-record show_keys).

    When ``music_root`` is set (the file lives under a configured music source
    dir) or the file/folder carries an ``{mbid-<uuid>}`` tag, the record is
    built as MUSIC (artist poster / album cover) via _build_music_asset_record
    and stamped with ``music_kind`` so the caller classifies it as artist/album.
    """
    folder = os.path.basename(root)
    filename, ext = os.path.splitext(fname)

    # base has the type tag stripped; callers re-attach the real extension so
    # parse_asset_filename's own splitext targets the extension (not a dot
    # inside a title like "8 A.M. Metro").
    image_type, base = parse_asset_type(filename)

    # Music: a configured music_root, or an {mbid-} tag anywhere, routes to the
    # music builder.
    mbid = extract_mbid(fname) or extract_mbid(folder)
    if music_root is not None or mbid:
        return _build_music_asset_record(
            fname,
            root,
            music_root=music_root,
            mbid=mbid,
            image_type=image_type,
            base=base,
            ext=ext,
            style=style,
            priority=priority,
            search_only=search_only,
        )

    if image_type != "poster":
        title = parse_asset_filename(base + ext)
        normalized_title = normalize_titles(base)
    else:
        title = parse_asset_filename(fname)
        # Derive the search/match key from the raw (ext-stripped) filename, not
        # from `title`. normalize_titles() already strips the year (and trailing
        # season tag), IDs, and special chars, so it yields the same key for
        # normal assets — but staying independent of parse_asset_filename means
        # a future title-parsing change can never silently poison
        # normalized_title (the root cause of the "Open Season 2" -> "open"
        # search/match failure).
        normalized_title = normalize_titles(filename)

    year = extract_year(fname) or extract_year(title) or extract_year(folder)
    tmdb_id, tvdb_id, imdb_id = extract_ids(fname)
    if not (tmdb_id or tvdb_id or imdb_id):
        tmdb_id, tvdb_id, imdb_id = extract_ids(folder)
    match = season_number_regex.search(fname) or season_number_regex.search(folder)
    season_number = (
        int(match.group(1)) if match and match.group(1) else (0 if match else None)
    )

    return {
        "title": title,
        "normalized_title": normalized_title,
        "year": year,
        "tmdb_id": tmdb_id,
        "tvdb_id": tvdb_id,
        "imdb_id": imdb_id,
        "season_number": season_number,
        "folder": folder,
        "file": os.path.join(root, fname),
        "style": style,
        "priority": priority,
        "image_type": image_type,
        "search_only": search_only,
    }


class PosterRenamerr(ChubModule):
    def __init__(self, logger: Optional[Logger] = None) -> None:
        super().__init__(logger=logger)

    @contextlib.contextmanager
    def apply_staging(self):
        """Redirect file output for the "plex" apply path.

        On apply_method == "plex" posters are uploaded straight to Plex and
        never kept on disk, but the rename → border pipeline still needs files
        to operate on. This stages them in a temp dir (flat layout, COPY only —
        never move/hardlink/symlink the user's source), yields the staging path,
        then restores the overridden config and removes the dir on exit. A
        no-op (yields None) on the "kometa" path, which writes to the
        configured destination_dir as usual.

        Used by both the scheduled run() and the webhook/adhoc orchestration so
        the staging lifecycle is identical and always cleaned up.
        """
        if getattr(self.config, "apply_method", "kometa") != "plex":
            yield None
            return
        orig = (
            self.config.destination_dir,
            self.config.action_type,
            self.config.asset_folders,
        )
        staging_dir = tempfile.mkdtemp(prefix="chub_poster_plex_")
        self.config.destination_dir = staging_dir
        self.config.action_type = "copy"
        self.config.asset_folders = False
        try:
            yield staging_dir
        finally:
            (
                self.config.destination_dir,
                self.config.action_type,
                self.config.asset_folders,
            ) = orig
            if os.path.isdir(staging_dir):
                shutil.rmtree(staging_dir, ignore_errors=True)

    def ensure_destination_dir(self):
        if not os.path.exists(self.config.destination_dir):
            self.logger.info(
                f"Creating destination directory: {self.config.destination_dir}"
            )
            os.makedirs(self.config.destination_dir)
        else:
            self.logger.debug(
                f"Destination directory already exists: {self.config.destination_dir}"
            )

    # Progress slice for sync_gdrive when invoked from inside poster_renamerr.
    # The nested SyncGDrive instance reports its own 0..100 internally but
    # against a stale job_id; clamp the parent job at the slice boundary
    # before and after so the Jobs page percentage advances visibly during
    # the sync.
    _SYNC_PROGRESS_CEILING_PCT = 10

    def sync_posters(self):
        if self.config.sync_posters:
            self.logger.info("Running sync_gdrive")
            self._report_progress(0)
            try:
                from backend.modules.sync_gdrive import SyncGDrive

                # skip_cache_refresh: merge_assets below does a full
                # clear() + rebuild, so the per-folder refresh would be
                # immediately overwritten — pure duplicated work.
                sync = SyncGDrive(logger=self.logger)
                # Drive the parent bar's 0..ceiling slice as folders complete,
                # so the longest phase isn't flat. No-ops without job context.
                sync.set_job_context(
                    getattr(self, "_job_id", None), getattr(self, "_job_db", None)
                )
                sync.set_progress_window(0, self._SYNC_PROGRESS_CEILING_PCT)
                sync.run(skip_cache_refresh=True)
                self.logger.info("Finished running sync_gdrive")
                self._report_progress(self._SYNC_PROGRESS_CEILING_PCT)
            except FileNotFoundError as e:
                self.logger.warning(
                    f"Skipping GDrive sync: {e}. "
                    "Set sync_posters to false in config if you don't use GDrive."
                )
        else:
            self.logger.debug("Sync posters is disabled. Skipping...")

    def process_file(self, file: str, new_file_path: str, action_type: str):
        try:
            if action_type == "copy":
                # Copy to a temp name in the destination dir, then atomically
                # os.replace() into place — an interrupted copy (crash, kill,
                # ENOSPC) can't leave a truncated poster at the real path or
                # clobber an existing good file with a partial one. Mirrors
                # asset_renamerr._file_op's destroy-safe link handling.
                tmp = f"{new_file_path}.chub-tmp-{os.getpid()}"
                try:
                    shutil.copy(file, tmp)
                    os.replace(tmp, new_file_path)
                except OSError:
                    with contextlib.suppress(OSError):
                        os.remove(tmp)
                    raise
            elif action_type == "move":
                shutil.move(file, new_file_path)
            elif action_type == "hardlink":
                os.link(file, new_file_path)
            elif action_type == "symlink":
                os.symlink(file, new_file_path)
            # Per-file action trace — visible when log_level: debug.
            # Single source of truth so every call site (rename_file,
            # future orphan cleanup, etc.) logs the same shape.
            self.logger.debug(f"[{action_type.upper()}] {new_file_path} ← {file}")
            return True
        except OSError as e:
            self.logger.error(f"Error {action_type}ing file: {e}")
            return False

    @staticmethod
    def _append_rename_history(existing: Optional[str], old: str, new: str) -> str:
        """Append a {old, new, at} entry to a media row's rename_history JSON,
        keeping the most recent 20. Returns the new JSON string."""
        try:
            history = json.loads(existing or "[]")
            if not isinstance(history, list):
                history = []
        except (ValueError, TypeError):
            history = []
        history.append(
            {
                "old": os.path.basename(old) if old else None,
                "new": os.path.basename(new) if new else None,
                "at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        return json.dumps(history[-20:])

    @staticmethod
    def _candidate_identity(cand: dict) -> tuple:
        """Identity signature for conflict detection. Prefers an external ID
        (TMDB, then IMDB), falling back to (normalized_title, year). Two matched
        posters with different signatures are a genuine ambiguity; duplicates
        of the same media across drives share a signature and don't conflict.
        """
        tmdb = cand.get("tmdb_id")
        if tmdb not in (None, "", 0, "0"):
            return ("tmdb", str(tmdb))
        imdb = cand.get("imdb_id")
        if imdb:
            return ("imdb", str(imdb).lower())
        return ("title", cand.get("normalized_title") or "", cand.get("year"))

    @staticmethod
    def _has_identity_conflict(matched_candidates: list) -> bool:
        """True only when matched posters GENUINELY disagree on identity.

        A real conflict means two posters that point at *different* media:
        different normalized titles, or different non-null IDs of the same
        source. It is NOT a conflict when same-title posters merely differ in
        ID *presence* — e.g. a collection with "Phineas and Ferb Collection.jpg"
        (no id) and "...Collection {tmdb-1}.jpg" — those are the same entity, so
        the bottom-wins source priority picks one silently (no needs_review).
        This is what lets id-less Plex collections auto-match instead of piling
        up in the review queue.
        """
        if len(matched_candidates) < 2:
            return False

        norm_titles = {c.get("normalized_title") or "" for c in matched_candidates}
        if len(norm_titles) > 1:
            return True

        def distinct_ids(field: str) -> set:
            vals = set()
            for c in matched_candidates:
                v = c.get(field)
                if v not in (None, "", 0, "0"):
                    vals.add(str(v).lower())
            return vals

        return (
            len(distinct_ids("tmdb_id")) > 1
            or len(distinct_ids("imdb_id")) > 1
            or len(distinct_ids("tvdb_id")) > 1
        )

    @staticmethod
    def find_asset_candidate(
        media: dict,
        db: ChubDB,
        image_type: str = "poster",
        is_collection: bool = False,
        conn=None,
    ) -> dict:
        """Find the best poster_cache candidate for ``media``, scoped to
        ``image_type``.

        This is the shared candidate-finding core (ID lookup, then prefix/AKA
        name lookup with season + identity checks) used both by poster matching
        (``image_type="poster"``) and by the asset pipeline (logo / squareart /
        background / banner). It performs NO writeback — callers decide where to
        record the result (media_cache for posters, media_asset_matches for
        assets).

        Returns a dict with: ``candidate`` (best row or None), ``matched``
        (bool), ``win_reason`` (str), ``matched_candidates`` (every row that
        passed is_match — used for conflict detection), ``candidates`` (the
        considered set), and ``reasons`` (human-readable trace).
        """
        asset_type = media.get("asset_type")
        title = media.get("title")
        normalized_title = media.get("normalized_title")
        season_number = media.get("season_number")
        expected_asset_type = "collection" if is_collection else asset_type

        alt_titles = []
        try:
            alt_titles = json.loads(media.get("alternate_titles") or "[]")
        except Exception:
            pass

        reasons = []
        matched = False
        candidate = None
        candidates = []
        win_reason = ""
        # Every poster that passed is_match() for this media — used to detect
        # ambiguous (conflicting-identity) matches.
        matched_candidates = []

        for id_field in ["imdb_id", "tmdb_id", "tvdb_id", "musicbrainz_id"]:
            id_val = media.get(id_field)
            if id_val:
                c = db.poster.get_by_id(
                    id_field,
                    id_val,
                    season_number,
                    asset_type=expected_asset_type,
                    image_type=image_type,
                    conn=conn,
                )
                if c:
                    matched, reason = is_match(c, media)
                    if matched:
                        reasons.append(
                            f"Matched by {id_field}: {id_val} (season {season_number}) [{reason}]"
                        )
                        candidate = c
                        candidates = [c]
                        win_reason = reason
                        matched_candidates = [c]
                        break

        if not candidate:
            # Look up candidates by the prefix of EVERY title the media is known
            # by — primary plus alternates — not just the primary. Otherwise a
            # poster named by an AKA (e.g. "Origen" for "Inception") is never in
            # the candidate set, so the alt-title check below can't fire. This
            # is what makes TMDB AKA hydration actually pay off.
            search_titles = [title] if title else []
            search_titles += [t for t in alt_titles if t]
            candidates = []
            seen_files = set()
            for st in search_titles:
                for c in db.poster.get_candidates_by_prefix(
                    st, asset_type=expected_asset_type, image_type=image_type, conn=conn
                ):
                    key = c.get("file")
                    if key not in seen_files:
                        seen_files.add(key)
                        candidates.append(c)

            all_titles = set()
            if normalized_title:
                all_titles.add(normalized_title)
            all_titles.update({normalize_titles(t) for t in alt_titles if t})

            for cand in candidates:
                cand_season = cand.get("season_number")
                if season_number is not None and cand_season != season_number:
                    continue
                if season_number is None and cand_season is not None:
                    continue
                cand_norm_title = cand.get("normalized_title", "")
                cand_alt_titles = set(
                    json.loads(cand.get("normalized_alternate_titles", "[]") or "[]")
                )

                if cand_norm_title in all_titles or bool(
                    all_titles & set(cand_alt_titles)
                ):
                    m, reason = is_match(cand, media)
                    if m:
                        reasons.append(
                            f"Prefix/name candidate: {cand.get('title')} (season {cand.get('season_number')}) [{reason}]"
                        )
                        matched_candidates.append(cand)
                        if not candidate:
                            candidate = cand
                            matched = True
                            win_reason = reason

        return {
            "candidate": candidate,
            "matched": bool(matched),
            "win_reason": win_reason,
            "matched_candidates": matched_candidates,
            "candidates": candidates,
            "reasons": reasons,
        }

    def match_item(self, media: dict, db: ChubDB, is_collection=False) -> dict:
        asset_type = media.get("asset_type")
        title = media.get("title")
        year = media.get("year")
        library_name = media.get("library_name")
        instance_name = media.get("instance_name")
        season_number = media.get("season_number")

        # A user-confirmed (manually applied/approved) row is locked: never let a
        # re-scan recompute and overwrite its match. This is what makes a manual
        # poster pick survive scheduled poster_renamerr runs. The lock is cleared
        # by applying a different poster (re-sets it) or by ignoring the item
        # (the ignore endpoint clears user_confirmed).
        if media.get("user_confirmed"):
            self.logger.debug(
                f"↳ user-confirmed, preserving manual match: {title} ({year})"
            )
            return {
                "matched": bool(media.get("matched")),
                "match": None,
                "candidates": [],
                "reasons": ["user_confirmed: manual match preserved"],
            }

        found = self.find_asset_candidate(
            media, db, image_type="poster", is_collection=is_collection
        )
        candidate = found["candidate"]
        matched = found["matched"]
        win_reason = found["win_reason"]
        matched_candidates = found["matched_candidates"]
        candidates = found["candidates"]
        reasons = found["reasons"]

        # --- Match transparency: status + confidence + conflict detection ---
        # match_status/confidence are additive metadata; `matched` (whether the
        # poster is applied) is unchanged. A loose match becomes "needs_review"
        # and, if two posters with different identities both matched, the
        # priority-winner is still applied but flagged with its rivals.
        match_status, match_confidence = classify_match(matched, win_reason)
        conflict_json = "[]"
        if self._has_identity_conflict(matched_candidates):
            match_status = "needs_review"
            conflict_json = json.dumps(
                [
                    {
                        "title": c.get("title"),
                        "year": c.get("year"),
                        "file": c.get("file"),
                        "tmdb_id": c.get("tmdb_id"),
                        "imdb_id": c.get("imdb_id"),
                        "tvdb_id": c.get("tvdb_id"),
                    }
                    for c in matched_candidates[:5]
                ]
            )

        # Steady-state skip: on a re-scan most rows match exactly as before, so
        # the row UPDATE would write byte-identical values. Skip it when every
        # field update() would set already equals the stored value. PROVABLY
        # SAFE — only a write that would be a no-op is skipped, so a real change
        # is never dropped (a mismatched type just means "don't skip"). The
        # predicate mirrors update()'s write set, identical for media_cache and
        # collections_cache: matched / match_status / match_confidence(float) /
        # conflict_ids are always written; original_file only when a candidate
        # matched; match_reason only when a reason exists. If update()'s written
        # fields change, update this predicate too — guarded by
        # test_match_item_skips_unchanged_write.
        new_original = candidate.get("file") if candidate else None
        update_is_noop = (
            int(bool(matched)) == media.get("matched")
            and match_status == media.get("match_status")
            and float(match_confidence) == media.get("match_confidence")
            and conflict_json == media.get("conflict_ids")
            and (new_original is None or new_original == media.get("original_file"))
            and (not win_reason or win_reason == media.get("match_reason"))
        )
        if not update_is_noop:
            if is_collection:
                db.collection.update(
                    title=title,
                    year=year,
                    library_name=library_name,
                    instance_name=instance_name,
                    matched_value=matched,
                    original_file=new_original,
                    match_status=match_status,
                    match_confidence=match_confidence,
                    match_reason=win_reason or None,
                    conflict_ids=conflict_json,
                    id=media.get("id"),
                )
            else:
                db.media.update(
                    asset_type=asset_type,
                    title=title,
                    year=year,
                    instance_name=instance_name,
                    matched_value=matched,
                    season_number=season_number,
                    original_file=new_original,
                    match_status=match_status,
                    match_confidence=match_confidence,
                    match_reason=win_reason or None,
                    conflict_ids=conflict_json,
                    id=media.get("id"),
                )

        # Recently-matched provenance: stamp matched_at only when the match is
        # NEW or CHANGED — never re-stamped for a stable, re-confirmed match —
        # so the "Recently matched" reel reflects genuinely recent matches
        # rather than the scan's processing order. Linked by file path so it
        # survives poster_cache's clear-and-reinsert on every scan.
        new_file = candidate.get("file") if (matched and candidate) else None
        prev_file = media.get("matched_poster_file")
        if new_file and new_file != prev_file:
            new_matched_at = datetime.now().isoformat(timespec="seconds")
        elif new_file:
            new_matched_at = media.get("matched_at")  # unchanged — keep
        else:
            new_matched_at = None  # no match — clear
        # Skip the provenance UPDATE too when both fields are unchanged — the
        # same provably-safe no-op skip.
        if new_matched_at != media.get("matched_at") or new_file != prev_file:
            if is_collection:
                db.collection.set_match_provenance(
                    media.get("id"), new_matched_at, new_file
                )
            else:
                db.media.set_match_provenance(media.get("id"), new_matched_at, new_file)

        if asset_type == "show":
            if season_number is not None:
                if matched and candidate:
                    self.logger.debug(
                        f"✓ Matched: [show] {title} ({year}) Season: {season_number} <-> {candidate.get('title')} ({candidate.get('year')}) Season: {candidate.get('season_number')}"
                    )
                else:
                    self.logger.debug(
                        f"✗ No match: [show] {title} ({year}) Season {season_number}"
                    )
            else:
                if matched and candidate:
                    self.logger.debug(
                        f"✓ Matched: [show] {title} ({year}) <-> {candidate.get('title')} ({candidate.get('year')})"
                    )
                else:
                    self.logger.debug(f"✗ No match: [show] {title} ({year})")

        elif is_collection:
            if matched and candidate:
                self.logger.debug(
                    f"✓ Matched: [collection] {title} ({year}) <-> {candidate.get('title')} ({candidate.get('year')})"
                )
            else:
                self.logger.debug(f"✗ No match: [collection] {title} ({year})")

        else:
            if matched and candidate:
                self.logger.debug(
                    f"✓ Matched: [movie] {title} ({year}) <-> {candidate.get('title')} ({candidate.get('year')})"
                )
            else:
                self.logger.debug(f"✗ No match: [movie] {title} ({year})")

        return {
            "matched": bool(matched),
            "match": candidate,
            "candidates": candidates,
            "reasons": reasons,
        }

    # Job-progress slice for match_assets_to_media. Picks up from
    # _MERGE_PROGRESS_CEILING_PCT (50) and runs to _MATCH_PROGRESS_CEILING_PCT
    # (90). Rename_files gets the final 90..100 slice.
    _MATCH_PROGRESS_CEILING_PCT = 90
    _MATCH_PROGRESS_EVERY = 250

    def match_assets_to_media(self, db: ChubDB):
        self.logger.info("Matching assets to media and collections, please wait...")
        from backend.util.connector import gather_media_and_collections

        all_media = gather_media_and_collections(self.config, db)
        total_items = len(all_media)
        if not all_media:
            self.logger.warning(
                "No media or collections found in database for matching."
            )
            self._report_progress(self._MATCH_PROGRESS_CEILING_PCT)
            return

        matches = 0
        non_matches = 0
        match_span = self._MATCH_PROGRESS_CEILING_PCT - self._MERGE_PROGRESS_CEILING_PCT

        with progress(
            all_media,
            desc="Matching assets to media & collections",
            total=total_items,
            unit="media",
            logger=self.logger,
        ) as bar:
            for idx, media in enumerate(bar, 1):
                if self.is_cancelled():
                    break
                is_collection = media.get("asset_type") == "collection"
                result = self.match_item(media, db, is_collection)
                if result["matched"]:
                    matches += 1
                else:
                    non_matches += 1

                if idx % self._MATCH_PROGRESS_EVERY == 0 and idx != total_items:
                    self._report_progress(
                        self._MERGE_PROGRESS_CEILING_PCT
                        + int(idx / total_items * match_span)
                    )

        self._report_progress(self._MATCH_PROGRESS_CEILING_PCT)
        self.logger.debug(f"Completed matching for all assets: {total_items} items")
        self.logger.debug(f"{matches} total_matches")
        self.logger.debug(f"{non_matches} non_matches")

    def _staged_dest(self, item: dict) -> Optional[str]:
        """Absolute path rename_file() stages *item* to under the CURRENT
        folder/title, computed with no side effects (no traversal guard, no
        mkdir). Single source of truth for the staged path so
        get_matched_assets() can detect when an already-staged asset has
        drifted — e.g. its media folder was renamed and the poster is stranded
        under the old name — and re-queue it. Returns None when there is no
        source file to stage. Keep in sync with rename_file(), which reuses it.
        """
        file = item.get("original_file") or item.get("file")
        if not file:
            return None
        asset_type = item.get("asset_type")
        folder = item.get("folder", item.get("media_folder", "")) or ""
        if asset_type == "collection" and not folder:
            folder = illegal_chars_regex.sub("", item.get("title") or "").strip()
        file_extension = os.path.splitext(file)[1]
        season_number = item.get("season_number")
        config = self.config
        dest_dir = (
            os.path.join(config.destination_dir, folder)
            if config.asset_folders
            else config.destination_dir
        )
        if asset_type == "show" and season_number is not None:
            season_str = str(season_number).zfill(2)
            new_file_name = (
                f"Season{season_str}{file_extension}"
                if config.asset_folders
                else f"{folder}_Season{season_str}{file_extension}"
            )
        elif asset_type == "album":
            # Kometa keys an album's cover by the ALBUM title alone, inside the
            # artist's folder (its find_item_assets uses item.title) — prefixing
            # the artist made every album cover unfindable.
            album_base = illegal_chars_regex.sub("", item.get("title") or "").strip()
            album_base = album_base or "album"
            new_file_name = (
                f"{album_base}{file_extension}"
                if config.asset_folders
                else f"{folder}_{album_base}{file_extension}"
            )
        else:
            new_file_name = (
                f"poster{file_extension}"
                if config.asset_folders
                else f"{folder}{file_extension}"
            )
        return os.path.join(dest_dir, new_file_name)

    @staticmethod
    def _source_hash(path: str) -> Optional[str]:
        """sha256 of a source poster file, or None if it can't be read (a missing
        source means "not unchanged" → re-process, never a silent skip)."""
        try:
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except OSError:
            return None

    def _build_upload_lib_indexes(self, db: ChubDB) -> List[PlexMediaIndex]:
        """One PlexMediaIndex per add_posters-enabled instance, built over the
        same plex_media_cache snapshot the uploader resolves against — so the
        skip's notion of "target libraries" can't drift from the uploader's.
        Instances with no snapshot contribute nothing (the coverage check then
        degrades to today's hash-only skip rather than re-staging everything).
        """
        indexes: List[PlexMediaIndex] = []
        for scope in self.config.plex_scope or []:
            if not scope.add_posters:
                continue
            rows = db.plex.get_by_instance(scope.instance)
            if rows:
                indexes.append(PlexMediaIndex(rows))
        return indexes

    @staticmethod
    def _current_target_libs(row: dict, lib_indexes: List[PlexMediaIndex]) -> set:
        """Libraries the uploader would currently target for ``row``, unioned
        across every enabled instance (uploaded_libraries is a flat
        cross-instance record). Empty when the item resolves nowhere — the
        uploader would only fail "No matching Plex entry found" for those, so
        an empty result must not block the skip."""
        asset_type = row.get("asset_type")
        season_number = row.get("season_number")
        title_override = None
        if asset_type == "movie":
            media_type = "movie"
        elif asset_type == "show":
            if season_number is None:
                media_type = "show"
            else:
                media_type = "season"
                # Mirror the uploader's season title key (_sync_seasons) so
                # title-only season matches count as targets too.
                title_override = (
                    f"{normalize_titles(row.get('title', ''))}:S{season_number}"
                )
        elif asset_type in ("collection", "artist", "album"):
            media_type = asset_type
        else:
            return set()
        libs: set = set()
        for idx in lib_indexes:
            entries, _key = idx.resolve(
                row,
                media_type=media_type,
                season_number=season_number if media_type == "season" else None,
                title_override=title_override,
            )
            libs.update(
                str(e["library_name"]) for e in entries if e.get("library_name")
            )
        return libs

    def _is_unchanged_upload(self, row: dict, lib_indexes=None) -> bool:
        """Plex apply path only: True when this matched poster can be skipped
        entirely (no copy, no border, no upload) because its SOURCE is unchanged
        since it was last successfully uploaded AND it was uploaded before.

        Mirrors PosterFlow's adopt-existing fast-path. Keyed on the raw source
        (source_file_hash), NOT the staged/bordered file_hash, so it's correct
        whether or not border_replacerr runs. Fails safe: any missing signal
        (no prior upload, no stored hash, unreadable source) → not skipped.

        With ``lib_indexes`` the skip additionally requires the recorded
        uploaded_libraries to cover every library the uploader would currently
        target, so a newly opted-in library or a partial per-library failure
        re-flows into the uploader's backfill instead of being skipped forever.
        ``None`` (caller couldn't build indexes) keeps the legacy hash-only
        behavior.
        """
        cfg = self.config
        if getattr(cfg, "apply_method", "kometa") != "plex":
            return False
        if not getattr(cfg, "skip_unchanged_uploads", True):
            return False
        stored = row.get("source_file_hash")
        if not stored or not row.get("uploaded_libraries"):
            return False
        if lib_indexes is not None:
            recorded = PosterUploader._parse_uploaded_libraries(
                row.get("uploaded_libraries")
            )
            targets = self._current_target_libs(row, lib_indexes)
            if not targets <= recorded:
                return False
        src = row.get("original_file")
        if not src:
            return False
        current = self._source_hash(src)
        return bool(current) and current == stored

    def _needs_staging(self, row: dict) -> bool:
        """True when a matched asset must be (re)staged: nothing staged yet, the
        staged file is missing, OR it sits at a stale path because the media
        folder/title was renamed (so the poster is stranded under the old name).
        The path check is what lets a folder rename self-heal on the next run
        instead of being skipped forever because the old staged file still
        exists.
        """
        current = row.get("renamed_file")
        if not current or not os.path.exists(current):
            return True
        expected = self._staged_dest(row)
        return bool(expected) and os.path.normpath(current) != os.path.normpath(
            expected
        )

    def _remove_superseded(self, previous: Optional[str], new_file_path: str) -> None:
        """Delete the file an asset was PREVIOUSLY staged to once it has moved to
        a new path (e.g. the media folder was renamed). Without this a folder
        rename leaves the old "<Old Folder>/poster.jpg" stranded forever: Kometa
        ignores it (the folder name no longer matches the item) and the
        orphan-asset pass spares it (its {tvdb-id}/{tmdb-id} still matches a live
        title), so duplicate folders accumulate. Bounded to destination_dir;
        never removes the destination root. Best-effort — failures only warn.
        """
        config = self.config
        if not previous or previous == new_file_path:
            return
        if config.dry_run or config.run_border_replacerr:
            return
        try:
            real_base = os.path.realpath(config.destination_dir)
            real_prev = os.path.realpath(previous)
            if not real_prev.startswith(real_base + os.sep):
                return  # outside the staging tree — leave it alone
            if not os.path.lexists(previous):
                return
            os.remove(previous)
            self.logger.debug(f"[CLEANUP] removed superseded staged asset {previous}")
            parent = os.path.dirname(previous)
            if (
                config.asset_folders
                and os.path.realpath(parent) != real_base
                and os.path.isdir(parent)
                and not os.listdir(parent)
            ):
                os.rmdir(parent)
                self.logger.debug(f"[CLEANUP] removed emptied stale folder {parent}")
        except OSError as e:
            self.logger.warning(f"Could not remove superseded asset {previous}: {e}")

    def rename_file(self, item: dict, db: ChubDB) -> Optional[dict]:
        asset_type = item.get("asset_type")
        file = item.get("original_file") or item.get("file")
        folder = item.get("folder", item.get("media_folder", "")) or ""
        # Plex collections have no on-disk folder, so collections_cache.folder is
        # empty — which previously produced a nameless ".jpg" (flat) or a generic
        # "poster.jpg" at the destination root. Kometa names a collection's asset
        # by its title, so fall back to the (path-sanitised) collection title.
        if asset_type == "collection" and not folder:
            folder = illegal_chars_regex.sub("", item.get("title") or "").strip()
        file_name = os.path.basename(file)
        config = self.config
        # Where this asset was staged on the previous run (may be a stale path
        # under an old folder name); used to clean up after a folder rename.
        previous_renamed = item.get("renamed_file")

        # _staged_dest() is the single source of truth for the destination
        # (shared with _needs_staging so a renamed media folder gets re-queued
        # rather than skipped); rename_file only adds the side effects below —
        # the path-traversal guard and directory creation. The per-type naming
        # (poster / SeasonNN / "<Artist> - <Album>") lives in _staged_dest().
        new_file_path = self._staged_dest(item)
        if not new_file_path:
            return None
        new_file_name = os.path.basename(new_file_path)
        dest_dir = os.path.dirname(new_file_path)

        if config.asset_folders:
            # Prevent path traversal
            real_dest = os.path.realpath(dest_dir)
            real_base = os.path.realpath(config.destination_dir)
            if not real_dest.startswith(real_base + os.sep) and real_dest != real_base:
                self.logger.warning(
                    f"Path traversal detected for folder '{folder}', skipping"
                )
                return None
            if (
                not os.path.exists(dest_dir)
                and not config.dry_run
                and not config.run_border_replacerr
            ):
                try:
                    os.makedirs(dest_dir)
                except OSError as e:
                    self.logger.error(f"Failed to create directory {dest_dir}: {e}")
                    return None

        item["renamed_file"] = new_file_path

        if asset_type == "collection":
            db.collection.update(
                title=item.get("title"),
                year=item.get("year"),
                library_name=item.get("library_name"),
                instance_name=item.get("instance_name"),
                matched_value=None,
                original_file=None,
                renamed_file=new_file_path,
                id=item.get("id"),
            )
        else:
            history_json = None
            if not config.dry_run:
                history_json = self._append_rename_history(
                    item.get("rename_history"),
                    item.get("original_file") or item.get("file"),
                    new_file_path,
                )
            db.media.update(
                asset_type=asset_type,
                title=item.get("title"),
                year=item.get("year"),
                instance_name=item.get("instance_name"),
                matched_value=None,
                season_number=item.get("season_number"),
                original_file=None,
                renamed_file=new_file_path,
                rename_history=history_json,
                id=item.get("id"),
            )

        messages = []
        discord_message = []
        file_ops_enabled = not config.run_border_replacerr

        if os.path.lexists(new_file_path):
            try:
                files_identical = filecmp.cmp(file, new_file_path)
            except OSError as e:
                self.logger.warning(f"Cannot compare files: {e}")
                files_identical = False
            if not files_identical:
                if file_name != new_file_name:
                    messages.append(f"{file_name} -renamed-> {new_file_name}")
                    discord_message.append(f"{new_file_name}")
                else:
                    if not config.print_only_renames:
                        messages.append(f"{file_name} -not-renamed-> {new_file_name}")
                        discord_message.append(f"{new_file_name}")
                if file_ops_enabled and not config.dry_run:
                    if config.action_type in ["hardlink", "symlink"]:
                        self.logger.debug(
                            f"[REPLACED] {new_file_path} (overwriting before "
                            f"{config.action_type})"
                        )
                        os.remove(new_file_path)
                    success = self.process_file(file, new_file_path, config.action_type)
                    if not success:
                        self.logger.warning(
                            f"File operation failed for {file} -> {new_file_path}"
                        )
                        return None
        else:
            if file_name != new_file_name:
                messages.append(f"{file_name} -renamed-> {new_file_name}")
                discord_message.append(f"{new_file_name}")
            else:
                if not config.print_only_renames:
                    messages.append(f"{file_name} -not-renamed-> {new_file_name}")
                    discord_message.append(f"{new_file_name}")
            if file_ops_enabled and not config.dry_run:
                success = self.process_file(file, new_file_path, config.action_type)
                if not success:
                    self.logger.warning(
                        f"File operation failed for {file} -> {new_file_path}"
                    )
                    return None

        # Now that the asset is staged at its current path, drop any copy left
        # behind at the previous path (folder-rename self-cleanup).
        if file_ops_enabled and not config.dry_run:
            self._remove_superseded(previous_renamed, new_file_path)

        if messages or discord_message:
            return {
                "title": item.get("title"),
                "year": item.get("year"),
                "folder": folder,
                "messages": messages,
                "discord_message": discord_message,
                "asset_type": asset_type,
                "id": item.get("id"),
            }
        return None

    def get_matched_assets(self, db: ChubDB) -> list:
        matched_assets = []
        skipped_unchanged = 0
        lib_indexes = None
        if getattr(self.config, "apply_method", "kometa") == "plex" and getattr(
            self.config, "skip_unchanged_uploads", True
        ):
            lib_indexes = self._build_upload_lib_indexes(db)

        def _consider(row: dict) -> None:
            nonlocal skipped_unchanged
            if not (row.get("matched") and self._needs_staging(row)):
                return
            if self._is_unchanged_upload(row, lib_indexes):
                skipped_unchanged += 1
                return
            matched_assets.append(row)

        for instance_name in self.config.instances:
            if not isinstance(instance_name, str):
                continue
            for row in db.media.get_by_instance(instance_name):
                _consider(row)
        for scope in self.config.plex_scope or []:
            if not scope.match_collections:
                continue
            libs = list(
                scope.library_names or []
            ) or db.collection.get_library_names_for_instance(scope.instance)
            for library_name in libs:
                for row in db.collection.get_by_instance_and_library(
                    scope.instance, library_name
                ):
                    _consider(row)
        if skipped_unchanged:
            self.logger.info(
                f"Skipped {skipped_unchanged} unchanged poster(s) already applied "
                "to Plex (source unchanged since last upload)"
            )
        return matched_assets

    def _run_match_quality_pass(self, db: ChubDB) -> None:
        """Automatic refinement after matching: fuzzy near-miss flagging
        (local, always) plus TMDB id verification + AKA hydration (only when a
        TMDB apikey is configured). Failures never abort the run.
        """
        try:
            from backend.util.config import load_config
            from backend.util.tmdb import run_match_quality

            tmdb_cfg = load_config().tmdb
            summary = run_match_quality(db, tmdb_cfg, self.logger)
            if any(summary.values()):
                self.logger.info(
                    "Match-quality pass: "
                    f"{summary.get('fuzzy_flagged', 0)} fuzzy-flagged, "
                    f"{summary.get('id_mismatches', 0)} id mismatches, "
                    f"{summary.get('akas_hydrated', 0)} AKA-hydrated "
                    f"({summary.get('verified', 0)} ids verified)"
                )
        except Exception as exc:
            self.logger.warning(f"Match-quality pass skipped: {exc}")

    # Rename_files reports across _MATCH_PROGRESS_CEILING_PCT..100. Update
    # less frequently than match — this phase is much shorter (only matched
    # assets, not the full media list).
    _RENAME_PROGRESS_EVERY = 100

    def rename_files(self, db: ChubDB, progress_ceiling: int = 100) -> tuple:
        output: Dict[str, List[Dict[str, Any]]] = {
            "collection": [],
            "movie": [],
            "show": [],
            "artist": [],
            "album": [],
        }
        manifest = {"media_cache": [], "collections_cache": []}
        matched_assets = self.get_matched_assets(db=db)

        if matched_assets:
            self.logger.info("Renaming assets please wait...")
            total = len(matched_assets)
            rename_span = progress_ceiling - self._MATCH_PROGRESS_CEILING_PCT
            with progress(
                matched_assets,
                desc="Renaming assets",
                total=total,
                unit="assets",
                logger=self.logger,
            ) as bar:
                for idx, item in enumerate(bar, 1):
                    if self.is_cancelled():
                        break
                    result = self.rename_file(item=item, db=db)
                    if result:
                        output.setdefault(item.get("asset_type", "movie"), []).append(
                            result
                        )

                    if item.get("asset_type") == "collection":
                        manifest["collections_cache"].append(item.get("id"))
                    else:
                        manifest["media_cache"].append(item.get("id"))

                    if idx % self._RENAME_PROGRESS_EVERY == 0 and idx != total:
                        self._report_progress(
                            self._MATCH_PROGRESS_CEILING_PCT
                            + int(idx / total * rename_span)
                        )
        # Pin at the rename ceiling (100 unless a post-rename phase like
        # asset_renamerr reserved the tail). The job_processor pins 100 on
        # completion, so the bar still lands exactly at done.
        self._report_progress(progress_ceiling)
        return output, manifest

    @staticmethod
    def _build_plex_notify_output(upload_result: Optional[dict]) -> dict:
        """Notification payload for the plex apply path: ONLY the posters the
        uploader genuinely pushed this run (action == "updated"), in the same
        {asset_type: [{title, year, messages}]} shape the formatter consumes.

        The staged/rename output must NOT feed the notification here — it
        lists what was staged, so a poster whose upload failed or was skipped
        (unchanged bytes, re-flow retries) would spam every scheduled run as
        if it had been uploaded. Failures and skips stay in the log summary.
        Returns an all-empty shape when nothing genuinely uploaded; the caller
        then attaches a one-line heartbeat instead of a poster list.
        """
        out: Dict[str, List[Dict[str, Any]]] = {
            "collection": [],
            "movie": [],
            "show": [],
            "artist": [],
            "album": [],
        }
        payload = (upload_result or {}).get("payload") or {}
        for up in as_list(payload.get("uploaded")):
            asset_type = up.get("asset_type") or "movie"
            season = up.get("season_number")
            libs = up.get("library_name") or "Plex"
            msg = (
                f"Season {str(season).zfill(2)} uploaded to {libs}"
                if asset_type == "show" and season is not None
                else f"Uploaded to {libs}"
            )
            out.setdefault(asset_type, []).append(
                {
                    "title": up.get("title"),
                    "year": up.get("year"),
                    "messages": [msg],
                }
            )
        return out

    def _music_in_scope(self) -> bool:
        """Whether this run's instances can yield artist/album rows at all.

        Music media comes from Lidarr, so without a Lidarr instance the artist
        and album sections can only ever print "No artists to rename".
        """
        lidarr = getattr(getattr(self.full_config, "instances", None), "lidarr", None)
        return any(name in (lidarr or {}) for name in (self.config.instances or []))

    def handle_output(self, output: Dict[str, List[Dict[str, Any]]]):
        headers = {
            "collection": "Collection",
            "movie": "Movie",
            "show": "Show",
            "artist": "Artist",
            "album": "Album",
        }
        # Never hide a section that actually has rows — the scope check only
        # suppresses the empty music headers on a Lidarr-less setup.
        music_scope = self._music_in_scope()
        sections = ["collection", "movie", "show"] + [
            t for t in ("artist", "album") if music_scope or output.get(t)
        ]
        for asset_type in sections:
            assets = output.get(asset_type, [])
            header = f"{headers.get(asset_type, asset_type.capitalize())}s"
            self.logger.info(create_table([[header]]))

            if not assets:
                # `header` is already plural (e.g. 'Shows'), don't double the s.
                self.logger.info(f"No {header.lower()} to rename\n")
                continue

            if asset_type == "show":
                grouped = {}
                for asset in assets:
                    key = (asset.get("title"), asset.get("year"), asset.get("folder"))
                    grouped.setdefault(key, {"messages": [], "discord_message": []})
                    grouped[key]["messages"].extend(asset.get("messages", []))
                    grouped[key]["discord_message"].extend(
                        asset.get("discord_message", [])
                    )

                for (title, year, folder), data in grouped.items():
                    display = f"{title} ({year})" if year else f"{title}"
                    self.logger.info(display)
                    for msg in data["messages"]:
                        self.logger.info(f"\t{msg}")
                    self.logger.info("")

            else:
                for asset in assets:
                    title = asset.get("title") or ""
                    year = asset.get("year")
                    display = f"{title} ({year})" if year else f"{title}"
                    self.logger.info(display)
                    for msg in asset.get("messages", []):
                        self.logger.info(f"\t{msg}")
                    self.logger.info("")

    def _classify_asset_record(self, record: dict, show_keys: set) -> str:
        # Music records are pre-classified by the builder (artist/album) — the
        # show/movie/collection heuristics below don't apply to them.
        if record.get("music_kind"):
            return record["music_kind"]
        if record.get("season_number") is not None or record.get("tvdb_id"):
            return "show"

        key = (record.get("normalized_title"), record.get("year"))
        if record.get("year") is not None and key in show_keys:
            return "show"

        # An IMDb id means it's a movie missing its year, not a collection.
        # Mirrored in asset_renamerr._classify — keep the two in step.
        if record.get("year") is None and not record.get("imdb_id"):
            return "collection"

        return "movie"

    def _build_gdrive_style_map(self) -> dict:
        """
        Map normalized gdrive `location` -> style prefix from its `name`.

        e.g. config entry name="CL2K Solen", location="/kometa/posters/CL2K/Solen"
        -> {"/kometa/posters/CL2K/Solen": "CL2K"}. Used at scan time to
        stamp each poster_cache row with the curator style it came from.
        """
        out: dict = {}
        full_config = getattr(self, "full_config", None)
        sync_cfg = getattr(full_config, "sync_gdrive", None)
        gdrive_list = getattr(sync_cfg, "gdrive_list", None) or []
        for entry in gdrive_list:
            loc = (getattr(entry, "location", "") or "").strip()
            name = (getattr(entry, "name", "") or "").strip()
            if not loc or not name:
                continue
            head = name.split(None, 1)[0]
            if head:
                out[os.path.realpath(loc).rstrip("/")] = head
        return out

    @staticmethod
    def _resolve_style_for_path(path: str, style_map: dict) -> Optional[str]:
        """Return the style of the longest gdrive_list location that is an
        ancestor of `path`. None if no entry matches."""
        if not style_map:
            return None
        real = os.path.realpath(path).rstrip("/")
        best_style = None
        best_len = -1
        for loc, style in style_map.items():
            if real == loc or real.startswith(loc + "/"):
                if len(loc) > best_len:
                    best_style = style
                    best_len = len(loc)
        return best_style

    def _get_assets_files(
        self,
        source_dir: str,
        priority: int = 0,
        include_assets: bool = False,
        search_only: int = 0,
        music: bool = False,
    ):
        """Walk source_dir and parse each image into a cache record.

        `priority` is stamped on every returned record and used by the
        match-phase queries to enforce bottom-wins source_dir ordering.
        See CONTRACT block in backend/util/database/poster_cache.py.
        Defaults to 0 for callers that don't care about priority (e.g.
        ad-hoc tests, single-folder refresh paths that don't know their
        position in source_dirs).

        Each record carries an `image_type` ("poster" for a plain poster, or
        logo/squareart/background/banner for a suffixed asset file). When
        `include_assets` is False (the default), suffixed asset files are
        skipped entirely so a poster_renamerr run by a user who hasn't enabled
        Asset Renamerr stores ZERO asset rows — no poster_cache bloat and no
        chance of an asset file being mis-handled as a poster. When True (the
        feature is on) the one walk feeds both poster matching and the asset
        pipeline. See build_asset_record().
        """
        style_map = self._build_gdrive_style_map()
        asset_records = []
        for root, dirs, files in os.walk(source_dir):
            dirs.sort(key=str.lower)
            style = self._resolve_style_for_path(root, style_map)
            for fname in sorted(files, key=str.lower):
                if not fname.lower().endswith(ASSET_IMAGE_EXTENSIONS):
                    continue
                record = build_asset_record(
                    fname,
                    root,
                    style=style,
                    priority=priority,
                    search_only=search_only,
                    music_root=source_dir if music else None,
                )
                if not include_assets and record.get("image_type") != "poster":
                    continue
                asset_records.append(record)

        show_keys = {
            (record.get("normalized_title"), record.get("year"))
            for record in asset_records
            if record.get("season_number") is not None or record.get("tvdb_id")
        }
        for record in asset_records:
            record["asset_type"] = self._classify_asset_record(record, show_keys)
        return asset_records

    # Asset count between merge-phase progress heartbeats. At ~150 assets/sec
    # on cold-cache rebuilds this yields one line every ~15-30 seconds, which
    # is a useful "still working" signal without flooding the log.
    _MERGE_PROGRESS_EVERY = 2500

    # merge_assets is the longest phase of a poster_renamerr run. Report
    # job progress across _SYNC_PROGRESS_CEILING_PCT..PROGRESS_CEILING_PCT
    # so the Jobs page UI doesn't sit at 10% for the entire scan. Remaining
    # 50%+ of the progress bar covers the matching + writeback phases.
    _MERGE_PROGRESS_CEILING_PCT = 50

    def merge_assets(self, source_dirs: List[str], db: ChubDB):
        # CONTRACT: source_dirs bottom-wins priority.
        # Each asset's `priority` is its source_dir's 0-based index in
        # this list. Top of list = 0, bottom = len-1. Higher value wins
        # in the match-phase queries (see poster_cache.py CONTRACT block).
        # If the priority stamp is removed or the iteration order is
        # randomized, tests/test_poster_renamerr.py::test_source_dirs_bottom_wins
        # will fail. Don't change without reading that test first.
        start_time = datetime.now()
        self.logger.info("Gathering all the posters, please wait...")
        source_dirs = source_dirs or self._scan_source_dirs()

        # Plan the progress curve: count total assets across all source_dirs
        # up front so each per-asset write contributes a proportional slice.
        # The dir-walk to count is fast (no DB ops) and lets us update job
        # progress smoothly instead of in big steps per source_dir.
        # Music source dirs (custom artist/album art) are scanned with the
        # music classifier appended after the regular dirs so their bottom-wins
        # priority is highest. They feed the same poster_cache.
        music_dirs = list(getattr(self.config, "music_source_dirs", []) or [])
        scan_plan = [(d, False) for d in source_dirs] + [(d, True) for d in music_dirs]

        per_dir_assets = []
        total_all = 0
        for idx, (source_dir, is_music) in enumerate(scan_plan):
            if self.is_cancelled():
                break
            assets = self._get_assets_files(
                source_dir,
                priority=idx,
                include_assets=getattr(self.config, "run_asset_renamerr", False),
                music=is_music,
            )
            per_dir_assets.append((source_dir, assets))
            total_all += len(assets)

        processed_all = 0
        for source_dir, assets in per_dir_assets:
            if self.is_cancelled():
                break
            if not assets:
                self.logger.warning(f"No assets found in '{source_dir}'")
                continue

            total = len(assets)
            self.logger.info(f"Processing {total} assets from '{source_dir}'")

            # The cache mirrors disk 1:1: one row per file in source_dirs.
            # db.poster.clear() ran before this merge, and the UNIQUE
            # constraint on (..., file) prevents duplicate-path inserts,
            # so we just upsert each parsed file as-is. No title-based
            # dedup (which previously wiped distinct shows sharing a
            # normalized title, e.g. The Traitors UK vs AU) and no
            # ID backfill from other rows (a row's fields should reflect
            # only what its own filename/folder yielded; ID inference
            # belongs in the match-to-media phase, not here).
            #
            # Writes are buffered and flushed via bulk_upsert at each
            # heartbeat boundary: one transaction per batch instead of a
            # fresh connection + commit(fsync) per row. merge_assets is the
            # longest phase of a run, so this is the dominant write-path win.
            batch: List[dict] = []
            for idx, asset in enumerate(assets, 1):
                batch.append(asset)
                processed_all += 1
                if idx % self._MERGE_PROGRESS_EVERY == 0 and idx != total:
                    db.poster.bulk_upsert(batch)
                    batch = []
                    self.logger.heartbeat(f"  Merged {idx} / {total} assets")
                    if total_all > 0:
                        merge_span = (
                            self._MERGE_PROGRESS_CEILING_PCT
                            - self._SYNC_PROGRESS_CEILING_PCT
                        )
                        self._report_progress(
                            self._SYNC_PROGRESS_CEILING_PCT
                            + int(processed_all / total_all * merge_span)
                        )
            if batch:
                db.poster.bulk_upsert(batch)

            self.logger.info(f"Finished merging {total} assets from '{source_dir}'")
        # Pin progress at the ceiling once all source_dirs are scanned so
        # subsequent phases visibly resume from a stable known point.
        self._report_progress(self._MERGE_PROGRESS_CEILING_PCT)

        duration = datetime.now() - start_time
        hours, remainder = divmod(duration.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        formatted_duration = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
        self.logger.info(f"Merge run time: {formatted_duration}")

    def _gdrive_match_locations(self) -> List[str]:
        """gdrive_list locations folded into poster matching — every drive
        except those flagged `search_only` (browse-only "Extras" drives).

        Typically all GDrives are match sources, so they're included by default
        with no per-drive config; the rare browse-only drive opts out via the
        search_only flag."""
        full_config = getattr(self, "full_config", None)
        sync_cfg = getattr(full_config, "sync_gdrive", None)
        gdrive_list = getattr(sync_cfg, "gdrive_list", None) or []
        out: List[str] = []
        for entry in gdrive_list:
            loc = (getattr(entry, "location", "") or "").strip()
            if loc and not getattr(entry, "search_only", False):
                out.append(loc)
        return out

    def _scan_source_dirs(self) -> List[str]:
        """Directories poster_renamerr scans AND matches: the configured local
        source_dirs plus every matchable gdrive_list location, deduped by
        realpath (first occurrence wins).

        A drive already listed in source_dirs keeps its position (and its
        bottom-wins priority); auto-included drives append after, so a GDrive
        contributor drive wins over a plain local fallback dir — the usual
        intent. See the GDrive-as-source design."""
        ordered = list(getattr(self.config, "source_dirs", []) or [])
        ordered += self._gdrive_match_locations()
        seen: set = set()
        out: List[str] = []
        for d in ordered:
            if not d:
                continue
            rp = os.path.realpath(d).rstrip("/")
            if rp in seen:
                continue
            seen.add(rp)
            out.append(d)
        return out

    def _matchable_source_dirs(self) -> List[str]:
        """Realpath'd dirs that own *matchable* rows — poster_renamerr's scan
        set (local source_dirs + matchable gdrive locations) plus
        asset_renamerr's source_dirs. A gdrive_list folder under any of these is
        already indexed by a renamer scan and is excluded from the search-only
        gdrive pass."""
        full_config = getattr(self, "full_config", None)
        ar_cfg = getattr(full_config, "asset_renamerr", None)
        covered = self._scan_source_dirs() + list(
            getattr(ar_cfg, "source_dirs", []) or []
        )
        seen: set = set()
        out: List[str] = []
        for sd in covered:
            if not sd:
                continue
            rp = os.path.realpath(sd).rstrip("/")
            if rp not in seen:
                seen.add(rp)
                out.append(rp)
        return out

    def merge_gdrive_search_index(self, db: ChubDB):
        """Index gdrive_list locations that aren't a renamer source_dir into
        poster_cache as SEARCH-ONLY rows.

        These assets (e.g. an "Extras" drive the user downloads but hasn't
        wired into poster_renamerr/asset_renamerr) become findable in Assets
        Search across ALL image types, while ``search_only=1`` keeps them out
        of poster matching/apply (see poster_cache.py match-phase queries).
        Folders already owned by a source_dir are skipped — whole-location when
        the gdrive folder is/under a source_dir, and per-file when a source_dir
        nests under the gdrive folder — so the matchable rows merge_assets just
        wrote are never shadowed.
        """
        full_config = getattr(self, "full_config", None)
        sync_cfg = getattr(full_config, "sync_gdrive", None)
        gdrive_list = getattr(sync_cfg, "gdrive_list", None) or []
        if not gdrive_list:
            return

        owned = self._matchable_source_dirs()

        def _is_owned(path: str) -> bool:
            rp = os.path.realpath(path).rstrip("/")
            return any(rp == sd or rp.startswith(sd + os.sep) for sd in owned)

        indexed = 0
        for entry in gdrive_list:
            loc = (getattr(entry, "location", "") or "").strip()
            if not loc or not os.path.isdir(loc) or _is_owned(loc):
                continue
            # include_assets=True: Assets Search wants every local image type
            # (posters AND logos/backgrounds/squareart), independent of whether
            # Asset Renamerr is enabled.
            assets = self._get_assets_files(
                loc, priority=0, include_assets=True, search_only=1
            )
            # Drop assets owned by a nested source_dir, then batch the rest.
            to_index = [a for a in assets if not _is_owned(a["file"])]
            if to_index:
                db.poster.bulk_upsert(to_index)
                indexed += len(to_index)
        if indexed:
            self.logger.info(
                f"Indexed {indexed} search-only asset(s) from gdrive_list "
                "locations outside source_dirs"
            )

    def _orphan_pass_scan_roots(self) -> List[str]:
        """The directories the post-rename orphan-asset pass walks.

        CONTRACT: destination_dir only. source_dirs are deliberately
        OUT OF SCOPE — they're either (a) gdrive-synced (any deleted
        file gets re-downloaded on the next sync, producing pure
        delete/restore churn) or (b) user-owned personal folders
        whose contents CHUB has no authority to remove. The only
        directory CHUB owns the lifecycle of is destination_dir, so
        that's the only place orphan cleanup acts.

        If a future refactor re-adds source_dirs here, the test
        tests/test_poster_renamerr.py::test_orphan_pass_scan_roots_excludes_source_dirs
        will fail. Read that test and the rationale above before
        "fixing" it — this scoping is the contract, not a bug.
        """
        return [self.config.destination_dir] if self.config.destination_dir else []

    def run_border_replacerr(
        self,
        manifest: Optional[dict],
        progress_window=None,
        process_all=False,
        manifest_only=False,
    ):
        from backend.modules.border_replacerr import BorderReplacerr

        if process_all:
            self.logger.debug(
                "\nRunning border replacerr (full-library pass — re-bordering "
                "all matched media and collections, including already-moved "
                "posters; manifest counts are not representative).\n"
            )
        else:
            self.logger.debug(
                "\nRunning border replacerr:\n"
                f"  Media assets to process: {len(manifest.get('media_cache', []))}\n"
                f"  Collection assets to process: {len(manifest.get('collections_cache', []))}\n"
                f"  Total assets to process: {len(manifest.get('media_cache', [])) + len(manifest.get('collections_cache', []))}\n"
            )

        border = BorderReplacerr(logger=self.logger)
        # Drive the parent bar's reserved slice as posters complete.
        if progress_window is not None:
            border.set_job_context(
                getattr(self, "_job_id", None), getattr(self, "_job_db", None)
            )
            border.set_progress_window(*progress_window)
        border.run(manifest, process_all=process_all, manifest_only=manifest_only)

        self.logger.info("Finished running border_replacerr.")

    def run_poster_rename_adhoc(self, media_items: List[dict]) -> dict:
        """
        Process specific media items directly.
        This is the method for webhook/API processing.

        Args:
            media_items: List of media items to process

        Returns:
            dict: Processing results with renamed files and manifest
        """
        log = self.logger.get_adapter("POSTER_ADHOC")

        if not media_items:
            return {"success": False, "message": "No media items provided"}

        try:
            with ChubDB(logger=self.logger) as db:
                self.ensure_destination_dir()

                # Clear and rebuild poster cache for current session. The lock
                # spans clear+rebuild+match: a concurrent clear (second webhook
                # worker or the scheduled run) must not empty the cache while
                # this run's per-item match reads it — the item lists here are
                # small webhook payloads, so holding it across the match+rename
                # loop is cheap (see _POSTER_CACHE_REBUILD_LOCK).
                with _POSTER_CACHE_REBUILD_LOCK:
                    db.poster.clear()
                    self.merge_assets(source_dirs=self._scan_source_dirs(), db=db)
                    # Index gdrive_list folders outside source_dirs as
                    # search-only so Assets Search covers all local assets.
                    self.merge_gdrive_search_index(db)

                    # Process each media item
                    output = {
                        "collection": [],
                        "movie": [],
                        "show": [],
                        "artist": [],
                        "album": [],
                    }
                    manifest = {"media_cache": [], "collections_cache": []}

                    matched_count = 0
                    for media_item in media_items:
                        # Match poster to media
                        is_collection = media_item.get("asset_type") == "collection"
                        match_result = self.match_item(media_item, db, is_collection)

                        if match_result["matched"]:
                            matched_count += 1
                            # Get the updated item from DB after matching
                            if is_collection:
                                updated_item = db.collection.get_by_id(
                                    media_item.get("id")
                                )
                            else:
                                updated_item = db.media.get_by_id(media_item.get("id"))

                            if updated_item:
                                # Rename the file
                                rename_result = self.rename_file(
                                    item=updated_item, db=db
                                )

                                if rename_result:
                                    asset_type = updated_item.get("asset_type", "movie")
                                    output.setdefault(asset_type, []).append(
                                        rename_result
                                    )

                                    # Add to manifest
                                    if asset_type == "collection":
                                        manifest["collections_cache"].append(
                                            updated_item["id"]
                                        )
                                    else:
                                        manifest["media_cache"].append(
                                            updated_item["id"]
                                        )

                log.info(
                    f"Processed {len(media_items)} media items, {matched_count} matched"
                )

                # No notification here. The sole caller (job_processor's
                # _adhoc_rename_and_post → _handle_post_rename_actions) sends ONE
                # OUTCOME notification after the poster actually lands in Plex (or
                # the kometa write). Notifying on the rename step too double-fired
                # a notification for every webhook.
                return {
                    "success": True,
                    "output": output,
                    "manifest": manifest,
                    "message": f"Successfully processed {matched_count}/{len(media_items)} items",
                    "stats": {
                        "total_items": len(media_items),
                        "matched_items": matched_count,
                        "renamed_items": sum(len(items) for items in output.values()),
                    },
                }

        except Exception as e:
            log.error(f"Error during adhoc poster rename: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Error during poster rename: {str(e)}",
            }

    def run(self):
        """
        Full scheduled run.

        Strict either/or apply pipeline (see PosterRenamerrConfig.apply_method):
          - "kometa": rename/copy posters into destination_dir for Kometa; no
            Plex upload.
          - "plex": stage posters in a temp dir (so the existing rename → border
            pipeline still works), upload them straight to Plex for instances
            whose per-instance add_posters opt-in is set, then discard the temp
            dir. destination_dir is not written.
        """
        apply_method = getattr(self.config, "apply_method", "kometa")
        try:
            # On the plex path this redirects output to a temp staging dir and
            # cleans it up on exit; on the kometa path it's a no-op.
            with self.apply_staging(), ChubDB(logger=self.logger) as db:
                if self.config.log_level == "debug":
                    print_settings(self.logger, self.config)

                self.ensure_destination_dir()

                if self.config.dry_run:
                    self.logger.info(
                        create_table([["Dry Run"], ["NO CHANGES WILL BE MADE"]])
                    )

                # Declare the pipeline phases this run will execute (gated by
                # config) so the Jobs page shows each sub-step and its timing.
                phase_plan = []
                if self.config.sync_posters:
                    phase_plan.append("sync_gdrive")
                phase_plan += [
                    "merge cache",
                    "arr/collections sync",
                    "match",
                    "match-quality",
                    "rename",
                ]
                if self.config.report_unmatched_assets:
                    phase_plan.append("unmatched report")
                if apply_method == "kometa" and self.config.clean_orphan_assets:
                    phase_plan.append("orphan cleanup")
                if self.config.run_border_replacerr:
                    phase_plan.append("border_replacerr")
                if apply_method == "plex":
                    phase_plan.append("plex upload")
                if self.config.run_asset_renamerr:
                    phase_plan.append("asset_renamerr")
                self._declare_phases(phase_plan)

                if self.config.sync_posters:
                    with self._phase("sync_gdrive"):
                        self.sync_posters()
                else:
                    self.sync_posters()

                # Serialized against the webhook adhoc rebuild (see
                # _POSTER_CACHE_REBUILD_LOCK) so a clear can't wipe rows the
                # other path just inserted.
                with self._phase("merge cache"), _POSTER_CACHE_REBUILD_LOCK:
                    self.logger.info("Clearing poster cache for rebuild")
                    db.poster.clear()
                    self.merge_assets(source_dirs=self._scan_source_dirs(), db=db)
                    # Index gdrive_list folders outside source_dirs as
                    # search-only so Assets Search covers all local assets.
                    self.merge_gdrive_search_index(db)
                    # Refresh planner stats before the match phase reads them.
                    db.poster.analyze()
                from backend.util.connector import build_instance_map

                with self._phase("arr/collections sync"):
                    connector = Connector(
                        db=db,
                        logger=self.logger,
                        instance_map=build_instance_map(self.config),
                    )
                    connector.update_arr_database()
                    connector.update_collections_database()

                # matching reads poster_cache per item; hold the rebuild lock so
                # a webhook clear() can't wipe it mid-match.
                with self._phase("match"), _POSTER_CACHE_REBUILD_LOCK:
                    self.match_assets_to_media(db=db)
                with self._phase("match-quality"):
                    self._run_match_quality_pass(db)
                # Post-rename tail allocation. rename always runs (small slice);
                # the heavy tail phases (border, asset) split the remainder so the
                # bar keeps advancing through them instead of pinning early. No
                # tail phase => rename runs the bar to 100 as before.
                _heavy = []
                if self.config.run_border_replacerr:
                    _heavy.append("border")
                if self.config.run_asset_renamerr:
                    _heavy.append("asset")
                rename_ceiling = 92 if _heavy else 100
                tail_windows: Dict[str, Tuple[int, int]] = {}
                if _heavy:
                    _span = (100 - rename_ceiling) / len(_heavy)
                    for _i, _name in enumerate(_heavy):
                        tail_windows[_name] = (
                            int(rename_ceiling + _i * _span),
                            int(rename_ceiling + (_i + 1) * _span),
                        )
                    # The last phase ends exactly at 100.
                    _last = _heavy[-1]
                    tail_windows[_last] = (tail_windows[_last][0], 100)
                with self._phase("rename"):
                    output, manifest = self.rename_files(
                        db, progress_ceiling=rename_ceiling
                    )

                if self.config.report_unmatched_assets:
                    from backend.modules.unmatched_assets import UnmatchedAssets

                    with self._phase("unmatched report"):
                        unmatched_reporter = UnmatchedAssets(logger=self.logger)
                        with ChubDB(logger=self.logger) as unmatched_db:
                            unmatched_reporter.print_stats(unmatched_db)

                # Orphan cleanup walks the on-disk destination_dir, so it only
                # applies to the kometa path (the plex path keeps no files).
                if apply_method == "kometa" and self.config.clean_orphan_assets:
                    from backend.modules.poster_cleanarr import (
                        run_orphan_assets_pass,
                    )

                    with self._phase("orphan cleanup"):
                        cleanarr_logger = Logger(self.config.log_level, "cleanarr")
                        allowed_roots = self._orphan_pass_scan_roots()
                        # In dry-run, force report mode regardless of configured
                        # action — never delete during a dry-run. Otherwise defer
                        # to Poster Cleanarr's mode so a single setting governs
                        # both the standalone Cleanarr run and Renamerr's
                        # post-rename orphan pass (mirrors how Renamerr triggers
                        # Border Replacerr — downstream module owns its policy).
                        cleanarr_cfg = getattr(
                            self.full_config, "poster_cleanarr", None
                        )
                        mode = (
                            "report"
                            if self.config.dry_run
                            else (
                                getattr(cleanarr_cfg, "orphan_assets_mode", "report")
                                or "report"
                            )
                        )
                        instance_names = list(self.config.instances) + [
                            s.instance for s in (self.config.plex_scope or [])
                        ]
                        run_orphan_assets_pass(
                            db=db,
                            instances=instance_names,
                            asset_dirs=allowed_roots,
                            mode=mode,
                            logger=cleanarr_logger,
                            include_collections=True,
                            ignore_titles=list(
                                getattr(cleanarr_cfg, "orphan_ignore_titles", []) or []
                            ),
                        )

                if self.config.run_border_replacerr:
                    with self._phase("border_replacerr"):
                        # kometa: full-library pass so a border-settings change
                        # re-borders the on-disk destination. plex: manifest
                        # subset ONLY — staged files are transient and only
                        # manifest assets upload; a full pass would re-encode
                        # Layer-A-skipped posters into dead temp paths from
                        # prior runs (leaking recreated dirs) for nothing.
                        self.run_border_replacerr(
                            manifest,
                            progress_window=tail_windows.get("border"),
                            process_all=(apply_method != "plex"),
                            manifest_only=(apply_method == "plex"),
                        )

                # Strict either/or: upload to Plex only on the "plex" path. The
                # uploader still gates per-instance on add_posters, so only
                # opted-in Plex servers receive the staged posters. The result
                # is kept: the notification below reports genuine uploads, not
                # the staged set.
                upload_result: Optional[Dict[str, Any]] = None
                if apply_method == "plex":
                    with self._phase("plex upload"):
                        upload_result = PosterUploader(
                            db=db, logger=self.logger, manifest=manifest
                        ).run()

                # Additional asset types (logo / squareart / background /
                # banner) ride this run when enabled: the gdrive sync, the single
                # image_type-aware merge_assets scan (poster_cache already holds
                # the asset rows), and the loaded media/Plex snapshot are all
                # reused, so no second sync/scan/fetch happens. See AssetRenamerr.
                if self.config.run_asset_renamerr:
                    from backend.modules.asset_renamerr import AssetRenamerr

                    with self._phase("asset_renamerr"):
                        self.logger.info("Running asset_renamerr")
                        asset_module = AssetRenamerr(logger=self.logger)
                        # Drive the reserved tail of the parent's bar so the %
                        # advances through this long phase instead of sitting at
                        # 100. No-ops cleanly when this run has no job context.
                        asset_module.set_job_context(
                            getattr(self, "_job_id", None),
                            getattr(self, "_job_db", None),
                        )
                        asset_module.set_progress_window(*tail_windows["asset"])
                        asset_output = asset_module.match_and_apply_assets(db)
                        # Same summary a standalone run prints. Without this the
                        # chained path emits nothing above DEBUG, so the artwork
                        # actually applied is invisible at the default log level.
                        asset_module.handle_output(asset_output)
                        self.logger.info("Finished running asset_renamerr")
                    # Notify under asset_renamerr so its own notification config
                    # governs (mirrors how each chained module owns its policy).
                    NotificationManager(
                        self.full_config, self.logger, module_name="asset_renamerr"
                    ).send_notification(asset_output)
                # Always notify on a successful run, even when nothing
                # happened — gives the user a heartbeat that the module fired.
                # kometa: the rename output IS the outcome (files written for
                # Kometa), notify from it as before. plex: notify ONLY the
                # posters the uploader genuinely pushed — staged-but-skipped
                # and failed posters stay in the logs, so re-flow retries
                # can't spam the notification every schedule. When nothing
                # uploaded, a one-line heartbeat replaces the poster list.
                if any(output.values()):
                    self.handle_output(output)
                notify_output: Dict[str, Any] = output
                if apply_method == "plex":
                    notify_output = self._build_plex_notify_output(upload_result)
                    if not any(notify_output.values()):
                        payload = (upload_result or {}).get("payload") or {}
                        failed = payload.get("failed", 0)
                        if (upload_result or {}).get("success"):
                            empty_text = "No posters were uploaded (nothing changed)."
                        elif failed:
                            empty_text = (
                                f"No posters were uploaded "
                                f"({failed} failed — check the logs)."
                            )
                        else:
                            reason = (upload_result or {}).get(
                                "message"
                            ) or "upload did not run"
                            empty_text = f"No posters were uploaded — {reason}"
                        notify_output["empty_text"] = empty_text
                manager = NotificationManager(
                    self.full_config, self.logger, module_name="poster_renamerr"
                )
                manager.send_notification(notify_output)

        except KeyboardInterrupt:
            self.logger.info("Keyboard Interrupt detected. Exiting...")
            return
        except Exception:
            self.logger.error("\n\nAn error occurred:\n", exc_info=True)
        finally:
            # Mark any declared-but-unreached phases skipped (e.g. an early
            # failure) so the Jobs timeline doesn't leave them stuck pending.
            self._finalize_phases()
            self.logger.log_outro()
