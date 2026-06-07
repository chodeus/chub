# modules/border_replacerr.py

import filecmp
import hashlib
import logging
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image

from backend.util.base_module import ChubModule
from backend.util.database import ChubDB
from backend.util.helper import create_table, get_config_dir, print_settings, progress
from backend.util.logger import Logger
from backend.util.notification import NotificationManager

# Path to bundled borders: backend/assets/borders/<holiday>/<name>.png
_BUNDLED_BORDERS_DIR = Path(__file__).resolve().parents[1] / "assets" / "borders"

# Map holiday display names ("🧧 Lunar New Year", "🎄 Christmas") to the
# folder names under assets/borders/ (alphanumeric, lowercase, no spaces).
# The mapping is generated from the display name by stripping non-ASCII,
# lowercasing, removing apostrophes/spaces. If a holiday's preset folder
# isn't in assets/borders/, image mode silently degrades to color mode.
_HOLIDAY_FOLDER_OVERRIDES = {
    "new year's day": "newyear",
    "lunar new year": "lunarnewyear",
    "valentine's day": "valentines",
    "st. patrick's day": "stpatricks",
    "easter": "easter",
    "mother's day": "mothersday",
    "father's day": "fathersday",
    "pride": "pride",
    "independence day": "independence",
    "labor day": "labor",
    "halloween": "halloween",
    "thanksgiving": "thanksgiving",
    "christmas": "christmas",
}

logging.getLogger("PIL").setLevel(logging.WARNING)


