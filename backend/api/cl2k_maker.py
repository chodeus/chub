"""CL2K Maker API.

Powers the CL2K Poster Maker page. Entry points (TMDB search, ID/URL paste,
unmatched-asset links) all resolve to a tmdb_id + kind; the art picker lists
every logo/backdrop; preview renders without saving; generate writes the poster
into every configured save location claiming its type (local folders and/or
Drive uploads; none = downloadable only) and records provenance.

    GET  /api/cl2k-maker/search?q=&type=         TMDB title search (entry point)
    GET  /api/cl2k-maker/resolve?external_id=&source=&type=   tvdb/imdb -> tmdb
    GET  /api/cl2k-maker/images?tmdb_id=&type=    all logos + backdrops (picker)
    POST /api/cl2k-maker/preview                  render to JPEG, no save
    POST /api/cl2k-maker/generate                 render + write + cache + log
    GET  /api/cl2k-maker/generated                provenance (recent)

Module settings are read/saved through the generic /api/config endpoints.
"""

import base64
import io
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, model_validator

from backend.api.utils import error, get_database, get_module_logger, ok
from backend.modules.cl2k_maker import (
    fanart_images,
    generate_background_art,
    generate_for_item,
    generate_logo_asset,
    generate_seasons,
    generate_square_art,
    psd_for_item,
    render_preview,
    retext_poster,
)
from backend.util.cl2k import geometry as geo, text_removal, tmdb_art
from backend.util.cl2k.image_fetch import (
    TMDB_IMAGE_CDN,
    _is_plex_art_path,
    download as download_image,
)
from backend.util.cl2k.logo_extract import (
    extract_logo_by_diff,
    extract_subject_logo,
    extract_title_logo,
    tighten_text_mask,
)
from backend.util.cl2k.renderer import (
    process_logo,
    render_framed_art,
    render_square_art,
)
from backend.util.config import load_config
from backend.util.database import ChubDB
from backend.util.database.cl2k_generated import cl2k_generated_for
from backend.util.tmdb import TMDBClient

router = APIRouter(
    prefix="/api/cl2k-maker",
    tags=["CL2K Maker"],
    responses={500: {"description": "Internal server error"}},
)


def get_cl2k_logger(request: Request) -> Any:
    """Log on-demand CL2K operations to the cl2k_maker module log (not the general
    log), so generation/upload activity and errors show up under the Logs page's
    CL2K Maker section instead of vanishing into the general log."""
    return get_module_logger(request, "cl2k_maker")


def _require_tmdb_or_backdrop(req: Any):
    """Require a tmdb_id unless the request supplies its own backdrop (path/b64)."""
    # Art auto-sources from TMDB (list_images) only when no backdrop is given.
    if req.tmdb_id is None and not (req.backdrop_path or req.backdrop_b64):
        raise ValueError("tmdb_id is required unless a backdrop is supplied")
    return req


class GenerateRequest(BaseModel):
    kind: str
    title: str
    # Optional so a TVDB/IMDB-only title can render from a supplied backdrop; the
    # validator below still requires tmdb_id whenever no backdrop is handed over.
    tmdb_id: Optional[int] = None
    year: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    season_number: Optional[int] = None
    backdrop_path: Optional[str] = None
    backdrop_b64: Optional[str] = None  # custom-uploaded backdrop (wins over path)
    logo_path: Optional[str] = None
    logo_b64: Optional[str] = (
        None  # custom uploaded logo (PNG, base64); wins over logo_path
    )
    # Logo size: relaxes the height clamp (the y=1100 zone-top guide) so tall/boxy
    # logos can render readable; 1.0 = the strict CL2K guide box. Width caps still apply.
    logo_scale: float = Field(1.0, ge=geo.LOGO_SCALE_MIN, le=geo.LOGO_SCALE_MAX)
    # Logo position: vertical shift in px from the locked baseline (positive = down).
    # Size is unaffected; the placement is clamped onto the canvas.
    logo_y_offset: int = Field(0, ge=geo.LOGO_Y_OFFSET_MIN, le=geo.LOGO_Y_OFFSET_MAX)
    # Per-render CL2K-whiten override; None falls back to the module config
    # (whiten_logo). True = two-tone white, False = the original colored logo.
    whiten: Optional[bool] = None
    # Flat white: paint the logo a pure-white silhouette (no two-tone keylines) —
    # for already-stylised/outline logos the two-tone whiten mangles. Wins over whiten.
    flat_white: bool = False
    # 3D logo: keep the lit face of extruded/bevelled art, drop the extrusion and
    # shadow, flat-white the rest. Wins over flat_white.
    logo_3d: bool = False
    # Invert logo: plate-style art -> clearlogo (white->transparent, black->white).
    invert: bool = False
    # B/W touch-up: regions brushed over the PROCESSED logo whose black/white is
    # inverted (for interior accents the two-tone keymap can't decide).
    logo_flip_b64: Optional[str] = None
    # Eraser: regions brushed over the PROCESSED logo made transparent (clean up
    # stray extracted/whitened bits a logo shouldn't have).
    logo_erase_b64: Optional[str] = None
    mask_b64: Optional[str] = None  # user-brushed mask (PNG, white=remove) for AI
    remove_text: bool = False  # run AI text removal (OpenAI can do it mask-less)
    focus_x: float = 0.5  # crop focal point (0..1); 0.5 = centre (cover mode)
    # Framing: "cover" scales up + crops to fill (focus_x + v_pos); "fit" scales the
    # backdrop down to the canvas width and black-pads the bottom, keeping the full
    # width so spread-out subjects all stay in frame. ``crop_*`` (0..1) optionally
    # isolates the subject region of a wide backdrop before the fit.
    fit_mode: str = "cover"
    crop_x: Optional[float] = None
    crop_y: Optional[float] = None
    crop_w: Optional[float] = None
    crop_h: Optional[float] = None
    # Vertical position. In cover ("Fill") it is -1..1 centred on 0: positive
    # slides the framing UP at the same size (real artwork flows down into the
    # gradient, no AI), negative slides it DOWN and only as far as real source
    # above the crop allows — no gradient up there to hide an extended band. In
    # fit/extend it keeps its 0..1 top-anchored meaning (0 = top, ~0.4 = headroom).
    v_pos: float = Field(0.0, ge=geo.V_POS_MIN, le=geo.V_POS_MAX)
    # Zoom (0.5-3.0): in fit/extend, >1 enlarges the subject above the full-width
    # fit (sides crop) so a wide backdrop isn't shrunk to a tiny strip; in cover
    # ("Fill"), <1 shrinks the art below the fill onto black. 1.0 = plain fit/cover.
    zoom: float = Field(1.0, ge=geo.ZOOM_MIN, le=geo.ZOOM_MAX)
    # Mirror: flip the artwork horizontally. Applied at the END of framing, so
    # the crop/focal point, the AI mask and the logo/label are unaffected.
    mirror: bool = False
    # Explicit bottom banner (e.g. "COMPLETE LIMITED SERIES"); overrides the auto
    # COLLECTION / season label when set.
    band_label: str = ""
    force: bool = False
    # Preview-only: render the logo-less base (backdrop + gradient + label + border)
    # so the frontend can overlay a live logo on top — the size/position sliders
    # then move the logo without a server render per drag. Always True on generate
    # (the logo is baked into the saved poster).
    place_logo: bool = True
    # Save mediums (independent). save_local writes to every local folder that
    # claims the image type; upload_gdrive=None/True uploads to every claiming
    # Drive (False skips). Nothing selected/routed = downloadable only.
    save_local: bool = True
    upload_gdrive: Optional[bool] = None

    @model_validator(mode="after")
    def _tmdb_id_or_backdrop(self):
        """Require a tmdb_id unless a backdrop is supplied (shared rule)."""
        return _require_tmdb_or_backdrop(self)


def _mask_bytes(b64: Optional[str]) -> Optional[bytes]:
    """Strict decode for brush masks: malformed base64 raises here (validate=True)
    so the endpoint can 400 with a readable message instead of handing garbage
    bytes to the renderer to crash on deep inside a render."""
    return _b64_to_bytes(b64, validate=True)


def _b64_to_bytes(
    b64: Optional[str], validate: bool = False, raster_only: bool = True
) -> Optional[bytes]:
    """Decode a base64 image, tolerating a ``data:...;base64,`` URL prefix.

    ``raster_only`` (the default) refuses markup-leading bytes: masks and
    backdrops must be raster, and SVG smuggled into them would otherwise reach
    ImageMagick's XML delegates. Only the logo field may carry SVG — the
    renderer routes that through sandboxed cairosvg."""
    if not b64:
        return None
    data = base64.b64decode(b64.split(",")[-1], validate=validate)
    if raster_only and data[:1024].lstrip(b"\xef\xbb\xbf \t\r\n\f\v").startswith(b"<"):
        raise ValueError("markup is not a valid raster image for this field")
    return data


def _ai_config_or_error(logger: Any, what: str):
    """``(full config, None)`` when an AI erase can run, else ``(None, 400)``.

    Every user-triggered AI route fails loudly rather than returning the image
    unchanged, which the frontend would report as a successful erase. Read live:
    a handler holding config from import time goes stale on a settings save.
    Routes needing more than "a provider is usable" (detect-text wants the
    sidecar specifically) add that check themselves — this owns only the part
    all three share.
    """
    cfg = load_config()
    reason = text_removal.unavailable_reason(cfg.cl2k_maker)
    if reason:
        logger.warning(f"CL2K {what}: AI unavailable — {reason}")
        return None, error(reason, "CL2K_AI_UNAVAILABLE")
    return cfg, None


