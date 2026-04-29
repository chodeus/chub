"""
Border Replacerr preview API.

Powers the Border Replacerr preview page in the UI. Generates side-by-side
"original | bordered" composite JPGs for a small mix of the user's actual
matched media so the user can sanity-check border colors and per-holiday
palettes without committing a full module run.

Endpoints:
    GET  /api/border-replacerr/preview/options
        List the holidays available in the user's config so the frontend
        dropdown can populate without a duplicate config fetch.

    POST /api/border-replacerr/preview
        Generate up to 6 composites (2 movies + 2 series + 2 collections,
        falling back across kinds when one is empty). Accepts ``count`` and
        ``holiday`` (default | current | <holiday name>) query params. The
        actual cropping/bordering reuses BorderReplacerr.replace_borders()
        so the preview is faithful to a real run.

    GET  /api/border-replacerr/preview/file/{token}.jpg
        Serve the bytes for a token returned by the POST endpoint. Tokens
        are opaque uuid4 hex strings; the backing file lives in a single
        well-known temp directory and is wiped on each new POST.
"""

import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image

from backend.api.utils import error, get_logger, ok
from backend.modules.border_replacerr import BorderReplacerr
from backend.util.config import ChubConfig, load_config
from backend.util.database import ChubDB

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


def _config() -> Any:
    return load_config()


def _get_config() -> Any:
    return load_config()


def _resolve_palette(
    config: ChubConfig, choice: str
) -> tuple[List[tuple[int, int, int]], Optional[str]]:
    """Resolve the user's holiday choice to an RGB palette + active label.

    Returns ``(palette, active_holiday_name)``. ``palette`` is empty when
    "default" is requested and no default colors are configured — callers
    should treat that as "remove the border" rather than "abort".
    """
    br = BorderReplacerr()
    cfg = config.border_replacerr

    if choice == "current":
        # Mirror what a real run would do: respect the existing holiday
        # parser including year-crossover rules.
        with ChubDB() as db:
            status = br.get_holiday_status(db=db)
        return list(status.get("border_colors") or []), status.get("active_holiday")

    if choice and choice != "default":
        # Match by name against configured holidays.
        for holiday in cfg.holidays or []:
            if holiday.name == choice:
                hex_colors = list(getattr(holiday, "colors", None) or cfg.border_colors or [])
                rgb = [br.convert_to_rgb(c) for c in hex_colors]
                return rgb, holiday.name

    # default / unknown choice → fall through to configured defaults
    rgb = [br.convert_to_rgb(c) for c in (cfg.border_colors or [])]
    return rgb, None


def _sample_assets(db: ChubDB, count: int) -> list[dict]:
    """Pick a mix of matched media + collections for the preview.

    Default split is 2 movies + 2 series + 2 collections (when count=6),
    scaled proportionally for other counts. If a kind is short, the
    remaining slots are filled from the other kinds so we still hit the
    requested total when possible.
    """
    media = [
        row
        for row in db.media.get_all()
        if row.get("matched") == 1 and row.get("original_file")
    ]
    movies = [row for row in media if row.get("asset_type") == "movie"]
    series = [row for row in media if row.get("asset_type") != "movie"]
    collections = [
        row for row in db.collection.get_all() if row.get("matched") == 1 and row.get("original_file")
    ]

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
        + [(row, "collection") for row in collections[max(0, count - 2 * target_each):]]
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
) -> None:
    """Write a 2000x1500 side-by-side ``original | bordered`` composite.

    When ``color`` is None the right side shows the cropped+resized result
    that BorderReplacerr would produce in "remove" mode.
    """
    br = BorderReplacerr()

    # The bordered side is whatever a real run would write — reuse the
    # module's own helper so the preview can never drift from production.
    bordered_tmp = PREVIEW_DIR / f"_bordered_{uuid.uuid4().hex}.jpg"
    if color is not None:
        br.replace_borders(original_file, str(bordered_tmp), color, border_width)
    else:
        br.remove_borders(original_file, str(bordered_tmp), border_width)

    try:
        with Image.open(original_file) as left_src:
            left = left_src.convert("RGB").resize((1000, 1500), Image.Resampling.LANCZOS)
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
    for holiday in cfg.holidays or []:
        options.append({"value": holiday.name, "label": holiday.name})
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
async def generate_preview(
    count: int = Query(6, ge=1, le=24),
    holiday: str = Query("current"),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    config = load_config()
    cfg = config.border_replacerr

    palette, active_holiday = _resolve_palette(config, holiday)
    border_width = int(cfg.border_width or 26)

    # Wipe previous previews so /tmp doesn't grow unboundedly across refreshes.
    if PREVIEW_DIR.exists():
        try:
            shutil.rmtree(PREVIEW_DIR)
        except OSError:
            pass
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with ChubDB(logger=logger) as db:
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
            },
        )

    previews = []
    for index, asset in enumerate(assets):
        token = uuid.uuid4().hex
        output_path = PREVIEW_DIR / f"{token}.jpg"

        # Cycle the palette so the user sees how each configured color lands
        # on different artwork. Empty palette → preview the "remove" path.
        color: Optional[tuple[int, int, int]] = (
            palette[index % len(palette)] if palette else None
        )

        try:
            _render_composite(
                asset["original_file"],
                output_path,
                color,
                border_width,
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
        previews.append(
            {
                "token": token,
                "title": asset.get("title") or "(untitled)",
                "kind": asset.get("_kind", "media"),
                "season_number": asset.get("season_number"),
                "color": color_hex,
            }
        )

    return ok(
        f"Generated {len(previews)} preview(s)",
        {
            "previews": previews,
            "active_holiday": active_holiday,
            "border_width": border_width,
            "palette_size": len(palette),
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
        return error("Invalid preview token", code="BORDER_PREVIEW_BAD_TOKEN", status_code=404)

    file_path = PREVIEW_DIR / f"{token}.jpg"
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
