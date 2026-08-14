"""
Poster image file operations — the PIL resize/convert/thumbnail work behind
the optimize, thumbnail and download endpoints.

Every function returns plain values so the API layer keeps sole ownership of
HTTP shapes (backend/util never imports backend.api).
"""

import os
from typing import Any, Dict, Optional, Tuple

from backend.util.config import ChubConfig
from backend.util.path_safety import resolve_confined

_PIL_FORMATS = {"jpeg": "JPEG", "jpg": "JPEG", "webp": "WEBP", "png": "PNG"}
_FORMAT_EXTENSIONS = {"JPEG": ".jpg", "WEBP": ".webp", "PNG": ".png"}
_FORMAT_MEDIA_TYPES = {"JPEG": "image/jpeg", "WEBP": "image/webp", "PNG": "image/png"}


def resolve_format(name: Optional[str]) -> Tuple[str, str]:
    """Map a requested format name to its (PIL format, file extension) pair."""
    pil_format = _PIL_FORMATS.get((name or "").lower(), "JPEG")
    return pil_format, _FORMAT_EXTENSIONS.get(pil_format, ".jpg")


def optimize_poster_files(
    db,
    logger,
    config: ChubConfig,
    max_width,
    max_height,
    pil_format,
    target_ext,
    quality,
    mode,
) -> Tuple[str, Dict[str, Any]]:
    """Resize/convert every cached poster in place; returns (message, result data)."""
    from PIL import Image

    # Get all posters from cache
    posters = db.poster.get_all()
    if not posters:
        return "No posters found to optimize", {
            "processed": 0,
            "skipped": 0,
            "failed": 0,
            "bytes_saved": 0,
            "mode": mode,
        }

    processed = 0
    skipped = 0
    failed = 0
    bytes_saved = 0
    details = []

    for poster in posters:
        file_path = poster.get("file", "")
        folder = poster.get("folder", "")
        raw_path = os.path.join(folder, file_path) if folder else file_path

        if not raw_path:
            skipped += 1
            continue

        # A poisoned cache row must never reach the shutil.move/os.remove below.
        real = resolve_confined(raw_path, config)
        if real is None:
            logger.warning(f"Skipping poster outside allowed roots: {raw_path}")
            skipped += 1
            continue

        full_path = str(real)
        if not os.path.isfile(full_path):
            skipped += 1
            continue

        try:
            original_size = os.path.getsize(full_path)

            with Image.open(full_path) as img:
                w, h = img.size
                needs_resize = w > max_width or h > max_height
                needs_convert = not full_path.lower().endswith(target_ext)

                if not needs_resize and not needs_convert:
                    skipped += 1
                    continue

                if mode == "report":
                    details.append(
                        {
                            "file": full_path,
                            "size": original_size,
                            "dimensions": f"{w}x{h}",
                            "needs_resize": needs_resize,
                            "needs_convert": needs_convert,
                        }
                    )
                    processed += 1
                    continue

                # Actually optimize
                if needs_resize:
                    img.thumbnail((max_width, max_height), Image.LANCZOS)

                img = img.convert("RGB") if pil_format in ("JPEG",) else img

                # Save to temp file, then replace
                import tempfile

                with tempfile.NamedTemporaryFile(
                    suffix=target_ext, delete=False, dir=os.path.dirname(full_path)
                ) as tmp:
                    save_kwargs = {"format": pil_format}
                    if pil_format in ("JPEG", "WEBP"):
                        save_kwargs["quality"] = quality
                        save_kwargs["optimize"] = True
                    img.save(tmp.name, **save_kwargs)
                    new_size = os.path.getsize(tmp.name)

                    if new_size < original_size:
                        import shutil

                        # Convert changes the container, so write the new
                        # extension and drop the original — else a .png would
                        # hold JPEG bytes.
                        base, _ = os.path.splitext(full_path)
                        dest_path = base + target_ext if needs_convert else full_path
                        # Don't clobber a different pre-existing file at the
                        # converted extension (e.g. a Kometa .jpg beside a
                        # Plex .png) — leave both, mirror poster_self_heal.
                        if dest_path != full_path and os.path.exists(dest_path):
                            os.unlink(tmp.name)
                            logger.warning(
                                f"optimize target exists, skipped to avoid "
                                f"clobber: {dest_path}"
                            )
                            skipped += 1
                            continue
                        shutil.move(tmp.name, dest_path)
                        if dest_path != full_path:
                            try:
                                db.poster.record_optimized_file(
                                    poster["id"], dest_path
                                )
                            except Exception as ce:
                                # Recovery before the destructive step: with no
                                # row pointing here, dropping the original
                                # would orphan the poster.
                                try:
                                    os.remove(dest_path)
                                except OSError:
                                    pass
                                logger.warning(
                                    f"cache update failed for {full_path}; "
                                    f"kept the original: {ce}"
                                )
                                skipped += 1
                                continue
                            poster["file"] = dest_path
                            if os.path.exists(full_path):
                                os.remove(full_path)
                        bytes_saved += original_size - new_size
                        processed += 1
                    else:
                        os.unlink(tmp.name)
                        skipped += 1

        except Exception as e:
            logger.warning(f"Failed to optimize {full_path}: {e}")
            failed += 1

    saved_mb = round(bytes_saved / (1024 * 1024), 1)
    result_data = {
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "bytes_saved": bytes_saved,
        "mode": mode,
    }
    if mode == "report" and details:
        result_data["candidates"] = details[:100]

    msg = (
        f"Found {processed} posters to optimize"
        if mode == "report"
        else f"Optimized {processed} posters, saved {saved_mb} MB"
    )
    return msg, result_data


def build_thumbnail(source_path: str, poster_id: int, width: int) -> str:
    """Return the cached JPEG thumbnail path for a poster, rendering it when stale."""
    # Cache beside the resolved source so the thumbnail follows the poster.
    thumb_dir = os.path.join(os.path.dirname(source_path), ".thumbnails")
    thumb_path = os.path.join(thumb_dir, f"{poster_id}_w{width}.jpg")

    # Serve from cache if fresh
    if os.path.isfile(thumb_path):
        src_mtime = os.path.getmtime(source_path)
        thumb_mtime = os.path.getmtime(thumb_path)
        if thumb_mtime >= src_mtime:
            return thumb_path

    from PIL import Image

    os.makedirs(thumb_dir, exist_ok=True)
    with Image.open(source_path) as img:
        aspect = img.height / img.width
        target_height = int(width * aspect)
        img.thumbnail((width, target_height), Image.LANCZOS)
        img.convert("RGB").save(thumb_path, "JPEG", quality=60, optimize=True)

    return thumb_path


def transcode_poster(
    source_path: str,
    size: Optional[int] = None,
    image_format: Optional[str] = None,
    quality: Optional[int] = None,
) -> Tuple[str, str, str]:
    """Write a resized/converted copy to a temp file; returns (path, media type, ext)."""
    from PIL import Image
    import tempfile

    pil_format, target_ext = resolve_format(image_format)

    with Image.open(source_path) as img:
        if size:
            img.thumbnail((size, size), Image.LANCZOS)
        if pil_format in ("JPEG",):
            img = img.convert("RGB")

        tmp = tempfile.NamedTemporaryFile(suffix=target_ext, delete=False)
        save_kwargs = {"format": pil_format}
        if quality and pil_format in ("JPEG", "WEBP"):
            save_kwargs["quality"] = quality
            save_kwargs["optimize"] = True
        img.save(tmp.name, **save_kwargs)
        tmp.close()

    return tmp.name, _FORMAT_MEDIA_TYPES.get(pil_format, "image/jpeg"), target_ext
