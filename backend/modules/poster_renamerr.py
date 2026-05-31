# modules/poster_renamerr.py

import filecmp
import json
import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.util.base_module import ChubModule
from backend.util.connector import Connector
from backend.util.constants import (
    asset_type_regex,
    illegal_chars_regex,
    season_number_regex,
)
from backend.util.database import ChubDB
from backend.util.helper import (
    classify_match,
    create_table,
    extract_ids,
    extract_year,
    is_match,
    normalize_titles,
    print_settings,
    progress,
)
from backend.util.normalization import parse_asset_filename
from backend.util.logger import Logger
from backend.util.notification import NotificationManager
from backend.util.upload_posters import PosterUploader


def build_asset_record(
    fname: str, root: str, style: Optional[str] = None, priority: int = 0
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
    """
    folder = os.path.basename(root)
    filename, ext = os.path.splitext(fname)

    m = asset_type_regex.search(filename)
    if m:
        image_type = m.group(1).lower()
        # Strip the type tag, then re-attach the real extension so
        # parse_asset_filename's own splitext targets the extension (not a dot
        # inside a title like "8 A.M. Metro").
        base = asset_type_regex.sub("", filename).strip(" -_")
        title = parse_asset_filename(base + ext)
        normalized_title = normalize_titles(base)
    else:
        image_type = "poster"
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
    }


class PosterRenamerr(ChubModule):
    def __init__(self, logger: Optional[Logger] = None) -> None:
        super().__init__(logger=logger)

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

                SyncGDrive(logger=self.logger).run()
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
                shutil.copy(file, new_file_path)
            elif action_type == "move":
                shutil.move(file, new_file_path)
            elif action_type == "hardlink":
                os.link(file, new_file_path)
            elif action_type == "symlink":
                os.symlink(file, new_file_path)
            # Per-file action trace — visible when log_level: debug.
            # Single source of truth so every call site (rename_file,
            # future orphan cleanup, etc.) logs the same shape.
            self.logger.debug(
                f"[{action_type.upper()}] {new_file_path} ← {file}"
            )
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

        for id_field in ["imdb_id", "tmdb_id", "tvdb_id"]:
            id_val = media.get(id_field)
            if id_val:
                c = db.poster.get_by_id(
                    id_field,
                    id_val,
                    season_number,
                    asset_type=expected_asset_type,
                    image_type=image_type,
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
                    st, asset_type=expected_asset_type, image_type=image_type
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

        if is_collection:
            db.collection.update(
                title=title,
                year=year,
                library_name=library_name,
                instance_name=instance_name,
                matched_value=matched,
                original_file=candidate.get("file") if candidate else None,
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
                original_file=candidate.get("file") if candidate else None,
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
        if is_collection:
            db.collection.set_match_provenance(media.get("id"), new_matched_at, new_file)
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
        all_media = []

        for inst in self.config.instances:
            if isinstance(inst, str):
                instance_name = inst
                media = db.media.get_by_instance(instance_name)
                if media:
                    all_media.extend(media)
            elif isinstance(inst, dict):
                for instance_name, params in inst.items():
                    library_names = params.library_names
                    if library_names:
                        for library_name in library_names:
                            collections = db.collection.get_by_instance_and_library(
                                instance_name, library_name
                            )
                            if collections:
                                all_media.extend(collections)
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
        file_extension = os.path.splitext(file)[1]
        season_number = item.get("season_number")
        config = self.config

        if config.asset_folders:
            dest_dir = os.path.join(config.destination_dir, folder)
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
        else:
            dest_dir = config.destination_dir

        if asset_type == "show" and season_number is not None:
            season_str = str(season_number).zfill(2)
            if config.asset_folders:
                new_file_name = f"Season{season_str}{file_extension}"
            else:
                new_file_name = f"{folder}_Season{season_str}{file_extension}"
            new_file_path = os.path.join(dest_dir, new_file_name)
        else:
            if config.asset_folders:
                new_file_name = f"poster{file_extension}"
            else:
                new_file_name = f"{folder}{file_extension}"
            new_file_path = os.path.join(dest_dir, new_file_name)

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
        for inst in self.config.instances:
            if isinstance(inst, str):
                instance_name = inst
                for row in db.media.get_by_instance(instance_name):
                    if row.get("matched") and (
                        not row.get("renamed_file")
                        or not os.path.exists(row.get("renamed_file"))
                    ):
                        matched_assets.append(row)
            elif isinstance(inst, dict):
                for instance_name, params in inst.items():
                    library_names = params.library_names
                    if library_names:
                        for library_name in library_names:
                            for row in db.collection.get_by_instance_and_library(
                                instance_name, library_name
                            ):
                                if row.get("matched") and (
                                    not row.get("renamed_file")
                                    or not os.path.exists(row.get("renamed_file"))
                                ):
                                    matched_assets.append(row)
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

    def rename_files(self, db: ChubDB) -> tuple:
        output: Dict[str, List[Dict[str, Any]]] = {
            "collection": [],
            "movie": [],
            "show": [],
        }
        manifest = {"media_cache": [], "collections_cache": []}
        matched_assets = self.get_matched_assets(db=db)

        if matched_assets:
            self.logger.info("Renaming assets please wait...")
            total = len(matched_assets)
            rename_span = 100 - self._MATCH_PROGRESS_CEILING_PCT
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
                        output[item.get("asset_type", "movie")].append(result)

                    if item.get("asset_type") == "collection":
                        manifest["collections_cache"].append(item.get("id"))
                    else:
                        manifest["media_cache"].append(item.get("id"))

                    if idx % self._RENAME_PROGRESS_EVERY == 0 and idx != total:
                        self._report_progress(
                            self._MATCH_PROGRESS_CEILING_PCT
                            + int(idx / total * rename_span)
                        )
        # Final pin at 100 — covered by job_processor's completion path too,
        # but explicit here keeps the ladder symmetric with merge/match.
        self._report_progress(100)
        return output, manifest

    def handle_output(self, output: Dict[str, List[Dict[str, Any]]]):
        headers = {"collection": "Collection", "movie": "Movie", "show": "Show"}
        for asset_type in ["collection", "movie", "show"]:
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
        if record.get("season_number") is not None or record.get("tvdb_id"):
            return "show"

        key = (record.get("normalized_title"), record.get("year"))
        if record.get("year") is not None and key in show_keys:
            return "show"

        if record.get("year") is None:
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
        self, source_dir: str, priority: int = 0, include_assets: bool = False
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
                if not fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    continue
                record = build_asset_record(
                    fname, root, style=style, priority=priority
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
        source_dirs = source_dirs or self.config.source_dirs

        # Plan the progress curve: count total assets across all source_dirs
        # up front so each per-asset write contributes a proportional slice.
        # The dir-walk to count is fast (no DB ops) and lets us update job
        # progress smoothly instead of in big steps per source_dir.
        per_dir_assets = []
        total_all = 0
        for idx, source_dir in enumerate(source_dirs):
            if self.is_cancelled():
                break
            assets = self._get_assets_files(
                source_dir,
                priority=idx,
                include_assets=getattr(self.config, "run_asset_renamerr", False),
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

            for idx, asset in enumerate(assets, 1):
                # The cache mirrors disk 1:1: one row per file in source_dirs.
                # db.poster.clear() ran before this merge, and the UNIQUE
                # constraint on (..., file) prevents duplicate-path inserts,
                # so we just upsert each parsed file as-is. No title-based
                # dedup (which previously wiped distinct shows sharing a
                # normalized title, e.g. The Traitors UK vs AU) and no
                # ID backfill from other rows (a row's fields should reflect
                # only what its own filename/folder yielded; ID inference
                # belongs in the match-to-media phase, not here).
                db.poster.upsert(asset)

                processed_all += 1
                if idx % self._MERGE_PROGRESS_EVERY == 0 and idx != total:
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

            self.logger.info(f"Finished merging {total} assets from '{source_dir}'")
        # Pin progress at the ceiling once all source_dirs are scanned so
        # subsequent phases visibly resume from a stable known point.
        self._report_progress(self._MERGE_PROGRESS_CEILING_PCT)

        duration = datetime.now() - start_time
        hours, remainder = divmod(duration.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        formatted_duration = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
        self.logger.info(f"Merge run time: {formatted_duration}")

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

    def run_border_replacerr(self, manifest: dict):
        from backend.modules.border_replacerr import BorderReplacerr

        self.logger.debug(
            "\nRunning border replacerr:\n"
            f"  Media assets to process: {len(manifest.get('media_cache', []))}\n"
            f"  Collection assets to process: {len(manifest.get('collections_cache', []))}\n"
            f"  Total assets to process: {len(manifest.get('media_cache', [])) + len(manifest.get('collections_cache', []))}\n"
        )

        BorderReplacerr(logger=self.logger).run(manifest)

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

                # Clear and rebuild poster cache for current session
                db.poster.clear()
                self.merge_assets(source_dirs=self.config.source_dirs, db=db)

                # Process each media item
                output = {"collection": [], "movie": [], "show": []}
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
                            updated_item = db.collection.get_by_id(media_item.get("id"))
                        else:
                            updated_item = db.media.get_by_id(media_item.get("id"))

                        if updated_item:
                            # Rename the file
                            rename_result = self.rename_file(item=updated_item, db=db)

                            if rename_result:
                                asset_type = updated_item.get("asset_type", "movie")
                                output[asset_type].append(rename_result)

                                # Add to manifest
                                if asset_type == "collection":
                                    manifest["collections_cache"].append(
                                        updated_item["id"]
                                    )
                                else:
                                    manifest["media_cache"].append(updated_item["id"])

                log.info(
                    f"Processed {len(media_items)} media items, {matched_count} matched"
                )

                # Always notify on webhook/API-driven adhoc imports so
                # the user has awareness — the trigger is asynchronous
                # and the UI may not be open. The formatter handles the
                # empty-output case with a clean "No files were renamed."
                # field, so a webhook that matched zero new media still
                # produces a small confirmation message rather than
                # silence.
                try:
                    manager = NotificationManager(
                        self.full_config,
                        self.logger,
                        module_name="poster_renamerr",
                    )
                    manager.send_notification(output)
                except Exception as e:
                    log.debug(f"adhoc poster_renamerr notification failed: {e}")

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
        Full scheduled run - existing functionality unchanged.
        """
        try:
            with ChubDB(logger=self.logger) as db:
                if self.config.log_level == "debug":
                    print_settings(self.logger, self.config)

                self.ensure_destination_dir()

                if self.config.dry_run:
                    self.logger.info(
                        create_table([["Dry Run"], ["NO CHANGES WILL BE MADE"]])
                    )

                self.sync_posters()

                db.poster.clear()
                self.merge_assets(source_dirs=self.config.source_dirs, db=db)
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

                self.match_assets_to_media(db=db)
                self._run_match_quality_pass(db)
                output, manifest = self.rename_files(db)

                if self.config.report_unmatched_assets:
                    from backend.modules.unmatched_assets import UnmatchedAssets

                    unmatched_reporter = UnmatchedAssets(logger=self.logger)
                    with ChubDB(logger=self.logger) as unmatched_db:
                        unmatched_reporter.print_stats(unmatched_db)

                if self.config.clean_orphan_assets:
                    from backend.modules.poster_cleanarr import (
                        run_orphan_assets_pass,
                    )

                    cleanarr_logger = Logger(self.config.log_level, "cleanarr")
                    allowed_roots = self._orphan_pass_scan_roots()
                    # In dry-run, force report mode regardless of configured
                    # action — never delete during a dry-run. Otherwise defer
                    # to Poster Cleanarr's mode so a single setting governs
                    # both the standalone Cleanarr run and Renamerr's
                    # post-rename orphan pass (mirrors how Renamerr triggers
                    # Border Replacerr — downstream module owns its policy).
                    cleanarr_cfg = getattr(self.full_config, "poster_cleanarr", None)
                    mode = (
                        "report"
                        if self.config.dry_run
                        else (
                            getattr(cleanarr_cfg, "orphan_assets_mode", "report")
                            or "report"
                        )
                    )
                    instance_names = [
                        name
                        for entry in (self.config.instances or [])
                        for name in (
                            [entry] if isinstance(entry, str) else list(entry.keys())
                        )
                    ]
                    run_orphan_assets_pass(
                        db=db,
                        instances=instance_names,
                        asset_dirs=allowed_roots,
                        mode=mode,
                        logger=cleanarr_logger,
                        include_collections=True,
                    )

                if self.config.run_border_replacerr:
                    self.run_border_replacerr(manifest)

                PosterUploader(db=db, logger=self.logger, manifest=manifest).run()

                # Additional asset types (clear logo / squareart / background /
                # banner) ride this run when enabled: the gdrive sync, the single
                # image_type-aware merge_assets scan (poster_cache already holds
                # the asset rows), and the loaded media/Plex snapshot are all
                # reused, so no second sync/scan/fetch happens. See AssetRenamerr.
                if self.config.run_asset_renamerr:
                    from backend.modules.asset_renamerr import AssetRenamerr

                    self.logger.info("Running asset_renamerr")
                    asset_output = AssetRenamerr(
                        logger=self.logger
                    ).match_and_apply_assets(db)
                    self.logger.info("Finished running asset_renamerr")
                    # Notify under asset_renamerr so its own notification config
                    # governs (mirrors how each chained module owns its policy).
                    NotificationManager(
                        self.full_config, self.logger, module_name="asset_renamerr"
                    ).send_notification(asset_output)
                # Always notify on a successful run, even when nothing
                # was renamed — gives the user a heartbeat that the
                # module fired. The formatter handles the empty-output
                # case with a clean "No files were renamed." field.
                if any(output.values()):
                    self.handle_output(output)
                manager = NotificationManager(
                    self.full_config, self.logger, module_name="poster_renamerr"
                )
                manager.send_notification(output)

        except KeyboardInterrupt:
            print("Keyboard Interrupt detected. Exiting...")
            return
        except Exception:
            self.logger.error("\n\nAn error occurred:\n", exc_info=True)
        finally:
            self.logger.log_outro()
