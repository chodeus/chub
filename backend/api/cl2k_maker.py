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

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from backend.api.utils import error, get_database, get_logger, ok
from backend.modules.cl2k_maker import (
    fanart_images,
    gdrive_psd_bytes,
    generate_for_item,
    generate_seasons,
    psd_for_item,
    render_preview,
    save_finished_poster,
)
from backend.util.cl2k.image_fetch import TMDB_IMAGE_CDN
from backend.util.config import load_config
from backend.util.database import ChubDB
from backend.util.tmdb import TMDBClient

router = APIRouter(
    prefix="/api/cl2k-maker",
    tags=["CL2K Maker"],
    responses={500: {"description": "Internal server error"}},
)


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
    mask_b64: Optional[str] = None  # user-brushed mask (PNG, white=remove) for AI
    remove_text: bool = False  # run AI text removal (OpenAI can do it mask-less)
    focus_x: float = 0.5  # crop focal point (0..1); 0.5 = centre
    focus_y: float = 0.5
    force: bool = False


def _mask_bytes(b64: Optional[str]) -> Optional[bytes]:
    return base64.b64decode(b64) if b64 else None


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
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    tmdb = TMDBClient(load_config().tmdb, db, logger)
    return ok("ok", {"results": tmdb.search_titles(q, media_type)})


@router.get("/resolve", summary="Resolve an external id (tvdb/imdb) to a tmdb id")
def resolve(
    external_id: str = Query(...),
    source: str = Query(..., description="tvdb_id | imdb_id"),
    media_type: str = Query("movie", alias="type"),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    tmdb = TMDBClient(load_config().tmdb, db, logger)
    mt = "movie" if media_type == "movie" else "tv"
    return ok("ok", {"tmdb_id": tmdb.find_tmdb_id(external_id, source, mt)})


@router.get("/images", summary="All logos + backdrops for the art picker")
def images(
    tmdb_id: int = Query(...),
    media_type: str = Query("movie", alias="type"),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_logger),
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


@router.post("/preview", summary="Render a CL2K poster without saving")
def preview(
    req: GenerateRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_logger),
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
    logger: Any = Depends(get_logger),
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
        mask_bytes=_mask_bytes(req.mask_b64),
        apply_ai=req.remove_text,
        focus_x=req.focus_x,
        focus_y=req.focus_y,
        force=req.force,
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
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    return ok("ok", {"items": db.cl2k_generated.list_recent(limit)})


@router.post("/psd-export", summary="Export the CL2K poster as a layered .psd")
def psd_export(
    req: GenerateRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_logger),
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
    logger: Any = Depends(get_logger),
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
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_logger),
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
        force=True,
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
    logger: Any = Depends(get_logger),
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


@router.post("/upload-poster", summary="File a finished poster as-is (no rendering)")
async def upload_poster(
    file: UploadFile = File(...),
    kind: str = Form(...),
    title: str = Form(...),
    tmdb_id: int = Form(...),
    year: Optional[int] = Form(None),
    tvdb_id: Optional[int] = Form(None),
    imdb_id: Optional[str] = Form(None),
    season_number: Optional[int] = Form(None),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    image_bytes = await file.read()
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
        logo_source="upload",
    )
    if result.get("status") == "generated":
        return ok("Poster saved", result)
    return error(result.get("reason", "save failed"), "CL2K_UPLOAD", data=result)


@router.get("/gdrive-list", summary="Configured .psd source drives, or .psd files in one")
def gdrive_list(
    drive_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="case-insensitive title substring"),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    cfg = load_config()
    if not drive_id:
        drives = [d.model_dump() for d in cfg.cl2k_maker.psd_source_drives]
        return ok("ok", {"drives": drives})
    from backend.util.cl2k.gdrive_upload import list_psd

    try:
        files = list_psd(cfg.sync_gdrive, drive_id, query=q)
    except Exception as exc:
        return error(str(exc), "CL2K_GDRIVE_LIST")
    return ok("ok", {"files": files})


class GDrivePsdRequest(BaseModel):
    drive_id: str
    path: str
    kind: str
    title: str
    tmdb_id: int
    year: Optional[int] = None
    tvdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    season_number: Optional[int] = None
    preview: bool = False


@router.post("/gdrive-psd", summary="Flatten a Drive .psd to a poster (preview or save)")
def gdrive_psd(
    req: GDrivePsdRequest,
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    cfg = load_config()
    try:
        blob = gdrive_psd_bytes(cfg, req.drive_id, req.path)
    except Exception as exc:
        return error(str(exc), "CL2K_GDRIVE_PSD")
    if req.preview:
        return ok("ok", {"preview_b64": base64.b64encode(blob).decode()})
    result = save_finished_poster(
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
        image_bytes=blob,
        logo_source="gdrive_psd",
    )
    if result.get("status") == "generated":
        return ok("Poster saved", result)
    return error(result.get("reason", "save failed"), "CL2K_GDRIVE_PSD", data=result)
