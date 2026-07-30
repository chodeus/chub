# modules/cl2k_maker.py

import os
import shutil
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

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
from backend.util.normalization import normalize_titles
from backend.util.tmdb import TMDBClient

_VALID_KINDS = ("movie", "show", "collection", "season")

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
    fit_mode: str = "cover",
    crop: Optional[Tuple[float, float, float, float]] = None,
    v_pos: float = 0.0,
    zoom: float = 1.0,
    band_label: str = "",
    logo_scale: float = 1.0,
    logo_y_offset: int = 0,
    logo_flip_bytes: Optional[bytes] = None,  # B/W touch-up regions (mask PNG)
    logo_erase_bytes: Optional[bytes] = None,  # erase regions (mask PNG, white=erase)
    whiten: Optional[bool] = None,  # None = module config (whiten_logo)
    flat_white: bool = False,  # paint the logo a flat pure-white silhouette
    logo_3d: bool = False,  # extruded art -> flat-white lit face; wins over flat_white
    invert: bool = False,  # plate logo -> clearlogo (white->transparent, black->white)
    allow_ai_extend: bool = True,
    place_logo: bool = True,
) -> Tuple[Optional[bytes], Dict[str, Any]]:
    """
    Resolve the artwork inputs and render a CL2K poster.
    
    Explicit logo bytes or a selected logo path take precedence over automatically
    resolved artwork. Missing logos may fall back to fanart artwork or a generated
    text wordmark. Season renders can reuse the stored show backdrop, and season
    labels are derived from the season number when needed.
    
    Parameters:
        kind (str): Poster type, such as ``movie``, ``show``, ``collection``, or
            ``season``.
        season_number (Optional[int]): Season number used for backdrop reuse and
            automatic season labeling.
        season_text (str): Label to render for a season poster.
        backdrop_path (Optional[str]): Selected backdrop asset path.
        logo_path (Optional[str]): Selected logo asset path.
        custom_logo_bytes (Optional[bytes]): Uploaded logo data that takes
            precedence over other logo sources.
        apply_ai (bool): Whether to apply AI text removal without requiring a mask.
        fit_mode (str): Backdrop fitting mode, including the AI-assisted
            ``"extend"`` mode.
        mask_bytes (Optional[bytes]): Mask defining regions for AI text removal.
        logo_3d (bool): Whether to render the logo with the 3D logo treatment.
        allow_ai_extend (bool): Whether AI outpainting may be used for ``"extend"``
            fitting.
        place_logo (bool): Whether to place the logo on the rendered poster.
    
    Returns:
        tuple: Rendered JPEG bytes and an information dictionary containing the
        resolved backdrop path and logo source. The image bytes are ``None`` when
        no textless backdrop is available; in that case, the information dictionary
        contains a ``"reason"`` entry.
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
        # AI runs only on a real generate (allow_ai_extend) AND when the provider
        # is fully configured — unavailable_reason(), not is_enabled(): a provider
        # with a missing endpoint/key silently passes the canvas through, and
        # covering that would bake the black band into the saved poster. Previews
        # (allow_ai_extend=False) and unconfigured renders fall back to the free
        # edge-extend fit, so we never spend AI on every preview.
        ai_ready = allow_ai_extend and text_removal.unavailable_reason(cfg) is None
        extended = None
        if extend_mask is not None and ai_ready:
            extended = text_removal.remove_text(
                canvas_bytes,
                config=cfg,
                mask_bytes=extend_mask,
                prompt=_EXTEND_PROMPT,
                logger=logger,
            )
        if extended is not None and extended is not canvas_bytes:
            backdrop_bytes = extended
            # Identity framing, not just "cover": the AI canvas is already
            # CANVAS_W x CANVAS_H with zoom/v_pos baked in by fit_extend_canvas.
            # Re-applying them re-scales the finished image and, for v_pos > 0,
            # crops rows off the top and fades a black band over the fill.
            fit_mode, crop, zoom, v_pos = "cover", None, 1.0, 0.0
        else:
            if extend_mask is not None and logger:
                reason = (
                    "preview"
                    if not allow_ai_extend
                    else (
                        text_removal.unavailable_reason(cfg)
                        or "AI returned the canvas unchanged"
                    )
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
        # Rescue a too-small real logo via the sidecar's super-resolution before
        # surrendering to the typeset wordmark; best-effort — upscale_image
        # returns None on any failure (older sidecar, timeout, misconfig) and we
        # fall back exactly as before.
        rescued = None
        if getattr(cfg, "ai_logo_upscale", True):
            rescued = text_removal.upscale_image(logo_bytes, cfg, logger=logger)
        if rescued and logo_is_usable(rescued):
            logger.debug(
                f"cl2k: {logo_source} logo too small — upscaled via the sidecar"
            )
            logo_bytes = rescued
        else:
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
        logo_erase_bytes=logo_erase_bytes,
        whiten=cfg.whiten_logo if whiten is None else whiten,
        flat_white=flat_white,
        logo_3d=logo_3d,
        invert=invert,
        focus_x=focus_x,
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
    fit_mode: str = "cover",
    crop: Optional[Tuple[float, float, float, float]] = None,
    v_pos: float = 0.0,
    zoom: float = 1.0,
    band_label: str = "",
    logo_scale: float = 1.0,
    logo_y_offset: int = 0,
    logo_flip_bytes: Optional[bytes] = None,  # B/W touch-up regions (mask PNG)
    logo_erase_bytes: Optional[bytes] = None,  # erase regions (mask PNG, white=erase)
    whiten: Optional[bool] = None,  # None = module config (whiten_logo)
    flat_white: bool = False,  # paint the logo a flat pure-white silhouette
    logo_3d: bool = False,  # extruded art -> flat-white lit face; wins over flat_white
    invert: bool = False,  # plate logo -> clearlogo (white->transparent, black->white)
    force: bool = False,
    save_local: bool = True,
    upload_gdrive: Optional[bool] = None,
    defer_upload: Optional[Callable[[Callable[[], None]], None]] = None,
) -> Dict[str, Any]:
    """
    Render a poster for an item and persist it to the configured destinations.
    
    Parameters:
        kind (str): Item type: ``movie``, ``show``, ``collection``, or ``season``.
        force (bool): Whether to generate the poster when an existing result is found.
        save_local (bool): Whether to save the poster to configured local folders.
        upload_gdrive (Optional[bool]): Whether to upload the poster to configured Google Drive folders.
        defer_upload (Optional[Callable]): Callback used to schedule deferred uploads.
    
    Returns:
        Dict[str, Any]: Generation status and, when successful, output file and destination details.
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
        fit_mode=fit_mode,
        crop=crop,
        v_pos=v_pos,
        zoom=zoom,
        band_label=band_label,
        logo_scale=logo_scale,
        logo_y_offset=logo_y_offset,
        logo_flip_bytes=logo_flip_bytes,
        logo_erase_bytes=logo_erase_bytes,
        whiten=whiten,
        flat_white=flat_white,
        logo_3d=logo_3d,
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
        defer_upload=defer_upload,
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
    fit_mode: str = "cover",
    v_pos: float = 0.0,
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
    if backdrop_bytes is None:
        if not backdrop_path:
            return {"status": "error", "reason": "no source art selected"}
        backdrop_bytes = image_fetch.download(backdrop_path)
    blob = renderer.render_square_art(
        backdrop_bytes=backdrop_bytes,
        focus_x=focus_x,
        fit_mode=fit_mode,
        v_pos=v_pos,
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
    fit_mode: str = "cover",
    v_pos: float = 0.0,
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
        fit_mode=fit_mode,
        v_pos=v_pos,
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
    flat_white: bool = False,  # paint the logo a flat pure-white silhouette
    logo_3d: bool = False,  # extruded art -> flat-white lit face; wins over flat_white
    invert: bool = False,  # plate logo -> clearlogo (white->transparent, black->white)
    flip_mask_bytes: Optional[bytes] = None,  # B/W touch-up regions (mask PNG)
    erase_mask_bytes: Optional[bytes] = None,  # erase regions (mask PNG, white=erase)
    save_local: bool = True,
    upload_gdrive: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Save a processed clear logo as a ``- Logo.png`` asset.
    
    The logo is read from ``logo_bytes`` or downloaded from ``logo_path``, then
    optionally whitened, converted to a flat-white or 3D treatment, inverted, and
    adjusted using the supplied touch-up masks.
    
    Parameters:
        kind (str): Poster item type.
        logo_bytes (Optional[bytes]): Logo image data to process directly.
        logo_path (Optional[str]): Image path used when ``logo_bytes`` is not provided.
        flip_mask_bytes (Optional[bytes]): Mask identifying regions to retain or flip.
        erase_mask_bytes (Optional[bytes]): Mask identifying regions to erase.
    
    Returns:
        Dict[str, Any]: Persistence status and details for the generated logo asset.
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
    raw = logo_bytes
    if raw is None and logo_path:
        raw = image_fetch.download(logo_path)
    if not raw:
        return {"status": "error", "reason": "no logo selected"}
    png, _w, _h = renderer.process_logo(
        raw,
        whiten=whiten,
        flat_white=flat_white,
        logo_3d=logo_3d,
        flip_mask_bytes=flip_mask_bytes,
        erase_mask_bytes=erase_mask_bytes,
        invert=invert,
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
        logo_source="logo-white" if (whiten or flat_white or logo_3d) else "logo",
        save_local=save_local,
        upload_gdrive=upload_gdrive,
        image_type="logo",
        asset_suffix=" - Logo",
        ext=".png",
    )


def _local_targets(cfg, image_type: str) -> List[str]:
    """Paths of the configured local folders that claim ``image_type`` (config
    order, deduped, blank paths skipped). Every claimer receives a copy; an
    empty result means the type isn't auto-saved locally."""
    seen, out = set(), []
    for folder in getattr(cfg, "local_folders", None) or []:
        path = (getattr(folder, "path", "") or "").strip()
        if not path or path in seen:
            continue
        if image_type in (getattr(folder, "types", None) or []):
            seen.add(path)
            out.append(path)
    return out


def _drive_targets(cfg, image_type: str) -> List[str]:
    """Folder ids of the configured Drive uploads that claim ``image_type``
    (config order, deduped, blank ids skipped)."""
    seen, out = set(), []
    for drive in getattr(cfg, "gdrive_uploads", None) or []:
        folder_id = (getattr(drive, "folder_id", "") or "").strip()
        if not folder_id or folder_id in seen:
            continue
        if image_type in (getattr(drive, "types", None) or []):
            seen.add(folder_id)
            out.append(folder_id)
    return out


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
    defer_upload: Optional[Callable[[Callable[[], None]], None]] = None,
) -> Dict[str, Any]:
    """Write a finished poster to every claiming save location + provenance.

    ``image_type`` / ``asset_suffix`` / ``ext`` let this same sink file the
    additional-asset types the maker produces — ``squareart`` (``- SquareArt.jpg``)
    and ``logo`` (``- Logo.png``) — into poster_cache so asset_renamerr applies
    them. Only true posters are written to the cl2k_generated provenance table (its
    exists_for() gate is poster-only, so an asset row must not appear there).

    Shared sink for rendered (:func:`generate_for_item`), uploaded-finished
    (:func:`save_finished_poster`) and .psd-flattened posters. ``backdrop_path``
    is None for posters that didn't go through the renderer.

    Routing: the file is written into every ``cfg.local_folders`` entry claiming
    its ``image_type`` (one poster_cache row per copy) and uploaded to every
    claiming ``cfg.gdrive_uploads`` folder. Nothing is mandatory — when no
    location claims the type, nothing is auto-saved and the result carries
    ``not_routed: True`` (the art stays downloadable from the maker page).
    ``save_local=False`` skips the local writes; ``upload_gdrive=False`` skips
    the uploads (``None``/``True`` both mean "upload wherever routed"). An
    upload with no local copy is staged from a temp file and is recorded only in
    provenance, NOT in poster_cache (nothing local for CHUB to match).
    """
    out_dirs = _local_targets(cfg, image_type) if save_local else []
    # Explicit False turns Drive upload off for this save; True and None (the
    # UI/module default) both upload to every configured Drive claiming the type.
    folder_ids = _drive_targets(cfg, image_type) if upload_gdrive is not False else []

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
    # provably impossible for a crafted title to escape the save dirs (path-injection).
    filename = os.path.basename(filename)

    # Nothing claims this type: a valid outcome by design — no auto-save, the
    # caller offers the art as a download instead.
    if not out_dirs and not folder_ids:
        logger.info(
            f"CL2K generated {filename} — no save location claims "
            f"'{image_type}', not auto-saved (downloadable only)"
        )
        return {
            "status": "generated",
            "file": filename,
            "logo_source": logo_source,
            "saved_local": False,
            "uploaded": False,
            "not_routed": True,
        }

    written: List[str] = []
    write_errors: List[str] = []
    for out_dir in out_dirs:
        try:
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, filename)
            with open(out_path, "wb") as fh:
                fh.write(blob)
        except OSError as exc:
            write_errors.append(f"{out_dir}: {exc}")
            logger.warning(f"CL2K local save failed in {out_dir}: {exc}")
            continue
        written.append(out_path)
        # Logged before the DB writes below so a failure there still leaves a
        # record that the file exists on disk.
        logger.info(f"CL2K saved {filename} to {out_dir}")

    if written:
        # poster_cache so CHUB's matching/upload picks it up — one row per copy.
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
                    "folder": os.path.basename(os.path.dirname(out_path).rstrip("/")),
                    "file": out_path,
                    "style": cfg.style,
                    "priority": cfg.priority,
                    "image_type": image_type,
                    "search_only": 0,
                }
                for out_path in written
            ]
        )

        # Provenance / "already generated" tracking is poster-only — an asset
        # (squareart / logo) shares the media's tmdb_id and must not make the batch
        # poster run think a poster exists for it. One row per generation, keyed
        # on the first local copy.
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
                    "file": written[0],
                    "backdrop_path": backdrop_path,
                    "logo_source": logo_source,
                    "uploaded": 0,
                }
            )

    uploaded_folders: List[str] = []
    upload_errors: List[str] = []

    def _run_uploads(reload_config: bool = False) -> None:
        """Upload to every routed Drive folder; deferred runs reload live config."""
        from backend.util.cl2k.gdrive_upload import upload_file

        targets, upload_cfg = folder_ids, sync_cfg
        if reload_config:
            # Deferred runs use current routing/credentials; skip if unreadable.
            try:
                from backend.util.config import load_config

                fresh = load_config()
                targets = _drive_targets(fresh.cl2k_maker, image_type)
                upload_cfg = fresh.sync_gdrive
            except Exception as exc:
                logger.warning(
                    f"CL2K skipped deferred Drive upload for {filename} — "
                    f"could not re-read config: {exc}"
                )
                return
            if not targets:
                logger.info(
                    f"CL2K skipped deferred Drive upload for {filename} — "
                    f"no Drive folder is routed for {image_type} any more"
                )
                return

        # rclone needs a real on-disk file named with the DAPS filename. Reuse a
        # local save when present; otherwise stage a temp copy just for the upload.
        tmpdir = None
        try:
            if written:
                src_path = written[0]
            else:
                tmpdir = tempfile.mkdtemp(prefix="cl2k_")
                src_path = os.path.join(tmpdir, filename)
                with open(src_path, "wb") as fh:
                    fh.write(blob)
            for folder_id in targets:
                logger.info(f"CL2K uploading {filename} to Drive folder {folder_id}…")
                try:
                    upload_file(src_path, folder_id, upload_cfg, logger)
                    uploaded_folders.append(folder_id)
                    logger.info(f"CL2K uploaded {filename} to Drive {folder_id}")
                except Exception as exc:
                    upload_errors.append(f"{folder_id}: {exc}")
                    logger.warning(
                        f"CL2K gdrive upload to {folder_id} failed for {filename}: {exc}"
                    )
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)

        if not uploaded_folders:
            return
        # Provenance is bookkeeping; the poster is already on Drive. Never let it
        # fail the request (inline) or raise inside the task (deferred).
        try:
            if written:
                cl2k_generated_for(db).mark_uploaded(written[0])
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
        except Exception as exc:
            logger.warning(
                f"CL2K uploaded {filename} but could not record provenance: {exc}"
            )

    # Defer only uploads backed by a local copy (rclone outruns the UI timeout).
    deferred_upload = False
    if folder_ids:
        if defer_upload is not None and written:
            defer_upload(lambda: _run_uploads(reload_config=True))
            deferred_upload = True
            logger.info(
                f"CL2K queued Drive upload for {filename} "
                f"({len(folder_ids)} folder(s)) — running after the response"
            )
        else:
            _run_uploads()

    # Nothing landed anywhere => error, not a misleading success. A deferred
    # upload can't be the cause: `written` is non-empty whenever we defer.
    if not written and not uploaded_folders:
        return {
            "status": "error",
            "reason": "; ".join(
                [f"local save failed: {e}" for e in write_errors]
                + [f"Drive upload failed: {e}" for e in upload_errors]
            ),
            "logo_source": logo_source,
        }

    logger.info(f"CL2K poster generated: {filename} (logo: {logo_source})")
    result = {
        "status": "generated",
        "file": written[0] if written else filename,
        "logo_source": logo_source,
        "saved_local": bool(written),
        "saved_paths": written,
        "uploaded": bool(uploaded_folders),
        "uploaded_folders": uploaded_folders,
        # Not yet uploaded, not failed. The provenance row's `uploaded` flag
        # settles it once the background task finishes.
        "upload_pending": deferred_upload,
    }
    # Surface non-fatal failures so the caller can tell the user which targets
    # missed while the generation still succeeded elsewhere.
    if upload_errors:
        result["upload_error"] = "; ".join(upload_errors)
    if write_errors:
        result["save_error"] = "; ".join(write_errors)
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
    flat_white: bool = False,  # paint the logo a flat pure-white silhouette
    logo_3d: bool = False,  # extruded art -> flat-white lit face; wins over flat_white
    invert: bool = False,  # plate logo -> clearlogo (white->transparent, black->white)
    save_local: bool = True,
    upload_gdrive: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Persist a completed poster after normalizing its dimensions and optionally applying a logo and border.
    
    The poster is normalized to the locked 1000×1500 canvas. An optional logo is composited using the configured styling, and the default border is applied unless disabled. The resulting poster is saved locally, uploaded to Google Drive, or both according to the destination options.
    
    Parameters:
        logo_3d (bool): Whether to render the logo with an extruded, lit-face treatment.
        save_local (bool): Whether to save the poster to configured local destinations.
        upload_gdrive (Optional[bool]): Whether to upload the poster to configured Google Drive destinations.
    
    Returns:
        Dict[str, Any]: Persistence status and destination details.
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
            flat_white=flat_white,
            logo_3d=logo_3d,
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
    tmdb_id: Optional[int] = None,
    tvdb_id: Optional[int] = None,
    imdb_id: Optional[str] = None,
    season_number: Optional[int] = None,
) -> Dict[str, Optional[str]]:
    """Return fanart.tv ``{logo, background}`` URLs for the art picker (None on miss).

    A show can resolve from tvdb_id alone (fanart.tv keys shows by TVDB), so
    tmdb_id is optional — a TVDB-only title still gets fanart art."""
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
    crop: Optional[Tuple[float, float, float, float]] = None,
    v_pos: float = 0.0,
    zoom: float = 1.0,
    logo_scale: float = 1.0,
    logo_y_offset: int = 0,
    whiten: Optional[bool] = None,  # None = module config (whiten_logo)
    flat_white: bool = False,  # paint the logo a flat pure-white silhouette
    logo_3d: bool = False,  # extruded art -> flat-white lit face; wins over flat_white
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
    """
    Generate CL2K posters for each season number in `seasons`.
    
    Each poster uses the supplied backdrop, logo, and framing settings. If no
    backdrop is supplied, the show's stored backdrop may be reused. Failures are
    isolated to individual seasons, and progress results are reported through
    `progress_cb` when provided.
    
    Parameters:
        seasons: Season numbers to generate.
        progress_cb: Optional callback invoked with each completed season's result.
    
    Returns:
        A dictionary containing the per-season generation results under `"results"`.
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
                crop=crop,
                v_pos=v_pos,
                zoom=zoom,
                logo_scale=logo_scale,
                logo_y_offset=logo_y_offset,
                whiten=whiten,
                flat_white=flat_white,
                logo_3d=logo_3d,
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
    fit_mode: str = "cover",
    crop: Optional[Tuple[float, float, float, float]] = None,
    v_pos: float = 0.0,
    zoom: float = 1.0,
    whiten: Optional[bool] = None,  # None = module config (whiten_logo)
    flat_white: bool = False,  # paint the logo a flat pure-white silhouette
    logo_3d: bool = False,  # extruded art -> flat-white lit face; wins over flat_white
    invert: bool = False,  # plate logo -> clearlogo (white->transparent, black->white)
) -> Optional[bytes]:
    """Resolve artwork and create a layered CL2K poster in PSD format.
    
    The backdrop uses the specified framing controls, and season text is derived from
    ``season_number`` when no explicit text is provided. Logo styling options,
    including whitening, inversion, and 3D treatment, are applied during export.
    
    Returns:
        Optional[bytes]: PSD bytes, or ``None`` when no backdrop is available.
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
        flat_white=flat_white,
        logo_3d=logo_3d,
        invert=invert,
    )
