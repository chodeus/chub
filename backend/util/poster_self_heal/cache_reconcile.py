# backend/util/poster_self_heal/cache_reconcile.py
"""Drop the poster_cache row for a file the healer just renamed.

Call after EVERY successful apply (scheduled and manual) — a surviving row
re-proposes the rename and collides with the file we created.
"""

from typing import Any


def drop_stale_row(db: Any, file_path: str, logger: Any = None) -> int:
    """Delete the poster_cache row for the EXACT pre-rename path.

    Exact match, never a prefix: 'X.jpg' must not also take 'X.jpg.bak'. Returns
    the row count; best-effort, so a cache problem can't fail a rename that
    already succeeded on Drive.
    """
    if not file_path:
        return 0
    try:
        return (
            db.poster.execute_query(
                "DELETE FROM poster_cache WHERE file = ?", (file_path,)
            )
            or 0
        )
    except Exception as exc:  # the rename already landed; never fail the run
        if logger:
            logger.warning(
                f"poster_self_heal: could not drop the stale cache row for "
                f"{file_path}: {exc}"
            )
        return 0
