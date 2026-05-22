# modules/jduparr.py

import os
import re
import subprocess
from typing import Any, Dict, List, Optional

from backend.util.base_module import ChubModule
from backend.util.helper import create_table, print_settings
from backend.util.logger import Logger
from backend.util.notification import NotificationManager


VIDEO_EXT_FILTER = "onlyext:mp4,mkv,avi"


class Jduparr(ChubModule):
    def __init__(self, logger: Optional[Logger] = None) -> None:
        super().__init__(logger=logger)

    @staticmethod
    def _is_unsafe_path_value(value: Any) -> bool:
        return (
            not isinstance(value, str)
            or not value
            or "\x00" in value
            or value.startswith("-")
        )

    @staticmethod
    def _is_summary_line(line: str) -> bool:
        return bool(
            re.search(r"\bduplicate files?\b", line, re.IGNORECASE)
            or re.search(r"\bNo duplicates found\.?\b", line, re.IGNORECASE)
            or re.match(r"^\d+\s+(?:files?|sets?)\b", line, re.IGNORECASE)
        )

    @classmethod
    def parse_duplicate_groups(cls, stdout: str) -> List[List[str]]:
        groups: List[List[str]] = []
        current_group: List[str] = []

        def flush_group() -> None:
            nonlocal current_group
            if len(current_group) > 1:
                groups.append(current_group)
            current_group = []

        for raw_line in stdout.splitlines():
            line = raw_line.strip()
            if not line:
                flush_group()
                continue
            if cls._is_summary_line(line):
                flush_group()
                continue
            current_group.append(line)

        flush_group()
        return groups

    @staticmethod
    def _flatten_groups(groups: List[List[str]]) -> List[str]:
        return [path for group in groups for path in group]

    @staticmethod
    def _candidate_count(groups: List[List[str]]) -> int:
        return sum(max(len(group) - 1, 0) for group in groups)

    @staticmethod
    def _parse_link_count(stdout: str, fallback: int) -> int:
        linked = sum(1 for line in stdout.splitlines() if "---->" in line)
        return linked or fallback

    def _build_scan_command(
        self, source_dirs: List[str], hash_db: Optional[str]
    ) -> List[str]:
        cmd = ["jdupes", "-r", "-M", "-X", VIDEO_EXT_FILTER]
        if hash_db:
            cmd.extend(["-y", hash_db])
        cmd.extend(source_dirs)
        return cmd

    def _build_link_command(
        self, source_dirs: List[str], hash_db: Optional[str]
    ) -> List[str]:
        cmd = ["jdupes", "-r", "-L", "-X", VIDEO_EXT_FILTER]
        if hash_db:
            cmd.extend(["-y", hash_db])
        cmd.extend(source_dirs)
        return cmd

    def _source_label(self, item: Dict[str, Any]) -> str:
        source_dirs = item.get("source_dirs")
        if isinstance(source_dirs, list) and source_dirs:
            return ", ".join(source_dirs)
        return item.get("source_dir", "Unknown")

    def print_output(self, output: list[dict]) -> None:
        total_relinked = 0
        total_candidates = 0
        for item in output:
            path = self._source_label(item)
            field_message = item["field_message"]
            files = item["output"]
            sub_count = item["sub_count"]
            linked_count = item.get("linked_count", 0)
            error = item.get("error")

            self.logger.debug(f"Findings for path: {path}")
            self.logger.debug(f"\t{field_message}")
            if error:
                self.logger.error(f"\t{error}")
            for i in files:
                self.logger.debug(f"\t\t{i}")
            total_candidates += sub_count
            total_relinked += linked_count
            self.logger.debug(
                f"\tTotal duplicate relink candidates for '{path}': {sub_count}"
            )
        if self.config.dry_run:
            self.logger.info(f"Total items that would be relinked: {total_candidates}")
        else:
            self.logger.info(f"Total items relinked: {total_relinked}")

    def _send_output(self, output: list[dict]) -> None:
        self.print_output(output)
        manager = NotificationManager(
            self.full_config, self.logger, module_name="jduparr"
        )
        manager.send_notification(output)

    def run(self) -> None:
        try:
            if self.config.dry_run:
                table = [["Dry Run"], ["NO CHANGES WILL BE MADE"]]
                self.logger.info(create_table(table))

            output = []

            # Expect self.config.source_dirs to always be present
            if not self.config.source_dirs:
                self.logger.error(
                    f"No source directories provided in config: {self.config.source_dirs}"
                )
                return

            if self.config.log_level.lower() == "debug":
                print_settings(self.logger, self.config)

            hash_db = self.config.hash_database
            if hash_db:
                # Reject anything that isn't a plain filesystem path — no null bytes,
                # no CLI-option smuggling (a value starting with '-' would be read
                # as another jdupes flag even in list-form subprocess).
                if "\x00" in hash_db or hash_db.startswith("-"):
                    self.logger.error(
                        f"Refusing unsafe hash_database value: {hash_db!r}"
                    )
                    return
                hash_db_dir = os.path.dirname(os.path.abspath(hash_db))
                if not os.path.isdir(hash_db_dir):
                    self.logger.error(
                        f"hash_database parent directory does not exist: {hash_db_dir}"
                    )
                    return

            valid_source_dirs = []
            for path in self.config.source_dirs:
                if self.is_cancelled():
                    self.logger.info("Cancellation requested, stopping jduparr.")
                    return
                if self._is_unsafe_path_value(path):
                    message = f"Refusing unsafe source directory value: {path!r}"
                    self.logger.error(message)
                    output.append(
                        {
                            "source_dir": str(path),
                            "source_dirs": [str(path)],
                            "field_message": "❌ Source directory was not scanned.",
                            "output": [],
                            "groups": [],
                            "sub_count": 0,
                            "linked_count": 0,
                            "status": "error",
                            "error": message,
                        }
                    )
                    continue
                if not os.path.isdir(path):
                    message = f"ERROR: path does not exist: {path}"
                    self.logger.error(message)
                    output.append(
                        {
                            "source_dir": path,
                            "source_dirs": [path],
                            "field_message": "❌ Source directory was not scanned.",
                            "output": [],
                            "groups": [],
                            "sub_count": 0,
                            "linked_count": 0,
                            "status": "error",
                            "error": message,
                        }
                    )
                    continue
                valid_source_dirs.append(path)

            if not valid_source_dirs:
                self._send_output(output)
                return

            scan_cmd = self._build_scan_command(valid_source_dirs, hash_db)
            try:
                scan_result = subprocess.run(
                    scan_cmd, capture_output=True, text=True, check=False
                )
            except FileNotFoundError:
                self.logger.error("jdupes not found. Ensure it is installed.")
                return

            if scan_result.returncode != 0:
                error_text = (scan_result.stderr or scan_result.stdout or "").strip()
                message = (
                    f"jdupes scan failed with exit code {scan_result.returncode}: "
                    f"{error_text or 'no error output'}"
                )
                self.logger.error(message)
                output.append(
                    {
                        "source_dir": ", ".join(valid_source_dirs),
                        "source_dirs": valid_source_dirs,
                        "field_message": "❌ Duplicate scan failed.",
                        "output": [],
                        "groups": [],
                        "sub_count": 0,
                        "linked_count": 0,
                        "status": "error",
                        "error": message,
                    }
                )
                self._send_output(output)
                return

            duplicate_groups = self.parse_duplicate_groups(scan_result.stdout)
            parsed_files = self._flatten_groups(duplicate_groups)
            candidate_count = self._candidate_count(duplicate_groups)
            linked_count = 0
            status = "ok"
            error_message = None

            if duplicate_groups and not self.config.dry_run:
                link_cmd = self._build_link_command(valid_source_dirs, hash_db)
                try:
                    link_result = subprocess.run(
                        link_cmd, capture_output=True, text=True, check=False
                    )
                except FileNotFoundError:
                    self.logger.error("jdupes not found. Ensure it is installed.")
                    return

                if link_result.returncode != 0:
                    status = "error"
                    error_text = (
                        link_result.stderr or link_result.stdout or ""
                    ).strip()
                    error_message = (
                        f"jdupes hardlink failed with exit code {link_result.returncode}: "
                        f"{error_text or 'no error output'}"
                    )
                    self.logger.error(error_message)
                else:
                    linked_count = self._parse_link_count(
                        link_result.stdout, candidate_count
                    )

            if not duplicate_groups:
                field_message = "✅ No duplicate files discovered..."
            elif self.config.dry_run:
                field_message = f"❌ Duplicate files discovered; {candidate_count} files would be relinked..."
            elif status == "error":
                field_message = "❌ Duplicate files discovered, but relinking failed..."
            else:
                field_message = (
                    f"✅ Duplicate files discovered; {linked_count} files relinked..."
                )

            output.append(
                {
                    "source_dir": ", ".join(valid_source_dirs),
                    "source_dirs": valid_source_dirs,
                    "field_message": field_message,
                    "output": parsed_files,
                    "groups": duplicate_groups,
                    "sub_count": candidate_count,
                    "linked_count": linked_count,
                    "status": status,
                    "error": error_message,
                }
            )

            self._send_output(output)

        except KeyboardInterrupt:
            print("Keyboard Interrupt detected. Exiting...")
            return
        except Exception:
            self.logger.error("An error occurred:", exc_info=True)
        finally:
            self.logger.log_outro()
