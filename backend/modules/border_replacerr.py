# modules/border_replacerr.py

import filecmp
import logging
import os
import re
import shutil
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
                poster = image.resize((1000, 1500)).convert("RGBA")
            with Image.open(border_image_path) as border:
                overlay = border.convert("RGBA")
                if overlay.size != (1000, 1500):
                    overlay = overlay.resize((1000, 1500))
            out_img = Image.alpha_composite(poster, overlay).convert("RGB")
            tmp_path = f"/tmp/{os.path.basename(renamed_file)}"
            out_img.save(tmp_path)
            if not os.path.exists(renamed_file) or not filecmp.cmp(
                renamed_file, tmp_path
            ):
                os.makedirs(os.path.dirname(renamed_file), exist_ok=True)
                shutil.move(tmp_path, renamed_file)
                self.logger.debug(
                    f"Composited border: {os.path.basename(original_file)} "
                    f"+ {os.path.basename(border_image_path)} → "
                    f"{os.path.basename(renamed_file)}"
                )
                self.logger.debug(f"[BORDER_COMPOSITED] {renamed_file}")
                return True
            os.remove(tmp_path)
            self.logger.debug(
                f"No border update needed for {os.path.basename(renamed_file)}"
            )
            return False
        except Exception as e:
            self.logger.error(
                f"Error compositing image border on "
                f"{os.path.basename(original_file)}: {e}"
            )
            return False

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
                out_img = out_img.resize((1000, 1500)).convert("RGB")

                tmp_path = f"/tmp/{os.path.basename(renamed_file)}"
                out_img.save(tmp_path)
                if not os.path.exists(renamed_file) or not filecmp.cmp(
                    renamed_file, tmp_path
                ):
                    os.makedirs(os.path.dirname(renamed_file), exist_ok=True)
                    shutil.move(tmp_path, renamed_file)
                    self.logger.debug(
                        f"Replaced border: {os.path.basename(original_file)} → {os.path.basename(renamed_file)}"
                    )
                    self.logger.debug(f"[BORDER_REPLACED] {renamed_file}")
                    return True
                else:
                    os.remove(tmp_path)
                    self.logger.debug(
                        f"No border update needed for {os.path.basename(renamed_file)}"
                    )
                    return False
        except Exception as e:
            self.logger.error(
                f"Error replacing border on {os.path.basename(original_file)}: {e}"
            )
            return False

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
                cropped = cropped.resize((1000, 1500)).convert("RGB")

                tmp_path = f"/tmp/{os.path.basename(renamed_file)}"
                cropped.save(tmp_path)
                if not os.path.exists(renamed_file) or not filecmp.cmp(
                    renamed_file, tmp_path
                ):
                    os.makedirs(os.path.dirname(renamed_file), exist_ok=True)
                    shutil.move(tmp_path, renamed_file)
                    self.logger.debug(
                        f"Removed border: {os.path.basename(original_file)} → {os.path.basename(renamed_file)}"
                    )
                    self.logger.debug(f"[BORDER_REMOVED] {renamed_file}")
                    return True
                else:
                    os.remove(tmp_path)
                    self.logger.debug(
                        f"No border update needed for {os.path.basename(renamed_file)}"
                    )
                    return False
        except Exception as e:
            self.logger.error(
                f"Error removing border on {os.path.basename(original_file)}: {e}"
            )
            return False

    def run(self, manifest: dict):
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
            color_index = 0
            border_index = 0
            processed = 0
            replaced = 0
            removed = 0
            skipped = 0
            if reset_all:
                self.logger.debug(
                    "Holiday state changed (or startup). Doing full reprocessing of all matched assets."
                )
                for row in db.media.get_all():
                    if row["matched"] == 1:
                        if (
                            self.config.exclusion_list
                            and row["title"] in self.config.exclusion_list
                        ):
                            self.logger.debug(
                                f"Skipping '{row['title']}' (in exclusion_list)."
                            )
                            skipped += 1
                            continue
                        if (
                            self.config.ignore_folders
                            and row.get("folder") in self.config.ignore_folders
                        ):
                            self.logger.debug(
                                f"Skipping '{row['title']}' (folder in ignore_folders)."
                            )
                            skipped += 1
                            continue
                        assets.append(row)
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
            with progress(
                assets,
                desc="Processing Posters",
                total=len(assets),
                unit="posters",
                logger=self.logger,
            ) as bar:
                for asset in bar:
                    original_file = asset["original_file"]
                    renamed_file = asset["renamed_file"]
                    title = asset["title"]
                    if not original_file or not renamed_file:
                        self.logger.warning(
                            f"Asset '{title}' missing file info. Skipping."
                        )
                        skipped += 1
                        continue

                    if border_paths:
                        border_path = border_paths[border_index]
                        if not dry_run:
                            result = self.replace_borders_with_image(
                                original_file, renamed_file, border_path
                            )
                        else:
                            self.logger.debug(
                                f"[DRY RUN] Would composite "
                                f"{os.path.basename(border_path)} onto: "
                                f"{renamed_file}"
                            )
                            result = True
                        border_index = (border_index + 1) % len(border_paths)
                        if result:
                            replaced += 1
                            if not dry_run:
                                changes.append(
                                    {
                                        "title": title,
                                        "action": "composited",
                                        "detail": os.path.basename(border_path),
                                    }
                                )
                        processed += 1
                    elif border_colors:
                        color = border_colors[color_index]
                        if not dry_run:
                            result = self.replace_borders(
                                original_file,
                                renamed_file,
                                color,
                                self.config.border_width,
                            )
                        else:
                            self.logger.debug(
                                f"[DRY RUN] Would replace border for: {renamed_file}"
                            )
                            result = True
                        color_index = (color_index + 1) % len(border_colors)
                        if result:
                            replaced += 1
                            if not dry_run:
                                changes.append(
                                    {
                                        "title": title,
                                        "action": "replaced",
                                        "detail": color,
                                    }
                                )
                        processed += 1
                    else:
                        if not dry_run:
                            result = self.remove_borders(
                                original_file,
                                renamed_file,
                                self.config.border_width,
                            )
                        else:
                            self.logger.debug(
                                f"[DRY RUN] Would remove border for: {renamed_file}"
                            )
                            result = True
                        if result:
                            removed += 1
                            if not dry_run:
                                changes.append(
                                    {
                                        "title": title,
                                        "action": "removed",
                                        "detail": "",
                                    }
                                )
                        processed += 1

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
                f"   → {processed} processed, {replaced} replaced, {removed} removed, {skipped} skipped"
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
                            "active_holiday": active_holiday,
                        }
                    )
                except Exception as e:
                    self.logger.debug(f"border_replacerr notification failed: {e}")
