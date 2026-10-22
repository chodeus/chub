# modules/renameinatorr.py

import posixpath
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from backend.util.arr import BaseARRClient, create_arr_client, relative_to
from backend.util.base_module import ChubModule
from backend.util.constants import season_regex
from backend.util.helper import create_table, print_settings, progress
from backend.util.logger import Logger
from backend.util.notification import NotificationManager
from backend.util.rename_checks import (
    BLOCKED,
    HELD,
    MOVE,
    FileOutcome,
    check_files,
    fold,
    plan_folders,
    records_drifted,
    root_of,
    taken_paths,
    untracked,
)

_DONE = "done"
_SKIPPED = "skipped"
_UNFINISHED = "unfinished"
# Past 4 the *arr gets slower: each request's database queries wait on SQLite locks in the *arr
_THREADS = 4


def _in_parallel(fn: Callable[[Any], Any], items: List[Any]) -> List[Any]:
    """`fn` over `items` on up to _THREADS threads, results in order; `fn` must use threadsafe reads."""
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(_THREADS, len(items))) as pool:
        return list(pool.map(fn, items))


@dataclass
class _Change:
    """An item this chunk renames or moves, with its files before and after."""

    item: Dict[str, Any]
    renames: Dict[str, str]
    target: Optional[str] = None
    disk: Set[str] = field(default_factory=set)
    records: Dict[int, str] = field(default_factory=dict)
    sent: bool = True
    move_sent: bool = True
    folder: str = ""
    disk_after: Set[str] = field(default_factory=set)
    records_after: Dict[int, str] = field(default_factory=dict)
    outcome: Optional[FileOutcome] = None


