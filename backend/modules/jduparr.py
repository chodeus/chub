# modules/jduparr.py

import os
import subprocess
from typing import Optional

from backend.util.base_module import ChubModule
from backend.util.helper import create_table, print_settings
from backend.util.logger import Logger
from backend.util.notification import NotificationManager


class Jduparr(ChubModule):
    def __init__(self, logger: Optional[Logger] = None) -> None:
        super().__init__(logger=logger)

    def print_output(self, output: list[dict]) -> None:
        count = 0
        for item in output:
            path = item["source_dir"]
            field_message = item["field_message"]
            files = item["output"]
            sub_count = item["sub_count"]

            self.logger.info(f"Findings for path: {path}")
            self.logger.info(f"\t{field_message}")
            for i in files:
                count += 1
                self.logger.info(f"\t\t{i}")
            self.logger.info(
                f"\tTotal items for '{os.path.basename(os.path.normpath(path))}': {sub_count}"
            )
        self.logger.info(f"Total items relinked: {count}")

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

            for path in self.config.source_dirs:
                if self.is_cancelled():
                    self.logger.info("Cancellation requested, stopping jduparr.")
                    return
                if not os.path.isdir(path):
                    self.logger.error(f"ERROR: path does not exist: {path}")
                    return

                # Find duplicate media files with jdupes
                cmd = ["jdupes", "-r", "-M", "-X", "onlyext:mp4,mkv,avi"]
                if hash_db:
                    cmd.extend(["-y", hash_db])
                cmd.append(path)
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True).stdout
                except FileNotFoundError:
                    self.logger.error("jdupes not found. Ensure it is installed.")
                    return

                # Hardlink duplicates if not dry run and duplicates found
                if not self.config.dry_run:
                    if "No duplicates found." not in result:
                        link_cmd = ["jdupes", "-r", "-L", "-X", "onlyext:mp4,mkv,avi"]
                        if hash_db:
                            link_cmd.extend(["-y", hash_db])
                        link_cmd.append(path)
                        subprocess.run(link_cmd)

                # Parse duplicate files from output
                parsed_files = sorted(
                    set(
                        line.split("/")[-1]
                        for line in result.splitlines()
                        if "/" in line
                    )
                )
                field_message = (
                    "✅ No unlinked files discovered..."
                    if not parsed_files
                    else "❌ Unlinked files discovered..."
                )
                sub_count = len(parsed_files)

                output_data = {
                    "source_dir": path,
                    "field_message": field_message,
                    "output": parsed_files,
                    "sub_count": sub_count,
                }
                output.append(output_data)

            # Print summarized output and send notification
            self.print_output(output)
            manager = NotificationManager(
                self.config, self.logger, module_name="jduparr"
            )
            manager.send_notification(output)

        except KeyboardInterrupt:
            print("Keyboard Interrupt detected. Exiting...")
            return
        except Exception:
            self.logger.error("An error occurred:", exc_info=True)
        finally:
            self.logger.log_outro()
