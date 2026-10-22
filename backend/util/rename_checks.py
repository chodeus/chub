"""Checks renameinatorr makes before it moves a folder and after it renames or moves files."""

import posixpath
import re
import unicodedata
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

ID_TAG = re.compile(
    r"[\[{](tvdb|tmdb|tvmaze|imdb|mbid|musicbrainz)(?:id)?[-=]([^\]}]*)[\]}]",
    re.IGNORECASE,
)
YEAR = re.compile(r"\((\d{4})\)")

KEEP = "keep"
MOVE = "move"
HELD = "held"
BLOCKED = "blocked"


class FolderVerdict(NamedTuple):
    action: str
    reason: str = ""


class FileOutcome(NamedTuple):
    renamed: Dict[str, str]
    not_renamed: List[str]
    missing: List[str]
    left_behind: List[str]
    expected_records: Dict[int, str]


def fold(name: str) -> str:
    """`name` NFC-normalised and casefolded, for clash checks."""
    return unicodedata.normalize("NFC", name).casefold()


def root_of(item: Dict[str, Any]) -> Optional[str]:
    """The item's root folder in one spelling, so listings can be keyed by it."""
    root = item.get("root_folder")
    return posixpath.normpath(root) if root else None


def taken_paths(media: Iterable[Dict[str, Any]]) -> Set[str]:
    """Every item's folder path, folded."""
    return {fold(m["path"].rstrip("/")) for m in media if m.get("path")}


def _parts(name: str) -> Tuple[str, Optional[str], Dict[str, str]]:
    """A folder name's title, its last (YYYY) year and its id tags."""
    ids = {key.lower(): value for key, value in ID_TAG.findall(name)}
    rest = ID_TAG.sub("", name)
    years = list(YEAR.finditer(rest))
    if not years:
        return rest, None, ids
    last = years[-1]
    return rest[: last.start()] + rest[last.end() :], last.group(1), ids


def irregular_reasons(current: str, expected: str) -> List[str]:
    """What renaming `current` to `expected` would lose; empty when nothing."""
    title, year, ids = _parts(current)
    new_title, new_year, new_ids = _parts(expected)
    reasons = []
    if re.search(r"\w", title) and not re.search(r"\w", new_title):
        reasons.append("the new name has no title")
    if year and not new_year:
        reasons.append(f"the new name drops the year {year}")
    reasons += [
        f"the new name drops the {key} id {value}"
        for key, value in ids.items()
        if key not in new_ids
    ]
    reasons += [
        f"the new name has an empty {key} id"
        for key, value in new_ids.items()
        if value.strip() in ("", "0")
    ]
    return reasons


def plan_folder(
    item: Dict[str, Any],
    expected: Optional[str],
    taken: Set[str],
    siblings: Optional[Set[str]],
) -> FolderVerdict:
    """Whether the item's folder should move to `expected`, and why not when it shouldn't."""
    path = (item.get("path") or "").rstrip("/")
    if "\\" in path or re.match(r"^[A-Za-z]:", path):
        return FolderVerdict(BLOCKED, "folder renames don't support Windows paths")
    parent, current = posixpath.split(path)
    if not current:
        return FolderVerdict(BLOCKED, "the arr has no folder path for it")
    if expected is None:
        return FolderVerdict(BLOCKED, "the arr's folder name for it couldn't be read")
    if expected == "":
        return FolderVerdict(BLOCKED, "the arr has no folder name for it")
    if expected == current:
        return FolderVerdict(KEEP)
    if not expected.strip() or "/" in expected or expected.strip() in (".", ".."):
        return FolderVerdict(
            BLOCKED, f"the arr gives an unusable folder name ({expected!r})"
        )
    root = root_of(item)
    if root is None:
        return FolderVerdict(BLOCKED, "the arr has no root folder for it")
    # The arr moves every item to <root folder>/<name>, so a nested folder would leave its parent
    if posixpath.normpath(parent) != root:
        return FolderVerdict(
            BLOCKED,
            "it's in a subfolder of its root folder, which the move would take it out of",
        )
    if siblings is None:
        return FolderVerdict(BLOCKED, "its root folder couldn't be listed")
    if current not in siblings:
        return FolderVerdict(BLOCKED, "its folder isn't on disk")
    # The arr merges into an existing folder, overwriting files with the same name
    target = fold(posixpath.join(parent, expected))
    if target != fold(path) and target in taken:
        return FolderVerdict(BLOCKED, "another item already uses that folder")
    if any(fold(name) == fold(expected) for name in siblings if name != current):
        return FolderVerdict(BLOCKED, "a folder with that name already exists")
    reasons = irregular_reasons(current, expected)
    if reasons:
        return FolderVerdict(HELD, "; ".join(reasons))
    return FolderVerdict(MOVE)


def plan_folders(
    items: Iterable[Dict[str, Any]],
    expected: Dict[int, Optional[str]],
    taken: Set[str],
    listings: Dict[str, Optional[Set[str]]],
) -> Dict[int, FolderVerdict]:
    """A verdict per item; each planned move claims its path in `taken` so no later item takes it."""
    verdicts = {}
    for item in items:
        siblings = listings.get(root_of(item) or "")
        name = expected.get(item["media_id"])
        verdict = plan_folder(item, name, taken, siblings)
        if verdict.action == MOVE:
            parent = posixpath.dirname(item["path"].rstrip("/"))
            taken.add(fold(posixpath.join(parent, name)))
        verdicts[item["media_id"]] = verdict
    return verdicts


def check_files(
    disk_before: Set[str],
    records_before: Dict[int, str],
    renames: Dict[str, str],
    disk_after: Set[str],
    left_behind: Set[str],
) -> FileOutcome:
    """What happened to an item's files; every path is relative to the item's folder."""
    renamed = {
        old: new
        for old, new in renames.items()
        if new in disk_after and old not in disk_after
    }
    not_renamed = sorted(
        old for old in renames if old not in renamed and old in disk_after
    )
    present = disk_after | left_behind
    missing = sorted(
        name
        for name in disk_before
        if name not in present and renames.get(name) not in present
    )
    expected_records = {
        file_id: renamed.get(rel, rel) for file_id, rel in records_before.items()
    }
    return FileOutcome(
        renamed, not_renamed, missing, sorted(left_behind), expected_records
    )


def records_drifted(expected: Dict[int, str], records: Dict[int, str]) -> bool:
    """Whether the arr's records no longer match the files they should point at."""
    return any(records.get(file_id) != rel for file_id, rel in expected.items())


def untracked(
    expected: Dict[int, str], records: Dict[int, str], disk: Set[str]
) -> List[str]:
    """Files on disk that should have a record but have none."""
    tracked = set(records.values())
    return sorted(
        rel for rel in set(expected.values()) if rel in disk and rel not in tracked
    )
