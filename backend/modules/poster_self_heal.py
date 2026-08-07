# backend/modules/poster_self_heal.py
"""poster_self_heal module — scheduled drift detection for CL2K posters.

The run() scans the CL2K maker's OWN posters from two sources — locally-saved
ones in poster_cache scoped to its ``local_folders`` paths (other owners'
synced-in CL2K drives share the style tag but are skipped), and live listings
of every linked ``gdrive_uploads`` folder (the source of truth for a Drive-only
setup, where posters were never recorded in poster_cache). It re-resolves each
against
TMDB (bridging stale ids through media_cache), and upserts proposals into
poster_heal_review. By default it only DETECTS (proposals wait for manual review
via backend/api/poster_self_heal.py). With ``auto_apply`` on, confident proposals
are renamed immediately (Drive + local); ambiguous matches always wait for a
manual pick. A run sends a Discord notification summarising the outcome.
"""

import os

from backend.util.base_module import ChubModule
from backend.util.cl2k.gdrive_upload import list_files
from backend.util.database import ChubDB
from backend.util.database.poster_heal_review import poster_heal_review_for
from backend.util.notification import NotificationManager
from backend.util.poster_self_heal.apply import apply_proposal
from backend.util.poster_self_heal.cache_reconcile import drop_stale_row
from backend.util.poster_self_heal.resolver import (
    index_media,
    poster_from_filename,
    resolve_poster,
)
from backend.util.tmdb import TMDBClient

_HEAL_KINDS = ("movie", "show")


def _is_under(path: str, base_dir: str) -> bool:
    """True if ``path`` lives inside ``base_dir`` (or equals it). Scopes the heal
    to the CL2K maker's own ``local_folders`` so synced-in CL2K posters from other
    owners' drives (same ``style`` tag, different folder) are left alone."""
    if not path or not base_dir:
        return False
    base = os.path.normpath(base_dir)
    p = os.path.normpath(path)
    return p == base or p.startswith(base + os.sep)


def local_dirs_for(cl2k) -> list:
    """Local folders the heal is scoped to: every non-blank ``local_folders``
    path, deduped in config order. ``types`` is deliberately NOT consulted — an
    inert routing row is still scanned."""
    out: list = []
    for folder in getattr(cl2k, "local_folders", None) or []:
        path = (getattr(folder, "path", "") or "").strip()
        if path and path not in out:
            out.append(path)
    return out


def should_auto_apply(prop, auto: bool, dismissed_files) -> bool:
    """Whether this run may rename ``prop`` without asking.

    False for a dismissed poster_file: "dismissed" is documented as terminal and
    sticky, and the upsert CASE only keeps it out of the review queue — without
    this it would still be renamed on disk and on Drive.
    """
    if not auto or prop.get("status") != "proposed":
        return False
    return prop.get("poster_file") not in dismissed_files


def drive_twins(cl2k) -> tuple:
    """``(drive_ids, twin_of)``; ``twin_of(image_type)`` resolves to the first
    ``gdrive_uploads`` entry claiming that type, else the poster Drive, else the
    first Drive."""
    drive_ids: list = []
    by_type: dict = {}
    for drive in getattr(cl2k, "gdrive_uploads", None) or []:
        fid = (getattr(drive, "folder_id", "") or "").strip()
        if not fid:
            continue
        if fid not in drive_ids:
            drive_ids.append(fid)
        for image_type in getattr(drive, "types", None) or []:
            by_type.setdefault(image_type, fid)
    fallback = by_type.get("poster") or (drive_ids[0] if drive_ids else None)

    def twin_of(image_type):
        return by_type.get(image_type or "poster", fallback)

    return drive_ids, twin_of


