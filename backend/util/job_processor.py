# util/job_processor.py

import json
import threading
import time
from typing import Any, Dict

from backend.util.database import ChubDB


# Module-level cancel registry: maps job_id -> threading.Event
# Shared between job processor threads and API cancel endpoint
_cancel_registry: Dict[int, threading.Event] = {}
_cancel_registry_lock = threading.Lock()


# Per-module advisory locks. Enqueue-side dedupe in worker.enqueue_job
# already collapses duplicate module_run jobs by module_name, but this
# is a backstop: anything that bypasses enqueue (webhook handlers
# calling _process_module_run_job directly, future paths we haven't
# anticipated) still gets serialized per module.
_MODULE_LOCKS: Dict[str, threading.Lock] = {}
_MODULE_LOCKS_GUARD = threading.Lock()


def _get_module_lock(module_name: str) -> threading.Lock:
    """Return (creating if needed) the advisory lock for `module_name`."""
    with _MODULE_LOCKS_GUARD:
        lock = _MODULE_LOCKS.get(module_name)
        if lock is None:
            lock = threading.Lock()
            _MODULE_LOCKS[module_name] = lock
        return lock


def register_cancel_event(job_id: int) -> threading.Event:
    """Create and register a cancel event for a job. Returns the event."""
    event = threading.Event()
    with _cancel_registry_lock:
        _cancel_registry[job_id] = event
    return event


def request_cancellation(job_id: int) -> bool:
    """Signal cancellation for a running job. Returns True if the job was found."""
    with _cancel_registry_lock:
        event = _cancel_registry.get(job_id)
    if event is not None:
        event.set()
        return True
    return False


def unregister_cancel_event(job_id: int) -> None:
    """Remove a cancel event after the job finishes."""
    with _cancel_registry_lock:
        _cancel_registry.pop(job_id, None)


def process_job(job: Dict[str, Any], logger, db: ChubDB = None) -> Dict[str, Any]:
    """
    Route jobs to appropriate handlers.

    Args:
        job: Job data from the database
        logger: Logger instance
        db: Shared database context (optional, creates new if not provided)

    Returns:
        dict: Job processing result
    """
    job_id = job.get("id")
    job_type = job.get("type")
    payload = json.loads(job.get("payload", "{}"))

    log = logger.get_adapter("JOB_PROCESSOR")
    log.debug(f"[JOB:{job_id}] Processing {job_type}")

    start_time = time.time()

    try:
        if job_type == "webhook":
            return _process_webhook_job(payload, logger, job_id, db)
        elif job_type == "poster_rename":
            return _process_poster_rename_job(payload, logger, job_id, db)
        elif job_type == "upload_posters":
            return _process_upload_posters_job(payload, logger, job_id, db)
        elif job_type == "module_run":
            return _process_module_run_job(payload, logger, job_id, db)
        elif job_type == "media_sync":
            return _process_media_sync_job(payload, logger, job_id, db)
        elif job_type == "cache_refresh":
            return _process_cache_refresh_job(payload, logger, job_id, db)
        elif job_type == "plex_metadata_scan":
            return _process_plex_metadata_scan_job(payload, logger, job_id, db)
        elif job_type == "kometa_assets_scan":
            return _process_kometa_assets_scan_job(payload, logger, job_id, db)
        elif job_type == "labelarr_bulk_sync":
            return _process_labelarr_bulk_sync_job(payload, logger, job_id, db)
        else:
            return {
                "status": 400,
                "success": False,
                "message": f"Unknown job type: {job_type}",
                "error_code": "UNKNOWN_JOB_TYPE",
            }

    except Exception as e:
        log.error(f"[JOB:{job_id}] Error processing {job_type}: {e}", exc_info=True)
        return {
            "status": 500,
            "success": False,
            "message": f"Job failed: {str(e)}",
            "error_code": "JOB_EXCEPTION",
        }
    finally:
        duration = time.time() - start_time
        log.debug(f"[JOB:{job_id}] Completed in {duration:.2f}s")


