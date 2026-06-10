# modules/cl2k_maker.py

import os
import shutil
import tempfile
from typing import Any, Dict, Optional, Tuple

from backend.util.base_module import ChubModule
from backend.util.cl2k import color
from backend.util.cl2k import geometry as geo
from backend.util.cl2k import image_fetch, text_removal
from backend.util.cl2k.naming import build_poster_filename
from backend.util.cl2k.renderer import render_cl2k
from backend.util.database import ChubDB
from backend.util.fanart import FanartClient
from backend.util.logger import Logger
from backend.util.normalization import normalize_titles
from backend.util.tmdb import TMDBClient

_VALID_KINDS = ("movie", "show", "collection", "season")
_BATCH_KINDS = ("movie", "show")  # media_cache asset_types we batch over


def _fanart_logo(
    full_config, db, logger, *, kind, tmdb_id, tvdb_id, imdb_id, season_number, lang
) -> Optional[str]:
    """Look up a clear-logo URL on fanart.tv (the second logo source). None on miss."""
    try:
        asset_type = "movie" if kind in ("movie", "collection") else "show"
        client = FanartClient(full_config.fanart, db, logger)
        res = client.get_images(
            {
                "asset_type": asset_type,
                "tmdb_id": tmdb_id,
                "tvdb_id": tvdb_id,
                "imdb_id": imdb_id,
                "season_number": season_number,
            },
            language=lang,
        )
        return (res or {}).get("logo")
    except Exception as exc:  # fanart is a best-effort fallback, never fatal
        logger.debug(f"fanart logo lookup failed: {exc}")
        return None


def _resolve_and_render(
    db: ChubDB,
    full_config,
    logger,
    *,
    kind: str,
    title: str,
    tmdb_id: int,
    season_number: Optional[int] = None,
    season_text: str = "",
    backdrop_path: Optional[str] = None,
    logo_path: Optional[str] = None,
    custom_logo_bytes: Optional[bytes] = None,
    tvdb_id: Optional[int] = None,
    imdb_id: Optional[str] = None,
    mask_bytes: Optional[bytes] = None,
    backdrop_bytes: Optional[bytes] = None,
    apply_ai: bool = False,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
) -> Tuple[Optional[bytes], Dict[str, Any]]:
    """Resolve art (textless backdrop + logo) and render.

    The logo source chain is: ``custom_logo_bytes`` (an uploaded PNG, used as-is)
    -> ``logo_path`` (a chosen TMDB/fanart logo) -> auto TMDB -> fanart.tv ->
    generated text wordmark. Returns ``(jpeg_bytes, info)``; ``jpeg_bytes`` is None
    with ``info['reason']`` set when no textless backdrop is available. Shared by
    the preview endpoint and :func:`generate_for_item`.
    """
    cfg = full_config.cl2k_maker
    lang = cfg.language or "en"
    tmdb = TMDBClient(full_config.tmdb, db, logger)

    # Season reuse: a new season inherits the show's existing backdrop (DAPS:
    # same background across seasons, only the season number changes).
    if kind == "season" and backdrop_path is None and backdrop_bytes is None:
        backdrop_path = db.cl2k_generated.get_backdrop_for(tmdb_id)

    # Resolve a logo path (unless a custom logo was uploaded or one was chosen)
    # and a backdrop path (unless bytes were uploaded for the manual-handoff flow).
    need_logo = custom_logo_bytes is None and logo_path is None
    need_backdrop = backdrop_bytes is None and backdrop_path is None
    if need_logo or need_backdrop:
        images = tmdb.list_images(tmdb_id, kind, languages=lang) or {}
        sel = image_fetch.select_cl2k_inputs(images, lang=lang)
        if backdrop_bytes is None:
            backdrop_path = backdrop_path or sel.get("backdrop")
        if custom_logo_bytes is None:
            logo_path = logo_path or sel.get("logo")

    if backdrop_bytes is None:
        if not backdrop_path:
            return None, {"reason": "no textless backdrop available", "logo_source": "none"}
        backdrop_bytes = image_fetch.download(backdrop_path)

    # Only run AI removal when explicitly requested (a brushed mask, or the
    # apply_ai flag for OpenAI's maskless mode) — never on every auto-render.
    if apply_ai or mask_bytes:
        backdrop_bytes = text_removal.remove_text(
            backdrop_bytes, config=cfg, mask_bytes=mask_bytes, logger=logger
        )

    logo_bytes = None
    logo_source = "text" if cfg.text_logo_fallback else "none"
    if custom_logo_bytes is not None:
        logo_bytes = custom_logo_bytes
        logo_source = "custom"
    elif logo_path:
        logo_bytes = image_fetch.download(logo_path)
        logo_source = "tmdb"
    else:
        fa_url = _fanart_logo(
            full_config,
            db,
            logger,
            kind=kind,
            tmdb_id=tmdb_id,
            tvdb_id=tvdb_id,
            imdb_id=imdb_id,
            season_number=season_number,
            lang=lang,
        )
        if fa_url:
            logo_bytes = image_fetch.download(fa_url)
            logo_source = "fanart"

    if kind == "season" and not season_text and season_number is not None:
        season_text = f"Season {season_number}"

    blob = render_cl2k(
        backdrop_bytes=backdrop_bytes,
        kind=kind,
        logo_bytes=logo_bytes,
        title=title if (cfg.text_logo_fallback or logo_bytes) else "",
        season_text=season_text,
        logo_max_width=cfg.logo_max_width,
        whiten=cfg.whiten_logo,
        focus_x=focus_x,
        focus_y=focus_y,
    )
    return blob, {"backdrop_path": backdrop_path, "logo_source": logo_source}


