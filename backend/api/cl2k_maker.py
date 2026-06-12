"""CL2K Maker API.

Powers the CL2K Poster Maker page. Entry points (TMDB search, ID/URL paste,
unmatched-asset links) all resolve to a tmdb_id + kind; the art picker lists
every logo/backdrop; preview renders without saving; generate writes the poster
into the configured source_dir and records provenance.

    GET  /api/cl2k-maker/search?q=&type=         TMDB title search (entry point)
    GET  /api/cl2k-maker/resolve?external_id=&source=&type=   tvdb/imdb -> tmdb
    GET  /api/cl2k-maker/images?tmdb_id=&type=    all logos + backdrops (picker)
    POST /api/cl2k-maker/preview                  render to JPEG, no save
    POST /api/cl2k-maker/generate                 render + write + cache + log
    GET  /api/cl2k-maker/generated                provenance (recent)

Module settings are read/saved through the generic /api/config endpoints.
"""

import base64
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

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
    save_finished_poster,
)
from backend.util.cl2k import tmdb_art
from backend.util.cl2k.image_fetch import TMDB_IMAGE_CDN, download as download_image
from backend.util.cl2k.renderer import process_logo, render_framed_art, render_square_art
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


class GenerateRequest(BaseModel):
    kind: str
    title: str
    tmdb_id: int
    year: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    season_number: Optional[int] = None
    backdrop_path: Optional[str] = None
    logo_path: Optional[str] = None
    logo_b64: Optional[str] = None  # custom uploaded logo (PNG, base64); wins over logo_path
    # Logo size: relaxes the height clamp (the y=1100 zone-top guide) so tall/boxy
    # logos can render readable; 1.0 = the strict CL2K guide box. Width caps still apply.
    logo_scale: float = Field(1.0, ge=0.25, le=3.0)
    # Logo position: vertical shift in px from the locked baseline (positive = down).
    # Size is unaffected; the placement is clamped onto the canvas.
    logo_y_offset: int = Field(0, ge=-600, le=200)
    # Per-render CL2K-whiten override; None falls back to the module config
    # (whiten_logo). True = two-tone white, False = the original colored logo.
    whiten: Optional[bool] = None
    # B/W touch-up: regions brushed over the PROCESSED logo whose black/white is
    # inverted (for interior accents the two-tone keymap can't decide).
    logo_flip_b64: Optional[str] = None
    mask_b64: Optional[str] = None  # user-brushed mask (PNG, white=remove) for AI
    remove_text: bool = False  # run AI text removal (OpenAI can do it mask-less)
    focus_x: float = 0.5  # crop focal point (0..1); 0.5 = centre (cover mode)
    focus_y: float = 0.5
    # Framing: "cover" scales up + crops to fill (focus_x/y); "fit" scales the
    # backdrop down to the canvas width and black-pads the bottom, keeping the full
    # width so spread-out subjects all stay in frame. ``crop_*`` (0..1) optionally
    # isolates the subject region of a wide backdrop before the fit.
    fit_mode: str = "cover"
    crop_x: Optional[float] = None
    crop_y: Optional[float] = None
    crop_w: Optional[float] = None
    crop_h: Optional[float] = None
    # Vertical position (0..1). In fit/extend it positions the fitted photo (0 =
    # top, ~0.4 = headroom). In cover ("Fill") it pans the framing UP at the same
    # size — real artwork flows down into the gradient, no AI (0 = unchanged).
    v_pos: float = 0.0
    # Zoom (>=1) for fit/extend: enlarge the subject above the full-width fit (sides
    # crop) so a wide backdrop isn't shrunk to a tiny strip. 1.0 = plain fit.
    zoom: float = Field(1.0, ge=1.0, le=3.0)
    # Explicit bottom banner (e.g. "COMPLETE LIMITED SERIES"); overrides the auto
    # COLLECTION / season label when set.
    band_label: str = ""
    force: bool = False
    # Preview-only: render the logo-less base (backdrop + gradient + label + border)
    # so the frontend can overlay a live logo on top — the size/position sliders
    # then move the logo without a server render per drag. Always True on generate
    # (the logo is baked into the saved poster).
    place_logo: bool = True
    # Save destinations (independent). upload_gdrive=None falls back to the module
    # config flag; at least one must be selected at save time.
    save_local: bool = True
    upload_gdrive: Optional[bool] = None