def _process_webhook_job(
    payload: Dict[str, Any], logger, job_id: int, db: ChubDB = None
) -> Dict[str, Any]:
    """
    Process webhook job by fetching ONLY the specific media item and updating it.

    Args:
        payload: Job payload containing webhook data
        logger: Logger instance
        job_id: Job ID for tracking
        db: Shared database context (creates new if not provided)

    Returns:
        dict: Processing result
    """
    log = logger.get_adapter("WEBHOOK_PROCESSOR")
    log.info(f"[JOB:{job_id}] Starting webhook processing")

    try:
        from backend.modules.poster_renamerr import PosterRenamerr
        from backend.util.arr import create_arr_client
        from backend.util.webhook_processor import WebhookProcessor

        webhook_data = payload.get("webhook_data", {})
        client_info = payload.get("client_info")

        # Validate webhook and get instance info
        processor = WebhookProcessor(logger)
        validation_result = processor._validate_webhook(webhook_data, client_info)
        if not validation_result["success"]:
            log.error(
                f"[JOB:{job_id}] Webhook validation failed: {validation_result['message']}"
            )
            return validation_result

        instance_info = validation_result["instance_info"]
        media_id = validation_result["media_id"]
        webhook_season = validation_result.get("season_number")
        # Pre-download adds (SeriesAdd/MovieAdded) have no new file for Plex to
        # scan, so the availability wait shouldn't burn the full retry budget.
        is_added_event = webhook_data.get("eventType", "") in (
            "SeriesAdd",
            "MovieAdded",
        )

        # Helper function to process the media item
        def _process_media_item(db_context):
            arr_logger = logger.get_adapter(
                f"{instance_info['type']}:{instance_info['name']}"
            )

            # Create direct ARR client connection
            client = create_arr_client(
                instance_info["url"], instance_info["api"], arr_logger
            )

            if not client or not client.is_connected():
                # Close the session we just opened; otherwise the socket
                # leaks on every failed-to-connect attempt.
                if client is not None:
                    try:
                        client.session.close()
                    except Exception:
                        pass
                return {
                    "success": False,
                    "message": f"Failed to connect to {instance_info['type']} instance",
                    "error_code": "ARR_CONNECTION_FAILED",
                }

            try:
                # Fetch ONLY the specific media item that triggered the webhook
                if instance_info["type"] == "radarr":
                    media = client.get_movie(media_id)
                    asset_type = "movie"
                else:
                    media = client.get_show(media_id)
                    asset_type = "show"

                if not media:
                    return {
                        "success": False,
                        "message": f"Media item {media_id} not found in {instance_info['name']}",
                        "error_code": "MEDIA_NOT_FOUND",
                    }

                log.debug(
                    f"[JOB:{job_id}] Fetched {media['title']} from {instance_info['name']}"
                )

                # Process the single media item for database storage
                processed_media = _process_media_record(media, asset_type)

                # Update only this specific media item in the database
                _update_media_record(
                    db_context, instance_info, asset_type, processed_media, log
                )

                # Get stored media records for poster processing
                stored_media = db_context.media.get_by_title_year_instance(
                    media["title"], media.get("year"), instance_info["name"]
                )

                if not stored_media:
                    return {
                        "success": False,
                        "message": "Failed to retrieve stored media from database",
                        "error_code": "MEDIA_RETRIEVAL_FAILED",
                    }

                return {"success": True, "media": media, "stored_media": stored_media}

            finally:
                # Clean up the ARR client connection
                if hasattr(client, "session") and client.session:
                    client.session.close()

        # Use shared database context or create new one if not provided
        if db is not None:
            # Use the shared database context
            process_result = _process_media_item(db)
        else:
            # Fallback: create new context if none provided (for backward compatibility)
            with ChubDB(logger=logger, quiet=True) as temp_db:
                process_result = _process_media_item(temp_db)

        if not process_result["success"]:
            return process_result

        media = process_result["media"]
        stored_media = process_result["stored_media"]

        # Wait for the item to appear in Plex before processing posters. For a
        # Sonarr season import, wait for that specific season folder to be
        # scanned (not just the show) so the season poster has somewhere to land.
        processor.wait_for_plex_availability(
            media["title"],
            year=media.get("year"),
            season_number=webhook_season if instance_info["type"] == "sonarr" else None,
            is_added_event=is_added_event,
        )

        # Run poster rename on the stored media. A Sonarr Download event
        # (On File Import / Upgrade / Import Complete) carries the affected
        # season; narrow `media_items` to (show row + matching season row)
        # so the renamer only re-matches what actually changed.
        media_items = stored_media if isinstance(stored_media, list) else [stored_media]
        if webhook_season is not None and instance_info["type"] == "sonarr":
            focused = [
                item
                for item in media_items
                if item.get("season_number") in (None, webhook_season)
            ]
            if focused:
                log.debug(
                    f"[JOB:{job_id}] Narrowed {len(media_items)} stored rows to "
                    f"{len(focused)} for season {webhook_season}"
                )
                media_items = focused

        renamer = PosterRenamerr(logger=logger)
        # Honour `webhook_force_reupload` on the originating *arr instance — when
        # set, the upload bypasses the uploader's hash-equal short-circuit so an
        # unchanged poster still gets re-pushed to Plex. The staging lifecycle
        # for the plex apply path lives inside the helper.
        force_upload = _instance_force_reupload(instance_info)
        rename_result = _adhoc_rename_and_post(
            renamer, media_items, logger, job_id, force_upload=force_upload
        )

        if rename_result["success"]:
            log.info(f"[JOB:{job_id}] Webhook processing successful")
            return {
                "success": True,
                "message": f"Webhook processed successfully: {media['title']}",
                "data": {"media": media, "rename_result": rename_result},
            }
        else:
            log.error(
                f"[JOB:{job_id}] Poster rename failed: {rename_result.get('message')}"
            )
            return {
                "success": False,
                "message": f"Poster rename failed: {rename_result.get('message')}",
                "error_code": "POSTER_RENAME_FAILED",
            }

    except Exception as e:
        log.error(
            f"[JOB:{job_id}] Exception during webhook processing: {e}", exc_info=True
        )
        return {
            "success": False,
            "message": f"Webhook processing failed: {str(e)}",
            "error_code": "WEBHOOK_PROCESSING_EXCEPTION",
        }