def render_preview(db: ChubDB, full_config, logger, **kwargs) -> Optional[bytes]:
    """Render a CL2K poster to JPEG bytes WITHOUT saving (live preview)."""
    blob, _info = _resolve_and_render(db, full_config, logger, **kwargs)
    return blob


def generate_for_item(
    *,
    db: ChubDB,
    full_config,
    logger,
    kind: str,
    title: str,
    tmdb_id: int,
    year: Optional[int] = None,
    tvdb_id: Optional[int] = None,
    imdb_id: Optional[str] = None,
    season_number: Optional[int] = None,
    season_text: str = "",
    backdrop_path: Optional[str] = None,
    logo_path: Optional[str] = None,
    custom_logo_bytes: Optional[bytes] = None,
    mask_bytes: Optional[bytes] = None,
    backdrop_bytes: Optional[bytes] = None,
    apply_ai: bool = False,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    force: bool = False,
    save_local: bool = True,
    upload_gdrive: Optional[bool] = None,
) -> Dict[str, Any]:
    """Render + name + write to the selected destinations + provenance.

    Shared core for the API (on-demand) and run() (batch). ``save_local`` /
    ``upload_gdrive`` choose the destination(s) (see :func:`_persist_poster`).
    Returns ``{status, file?, reason?, logo_source?}``.
    """
    cfg = full_config.cl2k_maker
    kind = (kind or "").lower()
    if kind not in _VALID_KINDS:
        return {"status": "error", "reason": f"invalid kind {kind!r}"}
    # output_dir is only required when actually saving locally; a Drive-only save
    # uploads from a temp copy and never touches output_dir.
    if save_local and not cfg.output_dir:
        return {"status": "error", "reason": "cl2k_maker.output_dir is not configured"}

    if (
        cfg.skip_existing
        and not force
        and db.cl2k_generated.exists_for(kind, tmdb_id, season_number)
    ):
        return {"status": "skipped", "reason": "already generated"}

    blob, info = _resolve_and_render(
        db,
        full_config,
        logger,
        kind=kind,
        title=title,
        tmdb_id=tmdb_id,
        season_number=season_number,
        season_text=season_text,
        backdrop_path=backdrop_path,
        logo_path=logo_path,
        custom_logo_bytes=custom_logo_bytes,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        mask_bytes=mask_bytes,
        backdrop_bytes=backdrop_bytes,
        apply_ai=apply_ai,
        focus_x=focus_x,
        focus_y=focus_y,
    )
    if blob is None:
        return {"status": "skipped", "reason": info.get("reason", "render failed")}
    logo_source = info.get("logo_source", "none")

    return _persist_poster(
        db,
        cfg,
        logger,
        sync_cfg=full_config.sync_gdrive,
        blob=blob,
        kind=kind,
        title=title,
        year=year,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        season_number=season_number,
        backdrop_path=info.get("backdrop_path"),
        logo_source=logo_source,
        save_local=save_local,
        upload_gdrive=upload_gdrive,
    )


