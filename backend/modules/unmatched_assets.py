# modules/unmatched_assets.py

from typing import Any, Dict, List, Optional

from backend.util.base_module import ChubModule
from backend.util.database import ChubDB
from backend.util.logger import Logger
from backend.util.notification import NotificationManager
from backend.util.release_readiness import is_release_ready


class UnmatchedAssets(ChubModule):
    def __init__(self, logger: Optional[Logger] = None) -> None:
        """
        Standard constructor using dependency injection.

        Args:
            config: Complete CHUB configuration object
            logger: Logger instance
        """
        super().__init__(logger=logger)

        self.allowed_instances: set = set()
        self.plex_libraries: Dict[str, set] = {}

        self.unmatched_media: List[Dict] = []
        self.unmatched_collections: List[Dict] = []
        self.all_media: List[Dict] = []
        self.all_collections: List[Dict] = []

    def fetch_data(self, db: ChubDB) -> None:
        self.unmatched_media = db.media.get_unmatched()
        self.unmatched_collections = db.collection.get_unmatched()
        self.all_media = db.media.get_all()
        self.all_collections = db.collection.get_all()

    def compute_instance_filters(self) -> None:
        for inst in getattr(self.config, "instances", []):
            if isinstance(inst, str):
                self.allowed_instances.add(inst)
            elif isinstance(inst, dict):
                for instance_name, params in inst.items():
                    self.allowed_instances.add(instance_name)
                    libs = set(params.get("library_names", []))
                    if libs:
                        self.plex_libraries[instance_name] = libs

    def allowed_media(self, asset: Dict[str, Any]) -> bool:
        inst = asset.get("instance_name")
        return bool(inst and inst in self.allowed_instances)

    def allowed_collection(self, asset: Dict[str, Any]) -> bool:
        inst = asset.get("instance_name")
        lib = asset.get("library_name")
        if inst not in self.allowed_instances:
            return False
        if inst in self.plex_libraries:
            if lib not in self.plex_libraries[inst]:
                return False
        ignore_collections = getattr(self.config, "ignore_collections", [])
        if ignore_collections and asset.get("title") in ignore_collections:
            return False
        return True

    def filter_by_instance(self) -> None:
        self.unmatched_media = [
            a for a in self.unmatched_media if self.allowed_media(a)
        ]
        self.unmatched_collections = [
            a for a in self.unmatched_collections if self.allowed_collection(a)
        ]
        self.all_media = [a for a in self.all_media if self.allowed_media(a)]
        self.all_collections = [
            a for a in self.all_collections if self.allowed_collection(a)
        ]

    def should_include(self, asset: Dict[str, Any]) -> bool:
        cfg = self.config
        # User-dismissed rows never appear in unmatched/review reports.
        if asset.get("ignored"):
            return False
        # Release-readiness gate (unreleased status / undownloaded): items with
        # nothing in Plex to attach a poster to. Shared with Asset Renamerr's
        # apply gate via release_readiness so the two can't drift.
        if not is_release_ready(asset):
            return False
        if getattr(cfg, "ignore_unmonitored", False):
            monitored = asset.get("monitored")
            if monitored is not None and not monitored:
                return False
        if (
            getattr(cfg, "ignore_folders", [])
            and asset.get("folder") in cfg.ignore_folders
        ):
            return False
        profile = asset.get("profile") or asset.get("quality_profile")
        if getattr(cfg, "ignore_profiles", []) and profile in cfg.ignore_profiles:
            return False
        tags = asset.get("tags", [])
        if isinstance(tags, str):
            import json

            try:
                tags = json.loads(tags)
            except Exception:
                tags = [t.strip() for t in tags.split(",") if t.strip()]
        if getattr(cfg, "ignore_tags", []):
            if any(tag in cfg.ignore_tags for tag in tags):
                return False
        if (
            getattr(cfg, "ignore_titles", [])
            and asset.get("title") in cfg.ignore_titles
        ):
            return False
        return True

    def filter_by_config(self) -> None:
        self.unmatched_media = [
            a for a in self.unmatched_media if self.should_include(a)
        ]
        self.unmatched_collections = [
            a for a in self.unmatched_collections if self.should_include(a)
        ]
        self.all_media = [a for a in self.all_media if self.should_include(a)]
        self.all_collections = [
            a for a in self.all_collections if self.should_include(a)
        ]

    def group_assets(self) -> tuple:
        group_map = {"movie": "movies", "show": "series", "series": "series"}
        unmatched = {"movies": [], "series": [], "collections": []}
        all_media_grouped = {"movies": [], "series": []}
        all_collections_grouped = []

        for row in self.unmatched_media:
            key = group_map.get(row.get("asset_type"))
            if not key:
                continue
            entry = dict(row)
            if key == "series":
                if entry.get("season_number") is not None:
                    found = next(
                        (
                            s
                            for s in unmatched["series"]
                            if s["title"] == entry["title"]
                            and s.get("year") == entry.get("year")
                        ),
                        None,
                    )
                    if found:
                        found.setdefault("missing_seasons", []).append(
                            entry["season_number"]
                        )
                    else:
                        unmatched["series"].append(
                            {
                                "title": entry["title"],
                                "year": entry.get("year"),
                                "missing_seasons": [entry["season_number"]],
                                "missing_main_poster": False,
                                "tmdb_id": entry.get("tmdb_id"),
                                "tvdb_id": entry.get("tvdb_id"),
                                "imdb_id": entry.get("imdb_id"),
                                "instance_name": entry.get("instance_name"),
                            }
                        )
                else:
                    found = next(
                        (
                            s
                            for s in unmatched["series"]
                            if s["title"] == entry["title"]
                            and s.get("year") == entry.get("year")
                        ),
                        None,
                    )
                    if found:
                        found["missing_main_poster"] = True
                    else:
                        unmatched["series"].append(
                            {
                                "title": entry["title"],
                                "year": entry.get("year"),
                                "missing_seasons": [],
                                "missing_main_poster": True,
                                "tmdb_id": entry.get("tmdb_id"),
                                "tvdb_id": entry.get("tvdb_id"),
                                "imdb_id": entry.get("imdb_id"),
                                "instance_name": entry.get("instance_name"),
                            }
                        )
            else:
                unmatched[key].append(entry)

        for row in self.unmatched_collections:
            unmatched["collections"].append(dict(row))

        for row in self.all_media:
            key = group_map.get(row.get("asset_type"))
            if not key:
                continue
            entry = dict(row)
            if key == "series":
                found = next(
                    (
                        s
                        for s in all_media_grouped["series"]
                        if s["title"] == entry["title"]
                        and s.get("year") == entry.get("year")
                    ),
                    None,
                )
                if found:
                    if entry.get("season_number") is not None:
                        found.setdefault("seasons", []).append(entry["season_number"])
                else:
                    seasons = []
                    if entry.get("season_number") is not None:
                        seasons = [entry["season_number"]]
                    all_media_grouped["series"].append(
                        {
                            "title": entry["title"],
                            "year": entry.get("year"),
                            "seasons": seasons,
                        }
                    )
            else:
                all_media_grouped[key].append(entry)

        for row in self.all_collections:
            all_collections_grouped.append(dict(row))

        return unmatched, all_media_grouped, all_collections_grouped

    def calculate_stats(
        self,
        unmatched: Dict[str, List],
        all_media_grouped: Dict[str, List],
        all_collections_grouped: List[Dict],
    ) -> Dict[str, Any]:
        """Calculate completion statistics"""
        unmatched_movies_total = len(unmatched["movies"])
        total_movies = len(all_media_grouped["movies"])
        percent_movies_complete = (
            ((total_movies - unmatched_movies_total) / total_movies * 100)
            if total_movies
            else 0
        )

        unmatched_series_total = sum(
            1 for item in unmatched["series"] if item.get("missing_main_poster", False)
        )
        total_series = len(all_media_grouped["series"])
        percent_series_complete = (
            ((total_series - unmatched_series_total) / total_series * 100)
            if total_series
            else 0
        )

        unmatched_seasons_total = sum(
            len(item.get("missing_seasons", [])) for item in unmatched["series"]
        )
        total_seasons = sum(
            len(item.get("seasons", [])) for item in all_media_grouped["series"]
        )
        percent_seasons_complete = (
            ((total_seasons - unmatched_seasons_total) / total_seasons * 100)
            if total_seasons
            else 0
        )

        unmatched_collections_total = len(unmatched["collections"])
        total_collections = len(all_collections_grouped)
        percent_collections_complete = (
            (
                (total_collections - unmatched_collections_total)
                / total_collections
                * 100
            )
            if total_collections
            else 0
        )

        grand_total = total_movies + total_series + total_seasons + total_collections
        grand_unmatched = (
            unmatched_movies_total
            + unmatched_series_total
            + unmatched_seasons_total
            + unmatched_collections_total
        )
        percent_grand_complete = (
            ((grand_total - grand_unmatched) / grand_total * 100) if grand_total else 0
        )

        summary = {
            "movies": {
                "total": total_movies,
                "unmatched": unmatched_movies_total,
                "percent_complete": percent_movies_complete,
            },
            "series": {
                "total": total_series,
                "unmatched": unmatched_series_total,
                "percent_complete": percent_series_complete,
            },
            "seasons": {
                "total": total_seasons,
                "unmatched": unmatched_seasons_total,
                "percent_complete": percent_seasons_complete,
            },
            "collections": {
                "total": total_collections,
                "unmatched": unmatched_collections_total,
                "percent_complete": percent_collections_complete,
            },
            "grand_total": {
                "total": grand_total,
                "unmatched": grand_unmatched,
                "percent_complete": percent_grand_complete,
            },
        }
        return summary

    def get_stats_adhoc(self) -> Dict[str, Any]:
        try:
            with ChubDB(logger=self.logger) as db:
                return self.get_stats(db)
        except Exception as exc:
            self.logger.error(f"\n\nAn error occurred: {exc}\n", exc_info=True)
            return {}

    def get_stats(self, db: ChubDB) -> Dict[str, Any]:
        self.fetch_data(db)

        self.compute_instance_filters()
        if not self.allowed_instances:
            all_instance_names = {
                asset.get("instance_name")
                for asset in self.unmatched_collections
                + self.all_collections
                + self.unmatched_media
                + self.all_media
            }
            self.allowed_instances = all_instance_names
            self.logger.debug(
                f"Allowed_instances defaulted to: {self.allowed_instances}"
            )

        # Backfill any missing tmdb_id values before grouping so unmatched
        # entries surface a real TMDB link. Sync-time backfill (in
        # Connector.update_arr_database) covers most rows; this catches the
        # case where stats are viewed without a recent sync.
        try:
            from backend.util.tmdb import backfill_missing_tmdb_ids

            backfill_missing_tmdb_ids(
                db,
                self.full_config.tmdb,
                self.logger,
                instance_names=self.allowed_instances or None,
            )
            # Re-fetch so in-memory rows reflect newly resolved IDs.
            self.fetch_data(db)
        except Exception as exc:
            self.logger.warning(f"TMDB backfill skipped in stats: {exc}")

        self.filter_by_instance()
        self.filter_by_config()
        unmatched, all_media_grouped, all_collections_grouped = self.group_assets()
        summary = self.calculate_stats(
            unmatched, all_media_grouped, all_collections_grouped
        )
        needs_review, ignored, locked = self.get_review_and_ignored(db)
        summary["needs_review"] = len(needs_review)
        summary["ignored"] = len(ignored)
        summary["locked"] = len(locked)
        return {
            "unmatched": unmatched,
            "all_media": all_media_grouped,
            "all_collections": all_collections_grouped,
            "needs_review": needs_review,
            "ignored": ignored,
            "locked": locked,
            "summary": summary,
        }

    # Additional (non-poster) artwork types surfaced on the Unmatched →
    # "Additional artwork" view. Banner is intentionally absent (no Plex/Kometa
    # apply path — see asset_renamerr.ALL_ASSET_TYPES). squareart applies to
    # movies + shows only.
    ARTWORK_TYPES = ["logo", "background", "squareart"]

    def get_artwork_stats_adhoc(self) -> Dict[str, Any]:
        try:
            with ChubDB(logger=self.logger) as db:
                return self.get_artwork_stats(db)
        except Exception as exc:
            self.logger.error(f"\n\nAn error occurred: {exc}\n", exc_info=True)
            return {}

    def get_artwork_stats(self, db: ChubDB) -> Dict[str, Any]:
        """Per-image-type coverage for the additional artwork (logo / background
        / squareart), derived from media_asset_matches.

        Reuses the same instance + config filtering as the poster view to get
        the eligible media universe, then for each (media, image_type) classifies
        it from its media_asset_matches row:
          - applied      → match_status == "applied" and not ignored
          - needs_review → row exists, status != applied, not ignored
          - ignored      → ignored flag set (user dismissed)
          - missing      → no row (or status failed) and not ignored
        Returns per-type {total, applied, missing, needs_review, ignored,
        percent_complete} plus flat per-type lists for the table, mirroring the
        shape the poster view returns so the frontend can reuse its rendering.
        """
        self.fetch_data(db)
        self.compute_instance_filters()
        if not self.allowed_instances:
            self.allowed_instances = {
                a.get("instance_name") for a in self.all_media + self.all_collections
            }
        self.filter_by_instance()
        self.filter_by_config()

        # Eligible media universe: only released/has-content movies+shows that
        # pass the ignore gates (same predicate the poster unmatched list uses).
        # squareart is movie/show-capable too; banner is excluded entirely.
        eligible = [
            a
            for a in self.all_media
            if a.get("asset_type") in ("movie", "show") and self.should_include(a)
        ]

        # Presence index: (target_id, image_type) -> match row (media only).
        index: Dict[tuple, Dict[str, Any]] = {}
        for image_type in self.ARTWORK_TYPES:
            for row in db.media_asset_matches.get_by_type(image_type):
                if row.get("target_kind") == "media":
                    index[(row.get("target_id"), image_type)] = row

        per_type: Dict[str, Dict[str, Any]] = {}
        for image_type in self.ARTWORK_TYPES:
            applied = missing = needs_review = ignored = 0
            missing_items: List[Dict[str, Any]] = []
            review_items: List[Dict[str, Any]] = []
            ignored_items: List[Dict[str, Any]] = []
            for media in eligible:
                row = index.get((media.get("id"), image_type))
                item = self._serialize_artwork_item(media, image_type, row)
                if row and row.get("ignored"):
                    ignored += 1
                    ignored_items.append(item)
                elif row and row.get("match_status") == "applied":
                    applied += 1
                elif row and row.get("match_status"):
                    needs_review += 1
                    review_items.append(item)
                else:
                    missing += 1
                    missing_items.append(item)
            total = len(eligible)
            per_type[image_type] = {
                "total": total,
                "applied": applied,
                "missing": missing,
                "needs_review": needs_review,
                "ignored": ignored,
                "percent_complete": (applied / total * 100) if total else 0,
                "missing_items": missing_items,
                "needs_review_items": review_items,
                "ignored_items": ignored_items,
            }

        grand_missing = sum(t["missing"] for t in per_type.values())
        grand_review = sum(t["needs_review"] for t in per_type.values())
        grand_ignored = sum(t["ignored"] for t in per_type.values())

        # Per-MEDIA rows: one entry per item, with the artwork types it's missing
        # / failed / ignored as arrays. This is what the per-media table renders
        # (one line per movie/show, chips showing which artwork it lacks) —
        # aligned with the poster Unmatched list. An item appears in:
        #   unmatched      → missing[] non-empty
        #   needs_review   → failed[] non-empty
        #   ignored        → ignored_types[] non-empty
        media_rows: Dict[Any, Dict[str, Any]] = {}
        for media in eligible:
            mid = media.get("id")
            entry = {
                "id": mid,
                "title": media.get("title"),
                "year": media.get("year"),
                "type": media.get("asset_type"),
                "asset_type": media.get("asset_type"),
                "season_number": media.get("season_number"),
                "instance_name": media.get("instance_name"),
                "tmdb_id": media.get("tmdb_id"),
                "tvdb_id": media.get("tvdb_id"),
                "imdb_id": media.get("imdb_id"),
                "missing": [],
                "failed": [],
                "ignored_types": [],
                "reasons": {},
            }
            for image_type in self.ARTWORK_TYPES:
                row = index.get((mid, image_type))
                if row and row.get("ignored"):
                    entry["ignored_types"].append(image_type)
                elif row and row.get("match_status") == "applied":
                    pass  # covered — nothing to show
                elif row and row.get("match_status"):
                    entry["failed"].append(image_type)
                    if row.get("detail"):
                        entry["reasons"][image_type] = row.get("detail")
                else:
                    entry["missing"].append(image_type)
            media_rows[mid] = entry

        rows = list(media_rows.values())
        unmatched_media = [r for r in rows if r["missing"]]
        review_media = [r for r in rows if r["failed"]]
        ignored_media = [r for r in rows if r["ignored_types"]]

        return {
            "types": per_type,
            "media": {
                "unmatched": unmatched_media,
                "needs_review": review_media,
                "ignored": ignored_media,
            },
            "summary": {
                "missing": len(unmatched_media),
                "needs_review": len(review_media),
                "ignored": len(ignored_media),
                # keep the per-type grand totals too (cards still show them)
                "missing_types": grand_missing,
                "needs_review_types": grand_review,
                "ignored_types": grand_ignored,
            },
        }

    @staticmethod
    def _serialize_artwork_item(
        media: Dict[str, Any], image_type: str, row: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Flatten a (media, image_type) pair to the fields the artwork table
        renders. ``row`` is the media_asset_matches row if one exists."""
        return {
            "id": media.get("id"),
            "title": media.get("title"),
            "year": media.get("year"),
            "type": media.get("asset_type"),
            "asset_type": media.get("asset_type"),
            "season_number": media.get("season_number"),
            "instance_name": media.get("instance_name"),
            "tmdb_id": media.get("tmdb_id"),
            "tvdb_id": media.get("tvdb_id"),
            "imdb_id": media.get("imdb_id"),
            "image_type": image_type,
            "match_status": (row or {}).get("match_status"),
            "source": (row or {}).get("source"),
            "reason": (row or {}).get("detail"),
            "ignored": bool((row or {}).get("ignored")),
        }

    @staticmethod
    def _serialize_match_row(row: Dict[str, Any], is_collection: bool) -> Dict[str, Any]:
        """Flatten a media/collection row to the fields the Needs-Review /
        Ignored tabs render (status, confidence, reason, conflicts)."""
        import json as _json

        conflicts = []
        raw = row.get("conflict_ids")
        if raw:
            try:
                parsed = _json.loads(raw)
                if isinstance(parsed, list):
                    conflicts = parsed
            except (ValueError, TypeError):
                conflicts = []
        return {
            "id": row.get("id"),
            "title": row.get("title"),
            "year": row.get("year"),
            "type": "collection" if is_collection else row.get("asset_type"),
            "asset_type": "collection" if is_collection else row.get("asset_type"),
            "season_number": row.get("season_number"),
            "instance_name": row.get("instance_name"),
            "tmdb_id": row.get("tmdb_id"),
            "tvdb_id": row.get("tvdb_id"),
            "imdb_id": row.get("imdb_id"),
            "match_status": row.get("match_status"),
            "match_confidence": row.get("match_confidence"),
            "match_reason": row.get("match_reason"),
            "conflicts": conflicts,
        }

    def get_review_and_ignored(self, db: ChubDB) -> tuple:
        """Return (needs_review, ignored, locked) flat lists for the tabs.

        needs_review honors the same instance/config gates as unmatched (minus
        the ignored gate, which the query already applies). ignored is the
        user's explicit dismissal list; locked is the rows the user manually
        applied/approved (user_confirmed) — both instance-filtered only.
        """
        review_rows = [
            self._serialize_match_row(r, False)
            for r in db.media.get_needs_review()
            if self.allowed_media(r) and self.should_include(r)
        ] + [
            self._serialize_match_row(r, True)
            for r in db.collection.get_needs_review()
            if self.allowed_collection(r) and self.should_include(r)
        ]
        ignored_rows = [
            self._serialize_match_row(r, False)
            for r in db.media.get_ignored()
            if self.allowed_media(r)
        ] + [
            self._serialize_match_row(r, True)
            for r in db.collection.get_ignored()
            if self.allowed_collection(r)
        ]
        locked_rows = [
            self._serialize_match_row(r, False)
            for r in db.media.get_user_confirmed()
            if self.allowed_media(r)
        ] + [
            self._serialize_match_row(r, True)
            for r in db.collection.get_user_confirmed()
            if self.allowed_collection(r)
        ]
        return review_rows, ignored_rows, locked_rows

    def print_stats(self, db: ChubDB) -> None:
        try:
            from backend.util.helper import create_table

            stats = self.get_stats(db)
            unmatched = stats["unmatched"]
            summary = stats["summary"]
            asset_types = ["movies", "series", "collections"]

            for asset_type in asset_types:
                data_set = unmatched.get(asset_type, [])
                if not data_set:
                    continue
                self.logger.info(
                    create_table([[f"Unmatched {asset_type.capitalize()}"]])
                )
                for item in data_set:
                    if asset_type == "series":
                        title = item.get("title", "Unknown")
                        year = item.get("year", "")
                        missing_seasons = item.get("missing_seasons", [])
                        missing_main = item.get("missing_main_poster", False)
                        parts = []
                        if missing_main:
                            parts.append("main")
                        if missing_seasons:
                            seasons_str = ", ".join(
                                f"S{s}" for s in sorted(missing_seasons)
                            )
                            parts.append(seasons_str)
                        if parts:
                            self.logger.info(
                                f"{title} ({year}) — missing: {' + '.join(parts)}"
                            )
                    else:
                        year = f" ({item.get('year')})" if item.get("year") else ""
                        self.logger.info(f"{item.get('title')}{year}")

            self.logger.info(create_table([["Statistics"]]))
            table = [
                ["Type", "Total", "Unmatched", "Percent Complete"],
                [
                    "Movies",
                    summary["movies"]["total"],
                    summary["movies"]["unmatched"],
                    f"{summary['movies']['percent_complete']:.2f}%",
                ],
                [
                    "Series",
                    summary["series"]["total"],
                    summary["series"]["unmatched"],
                    f"{summary['series']['percent_complete']:.2f}%",
                ],
                [
                    "Seasons",
                    summary["seasons"]["total"],
                    summary["seasons"]["unmatched"],
                    f"{summary['seasons']['percent_complete']:.2f}%",
                ],
                [
                    "Collections",
                    summary["collections"]["total"],
                    summary["collections"]["unmatched"],
                    f"{summary['collections']['percent_complete']:.2f}%",
                ],
                [
                    "Grand Total",
                    summary["grand_total"]["total"],
                    summary["grand_total"]["unmatched"],
                    f"{summary['grand_total']['percent_complete']:.2f}%",
                ],
            ]
            self.logger.info(create_table(table))
        except Exception as exc:
            self.logger.error(f"\n\nAn error occurred: {exc}\n", exc_info=True)

    def build_output(self, db: ChubDB) -> Dict[str, Any]:
        stats = self.get_stats(db)
        unmatched_dict = stats["unmatched"]
        summary = stats["summary"]

        table = [
            ["Type", "Total", "Unmatched", "Percent Complete"],
            [
                "Movies",
                summary["movies"]["total"],
                summary["movies"]["unmatched"],
                f"{summary['movies']['percent_complete']:.2f}%",
            ],
            [
                "Series",
                summary["series"]["total"],
                summary["series"]["unmatched"],
                f"{summary['series']['percent_complete']:.2f}%",
            ],
            [
                "Seasons",
                summary["seasons"]["total"],
                summary["seasons"]["unmatched"],
                f"{summary['seasons']['percent_complete']:.2f}%",
            ],
            [
                "Collections",
                summary["collections"]["total"],
                summary["collections"]["unmatched"],
                f"{summary['collections']['percent_complete']:.2f}%",
            ],
            [
                "Grand Total",
                summary["grand_total"]["total"],
                summary["grand_total"]["unmatched"],
                f"{summary['grand_total']['percent_complete']:.2f}%",
            ],
        ]
        return {"unmatched_dict": unmatched_dict, "summary": table}

    def send_notification(self, db: ChubDB) -> None:
        manager = NotificationManager(
            self.full_config, self.logger, module_name="unmatched_assets"
        )
        output = self.build_output(db)
        manager.send_notification(output)

    def run(self) -> None:
        try:
            if self.is_cancelled():
                self.logger.info("Cancellation requested, stopping unmatched_assets.")
                return

            with ChubDB(logger=self.logger) as db:
                self.print_stats(db)
                if self.is_cancelled():
                    self.logger.info("Cancelled before notifications.")
                    return
                self.send_notification(db)

        except KeyboardInterrupt:
            print("Keyboard Interrupt detected. Exiting...")
            return
        except Exception:
            self.logger.error("\n\nAn error occurred:\n", exc_info=True)
        finally:
            self.logger.log_outro()