def _process_media_record(media: dict, asset_type: str) -> list:
    """
    Process a single media item into the format expected by the database.
    This replaces the heavy connector logic for single-item processing.

    Args:
        media: Single media item from ARR API
        asset_type: 'movie' or 'show'

    Returns:
        list: Processed media items ready for database storage
    """
    processed_items = []

    if asset_type == "show":
        # For shows, create entries for the main show and each season
        # Main show entry (no season)
        show_entry = dict(media)
        show_entry["season_number"] = None
        processed_items.append(show_entry)

        # Individual season entries
        for season in media.get("seasons", []):
            season_entry = dict(media)
            season_entry["season_number"] = season.get("season_number")
            # Override the inherited show-level has_content + monitored with each
            # season's own values (mirrors connector._process_arr_media). Without
            # this, a webhook upsert clobbers a correct full sync: an unaired
            # season with no files would inherit the show's any-season-has-files
            # rollup (has_content=True) and a per-season unmonitored flag would be
            # lost — re-flagging it as in-library / release-ready.
            season_entry["has_content"] = (season.get("season_has_episodes") or 0) > 0
            if season.get("monitored") is not None:
                season_entry["monitored"] = season.get("monitored")
            processed_items.append(season_entry)
    else:
        # For movies, just add the single item
        processed_items.append(media)

    return processed_items


def _update_media_record(
    db: ChubDB, instance_info: dict, asset_type: str, processed_media: list, logger
) -> None:
    """
    Update only the specific media records for the webhook item.
    This prevents affecting other media in the instance.

    Args:
        db: Database connection
        instance_info: ARR instance information
        asset_type: 'movie' or 'show'
        processed_media: List of processed media items to update
        logger: Logger instance
    """
    instance_name = instance_info["name"]
    # Lowercase service type — stored as media_cache.source, which must match
    # sync_state.scope / /instances/types (upsert normalizes too, belt-and-braces).
    instance_type = instance_info["type"].lower()

    for item in processed_media:
        try:
            # Use upsert to add or update the individual record
            db.media.upsert(item, asset_type, instance_type, instance_name)

            # Log the action
            season = item.get("season_number")
            season_str = f" Season: {season}," if season is not None else ""
            logger.info(
                f"[ADD] Title: {item.get('title')} ({item.get('year')}) ({asset_type}),{season_str} from {instance_name}"
            )

        except Exception as e:
            logger.error(
                f"Failed to update media record for {item.get('title')}: {e}",
                exc_info=True,
            )

    logger.debug(
        f"[SYNC] Media cache for {instance_name} ({asset_type}) synchronized. {len(processed_media)} items present."
    )


def _process_poster_rename_job(
    payload: Dict[str, Any], logger, job_id: int, db: ChubDB = None
) -> Dict[str, Any]:
    """
    Process poster rename job.

    Args:
        payload: Job payload containing media items
        logger: Logger instance
        job_id: Job ID for tracking
        db: Shared database context (unused, kept for call-site compatibility)

    Returns:
        dict: Processing result
    """
    from backend.modules.poster_renamerr import PosterRenamerr

    media_items = payload.get("media_items", [])
    if not media_items:
        return {
            "status": 400,
            "success": False,
            "message": "No media items provided for poster rename",
            "error_code": "MISSING_MEDIA_ITEMS",
        }

    renamer = PosterRenamerr(logger=logger)
    # apply_staging() + post-rename actions (border + plex/kometa upload policy)
    # are handled inside the helper.
    return _adhoc_rename_and_post(renamer, media_items, logger, job_id)


def _process_upload_posters_job(
    payload: Dict[str, Any], logger, job_id: int, db: ChubDB = None
) -> Dict[str, Any]:
    """
    Process poster upload job.

    Args:
        payload: Job payload containing manifest
        logger: Logger instance
        job_id: Job ID for tracking

    Returns:
        dict: Processing result
    """
    from backend.util.upload_posters import PosterUploader

    manifest = payload.get("manifest")
    if not manifest:
        return {
            "status": 400,
            "success": False,
            "message": "No manifest provided for poster upload",
            "error_code": "MISSING_MANIFEST",
        }

    force = bool(payload.get("force", False))
    targeted = bool(payload.get("targeted", False))
    with ChubDB(logger=logger) as db:
        # Targeted (webhook) uploads reuse the cached Plex snapshot to avoid a
        # full library rebuild on every webhook — but only when a snapshot
        # already exists; otherwise fall back to a full refresh so fresh
        # installs still work. (The "wait for Plex to scan the new item/season"
        # retry lives upstream in webhook_processor.wait_for_plex_availability.)
        refresh_plex = True
        if targeted and db.plex.count() > 0:
            refresh_plex = False
            logger.get_adapter("UPLOAD_POSTERS").debug(
                "Targeted upload: reusing cached Plex snapshot (no full refresh)"
            )
        uploader = PosterUploader(
            db=db,
            logger=logger,
            manifest=manifest,
            force=force,
            refresh_plex=refresh_plex,
        )
        result = uploader.run()

    if result.get("success"):
        return {
            "status": 200,
            "success": True,
            "message": "Poster upload completed successfully",
        }
    else:
        return {
            "status": 500,
            "success": False,
            "message": f"Poster upload failed: {result.get('message')}",
            "error_code": "UPLOAD_FAILED",
        }