def _persist_poster(
    db: ChubDB,
    cfg,
    logger,
    *,
    sync_cfg=None,
    blob: bytes,
    kind: str,
    title: str,
    year: Optional[int],
    tmdb_id: int,
    tvdb_id: Optional[int],
    imdb_id: Optional[str],
    season_number: Optional[int],
    backdrop_path: Optional[str],
    logo_source: str,
    save_local: bool = True,
    upload_gdrive: Optional[bool] = None,
) -> Dict[str, Any]:
    """Write a finished poster to the selected destinations + provenance.

    Shared sink for rendered (:func:`generate_for_item`), uploaded-finished
    (:func:`save_finished_poster`) and .psd-flattened posters. ``backdrop_path``
    is None for posters that didn't go through the renderer.

    Destinations are independent: ``save_local`` writes the poster into
    ``output_dir`` and registers it in poster_cache (so the rest of CHUB
    matches/uploads it); ``upload_gdrive`` copies it to the configured Drive
    folder. ``upload_gdrive=None`` falls back to ``cfg.upload_to_gdrive`` (the
    batch ``run()`` default). At least one destination must be selected. A
    Drive-only save (``save_local=False``) has no persistent local file, so it is
    uploaded from a temporary copy and is recorded only in provenance, NOT in
    poster_cache (nothing local for CHUB to match).
    """
    if upload_gdrive is None:
        upload_gdrive = bool(cfg.upload_to_gdrive)
    do_upload = bool(upload_gdrive)
    if not save_local and not do_upload:
        return {"status": "error", "reason": "no save destination selected"}
    if do_upload and not cfg.gdrive_folder_id:
        if not save_local:
            return {
                "status": "error",
                "reason": "Google Drive selected but gdrive_folder_id is not configured",
            }
        # Local save still proceeds; just skip the (unconfigured) upload.
        do_upload = False

    filename = build_poster_filename(
        kind=kind,
        title=title,
        year=year,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        season_number=season_number,
        ext=geo.OUTPUT_EXT,
    )
    # build_poster_filename already strips path-illegal chars, but basename makes it
    # provably impossible for a crafted title to escape output_dir (path-injection).
    filename = os.path.basename(filename)

    out_path = None
    if save_local:
        os.makedirs(cfg.output_dir, exist_ok=True)
        out_path = os.path.join(cfg.output_dir, filename)
        with open(out_path, "wb") as fh:
            fh.write(blob)

        # poster_cache so CHUB's matching/upload picks it up
        db.poster.bulk_upsert(
            [
                {
                    "title": title,
                    "normalized_title": normalize_titles(title),
                    "year": year,
                    "tmdb_id": tmdb_id,
                    "tvdb_id": tvdb_id,
                    "imdb_id": imdb_id,
                    "season_number": season_number,
                    "folder": os.path.basename(cfg.output_dir.rstrip("/")),
                    "file": out_path,
                    "style": cfg.style,
                    "priority": cfg.priority,
                    "image_type": "poster",
                    "search_only": 0,
                }
            ]
        )

        db.cl2k_generated.record(
            {
                "kind": kind,
                "tmdb_id": tmdb_id,
                "tvdb_id": tvdb_id,
                "imdb_id": imdb_id,
                "season_number": season_number,
                "title": title,
                "year": year,
                "file": out_path,
                "backdrop_path": backdrop_path,
                "logo_source": logo_source,
                "uploaded": 0,
            }
        )

    upload_error = None
    uploaded = False
    if do_upload:
        from backend.util.cl2k.gdrive_upload import upload_file

        logger.info(
            f"CL2K uploading {filename} to Drive folder {cfg.gdrive_folder_id}…"
        )
        # rclone needs a real on-disk file named with the DAPS filename. Reuse the
        # local save when present; otherwise stage a temp copy just for the upload.
        tmpdir = None
        try:
            if out_path:
                src_path = out_path
            else:
                tmpdir = tempfile.mkdtemp(prefix="cl2k_")
                src_path = os.path.join(tmpdir, filename)
                with open(src_path, "wb") as fh:
                    fh.write(blob)
            upload_file(src_path, cfg.gdrive_folder_id, sync_cfg, logger)
            uploaded = True
            logger.info(f"CL2K uploaded {filename} to Drive")
        except Exception as exc:
            upload_error = str(exc)
            logger.warning(f"CL2K gdrive upload failed for {filename}: {exc}")
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)

        if uploaded:
            if out_path:
                db.cl2k_generated.mark_uploaded(out_path)
            else:
                # Drive-only: no persistent local file, so record provenance keyed
                # on the basename (poster_cache is skipped — nothing local to match).
                db.cl2k_generated.record(
                    {
                        "kind": kind,
                        "tmdb_id": tmdb_id,
                        "tvdb_id": tvdb_id,
                        "imdb_id": imdb_id,
                        "season_number": season_number,
                        "title": title,
                        "year": year,
                        "file": filename,
                        "backdrop_path": backdrop_path,
                        "logo_source": logo_source,
                        "uploaded": 1,
                    }
                )

    # A Drive-only save whose upload failed saved nothing — report it as an error
    # instead of a misleading success.
    if not save_local and not uploaded:
        return {
            "status": "error",
            "reason": f"Drive upload failed: {upload_error}",
            "logo_source": logo_source,
        }

    logger.info(f"CL2K poster generated: {filename} (logo: {logo_source})")
    result = {
        "status": "generated",
        "file": out_path or filename,
        "logo_source": logo_source,
        "saved_local": bool(save_local),
        "uploaded": uploaded,
    }
    # Surface a non-fatal upload failure so the caller can tell the user the file
    # saved locally but didn't reach Drive (generation still succeeds).
    if upload_error:
        result["upload_error"] = upload_error
    return result


