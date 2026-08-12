"""
Notification configuration API endpoints for CHUB.

Notifications are stored as a list of **destinations** (per-channel), each
fanning out to the modules it should report on. A destination is:

    {
        "id": "d1a2b3c4",
        "method": "discord" | "notifiarr",
        "name": "My CHUB",
        "enabled": true,
        "events": {"success": true, "failure": false},
        "modules": ["poster_renamerr", ...]  | ["__ALL__"],
        "config": { ...method-specific credentials... }
    }

Endpoints: list destinations, create/update/delete a destination, and send a
test message for one method+config.
"""

import uuid
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.api.utils import error, ok
from backend.modules import MODULES
from backend.util.config import (
    ALL_MODULES_SENTINEL,
    ChubConfig,
    ConfigNotifications,
    load_config,
    redact_secrets,
    save_config,
    strip_redacted_placeholders,
)
from backend.util.notification import NotificationManager

router = APIRouter(
    prefix="/api",
    tags=["Notifications"],
    responses={
        500: {"description": "Internal server error"},
        400: {"description": "Invalid notification configuration"},
        502: {"description": "Notification service connection failed"},
    },
)

ALLOWED_METHODS = ("discord", "notifiarr")


class NotificationEventsPayload(BaseModel):
    success: bool = True
    failure: bool = False


class DestinationPayload(BaseModel):
    """Request schema for creating/updating a destination."""

    method: str
    name: str = ""
    enabled: bool = True
    events: NotificationEventsPayload = Field(default_factory=NotificationEventsPayload)
    modules: List[str] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)


class TestPayload(BaseModel):
    """Request schema for the test button. `id` (optional) lets the server
    resolve redacted secrets against an already-saved destination."""

    method: str
    config: dict = Field(default_factory=dict)
    id: Optional[str] = None


# ── helpers ──────────────────────────────────────────────────────────────


def get_logger(request: Request, source: str = "WEB") -> Any:
    """Get logger adapter from app state."""
    return request.app.state.logger.get_adapter(source)


def get_config() -> ChubConfig:
    """Load current configuration."""
    return load_config()


def _destinations_as_dicts(config: ChubConfig) -> List[dict]:
    """Current destinations as plain dicts (real secrets, unredacted)."""
    notif = getattr(config, "notifications", None)
    data = notif.model_dump(mode="python") if hasattr(notif, "model_dump") else {}
    dests = data.get("destinations") if isinstance(data, dict) else None
    return list(dests) if isinstance(dests, list) else []


def _save_destinations(config: ChubConfig, destinations: List[dict]) -> None:
    """Persist a new destinations list, preserving any extra notification keys."""
    notif = getattr(config, "notifications", None)
    data = notif.model_dump(mode="python") if hasattr(notif, "model_dump") else {}
    if not isinstance(data, dict):
        data = {}
    data["destinations"] = destinations
    config.notifications = ConfigNotifications.model_validate(data)
    save_config(config)


def _new_id(method: str, existing_ids: set) -> str:
    base = (method[:1] or "d").lower()
    while True:
        candidate = f"{base}{uuid.uuid4().hex[:8]}"
        if candidate not in existing_ids:
            return candidate


def _validate_method(method: str) -> Optional[JSONResponse]:
    if method not in ALLOWED_METHODS:
        return error(
            f"Invalid method: '{method}'. Allowed: {', '.join(ALLOWED_METHODS)}",
            code="INVALID_METHOD",
            status_code=400,
        )
    return None


def _validate_modules(modules: List[str]) -> Optional[JSONResponse]:
    for m in modules:
        if m != ALL_MODULES_SENTINEL and m not in MODULES:
            return error(
                f"Invalid module: '{m}'.",
                code="INVALID_MODULE_NAME",
                status_code=400,
            )
    return None


def _normalize_modules(modules: List[str]) -> List[str]:
    """Collapse to the `__ALL__` sentinel when present; de-dupe otherwise."""
    if ALL_MODULES_SENTINEL in modules:
        return [ALL_MODULES_SENTINEL]
    seen: List[str] = []
    for m in modules:
        if m not in seen:
            seen.append(m)
    return seen


# ── endpoints ────────────────────────────────────────────────────────────


@router.get(
    "/notifications",
    summary="List notification destinations",
    description="Retrieve all configured notification destinations (secrets redacted).",
)
async def get_all_notifications(
    config: ChubConfig = Depends(get_config), logger: Any = Depends(get_logger)
) -> JSONResponse:
    try:
        logger.debug("Serving GET /api/notifications")
        destinations = redact_secrets(_destinations_as_dicts(config))
        return ok(
            "Notifications retrieved successfully",
            {"destinations": destinations},
        )
    except Exception as e:
        logger.error(f"Error retrieving notifications: {e}")
        return error(
            "Error retrieving notifications",
            code="NOTIFICATIONS_RETRIEVAL_ERROR",
            status_code=500,
        )