def _mask_bytes(b64: Optional[str]) -> Optional[bytes]:
    return base64.b64decode(b64) if b64 else None


def _b64_to_bytes(b64: Optional[str]) -> Optional[bytes]:
    """Decode a base64 image, tolerating a ``data:...;base64,`` URL prefix."""
    return base64.b64decode(b64.split(",")[-1]) if b64 else None


def _crop_tuple(req: Any):
    """Assemble the (x, y, w, h) fit crop from a request, or None if unset.

    Works for any request carrying ``crop_x/y/w/h`` (GenerateRequest, SeasonsRequest).
    Only used in ``fit`` mode; all four fields must be present for a crop to apply
    (a partial crop is ignored so the whole backdrop is fitted)."""
    parts = (req.crop_x, req.crop_y, req.crop_w, req.crop_h)
    return tuple(parts) if all(p is not None for p in parts) else None


def _resolve_logo_bytes(
    logo_path: Optional[str], logo_b64: Optional[str]
) -> Optional[bytes]:
    """Bytes for a chosen logo (or None). An uploaded PNG (``logo_b64``) wins over
    a chosen TMDB/fanart ``logo_path``, which is fetched via the host-allowlisted
    image downloader (so a crafted path can't trigger an SSRF)."""
    if logo_b64:
        return _b64_to_bytes(logo_b64)
    if logo_path:
        return download_image(logo_path)
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


