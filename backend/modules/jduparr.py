# modules/jduparr.py

import json
import os
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from backend.util.base_module import ChubModule
from backend.util.helper import as_list, create_table, print_settings
from backend.util.logger import Logger
from backend.util.notification import NotificationManager


VIDEO_EXT_FILTER = "onlyext:mp4,mkv,avi"

# jdupes can legitimately run for a long time on large libraries, but it must
# not be able to wedge the scheduler worker forever (e.g. a stale NFS mount).
# Generous ceiling; both the scan and link passes are bounded by it.
JDUPES_TIMEOUT_SECONDS = 6 * 60 * 60  # 6 hours


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
    def parse_duplicate_groups(stdout: str) -> List[List[str]]:
        """Parse ``jdupes --json`` output into duplicate-file groups.

        jdupes emits ``{"matchSets": [{"fileList": [{"filePath": ...}, ...]}]}``.
        Using the structured JSON output (instead of the line-oriented ``-M``
        text) means real file paths can never be mistaken for summary lines.
        Only sets with more than one file are genuine duplicate groups.
        """
        text = (stdout or "").strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return []

        groups: List[List[str]] = []
        for match_set in as_list(data.get("matchSets")):
            if not isinstance(match_set, dict):
                continue
            paths = [
                entry.get("filePath")
                for entry in as_list(match_set.get("fileList"))
                if isinstance(entry, dict) and entry.get("filePath")
            ]
            if len(paths) > 1:
                groups.append(paths)
        return groups

    @staticmethod
    def _flatten_groups(groups: List[List[str]]) -> List[str]:
        return [path for group in groups for path in group]

    @staticmethod
    def _safe_inode(path: str) -> Optional[Tuple[int, int]]:
        """(device, inode) for a path, or None if it can't be stat'd."""
        # lstat, not stat: jdupes does not follow symlinks without -s, so a link
        # planted between the two passes must never be traversed here either.
        try:
            st = os.lstat(path)
        except OSError:
            return None
        return (st.st_dev, st.st_ino)

    @classmethod
    def _inode_map(
        cls, groups: List[List[str]]
    ) -> Dict[str, Optional[Tuple[int, int]]]:
        """Snapshot every grouped path's file identity."""
        return {path: cls._safe_inode(path) for path in cls._flatten_groups(groups)}

    @classmethod
    def _unlinked_paths(
        cls, groups: List[List[str]], inodes: Dict[str, Optional[Tuple[int, int]]]
    ) -> List[str]:
        """Grouped paths not sharing their group's master inode."""
        # Any consistent anchor works — a fully linked group shares one inode —
        # so group[0] serves for both snapshots: before = candidates, after = leftovers.
        unlinked: List[str] = []
        for group in groups:
            master = next(
                (inodes[path] for path in group if inodes.get(path) is not None), None
            )
            if master is None:
                continue
            unlinked.extend(
                path
                for path in group
                if inodes.get(path) is not None and inodes[path] != master
            )
        return unlinked

    @staticmethod
    def _relinked_paths(
        before: Dict[str, Optional[Tuple[int, int]]],
        after: Dict[str, Optional[Tuple[int, int]]],
    ) -> List[str]:
        """Paths whose inode actually moved across the link pass."""
        return [
            path
            for path, was in before.items()
            if was is not None and after.get(path) is not None and after[path] != was
        ]

    @staticmethod
    def _error_item(
        source_dirs: List[str], field_message: str, message: str
    ) -> Dict[str, Any]:
        """Build an error-status output row for the given source dirs."""
        return {
            "source_dir": ", ".join(source_dirs),
            "source_dirs": list(source_dirs),
            "field_message": field_message,
            "output": [],
            "groups": [],
            "sub_count": 0,
            "linked_count": 0,
            "failed": [],
            "status": "error",
            "error": message,
        }

    def _build_scan_command(
        self, source_dirs: List[str], hash_db: Optional[str]
    ) -> List[str]:
        # --json is mutually exclusive with the -L link action (jdupes allows
        # only one print/action mode per run), so discovery and linking are
        # necessarily two separate passes. --json gives machine-readable match
        # sets, avoiding fragile text parsing of the -M output.
        cmd = ["jdupes", "-r", "--json", "-X", VIDEO_EXT_FILTER]
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
            for failed_path in item.get("failed") or []:
                self.logger.warning(f"\tStill unlinked: {failed_path}")
            total_candidates += sub_count
            total_relinked += linked_count
            self.logger.debug(
                f"\tTotal duplicate relink candidates for '{path}': {sub_count}"
            )
        if self.config.dry_run:
            self.logger.info(f"Total items that would be relinked: {total_candidates}")
            self.logger.info(f"   → {total_candidates} files would be relinked")
        else:
            self.logger.info(f"Total items relinked: {total_relinked}")
            self.logger.info(f"   → {total_relinked} files relinked")

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
                        self._error_item(
                            [str(path)],
                            "❌ Source directory was not scanned.",
                            message,
                        )
                    )
                    continue
                if not os.path.isdir(path):
                    message = f"ERROR: path does not exist: {path}"
                    self.logger.error(message)
                    output.append(
                        self._error_item(
                            [path], "❌ Source directory was not scanned.", message
                        )
                    )
                    continue
                valid_source_dirs.append(path)

            if not valid_source_dirs:
                self._send_output(output)
                return

            if self.is_cancelled():
                self.logger.info("Cancellation requested, stopping jduparr.")
                return

            scan_cmd = self._build_scan_command(valid_source_dirs, hash_db)
            try:
                scan_result = subprocess.run(
                    scan_cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=JDUPES_TIMEOUT_SECONDS,
                )
            except FileNotFoundError:
                message = "jdupes not found. Ensure it is installed."
                self.logger.error(message)
                output.append(
                    self._error_item(valid_source_dirs, "❌ Duplicate scan failed.", message)
                )
                self._send_output(output)
                return
            except subprocess.TimeoutExpired:
                message = (
                    f"jdupes scan timed out after {JDUPES_TIMEOUT_SECONDS} seconds."
                )
                self.logger.error(message)
                output.append(
                    self._error_item(valid_source_dirs, "❌ Duplicate scan failed.", message)
                )
                self._send_output(output)
                return

            if scan_result.returncode != 0:
                error_text = (scan_result.stderr or scan_result.stdout or "").strip()
                message = (
                    f"jdupes scan failed with exit code {scan_result.returncode}: "
                    f"{error_text or 'no error output'}"
                )
                self.logger.error(message)
                output.append(
                    self._error_item(
                        valid_source_dirs, "❌ Duplicate scan failed.", message
                    )
                )
                self._send_output(output)
                return

            duplicate_groups = self.parse_duplicate_groups(scan_result.stdout)
            parsed_files = self._flatten_groups(duplicate_groups)
            # Snapshot before linking: comparing inodes across the link pass is
            # the only way to tell a real relink from a file jdupes had already
            # linked, and the only proof that -L actually did the work.
            inodes_before = self._inode_map(duplicate_groups)
            candidate_count = len(self._unlinked_paths(duplicate_groups, inodes_before))
            linked_count = 0
            relink_failures: List[str] = []
            status = "ok"
            error_message = None

            if duplicate_groups and not self.config.dry_run:
                if self.is_cancelled():
                    self.logger.info("Cancellation requested, stopping jduparr.")
                    return

                link_cmd = self._build_link_command(valid_source_dirs, hash_db)
                link_result = None
                try:
                    link_result = subprocess.run(
                        link_cmd,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=JDUPES_TIMEOUT_SECONDS,
                    )
                except FileNotFoundError:
                    status = "error"
                    error_message = "jdupes not found. Ensure it is installed."
                    self.logger.error(error_message)
                except subprocess.TimeoutExpired:
                    status = "error"
                    error_message = (
                        f"jdupes hardlink timed out after "
                        f"{JDUPES_TIMEOUT_SECONDS} seconds."
                    )
                    self.logger.error(error_message)

                if link_result is not None and link_result.returncode != 0:
                    status = "error"
                    error_text = (
                        link_result.stderr or link_result.stdout or ""
                    ).strip()
                    error_message = (
                        f"jdupes hardlink failed with exit code {link_result.returncode}: "
                        f"{error_text or 'no error output'}"
                    )
                    self.logger.error(error_message)

                # Measure whatever the run achieved, failed exit included: jdupes
                # links what it can before reporting a per-file failure, so a
                # partial success is real and must not be reported as zero.
                if link_result is not None:
                    inodes_after = self._inode_map(duplicate_groups)
                    relinked = self._relinked_paths(inodes_before, inodes_after)
                    relink_failures = self._unlinked_paths(
                        duplicate_groups, inodes_after
                    )
                    linked_count = len(relinked)
                    for relinked_path in relinked:
                        self.logger.debug(f"[RELINKED] {relinked_path}")
                    for failed_path in relink_failures:
                        self.logger.warning(f"[NOT RELINKED] {failed_path}")

            if not duplicate_groups:
                field_message = "✅ No duplicate files discovered..."
            elif self.config.dry_run:
                field_message = f"❌ Duplicate files discovered; {candidate_count} files would be relinked..."
            elif status == "error":
                field_message = (
                    f"❌ Duplicate files discovered; relinking failed after "
                    f"{linked_count} of {candidate_count} files..."
                )
            elif relink_failures:
                field_message = (
                    f"❌ Duplicate files discovered; {linked_count} files relinked, "
                    f"{len(relink_failures)} still unlinked..."
                )
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
                    "failed": relink_failures,
                    "status": status,
                    "error": error_message,
                }
            )

            self._send_output(output)

        except KeyboardInterrupt:
            self.logger.info("Keyboard Interrupt detected. Exiting...")
            return
        except Exception:
            self.logger.error("An error occurred:", exc_info=True)
        finally:
            self.logger.log_outro()