def _adhoc_rename_and_post(
    renamer, media_items, logger, job_id: int, force_upload: bool = False
) -> Dict[str, Any]:
    """Run the webhook/adhoc rename + post-rename actions under the apply_staging
    context so the plex path's temp staging dir lives across rename → border →
    (synchronous) upload and is cleaned up afterwards. On the kometa path
    apply_staging() is a no-op and files are written to destination_dir.
    """
    with renamer.apply_staging():
        result = renamer.run_poster_rename_adhoc(media_items)
        if result.get("success") and result.get("output"):
            _handle_post_rename_actions(
                result, renamer, logger, job_id, force_upload=force_upload
            )
    return result


def _handle_post_rename_actions(
    rename_result: Dict[str, Any],
    renamer,
    logger,
    job_id: int,
    force_upload: bool = False,
) -> None:
    """
    Handle notifications and uploads after successful rename.

    Args:
        rename_result: Result from poster rename operation
        renamer: PosterRenamerr instance
        logger: Logger instance
        job_id: Job ID for tracking
        force_upload: When True, queues the upload job with `force=True` so
            the uploader skips its hash-equal short-circuit. Webhook flows
            set this from the *arr instance's `webhook_force_reupload`.
    """
    log = logger.get_adapter("POST_RENAME")

    try:
        output = rename_result.get("output", {})
        manifest = rename_result.get("manifest", {})

        # Send notifications if there are results
        if any(output.values()):
            from backend.util.notification import NotificationManager

            manager = NotificationManager(
                renamer.full_config, logger, module_name="poster_renamerr"
            )
            manager.send_notification(output)
            log.info(f"[JOB:{job_id}] Notifications sent")

        # Handle border replacer if enabled
        if getattr(renamer.config, "run_border_replacerr", False) and manifest:
            renamer.run_border_replacerr(manifest)
            log.info(f"[JOB:{job_id}] Border replacer completed")

        # Strict either/or (PosterRenamerrConfig.apply_method):
        #   - "kometa": files were written to destination_dir; do NOT upload.
        #   - "plex": posters were staged in a temp dir by apply_staging(); they
        #     must be uploaded SYNCHRONOUSLY here (a queued async upload job
        #     would run after the staging dir is cleaned up). The uploader still
        #     gates per-instance on add_posters. Targeted: reuse the cached Plex
        #     snapshot when one exists to avoid a full rebuild per webhook.
        apply_method = getattr(renamer.config, "apply_method", "kometa")
        if apply_method != "plex":
            log.info(f"[JOB:{job_id}] apply_method=kometa - no Plex upload")
        elif _check_plex_upload_enabled(renamer.config) and manifest:
            from backend.util.upload_posters import PosterUploader

            with ChubDB(logger=logger) as updb:
                refresh_plex = updb.plex.count() == 0
                PosterUploader(
                    db=updb,
                    logger=logger,
                    manifest=manifest,
                    force=force_upload,
                    refresh_plex=refresh_plex,
                ).run()
            log.info(f"[JOB:{job_id}] Plex upload completed")
        else:
            log.info(
                f"[JOB:{job_id}] Plex upload not enabled or no manifest - task complete"
            )

    except Exception as e:
        log.error(f"[JOB:{job_id}] Error in post-rename actions: {e}")


def _instance_force_reupload(instance_info: Dict[str, Any]) -> bool:
    """
    Return the configured `webhook_force_reupload` for a Sonarr/Radarr/Lidarr
    instance identified by `instance_info`. Falls back to False on any
    config-loading or attribute-lookup error so a malformed config can never
    silently force-upload everything.
    """
    try:
        from backend.util.config import load_config

        cfg = load_config()
        bucket = getattr(cfg.instances, instance_info.get("type", ""), None) or {}
        details = bucket.get(instance_info.get("name", ""))
        return bool(getattr(details, "webhook_force_reupload", False))
    except Exception:
        return False


def _check_plex_upload_enabled(config) -> bool:
    """
    Check if any Plex instances have poster upload enabled.

    Args:
        config: Application configuration

    Returns:
        bool: True if upload is enabled for any Plex instance
    """
    try:
        for scope in getattr(config, "plex_scope", []) or []:
            if getattr(scope, "add_posters", False):
                return True
        return False
    except Exception:
        return False