@router.get("/images", summary="All logos + backdrops + posters for the art picker")
def images(
    tmdb_id: int = Query(...),
    media_type: str = Query("movie", alias="type"),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    tmdb = TMDBClient(load_config().tmdb, db, logger)
    imgs = tmdb_art.list_images(tmdb, tmdb_id, media_type) or {"logos": [], "backdrops": []}
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


@router.get("/season-images", summary="TMDB season posters (portrait) for the art picker")
def season_images(
    tmdb_id: int = Query(...),
    season_number: int = Query(...),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    tmdb = TMDBClient(load_config().tmdb, db, logger)
    imgs = tmdb_art.list_season_images(tmdb, tmdb_id, season_number) or {"posters": []}
    return ok("ok", {"posters": _decorate(imgs.get("posters", []))})


@router.get("/upload-status", summary="Whether CL2K Drive upload has a usable OAuth token")
def upload_status(
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    from backend.util.cl2k.gdrive_upload import has_upload_token

    cfg = load_config()
    return ok(
        "ok",
        {
            "upload_to_gdrive": bool(cfg.cl2k_maker.upload_to_gdrive),
            "folder_id_set": bool(cfg.cl2k_maker.gdrive_folder_id),
            "token_ok": has_upload_token(cfg.sync_gdrive),
        },
    )


@router.get("/external-ids", summary="TMDB external ids (tvdb_id + imdb_id) for a title")
def external_ids(
    tmdb_id: int = Query(...),
    media_type: str = Query("movie", alias="type"),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    tmdb = TMDBClient(load_config().tmdb, db, logger)
    return ok("ok", tmdb_art.external_ids(tmdb, tmdb_id, media_type))


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
    resolved = tmdb_id or None
    if not resolved and tvdb_id:
        resolved = tmdb.find_tmdb_id(str(tvdb_id), "tvdb_id", mt)
    if not resolved and imdb_id:
        resolved = tmdb.find_tmdb_id(str(imdb_id), "imdb_id", mt)
    d = (tmdb.get_details(resolved, mt) if resolved else None) or {}
    return ok("ok", {"title": d.get("title"), "year": d.get("year")})


class LogoProcessRequest(BaseModel):
    logo_path: Optional[str] = None
    logo_b64: Optional[str] = None  # custom uploaded logo (PNG, base64)
    # Per-render whiten override so the live overlay matches the Builder toggle;
    # None falls back to the module config (whiten_logo).
    whiten: Optional[bool] = None
    flip_b64: Optional[str] = None  # B/W touch-up regions (mask PNG, white=flip)


@router.post("/logo-processed", summary="Trimmed + whitened logo for the live overlay")
def logo_processed(
    req: LogoProcessRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    """Return the trimmed + whitened logo (PNG, base64) and its natural size, plus
    the configured ``logo_max_width``. The frontend draws these bytes at the box
    derived from the logo geometry so the size/position sliders preview live —
    matching :func:`render_cl2k`'s placement without a render per drag."""
    raw = _resolve_logo_bytes(req.logo_path, req.logo_b64)
    if not raw:
        return error("No logo provided", "NO_LOGO")
    cfg = load_config().cl2k_maker
    try:
        png, width, height = process_logo(
            raw,
            whiten=cfg.whiten_logo if req.whiten is None else req.whiten,
            flip_mask_bytes=_b64_to_bytes(req.flip_b64),
        )
    except Exception as exc:
        logger.warning(f"cl2k: logo processing failed: {exc}")
        return error("Could not process that logo", "LOGO_PROCESS")
    return ok(
        "ok",
        {
            "b64": base64.b64encode(png).decode(),
            "width": width,
            "height": height,
            "max_width": cfg.logo_max_width,
        },
    )


@router.post("/preview", summary="Render a CL2K poster without saving")
def preview(
    req: GenerateRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
):
    blob = render_preview(
        db,
        load_config(),
        logger,
        kind=req.kind,
        title=req.title,
        tmdb_id=req.tmdb_id,
        season_number=req.season_number,
        backdrop_path=req.backdrop_path,
        logo_path=req.logo_path,
        custom_logo_bytes=_b64_to_bytes(req.logo_b64),
        tvdb_id=req.tvdb_id,
        imdb_id=req.imdb_id,
        mask_bytes=_mask_bytes(req.mask_b64),
        apply_ai=req.remove_text,
        focus_x=req.focus_x,
        focus_y=req.focus_y,
        fit_mode=req.fit_mode,
        crop=_crop_tuple(req),
        v_pos=req.v_pos,
        zoom=req.zoom,
        band_label=req.band_label,
        logo_scale=req.logo_scale,
        logo_y_offset=req.logo_y_offset,
        logo_flip_bytes=_b64_to_bytes(req.logo_flip_b64),
        whiten=req.whiten,
        place_logo=req.place_logo,
    )
    if blob is None:
        return error("No textless backdrop available", "NO_BACKDROP")
    return Response(
        content=blob, media_type="image/jpeg", headers={"Cache-Control": "no-store"}
    )


@router.post("/generate", summary="Generate + save a CL2K poster")
def generate(
    req: GenerateRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    result = generate_for_item(
        db=db,
        full_config=load_config(),
        logger=logger,
        kind=req.kind,
        title=req.title,
        tmdb_id=req.tmdb_id,
        year=req.year,
        tvdb_id=req.tvdb_id,
        imdb_id=req.imdb_id,
        season_number=req.season_number,
        backdrop_path=req.backdrop_path,
        logo_path=req.logo_path,
        custom_logo_bytes=_b64_to_bytes(req.logo_b64),
        mask_bytes=_mask_bytes(req.mask_b64),
        apply_ai=req.remove_text,
        focus_x=req.focus_x,
        focus_y=req.focus_y,
        fit_mode=req.fit_mode,
        crop=_crop_tuple(req),
        v_pos=req.v_pos,
        zoom=req.zoom,
        band_label=req.band_label,
        logo_scale=req.logo_scale,
        logo_y_offset=req.logo_y_offset,
        logo_flip_bytes=_b64_to_bytes(req.logo_flip_b64),
        whiten=req.whiten,
        force=req.force,
        save_local=req.save_local,
        upload_gdrive=req.upload_gdrive,
    )
    if result.get("status") == "generated":
        return ok("Poster generated", result)
    return error(
        result.get("reason", "generation failed"), "CL2K_GENERATE", data=result
    )


# ─── Square art + logo asset makers ──────────────────────────────────────────
# Two additional asset types the maker files separately from posters: square art
# (1:1 cropped backdrop, `- SquareArt.jpg`) and a clear-logo asset (`- Logo.png`).
# Both flow into poster_cache so asset_renamerr applies them to Plex
# (uploadSquareArt / uploadLogo).


class SquareArtRequest(BaseModel):
    kind: str
    title: str
    tmdb_id: int
    year: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    # File the art for ONE season of a show (` - Season NN` name; plexapi seasons
    # accept square art) instead of the show itself. None = show/movie-level.
    season_number: Optional[int] = None
    backdrop_path: Optional[str] = None
    backdrop_b64: Optional[str] = None  # custom-uploaded source art (base64)
    focus_x: float = 0.5
    focus_y: float = 0.5
    fit_mode: str = "cover"  # cover (focal crop) | fit (contain on black)
    zoom: float = Field(1.0, ge=0.5, le=3.0)
    save_local: bool = True
    upload_gdrive: Optional[bool] = None


class LogoAssetRequest(BaseModel):
    kind: str
    title: str
    tmdb_id: int
    year: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    logo_path: Optional[str] = None
    logo_b64: Optional[str] = None
    whiten: bool = False  # True = CL2K-whitened; False = original (colored) clear logo
    flip_b64: Optional[str] = None  # B/W touch-up regions (mask PNG, white=flip)
    save_local: bool = True
    upload_gdrive: Optional[bool] = None


def _square_backdrop_bytes(req: SquareArtRequest) -> Optional[bytes]:
    if req.backdrop_b64:
        return _b64_to_bytes(req.backdrop_b64)
    if req.backdrop_path:
        return download_image(req.backdrop_path)
    return None


@router.post("/square-preview", summary="Render square art (1:1) without saving")
def square_preview(
    req: SquareArtRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
):
    raw = _square_backdrop_bytes(req)
    if not raw:
        return error("No source art selected", "NO_BACKDROP")
    blob = render_square_art(
        backdrop_bytes=raw,
        focus_x=req.focus_x,
        focus_y=req.focus_y,
        fit_mode=req.fit_mode,
        zoom=req.zoom,
    )
    return Response(
        content=blob, media_type="image/jpeg", headers={"Cache-Control": "no-store"}
    )


@router.post("/square-generate", summary="Generate + save square art")
def square_generate(
    req: SquareArtRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    result = generate_square_art(
        db=db,
        full_config=load_config(),
        logger=logger,
        kind=req.kind,
        title=req.title,
        tmdb_id=req.tmdb_id,
        year=req.year,
        tvdb_id=req.tvdb_id,
        imdb_id=req.imdb_id,
        backdrop_path=req.backdrop_path,
        backdrop_bytes=_b64_to_bytes(req.backdrop_b64),
        focus_x=req.focus_x,
        focus_y=req.focus_y,
        fit_mode=req.fit_mode,
        zoom=req.zoom,
        season_number=req.season_number,
        save_local=req.save_local,
        upload_gdrive=req.upload_gdrive,
    )
    if result.get("status") == "generated":
        return ok("Square art generated", result)
    return error(result.get("reason", "generation failed"), "CL2K_GENERATE", data=result)


class BackgroundArtRequest(BaseModel):
    kind: str
    title: str
    tmdb_id: int
    year: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    # File the art for ONE season of a show (` - Season NN` name; Plex seasons take
    # background art, Kometa reads Season##_background). None = show/movie-level.
    season_number: Optional[int] = None
    backdrop_path: Optional[str] = None
    backdrop_b64: Optional[str] = None  # custom-uploaded source art (base64)
    focus_x: float = 0.5
    focus_y: float = 0.5
    fit_mode: str = "cover"  # cover (focal crop) | fit (contain on black)
    zoom: float = Field(1.0, ge=0.5, le=3.0)
    resolution: str = "1080p"  # 1080p (1920x1080) | 4k (3840x2160), per Plex dims
    save_local: bool = True
    upload_gdrive: Optional[bool] = None


@router.post("/background-preview", summary="Render background art (16:9) without saving")
def background_preview(
    req: BackgroundArtRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
):
    raw = None
    if req.backdrop_b64:
        raw = _b64_to_bytes(req.backdrop_b64)
    elif req.backdrop_path:
        raw = download_image(req.backdrop_path)
    if not raw:
        return error("No source art selected", "NO_BACKDROP")
    # Preview at 1080p regardless of the save resolution — same 16:9 frame,
    # quarter the bytes of a 4K render.
    blob = render_framed_art(
        backdrop_bytes=raw,
        width=1920,
        height=1080,
        focus_x=req.focus_x,
        focus_y=req.focus_y,
        fit_mode=req.fit_mode,
        zoom=req.zoom,
    )
    return Response(
        content=blob, media_type="image/jpeg", headers={"Cache-Control": "no-store"}
    )


@router.post("/background-generate", summary="Generate + save background art")
def background_generate(
    req: BackgroundArtRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    result = generate_background_art(
        db=db,
        full_config=load_config(),
        logger=logger,
        kind=req.kind,
        title=req.title,
        tmdb_id=req.tmdb_id,
        year=req.year,
        tvdb_id=req.tvdb_id,
        imdb_id=req.imdb_id,
        backdrop_path=req.backdrop_path,
        backdrop_bytes=_b64_to_bytes(req.backdrop_b64),
        focus_x=req.focus_x,
        focus_y=req.focus_y,
        fit_mode=req.fit_mode,
        zoom=req.zoom,
        resolution=req.resolution,
        season_number=req.season_number,
        save_local=req.save_local,
        upload_gdrive=req.upload_gdrive,
    )
    if result.get("status") == "generated":
        return ok("Background art generated", result)
    return error(result.get("reason", "generation failed"), "CL2K_GENERATE", data=result)


@router.post("/logo-asset-preview", summary="Processed logo asset (transparent PNG), no save")
def logo_asset_preview(
    req: LogoAssetRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
):
    raw = _resolve_logo_bytes(req.logo_path, req.logo_b64)
    if not raw:
        return error("No logo selected", "NO_LOGO")
    png, _w, _h = process_logo(
        raw, whiten=req.whiten, flip_mask_bytes=_b64_to_bytes(req.flip_b64)
    )
    return Response(
        content=png, media_type="image/png", headers={"Cache-Control": "no-store"}
    )


@router.post("/logo-asset-generate", summary="File a clear logo as a - Logo asset")
def logo_asset_generate(
    req: LogoAssetRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    result = generate_logo_asset(
        db=db,
        full_config=load_config(),
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
        flip_mask_bytes=_b64_to_bytes(req.flip_b64),
        save_local=req.save_local,
        upload_gdrive=req.upload_gdrive,
    )
    if result.get("status") == "generated":
        return ok("Logo asset filed", result)
    return error(result.get("reason", "generation failed"), "CL2K_GENERATE", data=result)


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
    blob = psd_for_item(
        db=db,
        full_config=load_config(),
        logger=logger,
        kind=req.kind,
        title=req.title,
        tmdb_id=req.tmdb_id,
        backdrop_path=req.backdrop_path,
        logo_path=req.logo_path,
        logo_scale=req.logo_scale,
        logo_y_offset=req.logo_y_offset,
        focus_x=req.focus_x,
        focus_y=req.focus_y,
        fit_mode=req.fit_mode,
        crop=_crop_tuple(req),
        v_pos=req.v_pos,
        zoom=req.zoom,
        whiten=req.whiten,
    )
    if blob is None:
        return error("No textless backdrop available", "NO_BACKDROP")
    return Response(
        content=blob,
        media_type="image/vnd.adobe.photoshop",
        headers={"Content-Disposition": 'attachment; filename="cl2k.psd"'},
    )


class SeasonsRequest(BaseModel):
    tmdb_id: int
    title: str
    seasons: List[int]
    year: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    # Framing carried over from the show poster so every season matches it.
    fit_mode: str = "cover"
    focus_x: float = 0.5
    focus_y: float = 0.5
    crop_x: Optional[float] = None
    crop_y: Optional[float] = None
    crop_w: Optional[float] = None
    crop_h: Optional[float] = None
    v_pos: float = 0.0
    zoom: float = Field(1.0, ge=1.0, le=3.0)
    logo_scale: float = Field(1.0, ge=0.25, le=3.0)
    logo_y_offset: int = Field(0, ge=-600, le=200)
    whiten: Optional[bool] = None  # None = module config (whiten_logo)
    force: bool = False


@router.post("/generate-seasons", summary="Generate CL2K posters for multiple seasons")
def generate_seasons_endpoint(
    req: SeasonsRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    out = generate_seasons(
        db=db,
        full_config=load_config(),
        logger=logger,
        tmdb_id=req.tmdb_id,
        title=req.title,
        seasons=req.seasons,
        year=req.year,
        tvdb_id=req.tvdb_id,
        imdb_id=req.imdb_id,
        fit_mode=req.fit_mode,
        focus_x=req.focus_x,
        focus_y=req.focus_y,
        crop=_crop_tuple(req),
        v_pos=req.v_pos,
        zoom=req.zoom,
        logo_scale=req.logo_scale,
        logo_y_offset=req.logo_y_offset,
        whiten=req.whiten,
        force=req.force,
    )
    return ok("Seasons generated", out)


@router.post("/upload-generate", summary="Generate from a manually-cleaned backdrop (handoff)")
async def upload_generate(
    file: UploadFile = File(...),
    kind: str = Form(...),
    title: str = Form(...),
    tmdb_id: int = Form(...),
    year: Optional[int] = Form(None),
    tvdb_id: Optional[int] = Form(None),
    imdb_id: Optional[str] = Form(None),
    season_number: Optional[int] = Form(None),
    logo_path: Optional[str] = Form(None),
    logo_b64: Optional[str] = Form(None),
    logo_scale: float = Form(1.0, ge=0.25, le=3.0),
    logo_y_offset: int = Form(0, ge=-600, le=200),
    whiten: Optional[bool] = Form(None),  # None = module config (whiten_logo)
    # Framing — same semantics as GenerateRequest: cover (focus point), fit
    # (top-anchor + black-fill bottom; optional crop isolates a region first;
    # v_pos slides the photo down), or extend.
    fit_mode: str = Form("cover"),
    focus_x: float = Form(0.5),
    focus_y: float = Form(0.5),
    crop_x: Optional[float] = Form(None),
    crop_y: Optional[float] = Form(None),
    crop_w: Optional[float] = Form(None),
    crop_h: Optional[float] = Form(None),
    v_pos: float = Form(0.0),
    zoom: float = Form(1.0, ge=1.0, le=3.0),
    preview: bool = Form(False),
    save_local: bool = Form(True),
    upload_gdrive: Optional[bool] = Form(None),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    backdrop_bytes = await file.read()
    crop_parts = (crop_x, crop_y, crop_w, crop_h)
    crop = tuple(crop_parts) if all(p is not None for p in crop_parts) else None
    common = dict(
        kind=kind,
        title=title,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        season_number=season_number,
        backdrop_bytes=backdrop_bytes,
        logo_path=logo_path,
        custom_logo_bytes=_b64_to_bytes(logo_b64),
        logo_scale=logo_scale,
        logo_y_offset=logo_y_offset,
        whiten=whiten,
        fit_mode=fit_mode,
        focus_x=focus_x,
        focus_y=focus_y,
        crop=crop,
        v_pos=v_pos,
        zoom=zoom,
    )
    if preview:
        # Render-only (no save, no provenance) so the framing can be adjusted
        # against a live preview before generating.
        blob = render_preview(db, load_config(), logger, **common)
        if blob is None:
            return error("render failed", "CL2K_GENERATE")
        return ok("ok", {"preview_b64": base64.b64encode(blob).decode()})
    result = generate_for_item(
        db=db,
        full_config=load_config(),
        logger=logger,
        year=year,
        force=True,
        save_local=save_local,
        upload_gdrive=upload_gdrive,
        **common,
    )
    if result.get("status") == "generated":
        return ok("Poster generated", result)
    return error(result.get("reason", "generation failed"), "CL2K_GENERATE", data=result)


@router.get("/fanart-images", summary="fanart.tv logo + background for the art picker")
def fanart_images_endpoint(
    tmdb_id: int = Query(...),
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


@router.post("/upload-poster", summary="File a finished poster (optionally add a logo)")
async def upload_poster(
    file: UploadFile = File(...),
    kind: str = Form(...),
    title: str = Form(...),
    tmdb_id: int = Form(...),
    year: Optional[int] = Form(None),
    tvdb_id: Optional[int] = Form(None),
    imdb_id: Optional[str] = Form(None),
    season_number: Optional[int] = Form(None),
    border: bool = Form(True),
    logo_path: Optional[str] = Form(None),
    logo_b64: Optional[str] = Form(None),
    logo_scale: float = Form(1.0, ge=0.25, le=3.0),
    logo_y_offset: int = Form(0, ge=-600, le=200),
    whiten: Optional[bool] = Form(None),  # None = module config (whiten_logo)
    preview: bool = Form(False),
    save_local: bool = Form(True),
    upload_gdrive: Optional[bool] = Form(None),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    image_bytes = await file.read()
    logo_bytes = _resolve_logo_bytes(logo_path, logo_b64)
    logo_source = "custom" if logo_b64 else "tmdb" if logo_path else "upload"
    if preview:
        # Mirror the save pipeline (normalize -> overlay logo -> border) so the
        # preview matches the file that would be written, without persisting it.
        from backend.modules.cl2k_maker import _normalize_poster
        from backend.util.cl2k.renderer import apply_border, overlay_logo

        cfg = load_config().cl2k_maker
        blob = _normalize_poster(image_bytes)
        if logo_bytes:
            blob = overlay_logo(
                blob,
                logo_bytes,
                kind=(kind or "movie").lower(),
                logo_max_width=cfg.logo_max_width,
                logo_scale=logo_scale,
                logo_y_offset=logo_y_offset,
                whiten=cfg.whiten_logo if whiten is None else whiten,
            )
        if border:
            blob = apply_border(blob)
        return ok("ok", {"preview_b64": base64.b64encode(blob).decode()})
    result = save_finished_poster(
        db=db,
        full_config=load_config(),
        logger=logger,
        kind=kind,
        title=title,
        tmdb_id=tmdb_id,
        year=year,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        season_number=season_number,
        image_bytes=image_bytes,
        logo_source=logo_source,
        add_border=border,
        logo_bytes=logo_bytes,
        logo_scale=logo_scale,
        logo_y_offset=logo_y_offset,
        whiten=whiten,
        save_local=save_local,
        upload_gdrive=upload_gdrive,
    )
    if result.get("status") == "generated":
        return ok("Poster saved", result)
    return error(result.get("reason", "save failed"), "CL2K_UPLOAD", data=result)


class RetextRequest(BaseModel):
    image_b64: str  # uploaded poster (base64; data-URL prefix allowed)
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


@router.post("/retext", summary="Re-text a finished poster (AI-erase old text + redraw label)")
def retext(
    req: RetextRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    if not req.image_b64:
        return error("no image provided", "CL2K_RETEXT")
    try:
        image_bytes = base64.b64decode(req.image_b64.split(",")[-1])
    except Exception:
        return error("invalid image data", "CL2K_RETEXT")
    logger.info(
        f"CL2K retext: {'preview' if req.preview else 'save'} "
        f"(apply_ai={req.apply_ai}, mask={'yes' if req.mask_b64 else 'no'}, "
        f"label={req.label_text!r})"
    )
    try:
        out = retext_poster(
            db=db,
            full_config=load_config(),
            logger=logger,
            image_bytes=image_bytes,
            mask_bytes=_mask_bytes(req.mask_b64),
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
        )
    except Exception as exc:
        # Without this, an AI/timeout failure produced a bare 500 with nothing in
        # the logs — log it and return a readable error to the client instead.
        logger.error(f"CL2K retext failed: {exc}", exc_info=True)
        return error(f"retext failed: {exc}", "CL2K_RETEXT")
    if req.preview:
        return ok("ok", {"preview_b64": base64.b64encode(out).decode()})
    if isinstance(out, dict) and out.get("status") == "generated":
        return ok("Poster saved", out)
    reason = out.get("reason", "retext failed") if isinstance(out, dict) else "retext failed"
    return error(reason, "CL2K_RETEXT", data=out if isinstance(out, dict) else None)


