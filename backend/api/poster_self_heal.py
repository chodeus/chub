"""Poster Self-Heal API.

Powers the review surface for the poster_self_heal module. The scheduled run
writes proposals into poster_heal_review; these endpoints list them, apply a
chosen rename (on the user's Drive via rclone + the local source copy), or
dismiss it.

    GET  /api/poster-self-heal/reviews          open proposals + pending picks
    GET  /api/poster-self-heal/count            open count (for the badge)
    GET  /api/poster-self-heal/coverage         save locations the heal scans
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


@router.get("/coverage", summary="Save locations this heal keeps up to date")
def coverage() -> JSONResponse:
    """What the next run will actually scan, derived from the live CL2K config.

    Built from the module's own ``local_dirs_for`` / ``drive_twins`` so the panel
    can't drift from the scan. Note the scope is WIDER than the maker's routing:
    a location with no claimed ``types`` saves nothing but is still healed, so
    filtering on ``types`` here would under-report. Config-only — no rclone.
    """
    from backend.modules.poster_self_heal import drive_twins, local_dirs_for
    from backend.util.cl2k.config import CL2K_IMAGE_TYPES

    cfg = load_config()
    cl2k = getattr(cfg, "cl2k_maker", None)
    if cl2k is None:
        return ok("ok", {"available": False, "folders": [], "drives": []})

    scanned = local_dirs_for(cl2k)
    drive_ids, twin_of = drive_twins(cl2k)
    # Which types actually rename INTO each Drive — the twin resolution, not the
    # claim, so a fallback target shows the types it really receives.
    heals: dict = {}
    for image_type in CL2K_IMAGE_TYPES:
        fid = twin_of(image_type)
        if fid:
            heals.setdefault(fid, []).append(image_type)

    # One row per PATH, first claimer wins — two rows sharing a path are a single
    # scanned location, and the panel keys on path.
    folders = []
    emitted: set = set()
    for f in getattr(cl2k, "local_folders", None) or []:
        path = (getattr(f, "path", "") or "").strip()
        if path not in scanned or path in emitted:
            continue
        emitted.add(path)
        folders.append(
            {
                "name": (getattr(f, "name", "") or "").strip(),
                "path": path,
                "types": list(getattr(f, "types", None) or []),
            }
        )
    seen: set = set()
    drives = []
    for d in getattr(cl2k, "gdrive_uploads", None) or []:
        fid = (getattr(d, "folder_id", "") or "").strip()
        if not fid or fid in seen:
            continue
        seen.add(fid)
        drives.append(
            {
                "name": (getattr(d, "name", "") or "").strip(),
                "folder_id": fid,
                "types": list(getattr(d, "types", None) or []),
                "heals_types": heals.get(fid, []),
            }
        )

    return ok(
        "ok",
        {
            "available": True,
            "style": (getattr(cl2k, "style", "") or "CL2K").strip(),
            "folders": folders,
            "drives": drives,
            "unrouted_types": [t for t in CL2K_IMAGE_TYPES if not twin_of(t)],
            "scanned_count": len(scanned),
            "drive_count": len(drive_ids),
        },
    )


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
    # "failed" is retryable on purpose — an auto-apply that raised is surfaced for
    # exactly this, and the cause is often transient (Drive listing, token).
    if row.get("status") not in ("proposed", "failed"):
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
