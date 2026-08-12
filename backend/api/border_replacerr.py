"""
Border Replacerr API.

Powers the Border Replacerr page in the UI. Two concerns live here:

Preview composites (existing)
    GET  /api/border-replacerr/preview/options
    POST /api/border-replacerr/preview
    GET  /api/border-replacerr/preview/file/{token}.jpg
        Side-by-side "original | bordered" JPGs for a small mix of the
        user's matched media so palettes can be sanity-checked before a
        full run.

Border manager (added when the page absorbed border colour + holiday
border editing — see the rebuild that moved visual config off the
Module Settings form)
    GET  /api/border-replacerr/presets
        The canonical holiday preset catalogue (name + schedule + colors).
    GET  /api/border-replacerr/borders/{holiday}
        List bundled (assets/borders/<folder>) + user (/config/borders/
        <folder>) variant names for a holiday so the picker can render
        thumbnails.
    GET  /api/border-replacerr/borders/{holiday}/{source}/{variant}.png
        Serve a resized thumbnail of one variant. Source is ``bundled``
        or ``user``; the on-disk PNG is resized to ~300x450 and cached
        in /tmp/chub_border_thumbs/.
"""

import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image

from backend.api.utils import error, get_database, get_logger, ok
from backend.modules.border_replacerr import BorderReplacerr
from backend.util.config import ChubConfig, load_config
from backend.util.database import ChubDB
from backend.util.helper import get_config_dir

# Bundled border PNGs live next to the SVG sources after the Docker build
# rasterizes them (see scripts/rasterize_borders.py + deploy/docker/Dockerfile).
_BUNDLED_BORDERS_DIR = Path(__file__).resolve().parents[1] / "assets" / "borders"

# Thumbnail cache. Wiping on container restart is fine — thumbs are
# deterministic per (folder, source, name) and re-generated cheaply.
_THUMB_DIR = Path(tempfile.gettempdir()) / "chub_border_thumbs"
_THUMB_SIZE = (300, 450)

router = APIRouter(
    prefix="/api/border-replacerr",
    tags=["Border Replacerr"],
    responses={
        500: {"description": "Internal server error"},
    },
)


# Single shared preview directory. Wiped at the start of each POST so the
# token-→file mapping never accumulates stale entries across runs. /tmp is
# fine — previews are throwaway by design and the user only looks at them
# right after triggering a refresh from the UI.
PREVIEW_DIR = Path(tempfile.gettempdir()) / "chub_border_preview"


# Holiday presets — the canonical catalogue. The frontend used to maintain
# its own copy in PresetsField.jsx; that file now reads this list via
# GET /api/border-replacerr/presets so the two sides can't drift.
_HOLIDAY_PRESETS: list[dict] = [
    {
        "name": "🎆 New Year's Day",
        "schedule": "range(12/30-01/02)",
        "colors": ["#00BFFF", "#FFD700"],
    },
    {
        "name": "🧧 Lunar New Year",
        "schedule": "range(01/20-02/20)",
        "colors": ["#C8102E", "#FFD700"],
    },
    {
        "name": "💘 Valentine's Day",
        "schedule": "range(02/05-02/15)",
        "colors": ["#D41F3A", "#FFC0CB"],
    },
    {
        "name": "🍀 St. Patrick's Day",
        "schedule": "range(03/14-03/18)",
        "colors": ["#00A36C", "#FFD700"],
    },
    {
        "name": "🐣 Easter",
        "schedule": "range(03/31-04/02)",
        "colors": ["#FFB6C1", "#87CEFA", "#98FB98"],
    },
    {
        "name": "🌸 Mother's Day",
        "schedule": "range(05/10-05/15)",
        "colors": ["#FF69B4", "#FFDAB9"],
    },
    {
        "name": "👨‍👧‍👦 Father's Day",
        "schedule": "range(06/15-06/20)",
        "colors": ["#1E90FF", "#4682B4"],
    },
    {
        "name": "🏳️‍🌈 Pride",
        "schedule": "range(06/01-06/30)",
        "colors": ["#E40303", "#FF8C00", "#FFED00", "#008026", "#004CFF", "#732982"],
    },
    {
        "name": "🗽 Independence Day",
        "schedule": "range(07/01-07/05)",
        "colors": ["#FF0000", "#FFFFFF", "#0000FF"],
    },
    {
        "name": "🧹 Labor Day",
        "schedule": "range(09/01-09/07)",
        "colors": ["#FFD700", "#4682B4"],
    },
    {
        "name": "🎃 Halloween",
        "schedule": "range(10/01-10/31)",
        "colors": ["#FFA500", "#000000"],
    },
    {
        "name": "🦃 Thanksgiving",
        "schedule": "range(11/01-11/30)",
        "colors": ["#FFA500", "#8B4513"],
    },
    {
        "name": "🎄 Christmas",
        "schedule": "range(12/01-12/31)",
        "colors": ["#FF0000", "#00FF00"],
    },
]


