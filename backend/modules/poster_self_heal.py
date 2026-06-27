# backend/modules/poster_self_heal.py
"""poster_self_heal module — scheduled drift detection for CL2K posters.

The run() does DETECTION only: it scans the CL2K-styled posters in poster_cache,
re-resolves each against TMDB (bridging stale ids through media_cache), and
upserts proposals into poster_heal_review. Applying a proposal is a separate,
manually-reviewed action (backend/api/poster_self_heal.py), so a run never
touches a file on its own.
"""

from backend.util.base_module import ChubModule
from backend.util.database import ChubDB
from backend.util.database.poster_heal_review import poster_heal_review_for
from backend.util.poster_self_heal.resolver import index_media, resolve_poster
from backend.util.tmdb import TMDBClient

_HEAL_KINDS = ("movie", "show")


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

        with ChubDB(self.logger) as db:
            tmdb_client = TMDBClient(self.full_config.tmdb, db, self.logger)
            if not tmdb_client.enabled:
                self.logger.error(
                    "TMDB API key not set — poster_self_heal needs TMDB to resolve "
                    "canonical ids/titles. Set it under Settings → Modules → TMDB."
                )
                return

            posters = [
                p
                for p in db.poster.get_all()
                if p.get("style") == style and p.get("asset_type") in _HEAL_KINDS
            ]
            media_index = index_media(db.media.get_all())
            reviews = poster_heal_review_for(db)

            total = len(posters)
            self.logger.info(
                f"poster_self_heal: scanning {total} CL2K posters (style={style!r})"
            )
            proposed = pending = 0
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
                    reviews.upsert(prop)
                    if prop["status"] == "pending":
                        pending += 1
                    else:
                        proposed += 1
                    self.logger.debug(
                        f"[{prop['drift_type']}] {prop['current_filename']} -> "
                        f"{prop['proposed_filename']}"
                    )
                if total:
                    self._report_progress(int(idx / total * 100))

            self.logger.info(
                f"poster_self_heal done: {proposed} proposed, {pending} need a manual "
                f"pick, {reviews.open_count()} open for review total"
            )
