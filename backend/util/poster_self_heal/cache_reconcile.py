# backend/util/poster_self_heal/cache_reconcile.py
"""Keep poster_cache honest after the healer renames a file.

A successful apply moves the file out from under the row that produced the
proposal. poster_cache's conflict key includes ``file`` (see its _UPSERT_SQL), so
the row cannot be updated in place — a re-index inserts a NEW row and leaves the
old one. The next run then re-reads the stale row, re-proposes the same rename,
and collides with the file its own previous run created; that collision is
permanent until the next full cache rebuild.

The SQL lives here rather than as a PosterCache method because poster_cache.py is
shared byte-identically with main and this is a develop-only extension concern. A
named ``delete_by_file`` on main would be tidier — worth doing when something on
main needs it too.
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