def _failed(
    logger: Any,
    what: str,
    exc: BaseException,
    code: str,
    *,
    status_code: int = 400,
    trace: bool = False,
) -> JSONResponse:
    """Log a failure in full; answer with a stable message that omits ``exc``.

    THE owner of that split for this router. Exception text carries filesystem
    paths, internal hostnames and provider payloads, so it stays server-side
    (CodeQL py/stack-trace-exposure); the code and status the caller sees are
    unchanged, and the reason is one log line away under Logs → CL2K Maker.
    """
    if trace:
        logger.error(f"cl2k: {what} failed: {exc}", exc_info=True)
    else:
        logger.warning(f"cl2k: {what} failed: {exc}")
    return error(
        f"Could not {what} — see the CL2K Maker log for the reason.",
        code,
        status_code=status_code,
    )


# Worker-side twin of _failed's public half: job registries are read back by
# /seasons-status, so a raw str(exc) there reaches the browser just the same.
_JOB_FAILED = "failed — see the CL2K Maker log for the reason"


def _run_or_error(logger: Any, what: str, code: str, run):
    """``(value, None)`` from ``run``, else ``(None, 400)`` naming what failed.

    Bad input (truncated data-URL, disallowed art host, provider down) only
    surfaces deep inside the render/save chain — this is where it becomes a
    readable 4xx plus a CL2K log line rather than a bare 500 and silence.
    """
    try:
        return run(), None
    except HTTPException:
        raise  # a real HTTP status (auth, upstream) must not become a 400
    except Exception as exc:
        return None, _failed(logger, what, exc, code)


def _save_response(logger: Any, *, done: str, what: str, run) -> JSONResponse:
    """Run one of the save/generate flows and shape its result dict into JSON."""
    result, bad = _run_or_error(logger, what, "CL2K_GENERATE", run)
    if bad is not None:
        return bad
    if result.get("status") == "generated":
        pending = result.get("upload_pending")
        return ok(f"{done} — uploading to Drive" if pending else done, result)
    return error(
        result.get("reason", "generation failed"), "CL2K_GENERATE", data=result
    )


def _framing(req: Any) -> geo.Framing:
    """Flat request fields -> the renderer's framing bundle.

    ``crop_*`` is poster-models-only, and a PARTIAL crop is ignored (whole backdrop).
    """
    parts = (
        getattr(req, "crop_x", None),
        getattr(req, "crop_y", None),
        getattr(req, "crop_w", None),
        getattr(req, "crop_h", None),
    )
    return geo.Framing(
        focus_x=req.focus_x,
        fit_mode=req.fit_mode,
        v_pos=req.v_pos,
        zoom=req.zoom,
        mirror=req.mirror,
        crop=tuple(parts) if all(p is not None for p in parts) else None,
    )


class LogoFetchError(Exception):
    """A chosen logo URL could not be downloaded (disallowed host, dead URL,
    rotated Plex token, …). Endpoints turn this into a clean 4xx instead of an
    opaque 500."""


def _resolve_logo_bytes(
    logo_path: Optional[str], logo_b64: Optional[str]
) -> Optional[bytes]:
    """Bytes for a chosen logo (or None). An uploaded PNG (``logo_b64``) wins
    over a chosen TMDB/fanart/Plex ``logo_path``, which is fetched via the
    host-allowlisted image downloader (so a crafted path can't trigger an
    SSRF). Download failures raise :class:`LogoFetchError`."""
    if logo_b64:
        return _b64_to_bytes(logo_b64, raster_only=False)
    if logo_path:
        try:
            return download_image(logo_path)
        except Exception as exc:
            raise LogoFetchError(str(exc)) from exc
    return None


def _decorate(items: List[dict]) -> List[dict]:
    """Add absolute CDN URLs to TMDB image records for the picker thumbnails."""
    out = []
    for it in items:
        path = it.get("file_path")
        if path:
            out.append({**it, "url": TMDB_IMAGE_CDN + path})
    return out


