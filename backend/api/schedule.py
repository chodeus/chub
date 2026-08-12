"""
Schedule management API endpoints for CHUB.

Provides CRUD operations for module scheduling configuration.
Follows the same pattern as instances.py for consistency.
"""

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.api.utils import error, get_logger, ok
from backend.modules import MODULES
from backend.util.config import (
    ChubConfig,
    ConfigError,
    ScheduleBlock,
    load_config,
    save_config,
)
from backend.util.scheduler import (
    _profile_value,
    _upgradinatorr_profile_label,
    cron_next_run,
    validate_schedule,
)

router = APIRouter(
    prefix="/api",
    tags=["Schedule Management"],
    responses={
        500: {"description": "Internal server error"},
    },
)


class ScheduleUpdateRequest(BaseModel):
    """Request schema for creating or updating a module schedule."""

    module: str
    schedule: str


class ScheduleBlockInput(BaseModel):
    """One multi-block schedule entry from the editor."""

    label: str = ""
    enabled: bool = True
    schedule: str = ""
    overrides: dict = {}


class ScheduleBlocksUpdateRequest(BaseModel):
    """Replace the full set of multi-block schedules for one module."""

    module: str
    blocks: list[ScheduleBlockInput] = []


def get_config() -> ChubConfig:
    """Load and return the current configuration."""
    return load_config()


@router.get(
    "/schedule",
    summary="Get all module schedules",
    description="Retrieve all configured module schedules from configuration.",
    responses={
        200: {
            "description": "Schedules retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Schedules retrieved successfully",
                        "data": {
                            "schedule": {
                                "health_checkarr": "daily(02:00)",
                                "poster_renamerr": "weekly(Mon,03:00)",
                            }
                        },
                    }
                }
            },
        }
    },
)
async def get_all_schedules(
    config: ChubConfig = Depends(get_config), logger: Any = Depends(get_logger)
) -> JSONResponse:
    """
    Retrieve all configured module schedules.

    Returns the complete schedule configuration for all modules.
    Used by the UI for schedule management interface.

    Returns:
        Complete schedule configuration dictionary
    """
    try:
        logger.debug("Serving GET /api/schedule")
        schedule_data = config.schedule

        # Next-run timestamps for top-level modules that use a cron(...) schedule.
        # The frontend computes hourly/daily/weekly/monthly itself but can't parse
        # cron, so those would otherwise drop off the dashboard's "Upcoming" list.
        next_runs: dict[str, str] = {}
        for module_name, expr in (schedule_data or {}).items():
            nr = cron_next_run(expr)
            if nr is not None:
                next_runs[module_name] = nr.isoformat()

        # Per-instance Upgradinatorr sub-schedules. These are honored by the
        # scheduler (see _tick_upgradinatorr_profiles) but live under
        # upgradinatorr.instances_list, not config.schedule, so the UI never saw
        # them. Surface them read-only alongside the module schedules.
        sub_schedules: list[dict[str, Any]] = []
        upgradinatorr_config = getattr(config, "upgradinatorr", None)
        profiles = getattr(upgradinatorr_config, "instances_list", None) or []
        for index, profile in enumerate(profiles):
            sched = (_profile_value(profile, "schedule", "") or "").strip()
            if not sched:
                continue
            nr = cron_next_run(sched)
            sub_schedules.append(
                {
                    "module": "upgradinatorr",
                    "label": _upgradinatorr_profile_label(profile, index),
                    "schedule": sched,
                    "enabled": bool(_profile_value(profile, "enabled", True)),
                    "next_run": nr.isoformat() if nr is not None else None,
                }
            )

        # Multi-block schedules (config.schedule_blocks): module -> [blocks].
        # Each enabled block is also surfaced in sub_schedules so the dashboard
        # Upcoming list + cron next-run cover it; the raw blocks are returned
        # under schedule_blocks for the editor.
        schedule_blocks: dict[str, list[dict[str, Any]]] = {}
        blocks_by_module = getattr(config, "schedule_blocks", None) or {}
        for module_name, blocks in blocks_by_module.items():
            out_blocks: list[dict[str, Any]] = []
            for index, block in enumerate(blocks or []):
                sched = (_profile_value(block, "schedule", "") or "").strip()
                label = _profile_value(block, "label", "") or f"block {index + 1}"
                enabled = bool(_profile_value(block, "enabled", True))
                overrides = _profile_value(block, "overrides", {}) or {}
                nr = cron_next_run(sched) if sched else None
                next_run = nr.isoformat() if nr is not None else None
                out_blocks.append(
                    {
                        "label": label,
                        "enabled": enabled,
                        "schedule": sched,
                        "overrides": overrides,
                        "next_run": next_run,
                    }
                )
                if sched and enabled:
                    sub_schedules.append(
                        {
                            "module": module_name,
                            "label": label,
                            "schedule": sched,
                            "enabled": enabled,
                            "next_run": next_run,
                        }
                    )
            schedule_blocks[module_name] = out_blocks

        return ok(
            "Schedules retrieved successfully",
            {
                "schedule": schedule_data,
                "next_runs": next_runs,
                "sub_schedules": sub_schedules,
                "schedule_blocks": schedule_blocks,
            },
        )

    except Exception as e:
        logger.error(f"Error retrieving schedules: {e}")
        return error(
            "Error retrieving schedules",
            code="SCHEDULES_RETRIEVAL_ERROR",
            status_code=500,
        )


