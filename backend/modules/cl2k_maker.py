# modules/cl2k_maker.py

import os
from typing import Any, Dict, Optional, Tuple

from backend.util.base_module import ChubModule
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
    tvdb_id: Optional[int] = None,
    imdb_id: Optional[str] = None,
    mask_bytes: Optional[bytes] = None,
    backdrop_bytes: Optional[bytes] = None,
    apply_ai: bool = False,
) -> Tuple[Optional[bytes], Dict[str, Any]]:
    """Resolve art (textless backdrop + logo: TMDB->fanart->text) and render.

    Returns ``(jpeg_bytes, info)``; ``jpeg_bytes`` is None with ``info['reason']``
    set when no textless backdrop is available. Shared by the preview endpoint
    and :func:`generate_for_item`.
    """
    cfg = full_config.cl2k_maker
    lang = cfg.language or "en"
    tmdb = TMDBClient(full_config.tmdb, db, logger)

    # Season reuse: a new season inherits the show's existing backdrop (DAPS:
    # same background across seasons, only the season number changes).
    if kind == "season" and backdrop_path is None and backdrop_bytes is None:
        backdrop_path = db.cl2k_generated.get_backdrop_for(tmdb_id)

    # Resolve a logo (always) and a backdrop path (unless bytes were uploaded
    # for the manual-handoff flow).
    if logo_path is None or (backdrop_bytes is None and backdrop_path is None):
        images = tmdb.list_images(tmdb_id, kind, languages=lang) or {}
        sel = image_fetch.select_cl2k_inputs(images, lang=lang)
        if backdrop_bytes is None:
            backdrop_path = backdrop_path or sel.get("backdrop")
        logo_path = logo_path or sel.get("logo")

    if backdrop_bytes is None:
        if not backdrop_path:
            return None, {"reason": "no textless backdrop available", "logo_source": "none"}
        backdrop_bytes = image_fetch.download(backdrop_path)

    # Only run AI removal when explicitly requested (a brushed mask, or the
    # apply_ai flag for OpenAI's maskless mode) — never on every auto-render.
    if apply_ai or mask_bytes:
        backdrop_bytes = text_removal.remove_text(
            backdrop_bytes, config=cfg, mask_bytes=mask_bytes
        )

    logo_bytes = None
    logo_source = "text" if cfg.text_logo_fallback else "none"
    if logo_path:
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
    mask_bytes: Optional[bytes] = None,
    backdrop_bytes: Optional[bytes] = None,
    apply_ai: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """Render + name + write to source_dir + upsert poster_cache + provenance.

    Shared core for the API (on-demand) and run() (batch). Returns
    ``{status, file?, reason?, logo_source?}``.
    """
    cfg = full_config.cl2k_maker
    kind = (kind or "").lower()
    if kind not in _VALID_KINDS:
        return {"status": "error", "reason": f"invalid kind {kind!r}"}
    if not cfg.output_dir:
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
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        mask_bytes=mask_bytes,
        backdrop_bytes=backdrop_bytes,
        apply_ai=apply_ai,
    )
    if blob is None:
        return {"status": "skipped", "reason": info.get("reason", "render failed")}
    logo_source = info.get("logo_source", "none")

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
            "backdrop_path": info.get("backdrop_path"),
            "logo_source": logo_source,
            "uploaded": 0,
        }
    )

    if cfg.upload_to_gdrive and cfg.gdrive_folder_id:
        from backend.util.cl2k.gdrive_upload import upload_file

        try:
            upload_file(out_path, cfg.gdrive_folder_id, cfg.gdrive_sa_location, logger)
            db.cl2k_generated.mark_uploaded(out_path)
        except Exception as exc:
            logger.warning(f"CL2K gdrive upload failed for {filename}: {exc}")

    logger.info(f"CL2K poster generated: {filename} (logo: {logo_source})")
    return {"status": "generated", "file": out_path, "logo_source": logo_source}


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