@router.get("/search", summary="TMDB title search")
def search(
    q: str = Query(..., min_length=1),
    media_type: str = Query("movie", alias="type"),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    tmdb = TMDBClient(load_config().tmdb, db, logger)
    return ok("ok", {"results": tmdb_art.search_titles(tmdb, q, media_type)})


@router.get("/resolve", summary="Resolve an external id (tvdb/imdb) to a tmdb id")
def resolve(
    external_id: str = Query(...),
    source: str = Query(..., description="tvdb_id | imdb_id"),
    media_type: str = Query("movie", alias="type"),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    tmdb = TMDBClient(load_config().tmdb, db, logger)
    mt = "movie" if media_type == "movie" else "tv"
    return ok("ok", {"tmdb_id": tmdb.find_tmdb_id(external_id, source, mt)})


def _resolve_tmdb_id(
    tmdb: TMDBClient,
    tmdb_id: Optional[int],
    tvdb_id: Optional[int],
    imdb_id: Optional[str],
    media_type: str,
) -> Optional[int]:
    """The title's TMDB id, looked up from a tvdb/imdb id when not supplied."""
    # TMDB art is keyed by tmdb_id, but a title may only carry a tvdb/imdb one
    # (Sonarr shows especially) — resolve rather than demand.
    if tmdb_id:
        return tmdb_id
    if tvdb_id:
        return tmdb.find_tmdb_id(str(tvdb_id), "tvdb_id", media_type)
    if imdb_id:
        return tmdb.find_tmdb_id(str(imdb_id), "imdb_id", media_type)
    return None


@router.get("/images", summary="All logos + backdrops + posters for the art picker")
def images(
    tmdb_id: Optional[int] = Query(None),
    tvdb_id: Optional[int] = Query(None),
    imdb_id: Optional[str] = Query(None),
    media_type: str = Query("movie", alias="type"),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    tmdb = TMDBClient(load_config().tmdb, db, logger)
    mt = "movie" if media_type == "movie" else "tv"
    resolved = _resolve_tmdb_id(tmdb, tmdb_id, tvdb_id, imdb_id, mt)
    if not resolved:
        return ok("ok", {"logos": [], "backdrops": [], "posters": []})
    imgs = tmdb_art.list_images(tmdb, resolved, media_type) or {
        "logos": [],
        "backdrops": [],
    }
    # Textless (null-language) posters first — pure art that needs no AI text
    # pass at all. Stable sort keeps TMDB's vote order within each group.
    posters = sorted(
        imgs.get("posters", []), key=lambda p: p.get("iso_639_1") is not None
    )
    return ok(
        "ok",
        {
            "logos": _decorate(imgs.get("logos", [])),
            "backdrops": _decorate(imgs.get("backdrops", [])),
            # Official posters too: often the only quality art for small titles
            # (documentaries etc.) — pick one, brush the title text, AI-erase.
            "posters": _decorate(posters),
        },
    )


@router.get(
    "/season-images", summary="TMDB season posters (portrait) for the art picker"
)
def season_images(
    tmdb_id: Optional[int] = Query(None),
    tvdb_id: Optional[int] = Query(None),
    imdb_id: Optional[str] = Query(None),
    season_number: int = Query(...),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    tmdb = TMDBClient(load_config().tmdb, db, logger)
    resolved = _resolve_tmdb_id(tmdb, tmdb_id, tvdb_id, imdb_id, "tv")
    if not resolved:
        return ok("ok", {"posters": []})
    imgs = tmdb_art.list_season_images(tmdb, resolved, season_number) or {"posters": []}
    return ok("ok", {"posters": _decorate(imgs.get("posters", []))})


@router.get(
    "/upload-status", summary="Configured CL2K save locations + Drive OAuth state"
)
def upload_status(
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """Feeds the maker page's save-target defaults: whether any local folder /
    Drive upload actually routes something (an entry with no claimed types is
    inert), and whether Drive uploads have a usable OAuth token."""
    from backend.util.cl2k.gdrive_upload import has_upload_token

    cfg = load_config()
    return ok(
        "ok",
        {
            "local_configured": any(
                (f.path or "").strip() and f.types for f in cfg.cl2k_maker.local_folders
            ),
            "gdrive_configured": any(
                (d.folder_id or "").strip() and d.types
                for d in cfg.cl2k_maker.gdrive_uploads
            ),
            "token_ok": has_upload_token(cfg.sync_gdrive),
        },
    )


class TestDriveRequest(BaseModel):
    gdrive_folder_id: str = ""


@router.post("/test-drive", summary="Verify CHUB can upload to a given Drive folder")
def test_drive(
    req: TestDriveRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """Upload a tiny marker file to ``gdrive_folder_id`` then delete it, proving
    write access with the Sync GDrive OAuth token. Powers the per-destination
    Test button in the CL2K settings."""
    from backend.util.cl2k.gdrive_upload import has_upload_token, test_drive_access

    folder_id = (req.gdrive_folder_id or "").strip()
    if not folder_id:
        return error("A Google Drive folder ID is required", "GDRIVE_FOLDER_REQUIRED")
    cfg = load_config()
    # Missing token is a config precondition (400), distinct from a genuine
    # rclone/Drive failure below (502).
    if not has_upload_token(cfg.sync_gdrive):
        return error(
            "No Google Drive OAuth token configured — set one under Sync GDrive "
            "(a service account cannot own files in a personal Drive).",
            "GDRIVE_NO_TOKEN",
        )
    try:
        detail = test_drive_access(folder_id, cfg.sync_gdrive, logger)
    except ValueError as exc:
        return _failed(logger, "accept that folder ID", exc, "GDRIVE_FOLDER_INVALID")
    except Exception as exc:
        return _failed(
            logger, "test that Drive folder", exc, "GDRIVE_TEST_FAILED", status_code=502
        )
    return ok(detail, {"folder_id": folder_id})


@router.post(
    "/gdrive/type-subfolders",
    summary="Create logos/backgrounds/squareart under a parent Drive folder",
)
def gdrive_type_subfolders(
    req: TestDriveRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """Split one parent Drive folder into the community artwork layout.

    Creates (or reuses) the three type subfolders and returns their real ids, so
    the caller can store one routed destination per type. Purely additive on
    Drive — nothing is moved, renamed or deleted, and a drive that should stay
    flat simply never calls this.
    """
    from backend.util.cl2k.gdrive_upload import ensure_type_subfolders, has_upload_token

    folder_id = (req.gdrive_folder_id or "").strip()
    if not folder_id:
        return error("A Google Drive folder ID is required", "GDRIVE_FOLDER_REQUIRED")
    cfg = load_config()
    if not has_upload_token(cfg.sync_gdrive):
        return error(
            "No Google Drive OAuth token configured — set one under Sync GDrive "
            "(a service account cannot own files in a personal Drive).",
            "GDRIVE_NO_TOKEN",
        )
    try:
        subfolders = ensure_type_subfolders(folder_id, cfg.sync_gdrive, logger)
    except ValueError as exc:
        return _failed(logger, "accept that folder ID", exc, "GDRIVE_FOLDER_INVALID")
    except Exception as exc:
        return _failed(
            logger,
            "create the type subfolders",
            exc,
            "GDRIVE_SUBFOLDERS_FAILED",
            status_code=502,
        )
    created = [s["name"] for s in subfolders if s["created"]]
    detail = (
        f"Created {', '.join(created)}" if created else "All three subfolders already existed"
    )
    return ok(detail, {"folder_id": folder_id, "subfolders": subfolders})


@router.get(
    "/external-ids", summary="TMDB external ids (tvdb_id + imdb_id) for a title"
)
def external_ids(
    tmdb_id: Optional[int] = Query(None),
    tvdb_id: Optional[int] = Query(None),
    imdb_id: Optional[str] = Query(None),
    media_type: str = Query("movie", alias="type"),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    tmdb = TMDBClient(load_config().tmdb, db, logger)
    mt = "movie" if media_type == "movie" else "tv"
    resolved = _resolve_tmdb_id(tmdb, tmdb_id, tvdb_id, imdb_id, mt)
    if not resolved:
        return ok("ok", {})
    return ok("ok", tmdb_art.external_ids(tmdb, resolved, media_type))


@router.get("/details", summary="Canonical TMDB title + year for an id")
def details(
    tmdb_id: Optional[int] = Query(None),
    tvdb_id: Optional[int] = Query(None),
    imdb_id: Optional[str] = Query(None),
    media_type: str = Query("movie", alias="type"),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """Title + release year for an id, so an id-only entry (paste / Edit IDs / deep
    link) shows the real name in the header instead of bare id tags. Resolves a
    usable TMDB id in order: ``tmdb_id`` → TVDB → IMDB (matching the save-time
    backfill), then reads the canonical title/year."""
    tmdb = TMDBClient(load_config().tmdb, db, logger)
    mt = "movie" if media_type == "movie" else "tv"
    resolved = _resolve_tmdb_id(tmdb, tmdb_id, tvdb_id, imdb_id, mt)
    d = (tmdb.get_details(resolved, mt) if resolved else None) or {}
    return ok("ok", {"title": d.get("title"), "year": d.get("year")})


class LogoProcessRequest(BaseModel):
    logo_path: Optional[str] = None
    logo_b64: Optional[str] = None  # custom uploaded logo (PNG, base64)
    # Per-render whiten override so the live overlay matches the Builder toggle;
    # None falls back to the module config (whiten_logo).
    whiten: Optional[bool] = None
    flat_white: bool = (
        False  # pure-white silhouette (no two-tone keylines); wins over whiten
    )
    logo_3d: bool = False  # extruded art -> flat-white lit face; wins over flat_white
    invert: bool = False  # plate logo -> clearlogo
    flip_b64: Optional[str] = None  # B/W touch-up regions (mask PNG, white=flip)
    erase_b64: Optional[str] = None  # erase regions (mask PNG, white=erase)
    # Picks the bottom baseline the auto box is fitted against (collection=1319).
    kind: str = "movie"


@router.post("/logo-processed", summary="Trimmed + whitened logo for the live overlay")
def logo_processed(
    req: LogoProcessRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """Return the trimmed + whitened logo (PNG, base64), its natural size and the
    placement box the render would give it. The frontend draws these bytes at
    ``box_w``/``box_h`` so the size/position sliders preview live — matching
    :func:`render_cl2k`'s placement without a render per drag.

    ``box_w``/``box_h`` come from :func:`geometry.auto_logo_size`, the SAME call
    :func:`renderer._place_logo` makes (``logo_max_width`` is never passed, so the
    render always takes its auto branch). Deriving the box here rather than
    re-deriving it in JS is what keeps the overlay and the generated poster the
    same size — a flat guide-box width over-sizes wide logos by ~15%."""
    try:
        raw = _resolve_logo_bytes(req.logo_path, req.logo_b64)
    except LogoFetchError as exc:
        return _failed(logger, "fetch that logo from its source", exc, "LOGO_FETCH")
    if not raw:
        return error("No logo provided", "NO_LOGO")
    cfg = load_config().cl2k_maker
    try:
        png, width, height = process_logo(
            raw,
            whiten=cfg.whiten_logo if req.whiten is None else req.whiten,
            flat_white=req.flat_white,
            logo_3d=req.logo_3d,
            flip_mask_bytes=_b64_to_bytes(req.flip_b64),
            erase_mask_bytes=_b64_to_bytes(req.erase_b64),
            invert=req.invert,
        )
    except Exception as exc:
        logger.warning(f"cl2k: logo processing failed: {exc}")
        return error("Could not process that logo", "LOGO_PROCESS")
    box_w, box_h = geo.auto_logo_size(width, height, geo.logo_baseline(req.kind))
    return ok(
        "ok",
        {
            "b64": base64.b64encode(png).decode(),
            "width": width,
            "height": height,
            "max_width": geo.LOGO_WIDTH_RECOMMENDED,
            "box_w": box_w,
            "box_h": box_h,
        },
    )


@router.post("/preview", summary="Render a CL2K poster without saving")
def preview(
    req: GenerateRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
):
    """Render a CL2K poster to JPEG and return the bytes, saving nothing."""
    try:
        mask_bytes = _mask_bytes(req.mask_b64)
    except Exception:
        return error("invalid mask data", "BAD_MASK")
    cfg = load_config()  # outside the guard: a config fault is not a render fault
    blob, bad = _run_or_error(
        logger,
        "render that preview",
        "PREVIEW_RENDER",
        lambda: render_preview(
            db,
            cfg,
            logger,
            kind=req.kind,
            title=req.title,
            tmdb_id=req.tmdb_id,
            season_number=req.season_number,
            backdrop_path=req.backdrop_path,
            backdrop_bytes=_b64_to_bytes(req.backdrop_b64),
            logo_path=req.logo_path,
            custom_logo_bytes=_b64_to_bytes(req.logo_b64, raster_only=False),
            tvdb_id=req.tvdb_id,
            imdb_id=req.imdb_id,
            mask_bytes=mask_bytes,
            apply_ai=req.remove_text,
            framing=_framing(req),
            band_label=req.band_label,
            logo_scale=req.logo_scale,
            logo_y_offset=req.logo_y_offset,
            logo_flip_bytes=_b64_to_bytes(req.logo_flip_b64),
            logo_erase_bytes=_b64_to_bytes(req.logo_erase_b64),
            whiten=req.whiten,
            flat_white=req.flat_white,
            logo_3d=req.logo_3d,
            invert=req.invert,
            place_logo=req.place_logo,
        ),
    )
    if bad is not None:
        return bad
    if blob is None:
        return error("No textless backdrop available", "NO_BACKDROP")
    return Response(
        content=blob, media_type="image/jpeg", headers={"Cache-Control": "no-store"}
    )


@router.post("/generate", summary="Generate + save a CL2K poster")
def generate(
    req: GenerateRequest,
    background_tasks: BackgroundTasks,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """Render a CL2K poster and file it to every claiming save location."""
    if (bad := _require_any_id(req)) is not None:
        return bad
    try:
        mask_bytes = _mask_bytes(req.mask_b64)
    except Exception:
        return error("invalid mask data", "BAD_MASK")
    cfg = load_config()  # outside the guard: a config fault is not a save fault
    return _save_response(
        logger,
        done="Poster generated",
        what="save that poster",
        run=lambda: generate_for_item(
            db=db,
            full_config=cfg,
            logger=logger,
            kind=req.kind,
            title=req.title,
            tmdb_id=req.tmdb_id,
            year=req.year,
            tvdb_id=req.tvdb_id,
            imdb_id=req.imdb_id,
            season_number=req.season_number,
            backdrop_path=req.backdrop_path,
            backdrop_bytes=_b64_to_bytes(req.backdrop_b64),
            logo_path=req.logo_path,
            custom_logo_bytes=_b64_to_bytes(req.logo_b64),
            mask_bytes=mask_bytes,
            apply_ai=req.remove_text,
            framing=_framing(req),
            band_label=req.band_label,
            logo_scale=req.logo_scale,
            logo_y_offset=req.logo_y_offset,
            logo_flip_bytes=_b64_to_bytes(req.logo_flip_b64),
            logo_erase_bytes=_b64_to_bytes(req.logo_erase_b64),
            whiten=req.whiten,
            flat_white=req.flat_white,
            logo_3d=req.logo_3d,
            invert=req.invert,
            force=req.force,
            save_local=req.save_local,
            upload_gdrive=req.upload_gdrive,
            # Every interactive save defers alike (posters and the asset makers);
            # the batch run() stays inline. A deferred failure notifies — see
            # _run_uploads.
            defer_upload=background_tasks.add_task,
        ),
    )


# ─── Square art + logo asset makers ──────────────────────────────────────────
# Two additional asset types the maker files separately from posters: square art
# (1:1 cropped backdrop, `- squareart.jpg`) and a clear-logo asset (`- logo.png`).
# Both flow into poster_cache so asset_renamerr applies them to Plex
# (uploadSquareArt / uploadLogo).


def _require_any_id(req) -> Optional[JSONResponse]:
    """Reject art with no id at all — the filename would carry nothing to match
    on, so asset_renamerr could never bind it to a library item."""
    if req.tmdb_id or req.tvdb_id or (req.imdb_id or "").strip():
        return None
    return error(
        "Needs at least one of TMDB, TVDB or IMDB id — without one the filename "
        "has nothing for CHUB or Kometa to match against.",
        "NO_MEDIA_ID",
    )


class SquareArtRequest(BaseModel):
    kind: str
    title: str
    # Supplied art, so an id is only a filename tag. _require_any_id demands one.
    tmdb_id: Optional[int] = None
    year: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    # File the art for ONE season of a show (` - Season NN` name; plexapi seasons
    # accept square art) instead of the show itself. None = show/movie-level.
    season_number: Optional[int] = None
    backdrop_path: Optional[str] = None
    backdrop_b64: Optional[str] = None  # custom-uploaded source art (base64)
    focus_x: float = 0.5
    v_pos: float = Field(0.0, ge=geo.V_POS_MIN, le=geo.V_POS_MAX)
    fit_mode: str = "cover"  # cover (focal crop) | fit (contain on black)
    zoom: float = Field(1.0, ge=geo.ZOOM_MIN, le=geo.ZOOM_MAX)
    mirror: bool = False  # flip the artwork horizontally
    save_local: bool = True
    upload_gdrive: Optional[bool] = None


class LogoAssetRequest(BaseModel):
    kind: str
    title: str
    # Supplied art, so an id is only a filename tag. _require_any_id demands one.
    tmdb_id: Optional[int] = None
    year: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    logo_path: Optional[str] = None
    logo_b64: Optional[str] = None
    whiten: bool = False  # True = CL2K-whitened; False = original (colored) clear logo
    flat_white: bool = False  # pure-white silhouette (no keylines); wins over whiten
    logo_3d: bool = False  # extruded art -> flat-white lit face; wins over flat_white
    invert: bool = False  # plate logo -> clearlogo (white->transparent, black->white)
    flip_b64: Optional[str] = None  # B/W touch-up regions (mask PNG, white=flip)
    erase_b64: Optional[str] = None  # erase regions (mask PNG, white=erase)
    save_local: bool = True
    upload_gdrive: Optional[bool] = None


class ExtractLogoRequest(BaseModel):
    # Source poster: an uploaded image (base64/data-url) wins over a TMDB/fanart/
    # Plex path that we fetch. Extraction keys the title out of the artwork.
    image_b64: Optional[str] = None
    image_path: Optional[str] = None
    # Brushed region (PNG, white = look here). Confines the key so areas outside
    # the title can't leak in; without it the whole image is keyed.
    mask_b64: Optional[str] = None
    # "white" keys a white/near-white title by brightness; "subject" keys a
    # coloured title by its colour distance from the local background; "erase"
    # inpaints the title away and keys whatever changed — the most faithful key,
    # it catches glows no colour key can, and the only one needing a provider.
    mode: str = "white"
    # Smoothstep band, interpreted per mode (white: min-channel 0-255; subject:
    # ΔE76 0-~150; erase: RGB distance 0-441). None lets each mode use its own
    # default — white/subject then fit the band to the poster (Otsu).
    lo: Optional[float] = Field(None, ge=0.0, le=441.0)
    hi: Optional[float] = Field(None, ge=0.0, le=441.0)


def _source_art_bytes(req: Any) -> Optional[bytes]:
    """Source art for an asset request: an upload wins over a fetched path."""
    if req.backdrop_b64:
        return _b64_to_bytes(req.backdrop_b64)
    if req.backdrop_path:
        return download_image(req.backdrop_path)
    return None


def _art_preview(logger: Any, req: Any, render):
    """Fetch the source art and render an asset preview, or a clean 4xx."""
    raw, bad = _run_or_error(
        logger, "fetch that source art", "IMAGE_FETCH", lambda: _source_art_bytes(req)
    )
    if bad is not None:
        return bad
    if not raw:
        return error("No source art selected", "NO_BACKDROP")
    blob, bad = _run_or_error(
        logger, "render that preview", "PREVIEW_RENDER", lambda: render(raw)
    )
    if bad is not None:
        return bad
    return Response(
        content=blob, media_type="image/jpeg", headers={"Cache-Control": "no-store"}
    )


@router.post("/square-preview", summary="Render square art (1:1) without saving")
def square_preview(
    req: SquareArtRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
):
    """Render 1:1 square art and return the JPEG bytes, saving nothing."""
    return _art_preview(
        logger,
        req,
        lambda raw: render_square_art(
            backdrop_bytes=raw,
            framing=_framing(req),
        ),
    )


@router.post("/square-generate", summary="Generate + save square art")
def square_generate(
    req: SquareArtRequest,
    background_tasks: BackgroundTasks,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """Render square art and file it as the item's ``- squareart.jpg`` asset."""
    if (bad := _require_any_id(req)) is not None:
        return bad
    cfg = load_config()  # outside the guard: a config fault is not a save fault
    return _save_response(
        logger,
        done="Square art generated",
        what="save that square art",
        run=lambda: generate_square_art(
            db=db,
            full_config=cfg,
            logger=logger,
            kind=req.kind,
            title=req.title,
            tmdb_id=req.tmdb_id,
            year=req.year,
            tvdb_id=req.tvdb_id,
            imdb_id=req.imdb_id,
            backdrop_path=req.backdrop_path,
            backdrop_bytes=_b64_to_bytes(req.backdrop_b64),
            framing=_framing(req),
            season_number=req.season_number,
            save_local=req.save_local,
            upload_gdrive=req.upload_gdrive,
            defer_upload=background_tasks.add_task,
        ),
    )


class BackgroundArtRequest(BaseModel):
    kind: str
    title: str
    # Supplied art, so an id is only a filename tag. _require_any_id demands one.
    tmdb_id: Optional[int] = None
    year: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    # File the art for ONE season of a show (` - Season NN` name; Plex seasons take
    # background art, Kometa reads Season##_background). None = show/movie-level.
    season_number: Optional[int] = None
    backdrop_path: Optional[str] = None
    backdrop_b64: Optional[str] = None  # custom-uploaded source art (base64)
    focus_x: float = 0.5
    v_pos: float = Field(0.0, ge=geo.V_POS_MIN, le=geo.V_POS_MAX)
    fit_mode: str = "cover"  # cover (focal crop) | fit (contain on black)
    zoom: float = Field(1.0, ge=geo.ZOOM_MIN, le=geo.ZOOM_MAX)
    mirror: bool = False  # flip the artwork horizontally
    resolution: str = "1080p"  # 1080p (1920x1080) | 4k (3840x2160), per Plex dims
    save_local: bool = True
    upload_gdrive: Optional[bool] = None


@router.post(
    "/background-preview", summary="Render background art (16:9) without saving"
)
def background_preview(
    req: BackgroundArtRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
):
    """Render 16:9 background art and return the JPEG bytes, saving nothing."""
    # Preview at 1080p regardless of the save resolution — same 16:9 frame,
    # quarter the bytes of a 4K render.
    return _art_preview(
        logger,
        req,
        lambda raw: render_framed_art(
            backdrop_bytes=raw,
            width=1920,
            height=1080,
            framing=_framing(req),
        ),
    )


@router.post("/background-generate", summary="Generate + save background art")
def background_generate(
    req: BackgroundArtRequest,
    background_tasks: BackgroundTasks,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """Render background art and file it as the ``- background.jpg`` asset."""
    if (bad := _require_any_id(req)) is not None:
        return bad
    cfg = load_config()  # outside the guard: a config fault is not a save fault
    return _save_response(
        logger,
        done="Background art generated",
        what="save that background art",
        run=lambda: generate_background_art(
            db=db,
            full_config=cfg,
            logger=logger,
            kind=req.kind,
            title=req.title,
            tmdb_id=req.tmdb_id,
            year=req.year,
            tvdb_id=req.tvdb_id,
            imdb_id=req.imdb_id,
            backdrop_path=req.backdrop_path,
            backdrop_bytes=_b64_to_bytes(req.backdrop_b64),
            framing=_framing(req),
            resolution=req.resolution,
            season_number=req.season_number,
            save_local=req.save_local,
            upload_gdrive=req.upload_gdrive,
            defer_upload=background_tasks.add_task,
        ),
    )


@router.post(
    "/logo-asset-preview", summary="Processed logo asset (transparent PNG), no save"
)
def logo_asset_preview(
    req: LogoAssetRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
):
    """Return the processed clear logo as a transparent PNG, saving nothing."""
    try:
        raw = _resolve_logo_bytes(req.logo_path, req.logo_b64)
    except LogoFetchError as exc:
        return _failed(logger, "fetch that logo from its source", exc, "LOGO_FETCH")
    if not raw:
        return error("No logo selected", "NO_LOGO")
    png, bad = _run_or_error(
        logger,
        "process that logo",
        "LOGO_PROCESS",
        lambda: process_logo(
            raw,
            whiten=req.whiten,
            flat_white=req.flat_white,
            logo_3d=req.logo_3d,
            flip_mask_bytes=_b64_to_bytes(req.flip_b64),
            erase_mask_bytes=_b64_to_bytes(req.erase_b64),
            invert=req.invert,
        )[0],
    )
    if bad is not None:
        return bad
    return Response(
        content=png, media_type="image/png", headers={"Cache-Control": "no-store"}
    )


@router.post("/logo-asset-generate", summary="File a clear logo as a - logo asset")
def logo_asset_generate(
    req: LogoAssetRequest,
    background_tasks: BackgroundTasks,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """File a processed clear logo as the item's ``- logo.png`` asset."""
    if (bad := _require_any_id(req)) is not None:
        return bad
    cfg = load_config()  # outside the guard: a config fault is not a save fault
    return _save_response(
        logger,
        done="Logo asset filed",
        what="file that logo asset",
        run=lambda: generate_logo_asset(
            db=db,
            full_config=cfg,
            logger=logger,
            kind=req.kind,
            title=req.title,
            tmdb_id=req.tmdb_id,
            year=req.year,
            tvdb_id=req.tvdb_id,
            imdb_id=req.imdb_id,
            logo_path=req.logo_path,
            logo_bytes=_b64_to_bytes(req.logo_b64),
            whiten=req.whiten,
            flat_white=req.flat_white,
            logo_3d=req.logo_3d,
            invert=req.invert,
            flip_mask_bytes=_b64_to_bytes(req.flip_b64),
            erase_mask_bytes=_b64_to_bytes(req.erase_b64),
            save_local=req.save_local,
            upload_gdrive=req.upload_gdrive,
            defer_upload=background_tasks.add_task,
        ),
    )


@router.post(
    "/extract-logo",
    summary="Key a title out of poster art into a transparent logo PNG",
)
def extract_logo(
    req: ExtractLogoRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
):
    """Key a title out of poster art and return it as a transparent logo PNG."""
    if req.image_b64:
        try:
            raw = _b64_to_bytes(req.image_b64)
        except Exception:
            return error("invalid image data", "BAD_IMAGE")
    elif req.image_path:
        try:
            raw = download_image(req.image_path)
        except Exception as exc:  # disallowed host / fetch failure
            return _failed(logger, "fetch that poster", exc, "IMAGE_FETCH")
    else:
        raw = None
    if not raw:
        return error("No poster image provided", "NO_IMAGE")
    try:
        mask = _mask_bytes(req.mask_b64)
    except Exception:
        return error("invalid mask data", "BAD_MASK")
    band = {k: v for k, v in (("lo", req.lo), ("hi", req.hi)) if v is not None}
    if req.mode == "erase":
        if not mask:
            return error(
                "Brush over the title first — the eraser only fills what is masked",
                "NO_MASK",
            )
        cfg, unavailable = _ai_config_or_error(logger, "extract-logo erase")
        if unavailable:
            return unavailable
        try:
            cleaned = text_removal.remove_text(
                raw, config=cfg.cl2k_maker, mask_bytes=mask, logger=logger
            )
        except Exception as exc:
            return _failed(logger, "run the AI erase", exc, "CL2K_AI", trace=True)
        if cleaned == raw:
            # By value, not identity: remove_text hands the original object back
            # when the provider bails, but a provider can also echo an equal
            # copy. Either way diffing keys nothing, so fail here instead of
            # returning a blank logo that looks like a bad brush.
            return error("The AI erase returned the poster unchanged", "CL2K_AI")
        png = extract_logo_by_diff(raw, cleaned, mask, **band)
    else:
        extract = extract_subject_logo if req.mode == "subject" else extract_title_logo
        png = extract(raw, mask, **band)
    return Response(
        content=png, media_type="image/png", headers={"Cache-Control": "no-store"}
    )


@router.get("/generated", summary="Recently generated CL2K posters")
def generated(
    limit: int = Query(200, ge=1, le=1000),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    return ok("ok", {"items": cl2k_generated_for(db).list_recent(limit)})


@router.post("/psd-export", summary="Export the CL2K poster as a layered .psd")
def psd_export(
    req: GenerateRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
):
    """Export the poster the preview shows as a layered .psd (for Photopea)."""
    cfg = load_config()  # outside the guard: a config fault is not an export fault
    blob, bad = _run_or_error(
        logger,
        "export that .psd",
        "PSD_EXPORT",
        lambda: psd_for_item(
            db=db,
            full_config=cfg,
            logger=logger,
            kind=req.kind,
            title=req.title,
            tmdb_id=req.tmdb_id,
            backdrop_path=req.backdrop_path,
            backdrop_bytes=_b64_to_bytes(req.backdrop_b64),
            logo_path=req.logo_path,
            custom_logo_bytes=_b64_to_bytes(req.logo_b64),
            season_number=req.season_number,
            band_label=req.band_label,
            logo_scale=req.logo_scale,
            logo_y_offset=req.logo_y_offset,
            logo_flip_bytes=_b64_to_bytes(req.logo_flip_b64),
            logo_erase_bytes=_b64_to_bytes(req.logo_erase_b64),
            framing=_framing(req),
            whiten=req.whiten,
            flat_white=req.flat_white,
            logo_3d=req.logo_3d,
            invert=req.invert,
        ),
    )
    if bad is not None:
        return bad
    if blob is None:
        return error("No textless backdrop available", "NO_BACKDROP")
    return Response(
        content=blob,
        media_type="image/vnd.adobe.photoshop",
        headers={"Content-Disposition": 'attachment; filename="cl2k.psd"'},
    )


class SeasonsRequest(BaseModel):
    # Optional, gated by the validator below (tmdb_id or a supplied backdrop) —
    # a season batch carrying the show's backdrop over needs no tmdb_id.
    tmdb_id: Optional[int] = None
    title: str
    seasons: List[int]
    year: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    # Art carried over from the show poster the user built in the preview, so every
    # season reuses the SAME backdrop + logo instead of the backend re-resolving a
    # fresh auto-pick (which produced "a random poster"). Mirrors GenerateRequest:
    # an uploaded backdrop/logo (``*_b64``) wins over a chosen TMDB/Plex path.
    backdrop_path: Optional[str] = None
    backdrop_b64: Optional[str] = None
    logo_path: Optional[str] = None
    logo_b64: Optional[str] = None
    # Framing carried over from the show poster so every season matches it.
    fit_mode: str = "cover"
    focus_x: float = 0.5
    crop_x: Optional[float] = None
    crop_y: Optional[float] = None
    crop_w: Optional[float] = None
    crop_h: Optional[float] = None
    v_pos: float = Field(0.0, ge=geo.V_POS_MIN, le=geo.V_POS_MAX)
    zoom: float = Field(1.0, ge=geo.ZOOM_MIN, le=geo.ZOOM_MAX)
    mirror: bool = False  # flip the artwork horizontally
    logo_scale: float = Field(1.0, ge=geo.LOGO_SCALE_MIN, le=geo.LOGO_SCALE_MAX)
    logo_y_offset: int = Field(0, ge=geo.LOGO_Y_OFFSET_MIN, le=geo.LOGO_Y_OFFSET_MAX)
    whiten: Optional[bool] = None  # None = module config (whiten_logo)
    flat_white: bool = False  # pure-white silhouette (no keylines); wins over whiten
    logo_3d: bool = False  # extruded art -> flat-white lit face; wins over flat_white
    invert: bool = False  # plate logo -> clearlogo
    # The logo edits the preview was built with — every season reuses the SAME
    # logo, so omitting these silently bulk-generated with an unedited one.
    logo_flip_b64: Optional[str] = None  # B/W touch-up regions (mask PNG)
    logo_erase_b64: Optional[str] = None  # erase regions (mask PNG, white=erase)
    force: bool = False
    # Save destinations (mirror GenerateRequest): honour the same targets the
    # single-poster Generate used. upload_gdrive=None falls back to module config.
    save_local: bool = True
    upload_gdrive: Optional[bool] = None

    @model_validator(mode="after")
    def _tmdb_id_or_backdrop(self):
        """Require a tmdb_id unless a backdrop is supplied (shared rule)."""
        return _require_tmdb_or_backdrop(self)


# ─── Background season-batch jobs ────────────────────────────────────────────
# Generating a full show's worth of seasons (download + ImageMagick text-removal
# + render + Drive upload, per season) easily outlasts a reverse-proxy timeout, so
# the request returned a false failure even though every poster was written. The
# batch now runs in a daemon thread and the frontend polls /seasons-status.
#
# The CL2K maker runs in a single-process uvicorn (see backend/api/server.py), so
# this in-process registry is shared by the request handlers and the worker
# thread — no cross-process store needed. Jobs are ephemeral (lost on restart);
# the posters themselves persist to disk/Drive + cl2k_generated, so a lost status
# only loses the progress readout, never the work.
_season_jobs: Dict[int, Dict[str, Any]] = {}
_season_jobs_lock = threading.Lock()
_season_job_seq = 0


# Keep a small tail of finished jobs so a poll that arrives just after completion
# still sees the result, without the registry growing unbounded over long uptime.
_SEASON_JOB_KEEP = 50


def _new_season_job(total: int, title: str) -> int:
    global _season_job_seq
    with _season_jobs_lock:
        # Evict the oldest finished jobs once we're over the cap (the just-created
        # and any still-running jobs are newest, so they're never pruned).
        if len(_season_jobs) >= _SEASON_JOB_KEEP:
            finished = [k for k, v in _season_jobs.items() if v["status"] != "running"]
            for k in sorted(finished)[: len(_season_jobs) - _SEASON_JOB_KEEP + 1]:
                _season_jobs.pop(k, None)
        _season_job_seq += 1
        jid = _season_job_seq
        _season_jobs[jid] = {
            "id": jid,
            "status": "running",
            "title": title,
            "total": total,
            "done": 0,
            "results": [],
            "error": None,
        }
    return jid


def _season_job_snapshot(jid: int) -> Optional[Dict[str, Any]]:
    """A self-consistent copy — ``results`` is copied too, never aliased.

    A shallow copy left it pointing at the live list the worker appends to, so a
    poll could serialise more entries than the ``done`` it read a line earlier."""
    with _season_jobs_lock:
        job = _season_jobs.get(jid)
        return {**job, "results": list(job["results"])} if job else None


# A show has nowhere near this many seasons; a huge list is a malformed/abusive
# request, not a real batch. Rejected visibly, never silently truncated.
_MAX_SEASONS = 60


def _clean_seasons(raw) -> List[int]:
    """Deduped, ordered, non-negative season numbers from a raw request list."""
    out = set()
    for n in raw or []:
        try:
            v = int(n)
        except (TypeError, ValueError):
            continue
        if v >= 0:
            out.add(v)
    return sorted(out)


def _spawn_season_job(
    jid: int, target, args, *, name: str, logger: Any
) -> Optional[JSONResponse]:
    """Start the daemon worker; on RuntimeError mark the job errored (so it can't
    poll 'running' forever) and return a 503, else None."""
    try:
        threading.Thread(target=target, args=args, daemon=True, name=name).start()
    except RuntimeError as exc:
        logger.error(f"cl2k: could not start {name}: {exc}")
        with _season_jobs_lock:
            job = _season_jobs.get(jid)
            if job is not None:
                job["status"] = "error"
                job["error"] = f"the season job could not be started — {_JOB_FAILED}"
        return error(
            "could not start the season job", "CL2K_JOB_START", status_code=503
        )
    return None


def _run_seasons_job(jid: int, db: ChubDB, logger: Any, req: SeasonsRequest) -> None:
    """Worker body: render every requested season, updating the registry as each
    completes. Never raises — a crash is recorded as the job's error so the
    frontend poll terminates instead of spinning on a stuck "running"."""

    def _progress(entry: Dict[str, Any]) -> None:
        with _season_jobs_lock:
            job = _season_jobs.get(jid)
            if job is not None:
                job["results"].append(entry)
                job["done"] += 1

    try:
        # Hoisted out of the loop, not out of the guard: malformed base64 must
        # fail the job, and re-decoding multi-MB blobs per season is wasted work.
        backdrop_bytes = _b64_to_bytes(req.backdrop_b64)
        logo_bytes = _b64_to_bytes(req.logo_b64)
        logo_flip_bytes = _b64_to_bytes(req.logo_flip_b64)
        logo_erase_bytes = _b64_to_bytes(req.logo_erase_b64)
        for n in req.seasons:
            # Re-read per season: config is REPLACED on reload.
            # Inside the guard, so a config fault fails the job, not the thread.
            generate_seasons(
                db=db,
                full_config=load_config(),
                logger=logger,
                tmdb_id=req.tmdb_id,
                title=req.title,
                seasons=[int(n)],
                year=req.year,
                tvdb_id=req.tvdb_id,
                imdb_id=req.imdb_id,
                backdrop_path=req.backdrop_path,
                backdrop_bytes=backdrop_bytes,
                logo_path=req.logo_path,
                custom_logo_bytes=logo_bytes,
                framing=_framing(req),
                logo_scale=req.logo_scale,
                logo_y_offset=req.logo_y_offset,
                whiten=req.whiten,
                flat_white=req.flat_white,
                logo_3d=req.logo_3d,
                invert=req.invert,
                logo_flip_bytes=logo_flip_bytes,
                logo_erase_bytes=logo_erase_bytes,
                force=req.force,
                save_local=req.save_local,
                upload_gdrive=req.upload_gdrive,
                progress_cb=_progress,
            )
        with _season_jobs_lock:
            job = _season_jobs.get(jid)
            if job is not None:
                job["status"] = "done"
    except Exception as exc:  # defensive: never leave a job stuck "running"
        logger.error(f"cl2k: season batch {jid} crashed: {exc}", exc_info=True)
        with _season_jobs_lock:
            job = _season_jobs.get(jid)
            if job is not None:
                job["status"] = "error"
                job["error"] = f"the season batch {_JOB_FAILED}"


@router.post("/generate-seasons", summary="Start a background CL2K season batch")
def generate_seasons_endpoint(
    req: SeasonsRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    if (bad := _require_any_id(req)) is not None:
        return bad
    seasons = _clean_seasons(req.seasons)
    if not seasons:
        return error("No seasons requested", "CL2K_NO_SEASONS")
    if len(seasons) > _MAX_SEASONS:
        return error(
            f"Too many seasons ({len(seasons)}); the maximum is {_MAX_SEASONS}",
            "CL2K_TOO_MANY_SEASONS",
        )
    req.seasons = seasons  # the worker iterates req.seasons
    jid = _new_season_job(len(seasons), req.title)
    if (
        failed := _spawn_season_job(
            jid,
            _run_seasons_job,
            (jid, db, logger, req),
            name=f"cl2k-seasons-{jid}",
            logger=logger,
        )
    ) is not None:
        return failed
    logger.info(f"cl2k: season batch {jid} started ({len(seasons)} seasons)")
    return ok("Season generation started", {"job_id": jid, "total": len(seasons)})


@router.get("/seasons-status/{job_id}", summary="Progress of a background season batch")
def seasons_status(job_id: int) -> JSONResponse:
    """Progress + outcome of a season batch.

    ``status`` stays the LIFECYCLE (running / done / error) — the page treats any
    other value as "still going" — and escalates to ``error`` only for a finished
    batch that produced nothing, which used to toast a green "0/N generated".
    ``failed`` and ``outcome`` (ok | partial | error) carry the finer verdict."""
    job = _season_job_snapshot(job_id)
    if job is None:
        return error("Unknown season job", "CL2K_NO_JOB", status_code=404)
    results = job["results"]
    generated = sum(1 for r in results if r.get("status") == "generated")
    # A skip ("already generated") is an outcome, not a failure.
    failed = sum(1 for r in results if r.get("status") not in ("generated", "skipped"))
    status, detail = job["status"], job["error"]
    if failed:
        outcome = "partial" if (generated or status == "running") else "error"
    else:
        outcome = "error" if status == "error" else "ok"
    if outcome == "error" and status == "done":
        status = "error"
        detail = detail or f"all {failed} of {job['total']} seasons failed"
    return ok(
        "Season job status",
        {
            "job_id": job["id"],
            "status": status,
            "outcome": outcome,
            "total": job["total"],
            "done": job["done"],
            "generated": generated,
            "failed": failed,
            "results": results,
            "error": detail,
        },
    )


# ─── File-as-is season batch ─────────────────────────────────────────────────
# The "File as is" output files ONE finished poster, drawing a band label + border
# (no logo/reframe). This batches that over a list of seasons: the same source
# image is re-filed once per season with that season's SEASON-N band, reusing the
# background-job registry + /seasons-status poll the full-CL2K season batch uses.


class RetextSeasonsRequest(BaseModel):
    # Source poster: uploaded bytes (base64) OR a remote path fetched server-side
    # (mirrors RetextRequest). The same image is reused for every season.
    image_b64: Optional[str] = None
    image_path: Optional[str] = None
    seasons: List[int]
    title: str = ""
    tmdb_id: int = 0
    year: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    text_y: Optional[float] = None  # band vertical position, 0..1 (None = CL2K band)
    border: bool = True
    save_local: bool = True
    upload_gdrive: Optional[bool] = None


def _run_retext_seasons_job(
    jid: int, db: ChubDB, logger: Any, image_bytes: bytes, req: RetextSeasonsRequest
) -> None:
    """Worker body: re-file the one source poster once per season, drawing that
    season's SEASON-N band. Never raises — a crash is recorded as the job error so
    the frontend poll terminates instead of spinning on a stuck "running"."""
    try:
        for n in req.seasons:
            n = int(n)
            # Re-read per season: config is REPLACED on reload.
            # Inside the guard, so a config fault fails the job, not the thread.
            full_config = load_config()
            try:
                res = retext_poster(
                    db=db,
                    full_config=full_config,
                    logger=logger,
                    image_bytes=image_bytes,
                    apply_ai=False,
                    # No label_text — retext_poster derives the SEASON-N band from
                    # season_number (single source of truth, season_band_text).
                    text_y_frac=req.text_y,
                    save=True,
                    kind="season",
                    title=req.title,
                    tmdb_id=req.tmdb_id,
                    year=req.year,
                    tvdb_id=req.tvdb_id,
                    imdb_id=req.imdb_id,
                    season_number=n,
                    add_border=req.border,
                    save_local=req.save_local,
                    upload_gdrive=req.upload_gdrive,
                )
            except Exception as exc:  # one bad season must not sink the rest
                logger.error(f"cl2k: as-is season {n} failed: {exc}", exc_info=True)
                res = {"status": "error", "reason": f"season {n} {_JOB_FAILED}"}
            if not isinstance(res, dict):
                res = {"status": "generated"}
            with _season_jobs_lock:
                job = _season_jobs.get(jid)
                if job is not None:
                    job["results"].append({"season": n, **res})
                    job["done"] += 1
        with _season_jobs_lock:
            job = _season_jobs.get(jid)
            if job is not None:
                job["status"] = "done"
    except Exception as exc:  # defensive: never leave a job stuck "running"
        logger.error(f"cl2k: as-is season batch {jid} crashed: {exc}", exc_info=True)
        with _season_jobs_lock:
            job = _season_jobs.get(jid)
            if job is not None:
                job["status"] = "error"
                job["error"] = f"the season batch {_JOB_FAILED}"


@router.post("/retext-seasons", summary="Start a background File-as-is season batch")
def retext_seasons_endpoint(
    req: RetextSeasonsRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """Start the background batch that re-files one poster per season, as is."""
    if (bad := _require_any_id(req)) is not None:
        return bad
    seasons = _clean_seasons(req.seasons)
    if not seasons:
        return error("No seasons requested", "CL2K_NO_SEASONS")
    if len(seasons) > _MAX_SEASONS:
        return error(
            f"Too many seasons ({len(seasons)}); the maximum is {_MAX_SEASONS}",
            "CL2K_TOO_MANY_SEASONS",
        )
    req.seasons = seasons  # the worker iterates req.seasons
    if req.image_b64:
        try:
            image_bytes = base64.b64decode(req.image_b64.split(",")[-1])
        except Exception:
            return error("invalid image data", "CL2K_RETEXT")
    elif req.image_path:
        try:
            image_bytes = download_image(req.image_path)
        except Exception as exc:
            return _failed(logger, "fetch the source image", exc, "CL2K_RETEXT")
    else:
        return error("no image provided", "CL2K_RETEXT")
    jid = _new_season_job(len(seasons), req.title)
    if (
        failed := _spawn_season_job(
            jid,
            _run_retext_seasons_job,
            (jid, db, logger, image_bytes, req),
            name=f"cl2k-retext-seasons-{jid}",
            logger=logger,
        )
    ) is not None:
        return failed
    logger.info(f"cl2k: as-is season batch {jid} started ({len(seasons)} seasons)")
    return ok("Season generation started", {"job_id": jid, "total": len(seasons)})


@router.get("/fanart-images", summary="fanart.tv logo + background for the art picker")
def fanart_images_endpoint(
    # tmdb_id optional: fanart.tv keys shows by tvdb_id, so a TVDB-only title
    # (no TMDB cross-link) can still pull a logo/background from fanart.
    tmdb_id: Optional[int] = Query(None),
    media_type: str = Query("movie", alias="type"),
    tvdb_id: Optional[int] = Query(None),
    imdb_id: Optional[str] = Query(None),
    season_number: Optional[int] = Query(None),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    res = fanart_images(
        load_config(),
        db,
        logger,
        kind=media_type,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        season_number=season_number,
    )
    # Shape like /images so the picker can merge sources. fanart returns absolute
    # URLs; image_fetch.download and the render request accept those as-is, so
    # file_path == url here.
    logos = [{"file_path": res["logo"], "url": res["logo"]}] if res.get("logo") else []
    backdrops = (
        [{"file_path": res["background"], "url": res["background"]}]
        if res.get("background")
        else []
    )
    return ok("ok", {"logos": logos, "backdrops": backdrops})


@router.get("/plex-images", summary="Plex artwork (logos + backgrounds + posters)")
def plex_images_endpoint(
    tmdb_id: Optional[int] = Query(None),
    media_type: str = Query("movie", alias="type"),
    tvdb_id: Optional[int] = Query(None),
    imdb_id: Optional[str] = Query(None),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """Read-only Plex artwork for the picker: resolves the item to a ratingKey
    via the synced plex_media_cache and returns its clearLogos / backgrounds /
    posters. ``file_path`` is a tokenless Plex URL the backend downloader re-mints
    the token for; ``url`` routes the browser through /plex-art so the
    X-Plex-Token never reaches the client. Never writes to Plex, so it can't
    affect Poster Cleanarr's in-use set."""
    from backend.util.cl2k.plex_art import plex_images

    res = plex_images(
        load_config(),
        db,
        logger,
        kind=media_type,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
    )
    return ok("ok", res)


# The /plex-art proxy only fetches Plex artwork-key paths — never arbitrary Plex
# endpoints (a leaked <img> src repointed at /:/prefs leaks the PlexOnlineToken).
def _valid_plex_art_src(src: str) -> bool:
    """True only for a clean Plex artwork-key URL — the /plex-art proxy guard."""
    return _is_plex_art_path(src)


def _img_media_type(blob: bytes) -> str:
    """Content-Type from magic bytes so PNG logos (transparency) aren't
    mislabeled as JPEG."""
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


@router.get(
    "/plex-art",
    summary="Proxy Plex artwork server-side (X-Plex-Token stays off the browser)",
)
def plex_art_proxy(
    src: str = Query(..., description="Tokenless Plex image URL from /plex-images"),
    logger: Any = Depends(get_cl2k_logger),
) -> Response:
    """Fetch a Plex ARTWORK image server-side and stream the bytes back, so the
    browser's <img> never carries the user's long-lived X-Plex-Token. ``src`` is
    constrained to Plex artwork-key paths (_is_plex_art_path) and ``download_image``
    re-mints the token + SSRF-gates the host, so a stream token minted to load one
    poster can't be repointed at other Plex endpoints or hosts. Loaded by <img>
    with a short-lived stream token in the URL (see the manifest's
    ``stream_prefixes``)."""
    if not _valid_plex_art_src(src):
        raise HTTPException(status_code=400, detail="not a Plex artwork URL")
    try:
        blob = download_image(src)
    except Exception as exc:
        logger.debug(f"cl2k: plex-art proxy fetch failed: {exc}")
        raise HTTPException(status_code=404, detail="image unavailable") from exc
    if not blob:
        raise HTTPException(status_code=404, detail="image unavailable")
    return Response(
        content=blob,
        media_type=_img_media_type(blob),
        headers={"Cache-Control": "private, max-age=3600"},
    )


class RetextRequest(BaseModel):
    # The source poster: uploaded bytes (base64) OR a TMDB/fanart/Plex path we
    # fetch server-side. Prefer the path for remote art — the browser can't fetch
    # image.tmdb.org directly (no CORS), so the frontend must not base64 it itself.
    image_b64: Optional[str] = None  # uploaded poster (base64; data-URL prefix allowed)
    image_path: Optional[str] = None  # remote art path/URL, fetched via download_image
    mask_b64: Optional[str] = None  # brushed mask over the old text (white=erase)
    apply_ai: bool = False  # run AI text-removal on the masked region
    prompt: Optional[str] = None  # per-edit AI prompt (defaults to ai_prompt)
    label_text: str = ""  # new label to draw in CL2K font (e.g. "SEASON 2026")
    text_y: Optional[float] = None  # label vertical position, 0..1 fraction
    kind: str = "movie"
    title: str = ""
    tmdb_id: int = 0
    year: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    season_number: Optional[int] = None
    border: bool = True  # composite the default 26px white CL2K border
    preview: bool = False
    # Skip the 1000x1500 normalize on previews so the AI-erased image keeps its
    # original dimensions (used when the result feeds the full CL2K render).
    keep_size: bool = False
    save_local: bool = True
    upload_gdrive: Optional[bool] = None


@router.post(
    "/retext", summary="Re-text a finished poster (AI-erase old text + redraw label)"
)
def retext(
    req: RetextRequest,
    background_tasks: BackgroundTasks,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """Re-text a finished poster: AI-erase the old label, draw the new one."""
    # Only a save needs a matchable filename; a preview returns bytes to the caller.
    if not req.preview and (bad := _require_any_id(req)) is not None:
        return bad
    if req.image_b64:
        try:
            image_bytes = base64.b64decode(req.image_b64.split(",")[-1])
        except Exception:
            return error("invalid image data", "CL2K_RETEXT")
    elif req.image_path:
        try:
            image_bytes = download_image(req.image_path)
        except Exception as exc:  # disallowed host / fetch failure
            return _failed(logger, "fetch the source image", exc, "CL2K_RETEXT")
    else:
        return error("no image provided", "CL2K_RETEXT")
    try:
        mask_bytes = _mask_bytes(req.mask_b64)
    except Exception:
        return error("invalid mask data", "CL2K_RETEXT")
    logger.info(
        f"CL2K retext: {'preview' if req.preview else 'save'} "
        f"(apply_ai={req.apply_ai}, mask={'yes' if req.mask_b64 else 'no'}, "
        f"label={req.label_text!r})"
    )
    # Only the user-triggered apply_ai path is gated; the lenient skip for an
    # unconfigured provider stays in remove_text.
    if req.apply_ai:
        cfg, unavailable = _ai_config_or_error(logger, "retext")
        if unavailable:
            return unavailable
    else:
        cfg = load_config()
    try:
        out = retext_poster(
            db=db,
            full_config=cfg,
            logger=logger,
            image_bytes=image_bytes,
            mask_bytes=mask_bytes,
            apply_ai=req.apply_ai,
            prompt=req.prompt,
            label_text=req.label_text,
            text_y_frac=req.text_y,
            save=not req.preview,
            kind=req.kind,
            title=req.title,
            tmdb_id=req.tmdb_id,
            year=req.year,
            tvdb_id=req.tvdb_id,
            imdb_id=req.imdb_id,
            season_number=req.season_number,
            add_border=req.border,
            keep_size=req.keep_size,
            save_local=req.save_local,
            upload_gdrive=req.upload_gdrive,
            # A save uploads via rclone, which outruns the request timeout on a slow
            # link. A preview never persists, so it has nothing to defer.
            defer_upload=None if req.preview else background_tasks.add_task,
        )
    except Exception as exc:
        # Without this, an AI/timeout failure produced a bare 500 with nothing in
        # the logs — log it and return a readable error to the client instead.
        return _failed(logger, "re-text that poster", exc, "CL2K_RETEXT", trace=True)
    if req.preview:
        return ok("ok", {"preview_b64": base64.b64encode(out).decode()})
    if isinstance(out, dict) and out.get("status") == "generated":
        if out.get("upload_pending"):
            return ok("Poster saved — uploading to Drive", out)
        return ok("Poster saved", out)
    reason = (
        out.get("reason", "retext failed") if isinstance(out, dict) else "retext failed"
    )
    return error(reason, "CL2K_RETEXT", data=out if isinstance(out, dict) else None)


class DetectTextRequest(BaseModel):
    # The poster to scan: uploaded bytes (base64) OR a TMDB/fanart/Plex path we
    # fetch server-side (mirrors RetextRequest — the browser can't fetch
    # image.tmdb.org itself, no CORS, so remote art must come through the
    # host-allowlisted downloader).
    image_b64: Optional[str] = None  # base64; data-URL prefix allowed
    image_path: Optional[str] = None  # remote art path/URL, fetched via download_image
    min_score: float = Field(0.5, ge=0.0, le=1.0)  # detector confidence floor


@router.post(
    "/detect-text", summary="Detect text regions on a poster via the LaMa sidecar"
)
def detect_text(
    req: DetectTextRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """Proxy the sidecar's /api/v1/detect so the frontend can pre-fill the erase
    brush: returns its body verbatim — {regions: [polygons], mask: b64 PNG
    (white=text)}. Sidecar-only; OpenAI has no detection endpoint."""
    if req.image_b64:
        try:
            image_bytes = base64.b64decode(req.image_b64.split(",")[-1])
        except Exception:
            return error("invalid image data", "CL2K_DETECT")
    elif req.image_path:
        try:
            image_bytes = download_image(req.image_path)
        except Exception as exc:  # disallowed host / fetch failure
            return _failed(logger, "fetch the source image", exc, "CL2K_DETECT")
    else:
        return error("no image provided", "CL2K_DETECT")
    full_config, unavailable = _ai_config_or_error(logger, "detect-text")
    if unavailable:
        return unavailable
    cfg = full_config.cl2k_maker
    if cfg.ai_provider != "lama_sidecar":  # openai has no detection endpoint
        reason = (
            "Text detection needs the LaMa sidecar provider — "
            "select it in Module Settings → CL2K Maker."
        )
        logger.warning(f"CL2K detect-text: unavailable — {reason}")
        return error(reason, "CL2K_AI_UNAVAILABLE")
    import requests

    # Shared route derivation with inpaint/upscale so a custom endpoint path is
    # honoured the same way for every sidecar route.
    url = text_removal._lama_route(cfg.ai_endpoint, "/api/v1/detect")
    try:
        resp = requests.post(
            url,
            json={
                "image": base64.b64encode(image_bytes).decode(),
                "min_score": req.min_score,
            },
            headers=text_removal._lama_headers(cfg),
            timeout=text_removal._timeout(cfg),
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        # Mirror /retext: a timeout/5xx/older-sidecar 404 comes back readable,
        # not as a bare 500 with nothing in the logs.
        return _failed(logger, "detect the text", exc, "CL2K_DETECT", trace=True)
    return ok("ok", body)


class TightenMaskRequest(BaseModel):
    # The poster to key against: uploaded bytes (base64) OR a remote art path we
    # fetch server-side (same source rules as /detect-text and /retext).
    image_b64: Optional[str] = None
    image_path: Optional[str] = None
    mask_b64: Optional[str] = None  # the brushed BLOCK mask (white = erase)
    color_tol: float = Field(33.0, ge=5.0, le=120.0)  # ΔE76 title-colour band


@router.post(
    "/tighten-mask",
    summary="Shrink a brushed block erase-mask down to the title glyph strokes",
)
def tighten_mask(
    req: TightenMaskRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """Colour-key the brushed region down to the title strokes so the inpainter
    fills thin gaps (sharp) instead of one big block (blurry). Pure local
    compute — no AI provider needed. Returns {tightened: bool, mask: b64 PNG |
    null}; ``tightened=false`` means no lettering could be isolated, so the
    frontend keeps the user's block."""
    if req.image_b64:
        try:
            raw = _b64_to_bytes(req.image_b64)
        except Exception:
            return error("invalid image data", "CL2K_TIGHTEN")
    elif req.image_path:
        try:
            raw = download_image(req.image_path)
        except Exception as exc:  # disallowed host / fetch failure
            return _failed(logger, "fetch the source image", exc, "CL2K_TIGHTEN")
    else:
        raw = None
    if not raw:
        return error("no image provided", "CL2K_TIGHTEN")
    try:
        mask = _mask_bytes(req.mask_b64)
    except Exception:
        return error("invalid mask data", "CL2K_TIGHTEN")
    if not mask:
        return error("no mask provided — brush over the text first", "CL2K_TIGHTEN")
    try:
        tightened = tighten_text_mask(raw, mask, color_tol=req.color_tol)
    except Exception as exc:
        return _failed(logger, "tighten that mask", exc, "CL2K_TIGHTEN", trace=True)
    if tightened is None:
        return ok(
            "kept",
            {
                "tightened": False,
                "mask": None,
                "reason": "Couldn't isolate the lettering — kept your mask.",
            },
        )
    return ok("ok", {"tightened": True, "mask": base64.b64encode(tightened).decode()})


def _probe_png() -> str:
    """A 32x32 base64 PNG — the cheapest body the sidecar's detect will accept."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (0, 0, 0)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _test_lama_sidecar(cfg, logger) -> JSONResponse:
    """Probe the LaMa sidecar's authenticated route and report what it proves."""
    import requests

    url = text_removal._lama_route(cfg.ai_endpoint, "/api/v1/detect")
    body = {"image": _probe_png(), "min_score": 0.5}
    timeout = min(text_removal._timeout(cfg), 30)
    try:
        resp = requests.post(
            url, json=body, headers=text_removal._lama_headers(cfg), timeout=timeout
        )
    except Exception as exc:
        logger.warning(f"cl2k: test-ai sidecar unreachable — {exc}")
        return error(
            f"Couldn't reach the sidecar at {cfg.ai_endpoint} — see the CL2K "
            "Maker log for the reason.",
            "CL2K_AI_TEST",
            status_code=503,
        )
    if resp.status_code in (401, 403):
        if not cfg.client_key:
            # The asymmetric case: container keyed, CHUB not. Every erase 401s
            # and nothing else reports it, so name it precisely.
            return error(
                "The sidecar requires a key but CHUB's Sidecar API Key is empty "
                "— copy the container's LAMA_API_KEY into it.",
                "CL2K_AI_TEST",
            )
        return error(
            "The sidecar rejected the key. CHUB's Sidecar API Key and the "
            "container's LAMA_API_KEY must match exactly.",
            "CL2K_AI_TEST",
        )
    if not resp.ok:
        return error(
            f"The sidecar answered HTTP {resp.status_code}.", "CL2K_AI_TEST"
        )
    if not cfg.client_key:
        return ok("Sidecar reachable. No key set — it is accepting anyone on this network.")
    # A 200 alone can't tell "key accepted" from "key ignored": a keyless sidecar
    # ignores the header entirely. Re-probe unauthenticated to tell them apart.
    try:
        bare = requests.post(url, json=body, timeout=timeout)
    except Exception as exc:
        # An exception proves nothing about enforcement. Say what was actually
        # verified — the key works — and never claim the part that wasn't.
        logger.warning(f"cl2k: test-ai unauthenticated re-probe failed — {exc}")
        return ok(
            "Sidecar reachable and your key works. The follow-up check — whether "
            "a keyless call gets blocked — could not run; see the CL2K Maker log."
        )
    if bare.status_code not in (401, 403):
        return ok(
            "Sidecar reachable and your key works — but it also answers WITHOUT "
            "a key, so LAMA_API_KEY is not set on the container."
        )
    return ok("Sidecar reachable, key accepted, and unauthenticated calls are refused.")


def _test_openai(cfg, logger) -> JSONResponse:
    """Probe OpenAI's authenticated route and report whether the key works."""
    import requests

    try:
        resp = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=20,
        )
    except Exception as exc:
        return _failed(logger, "reach OpenAI", exc, "CL2K_AI_TEST", status_code=503)
    if resp.status_code in (401, 403):
        return error("OpenAI rejected the API key.", "CL2K_AI_TEST")
    if not resp.ok:
        return error(f"OpenAI answered HTTP {resp.status_code}.", "CL2K_AI_TEST")
    return ok("OpenAI reachable and the key is accepted.")


@router.post(
    "/test-ai", summary="Check the configured AI provider is reachable and authenticated"
)
def test_ai(
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """Round-trip the provider's AUTHENTICATED route.

    Deliberately not /health: the sidecar leaves that open, so it answers 200
    with a wrong key or none at all. Credentials are read server-side — the
    frontend only ever sees them redacted, so it cannot send them back.
    """
    cfg, unavailable = _ai_config_or_error(logger, "test-ai")
    if unavailable:
        return unavailable
    maker = cfg.cl2k_maker
    if maker.ai_provider == "lama_sidecar":
        return _test_lama_sidecar(maker, logger)
    return _test_openai(maker, logger)