@router.post(
    "/notifications/destinations",
    summary="Create a notification destination",
    description="Append a new destination and persist it.",
)
async def create_destination(
    payload: DestinationPayload, logger: Any = Depends(get_logger)
) -> JSONResponse:
    try:
        method_err = _validate_method(payload.method)
        if method_err:
            return method_err
        module_err = _validate_modules(payload.modules)
        if module_err:
            return module_err

        config = load_config()
        destinations = _destinations_as_dicts(config)
        existing_ids = {d.get("id") for d in destinations if isinstance(d, dict)}

        new_dest = {
            "id": _new_id(payload.method, existing_ids),
            "method": payload.method,
            "name": payload.name,
            "enabled": payload.enabled,
            "events": payload.events.model_dump(),
            "modules": _normalize_modules(payload.modules),
            "config": payload.config,
        }
        destinations.append(new_dest)
        _save_destinations(config, destinations)

        logger.info(
            f"Created {payload.method} notification destination {new_dest['id']}"
        )
        return ok(
            "Notification destination created successfully",
            {"destination": redact_secrets(new_dest)},
        )
    except Exception as e:
        logger.error(f"Failed to create notification destination: {e}")
        return error(
            "Failed to create destination",
            code="NOTIFICATION_CREATE_ERROR",
            status_code=500,
        )


@router.put(
    "/notifications/destinations/{destination_id}",
    summary="Update a notification destination",
    description="Update an existing destination. Secrets sent back as the "
    "redacted placeholder are preserved (not overwritten).",
)
async def update_destination(
    destination_id: str,
    payload: DestinationPayload,
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    try:
        method_err = _validate_method(payload.method)
        if method_err:
            return method_err
        module_err = _validate_modules(payload.modules)
        if module_err:
            return module_err

        config = load_config()
        destinations = _destinations_as_dicts(config)

        idx = next(
            (
                i
                for i, d in enumerate(destinations)
                if isinstance(d, dict) and d.get("id") == destination_id
            ),
            None,
        )
        if idx is None:
            return error(
                f"No destination found with id '{destination_id}'",
                code="NOTIFICATION_NOT_FOUND",
                status_code=404,
            )

        existing_config = destinations[idx].get("config") or {}
        merged_config = strip_redacted_placeholders(payload.config, existing_config)

        updated = {
            "id": destination_id,
            "method": payload.method,
            "name": payload.name,
            "enabled": payload.enabled,
            "events": payload.events.model_dump(),
            "modules": _normalize_modules(payload.modules),
            "config": merged_config,
        }
        destinations[idx] = updated
        _save_destinations(config, destinations)

        logger.info(f"Updated notification destination {destination_id}")
        return ok(
            "Notification destination updated successfully",
            {"destination": redact_secrets(updated)},
        )
    except Exception as e:
        logger.error(f"Failed to update notification destination {destination_id}: {e}")
        return error(
            "Failed to update destination",
            code="NOTIFICATION_UPDATE_ERROR",
            status_code=500,
        )


@router.delete(
    "/notifications/destinations/{destination_id}",
    summary="Delete a notification destination",
    description="Remove a destination by id.",
)
async def delete_destination(
    destination_id: str, logger: Any = Depends(get_logger)
) -> JSONResponse:
    try:
        config = load_config()
        destinations = _destinations_as_dicts(config)
        remaining = [
            d
            for d in destinations
            if not (isinstance(d, dict) and d.get("id") == destination_id)
        ]
        if len(remaining) == len(destinations):
            return error(
                f"No destination found with id '{destination_id}'",
                code="NOTIFICATION_NOT_FOUND",
                status_code=404,
            )
        _save_destinations(config, remaining)

        logger.info(f"Deleted notification destination {destination_id}")
        return ok(
            "Notification destination deleted successfully",
            {"id": destination_id},
        )
    except Exception as e:
        logger.error(f"Failed to delete notification destination {destination_id}: {e}")
        return error(
            "Failed to delete destination",
            code="NOTIFICATION_DELETE_ERROR",
            status_code=500,
        )


@router.post(
    "/notifications/test",
    summary="Test a notification destination",
    description="Send a test message for one method + config without saving.",
    responses={
        200: {"description": "Test notification sent successfully"},
        400: {"description": "Invalid notification configuration"},
        502: {"description": "Notification service connection failed"},
    },
)
def test_notification(
    payload: TestPayload, logger: Any = Depends(get_logger)
) -> JSONResponse:
    try:
        logger.debug("Serving POST /api/notifications/test (%s)", payload.method)

        method_err = _validate_method(payload.method)
        if method_err:
            return method_err

        config = load_config()
        # Resolve redacted placeholders against the stored destination so testing
        # an already-saved channel uses the real webhook, not "********".
        resolved = payload.config
        if payload.id:
            stored = next(
                (
                    d
                    for d in _destinations_as_dicts(config)
                    if isinstance(d, dict) and d.get("id") == payload.id
                ),
                None,
            )
            if stored:
                resolved = strip_redacted_placeholders(
                    payload.config, stored.get("config") or {}
                )

        manager = NotificationManager(config, logger, module_name="main")
        result = manager.send_test_to(payload.method, resolved)

        if isinstance(result, dict) and "success" in result:
            return JSONResponse(
                status_code=200 if result["success"] else 400, content=result
            )
        return ok("Test notification sent successfully", result or {})

    except ValueError as e:
        logger.error(f"Invalid notification configuration: {e}")
        return error(
            "Invalid notification configuration",
            code="NOTIFICATION_CONFIG_INVALID",
            status_code=400,
        )
    except ConnectionError as e:
        logger.error(f"Notification service connection failed: {e}")
        return error(
            "Failed to connect to notification service",
            code="NOTIFICATION_CONNECTION_FAILED",
            status_code=502,
        )
    except Exception as e:
        logger.error(f"Test notification failed: {e}")
        return error(
            "Test notification failed",
            code="NOTIFICATION_TEST_ERROR",
            status_code=500,
        )