def _process_media_sync_job(
    payload: Dict[str, Any], logger, job_id: int, db: ChubDB = None
) -> Dict[str, Any]:
    """Background media-cache reconciliation.

    Steps through each configured *arr instance SEQUENTIALLY (Connector already
    syncs one instance at a time), refreshing media_cache, then refreshes Plex
    via the TTL-guarded path (``refresh_plex_cache_if_stale`` — one instance at a
    time, per-library, deduped against a recent walk) rather than a forced full
    walk, then collections + Plex mappings. Logs to General via ``get_adapter``
    on the shared worker logger — this is NOT a module, so it never gets its own
    log file or a Modules-page entry. Stepping sequentially + the gentle Plex
    path keep this pass from spiking resources.
    """
    log = logger.get_adapter("media_sync")
    lock = _get_module_lock("media_sync")
    if not lock.acquire(blocking=False):
        log.info(f"[JOB:{job_id}] media_sync already running; skipping this trigger")
        return {
            "status": 200,
            "success": True,
            "deferred": True,
            "message": "media_sync already in flight",
        }
    try:
        from backend.util.config import load_config
        from backend.util.connector import Connector, build_instance_map
        from backend.util.plex_refresh import refresh_plex_cache_if_stale

        start = time.time()
        cfg = load_config()
        instance_map = build_instance_map(cfg)
        log.info("Media-cache reconciliation starting (arr + plex + collections)")

        owns_db = db is None
        db_ctx = db if db is not None else ChubDB(logger=logger)
        if owns_db:
            db_ctx.__enter__()
        try:
            connector = Connector(db=db_ctx, logger=logger, instance_map=instance_map)
            try:
                arr_results = connector.update_arr_database()

                # Plex: gentle, TTL-guarded refresh (walks only stale libraries,
                # one instance at a time) — NOT the forced full walk, so a daily
                # cadence can't hammer a large library. Empty list = all
                # libraries of that instance.
                enabled_plex = {
                    name: []
                    for name, detail in (
                        getattr(cfg.instances, "plex", {}) or {}
                    ).items()
                    if getattr(detail, "enabled", True)
                }
                if enabled_plex:
                    try:
                        refresh_plex_cache_if_stale(db_ctx, cfg, logger, enabled_plex)
                    except Exception as exc:
                        log.warning(f"Plex refresh failed: {exc}")

                connector.update_collections_database()
                try:
                    connector.update_media_plex_mappings()
                except Exception as exc:
                    log.warning(f"Plex mapping update failed: {exc}")
            finally:
                connector.connection_manager.close_all_connections()
        finally:
            if owns_db:
                db_ctx.__exit__(None, None, None)

        succeeded = len([r for r in arr_results if r.success])
        elapsed = time.time() - start
        log.info(
            f"Media-cache reconciliation complete: {succeeded}/{len(arr_results)} "
            f"instances in {elapsed:.1f}s"
        )
        return {
            "status": 200,
            "success": True,
            "message": f"Synced {succeeded}/{len(arr_results)} instances",
            "data": {"synced": succeeded, "attempted": len(arr_results)},
        }
    except Exception as e:
        log.error(f"[JOB:{job_id}] media_sync failed: {e}", exc_info=True)
        return {
            "status": 500,
            "success": False,
            "message": f"media_sync failed: {e}",
            "error_code": "MEDIA_SYNC_FAILED",
        }
    finally:
        lock.release()


