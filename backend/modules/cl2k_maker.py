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
from backend.util.cl2k import renderer
from backend.util.cl2k.renderer import logo_is_usable, render_cl2k
from backend.util.cl2k.tmdb_art import list_images
from backend.util.database import ChubDB
from backend.util.database.cl2k_generated import cl2k_generated_for
from backend.util.fanart import FanartClient
from backend.util.logger import Logger
from backend.util.normalization import normalize_titles
from backend.util.tmdb import TMDBClient

_VALID_KINDS = ("movie", "show", "collection", "season")
_BATCH_KINDS = ("movie", "show")  # media_cache asset_types we batch over

# Prompt for the "extend" framing's AI outpaint. The model must *continue the
# existing scene downward* — never invent text, logos, or new subjects (those would
# clash with the CL2K logo/label drawn on top).
_EXTEND_PROMPT = (
    "Naturally extend and continue this image downward to fill the empty lower area, "
    "matching the existing background, colours, lighting and grain. Do not add any "
    "text, logos, watermarks, borders, or new people or objects."
)


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


def _backfill_title_year(
    full_config,
    db,
    logger,
    *,
    kind: str,
    tmdb_id: Optional[int],
    title: str,
    year: Optional[int],
    tvdb_id: Optional[int] = None,
    imdb_id: Optional[str] = None,
) -> Tuple[str, Optional[int]]:
    """Fill a blank title/year from TMDB before naming/rendering.

    Items added by id paste or the Edit-IDs panel arrive with no title (the UI
    only resolves the ids), which would reduce the DAPS filename to bare id tags
    (``{tmdb-N}.jpg``) and draw an empty text-wordmark fallback. When the title is
    blank we resolve a usable TMDB id in order — the supplied ``tmdb_id``, else the
    ``tvdb_id``, else the ``imdb_id`` (TVDB/IMDB matched via
    :meth:`find_tmdb_id`) — then read the canonical title/year from
    :meth:`get_details`. A TVDB/IMDB-only title with no TMDB entry keeps whatever
    the user typed in Edit IDs (worst case: bare id tags). Best-effort and cached;
    a transient TMDB failure leaves the originals untouched. Collections carry
    their own title and are skipped.
    """
    if kind not in ("movie", "show", "season"):
        return title, year
    if (title or "").strip():
        return title, year
    mt = "movie" if kind == "movie" else "tv"
    try:
        tmdb = TMDBClient(full_config.tmdb, db, logger)
        # Resolve a usable tmdb id, falling back TVDB → IMDB when none is given.
        resolved = tmdb_id or None
        if not resolved and tvdb_id:
            resolved = tmdb.find_tmdb_id(str(tvdb_id), "tvdb_id", mt)
        if not resolved and imdb_id:
            resolved = tmdb.find_tmdb_id(str(imdb_id), "imdb_id", mt)
        if resolved:
            details = tmdb.get_details(resolved, mt)
            if details:
                title = details.get("title") or title
                if year is None:
                    year = details.get("year")
    except Exception as exc:  # never block a save on a metadata lookup
        logger.warning(f"cl2k: title backfill failed (tmdb={tmdb_id}): {exc}")
    return title, year


# CL2K season bands spell the number out ("SEASON ONE", not "SEASON 1"), matching
# the template convention. Year-numbered seasons stay as digits, though — Formula 1
# "Season 2026" reads "SEASON 2026", not "SEASON TWO THOUSAND…". A real season count
# never reaches four digits, so anything >= 1000 is treated as a year and kept as
# digits (which also serves as the always-produce-a-label fallback).
_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = (
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)