class Renameinatorr(ChubModule):
    def __init__(self, logger: Optional[Logger] = None) -> None:
        super().__init__(logger=logger)

    @staticmethod
    def print_output(output: Dict[str, Dict[str, Any]], logger: Logger) -> None:
        for instance_data in output.values():
            name = instance_data["server_name"]
            logger.info(create_table([[f"{name.capitalize()} Rename List"]]))
            if instance_data.get("stopped"):
                logger.warning(f"Stopped on {name}: {instance_data['stopped']}")
            for item in instance_data["data"]:
                Renameinatorr._log_item(item, logger)
            logger.info("")
            Renameinatorr._log_summary(name, instance_data["data"], logger)
            logger.info("")

    @staticmethod
    def _log_item(item: Dict[str, Any], logger: Logger) -> None:
        """Log one item's renames, held or blocked folder, and problems."""
        notes = []
        if item["new_path_name"]:
            notes.append(
                f"\tFolder Renamed: {item['path_name']} -> {item['new_path_name']}"
            )
        if item.get("held"):
            notes.append(f"\tFolder Held: {item['path_name']} ({item['held']})")
        if item.get("blocked"):
            notes.append(
                f"\tFolder Not Renamed: {item['path_name']} ({item['blocked']})"
            )
        problems = item.get("problems", [])
        if not (notes or problems or item["file_info"]):
            return
        logger.info(f"{item['title']} ({item['year']})")
        for note in notes:
            logger.info(note)
        for problem in problems:
            logger.warning(f"\tProblem: {problem}")
        if item["file_info"]:
            logger.info("\tFiles:")
            for existing_path, new_path in item["file_info"].items():
                logger.info(f"\t\tOriginal: {existing_path}\n\t\tNew: {new_path}\n")

    @staticmethod
    def _log_summary(name: str, data: List[Dict[str, Any]], logger: Logger) -> None:
        """Log the instance's rename counts, or that nothing was renamed."""
        counts = [
            ("Total Renamed Items", sum(bool(v["file_info"]) for v in data)),
            ("Total Folder Renames", sum(bool(v["new_path_name"]) for v in data)),
            ("Folder Renames Held", sum(bool(v.get("held")) for v in data)),
            ("Folders Not Renamed", sum(bool(v.get("blocked")) for v in data)),
            ("Items With Problems", sum(bool(v.get("problems")) for v in data)),
        ]
        if not any(count for _, count in counts):
            logger.info(f"No items renamed in {name}.")
            return
        table = [[f"{name.capitalize()} Rename Summary"], [f"Total Items: {len(data)}"]]
        table += [[f"{label}: {count}"] for label, count in counts if count]
        logger.info(create_table(table))

    @staticmethod
    def get_count_for_instance_type(
        config: Any, instance_type: str, logger: Logger
    ) -> int:
        count = config.count
        override = getattr(config, f"{instance_type}_count", None)
        if override:
            logger.debug(
                f"{instance_type}_count found! overriding count from {config.count} to {override}"
            )
            count = override
        logger.info(f"using count= {count} for instance_type= {instance_type}")
        return count

    @staticmethod
    def get_chunks_for_run(
        media_dict: List[Dict[str, Any]], chunk_size: int, logger: Logger
    ) -> List[List[Dict[str, Any]]]:
        chunks: List[List[Dict[str, Any]]] = []
        for i in range(0, len(media_dict), chunk_size):
            chunks.append(media_dict[i : i + chunk_size])
        return chunks

    @staticmethod
    def _tag_labels(item: Dict[str, Any]) -> Set[str]:
        """The item's tags in lower case; normalize_arr_media stores labels, not ids."""
        return {str(tag).lower() for tag in item.get("tags") or []}

    @staticmethod
    def get_untagged_chunks_for_run(
        media_dict: List[Dict[str, Any]],
        tag: Set[str],
        chunk_size: int,
        all_in_single_run: bool,
        logger: Logger,
    ) -> List[List[Dict[str, Any]]]:
        """Chunks of the items carrying none of `tag` (one tag's spellings); with an empty set, of every item."""
        all_items_without_tags = [
            item for item in media_dict if not tag & Renameinatorr._tag_labels(item)
        ]
        if all_in_single_run or not chunk_size:
            return [all_items_without_tags] if all_items_without_tags else []
        return Renameinatorr.get_chunks_for_run(
            all_items_without_tags, chunk_size, logger
        )

    @staticmethod
    def ignore_labels(config: Any) -> Set[str]:
        """The configured (comma-separated) ignore tags, in lower case."""
        names = str(getattr(config, "ignore_tags", "") or "").split(",")
        return {name.strip().lower() for name in names if name.strip()}

    @staticmethod
    def filter_ignored(
        media_dict: List[Dict[str, Any]], ignore_labels: Set[str]
    ) -> List[Dict[str, Any]]:
        """Drop items carrying any of the ignore tags."""
        if not ignore_labels:
            return media_dict
        return [
            item
            for item in media_dict
            if not ignore_labels & Renameinatorr._tag_labels(item)
        ]

    @staticmethod
    def _tag_spellings(app: BaseARRClient, labels: Set[str]) -> Optional[Set[str]]:
        """`labels` plus each one's id as text, which an item carries when its label lookup failed; None when the tags can't be read."""
        tags = app.get_all_tags()
        if not isinstance(tags, list):
            return None
        ids = {
            str(tag.get("id"))
            for tag in tags
            if isinstance(tag, dict) and str(tag.get("label", "")).lower() in labels
        }
        return labels | ids

    @staticmethod
    def _find_tag_id(app: BaseARRClient, label: str) -> Optional[int]:
        """The id of the tag called `label`, without creating it; None when there's none."""
        return next(
            (
                tag["id"]
                for tag in app.get_all_tags() or []
                if str(tag.get("label", "")).lower() == label
            ),
            None,
        )

    def _cycle_chunks(
        self,
        app: BaseARRClient,
        media_dict: List[Dict[str, Any]],
        tag_id: int,
        cycle_tag: Set[str],
        chunk_size: int,
        all_in_single_run: bool,
        ignore_labels: Set[str],
        dry_run: bool,
        logger: Logger,
    ) -> List[List[Dict[str, Any]]]:
        """The untagged chunks of the tag cycle; once every item is tagged, clears the tags and starts again."""
        chunks = self.get_untagged_chunks_for_run(
            media_dict, cycle_tag, chunk_size, all_in_single_run, logger
        )
        if chunks and any(chunks):
            return chunks
        if dry_run:
            logger.info(
                "All media is tagged; a real run would clear the tags and start again."
            )
            return self.get_untagged_chunks_for_run(
                media_dict, set(), chunk_size, all_in_single_run, logger
            )
        logger.info("All media is tagged. Removing tags...")
        app.remove_tags([item["media_id"] for item in media_dict], tag_id)
        media_dict = self.filter_ignored(app.get_all_media(), ignore_labels)
        return self.get_untagged_chunks_for_run(
            media_dict, cycle_tag, chunk_size, all_in_single_run, logger
        )

    def process_instance(
        self,
        app: BaseARRClient,
        instance_type: str,
        config: Any,
        logger: Logger,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """The instance's rename report, and why it stopped early (None when it didn't)."""
        table = [[f"Processing {app.instance_name}"]]
        logger.debug(create_table(table))
        default_batch_size: int = 100
        instance_start_time: float = time.time()
        media_dict: List[Dict[str, Any]] = app.get_all_media()
        # Before the ignore filter: ignored items still occupy their folders
        taken = taken_paths(media_dict)
        count: int = self.get_count_for_instance_type(config, instance_type, logger)
        tag_id: Any = None
        dry_run = getattr(config, "dry_run", False)

        # Re-applied after every re-fetch below (the tag-cycle reset), so an ignored item never comes back
        ignore_labels = self.ignore_labels(config)
        if ignore_labels:
            ignore_labels = self._tag_spellings(app, ignore_labels)
            if ignore_labels is None:
                return (
                    [],
                    "its tags couldn't be read, so the ignore tags couldn't be applied",
                )
            before_count = len(media_dict)
            media_dict = self.filter_ignored(media_dict, ignore_labels)
            skipped_count = before_count - len(media_dict)
            if skipped_count > 0:
                logger.info(
                    f"Skipped {skipped_count} items due to ignore tags '{config.ignore_tags}'."
                )

        # Tagging logic: filter untagged, clear if all tagged, then chunk
        enable_batching = getattr(config, "enable_batching", False)
        tag_label = str(getattr(config, "tag_name", "") or "").strip().lower()
        if tag_label:
            # A dry run only looks the tag up: get_tag_id_from_name creates a missing one
            tag_id = (
                self._find_tag_id(app, tag_label)
                if dry_run
                else app.get_tag_id_from_name(tag_label)
            )
            if tag_id is not None:
                chunk_size = (
                    count if count else (default_batch_size if enable_batching else 0)
                )
                chunks_to_process_this_run = self._cycle_chunks(
                    app,
                    media_dict,
                    tag_id,
                    {tag_label, str(tag_id)},
                    chunk_size,
                    not enable_batching and not count,
                    ignore_labels,
                    dry_run,
                    logger,
                )
                if not enable_batching and chunks_to_process_this_run:
                    # Non-batched: only process the first chunk
                    chunks_to_process_this_run = [chunks_to_process_this_run[0]]
            else:
                # tag_name set but tag doesn't exist yet — process all media
                chunks_to_process_this_run = [media_dict] if media_dict else []
        else:
            # No tagging — chunk all media
            if not enable_batching:
                if not count:
                    chunks_to_process_this_run: List[List[Dict[str, Any]]] = [
                        media_dict
                    ]
                else:
                    chunks_to_process_this_run = self.get_chunks_for_run(
                        media_dict, count, logger
                    )
                    chunks_to_process_this_run = (
                        [chunks_to_process_this_run[0]]
                        if chunks_to_process_this_run
                        else []
                    )
            else:
                count = count if count else default_batch_size
                chunks_to_process_this_run = self.get_chunks_for_run(
                    media_dict, count, logger
                )
        logger.info(f"num_chunks= {len(chunks_to_process_this_run)}")
        final_media_dict: List[Dict[str, Any]] = []
        stopped: Optional[str] = None
        chunk_progress_bar = progress(
            chunks_to_process_this_run,
            desc=f"Processing batches for '{app.instance_name}'...",
            unit="items",
            logger=logger,
            leave=True,
        )
        for chunk in chunk_progress_bar:
            if self.is_cancelled():
                break
            if not chunk:
                continue
            chunk_start_time: float = time.time()
            logger.debug(f"Processing {len(chunk)} media items in current chunk")
            logger.info("Processing data... This may take a while.")
            stopped = self._process_chunk(app, chunk, config, logger, tag_id, taken)
            final_media_dict.extend(chunk)
            total_renamed = sum(
                len(i["file_info"]) for i in chunk if i.get("file_info")
            )
            total_folder_renamed = sum(bool(i.get("new_path_name")) for i in chunk)
            logger.info(
                f"Chunk completed in {time.time() - chunk_start_time:.2f} seconds | "
                f"Files renamed: {total_renamed} | Folders renamed: {total_folder_renamed}"
            )
            if stopped:
                logger.warning(
                    f"Stopping {app.instance_name} here, so nothing more is renamed "
                    f"until this is looked at: {stopped}"
                )
                break
        logger.info(
            f"Finished processing {app.instance_name} in {time.time() - instance_start_time:.2f} seconds."
        )
        final_media_dict.sort(key=lambda it: it.get("new_path_name") or it["path_name"])
        trimmed: List[Dict[str, Any]] = []
        for item in final_media_dict:
            raw_info = item.get("file_info", {})
            sorted_info = {old: raw_info[old] for old in sorted(raw_info.keys())}
            trimmed.append(
                {
                    "title": item["title"],
                    "year": item["year"],
                    "path_name": item["path_name"],
                    "new_path_name": item.get("new_path_name"),
                    "file_info": sorted_info,
                    "held": item.get("held"),
                    "blocked": item.get("blocked"),
                    "problems": item.get("problems", []),
                }
            )
        return trimmed, stopped

    def _process_chunk(
        self,
        app: BaseARRClient,
        chunk: List[Dict[str, Any]],
        config: Any,
        logger: Logger,
        tag_id: Any,
        taken: Set[str],
    ) -> Optional[str]:
        """Rename one chunk's files and folders; returns why the instance should stop, or None."""
        stop, changes = self._plan_chunk(app, chunk, config, taken, logger)
        if stop or getattr(config, "dry_run", False):
            return stop
        if self.is_cancelled():
            for item in chunk:
                item["file_info"] = {}
            return None
        if not changes:
            logger.info(f"No media to rename on {app.instance_name}...")
            self._tag(app, chunk, config, tag_id, logger)
            return None
        return self._apply_changes(app, chunk, changes, config, tag_id, logger)

    def _plan_chunk(
        self,
        app: BaseARRClient,
        chunk: List[Dict[str, Any]],
        config: Any,
        taken: Set[str],
        logger: Logger,
    ) -> Tuple[Optional[str], List[_Change]]:
        """Each item's planned renames and folder move, or a stop reason when the plan can't be read."""
        dry_run = getattr(config, "dry_run", False)
        if getattr(config, "refresh_before_rename", False) and not dry_run:
            self._refresh_before_rename(app, chunk, logger)
        previews, expected = self._prefetch(
            app, chunk, getattr(config, "rename_folders", False)
        )
        for item in chunk:
            item.update(
                new_path_name=None, held=None, blocked=None, problems=[], retry=False
            )
        if expected and all(name is None for name in expected.values()):
            return "its folder names couldn't be read, so this batch wasn't renamed", []
        targets = self._plan_moves(app, chunk, expected, taken) if expected else {}
        if targets is None:
            return "a root folder couldn't be listed, so this batch wasn't renamed", []
        changes: List[_Change] = []
        for item in chunk:
            renames = self._renames(item, previews.get(item["media_id"]))
            target = targets.get(item["media_id"])
            item["file_info"] = self._display(renames)
            if dry_run:
                item["new_path_name"] = target
            if renames or target:
                changes.append(_Change(item, renames, target))
        return None, changes

    def _apply_changes(
        self,
        app: BaseARRClient,
        chunk: List[Dict[str, Any]],
        changes: List[_Change],
        config: Any,
        tag_id: Any,
        logger: Logger,
    ) -> Optional[str]:
        """Rename, move, check and tag one batch; returns why the instance should stop, or None."""
        changes = self._snapshot(app, changes)
        # Just before the rename: a refresh beside a rename or move saves what it read first, undoing the change
        if not app.wait_for_refreshes("before renaming"):
            for change in changes:
                change.item["file_info"] = {}
            return "a refresh was still running, so this batch wasn't renamed"
        if not self._rename_files(app, changes, logger):
            return "the file renames didn't finish, so this batch wasn't checked"
        moved = self._move_folders(app, changes, logger)
        if moved == _UNFINISHED:
            return "the folder moves didn't finish, so this batch wasn't checked"
        verified = self._verify(app, changes, logger)
        request_failed = any(not c.sent or not c.move_sent for c in changes)
        # A skipped move or a failed request retries the whole batch next run; an item's own problem waits a cycle
        if moved != _SKIPPED and not request_failed:
            self._tag(app, chunk, config, tag_id, logger)
        return self._stop_reason(verified, request_failed, moved)

    @staticmethod
    def _stop_reason(verified: bool, request_failed: bool, moved: str) -> Optional[str]:
        """Why the instance should stop after a batch that ran, or None."""
        if not verified:
            return "some renamed items' files need checking (see their problems)"
        if request_failed:
            return "a rename or move request to the arr failed, so this batch will be tried again"
        if moved == _SKIPPED:
            return (
                "a refresh was still running, so this batch's folders weren't renamed"
            )
        return None

    @staticmethod
    def _refresh_before_rename(
        app: BaseARRClient, chunk: List[Dict[str, Any]], logger: Logger
    ) -> None:
        """Refresh the chunk first, so renames pick up titles that have changed (e.g. Sonarr TBA episodes)."""
        ids = [item["media_id"] for item in chunk]
        logger.info(
            f"Refreshing metadata for {len(ids)} item(s) before rename check..."
        )
        if app.refresh_and_wait(ids):
            logger.info("Metadata refresh complete; checking rename list...")
        else:
            logger.warning(
                "Metadata refresh did not complete cleanly; "
                "proceeding with rename check anyway."
            )

    @staticmethod
    def _prefetch(
        app: BaseARRClient, chunk: List[Dict[str, Any]], with_folders: bool
    ) -> Tuple[Dict[int, Any], Optional[Dict[int, Optional[str]]]]:
        """Each item's rename preview and, with `with_folders`, the folder name the arr wants for it."""

        # Read-only GETs on private sessions (threadsafe=True); every state change stays in the caller
        def fetch(item):
            folder = (
                app.get_expected_folder(item, threadsafe=True) if with_folders else None
            )
            return (
                item["media_id"],
                app.get_rename_list(item["media_id"], threadsafe=True),
                folder,
            )

        previews: Dict[int, Any] = {}
        expected: Dict[int, Optional[str]] = {}
        for media_id, preview, folder in _in_parallel(fetch, chunk):
            previews[media_id] = preview
            expected[media_id] = folder
        return previews, expected if with_folders else None

    @staticmethod
    def _plan_moves(
        app: BaseARRClient,
        chunk: List[Dict[str, Any]],
        expected: Dict[int, Optional[str]],
        taken: Set[str],
    ) -> Optional[Dict[int, str]]:
        """The folder name each item moves to, marking held and blocked items; None when a root folder can't be listed."""
        roots = {
            root_of(item)
            for item in chunk
            if expected.get(item["media_id"]) not in (None, item["path_name"])
        } - {None}
        listings = {root: app.list_folders(root) for root in roots}
        if any(names is None for names in listings.values()):
            return None
        verdicts = plan_folders(chunk, expected, taken, listings)
        targets: Dict[int, str] = {}
        for item in chunk:
            verdict = verdicts[item["media_id"]]
            if verdict.action == MOVE:
                targets[item["media_id"]] = expected[item["media_id"]]
            elif verdict.action == HELD:
                item["held"] = verdict.reason
            elif verdict.action == BLOCKED:
                item["blocked"] = verdict.reason
            # None is a failed read, so look again next run; "" means the arr has no name for it
            item["retry"] = expected.get(item["media_id"]) is None
        return targets

    @staticmethod
    def _renames(item: Dict[str, Any], preview: Any) -> Dict[str, str]:
        """The item's previewed renames as {old: new}, relative to its folder."""
        if not isinstance(preview, list):
            return {}
        folder = item.get("path") or ""
        renames: Dict[str, str] = {}
        for entry in preview:
            old = entry.get("existingPath") if isinstance(entry, dict) else None
            new = entry.get("newPath") if isinstance(entry, dict) else None
            if isinstance(old, str) and isinstance(new, str):
                renames[relative_to(old, folder)] = relative_to(new, folder)
        return renames

    @staticmethod
    def _display(renames: Dict[str, str]) -> Dict[str, str]:
        """Renames as the report shows them, without the season folder."""
        return {
            re.sub(season_regex, "", old).lstrip("/"): re.sub(
                season_regex, "", new
            ).lstrip("/")
            for old, new in renames.items()
        }

    @staticmethod
    def _tag(
        app: BaseARRClient,
        chunk: List[Dict[str, Any]],
        config: Any,
        tag_id: Any,
        logger: Logger,
    ) -> None:
        """Tag the batch as visited this cycle, except items a failed read kept from being checked."""
        done = [item["media_id"] for item in chunk if not item["retry"]]
        if not done or tag_id is None or not getattr(config, "tag_name", None):
            return
        logger.info(
            f"Adding tag '{config.tag_name}' to items in {app.instance_name}..."
        )
        app.add_tags(done, tag_id)

    @staticmethod
    def _snapshot(app: BaseARRClient, changes: List[_Change]) -> List[_Change]:
        """Read each change's files before anything moves; an item whose files can't be read is left alone."""

        def read(change):
            path, media_id = change.item.get("path"), change.item["media_id"]
            if not path:
                return None, None
            return (
                app.get_media_files(path, threadsafe=True),
                app.get_file_records(media_id, path, threadsafe=True),
            )

        readable = []
        for change, (disk, records) in zip(changes, _in_parallel(read, changes)):
            item = change.item
            if disk is None or records is None:
                item["problems"].append(
                    "its files couldn't be read, so it was left alone"
                )
                item["file_info"] = {}
                item["retry"] = True
                continue
            change.disk, change.records = disk, records
            readable.append(change)
        return readable

    def _rename_files(
        self, app: BaseARRClient, changes: List[_Change], logger: Logger
    ) -> bool:
        """Rename the previewed files and wait; False when the renames didn't finish."""
        ids = [change.item["media_id"] for change in changes if change.renames]
        if not ids:
            return True
        earlier_renames = app.command_ids(app.RENAME_COMMAND)
        if app.rename_media(ids) is None:
            logger.warning(f"The rename request to {app.instance_name} failed.")
            for change in changes:
                if change.renames:
                    change.sent = False
        if self._wait_for_renames(app, logger, earlier_renames):
            return True
        for change in changes:
            change.item["file_info"] = {}
        return False

    @staticmethod
    def _wait_for_renames(
        app: BaseARRClient, logger: Logger, earlier_renames: Optional[set]
    ) -> bool:
        """Wait for the file renames this run queued; False, with a warning, when they didn't finish."""
        # Checking or refreshing beside the renames reads files mid-rename
        if app.wait_for_commands_to_finish(
            [app.RENAME_COMMAND], "rename files", ignore_ids=earlier_renames or set()
        ):
            return True
        logger.warning(
            f"Renames on {app.instance_name} did not finish, so nothing more was done or checked."
        )
        return False

    @staticmethod
    def _move_folders(
        app: BaseARRClient, changes: List[_Change], logger: Logger
    ) -> str:
        """Move the planned folders and wait: _DONE, _SKIPPED (nothing sent) or _UNFINISHED."""
        moving = [change for change in changes if change.target]
        if not moving:
            return _DONE
        if not app.wait_for_refreshes("before moving folders"):
            logger.warning(
                f"A refresh on {app.instance_name} was still running, so no folders were renamed."
            )
            for change in moving:
                change.target = None
            return _SKIPPED
        logger.info(f"Renaming folders in {app.instance_name}...")
        by_root: Dict[str, List[int]] = defaultdict(list)
        for change in moving:
            by_root[change.item["root_folder"]].append(change.item["media_id"])
        earlier_moves = app.command_ids(app.FOLDER_MOVE_COMMAND)
        for root_folder, folder_media_ids in by_root.items():
            logger.debug(f"renaming root folder {root_folder}")
            if app.rename_folders(folder_media_ids, root_folder) is None:
                logger.warning(f"A folder move request to {app.instance_name} failed.")
                for change in moving:
                    if change.item["root_folder"] == root_folder:
                        change.move_sent = False
        if not app.wait_for_commands_to_finish(
            [app.FOLDER_MOVE_COMMAND], "rename folders", ignore_ids=earlier_moves or set()
        ):
            logger.warning(
                f"Folder moves on {app.instance_name} did not finish, so nothing was checked or refreshed."
            )
            for change in changes:
                change.item["file_info"] = {}
            return _UNFINISHED
        # Finished isn't moved: the *arr logs a folder it couldn't move and carries on, so _verify checks each one
        logger.info(f"Folder moves finished in {app.instance_name}...")
        return _DONE

    def _verify(
        self, app: BaseARRClient, changes: List[_Change], logger: Logger
    ) -> bool:
        """Check what each change did and refresh the items whose records drifted; False when files need checking."""
        if not changes:
            return True
        logger.info(f"Checking the renamed items in {app.instance_name}...")
        current = {m["media_id"]: m for m in app.get_all_media() or []}

        def read(change):
            old = change.item["path"].rstrip("/")
            now = current.get(change.item["media_id"]) or {}
            new = (now.get("path") or "").rstrip("/")
            if not new:
                return new, None, set(), None
            return (
                new,
                app.get_media_files(new, threadsafe=True),
                app.get_media_files(old, threadsafe=True) if new != old else set(),
                app.get_file_records(change.item["media_id"], new, threadsafe=True),
            )

        healthy = True
        drifted: List[_Change] = []
        for change, after in zip(changes, _in_parallel(read, changes)):
            if not self._check(change, *after, logger):
                healthy = False
            elif change.outcome.missing or change.outcome.left_behind:
                healthy = False
            elif records_drifted(change.outcome.expected_records, change.records_after):
                drifted.append(change)
        if drifted and not self._refresh_drifted(app, drifted, logger):
            healthy = False
        return healthy

    @staticmethod
    def _check(
        change: _Change,
        new: str,
        disk: Optional[Set[str]],
        left: Optional[Set[str]],
        records: Optional[Dict[int, str]],
        logger: Logger,
    ) -> bool:
        """Record what the change did to one item's files, read at `new`; False when they couldn't be read."""
        item = change.item
        old = item["path"].rstrip("/")
        # On a case-insensitive disk, a case-only rename's old path still lists the new folder
        if left and fold(new) == fold(old) and left == disk:
            left = set()
        if disk is None or left is None or records is None:
            item["problems"].append("its files couldn't be read after the change")
            item["file_info"] = {}
            item["retry"] = True
            return False
        outcome = check_files(change.disk, change.records, change.renames, disk, left)
        change.folder, change.disk_after, change.records_after = new, disk, records
        change.outcome = outcome
        item["file_info"] = Renameinatorr._display(outcome.renamed)
        new_name = posixpath.basename(new)
        if new_name != item["path_name"]:
            item["new_path_name"] = new_name
        if change.target and new_name != change.target:
            item["problems"].append(
                "its folder wasn't renamed (see the arr's logs)"
                if change.move_sent
                else "its folder wasn't renamed: the move request failed"
            )
        if outcome.not_renamed:
            count = len(outcome.not_renamed)
            item["problems"].append(
                f"{count} file(s) weren't renamed (see the arr's logs)"
                if change.sent
                else f"{count} file(s) weren't renamed: the rename request failed"
            )
        for files, what in (
            (outcome.missing, "went missing"),
            (outcome.left_behind, f"were left behind in {old}"),
        ):
            if files:
                item["problems"].append(
                    f"{len(files)} file(s) {what}, so it wasn't refreshed"
                )
                logger.warning(
                    f"{item['title']}: these files {what}:\n\t" + "\n\t".join(files)
                )
        return True

    @staticmethod
    def _refresh_drifted(
        app: BaseARRClient, drifted: List[_Change], logger: Logger
    ) -> bool:
        """Refresh the items whose records no longer match their files; False when that didn't put them right."""
        ids = [change.item["media_id"] for change in drifted]
        logger.info(
            f"Refreshing {len(ids)} item(s) on {app.instance_name} whose records don't match their files..."
        )
        if not app.refresh_and_wait(ids):
            for change in drifted:
                change.item["problems"].append(
                    "its records didn't match its files, and the refresh didn't complete"
                )
            return False
        healthy = True
        for change in drifted:
            records = app.get_file_records(change.item["media_id"], change.folder)
            lost = (
                None
                if records is None
                else untracked(
                    change.outcome.expected_records, records, change.disk_after
                )
            )
            if lost is None:
                change.item["problems"].append(
                    "its records couldn't be read after the refresh"
                )
                healthy = False
            elif lost:
                change.item["problems"].append(
                    f"the arr lost track of {len(lost)} file(s)"
                )
                logger.warning(
                    f"{change.item['title']}: the arr has no record of:\n\t"
                    + "\n\t".join(lost)
                )
                healthy = False
        return healthy

    def run(self):
        try:
            if self.config.log_level.lower() == "debug":
                print_settings(self.logger, self.config)
            if self.config.dry_run:
                table = [["Dry Run"], ["NO CHANGES WILL BE MADE"]]
                self.logger.info(create_table(table))
                self.logger.info("")

            output = {}
            for instance_type in ["radarr", "sonarr", "lidarr"]:
                instance_dict = getattr(self.full_config.instances, instance_type, {})
                for instance_name, instance_cfg in instance_dict.items():
                    if instance_name in self.config.instances:
                        app = create_arr_client(
                            instance_cfg.url,
                            instance_cfg.api,
                            self.logger,
                        )
                        if app and app.connect_status:
                            data, stopped = self.process_instance(
                                app, instance_type, self.config, self.logger
                            )
                            output[instance_name] = {
                                "server_name": app.instance_name,
                                "data": data,
                                "stopped": stopped,
                            }
            if any(value["data"] or value["stopped"] for value in output.values()):
                self.print_output(output, self.logger)
                manager = NotificationManager(
                    self.full_config, self.logger, module_name="renameinatorr"
                )
                manager.send_notification(output)
            else:
                self.logger.info("No media items to rename.")
        except KeyboardInterrupt:
            self.logger.info("Keyboard Interrupt detected. Exiting...")
            return
        except Exception:
            self.logger.error("\n\nAn error occurred:\n", exc_info=True)
            self.logger.error("\n\n")
        finally:
            self.logger.log_outro()