def _process_module_run_job(
    payload: Dict[str, Any], logger, job_id: int, db: ChubDB = None
) -> Dict[str, Any]:
    """
    Process module run job - executes a CHUB module.

    Args:
        payload: Job payload containing module info
        logger: Logger instance
        job_id: Job ID for tracking
        db: Shared database context (creates new if not provided)

    Returns:
        dict: Processing result
    """
    log = logger.get_adapter("MODULE_PROCESSOR")

    module_name = payload.get("module_name")
    origin = payload.get("origin", "job")
    # The immediate flag was intended to potentially adjust behavior (like priority or timeout), but it's not currently used in the job processing logic.
    # immediate = payload.get("immediate", False)

    if not module_name:
        return {
            "status": 400,
            "success": False,
            "message": "No module_name provided for module run",
            "error_code": "MISSING_MODULE_NAME",
        }

    log.info(f"[JOB:{job_id}] Running module {module_name} (origin={origin})")

    module_lock = _get_module_lock(module_name)
    if not module_lock.acquire(blocking=False):
        # Backstop for callers that bypass enqueue dedupe (e.g. webhook
        # handlers invoking us directly). Non-blocking so a worker thread
        # isn't tied up waiting — we surface the skip as success+deferred
        # so the queue doesn't retry.
        log.warning(
            f"[JOB:{job_id}] {module_name} is already running on another worker; "
            "deferring this run."
        )
        return {
            "status": 200,
            "success": True,
            "deferred": True,
            "message": f"Skipped — {module_name} already in flight",
            "data": {"module": module_name, "origin": origin},
        }

    try:
        from backend.modules import MODULES

        if module_name not in MODULES:
            return {
                "status": 400,
                "success": False,
                "message": f"Unknown module: {module_name}",
                "error_code": "UNKNOWN_MODULE",
            }

        module_class = MODULES[module_name]

        # Create a module-specific logger so each module gets its own log file
        from backend.util.config import load_config
        from backend.util.logger import Logger

        try:
            full_config = load_config()
            module_config = getattr(full_config, module_name, None)
            module_log_level = (
                getattr(module_config, "log_level", "INFO") if module_config else "INFO"
            )
            max_logs = getattr(full_config.general, "max_logs", 9)
            module_logger = Logger(
                log_level=module_log_level,
                module_name=module_name,
                max_logs=max_logs,
            )
        except Exception:
            # Fall back to shared logger if module-specific logger fails
            module_logger = logger

        module_instance = module_class(logger=module_logger)

        # Apply payload overrides to the module's config. This is how the API
        # (e.g. the Poster Cleanarr UI) steers a module run without mutating
        # the on-disk config file. Overrides are attribute-level; unknown
        # keys are tolerated so modules can opt in as they gain support.
        overrides = payload.get("overrides")
        if isinstance(overrides, dict):
            for key, value in overrides.items():
                try:
                    setattr(module_instance.config, key, value)
                    # Some modules cache config values on self at __init__ —
                    # mirror the override onto the instance for parity.
                    if hasattr(module_instance, key):
                        setattr(module_instance, key, value)
                except Exception:  # noqa: S112 -- best-effort overrides
                    continue

        # Register cancel event so this job can be cancelled via the API
        cancel_event = register_cancel_event(job_id) if job_id else None
        if cancel_event is not None:
            module_instance.set_cancel_event(cancel_event)

        # Helper function to execute module with database context
        def _execute_module_with_db(db_context):
            # Record run start in database
            db_context.run_state.record_run_start(module_name, run_by=origin)

            # Hand the module a job-progress channel so long-running phases
            # (e.g. poster_renamerr.merge_assets) can update the Jobs page
            # percentage instead of leaving it stuck at 0% until completion.
            module_instance.set_job_context(job_id, db_context)

            # Report initial progress
            if job_id:
                try:
                    db_context.worker.update_progress("jobs", job_id, 0)
                except Exception:  # noqa: S110 -- progress update is non-critical
                    pass

            start_time = time.time()

            # module_args: optional kwargs forwarded to module.run(). Lets
            # the generic module_run path express module-specific filters
            # (e.g. sync_gdrive's only_folders + notify) so we don't need
            # a dedicated job_type per parametrized invocation. Modules
            # whose run() doesn't accept these kwargs raise TypeError on
            # call, which we catch and retry with no args — defensive so
            # existing modules unaware of the convention keep working.
            module_args = payload.get("module_args") or {}

            try:
                # Execute the module
                try:
                    module_instance.run(**module_args)
                except TypeError:
                    if module_args:
                        log.warning(
                            f"[JOB:{job_id}] {module_name}.run() does not accept "
                            f"module_args {list(module_args)}; retrying without"
                        )
                        module_instance.run()
                    else:
                        raise

                # Check if cancelled during execution
                if cancel_event and cancel_event.is_set():
                    duration = int(time.time() - start_time)
                    db_context.run_state.record_run_finish(
                        module_name,
                        success=False,
                        status="cancelled",
                        message="Cancelled by user",
                        duration=duration,
                        run_by=origin,
                    )
                    log.info(
                        f"[JOB:{job_id}] Module {module_name} was cancelled after {duration}s"
                    )
                    return {
                        "status": 200,
                        "success": True,
                        "message": f"Module {module_name} was cancelled",
                        "data": {
                            "module": module_name,
                            "duration": duration,
                            "origin": origin,
                            "cancelled": True,
                        },
                    }

                duration = int(time.time() - start_time)

                # Report completion progress
                if job_id:
                    try:
                        db_context.worker.update_progress("jobs", job_id, 100)
                    except Exception:
                        pass

                # Record successful completion
                db_context.run_state.record_run_finish(
                    module_name,
                    success=True,
                    status="success",
                    message="Completed successfully",
                    duration=duration,
                    run_by=origin,
                )

                log.info(
                    f"[JOB:{job_id}] Module {module_name} completed successfully in {duration}s"
                )

                return {
                    "status": 200,
                    "success": True,
                    "message": f"Module {module_name} completed successfully",
                    "data": {
                        "module": module_name,
                        "duration": duration,
                        "origin": origin,
                    },
                }

            except Exception as e:
                duration = int(time.time() - start_time)
                error_msg = str(e)

                # Record failure
                db_context.run_state.record_run_finish(
                    module_name,
                    success=False,
                    status="error",
                    message=error_msg,
                    duration=duration,
                    run_by=origin,
                )

                log.error(f"[JOB:{job_id}] Module {module_name} failed: {error_msg}")

                return {
                    "status": 500,
                    "success": False,
                    "message": f"Module {module_name} failed: {error_msg}",
                    "error_code": "MODULE_EXECUTION_FAILED",
                    "data": {
                        "module": module_name,
                        "duration": duration,
                        "origin": origin,
                        "error": error_msg,
                    },
                }

        # Use shared database context or create new one if not provided
        try:
            if db is not None:
                return _execute_module_with_db(db)
            else:
                with ChubDB(logger=logger, quiet=True) as temp_db:
                    return _execute_module_with_db(temp_db)
        finally:
            # Always clean up the cancel event when the job finishes
            if job_id:
                unregister_cancel_event(job_id)

    except Exception as e:
        log.error(f"[JOB:{job_id}] Exception in module run job: {e}", exc_info=True)
        return {
            "status": 500,
            "success": False,
            "message": f"Module run job failed: {str(e)}",
            "error_code": "MODULE_JOB_EXCEPTION",
        }
    finally:
        module_lock.release()