def _number_to_words(n: int) -> str:
    """Cardinal number as English words: 1 -> 'one', 21 -> 'twenty-one'."""
    if not isinstance(n, int) or n < 0 or n >= 1000:
        return str(n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")
    hundreds, rem = divmod(n, 100)
    return f"{_ONES[hundreds]} hundred" + (f" {_number_to_words(rem)}" if rem else "")


def season_band_text(season_number: int) -> str:
    """The CL2K season band label for a season number. Season 0 is the Specials
    season — "Specials" (matching the `- Specials` filename in naming.py), not
    "Season 0". Other seasons spell the number out per the template ("SEASON ONE",
    not "SEASON 1"); year-numbered seasons stay as digits (see _number_to_words).
    The renderer uppercases this."""
    return (
        "Specials"
        if season_number == 0
        else f"Season {_number_to_words(season_number)}"
    )


def _resolve_default_art(
    tmdb,
    tmdb_id: int,
    kind: str,
    lang: str,
    backdrop_path: Optional[str],
    logo_path: Optional[str],
    *,
    need_backdrop: bool = True,
    need_logo: bool = True,
) -> Tuple[Optional[str], Optional[str]]:
    """Fill a default backdrop/logo path from TMDB for whichever is still unset.

    The ONE place CL2K auto-picks art, shared by the render path and the PSD export
    so they can never drift to different pictures. A caller that already holds
    uploaded bytes for one input passes ``need_*=False`` to leave it alone. A single
    list_images call covers both. Returns the (possibly filled) ``(backdrop, logo)``.
    """
    if (need_backdrop and backdrop_path is None) or (need_logo and logo_path is None):
        images = list_images(tmdb, tmdb_id, kind, languages=lang) or {}
        sel = image_fetch.select_cl2k_inputs(images, lang=lang)
        if need_backdrop and backdrop_path is None:
            backdrop_path = sel.get("backdrop")
        if need_logo and logo_path is None:
            logo_path = sel.get("logo")
    return backdrop_path, logo_path


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
    fit_mode: str = "cover",
    crop: Optional[Tuple[float, float, float, float]] = None,
    v_pos: float = 0.0,
    zoom: float = 1.0,
    band_label: str = "",
    logo_scale: float = 1.0,
    logo_y_offset: int = 0,
    logo_flip_bytes: Optional[bytes] = None,  # B/W touch-up regions (mask PNG)
    whiten: Optional[bool] = None,  # None = module config (whiten_logo)
    invert: bool = False,  # plate logo -> clearlogo (white->transparent, black->white)
    allow_ai_extend: bool = True,
    place_logo: bool = True,
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
        backdrop_path = cl2k_generated_for(db).get_backdrop_for(tmdb_id)

    # Was the logo auto-sourced (no upload, no chosen path)? Captured BEFORE
    # resolution because the small-logo drop below applies only to auto picks —
    # a user's explicit choice is always honoured.
    logo_auto_sourced = custom_logo_bytes is None and logo_path is None

    # Fill a default backdrop/logo from TMDB for anything still unset. Uploaded
    # bytes (manual-handoff backdrop, custom logo) mean "don't auto-resolve this".
    backdrop_path, logo_path = _resolve_default_art(
        tmdb,
        tmdb_id,
        kind,
        lang,
        backdrop_path,
        logo_path,
        need_backdrop=backdrop_bytes is None,
        need_logo=custom_logo_bytes is None,
    )

    if backdrop_bytes is None:
        if not backdrop_path:
            return None, {
                "reason": "no textless backdrop available",
                "logo_source": "none",
            }
        backdrop_bytes = image_fetch.download(backdrop_path)

    # EXTEND framing: keep the subjects full-size (fit to width, top-anchored) and
    # AI-outpaint the empty bottom band — the artist's "extend the bottom, crop the
    # wasted top" trick. Falls back to the free edge-extend fit when no AI provider
    # is configured (or the photo already fills the canvas, so there's nothing to
    # extend). The fill happens here, before the gradient/logo, so the AI only sees
    # the backdrop; the resulting canvas is already 1000×1500, so it renders as a
    # straight cover (identity).
    if fit_mode == "extend":
        canvas_bytes, extend_mask = renderer.fit_extend_canvas(
            backdrop_bytes, crop, zoom=zoom, v_pos=v_pos
        )
        # AI runs only on a real generate (allow_ai_extend) AND when a provider is
        # configured. Previews (allow_ai_extend=False) and provider-less renders fall
        # back to the free edge-extend fit, so we never spend AI on every preview.
        if extend_mask is not None and allow_ai_extend and text_removal.is_enabled(cfg):
            backdrop_bytes = text_removal.remove_text(
                canvas_bytes,
                config=cfg,
                mask_bytes=extend_mask,
                prompt=_EXTEND_PROMPT,
                logger=logger,
            )
            fit_mode, crop = "cover", None
        else:
            if extend_mask is not None and logger:
                reason = (
                    "preview" if not allow_ai_extend else "no AI provider configured"
                )
                logger.info(
                    f"cl2k: extend — {reason}; using the free edge-extend fit instead"
                )
            fit_mode = "fit"

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

    # CL2K rule: a clear logo too small to render crisply at the ~600px box is
    # worse than drawn title text. Reject low-res logos the maker chose ITSELF
    # (the auto TMDB/fanart fallback, ``need_logo``) so render_cl2k's title-text
    # fallback takes over. A logo the user picked in the art picker — like a
    # custom upload — is their explicit choice and is kept as-is: the preview
    # always shows it, so dropping it on save was a silent surprise (the small
    # "The Tiny Chef Show" wordmarks are the canonical case). They can size it
    # with the logo_scale slider if it's soft.
    if (
        logo_bytes
        and logo_auto_sourced
        and logo_source in ("tmdb", "fanart")
        and not logo_is_usable(logo_bytes)
    ):
        logger.debug(
            f"cl2k: {logo_source} logo too small for the logo box — using title text"
        )
        logo_bytes = None
        logo_source = "text" if cfg.text_logo_fallback else "none"

    if kind == "season" and not season_text and season_number is not None:
        season_text = season_band_text(season_number)

    blob = render_cl2k(
        backdrop_bytes=backdrop_bytes,
        kind=kind,
        logo_bytes=logo_bytes,
        title=title if (cfg.text_logo_fallback or logo_bytes) else "",
        season_text=season_text,
        logo_scale=logo_scale,
        logo_y_offset=logo_y_offset,
        logo_flip_bytes=logo_flip_bytes,
        whiten=cfg.whiten_logo if whiten is None else whiten,
        invert=invert,
        focus_x=focus_x,
        focus_y=focus_y,
        fit_mode=fit_mode,
        crop=crop,
        v_pos=v_pos,
        zoom=zoom,
        band_label=band_label,
        place_logo=place_logo,
        text_logo_stroke=cfg.text_logo_stroke,
    )
    return blob, {"backdrop_path": backdrop_path, "logo_source": logo_source}


def render_preview(db: ChubDB, full_config, logger, **kwargs) -> Optional[bytes]:
    """Render a CL2K poster to JPEG bytes WITHOUT saving (live preview).

    Previews never run the AI outpaint (``extend`` falls back to the free
    edge-extend fit) so a live preview is fast and free; the AI fill is applied
    only on a real generate.
    """
    kwargs.setdefault("allow_ai_extend", False)
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
    fit_mode: str = "cover",
    crop: Optional[Tuple[float, float, float, float]] = None,
    v_pos: float = 0.0,
    zoom: float = 1.0,
    band_label: str = "",
    logo_scale: float = 1.0,
    logo_y_offset: int = 0,
    logo_flip_bytes: Optional[bytes] = None,  # B/W touch-up regions (mask PNG)
    whiten: Optional[bool] = None,  # None = module config (whiten_logo)
    invert: bool = False,  # plate logo -> clearlogo (white->transparent, black->white)
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
    title, year = _backfill_title_year(
        full_config,
        db,
        logger,
        kind=kind,
        tmdb_id=tmdb_id,
        title=title,
        year=year,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
    )
    # output_dir is only required when actually saving locally; a Drive-only save
    # uploads from a temp copy and never touches output_dir.
    if save_local and not cfg.output_dir:
        return {"status": "error", "reason": "cl2k_maker.output_dir is not configured"}

    if (
        cfg.skip_existing
        and not force
        and cl2k_generated_for(db).exists_for(kind, tmdb_id, season_number)
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
        fit_mode=fit_mode,
        crop=crop,
        v_pos=v_pos,
        zoom=zoom,
        band_label=band_label,
        logo_scale=logo_scale,
        logo_y_offset=logo_y_offset,
        logo_flip_bytes=logo_flip_bytes,
        whiten=whiten,
        invert=invert,
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


def generate_square_art(
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
    backdrop_path: Optional[str] = None,
    backdrop_bytes: Optional[bytes] = None,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    fit_mode: str = "cover",
    zoom: float = 1.0,
    season_number: Optional[int] = None,
    save_local: bool = True,
    upload_gdrive: Optional[bool] = None,
) -> Dict[str, Any]:
    """Render + file 1:1 square art (``- SquareArt.jpg``) for a media item.

    Plain cropped artwork (no logo/gradient), filed into poster_cache as
    ``squareart`` so asset_renamerr applies it to Plex (uploadSquareArt). Always
    overwrites — a deliberate manual action. ``season_number`` files the art for
    one season of a show (``… - Season NN - SquareArt.jpg``; plexapi seasons
    accept square art) instead of the show itself.
    """
    cfg = full_config.cl2k_maker
    kind = (kind or "").lower()
    if kind not in _VALID_KINDS:
        return {"status": "error", "reason": f"invalid kind {kind!r}"}
    if season_number is not None and kind == "show":
        kind = "season"  # season-suffixed naming; backfill/lookup stays TV-side
    title, year = _backfill_title_year(
        full_config,
        db,
        logger,
        kind=kind,
        tmdb_id=tmdb_id,
        title=title,
        year=year,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
    )
    if save_local and not cfg.output_dir:
        return {"status": "error", "reason": "cl2k_maker.output_dir is not configured"}
    if backdrop_bytes is None:
        if not backdrop_path:
            return {"status": "error", "reason": "no source art selected"}
        backdrop_bytes = image_fetch.download(backdrop_path)
    blob = renderer.render_square_art(
        backdrop_bytes=backdrop_bytes,
        focus_x=focus_x,
        focus_y=focus_y,
        fit_mode=fit_mode,
        zoom=zoom,
    )
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
        backdrop_path=backdrop_path,
        logo_source="squareart",
        save_local=save_local,
        upload_gdrive=upload_gdrive,
        image_type="squareart",
        asset_suffix=" - SquareArt",
        ext=".jpg",
    )


def generate_background_art(
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
    backdrop_path: Optional[str] = None,
    backdrop_bytes: Optional[bytes] = None,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    fit_mode: str = "cover",
    zoom: float = 1.0,
    resolution: str = "1080p",
    season_number: Optional[int] = None,
    save_local: bool = True,
    upload_gdrive: Optional[bool] = None,
) -> Dict[str, Any]:
    """Render + file 16:9 background art (``- Background.jpg``) for a media item.

    Plex background art per its recommended dimensions: ``resolution`` ``"1080p"``
    = 1920x1080, ``"4k"`` = 3840x2160. Plain framed artwork (no logo/gradient),
    filed into poster_cache as ``background`` so asset_renamerr applies it to
    Plex (uploadArt) / Kometa. Always overwrites — a deliberate manual action.
    ``season_number`` files the art for one season of a show
    (``… - Season NN - Background.jpg``; Plex seasons take background art and
    Kometa reads ``Season##_background``) instead of the show itself.
    """
    cfg = full_config.cl2k_maker
    kind = (kind or "").lower()
    if kind not in _VALID_KINDS:
        return {"status": "error", "reason": f"invalid kind {kind!r}"}
    if season_number is not None and kind == "show":
        kind = "season"  # season-suffixed naming; backfill/lookup stays TV-side
    title, year = _backfill_title_year(
        full_config,
        db,
        logger,
        kind=kind,
        tmdb_id=tmdb_id,
        title=title,
        year=year,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
    )
    if save_local and not cfg.output_dir:
        return {"status": "error", "reason": "cl2k_maker.output_dir is not configured"}
    if backdrop_bytes is None:
        if not backdrop_path:
            return {"status": "error", "reason": "no source art selected"}
        backdrop_bytes = image_fetch.download(backdrop_path)
    width, height = (3840, 2160) if (resolution or "").lower() == "4k" else (1920, 1080)
    blob = renderer.render_framed_art(
        backdrop_bytes=backdrop_bytes,
        width=width,
        height=height,
        focus_x=focus_x,
        focus_y=focus_y,
        fit_mode=fit_mode,
        zoom=zoom,
    )
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
        backdrop_path=backdrop_path,
        logo_source="background",
        save_local=save_local,
        upload_gdrive=upload_gdrive,
        image_type="background",
        asset_suffix=" - Background",
        ext=".jpg",
    )