class BorderReplacerr(ChubModule):
    def __init__(self, logger: Optional[Logger] = None) -> None:
        super().__init__(logger=logger)

    @staticmethod
    def _safe_holiday_date(year: int, month: int, day: int) -> datetime:
        """Build a date for a holiday range boundary, clamping Feb 29 to Feb 28
        on non-leap years so a leap-day range doesn't raise every other year."""
        try:
            return datetime(year, month, day)
        except ValueError:
            if month == 2 and day == 29:
                return datetime(year, 2, 28)
            raise

    def get_holiday_status(self, db: ChubDB):
        now = datetime.now()
        holidays = self.config.holidays
        default_colors = self.config.border_colors
        skip_enabled = self.config.skip

        last_status = db.holiday.get_status()
        last_active_holiday = last_status["last_active_holiday"]

        current_holiday = None
        border_colors = None
        border_paths: List[str] = []
        for holiday_item in holidays:
            holiday = holiday_item.name
            schedule = holiday_item.schedule
            color_list = getattr(holiday_item, "colors", default_colors)
            border_names = getattr(holiday_item, "borders", []) or []
            if not schedule or not schedule.startswith("range("):
                continue
            # A single malformed holiday entry must not abort the whole run /
            # crash the preview API — skip it with a warning instead.
            try:
                inside = schedule[len("range(") : -1]
                start_str, end_str = inside.split("-", 1)
                sm, sd = map(int, start_str.split("/"))
                em, ed = map(int, end_str.split("/"))
                year = now.year
                start_date = self._safe_holiday_date(year, sm, sd)
                end_date = self._safe_holiday_date(year, em, ed)
            except (ValueError, AttributeError) as e:
                self.logger.warning(
                    f"Skipping holiday '{holiday}': invalid schedule "
                    f"{schedule!r} ({e})"
                )
                continue
            if end_date < start_date:  # handle year crossover
                if now.month < sm:
                    start_date = start_date.replace(year=year - 1)
                else:
                    end_date = end_date.replace(year=year + 1)
            if start_date <= now <= end_date:
                if isinstance(color_list, str):
                    color_list = [color_list]
                border_colors = [self.convert_to_rgb(c) for c in color_list]
                border_paths = self._resolve_border_paths(holiday, border_names)
                current_holiday = holiday
                break

        if not border_colors and default_colors:
            border_colors = [self.convert_to_rgb(c) for c in default_colors]

        reset_all = current_holiday != last_active_holiday
        result = {
            "active_holiday": current_holiday,
            "last_active_holiday": last_active_holiday,
            "border_colors": border_colors,
            "border_paths": border_paths,
            "skip_enabled": skip_enabled,
            "reset_all": reset_all,
        }
        return result

    def _holiday_folder(self, holiday_name: str) -> Optional[str]:
        """Map a preset display name to its assets/borders/ subfolder."""
        if not holiday_name:
            return None
        # Strip emojis and whitespace, lowercase
        cleaned = re.sub(r"[^\x00-\x7f]", "", holiday_name).strip().lower()
        if cleaned in _HOLIDAY_FOLDER_OVERRIDES:
            return _HOLIDAY_FOLDER_OVERRIDES[cleaned]
        # Best-effort fallback: alphanumeric only, no spaces
        return re.sub(r"[^a-z0-9]", "", cleaned) or None

    def _resolve_border_paths(self, holiday_name: str, names: List[str]) -> List[str]:
        """Resolve user-supplied border names to absolute file paths.

        For each name, check /config/borders/<holiday>/<name>.png first
        (user customs), then assets/borders/<holiday>/<name>.png
        (bundled). Drop unresolvable entries with a warning so the rest
        of the rotation still works.
        """
        folder = self._holiday_folder(holiday_name)
        if not folder or not names:
            return []
        user_dir = Path(get_config_dir()) / "borders" / folder
        bundled_dir = _BUNDLED_BORDERS_DIR / folder
        resolved: List[str] = []
        for raw in names:
            # Allow with-or-without ".png" in config
            stem = Path(raw).stem
            user_path = user_dir / f"{stem}.png"
            bundled_path = bundled_dir / f"{stem}.png"
            if user_path.is_file():
                resolved.append(str(user_path))
            elif bundled_path.is_file():
                resolved.append(str(bundled_path))
            elif self.logger:
                self.logger.warning(
                    f"Border '{raw}' not found for holiday '{holiday_name}' — "
                    f"checked {user_path} and {bundled_path}"
                )
        return resolved

    def convert_to_rgb(self, hex_color: str) -> Tuple[int, int, int]:
        hex_color = hex_color.strip("#")
        if len(hex_color) == 3:
            hex_color = "".join(c * 2 for c in hex_color)
        try:
            color_code = tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            self.logger.error(
                f"Error: {hex_color} is not a valid hexadecimal color code.\nDefaulting to white."
            )
            return (255, 255, 255)
        return color_code

    @staticmethod
    def _safe_stat(path: str):
        """os.stat(path) or None if it can't be stat'd."""
        try:
            return os.stat(path)
        except OSError:
            return None

    @staticmethod
    def _file_digest(path: str) -> str:
        """MD5 of a file's bytes (used to fingerprint border PNGs)."""
        h = hashlib.md5()
        try:
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
        except OSError:
            return ""
        return h.hexdigest()

    def _save_if_changed(self, out_img: "Image.Image", renamed_file: str) -> bool:
        """Write ``out_img`` next to ``renamed_file`` via a temp file, then
        atomically move it into place only if the bytes differ from the
        current file. Returns True if written, False if unchanged.

        Two fixes over the old `/tmp/{basename}` approach:
          - The temp lives in the destination directory, so the move is an
            atomic same-filesystem ``os.replace`` rather than a cross-device
            copy (the dest is typically a FUSE/array mount, /tmp is not), and
            concurrent workers compositing the same basename can't collide
            (mkstemp gives each a unique name) — the prerequisite for #11.
          - filecmp uses shallow=False (content compare). The old default
            shallow=True compared stat signatures; a freshly written temp
            always has a new mtime, so "unchanged" never fired and every
            poster was rewritten each run. Content compare makes the skip real.
        """
        dest_dir = os.path.dirname(renamed_file)
        os.makedirs(dest_dir, exist_ok=True)
        suffix = os.path.splitext(renamed_file)[1] or ".jpg"
        fd, tmp_path = tempfile.mkstemp(prefix=".border-", suffix=suffix, dir=dest_dir)
        os.close(fd)
        try:
            out_img.save(tmp_path)
            if not os.path.exists(renamed_file) or not filecmp.cmp(
                renamed_file, tmp_path, shallow=False
            ):
                os.replace(tmp_path, renamed_file)
                return True
            os.remove(tmp_path)
            return False
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    # Best-effort cleanup of our own temp file; failing to
                    # remove it must not mask the original error re-raised below.
                    pass
            raise

    def replace_borders_with_image(
        self, original_file: str, renamed_file: str, border_image_path: str
    ) -> bool:
        """Composite a 1000×1500 PNG border over a poster.

        The border PNG must have an opaque decorated outer ring and a
        transparent rectangular center where the poster shows through.
        Final output is 1000×1500 RGB.
        """
        try:
            with Image.open(original_file) as image:
                # Skip the resample when the source is already target size
                # (often, since our own output is 1000x1500).
                if image.size != (1000, 1500):
                    image = image.resize((1000, 1500))
                poster = image.convert("RGBA")
            with Image.open(border_image_path) as border:
                overlay = border.convert("RGBA")
                if overlay.size != (1000, 1500):
                    overlay = overlay.resize((1000, 1500))
            out_img = Image.alpha_composite(poster, overlay).convert("RGB")
            if self._save_if_changed(out_img, renamed_file):
                self.logger.debug(
                    f"Composited border: {os.path.basename(original_file)} "
                    f"+ {os.path.basename(border_image_path)} → "
                    f"{os.path.basename(renamed_file)}"
                )
                self.logger.debug(f"[BORDER_COMPOSITED] {renamed_file}")
                return True
            self.logger.debug(
                f"No border update needed for {os.path.basename(renamed_file)}"
            )
            return False
        except Exception as e:
            self.logger.error(
                f"Error compositing image border on "
                f"{os.path.basename(original_file)}: {e}"
            )
            # None = failure (distinct from False = no change needed) so run()
            # can tally it instead of silently counting it as processed.
            return None

    def replace_borders(self, original_file, renamed_file, border_color, border_width):
        try:
            with Image.open(original_file) as image:
                width, height = image.size
                cropped = image.crop(
                    (
                        border_width,
                        border_width,
                        width - border_width,
                        height - border_width,
                    )
                )
                new_width = cropped.width + 2 * border_width
                new_height = cropped.height + 2 * border_width
                out_img = Image.new("RGB", (new_width, new_height), border_color)
                out_img.paste(cropped, (border_width, border_width))
                if out_img.size != (1000, 1500):
                    out_img = out_img.resize((1000, 1500))
                out_img = out_img.convert("RGB")

                if self._save_if_changed(out_img, renamed_file):
                    self.logger.debug(
                        f"Replaced border: {os.path.basename(original_file)} → {os.path.basename(renamed_file)}"
                    )
                    self.logger.debug(f"[BORDER_REPLACED] {renamed_file}")
                    return True
                else:
                    self.logger.debug(
                        f"No border update needed for {os.path.basename(renamed_file)}"
                    )
                    return False
        except Exception as e:
            self.logger.error(
                f"Error replacing border on {os.path.basename(original_file)}: {e}"
            )
            return None  # None = failure (vs False = no change needed)

    def remove_borders(self, original_file, renamed_file, border_width):
        try:
            with Image.open(original_file) as image:
                width, height = image.size
                cropped = image.crop(
                    (
                        border_width,
                        border_width,
                        width - border_width,
                        height - border_width,
                    )
                )
                if cropped.size != (1000, 1500):
                    cropped = cropped.resize((1000, 1500))
                cropped = cropped.convert("RGB")

                if self._save_if_changed(cropped, renamed_file):
                    self.logger.debug(
                        f"Removed border: {os.path.basename(original_file)} → {os.path.basename(renamed_file)}"
                    )
                    self.logger.debug(f"[BORDER_REMOVED] {renamed_file}")
                    return True
                else:
                    self.logger.debug(
                        f"No border update needed for {os.path.basename(renamed_file)}"
                    )
                    return False
        except Exception as e:
            self.logger.error(
                f"Error removing border on {os.path.basename(original_file)}: {e}"
            )
            return None  # None = failure (vs False = no change needed)

    def _asset_excluded(self, asset: dict) -> bool:
        """True if this asset should be skipped per exclusion_list /
        ignore_folders. Logs a debug line so the user can see why."""
        title = asset.get("title")
        if self.config.exclusion_list and title in self.config.exclusion_list:
            self.logger.debug(f"Skipping '{title}' (in exclusion_list).")
            return True
        if (
            self.config.ignore_folders
            and asset.get("folder") in self.config.ignore_folders
        ):
            self.logger.debug(f"Skipping '{title}' (folder in ignore_folders).")
            return True
        return False

    def _collect_matched_assets(self, db) -> list:
        """Return every matched media row + matched collection row, with
        exclusion_list / ignore_folders applied.

        Unlike poster_renamerr.get_matched_assets(), this does NOT drop
        already-moved posters (those whose renamed_file exists on disk), so
        the full-library border pass re-borders the whole library, not just
        the not-yet-moved subset carried in a manifest. Collections are
        included here (the old reset_all branch processed media only)."""
        assets: list = []
        # Use .get() defensively: db rows are trusted but may be partial in
        # edge cases (e.g. a row mid-write); a missing key skips the row rather
        # than crashing the whole library pass.
        for row in db.media.get_all():
            if row.get("matched") != 1:
                continue
            if self._asset_excluded(row):
                continue
            assets.append(row)
        for row in db.collection.get_all():
            if row.get("matched") != 1:
                continue
            if self._asset_excluded(row):
                continue
            assets.append(row)
        return assets

    @staticmethod
    def _should_process_all(manifest, process_all: bool, reset_all: bool) -> bool:
        """Decide whether to border the full matched library vs only the
        manifest subset.

        Full library when: the caller asked (process_all, e.g. a renamerr
        full run), or the holiday state just changed (reset_all), or no
        manifest was supplied (standalone module run). Otherwise the
        manifest subset (webhook/adhoc imports)."""
        return bool(process_all or reset_all or manifest is None)

    def run(self, manifest: Optional[dict] = None, process_all: bool = False):
        with ChubDB(logger=self.logger) as db:
            if self.config.log_level.lower() == "debug":
                print_settings(self.logger, self.config)

            results = self.get_holiday_status(db=db)
            skip_enabled = results["skip_enabled"]
            reset_all = results["reset_all"]
            active_holiday = results["active_holiday"]

            if skip_enabled and not active_holiday:
                self.logger.info(
                    "Border replacerr is in skip mode and today is not a holiday. Skipping all processing."
                )
                db.holiday.set_status(active_holiday)
                return
            if skip_enabled and active_holiday:
                self.logger.info(
                    "Border replacerr skip mode: Overriding skip due to active holiday."
                )

            assets = []
            processed = 0
            replaced = 0
            removed = 0
            skipped = 0
            failed = 0
            gate_skipped = 0
            if self._should_process_all(manifest, process_all, reset_all):
                self.logger.debug(
                    "Full-library border pass: reprocessing all matched media "
                    "and collections (includes already-moved posters)."
                )
                assets = self._collect_matched_assets(db)
            else:
                all_ids = [("media_cache", i) for i in manifest["media_cache"]] + [
                    ("collections_cache", i) for i in manifest["collections_cache"]
                ]
                for source, asset_id in all_ids:
                    if source == "media_cache":
                        asset = db.media.get_by_id(asset_id)
                    else:
                        asset = db.collection.get_by_id(asset_id)
                    if not asset:
                        self.logger.warning(
                            f"Asset ID {asset_id} not found in {source}. Skipping."
                        )
                        continue
                    if (
                        self.config.exclusion_list
                        and asset["title"] in self.config.exclusion_list
                    ):
                        self.logger.debug(
                            f"Skipping '{asset['title']}' (in exclusion_list)."
                        )
                        continue
                    if (
                        self.config.ignore_folders
                        and asset.get("folder") in self.config.ignore_folders
                    ):
                        self.logger.debug(
                            f"Skipping '{asset['title']}' (folder in ignore_folders)."
                        )
                        continue
                    assets.append(asset)

            if not assets:
                self.logger.info("No assets to process for border replacerr.")
                db.holiday.set_status(active_holiday)
                return

            border_colors = results["border_colors"]
            border_paths = results.get("border_paths") or []
            dry_run = self.config.dry_run

            self.logger.debug(f"Total assets to process: {len(assets)}")
            if border_paths:
                self.logger.debug(
                    f"Border mode: image ({len(border_paths)} variants) — "
                    f"{', '.join(os.path.basename(p) for p in border_paths)}"
                )
            elif border_colors:
                self.logger.debug(
                    f"Border mode: color — "
                    f"{', '.join(f'#{r:02x}{g:02x}{b:02x}' for (r, g, b) in border_colors)}"
                )
            else:
                self.logger.debug("Border mode: removing borders")

            self.logger.info(f"Processing {len(assets)} posters, please wait...")
            # Collect each poster whose border actually changed so the user
            # can see exactly which titles were touched without flipping to
            # DEBUG. Skips dry-run because `result=True` there is unconditional
            # and the list would just be every input.
            changes: List[Dict[str, str]] = []

            # Skip-gate state: the (mtime, size, settings-signature) of each
            # output we last wrote. A poster whose output file is unchanged and
            # whose signature still matches would re-encode to byte-identical
            # bytes, so it's skipped entirely (no decode/resize/encode).
            # Disabled on dry-run (we want to report what WOULD happen). Empty
            # on first run, so the first pass processes everything as before.
            gate_enabled = not dry_run
            state_map = db.border.get_all_map() if gate_enabled else {}

            # Hash each border PNG's bytes once so swapping a PNG's contents
            # (same filename) invalidates the gate.
            png_hash = (
                {p: self._file_digest(p) for p in border_paths} if border_paths else {}
            )

            def _variant_sig(variant) -> str:
                if border_paths:
                    return f"image:{png_hash.get(variant, '')}"
                if border_colors:
                    return f"color:{self.config.border_width}:{variant}"
                return f"remove:{self.config.border_width}"

            # Pre-filter: drop assets missing file info (tally skipped), assign
            # each survivor its round-robin variant (positional over ALL valid
            # assets, so the assignment is stable regardless of which get
            # gate-skipped), then apply the skip-gate. Pre-assigning the variant
            # means the worker holds no shared mutable index — the prerequisite
            # for concurrency.
            work: List[Tuple[dict, object, str]] = []
            variant_index = 0
            for asset in assets:
                if not asset.get("original_file") or not asset.get("renamed_file"):
                    self.logger.warning(
                        f"Asset '{asset.get('title')}' missing file info. Skipping."
                    )
                    skipped += 1
                    continue
                if not os.path.exists(asset["original_file"]):
                    # Full-library sweeps re-encounter posters whose source was
                    # since removed (gdrive cleanup, one-time drops). Skip them
                    # quietly instead of letting the encoder fail and tallying a
                    # scary 'failed' every run.
                    self.logger.debug(
                        f"Skipping '{asset.get('title')}' — source poster missing "
                        f"on disk ({asset['original_file']})."
                    )
                    skipped += 1
                    continue
                if border_paths:
                    variant = border_paths[variant_index % len(border_paths)]
                elif border_colors:
                    variant = border_colors[variant_index % len(border_colors)]
                else:
                    variant = None
                variant_index += 1
                sig = _variant_sig(variant)
                original_file = asset["original_file"]
                renamed_file = asset["renamed_file"]
                # Gate on the SOURCE file (the border op's actual input): if the
                # input poster is unchanged and the settings signature matches,
                # the output we'd produce is byte-identical, so the decode/encode
                # is skippable. Output existence is required so a deleted output
                # is regenerated. Keying on source (not output) is correct
                # whether the border is applied in place (source == output) or to
                # a separate path: a re-downloaded source bumps its mtime/size
                # and forces a reprocess even if the stale output was untouched.
                if gate_enabled and os.path.exists(renamed_file):
                    prev = state_map.get(renamed_file)
                    if prev and prev["variant_sig"] == sig:
                        st = self._safe_stat(original_file)
                        if (
                            st is not None
                            and prev["source_mtime"] == st.st_mtime
                            and prev["source_size"] == st.st_size
                        ):
                            gate_skipped += 1
                            processed += 1
                            continue
                work.append((asset, variant, sig))

            def _process(item: Tuple[dict, object, str]):
                """Apply the active border op to one poster. Returns
                (result, title, action, detail, original_file, renamed_file, sig);
                result is True (written), False (unchanged) or None (failed)."""
                asset, variant, sig = item
                original_file = asset["original_file"]
                renamed_file = asset["renamed_file"]
                title = asset["title"]
                if border_paths:
                    action, detail = "composited", os.path.basename(variant)
                    if dry_run:
                        self.logger.debug(
                            f"[DRY RUN] Would composite {detail} onto: {renamed_file}"
                        )
                        return True, title, action, detail, original_file, renamed_file, sig
                    result = self.replace_borders_with_image(
                        original_file, renamed_file, variant
                    )
                elif border_colors:
                    action, detail = "replaced", variant
                    if dry_run:
                        self.logger.debug(
                            f"[DRY RUN] Would replace border for: {renamed_file}"
                        )
                        return True, title, action, detail, original_file, renamed_file, sig
                    result = self.replace_borders(
                        original_file, renamed_file, variant, self.config.border_width
                    )
                else:
                    action, detail = "removed", ""
                    if dry_run:
                        self.logger.debug(
                            f"[DRY RUN] Would remove border for: {renamed_file}"
                        )
                        return True, title, action, detail, original_file, renamed_file, sig
                    result = self.remove_borders(
                        original_file, renamed_file, self.config.border_width
                    )
                return result, title, action, detail, original_file, renamed_file, sig

            # PIL releases the GIL during decode/resize/composite/encode, so a
            # thread pool gives real parallelism on the CPU-bound encode without
            # the pickling cost of processes (and self.logger keeps working).
            # dry-run forces 1 worker: no I/O, and it keeps the "Would ..." debug
            # lines in asset order. map() preserves submission order so the
            # changes table and counters stay deterministic regardless of workers.
            if dry_run:
                workers = 1
            else:
                configured = getattr(self.config, "border_workers", None)
                workers = (
                    int(configured) if configured else min(8, os.cpu_count() or 4)
                )
                workers = max(1, min(workers, len(work) or 1))

            # Refresh each processed asset's gate state (mtime/size of the SOURCE
            # file + the signature it was made with) so the next run can skip it.
            # Keyed by the output path (stable per-asset identity). Recorded for
            # written (True) and unchanged (False) results, not failures (None) —
            # failures should retry next run. Timestamp computed once.
            from datetime import timezone

            now_iso = datetime.now(timezone.utc).isoformat()
            new_states: List[dict] = []
            total_work = len(work)

            with progress(
                work,
                desc="Processing Posters",
                total=total_work,
                unit="posters",
                logger=self.logger,
            ) as bar:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    for (
                        result,
                        title,
                        action,
                        detail,
                        original_file,
                        renamed_file,
                        sig,
                    ) in pool.map(_process, work):
                        bar.update(1)
                        if result:
                            if action == "removed":
                                removed += 1
                            else:
                                replaced += 1
                            if not dry_run:
                                changes.append(
                                    {
                                        "title": title,
                                        "action": action,
                                        "detail": detail,
                                    }
                                )
                        elif result is None:
                            failed += 1
                        if gate_enabled and result is not None:
                            st = self._safe_stat(original_file)
                            if st is not None:
                                new_states.append(
                                    {
                                        "renamed_file": renamed_file,
                                        "source_mtime": st.st_mtime,
                                        "source_size": st.st_size,
                                        "variant_sig": sig,
                                        "updated_at": now_iso,
                                    }
                                )
                        processed += 1
                        # Drive the Jobs-page bar (no-op without job context; maps
                        # into the parent's reserved slice when chained from
                        # poster_renamerr). Report periodically + at the end.
                        if total_work and (processed % 25 == 0 or processed == total_work):
                            self._report_progress(int(processed / total_work * 100))

            if new_states:
                db.border.bulk_record(new_states)

            if changes:
                self.logger.info("")  # Spacing
                self.logger.info(create_table([["Posters Updated"]]))
                for change in changes:
                    if change["action"] == "composited":
                        self.logger.info(
                            f"  {change['title']} — composited {change['detail']}"
                        )
                    elif change["action"] == "replaced":
                        self.logger.info(
                            f"  {change['title']} — border replaced ({change['detail']})"
                        )
                    elif change["action"] == "removed":
                        self.logger.info(f"  {change['title']} — border removed")

            self.logger.info("")  # Spacing
            self.logger.info(create_table([["Border Replacerr Summary"]]))
            summary_table = [
                ["Processed", processed],
                ["Skipped", skipped],
            ]
            if gate_skipped:
                summary_table.append(["Unchanged (gate)", gate_skipped])
            if failed:
                summary_table.append(["Failed", failed])
            if replaced:
                summary_table.append(["Borders replaced", replaced])
            elif removed:
                summary_table.append(["Borders removed", removed])
            else:
                summary_table.append(["Borders changed", 0])
            for row in summary_table:
                self.logger.info(f"{row[0]:<20}: {row[1]}")

            if replaced or removed:
                action = []
                if replaced:
                    action.append(f"{replaced} replaced")
                if removed:
                    action.append(f"{removed} removed")
                self.logger.info(
                    f"Border replacerr completed: {processed} processed, {', '.join(action)}, {skipped} skipped."
                )
            else:
                self.logger.info(
                    f"Border replacerr completed: {processed} processed, {skipped} skipped. No borders changed."
                )
            self.logger.info(
                f"   → {processed} processed, {replaced} replaced, {removed} removed, "
                f"{skipped} skipped, {failed} failed"
            )
            if failed:
                self.logger.warning(
                    f"{failed} poster(s) failed to composite/replace/remove — "
                    "see the ERROR lines above for details."
                )
            self.logger.info("")

            db.holiday.set_status(active_holiday)

            # Notify — skipped on dry-run or if nothing changed (no-op runs
            # don't need to spam every cron).
            if not getattr(self.config, "dry_run", False) and (replaced or removed):
                try:
                    manager = NotificationManager(
                        self.full_config, self.logger, module_name="border_replacerr"
                    )
                    manager.send_notification(
                        {
                            "processed": processed,
                            "skipped": skipped,
                            "replaced": replaced,
                            "removed": removed,
                            "failed": failed,
                            "active_holiday": active_holiday,
                        }
                    )
                except Exception as e:
                    self.logger.debug(f"border_replacerr notification failed: {e}")