def _get_config() -> Any:
    return load_config()


def _resolve_palette(
    config: ChubConfig, choice: str, db: ChubDB
) -> tuple[List[tuple[int, int, int]], List[str], Optional[str]]:
    """Resolve the user's holiday choice to its render inputs.

    Returns ``(palette, border_paths, active_holiday_name)``. When
    ``border_paths`` is non-empty the caller should render via the
    image-composite path; otherwise it falls back to ``palette``. Either
    can be empty — empty palette + empty border_paths means "remove the
    border" rather than "abort".
    """
    br = BorderReplacerr()
    cfg = config.border_replacerr

    if choice == "current":
        # Mirror what a real run would do: respect the existing holiday
        # parser including year-crossover rules.
        status = br.get_holiday_status(db=db)
        return (
            list(status.get("border_colors") or []),
            list(status.get("border_paths") or []),
            status.get("active_holiday"),
        )

    if choice and choice != "default":
        # Match by name against configured holidays first — saved entries win
        # over presets so users who customized a preset's colors see their
        # version, not the preset default.
        for holiday in cfg.holidays or []:
            if holiday.name == choice:
                hex_colors = list(
                    getattr(holiday, "colors", None) or cfg.border_colors or []
                )
                rgb = [br.convert_to_rgb(c) for c in hex_colors]
                names = list(getattr(holiday, "borders", None) or [])
                borders = br._resolve_border_paths(holiday.name, names)
                return rgb, borders, holiday.name

        # Fall back to the built-in preset catalogue so the user can preview
        # any holiday palette without first saving it to their config.
        for preset in _HOLIDAY_PRESETS:
            if preset["name"] == choice:
                rgb = [br.convert_to_rgb(c) for c in preset["colors"]]
                return rgb, [], preset["name"]

    # default / unknown choice → fall through to configured defaults
    rgb = [br.convert_to_rgb(c) for c in (cfg.border_colors or [])]
    return rgb, [], None