def generate_logo_asset(
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
    logo_path: Optional[str] = None,
    logo_bytes: Optional[bytes] = None,
    whiten: bool = False,
    invert: bool = False,  # plate logo -> clearlogo (white->transparent, black->white)
    flip_mask_bytes: Optional[bytes] = None,  # B/W touch-up regions (mask PNG)
    save_local: bool = True,
    upload_gdrive: Optional[bool] = None,
) -> Dict[str, Any]:
    """File a clear logo as its own ``- Logo.png`` asset (applied via uploadLogo).

    ``whiten`` exports the CL2K-whitened logo; otherwise the original (colored)
    clear logo, trimmed. Filed separately from any square art or poster.
    """
    cfg = full_config.cl2k_maker
    kind = (kind or "").lower()
    if kind not in _VALID_KINDS:
        return {"status": "error", "reason": f"invalid kind {kind!r}"}
    title, year = _backfill_title_year(
        full_config,
        db,
        logger,
        kind=kind,
        tmdb_id=tmdb_id,
        title=title,
        year=year,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
    )
    if save_local and not cfg.output_dir:
        return {"status": "error", "reason": "cl2k_maker.output_dir is not configured"}
    raw = logo_bytes
    if raw is None and logo_path:
        raw = image_fetch.download(logo_path)
    if not raw:
        return {"status": "error", "reason": "no logo selected"}
    png, _w, _h = renderer.process_logo(
        raw, whiten=whiten, flip_mask_bytes=flip_mask_bytes, invert=invert
    )
    return _persist_poster(
        db,
        cfg,
        logger,
        sync_cfg=full_config.sync_gdrive,
        blob=png,
        kind=kind,
        title=title,
        year=year,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        season_number=None,
        backdrop_path=None,
        logo_source="logo-white" if whiten else "logo",
        save_local=save_local,
        upload_gdrive=upload_gdrive,
        image_type="logo",
        asset_suffix=" - Logo",
        ext=".png",
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
    image_type: str = "poster",
    asset_suffix: str = "",
    ext: Optional[str] = None,
) -> Dict[str, Any]:
    """Write a finished poster to the selected destinations + provenance.

    ``image_type`` / ``asset_suffix`` / ``ext`` let this same sink file the
    additional-asset types the maker produces — ``squareart`` (``- SquareArt.jpg``)
    and ``logo`` (``- Logo.png``) — into poster_cache so asset_renamerr applies
    them. Only true posters are written to the cl2k_generated provenance table (its
    exists_for() gate is poster-only, so an asset row must not appear there).

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
        ext=ext or geo.OUTPUT_EXT,
        asset_suffix=asset_suffix,
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
        # Logged before the DB writes below so a failure there still leaves a
        # record that the file exists on disk.
        logger.info(f"CL2K saved {filename} to {cfg.output_dir}")

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
                    "image_type": image_type,
                    "search_only": 0,
                }
            ]
        )

        # Provenance / "already generated" tracking is poster-only — an asset
        # (squareart / logo) shares the media's tmdb_id and must not make the batch
        # poster run think a poster exists for it.
        if image_type == "poster":
            cl2k_generated_for(db).record(
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
                cl2k_generated_for(db).mark_uploaded(out_path)
            elif image_type == "poster":
                # Drive-only: no persistent local file, so record provenance keyed
                # on the basename (poster_cache is skipped — nothing local to match).
                # Assets (squareart / logo) stay out of the poster provenance table.
                cl2k_generated_for(db).record(
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
    logo_scale: float = 1.0,
    logo_y_offset: int = 0,
    whiten: Optional[bool] = None,  # None = module config (whiten_logo)
    invert: bool = False,  # plate logo -> clearlogo (white->transparent, black->white)
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
    title, year = _backfill_title_year(
        full_config,
        db,
        logger,
        kind=kind,
        tmdb_id=tmdb_id,
        title=title,
        year=year,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
    )
    if save_local and not cfg.output_dir:
        return {"status": "error", "reason": "cl2k_maker.output_dir is not configured"}
    blob = _normalize_poster(image_bytes)
    if logo_bytes:
        from backend.util.cl2k.renderer import overlay_logo

        blob = overlay_logo(
            blob,
            logo_bytes,
            kind=kind,
            logo_scale=logo_scale,
            logo_y_offset=logo_y_offset,
            whiten=cfg.whiten_logo if whiten is None else whiten,
            invert=invert,
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
    keep_size: bool = False,
    save_local: bool = True,
    upload_gdrive: Optional[bool] = None,
):
    """Re-text a finished poster: AI-erase the brushed old text, then draw a new
    CL2K-style label (e.g. swap a season year).

    ``keep_size`` skips the 1000×1500 normalize on the preview path so the
    AI-erased image keeps its original dimensions — used when the result feeds
    the full CL2K render (whose framing must see the uncropped image) instead of
    being saved as-is. The save path always normalizes (save_finished_poster).

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
    img = image_bytes if keep_size else _normalize_poster(image_bytes)
    if apply_ai and mask_bytes:
        img = text_removal.remove_text(
            img, config=cfg, mask_bytes=mask_bytes, prompt=prompt, logger=logger
        )
    # An explicit label_text (a banner override or a free-text title) wins; otherwise
    # a season draws its SEASON-N band, derived here so season_band_text is the ONE
    # source of truth for the on-poster label (the full render path uses it too) —
    # no caller, frontend included, re-spells the number.
    label = label_text
    if not label and kind == "season" and season_number is not None:
        label = season_band_text(season_number)
    if label:
        center_y = None
        if text_y_frac is not None:
            center_y = int(max(0.0, min(1.0, text_y_frac)) * geo.CANVAS_H)
        img = overlay_label(img, label, center_y=center_y)
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
    fit_mode: str = "cover",
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    crop: Optional[Tuple[float, float, float, float]] = None,
    v_pos: float = 0.0,
    zoom: float = 1.0,
    logo_scale: float = 1.0,
    logo_y_offset: int = 0,
    whiten: Optional[bool] = None,  # None = module config (whiten_logo)
    invert: bool = False,  # plate logo -> clearlogo (white->transparent, black->white)
    force: bool = False,
    backdrop_path: Optional[str] = None,
    backdrop_bytes: Optional[bytes] = None,
    logo_path: Optional[str] = None,
    custom_logo_bytes: Optional[bytes] = None,
    save_local: bool = True,
    upload_gdrive: Optional[bool] = None,
    progress_cb=None,
) -> Dict[str, Any]:
    """Generate CL2K season posters for each number in ``seasons``.

    The backdrop and logo the user built in the preview are passed through to
    EVERY season (``backdrop_path``/``backdrop_bytes`` + ``logo_path``/
    ``custom_logo_bytes``), so each season is composed from the same art rather
    than re-resolving a fresh auto-pick server-side. When no backdrop is supplied
    the season-reuse path in :func:`generate_for_item` still falls back to the
    show's most-recent stored backdrop. The framing (``fit_mode`` / ``focus`` /
    ``crop`` / ``logo_scale``) is carried from the show poster so every season is
    composed identically.

    ``progress_cb`` (optional) is invoked with each season's result dict as it
    completes, so a background runner can report live progress. A failure on one
    season is captured as an ``error`` result and never aborts the batch.
    """
    results = []
    for n in seasons:
        try:
            res = generate_for_item(
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
                backdrop_path=backdrop_path,
                backdrop_bytes=backdrop_bytes,
                logo_path=logo_path,
                custom_logo_bytes=custom_logo_bytes,
                fit_mode=fit_mode,
                focus_x=focus_x,
                focus_y=focus_y,
                crop=crop,
                v_pos=v_pos,
                zoom=zoom,
                logo_scale=logo_scale,
                logo_y_offset=logo_y_offset,
                whiten=whiten,
                invert=invert,
                force=force,
                save_local=save_local,
                upload_gdrive=upload_gdrive,
            )
        except Exception as exc:  # one bad season must not sink the rest
            logger.error(f"cl2k: season {n} generation failed: {exc}", exc_info=True)
            res = {"status": "error", "reason": str(exc)}
        entry = {"season": int(n), **res}
        results.append(entry)
        if progress_cb is not None:
            try:
                progress_cb(entry)
            except Exception:  # progress reporting is best-effort
                pass
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
    season_number: Optional[int] = None,
    band_label: str = "",
    logo_scale: float = 1.0,
    logo_y_offset: int = 0,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    fit_mode: str = "cover",
    crop: Optional[Tuple[float, float, float, float]] = None,
    v_pos: float = 0.0,
    zoom: float = 1.0,
    whiten: Optional[bool] = None,  # None = module config (whiten_logo)
    invert: bool = False,  # plate logo -> clearlogo (white->transparent, black->white)
) -> Optional[bytes]:
    """Resolve art and return a layered CL2K poster as PSD bytes (for Photopea).

    The backdrop is framed via the renderer's own fit/cover/v_pos machinery so
    the PSD's POSTER layer is pixel-identical to what /preview and /generate
    show for the same framing knobs. A season's SEASON-N band is derived from
    ``season_number`` (via season_band_text — same rule as the render path), and a
    ``band_label`` override wins over it, so the PSD carries the same label the
    flattened poster would, unless an explicit ``season_text`` is given.
    """
    from backend.util.cl2k.psd_export import export_psd

    cfg = full_config.cl2k_maker
    lang = cfg.language or "en"
    if not season_text and kind == "season" and season_number is not None:
        season_text = season_band_text(season_number)
    tmdb = TMDBClient(full_config.tmdb, db, logger)
    backdrop_path, logo_path = _resolve_default_art(
        tmdb, tmdb_id, kind, lang, backdrop_path, logo_path
    )
    if not backdrop_path:
        return None
    backdrop_bytes = renderer.frame_backdrop(
        backdrop_bytes=image_fetch.download(backdrop_path),
        focus_x=focus_x,
        focus_y=focus_y,
        fit_mode=fit_mode,
        crop=crop,
        v_pos=v_pos,
        zoom=zoom,
    )
    logo_bytes = image_fetch.download(logo_path) if logo_path else None
    return export_psd(
        backdrop_bytes=backdrop_bytes,
        kind=kind,
        logo_bytes=logo_bytes,
        title=title,
        season_text=season_text,
        band_label=band_label,
        logo_scale=logo_scale,
        logo_y_offset=logo_y_offset,
        whiten=cfg.whiten_logo if whiten is None else whiten,
        invert=invert,
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
                        f"CL2K generation failed for {media.get('title')}: {exc}",
                        exc_info=True,
                    )
                if total:
                    self._report_progress(int(idx / total * 100))

            self.logger.info(
                f"CL2K batch done: {generated} generated, {skipped} skipped, "
                f"{failed} failed"
            )