@router.get(
    "/schedule/{module_id}",
    summary="Get module schedule",
    description="Retrieve the schedule for a specific module.",
    responses={
        200: {
            "description": "Module schedule retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Schedule for 'health_checkarr' retrieved successfully",
                        "data": {
                            "module": "health_checkarr",
                            "schedule": "daily(02:00)",
                        },
                    }
                }
            },
        },
        404: {"description": "Module schedule not found"},
    },
)
async def get_module_schedule(
    module_id: str,
    config: ChubConfig = Depends(get_config),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Retrieve the schedule for a specific module.

    Returns the schedule string for the requested module, or null
    if no schedule is configured.

    Args:
        module_id: Module name (e.g., "health_checkarr", "poster_renamerr")

    Returns:
        Module schedule configuration
    """
    try:
        logger.debug(f"Serving GET /api/schedule/{module_id}")

        # Get schedule for the module (may be None)
        module_schedule = config.schedule.get(module_id)

        return ok(
            f"Schedule for '{module_id}' retrieved successfully",
            {"module": module_id, "schedule": module_schedule},
        )

    except Exception as e:
        logger.error(f"Error retrieving schedule for module {module_id}: {e}")
        return error(
            "Error retrieving schedule",
            code="SCHEDULE_RETRIEVAL_ERROR",
            status_code=500,
        )


@router.post(
    "/schedule",
    summary="Create or update module schedule",
    description="Create or update the schedule for a specific module.",
    responses={
        200: {
            "description": "Schedule created/updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Schedule for 'health_checkarr' updated successfully",
                        "data": {
                            "module": "health_checkarr",
                            "schedule": "daily(02:00)",
                        },
                    }
                }
            },
        },
        400: {"description": "Invalid module name"},
        500: {"description": "Configuration save failed"},
    },
)
async def update_module_schedule(
    data: ScheduleUpdateRequest, logger: Any = Depends(get_logger)
) -> JSONResponse:
    """
    Create or update a module schedule.

    Validates that the module name exists in the available modules list,
    then updates the schedule configuration and persists to config.yml.

    Args:
        data: Module name and schedule string

    Returns:
        Success confirmation with updated schedule details
    """
    try:
        module_name = data.module
        schedule_string = data.schedule

        logger.info(f"Updating schedule for module: {module_name}")

        # Validate module exists in MODULES registry
        if module_name not in MODULES:
            available_modules = ", ".join(sorted(MODULES.keys()))
            return error(
                f"Invalid module name: '{module_name}'. "
                f"Available modules: {available_modules}",
                code="INVALID_MODULE_NAME",
                status_code=400,
            )

        # Reject a malformed schedule up front — otherwise it persists and then
        # silently never fires (check_schedule swallows the parse error).
        try:
            validate_schedule(schedule_string)
        except ValueError as exc:
            logger.error(f"Invalid schedule '{schedule_string}': {exc}")
            return error(
                f"Invalid schedule '{schedule_string}'",
                code="INVALID_SCHEDULE",
                status_code=400,
            )

        # Load current config
        config = load_config()

        # Update schedule for the module
        config.schedule[module_name] = schedule_string

        # Save updated configuration
        save_config(config)

        logger.info(f"Successfully updated schedule for module: {module_name}")
        return ok(
            f"Schedule for '{module_name}' updated successfully",
            {"module": module_name, "schedule": schedule_string},
        )

    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Failed to update schedule for module {data.module}: {e}")
        return error(
            "Failed to update schedule",
            code="SCHEDULE_UPDATE_ERROR",
            status_code=500,
        )


@router.post(
    "/schedule/blocks",
    summary="Replace a module's multi-block schedules",
    description=(
        "Set the full list of schedule blocks for a module. Each block has its "
        "own schedule string and an overrides map applied only to that run, so "
        "one module can e.g. report daily and remove weekly."
    ),
)
async def update_module_schedule_blocks(
    data: ScheduleBlocksUpdateRequest, logger: Any = Depends(get_logger)
) -> JSONResponse:
    """Replace config.schedule_blocks[module] with the supplied blocks."""
    try:
        module_name = data.module
        if module_name not in MODULES:
            available_modules = ", ".join(sorted(MODULES.keys()))
            return error(
                f"Invalid module name: '{module_name}'. "
                f"Available modules: {available_modules}",
                code="INVALID_MODULE_NAME",
                status_code=400,
            )

        for b in data.blocks:
            try:
                validate_schedule(b.schedule)
            except ValueError as exc:
                logger.error(f"Invalid schedule in block '{b.label}': {exc}")
                return error(
                    f"Invalid schedule in block '{b.label}'",
                    code="INVALID_SCHEDULE",
                    status_code=400,
                )

        config = load_config()
        blocks = [
            ScheduleBlock(
                label=b.label,
                enabled=b.enabled,
                schedule=b.schedule,
                overrides=b.overrides or {},
            )
            for b in data.blocks
        ]
        if blocks:
            config.schedule_blocks[module_name] = blocks
        else:
            # Empty list clears the module's blocks rather than persisting [].
            config.schedule_blocks.pop(module_name, None)

        save_config(config)
        logger.info(
            f"Updated {len(blocks)} schedule block(s) for module: {module_name}"
        )
        return ok(
            f"Schedule blocks for '{module_name}' updated successfully",
            {
                "module": module_name,
                "blocks": [b.model_dump() for b in blocks],
            },
        )

    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Failed to update schedule blocks for module {data.module}: {e}")
        return error(
            "Failed to update schedule blocks",
            code="SCHEDULE_BLOCKS_UPDATE_ERROR",
            status_code=500,
        )


@router.delete(
    "/schedule/{module_id}",
    summary="Delete module schedule",
    description="Remove the schedule for a specific module from configuration.",
    responses={
        200: {
            "description": "Schedule deleted successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Schedule for 'health_checkarr' deleted successfully",
                        "data": {"module": "health_checkarr"},
                    }
                }
            },
        },
        404: {"description": "Module schedule not found"},
        500: {"description": "Configuration save failed"},
    },
)
async def delete_module_schedule(
    module_id: str, logger: Any = Depends(get_logger)
) -> JSONResponse:
    """
    Delete a module schedule from configuration.

    Removes the schedule entry for the specified module from config.yml.
    This operation is permanent.

    Args:
        module_id: Module name to remove schedule for

    Returns:
        Success confirmation with deleted module name
    """
    try:
        logger.info(f"Deleting schedule for module: {module_id}")

        # Load current config
        config = load_config()

        # Check if module has a schedule configured
        if module_id not in config.schedule:
            return error(
                f"No schedule found for module '{module_id}'",
                code="SCHEDULE_NOT_FOUND",
                status_code=404,
            )

        # Remove the schedule
        del config.schedule[module_id]

        # Save updated configuration
        save_config(config)

        logger.info(f"Successfully deleted schedule for module: {module_id}")
        return ok(
            f"Schedule for '{module_id}' deleted successfully",
            {"module": module_id},
        )

    except ConfigError:
        raise
    except Exception as e:
        logger.error(f"Failed to delete schedule for module {module_id}: {e}")
        return error(
            "Failed to delete schedule",
            code="SCHEDULE_DELETE_ERROR",
            status_code=500,
        )
