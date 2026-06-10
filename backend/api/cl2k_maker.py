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
from pydantic import BaseModel

from backend.api.utils import error, get_database, get_module_logger, ok
from backend.modules.cl2k_maker import (
    fanart_images,
    generate_for_item,
    generate_seasons,
    psd_for_item,
    render_preview,
    retext_poster,
    save_finished_poster,
)
from backend.util.cl2k.image_fetch import TMDB_IMAGE_CDN, download as download_image
from backend.util.config import load_config
from backend.util.database import ChubDB
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
    mask_b64: Optional[str] = None  # user-brushed mask (PNG, white=remove) for AI
    remove_text: bool = False  # run AI text removal (OpenAI can do it mask-less)
    focus_x: float = 0.5  # crop focal point (0..1); 0.5 = centre
    focus_y: float = 0.5
    force: bool = False
    # Save destinations (independent). upload_gdrive=None falls back to the module
    # config flag; at least one must be selected at save time.
    save_local: bool = True
    upload_gdrive: Optional[bool] = None


def _mask_bytes(b64: Optional[str]) -> Optional[bytes]:
    return base64.b64decode(b64) if b64 else None


def _b64_to_bytes(b64: Optional[str]) -> Optional[bytes]:
    """Decode a base64 image, tolerating a ``data:...;base64,`` URL prefix."""
    return base64.b64decode(b64.split(",")[-1]) if b64 else None


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
    return ok("ok", {"results": tmdb.search_titles(q, media_type)})


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


@router.get("/images", summary="All logos + backdrops for the art picker")
def images(
    tmdb_id: int = Query(...),
    media_type: str = Query("movie", alias="type"),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    tmdb = TMDBClient(load_config().tmdb, db, logger)
    imgs = tmdb.list_images(tmdb_id, media_type) or {"logos": [], "backdrops": []}
    return ok(
        "ok",
        {
            "logos": _decorate(imgs.get("logos", [])),
            "backdrops": _decorate(imgs.get("backdrops", [])),
        },
    )


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
    return ok("ok", tmdb.external_ids(tmdb_id, media_type))


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
        force=req.force,
        save_local=req.save_local,
        upload_gdrive=req.upload_gdrive,
    )
    if result.get("status") == "generated":
        return ok("Poster generated", result)
    return error(
        result.get("reason", "generation failed"), "CL2K_GENERATE", data=result
    )


@router.get("/generated", summary="Recently generated CL2K posters")
def generated(
    limit: int = Query(200, ge=1, le=1000),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    return ok("ok", {"items": db.cl2k_generated.list_recent(limit)})


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
    save_local: bool = Form(True),
    upload_gdrive: Optional[bool] = Form(None),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_cl2k_logger),
) -> JSONResponse:
    backdrop_bytes = await file.read()
    result = generate_for_item(
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
        backdrop_bytes=backdrop_bytes,
        logo_path=logo_path,
        custom_logo_bytes=_b64_to_bytes(logo_b64),
        force=True,
        save_local=save_local,
        upload_gdrive=upload_gdrive,
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
                whiten=cfg.whiten_logo,
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