def _sample_assets(db: ChubDB, count: int) -> list[dict]:
    """Pick a mix of matched media + collections for the preview.

    Default split is 2 movies + 2 series + 2 collections (when count=6),
    scaled proportionally for other counts. If a kind is short, the
    remaining slots are filled from the other kinds so we still hit the
    requested total when possible.
    """
    # Bounded in SQL — the preview needs at most `count` (≤24) rows per kind,
    # never the whole table, which is 10k+ rows on large libraries. Each kind
    # gets its own bounded pool so one dominant type can't starve the others.
    pool_limit = max(count * 2, 24)
    movies = db.media.get_matched_with_files(pool_limit, asset_type="movie")
    series = db.media.get_matched_with_files(
        pool_limit, asset_type="movie", invert_type=True
    )
    collections = db.collection.get_matched_with_files(pool_limit)

    target_each = max(1, count // 3)
    picks: list[dict] = []

    def take(pool: list, kind: str, want: int) -> list[dict]:
        out = []
        for row in pool[:want]:
            row = dict(row)
            row["_kind"] = kind
            out.append(row)
        return out

    picks += take(movies, "movie", target_each)
    picks += take(series, "series", target_each)
    picks += take(collections, "collection", count - len(picks))

    # Fill any shortage from whichever pool has spare entries.
    leftovers = (
        [(row, "movie") for row in movies[target_each:]]
        + [(row, "series") for row in series[target_each:]]
        + [
            (row, "collection")
            for row in collections[max(0, count - 2 * target_each) :]
        ]
    )
    while len(picks) < count and leftovers:
        row, kind = leftovers.pop(0)
        row = dict(row)
        row["_kind"] = kind
        picks.append(row)

    return picks[:count]


def _render_composite(
    original_file: str,
    output_path: Path,
    color: Optional[tuple[int, int, int]],
    border_width: int,
    border_image: Optional[str] = None,
) -> None:
    """Write a 2000x1500 side-by-side ``original | bordered`` composite.

    Precedence: ``border_image`` (PNG path) > ``color`` (RGB tuple) >
    None (remove-border mode). Reusing BorderReplacerr's own helpers
    keeps the preview faithful to a real run.
    """
    br = BorderReplacerr()

    # The bordered side is whatever a real run would write — reuse the
    # module's own helper so the preview can never drift from production.
    bordered_tmp = PREVIEW_DIR / f"_bordered_{uuid.uuid4().hex}.jpg"
    if border_image is not None:
        br.replace_borders_with_image(original_file, str(bordered_tmp), border_image)
    elif color is not None:
        br.replace_borders(original_file, str(bordered_tmp), color, border_width)
    else:
        br.remove_borders(original_file, str(bordered_tmp), border_width)

    try:
        with Image.open(original_file) as left_src:
            left = left_src.convert("RGB").resize(
                (1000, 1500), Image.Resampling.LANCZOS
            )
        with Image.open(bordered_tmp) as right_src:
            right = right_src.convert("RGB")
            # bordered_tmp is already 1000x1500 from BorderReplacerr, but
            # be defensive in case future code changes that.
            if right.size != (1000, 1500):
                right = right.resize((1000, 1500), Image.Resampling.LANCZOS)

        composite = Image.new("RGB", (2000, 1500), (0, 0, 0))
        composite.paste(left, (0, 0))
        composite.paste(right, (1000, 0))
        composite.save(output_path, "JPEG", quality=85, optimize=True)
    finally:
        if bordered_tmp.exists():
            try:
                bordered_tmp.unlink()
            except OSError:
                # Best-effort cleanup of the per-asset scratch file. A failure
                # here (locked file, race with another preview run) is not
                # worth surfacing — the next /preview POST wipes PREVIEW_DIR
                # wholesale anyway.
                pass


@router.get(
    "/preview/options",
    summary="Border preview dropdown options",
    description=(
        "Return holiday choices for the Border Replacerr preview page. "
        "The frontend uses this to populate the holiday dropdown so the user "
        "can preview any configured holiday's palette."
    ),
)
async def preview_options(
    config: ChubConfig = Depends(_get_config),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    cfg = config.border_replacerr
    options = [
        {"value": "default", "label": "Default border colors"},
        {"value": "current", "label": "Current state (live holiday resolver)"},
    ]

    # Saved holidays first, marked as such so the user can tell which entries
    # already live in their config vs. which are preview-only suggestions.
    saved_names: set[str] = set()
    for holiday in cfg.holidays or []:
        saved_names.add(holiday.name)
        options.append({"value": holiday.name, "label": f"{holiday.name} (saved)"})

    # Built-in preset catalogue — same set the holidays picker uses. Skipping
    # entries the user already saved avoids dupes in the dropdown.
    for preset in _HOLIDAY_PRESETS:
        if preset["name"] in saved_names:
            continue
        options.append({"value": preset["name"], "label": preset["name"]})

    return ok("Preview options retrieved", {"options": options})


@router.post(
    "/preview",
    summary="Generate border previews",
    description=(
        "Generate side-by-side composite JPGs (original | bordered) for a "
        "small mix of the user's matched media. Returns metadata + opaque "
        "tokens; fetch each composite via /api/border-replacerr/preview/file/{token}.jpg."
    ),
)
def generate_preview(
    count: int = Query(6, ge=1, le=24),
    holiday: str = Query("current"),
    db: ChubDB = Depends(get_database),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    config = load_config()
    cfg = config.border_replacerr

    try:
        palette, border_paths, active_holiday = _resolve_palette(config, holiday, db)
    except (ValueError, KeyError, AttributeError) as e:
        # A malformed holiday/border config must yield a clean 4xx, not an
        # unhandled 500 on the preview endpoint.
        logger.error(f"Invalid border/holiday configuration: {e}")
        return error(
            "Invalid border/holiday configuration",
            code="BORDER_CONFIG_INVALID",
            status_code=400,
        )
    border_width = int(cfg.border_width or 26)

    # Wipe previous previews so /tmp doesn't grow unboundedly across refreshes.
    if PREVIEW_DIR.exists():
        try:
            shutil.rmtree(PREVIEW_DIR)
        except OSError:
            # If wipe fails (permissions, race with another worker), continue
            # — mkdir+exist_ok=True below will reuse the directory and the
            # new previews will land alongside any leftovers. /tmp gets wiped
            # on container restart so worst case is a few stale files.
            pass
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    try:
        assets = _sample_assets(db, count)
    except Exception as exc:  # pragma: no cover — DB read shouldn't fail in practice
        logger.error(f"Failed to sample assets for border preview: {exc}")
        return error(
            "Failed to sample assets from the database",
            code="BORDER_PREVIEW_DB_ERROR",
            status_code=500,
        )

    if not assets:
        return ok(
            "No matched assets available for preview",
            {
                "previews": [],
                "active_holiday": active_holiday,
                "border_width": border_width,
                "palette_size": len(palette),
                "border_count": len(border_paths),
                "mode": "image" if border_paths else ("color" if palette else "remove"),
            },
        )

    previews = []
    mode = "image" if border_paths else ("color" if palette else "remove")
    for index, asset in enumerate(assets):
        token = uuid.uuid4().hex
        output_path = PREVIEW_DIR / f"{token}.jpg"

        # Image-mode cycles through resolved PNG paths; color-mode cycles
        # through the palette; otherwise we preview the "remove" path.
        border_image: Optional[str] = (
            border_paths[index % len(border_paths)] if border_paths else None
        )
        color: Optional[tuple[int, int, int]] = (
            palette[index % len(palette)] if (palette and not border_paths) else None
        )

        try:
            _render_composite(
                asset["original_file"],
                output_path,
                color,
                border_width,
                border_image=border_image,
            )
        except Exception as exc:
            logger.warning(
                "Skipped border preview for %s (%s): %s",
                asset.get("title"),
                asset.get("original_file"),
                exc,
            )
            continue

        color_hex = (
            "#" + "".join(f"{c:02x}" for c in color) if color is not None else None
        )
        border_name = Path(border_image).stem if border_image else None
        previews.append(
            {
                "token": token,
                "title": asset.get("title") or "(untitled)",
                "kind": asset.get("_kind", "media"),
                "season_number": asset.get("season_number"),
                "color": color_hex,
                "border": border_name,
            }
        )

    return ok(
        f"Generated {len(previews)} preview(s)",
        {
            "previews": previews,
            "active_holiday": active_holiday,
            "border_width": border_width,
            "palette_size": len(palette),
            "border_count": len(border_paths),
            "mode": mode,
        },
    )


@router.get(
    "/preview/file/{token}.jpg",
    summary="Serve a generated preview composite",
    description="Returns the JPG bytes for a token previously issued by POST /preview.",
    responses={
        200: {"content": {"image/jpeg": {}}},
        404: {"description": "Preview not found (token expired or unknown)"},
    },
)
async def preview_file(token: str, logger: Any = Depends(get_logger)):
    # Token is uuid4 hex so anything else is rejected upfront — keeps the
    # endpoint from doubling as a generic /tmp peeker.
    if not token or len(token) != 32 or not all(c in "0123456789abcdef" for c in token):
        return error(
            "Invalid preview token", code="BORDER_PREVIEW_BAD_TOKEN", status_code=404
        )

    # Defense in depth: resolve the candidate path and confirm it lives
    # inside PREVIEW_DIR before serving. The hex-token validator above
    # already rules out traversal, but the explicit containment check
    # makes the safety property obvious to static analysis (CodeQL
    # py/path-injection) and survives any future loosening of the
    # validator.
    preview_root = PREVIEW_DIR.resolve()
    file_path = (PREVIEW_DIR / f"{token}.jpg").resolve()
    if not file_path.is_relative_to(preview_root):
        return error(
            "Invalid preview path", code="BORDER_PREVIEW_BAD_TOKEN", status_code=404
        )

    if not file_path.exists():
        return error(
            "Preview not found (it may have expired)",
            code="BORDER_PREVIEW_NOT_FOUND",
            status_code=404,
        )

    return FileResponse(
        path=str(file_path),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


# ─── Border manager: presets + thumbnail catalogue ──────────────────────


def _safe_holiday_folder(holiday_name: str) -> Optional[str]:
    """Resolve a holiday display name to its assets/borders/ folder name.

    Returns None for inputs that don't map to a known folder. The folder
    string from ``BorderReplacerr._holiday_folder`` is alphanumeric-only,
    so anything coming back here is safe to use as a path segment.
    """
    folder = BorderReplacerr()._holiday_folder(holiday_name)
    if not folder:
        return None
    # Belt-and-braces: enforce the documented invariant (alphanumeric, no
    # dots/slashes) before the caller stitches it into a filesystem path.
    if not folder.isalnum():
        return None
    return folder


def _list_variants_in(directory: Path) -> List[str]:
    """Return sorted variant names (PNG stems) under ``directory``.

    Missing directories return an empty list so the caller doesn't need
    to special-case fresh installs or holidays without bundled art.
    """
    if not directory.is_dir():
        return []
    names = sorted(p.stem for p in directory.glob("*.png") if p.is_file())
    return names


@router.get(
    "/presets",
    summary="Holiday preset catalogue",
    description=(
        "Return the canonical list of holiday presets (name, schedule, "
        "colors) so the frontend doesn't have to keep a parallel copy."
    ),
)
async def list_presets() -> JSONResponse:
    return ok("Holiday presets retrieved", {"presets": _HOLIDAY_PRESETS})


@router.get(
    "/borders/{holiday}",
    summary="List bundled + user border variants for a holiday",
    description=(
        "Return the variant names available for the given holiday. "
        "``bundled`` entries come from the shipped assets; ``user`` entries "
        "come from /config/borders/<folder>/. Each entry can be fetched as "
        "a thumbnail via /borders/{holiday}/{source}/{name}.png."
    ),
)
async def list_borders(holiday: str) -> JSONResponse:
    folder = _safe_holiday_folder(holiday)
    if not folder:
        return ok(
            "No bundled folder for that holiday",
            {"holiday": holiday, "folder": None, "bundled": [], "user": []},
        )

    bundled_dir = _BUNDLED_BORDERS_DIR / folder
    user_dir = Path(get_config_dir()) / "borders" / folder
    return ok(
        "Border variants retrieved",
        {
            "holiday": holiday,
            "folder": folder,
            "bundled": _list_variants_in(bundled_dir),
            "user": _list_variants_in(user_dir),
        },
    )


def _resolve_variant_source_dir(source: str, folder: str) -> Optional[Path]:
    if source == "bundled":
        return _BUNDLED_BORDERS_DIR / folder
    if source == "user":
        return Path(get_config_dir()) / "borders" / folder
    return None


@router.get(
    "/borders/{holiday}/{source}/{variant}.png",
    summary="Serve a border variant thumbnail",
    description=(
        "Return a ~300x450 PNG thumbnail of the requested border variant. "
        "Thumbnails are cached in /tmp/chub_border_thumbs/ — a container "
        "restart wipes them; they regenerate on next request."
    ),
    responses={
        200: {"content": {"image/png": {}}},
        404: {"description": "Variant not found"},
    },
)
def border_thumbnail(
    holiday: str,
    source: str,
    variant: str,
    logger: Any = Depends(get_logger),
):
    folder = _safe_holiday_folder(holiday)
    if not folder:
        return error(
            "Unknown holiday", code="BORDER_THUMB_UNKNOWN_HOLIDAY", status_code=404
        )

    source_dir = _resolve_variant_source_dir(source, folder)
    if source_dir is None:
        return error("Unknown source", code="BORDER_THUMB_BAD_SOURCE", status_code=404)

    # Variant comes from URL; allow only alphanumerics, dashes, dots, and
    # underscores so a stem like "v1" or "user_one" works but "../foo"
    # cannot. Stem-strip again as belt-and-braces.
    stem = Path(variant).stem
    if not stem or not all(c.isalnum() or c in "-_." for c in stem):
        return error(
            "Invalid variant name", code="BORDER_THUMB_BAD_VARIANT", status_code=404
        )

    source_root = source_dir.resolve()
    full_png = (source_dir / f"{stem}.png").resolve()
    if not full_png.is_relative_to(source_root) or not full_png.is_file():
        return error(
            "Variant not found", code="BORDER_THUMB_NOT_FOUND", status_code=404
        )

    cache_dir = _THUMB_DIR / folder
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{source}_{stem}.png"

    # Regenerate when the source PNG is newer than the cached thumbnail
    # (catches user edits dropped into /config/borders/...). Bundled PNGs
    # are static after build, so this normally hits the cache.
    needs_render = (
        not cache_path.is_file()
        or cache_path.stat().st_mtime < full_png.stat().st_mtime
    )
    if needs_render:
        try:
            with Image.open(full_png) as img:
                img = img.convert("RGBA")
                img.thumbnail(_THUMB_SIZE, Image.Resampling.LANCZOS)
                img.save(cache_path, "PNG", optimize=True)
        except Exception as exc:
            logger.warning("Failed to render border thumbnail %s: %s", full_png, exc)
            return error(
                "Failed to render thumbnail",
                code="BORDER_THUMB_RENDER_FAILED",
                status_code=500,
            )

    return FileResponse(
        path=str(cache_path),
        media_type="image/png",
        # Thumbnails are deterministic per (folder, source, variant) until
        # the source PNG changes; a long browser cache is safe.
        headers={"Cache-Control": "public, max-age=86400"},
    )