class PosterSelfHeal(ChubModule):
    """Detect stale ids / changed titles / missing ids on CL2K posters."""

    def run(self) -> None:
        cl2k = getattr(self.full_config, "cl2k_maker", None)
        if cl2k is None:
            self.logger.error(
                "CL2K maker config not found — poster_self_heal needs the CL2K "
                "extension; nothing to scan."
            )
            return

        style = (getattr(cl2k, "style", "") or "CL2K").strip()
        local_dirs = local_dirs_for(cl2k)
        drive_ids, twin_of = drive_twins(cl2k)
        if not local_dirs and not drive_ids:
            self.logger.error(
                "CL2K maker has no local folders or Drive uploads configured — "
                "poster_self_heal heals the CL2K posters it can see: locally-saved "
                "ones (tracked in poster_cache under a local folder) and/or ones "
                "in a linked Drive folder. Add at least one under Settings → "
                "Modules → CL2K Maker. Nothing scanned."
            )
            return

        sync_cfg = self.full_config.sync_gdrive
        auto = bool(getattr(self.config, "auto_apply", False))

        with ChubDB(self.logger) as db:
            tmdb_client = TMDBClient(self.full_config.tmdb, db, self.logger)
            if not tmdb_client.enabled:
                self.logger.error(
                    "TMDB API key not set — poster_self_heal needs TMDB to resolve "
                    "canonical ids/titles. Set it under Settings → Modules → TMDB."
                )
                return

            # LOCAL source — the user's OWN CL2K output (any configured local
            # folder), NOT every poster carrying the shared "CL2K" style tag
            # (that also covers other owners' "CL2K <name>" drives synced into
            # the cache).
            local_posters = (
                [
                    p
                    for p in db.poster.get_all()
                    if p.get("style") == style
                    and p.get("asset_type") in _HEAL_KINDS
                    and any(_is_under(p.get("file"), d) for d in local_dirs)
                ]
                if local_dirs
                else []
            )
            local_names = {os.path.basename(p.get("file") or "") for p in local_posters}

            # LIVE-DRIVE source — posters living in any linked Drive folder. The
            # source of truth for a Drive-only setup (no local copy in
            # poster_cache). Skip names a local row already covers (its apply
            # renames the Drive copy too) and names an earlier folder already
            # yielded (one proposal per filename). A listing failure logs a
            # warning and yields []. Each poster keeps the folder it was found
            # in so apply renames the right Drive copy.
            drive_posters = []
            seen_names = set(local_names)
            for fid in drive_ids:
                for name in list_files(fid, sync_cfg, self.logger):
                    base = os.path.basename(name)
                    if base in seen_names:
                        continue
                    parsed = poster_from_filename(base)
                    if parsed:
                        seen_names.add(base)
                        drive_posters.append((parsed, fid))

            # Local rows heal the Drive twin that receives their own image_type.
            posters = [
                (p, twin_of(p.get("image_type"))) for p in local_posters
            ] + drive_posters
            media_index = index_media(db.media.get_all())
            reviews = poster_heal_review_for(db)

            # Drop open proposals from an earlier, broader scan — absolute local
            # paths outside every configured folder (e.g. other owners' synced
            # posters, or a folder since removed). Live-Drive proposals carry a
            # bare filename (not absolute), so they're kept.
            pruned = 0
            if local_dirs:
                for row in reviews.list_open(limit=1_000_000):
                    pf = row.get("poster_file") or ""
                    if os.path.isabs(pf) and not any(
                        _is_under(pf, d) for d in local_dirs
                    ):
                        reviews.delete(row["id"])
                        pruned += 1
            if pruned:
                self.logger.info(
                    f"poster_self_heal: pruned {pruned} out-of-scope proposal(s)"
                )

            total = len(posters)
            self.logger.info(
                f"poster_self_heal: scanning {total} CL2K posters "
                f"({len(local_posters)} local"
                f"{f' under {len(local_dirs)} folder(s)' if local_dirs else ''}, "
                f"{len(drive_posters)} on Drive)"
                f"{' [auto-apply ON]' if auto else ''}"
            )
            proposed = pending = applied = failed = dismissed = 0
            # "dismissed" is documented as terminal and sticky, so auto-apply must
            # not act on one. The upsert CASE only keeps it out of the review
            # queue; without this it would still be renamed on disk and on Drive,
            # which is the opposite of what the user asked for. Read once — the
            # loop can run to tens of thousands of posters.
            dismissed_files = reviews.dismissed_files() if auto else set()
            for idx, (poster, heal_folder_id) in enumerate(posters, 1):
                if self.is_cancelled():
                    self.logger.info("poster_self_heal cancelled.")
                    break
                try:
                    prop = resolve_poster(
                        poster, media_index, heal_folder_id, tmdb_client, self.config
                    )
                except Exception as exc:
                    self.logger.warning(
                        f"poster_self_heal: resolve failed for {poster.get('file')}: {exc}",
                        exc_info=True,
                    )
                    prop = None
                if prop:
                    self.logger.debug(
                        f"[{prop['drift_type']}] {prop['current_filename']} -> "
                        f"{prop['proposed_filename']}"
                    )
                    # Auto-apply confident proposals when enabled; ambiguous
                    # (pending) ones always wait for a manual pick.
                    apply_error = None
                    skipped = auto and prop["poster_file"] in dismissed_files
                    if skipped:
                        dismissed += 1
                        self.logger.debug(
                            f"skipping dismissed {prop['current_filename']}"
                        )
                    elif should_auto_apply(prop, auto, dismissed_files):
                        try:
                            note = apply_proposal(prop, sync_cfg, self.logger)
                            prop["status"] = "applied"
                            applied += 1
                            self.logger.info(
                                f"auto-applied {prop['proposed_filename']}{note}"
                            )
                        except Exception as exc:
                            apply_error = str(exc)
                            failed += 1
                            self.logger.warning(
                                f"auto-apply failed for {prop['current_filename']}: {exc}"
                                " — reopened for manual review"
                            )
                    # A failed apply is counted ONCE, as failed: its status is
                    # still "proposed" here, and counting it again below reported
                    # two items as four. A dismissed skip isn't open either.
                    if apply_error is None and not skipped:
                        if prop["status"] == "pending":
                            pending += 1
                        elif prop["status"] == "proposed":
                            proposed += 1
                    reviews.upsert(prop)
                    if apply_error is not None:
                        # upsert's CASE keeps a terminal status, so a row that was
                        # already "applied" would stay invisible — force it open.
                        reviews.mark_failed(prop["poster_file"], apply_error)
                    elif prop["status"] == "applied":
                        # The rename moved the file out from under the index that
                        # produced this proposal. Drop the stale row or the next
                        # run re-proposes a rename whose target now exists — which
                        # fails forever, since the collision is our own doing.
                        stale = prop.get("poster_file") or ""
                        if os.path.isabs(stale):
                            drop_stale_row(db, stale, self.logger)
                if total:
                    self._report_progress(int(idx / total * 100))

            self.logger.info(
                f"poster_self_heal done: {applied} auto-applied, {proposed} proposed, "
                f"{pending} need a manual pick, {failed} failed"
                f"{f', {dismissed} skipped (dismissed)' if dismissed else ''}; "
                f"{reviews.open_count()} open for review total"
            )

            # Failures notify too — a run whose only outcome is failures is
            # exactly the one worth telling the user about.
            if applied or proposed or pending or failed:
                output = {
                    "scanned": total,
                    "applied": applied,
                    "proposed": proposed,
                    "pending": pending,
                    "failed": failed,
                    "open": reviews.open_count(),
                }
                try:
                    NotificationManager(
                        self.full_config, self.logger, module_name="poster_self_heal"
                    ).send_notification(output)
                except Exception as exc:
                    self.logger.error(f"Failed to send notification: {exc}")