def _cover_to_canvas(im):
    """Cover-resize + center-crop a PIL image to the locked CL2K canvas."""
    from PIL import Image

    w, h = geo.CANVAS_W, geo.CANVAS_H
    scale = max(w / im.width, h / im.height)
    # LANCZOS — sharpest resample for the downscale to canvas (matches the Wand
    # renderer); PIL's default is BICUBIC, which is softer on fine detail.
    im = im.resize(
        (round(im.width * scale), round(im.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = (im.width - w) // 2
    top = (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


def _normalize_poster(image_bytes: bytes) -> bytes:
    """Force a finished poster to the locked 1000×1500 canvas (JPEG, CL2K quality).

    A poster that is already a 1000×1500 JPEG passes through untouched (no re-encode,
    so a high-quality source keeps its quality). Anything else — wrong dimensions,
    wrong aspect, or a non-JPEG container — is center-cropped to 2:3, scaled to the
    canvas, and re-encoded at the CL2K quality with NO chroma subsampling (4:4:4),
    matching hand-made posters.
    """
    import io

    from PIL import Image

    im = Image.open(io.BytesIO(image_bytes))
    correct_size = (im.width, im.height) == (geo.CANVAS_W, geo.CANVAS_H)
    if correct_size and (im.format or "").upper() == "JPEG":
        return image_bytes
    im = im.convert("RGB")
    if not correct_size:
        im = _cover_to_canvas(im)
    buf = io.BytesIO()
    im.save(
        buf,
        format="JPEG",
        quality=geo.OUTPUT_QUALITY,
        subsampling=0,
        progressive=geo.JPEG_PROGRESSIVE,
        icc_profile=color.srgb_icc_bytes(),
    )
    return buf.getvalue()


def save_finished_poster(
    *,
    db: ChubDB,
    full_config,
    logger,
    kind: str,
    title: str,
    tmdb_id: int,
    image_bytes: bytes,
    year: Optional[int] = None,
    tvdb_id: Optional[int] = None,
    imdb_id: Optional[str] = None,
    season_number: Optional[int] = None,
    logo_source: str = "upload",
    add_border: bool = True,
    logo_bytes: Optional[bytes] = None,
    save_local: bool = True,
    upload_gdrive: Optional[bool] = None,
) -> Dict[str, Any]:
    """File a pre-made poster (no rendering) into the selected destinations.

    Used by the manual finished-poster upload and the G-Drive .psd source (both
    supply a complete poster). The image is forced to the locked 1000×1500 canvas
    (cropped if needed), named per DAPS, and registered so the rest of CHUB picks
    it up. When ``logo_bytes`` is given (a TMDB/fanart/custom clear logo), it is
    composited at the locked CL2K baseline first, with the same whitening/sizing a
    fresh render uses. ``add_border`` (default True, per the DAPS rule) composites
    the default 26px white frame; uncheck it for a poster that already has the
    required border. ``save_local`` / ``upload_gdrive`` choose the destination(s).
    """
    cfg = full_config.cl2k_maker
    kind = (kind or "").lower()
    if kind not in _VALID_KINDS:
        return {"status": "error", "reason": f"invalid kind {kind!r}"}
    if save_local and not cfg.output_dir:
        return {"status": "error", "reason": "cl2k_maker.output_dir is not configured"}
    blob = _normalize_poster(image_bytes)
    if logo_bytes:
        from backend.util.cl2k.renderer import overlay_logo

        blob = overlay_logo(
            blob,
            logo_bytes,
            kind=kind,
            logo_max_width=cfg.logo_max_width,
            whiten=cfg.whiten_logo,
        )
    if add_border:
        from backend.util.cl2k.renderer import apply_border

        blob = apply_border(blob)
    return _persist_poster(
        db,
        cfg,
        logger,
        sync_cfg=full_config.sync_gdrive,
        blob=blob,
        kind=kind,
        title=title,
        year=year,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        season_number=season_number,
        backdrop_path=None,
        logo_source=logo_source,
        save_local=save_local,
        upload_gdrive=upload_gdrive,
    )


def fanart_images(
    full_config,
    db: ChubDB,
    logger,
    *,
    kind: str,
    tmdb_id: int,
    tvdb_id: Optional[int] = None,
    imdb_id: Optional[str] = None,
    season_number: Optional[int] = None,
) -> Dict[str, Optional[str]]:
    """Return fanart.tv ``{logo, background}`` URLs for the art picker (None on miss)."""
    cfg = full_config.cl2k_maker
    lang = cfg.language or "en"
    try:
        asset_type = "movie" if kind in ("movie", "collection") else "show"
        client = FanartClient(full_config.fanart, db, logger)
        res = client.get_images(
            {
                "asset_type": asset_type,
                "tmdb_id": tmdb_id,
                "tvdb_id": tvdb_id,
                "imdb_id": imdb_id,
                "season_number": season_number,
            },
            language=lang,
        )
        res = res or {}
        return {"logo": res.get("logo"), "background": res.get("background")}
    except Exception as exc:
        logger.debug(f"fanart image lookup failed: {exc}")
        return {"logo": None, "background": None}


def retext_poster(
    *,
    db: ChubDB,
    full_config,
    logger,
    image_bytes: bytes,
    mask_bytes: Optional[bytes] = None,
    apply_ai: bool = False,
    prompt: Optional[str] = None,
    label_text: str = "",
    text_y_frac: Optional[float] = None,
    save: bool = False,
    kind: str = "movie",
    title: str = "",
    tmdb_id: int = 0,
    year: Optional[int] = None,
    tvdb_id: Optional[int] = None,
    imdb_id: Optional[str] = None,
    season_number: Optional[int] = None,
    add_border: bool = True,
    save_local: bool = True,
    upload_gdrive: Optional[bool] = None,
):
    """Re-text a finished poster: AI-erase the brushed old text, then draw a new
    CL2K-style label (e.g. swap a season year).

    AI handles only the *erase* (reliable); the new label is drawn deterministically
    in the CL2K font, so it's always crisp. Returns JPEG bytes when ``save`` is
    False (preview); otherwise files it via :func:`save_finished_poster` and
    returns that result dict. ``text_y_frac`` (0..1) places the label vertically
    (defaults to the CL2K season-label position). ``add_border`` (default True, per
    the DAPS rule) composites the default 26px white frame onto both the preview and
    the saved file; uncheck it for a poster that already has the required border.
    """
    from backend.util.cl2k.renderer import apply_border, overlay_label

    cfg = full_config.cl2k_maker
    img = _normalize_poster(image_bytes)
    if apply_ai and mask_bytes:
        img = text_removal.remove_text(
            img, config=cfg, mask_bytes=mask_bytes, prompt=prompt, logger=logger
        )
    if label_text:
        center_y = None
        if text_y_frac is not None:
            center_y = int(max(0.0, min(1.0, text_y_frac)) * geo.CANVAS_H)
        img = overlay_label(img, label_text, center_y=center_y)
    if add_border:
        img = apply_border(img)
    if not save:
        return img
    # The border is already composited above, so don't add it again on save.
    return save_finished_poster(
        db=db,
        full_config=full_config,
        logger=logger,
        kind=kind,
        title=title,
        tmdb_id=tmdb_id,
        year=year,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        season_number=season_number,
        image_bytes=img,
        logo_source="retext",
        add_border=False,
        save_local=save_local,
        upload_gdrive=upload_gdrive,
    )


def generate_seasons(
    *,
    db: ChubDB,
    full_config,
    logger,
    tmdb_id: int,
    title: str,
    seasons,
    year: Optional[int] = None,
    tvdb_id: Optional[int] = None,
    imdb_id: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Generate CL2K season posters for each number in ``seasons``.

    Each season reuses the show's existing backdrop (via generate_for_item's
    season-reuse path) and only changes the season number.
    """
    results = []
    for n in seasons:
        results.append(
            generate_for_item(
                db=db,
                full_config=full_config,
                logger=logger,
                kind="season",
                title=title,
                tmdb_id=tmdb_id,
                year=year,
                tvdb_id=tvdb_id,
                imdb_id=imdb_id,
                season_number=int(n),
                force=force,
            )
        )
    return {"results": results}


def psd_for_item(
    *,
    db: ChubDB,
    full_config,
    logger,
    kind: str,
    title: str,
    tmdb_id: int,
    backdrop_path: Optional[str] = None,
    logo_path: Optional[str] = None,
    season_text: str = "",
) -> Optional[bytes]:
    """Resolve art and return a layered CL2K poster as PSD bytes (for Photopea)."""
    from backend.util.cl2k.psd_export import export_psd

    cfg = full_config.cl2k_maker
    lang = cfg.language or "en"
    tmdb = TMDBClient(full_config.tmdb, db, logger)
    if backdrop_path is None or logo_path is None:
        images = tmdb.list_images(tmdb_id, kind, languages=lang) or {}
        sel = image_fetch.select_cl2k_inputs(images, lang=lang)
        backdrop_path = backdrop_path or sel.get("backdrop")
        logo_path = logo_path or sel.get("logo")
    if not backdrop_path:
        return None
    backdrop_bytes = image_fetch.download(backdrop_path)
    logo_bytes = image_fetch.download(logo_path) if logo_path else None
    return export_psd(
        backdrop_bytes=backdrop_bytes,
        kind=kind,
        logo_bytes=logo_bytes,
        title=title,
        season_text=season_text,
        logo_max_width=cfg.logo_max_width,
        whiten=cfg.whiten_logo,
    )


class Cl2kMaker(ChubModule):
    """Batch CL2K poster generation over the media library.

    On-demand single-poster generation goes through the API, which calls
    :func:`generate_for_item` directly. This run() is the scheduled/manual batch:
    it walks media_cache for matched movies/shows lacking a CL2K poster and
    generates one for each (honouring the duplicate guard).
    """

    def __init__(self, logger: Optional[Logger] = None) -> None:
        super().__init__(logger=logger)

    def run(self, manifest: Optional[dict] = None) -> None:
        cfg = self.config
        if not cfg.enabled:
            self.logger.info("cl2k_maker is disabled; skipping batch run.")
            return
        if not cfg.output_dir:
            self.logger.error("cl2k_maker.output_dir is not configured; aborting.")
            return

        with ChubDB(logger=self.logger) as db:
            rows = db.media.get_all()
            candidates = [
                r
                for r in rows
                if r.get("asset_type") in _BATCH_KINDS
                and r.get("tmdb_id")
                and r.get("matched")
            ]
            total = len(candidates)
            self.logger.info(f"CL2K batch: {total} matched movie/show candidates")
            generated = skipped = failed = 0
            for idx, media in enumerate(candidates, 1):
                if self.is_cancelled():
                    self.logger.info("CL2K batch cancelled.")
                    break
                try:
                    result = generate_for_item(
                        db=db,
                        full_config=self.full_config,
                        logger=self.logger,
                        kind=media["asset_type"],
                        title=media.get("title", ""),
                        tmdb_id=media.get("tmdb_id"),
                        year=media.get("year"),
                        tvdb_id=media.get("tvdb_id"),
                        imdb_id=media.get("imdb_id"),
                    )
                    status = result.get("status")
                    if status == "generated":
                        generated += 1
                    elif status == "skipped":
                        skipped += 1
                    else:
                        failed += 1
                except Exception as exc:
                    failed += 1
                    self.logger.warning(
                        f"CL2K generation failed for {media.get('title')}: {exc}"
                    )
                if total:
                    self._report_progress(int(idx / total * 100))

            self.logger.info(
                f"CL2K batch done: {generated} generated, {skipped} skipped, "
                f"{failed} failed"
            )