def _process_labelarr_bulk_sync_job(
    payload: Dict[str, Any], logger, job_id: int, db: Any = None
) -> Dict[str, Any]:
    """Bulk labelarr sync — one job processes a list of media_cache_ids.

    Single canonical handler for both /labelarr/sync (single item, with
    notify=False from the API layer) and /labelarr/bulk-sync (many items,
    notify=True default). One Discord summary fires at the end when
    notify is True.
    """
    log = logger.get_adapter("LABELARR_BULK")
    log.info(f"[JOB:{job_id}] Starting bulk labelarr sync")

    try:
        from backend.modules.labelarr import Labelarr

        source_instance = payload.get("source_instance")
        media_cache_ids = payload.get("media_cache_ids") or []
        tag_actions = payload.get("tag_actions") or {}
        plex_instance = payload.get("plex_instance")
        dry_run = payload.get("dry_run", False)
        # notify: True (default) sends one aggregate Discord summary at
        # the end of the bulk operation; /labelarr/sync (single-item
        # path) sets this False so single-click UI actions stay silent
        # while still going through the canonical bulk processor.
        notify = payload.get("notify", True)

        if not source_instance or not media_cache_ids:
            return {
                "status": 400,
                "success": False,
                "message": "Missing required parameters: source_instance or media_cache_ids",
                "error_code": "MISSING_PARAMETERS",
            }

        labelarr = Labelarr(logger=logger)
        result = labelarr.labelarr_bulk_sync_adhoc(
            source_instance=source_instance,
            media_cache_ids=media_cache_ids,
            tag_actions=tag_actions,
            plex_instance=plex_instance,
            dry_run=dry_run,
            notify=notify,
        )

        return {
            "status": 200,
            "success": True,
            "message": result.get("message", "Bulk labelarr sync completed"),
            "data": result.get("data", {}),
        }

    except Exception as e:
        log.error(f"[JOB:{job_id}] Bulk labelarr sync failed: {e}", exc_info=True)
        return {
            "status": 500,
            "success": False,
            "message": f"Bulk labelarr sync failed: {str(e)}",
            "error_code": "LABELARR_BULK_SYNC_FAILED",
        }


def _process_plex_metadata_scan_job(
    payload: Dict[str, Any], logger, job_id: int, db: ChubDB = None
) -> Dict[str, Any]:
    """Warm the Poster Cleanarr scan cache on a worker thread.

    Walks the Plex Metadata tree + PhotoTranscoder cache (a ~140k-file scan on
    large libraries) and stores the result in the in-memory TTL cache that the
    GET /plex-metadata/by-media + /bloat endpoints read. Runs here, off the
    FastAPI event loop, so the scan never blocks the API or trips the client's
    request timeout.
    """
    log = logger.get_adapter("PLEX_METADATA_SCAN")
    plex_path = payload.get("plex_path")
    if not plex_path:
        return {
            "status": 400,
            "success": False,
            "message": "plex_path missing from scan payload",
            "error_code": "PLEX_PATH_UNSET",
        }

    from backend.util.plex_metadata import scan_bundles, scan_transcoder_cache

    log.info(f"[JOB:{job_id}] Scanning Plex metadata at {plex_path}")
    scan = scan_bundles(plex_path, force=True)
    transcoder = scan_transcoder_cache(plex_path, force=True)
    stats = scan["stats"]
    log.info(
        f"[JOB:{job_id}] Scan complete: {stats['bundle_count']} bundles, "
        f"{stats['variant_count']} variants, {stats['bloat_count']} bloat; "
        f"transcoder {transcoder['count']} files"
    )
    return {
        "status": 200,
        "success": True,
        "message": "Plex metadata scan complete",
        "data": {"stats": stats, "transcoder": transcoder},
    }


def _process_kometa_assets_scan_job(
    payload: Dict[str, Any], logger, job_id: int, db: ChubDB = None
) -> Dict[str, Any]:
    """Warm the Kometa stale/orphan scan cache on a worker thread.

    The asset-dir walk + Plex-mapping detection ran on the event loop on every
    Poster Cleanarr page load; this moves it off-loop. Results land in the TTL
    cache read by GET /plex-metadata/kometa-assets-scan.
    """
    log = logger.get_adapter("KOMETA_ASSETS_SCAN")
    from backend.modules.poster_cleanarr import scan_kometa_assets

    log.info(f"[JOB:{job_id}] Scanning Kometa assets")
    with ChubDB(logger=logger) as scan_db:
        result = scan_kometa_assets(scan_db, logger, force=True)
    stats = result["stats"]
    log.info(
        f"[JOB:{job_id}] Kometa scan complete: {stats['stale_count']} stale, "
        f"{stats['orphan_count']} orphan"
    )
    return {
        "status": 200,
        "success": True,
        "message": "Kometa assets scan complete",
        "data": {"stats": stats},
    }


