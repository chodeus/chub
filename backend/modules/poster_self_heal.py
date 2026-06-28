# backend/modules/poster_self_heal.py
"""poster_self_heal module — scheduled drift detection for CL2K posters.

The run() scans the CL2K maker's OWN posters (those under its ``output_dir``;
other owners' synced-in CL2K drives share the style tag but are skipped),
re-resolves each against
TMDB (bridging stale ids through media_cache), and upserts proposals into
poster_heal_review. By default it only DETECTS (proposals wait for manual review
via backend/api/poster_self_heal.py). With ``auto_apply`` on, confident proposals
are renamed immediately (Drive + local); ambiguous matches always wait for a
manual pick. A run sends a Discord notification summarising the outcome.
"""

import os

from backend.util.base_module import ChubModule
from backend.util.database import ChubDB
from backend.util.database.poster_heal_review import poster_heal_review_for
from backend.util.notification import NotificationManager
from backend.util.poster_self_heal.apply import apply_proposal
from backend.util.poster_self_heal.resolver import index_media, resolve_poster
from backend.util.tmdb import TMDBClient

_HEAL_KINDS = ("movie", "show")


def _is_under(path: str, base_dir: str) -> bool:
    """True if ``path`` lives inside ``base_dir`` (or equals it). Scopes the heal
    to the CL2K maker's own ``output_dir`` so synced-in CL2K posters from other
    owners' drives (same ``style`` tag, different folder) are left alone."""
    if not path or not base_dir:
        return False
    base = os.path.normpath(base_dir)
    p = os.path.normpath(path)
    return p == base or p.startswith(base + os.sep)


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
        folder_id = (getattr(cl2k, "gdrive_folder_id", "") or "").strip() or None
        output_dir = (getattr(cl2k, "output_dir", "") or "").strip()
        if not output_dir:
            self.logger.error(
                "CL2K maker output_dir is not set — poster_self_heal can't tell "
                "your own posters from synced-in CL2K posters (every synced "
                "'CL2K <owner>' drive shares the same style tag). Set it under "
                "Settings → Modules → CL2K Maker; nothing scanned."
            )
            return

        with ChubDB(self.logger) as db:
            tmdb_client = TMDBClient(self.full_config.tmdb, db, self.logger)
            if not tmdb_client.enabled:
                self.logger.error(
                    "TMDB API key not set — poster_self_heal needs TMDB to resolve "
                    "canonical ids/titles. Set it under Settings → Modules → TMDB."
                )
                return

            # Scope to the user's OWN CL2K output (output_dir) — NOT every poster
            # carrying the shared "CL2K" style tag, which also covers other
            # owners' "CL2K <name>" drives synced into the cache.
            posters = [
                p
                for p in db.poster.get_all()
                if p.get("style") == style
                and p.get("asset_type") in _HEAL_KINDS
                and _is_under(p.get("file"), output_dir)
            ]
            media_index = index_media(db.media.get_all())
            reviews = poster_heal_review_for(db)

            # Drop open proposals no longer in scope (e.g. left by an earlier,
            # broader scan) so the queue only ever holds output_dir posters.
            pruned = 0
            for row in reviews.list_open(limit=1_000_000):
                if not _is_under(row.get("poster_file"), output_dir):
                    reviews.delete(row["id"])
                    pruned += 1
            if pruned:
                self.logger.info(
                    f"poster_self_heal: pruned {pruned} out-of-scope proposal(s)"
                )

            auto = bool(getattr(self.config, "auto_apply", False))
            sync_cfg = self.full_config.sync_gdrive
            total = len(posters)
            self.logger.info(
                f"poster_self_heal: scanning {total} CL2K posters under "
                f"{output_dir} (style={style!r})"
                f"{' [auto-apply ON]' if auto else ''}"
            )
            proposed = pending = applied = failed = 0
            for idx, poster in enumerate(posters, 1):
                if self.is_cancelled():
                    self.logger.info("poster_self_heal cancelled.")
                    break
                try:
                    prop = resolve_poster(
                        poster, media_index, folder_id, tmdb_client, self.config
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
                    if auto and prop["status"] == "proposed":
                        try:
                            note = apply_proposal(prop, sync_cfg, self.logger)
                            prop["status"] = "applied"
                            applied += 1
                            self.logger.info(
                                f"auto-applied {prop['proposed_filename']}{note}"
                            )
                        except Exception as exc:
                            failed += 1
                            self.logger.warning(
                                f"auto-apply failed for {prop['current_filename']}: {exc}"
                                " — left for manual review"
                            )
                    if prop["status"] == "pending":
                        pending += 1
                    elif prop["status"] == "proposed":
                        proposed += 1
                    reviews.upsert(prop)
                if total:
                    self._report_progress(int(idx / total * 100))

            self.logger.info(
                f"poster_self_heal done: {applied} auto-applied, {proposed} proposed, "
                f"{pending} need a manual pick, {failed} failed; "
                f"{reviews.open_count()} open for review total"
            )

            if applied or proposed or pending:
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
