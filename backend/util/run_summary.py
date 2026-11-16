"""The Run Summary block poster renamerr prints last, so the end of its log says how the run went."""

from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.util.constants import plural
from backend.util.helper import create_table
from backend.util.upload_posters import upload_skip_reason

_ORPHAN_VERBS = {"report": "found (report only)", "move": "moved", "remove": "removed"}

# A step's line and whether the step failed at its job.
Line = Tuple[str, bool]


def _as_is(line: Line) -> Line:
    return line


def _dry(line: Line, dry_run: Any) -> Line:
    """Mark a chained module's line when that module ran as its own dry run."""
    return (f"[DRY RUN] {line[0]}", line[1]) if dry_run else line


def _gdrive_text(summary: Optional[Dict[str, Any]]) -> Line:
    """``summary`` is SyncGDrive.summary, None when the sync stopped before counting its folders."""
    if not summary:
        return "stopped before it counted its folders", True
    total, synced, failed = summary["total"], summary["synced"], summary["failed"]
    if failed:
        return _dry((f"{failed}/{total} folders failed", True), summary.get("dry_run"))
    if not total:
        return "no folders in gdrive_list", False
    if synced < total:
        changes = f", {summary['changes']}" if synced else ""
        return _dry((f"stopped after {synced}/{total} folders{changes}", True), summary.get("dry_run"))
    return _dry((f"{synced}/{total} folders, {summary['changes']}", False), summary.get("dry_run"))


def _arr_text(results: List[Any]) -> Line:
    """``results`` is Connector.update_arr_database's SyncResults; a failed one names its error."""
    if not results:
        return "no arr instances", False
    failed = [r for r in results if not r.success]
    text = f"{len(results) - len(failed)}/{len(results)} instances synced"
    if not failed:
        return text, False
    more = f" (+{len(failed) - 1} more)" if len(failed) > 1 else ""
    return f"{text}, {failed[0].instance_name}: {failed[0].error_message or 'failed'}{more}", True


def _renames_text(result: Tuple[Dict[str, int], int]) -> Line:
    """``result`` is the renamed count per section and how many posters failed to stage."""
    counts, failed = result
    text = ", ".join(plural(n, kind) for kind, n in counts.items())
    return (f"{text}, {failed} failed", True) if failed else (text, False)


def _orphans_text(result: Dict[str, Any]) -> Line:
    """``result`` is run_orphan_assets_pass's: ``count`` done of ``found``, or ``skipped`` when it could not run."""
    if result.get("skipped"):
        return "skipped, see the cleanarr log", True
    verb = _ORPHAN_VERBS.get(result["mode"], result["mode"])
    text = f"{plural(result['count'], 'orphan')} {verb}"
    missed = result.get("found", result["count"]) - result["count"]
    return (f"{text}, {missed} not {verb}, see the cleanarr log", True) if missed else (text, False)


def _border_text(counts: Optional[Dict[str, int]]) -> Line:
    """``counts`` is BorderReplacerr.run's; None when it had no posters to process."""
    if counts is None:
        return "no posters to process", False
    text = f"{counts['replaced'] + counts['removed']} changed of {counts['processed']} processed"
    line = (f"{text}, {counts['failed']} failed", True) if counts["failed"] else (text, False)
    return _dry(line, counts.get("dry_run"))


def _upload_text(result: Dict[str, Any]) -> Line:
    """``result`` is PosterUploader.run's; a failed one names its first instance error, or why it did not run."""
    payload = result.get("payload") or {}
    failed = payload.get("failed", 0)
    text = f"{payload.get('updated', 0)} uploaded, {failed} failed"
    broken = [i for i in payload.get("instance_results") or [] if i.get("error")]
    if broken:
        text += f", {plural(len(broken), 'instance')} with errors ({broken[0]['error']})"
    elif not result.get("success") and not failed:
        text += f" ({upload_skip_reason(result)})"
    return text, bool(failed or broken or not result.get("success"))


def _assets_text(output: Dict[str, List[dict]]) -> Line:
    """``output`` is match_and_apply_assets': one entry per apply tried, ``applied`` False when it failed."""
    if not output:
        return "no asset types run", False
    done = [plural(sum(1 for e in entries if e.get("applied")), kind) for kind, entries in output.items()]
    failed = sum(1 for entries in output.values() for e in entries if not e.get("applied"))
    text = f"{', '.join(done)} applied"
    line = (f"{text}, {failed} failed", True) if failed else (text, False)
    return _dry(line, any(e.get("dry_run") for entries in output.values() for e in entries))


class RunSummary:
    """One line per recorded step, in run order; each is formatted in ``log``, where a fault costs only its own line."""

    def __init__(self) -> None:
        self.lines: List[Tuple[str, Callable[[Any], Line], Any]] = []

    def _add(self, label: str, text: Callable[[Any], Line], result: Any) -> None:
        self.lines.append((label, text, result))

    def gdrive_not_run(self, reason: str, failed: bool) -> None:
        self._add("GDrive sync", _as_is, (reason, failed))

    def gdrive(self, summary: Optional[Dict[str, Any]]) -> None:
        self._add("GDrive sync", _gdrive_text, summary)

    def arr(self, results: List[Any]) -> None:
        self._add("Arr sync", _arr_text, results)

    def renames(self, counts: Dict[str, int], failed: int) -> None:
        self._add("Posters renamed", _renames_text, (counts, failed))

    def orphans(self, result: Dict[str, Any]) -> None:
        self._add("Orphan cleanup", _orphans_text, result)

    def border(self, counts: Optional[Dict[str, int]]) -> None:
        self._add("Border replacerr", _border_text, counts)

    def upload(self, result: Dict[str, Any]) -> None:
        self._add("Plex upload", _upload_text, result)

    def assets(self, output: Dict[str, List[dict]]) -> None:
        self._add("Asset renamerr", _assets_text, output)

    def log(
        self,
        logger: Any,
        failure: Optional[BaseException],
        phase_failure: Optional[Tuple[str, BaseException]],
        cancelled: bool,
        dry_run: bool,
    ) -> None:
        """Log the block; a step result it cannot read costs only that step's line."""
        logger.info(create_table([["Run Summary"]]))
        if dry_run:
            logger.info("Poster renamerr ran as a dry run.")
        any_failed = False
        for label, text, step_result in self.lines:
            try:
                line, failed = text(step_result)
            except Exception as e:
                line, failed = f"could not summarise this step ({type(e).__name__}: {e})", True
            any_failed = any_failed or failed
            logger.info(f"{label:<17}: {'❌ ' if failed else ''}{line}")
        result = result_text(failure, phase_failure, cancelled, any_failed)
        logger.info(f"{'Result':<17}: {result}")


def result_text(
    failure: Optional[BaseException],
    phase_failure: Optional[Tuple[str, BaseException]],
    cancelled: bool,
    steps_failed: bool = False,
) -> str:
    """The Result line; a step is named only when its own exception ended the run."""
    if failure is None:
        if cancelled:
            return "⏹ cancelled"
        return "⚠ finished, with failures above" if steps_failed else "✅ finished"
    if isinstance(failure, KeyboardInterrupt):
        return "⏹ stopped by keyboard interrupt"
    step = phase_failure[0] if phase_failure and phase_failure[1] is failure else None
    where = f" at {step}" if step else ""
    return f"❌ failed{where}: {str(failure) or type(failure).__name__}"
