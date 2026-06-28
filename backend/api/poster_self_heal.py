"""Poster Self-Heal API.

Powers the review surface for the poster_self_heal module. The scheduled run
writes proposals into poster_heal_review; these endpoints list them, apply a
chosen rename (on the user's Drive via rclone + the local source copy), or
dismiss it.

    GET  /api/poster-self-heal/reviews          open proposals + pending picks
    GET  /api/poster-self-heal/count            open count (for the badge)
    POST /api/poster-self-heal/reviews/{id}/apply     rename on Drive + locally
    POST /api/poster-self-heal/reviews/{id}/dismiss   mark dismissed

Module settings are read/saved through the generic /api/config endpoints.
"""

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from backend.api.utils import error, get_database, get_module_logger, ok
from backend.util.config import load_config
from backend.util.database import ChubDB
from backend.util.database.poster_heal_review import poster_heal_review_for
from backend.util.poster_self_heal.apply import apply_proposal

router = APIRouter(
    prefix="/api/poster-self-heal",
    tags=["Poster Self-Heal"],
    responses={500: {"description": "Internal server error"}},
)


def get_heal_logger(request: Request) -> Any:
    """Log review/apply activity under the poster_self_heal module log."""
    return get_module_logger(request, "poster_self_heal")


@router.get("/reviews", summary="Open poster-heal proposals")
def list_reviews(
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    reviews = poster_heal_review_for(db)
    return ok("ok", {"reviews": reviews.list_open()})


@router.get("/count", summary="Open review count (badge)")
def review_count(
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    reviews = poster_heal_review_for(db)
    return ok("ok", {"count": reviews.open_count()})


@router.post("/reviews/{review_id}/dismiss", summary="Dismiss a proposal")
def dismiss_review(
    review_id: int,
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    reviews = poster_heal_review_for(db)
    if not reviews.get(review_id):
        return error("Review not found", "NOT_FOUND", status_code=404)
    reviews.set_status(review_id, "dismissed")
    return ok("Dismissed")


@router.post("/reviews/{review_id}/apply", summary="Apply a proposed rename")
def apply_review(
    review_id: int,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_heal_logger),
) -> JSONResponse:
    reviews = poster_heal_review_for(db)
    row = reviews.get(review_id)
    if not row:
        return error("Review not found", "NOT_FOUND", status_code=404)
    if row.get("status") not in ("proposed",):
        return error("Only an open proposal can be applied", "BAD_STATUS")

    current = row.get("current_filename") or ""
    proposed = row.get("proposed_filename") or ""
    if not proposed or proposed == current or row.get("drift_type") == "ambiguous":
        return error(
            "This item needs a manual pick — there is no single rename to apply",
            "NO_PROPOSAL",
        )

    try:
        note = apply_proposal(row, load_config().sync_gdrive, logger)
    except Exception as exc:
        return error(f"Google Drive rename failed: {exc}", "DRIVE_RENAME")

    reviews.set_status(review_id, "applied")
    return ok(f"Applied{note}", {"new_filename": proposed})