def _process_cache_refresh_job(
    payload: Dict[str, Any], logger, job_id: int, db: ChubDB = None
) -> Dict[str, Any]:
    """
    Process cache refresh job by syncing ARR and Plex databases.

    Args:
        payload: Job payload containing refresh configuration
        logger: Logger instance
        job_id: Job ID for tracking

    Returns:
        dict: Processing result
    """
    log = logger.get_adapter("CACHE_REFRESH")
    log.info(f"[JOB:{job_id}] Starting cache refresh")

    try:
        from backend.util.connector import Connector

        # Extract refresh configuration from payload
        arr_instances = payload.get("arr_instances", [])
        plex_instances = payload.get("plex_instances", [])
        libraries = payload.get("libraries", [])
        update_mappings = payload.get("update_mappings", False)

        log.info(
            f"[JOB:{job_id}] Refresh config - ARR: {len(arr_instances)}, Plex: {len(plex_instances)}, Libraries: {len(libraries)}, Mappings: {update_mappings}"
        )

        # Construct instance_map from payload data for Connector
        # Expected format: {'arrs': ['Radarr Test'], 'plex': {'plex_1': ['Test Movies']}}
        instance_map = {}

        # When both are empty, auto-discover all configured instances
        if not arr_instances and not plex_instances:
            from backend.util.config import load_config

            cfg = load_config()
            for svc_type in ("radarr", "sonarr", "lidarr"):
                svc_instances = getattr(cfg.instances, svc_type, {})
                for name, detail in svc_instances.items():
                    if detail.enabled:
                        instance_map.setdefault("arrs", []).append(name)
            plex_instances_cfg = getattr(cfg.instances, "plex", {})
            if plex_instances_cfg:
                plex_map = {}
                for name, detail in plex_instances_cfg.items():
                    if detail.enabled:
                        plex_map[name] = libraries if libraries else []
                if plex_map:
                    instance_map["plex"] = plex_map
            log.info(f"[JOB:{job_id}] Auto-discovered instances: {instance_map}")
        else:
            # Add ARR instances to map
            if arr_instances:
                instance_map["arrs"] = arr_instances

            # Add Plex instances with libraries to map
            if plex_instances:
                plex_map = {}
                for plex_instance in plex_instances:
                    # Use libraries if specified, otherwise use empty list (all libraries)
                    plex_map[plex_instance] = libraries if libraries else []
                instance_map["plex"] = plex_map

        # Initialize connector with proper instance_map and database
        with ChubDB(logger=logger) as db:
            with Connector(
                db=db, instance_map=instance_map, logger=logger
            ) as connector:
                results = connector.sync_all_databases()

                # Log results
                arr_results = results.get("arr", [])
                plex_results = results.get("plex", [])
                collections_results = results.get("collections", [])
                mapping_results = results.get("mappings", {})

                arr_success = len([r for r in arr_results if r.success])
                plex_success = len([r for r in plex_results if r.success])
                collections_success = len([r for r in collections_results if r.success])

                log.info(
                    f"[JOB:{job_id}] Sync results - ARR: {arr_success}/{len(arr_results)}, Plex: {plex_success}/{len(plex_results)}, Collections: {collections_success}/{len(collections_results)}"
                )

                if isinstance(mapping_results, dict) and "updated" in mapping_results:
                    log.info(
                        f"[JOB:{job_id}] Plex mappings - Updated: {mapping_results['updated']}, No match: {mapping_results['no_match']}"
                    )

                # Determine overall success
                total_attempted = (
                    len(arr_results) + len(plex_results) + len(collections_results)
                )
                total_successful = arr_success + plex_success + collections_success

                success = total_successful == total_attempted and total_attempted > 0

                # Convert SyncResult objects to dictionaries for JSON serialization
                serializable_results = {}
                for key, value in results.items():
                    if key == "mappings":
                        serializable_results[key] = value  # Already a dict
                    else:
                        # Convert SyncResult objects to dicts
                        serializable_results[key] = [
                            {
                                "instance_name": r.instance_name,
                                "instance_type": r.instance_type,
                                "success": r.success,
                                "items_processed": r.items_processed,
                                "error_message": r.error_message,
                                "duration": r.duration,
                            }
                            for r in value
                        ]

                return {
                    "status": 200,
                    "success": success,
                    "message": f"Cache refresh completed: {total_successful}/{total_attempted} instances successful",
                    "data": {
                        "arr_synced": len(arr_results),
                        "plex_synced": len(plex_results),
                        "collections_synced": len(collections_results),
                        "mappings_updated": (
                            mapping_results.get("updated", 0)
                            if isinstance(mapping_results, dict)
                            else 0
                        ),
                        "results": serializable_results,
                    },
                }

    except Exception as e:
        log.error(f"[JOB:{job_id}] Cache refresh failed: {e}", exc_info=True)
        return {
            "status": 500,
            "success": False,
            "message": f"Cache refresh failed: {str(e)}",
            "error_code": "CACHE_REFRESH_FAILED",
        }
