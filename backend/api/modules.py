"""
Module execution API endpoints for CHUB.

Provides module orchestration functionality including execution,
status monitoring, and run state management.
"""

import asyncio
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.api.utils import error, get_database, get_logger, ok
from backend.util.database import ChubDB


MODULE_DESCRIPTIONS = {
    "poster_renamerr": "Match and rename poster artwork for media libraries",
    "border_replacerr": "Add or replace borders on poster images",
    "sync_gdrive": "Sync poster files from Google Drive",
    "unmatched_assets": "Report media without matching poster artwork",
    "upgradinatorr": "Trigger quality upgrade searches in Radarr/Sonarr",
    "renameinatorr": "Rename media files to preferred naming scheme",
    "health_checkarr": "Check Radarr/Sonarr for removed media entries",
    "nohl": "Find and re-search non-hardlinked media files",
    "labelarr": "Sync labels between Radarr/Sonarr and Plex",
    "jduparr": "Find and hardlink duplicate media files",
}


class RunRequest(BaseModel):
    """Request model for running a module."""

    module: str


router = APIRouter(
    prefix="/api",
    tags=["Modules"],
    responses={
        500: {"description": "Internal server error"},
        400: {"description": "Bad request or invalid module state"},
    },
)


def get_module_orchestrator(request: Request) -> Any:
    """Dependency injection for module orchestrator"""
    orchestrator = getattr(request.app.state, "module_orchestrator", None)
    if orchestrator is None:
        raise RuntimeError("ModuleOrchestrator not available in app state")
    return orchestrator


# --- New endpoints: list, history, stats ---


@router.get(
    "/modules",
    summary="List all modules",
    description="List all available modules with their status, schedule, and description.",
    responses={
        200: {
            "description": "Module list retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Retrieved 10 modules",
                        "data": {
                            "modules": [
                                {
                                    "name": "sync_gdrive",
                                    "description": "Sync poster files from Google Drive",
                                    "enabled": True,
                                    "schedule": "0 3 * * *",
                                    "running": False,
                                    "last_run": "2024-01-01T03:00:00Z",
                                    "last_run_status": "completed",
                                    "last_run_successful": True,
                                    "last_duration": 120,
                                }
                            ]
                        },
                    }
                }
            },
        }
    },
)
async def list_modules(
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
    orchestrator: Any = Depends(get_module_orchestrator),
) -> JSONResponse:
    """
    List all available modules with their current state.

    Returns every registered module with its description, enabled
    status, schedule configuration, running state, and last
    execution details for dashboard display.

    Returns:
        Complete list of modules with status and metadata
    """
    try:
        logger.debug("Serving GET /api/modules")
        from backend.modules import MODULES
        from backend.util.config import load_config

        config = load_config()
        schedule_data = config.schedule if hasattr(config, "schedule") else {}

        modules_list = []
        for name in MODULES:
            run_state = db.run_state.get_run_state(name)
            status = orchestrator.get_module_status(name)
            schedule_val = (
                schedule_data.get(name) if isinstance(schedule_data, dict) else None
            )

            modules_list.append(
                {
                    "name": name,
                    "description": MODULE_DESCRIPTIONS.get(name, ""),
                    "enabled": schedule_val is not None
                    and schedule_val != ""
                    and schedule_val is not None,
                    "schedule": schedule_val,
                    "running": status.get("running", False),
                    "last_run": run_state.get("last_run") if run_state else None,
                    "last_run_status": run_state.get("last_run_status")
                    if run_state
                    else None,
                    "last_run_successful": run_state.get("last_run_successful")
                    if run_state
                    else None,
                    "last_duration": run_state.get("last_duration")
                    if run_state
                    else None,
                }
            )

        return ok(f"Retrieved {len(modules_list)} modules", {"modules": modules_list})
    except Exception as e:
        logger.error(f"Error listing modules: {e}")
        return error(
            f"Error listing modules: {str(e)}",
            code="MODULES_LIST_ERROR",
            status_code=500,
        )


@router.get(
    "/modules/history",
    summary="Get module execution history",
    description="Retrieve execution history from the jobs table with optional filtering.",
    responses={
        200: {
            "description": "Module execution history retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Retrieved 15 history entries",
                        "data": {
                            "history": [
                                {
                                    "id": 1,
                                    "type": "module_run",
                                    "module_name": "sync_gdrive",
                                    "status": "completed",
                                    "created_at": "2024-01-01T03:00:00Z",
                                }
                            ]
                        },
                    }
                }
            },
        }
    },
)
async def get_modules_history(
    module: Optional[str] = Query(None, description="Filter by module name"),
    status: Optional[str] = Query(None, description="Filter by job status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, description="Number of entries to skip"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Retrieve module execution history from the jobs table.

    Returns completed and in-progress module execution records
    with optional filtering by module name and job status.
    Supports pagination via limit and offset.

    Args:
        module: Filter results to a specific module name
        status: Filter results by job status (e.g. completed, failed)
        limit: Maximum number of history entries to return
        offset: Number of entries to skip for pagination

    Returns:
        Paginated list of module execution history entries
    """
    try:
        logger.debug("Serving GET /api/modules/history")
        result = db.worker.list_jobs(
            status=status,
            limit=limit,
            offset=offset,
            job_type="module_run",
            module_name=module,
        )
        if isinstance(result, dict) and "data" in result:
            jobs = result.get("data", {}).get("jobs", [])
            total = result.get("data", {}).get("total")
        else:
            jobs = result if isinstance(result, list) else []
            total = None

        # Surface module_name for the frontend (extracted from payload JSON).
        for job in jobs:
            payload = job.get("payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (json.JSONDecodeError, TypeError):
                    payload = {}
            job["module_name"] = (
                payload.get("module_name", "") if isinstance(payload, dict) else ""
            )

        return ok(
            f"Retrieved {len(jobs)} history entries",
            {"history": jobs, "total": total, "limit": limit, "offset": offset},
        )
    except Exception as e:
        logger.error(f"Error retrieving module history: {e}")
        return error(
            f"Error retrieving history: {str(e)}",
            code="MODULE_HISTORY_ERROR",
            status_code=500,
        )


@router.get(
    "/modules/stats",
    summary="Get module statistics",
    description="Retrieve aggregated module execution statistics and run states.",
    responses={
        200: {
            "description": "Module statistics retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Module statistics retrieved",
                        "data": {
                            "job_stats": {
                                "total": 100,
                                "completed": 95,
                                "failed": 5,
                            },
                            "run_states": [
                                {
                                    "module_name": "sync_gdrive",
                                    "last_run": "2024-01-01T03:00:00Z",
                                    "last_run_status": "completed",
                                }
                            ],
                        },
                    }
                }
            },
        }
    },
)
async def get_modules_stats(
    module: Optional[str] = Query(None, description="Filter by module name"),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Retrieve aggregated module execution statistics.

    Returns job execution counts and run state information
    for all modules or a specific module when filtered.

    Args:
        module: Filter statistics to a specific module name

    Returns:
        Job statistics and run state data
    """
    try:
        logger.debug("Serving GET /api/modules/stats")
        job_stats = db.worker.job_stats()
        run_states = db.run_state.get_all()

        stats = {
            "job_stats": job_stats,
            "run_states": run_states,
        }

        if module:
            stats["run_states"] = [
                r for r in run_states if r.get("module_name") == module
            ]

        return ok("Module statistics retrieved", stats)
    except Exception as e:
        logger.error(f"Error retrieving module stats: {e}")
        return error(
            f"Error retrieving stats: {str(e)}",
            code="MODULE_STATS_ERROR",
            status_code=500,
        )


@router.get(
    "/modules/run-states",
    summary="Get all module run states",
    description="Retrieve run state information for all registered modules.",
    responses={
        200: {
            "description": "Run states retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Retrieved 5 run states",
                        "data": {
                            "sync_gdrive": {
                                "last_run": "2024-01-01T12:00:00Z",
                                "status": "completed",
                                "duration": 120,
                            }
                        },
                    }
                }
            },
        }
    },
)
async def get_all_run_states(
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Retrieve run state information for all modules.

    Returns execution history and current state for all
    registered CHUB modules including timestamps, durations,
    and execution results. Returns as an object keyed by module name.

    Returns:
        Complete run state information for all modules
    """
    try:
        run_states = db.run_state.get_all()

        # Convert array to object keyed by module_name for frontend consumption
        states_by_name = {}
        for state in run_states:
            name = state.get("module_name")
            if name:
                # Add 'status' alias for frontend compatibility
                state["status"] = state.get("last_run_status", "unknown")
                states_by_name[name] = state

        # Overlay running status from active jobs
        orchestrator = request.app.state.module_orchestrator
        if orchestrator:
            from backend.modules import MODULES

            for mod_name in MODULES:
                job_status = orchestrator.get_module_status(mod_name)
                if job_status.get("running"):
                    if mod_name in states_by_name:
                        states_by_name[mod_name]["status"] = "running"
                        states_by_name[mod_name]["job_id"] = job_status.get("job_id")
                    else:
                        states_by_name[mod_name] = {
                            "module_name": mod_name,
                            "status": "running",
                            "job_id": job_status.get("job_id"),
                        }

        return ok(
            f"Retrieved {len(run_states)} run states", data=states_by_name
        )

    except Exception as e:
        logger.error(f"Error getting run states: {e}")
        return error(
            f"Error getting run states: {str(e)}",
            code="RUN_STATE_ERROR",
            status_code=500,
        )



@router.get(
    "/modules/events",
    summary="Module status event stream",
    description="Server-Sent Events stream for real-time module status updates.",
)
async def module_events(request: Request):
    """
    SSE endpoint for real-time module status updates.

    Opens a persistent connection and pushes status changes as they
    occur. More efficient than polling — the server checks internally
    and only pushes when state changes.

    Events are JSON objects with fields:
    - event: Type of change (status_change, progress)
    - module: Module name
    - status: Current status (running, success, error, cancelled)
    - progress: Progress percentage (0-100) when available
    """
    from backend.modules import MODULES

    async def event_generator():
        previous_states = {}
        try:
            while True:
                if await request.is_disconnected():
                    break

                # Poll current states from database
                try:
                    with ChubDB(request.app.state.logger, quiet=True) as db:
                        run_states = db.run_state.get_all()
                        states_by_name = {}
                        for state in run_states:
                            name = state.get("module_name")
                            if name:
                                states_by_name[name] = {
                                    "status": state.get("last_run_status", "unknown"),
                                    "last_run": state.get("last_run"),
                                }

                        # Check for running jobs and their progress
                        orchestrator = request.app.state.module_orchestrator
                        if orchestrator:
                            for mod_name in MODULES:
                                job_status = orchestrator.get_module_status(mod_name)
                                if job_status.get("running"):
                                    job_id = job_status.get("job_id")
                                    job = db.worker.get_job_by_id("jobs", job_id) if job_id else None
                                    progress = job.get("progress", 0) if job else 0
                                    states_by_name[mod_name] = {
                                        "status": "running",
                                        "job_id": job_id,
                                        "progress": progress,
                                    }

                    # Detect changes and emit events
                    for name, state in states_by_name.items():
                        prev = previous_states.get(name, {})
                        if state != prev:
                            event_data = json.dumps({
                                "event": "status_change",
                                "module": name,
                                **state,
                            })
                            yield f"data: {event_data}\n\n"

                    previous_states = states_by_name

                except Exception as sse_err:
                    # The SSE loop must not crash, but silently swallowing errors
                    # made "frozen stream" bugs invisible. Log and continue.
                    log = request.app.state.logger.get_adapter("SSE")
                    log.debug(f"SSE poll error (continuing): {sse_err}")

                await asyncio.sleep(2)

        except asyncio.CancelledError:  # Expected on client disconnect
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/modules/status",
    summary="Get module status",
    description="Retrieve the current execution status of a specific module.",
    responses={
        200: {
            "description": "Module status retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Status retrieved for module sync_gdrive",
                        "data": {
                            "running": False,
                            "last_run": "2024-01-01T12:00:00Z",
                            "status": "completed",
                        },
                    }
                }
            },
        }
    },
)
async def module_status(
    request: Request,
    module: str,
    logger: Any = Depends(get_logger),
    orchestrator: Any = Depends(get_module_orchestrator),
) -> JSONResponse:
    """
    Get the current execution status of a module.

    Returns detailed status information including whether the
    module is currently running, last execution time, and
    current state for monitoring purposes.

    Args:
        module: Name of the module to check status for

    Returns:
        Module status with execution state and timestamps
    """
    try:
        status = orchestrator.get_module_status(module)

        return ok(f"Status retrieved for module {module}", data=status)

    except Exception as e:
        logger.error(f"Error getting status for module {module}: {e}")
        return error(
            f"Error getting module status: {str(e)}",
            code="MODULE_STATUS_ERROR",
            status_code=500,
        )


# --- Parameterized module name endpoints ---


@router.get(
    "/modules/{name}",
    summary="Get module details",
    description="Retrieve detailed information about a specific module by name.",
    responses={
        200: {
            "description": "Module details retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Module 'sync_gdrive' details retrieved",
                        "data": {
                            "name": "sync_gdrive",
                            "description": "Sync poster files from Google Drive",
                            "enabled": True,
                            "schedule": "0 3 * * *",
                            "running": False,
                            "run_state": {},
                            "config": {},
                        },
                    }
                }
            },
        },
        404: {"description": "Module not found"},
    },
)
async def get_module(
    name: str,
    request: Request,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
    orchestrator: Any = Depends(get_module_orchestrator),
) -> JSONResponse:
    """
    Get detailed information about a specific module.

    Returns the module's description, schedule, running state,
    full run state history, and current configuration.

    Args:
        name: The module name to retrieve details for

    Returns:
        Complete module details including config and run state
    """
    try:
        logger.debug(f"Serving GET /api/modules/{name}")
        from backend.modules import MODULES
        from backend.util.config import load_config

        if name not in MODULES:
            return error(
                f"Module '{name}' not found", code="MODULE_NOT_FOUND", status_code=404
            )

        config = load_config()
        config_data = config.model_dump(mode="python")
        schedule_data = config_data.get("schedule", {})

        run_state = db.run_state.get_run_state(name)
        status = orchestrator.get_module_status(name)
        schedule_val = schedule_data.get(name)

        module_info = {
            "name": name,
            "description": MODULE_DESCRIPTIONS.get(name, ""),
            "enabled": schedule_val is not None and schedule_val != "",
            "schedule": schedule_val,
            "running": status.get("running", False),
            "run_state": run_state,
            "config": config_data.get(name, {}),
        }

        return ok(f"Module '{name}' details retrieved", module_info)
    except Exception as e:
        logger.error(f"Error retrieving module {name}: {e}")
        return error(
            f"Error retrieving module: {str(e)}",
            code="MODULE_GET_ERROR",
            status_code=500,
        )


@router.post(
    "/modules/{name}/execute",
    summary="Execute module by name",
    description="Execute a specific module immediately by name.",
    responses={
        200: {
            "description": "Module executed successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Module sync_gdrive completed",
                        "data": {
                            "module": "sync_gdrive",
                            "status": "completed",
                        },
                    }
                }
            },
        },
        400: {"description": "Module already running"},
        404: {"description": "Module not found"},
    },
)
async def execute_module_by_name(
    name: str,
    request: Request,
    logger: Any = Depends(get_logger),
    orchestrator: Any = Depends(get_module_orchestrator),
) -> JSONResponse:
    """
    Execute a specific module immediately by name.

    Runs the module through the orchestrator with duplicate
    execution prevention. Blocks until the module completes
    and returns the execution result.

    Args:
        name: The module name to execute

    Returns:
        Module execution result with status and output data
    """
    try:
        logger.debug(f"Serving POST /api/modules/{name}/execute")
        from backend.modules import MODULES

        if name not in MODULES:
            return error(
                f"Module '{name}' not found", code="MODULE_NOT_FOUND", status_code=404
            )

        status = orchestrator.get_module_status(name)
        if status["running"]:
            return error(
                f"Module {name} is already running",
                code="MODULE_ALREADY_RUNNING",
                status_code=400,
            )

        result = orchestrator.run_module_async(name, origin="web")
        if result["success"]:
            job_id = result["data"]["job_id"]
            return ok(
                f"Module {name} started",
                data={"module": name, "status": "started", "job_id": job_id},
            )
        return error(
            result["message"],
            code=result.get("error_code", "MODULE_ENQUEUE_FAILED"),
            status_code=500,
        )
    except Exception as e:
        logger.error(f"Error executing module {name}: {e}")
        return error(
            f"Error executing module: {str(e)}",
            code="MODULE_EXECUTE_ERROR",
            status_code=500,
        )


@router.get(
    "/modules/{name}/status/{job_id}",
    summary="Get job status",
    description="Retrieve the status of a specific module execution job.",
    responses={
        200: {
            "description": "Job status retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Job status retrieved",
                        "data": {
                            "id": 123,
                            "type": "module_run",
                            "status": "completed",
                        },
                    }
                }
            },
        },
        404: {"description": "Job not found"},
    },
)
async def get_module_job_status(
    name: str,
    job_id: int,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Get the status of a specific module execution job.

    Returns the complete job record including status, timing,
    and any output data for monitoring execution progress.

    Args:
        name: The module name the job belongs to
        job_id: The unique job identifier

    Returns:
        Complete job status and execution details
    """
    try:
        logger.debug(f"Serving GET /api/modules/{name}/status/{job_id}")
        job = db.worker.get_job_by_id("jobs", job_id)
        if not job:
            return error("Job not found", code="JOB_NOT_FOUND", status_code=404)
        return ok("Job status retrieved", job)
    except Exception as e:
        logger.error(f"Error retrieving job {job_id}: {e}")
        return error(
            f"Error retrieving job status: {str(e)}",
            code="JOB_STATUS_ERROR",
            status_code=500,
        )


@router.get(
    "/modules/{name}/schema",
    summary="Get module config schema",
    description="Retrieve the JSON schema for a module's configuration model.",
    responses={
        200: {
            "description": "Module config schema retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Schema for module 'sync_gdrive'",
                        "data": {
                            "schema": {
                                "type": "object",
                                "properties": {},
                            }
                        },
                    }
                }
            },
        },
        404: {"description": "No config schema found for module"},
    },
)
async def get_module_schema(
    name: str,
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Get the JSON schema for a module's configuration model.

    Returns the Pydantic model JSON schema for the specified
    module's configuration section, useful for dynamic form
    generation in the frontend.

    Args:
        name: The module name to retrieve the schema for

    Returns:
        JSON schema for the module's configuration
    """
    try:
        logger.debug(f"Serving GET /api/modules/{name}/schema")
        from backend.util.config import ChubConfig

        if name not in ChubConfig.model_fields:
            return error(
                f"No config schema for module '{name}'",
                code="SCHEMA_NOT_FOUND",
                status_code=404,
            )

        field_info = ChubConfig.model_fields[name]
        schema = field_info.annotation.model_json_schema()
        return ok(f"Schema for module '{name}'", {"schema": schema})
    except Exception as e:
        logger.error(f"Error retrieving schema for {name}: {e}")
        return error(
            f"Error retrieving schema: {str(e)}", code="SCHEMA_ERROR", status_code=500
        )


@router.put(
    "/modules/{name}/config",
    summary="Update module config",
    description="Update a module's configuration section with new values.",
    responses={
        200: {
            "description": "Module configuration updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Configuration for 'sync_gdrive' updated",
                        "data": {"module": "sync_gdrive"},
                    }
                }
            },
        },
        400: {"description": "Configuration validation failed"},
        404: {"description": "Module not found in configuration"},
    },
)
async def update_module_config(
    name: str,
    request: Request,
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Update a module's configuration section.

    Validates the provided configuration against the module's
    Pydantic model and persists the changes to the config file.

    Args:
        name: The module name to update configuration for

    Returns:
        Confirmation of the configuration update
    """
    try:
        payload = await request.json()
        logger.debug(f"Serving PUT /api/modules/{name}/config")
        from backend.util.config import ChubConfig, load_config, save_config

        if name not in ChubConfig.model_fields:
            return error(
                f"Module '{name}' not found in config",
                code="MODULE_NOT_FOUND",
                status_code=404,
            )

        config = load_config()
        config_dict = config.model_dump(mode="python")
        config_dict[name] = payload

        updated = ChubConfig.model_validate(config_dict)
        save_config(updated)

        return ok(f"Configuration for '{name}' updated", {"module": name})
    except ValueError as e:
        return error(
            f"Config validation failed: {str(e)}",
            code="CONFIG_VALIDATION_ERROR",
            status_code=400,
        )
    except Exception as e:
        logger.error(f"Error updating config for {name}: {e}")
        return error(
            f"Error updating config: {str(e)}",
            code="CONFIG_UPDATE_ERROR",
            status_code=500,
        )


@router.patch(
    "/modules/{name}",
    summary="Toggle module",
    description="Enable or disable a module by setting or clearing its schedule.",
    responses={
        200: {
            "description": "Module toggled successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Module 'sync_gdrive' enabled",
                        "data": {
                            "module": "sync_gdrive",
                            "enabled": True,
                        },
                    }
                }
            },
        }
    },
)
async def toggle_module(
    name: str,
    request: Request,
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Enable or disable a module by setting or clearing its schedule.

    Toggles the module's enabled state in the configuration file.
    Enabling a module without a schedule sets it to a null schedule
    (enabled but not auto-scheduled).

    Args:
        name: The module name to toggle

    Returns:
        Confirmation with the new enabled state
    """
    try:
        payload = await request.json()
        enabled = payload.get("enabled")
        logger.debug(f"Serving PATCH /api/modules/{name} enabled={enabled}")
        from backend.util.config import load_config, save_config

        config = load_config()
        config_dict = config.model_dump(mode="python")
        schedule = config_dict.get("schedule", {})

        if enabled:
            if not schedule.get(name):
                schedule[name] = None  # Enabled but no schedule set
        else:
            schedule[name] = None

        config_dict["schedule"] = schedule
        from backend.util.config import ChubConfig

        updated = ChubConfig.model_validate(config_dict)
        save_config(updated)

        return ok(
            f"Module '{name}' {'enabled' if enabled else 'disabled'}",
            {"module": name, "enabled": enabled},
        )
    except Exception as e:
        logger.error(f"Error toggling module {name}: {e}")
        return error(
            f"Error toggling module: {str(e)}",
            code="MODULE_TOGGLE_ERROR",
            status_code=500,
        )


@router.get(
    "/modules/{name}/history",
    summary="Get module-specific history",
    description="Retrieve execution history for a specific module with pagination.",
    responses={
        200: {
            "description": "Module history retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Retrieved 10 history entries for sync_gdrive",
                        "data": {
                            "history": [
                                {
                                    "id": 1,
                                    "type": "module_run",
                                    "module_name": "sync_gdrive",
                                    "status": "completed",
                                }
                            ]
                        },
                    }
                }
            },
        }
    },
)
async def get_module_history(
    name: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, description="Number of entries to skip"),
    status: Optional[str] = Query(None),
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Get execution history for a specific module.

    Returns completed and in-progress execution records for
    the named module with optional status filtering and
    pagination support via limit and offset.

    Args:
        name: The module name to retrieve history for
        limit: Maximum number of history entries to return
        offset: Number of entries to skip for pagination
        status: Filter results by job status

    Returns:
        Paginated list of execution history entries for the module
    """
    try:
        logger.debug(f"Serving GET /api/modules/{name}/history")
        result = db.worker.list_jobs(
            status=status,
            limit=limit,
            offset=offset,
            job_type="module_run",
            module_name=name,
        )
        jobs = (
            result.get("data", {}).get("jobs", [])
            if isinstance(result, dict)
            else (result if isinstance(result, list) else [])
        )
        for job in jobs:
            job["module_name"] = name

        return ok(
            f"Retrieved {len(jobs)} history entries for {name}",
            {"history": jobs, "limit": limit, "offset": offset},
        )
    except Exception as e:
        logger.error(f"Error retrieving history for {name}: {e}")
        return error(
            f"Error retrieving history: {str(e)}",
            code="MODULE_HISTORY_ERROR",
            status_code=500,
        )


@router.get(
    "/modules/{name}/stats",
    summary="Get module-specific stats",
    description="Retrieve execution statistics for a specific module.",
    responses={
        200: {
            "description": "Module statistics retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Statistics for module 'sync_gdrive'",
                        "data": {
                            "run_state": {
                                "last_run": "2024-01-01T03:00:00Z",
                                "last_run_status": "completed",
                            },
                            "job_stats": {},
                        },
                    }
                }
            },
        }
    },
)
async def get_module_specific_stats(
    name: str,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Get execution statistics for a specific module.

    Returns the module's run state history and aggregated
    job statistics for monitoring and reporting.

    Args:
        name: The module name to retrieve statistics for

    Returns:
        Run state and job statistics for the module
    """
    try:
        logger.debug(f"Serving GET /api/modules/{name}/stats")
        run_state = db.run_state.get_run_state(name)
        job_stats = db.worker.job_stats()

        return ok(
            f"Statistics for module '{name}'",
            {
                "run_state": run_state,
                "job_stats": job_stats,
            },
        )
    except Exception as e:
        logger.error(f"Error retrieving stats for {name}: {e}")
        return error(
            f"Error retrieving stats: {str(e)}",
            code="MODULE_STATS_ERROR",
            status_code=500,
        )


@router.delete(
    "/modules/{name}/execution/{job_id}",
    summary="Cancel module execution",
    description="Cancel a running module execution by job ID.",
    responses={
        200: {
            "description": "Cancellation result",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Cancellation requested for module poster_renamerr job 42",
                        "data": {"module": "poster_renamerr", "job_id": 42, "status": "cancelling"},
                    }
                }
            },
        }
    },
)
async def cancel_module_execution(
    name: str,
    job_id: int,
    logger: Any = Depends(get_logger),
    db: ChubDB = Depends(get_database),
) -> JSONResponse:
    """
    Cancel a running module execution.

    Signals cooperative cancellation for the specified job. The module
    will stop at its next cancellation check point.

    Args:
        name: The module name the job belongs to
        job_id: The unique job identifier to cancel

    Returns:
        Cancellation result
    """
    from backend.util.job_processor import request_cancellation

    try:
        logger.debug(f"Serving DELETE /api/modules/{name}/execution/{job_id}")

        # Verify the job exists and is running
        job = db.worker.get_job_by_id("jobs", job_id)
        if not job:
            return error(
                f"Job {job_id} not found",
                code="JOB_NOT_FOUND",
                status_code=404,
            )

        if job.get("status") != "running":
            return error(
                f"Job {job_id} is not running (status: {job.get('status')})",
                code="JOB_NOT_RUNNING",
                status_code=400,
            )

        # Signal the cancel event
        if request_cancellation(job_id):
            # Update job status to reflect cancellation is in progress
            db.worker.execute_query(
                "UPDATE jobs SET status='cancelled' WHERE id=? AND status='running'",
                (job_id,),
            )
            logger.info(f"Cancellation requested for module {name} job {job_id}")
            return ok(
                f"Cancellation requested for module {name} job {job_id}",
                {"module": name, "job_id": job_id, "status": "cancelling"},
            )
        else:
            return error(
                f"Job {job_id} has no active cancel handle — it may have already finished",
                code="NO_CANCEL_HANDLE",
                status_code=409,
            )

    except Exception as e:
        logger.error(f"Error cancelling job {job_id}: {e}", exc_info=True)
        return error(
            f"Error cancelling execution: {str(e)}",
            code="CANCEL_ERROR",
            status_code=500,
        )


@router.post(
    "/modules/{name}/test",
    summary="Test module",
    description="Probe each configured instance for the named module and "
    "return per-instance connectivity (healthy / unhealthy / timeout / "
    "unreachable / blocked / not_found).",
    responses={
        200: {
            "description": "Per-instance connectivity results",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Module 'upgradinatorr' test: 2/3 instances healthy",
                        "data": {
                            "results": [
                                {
                                    "instance": "radarr-1",
                                    "service": "radarr",
                                    "status": "healthy",
                                    "status_code": 200,
                                },
                            ]
                        },
                    }
                }
            },
        },
        404: {"description": "Module not found"},
    },
)
async def test_module(
    name: str,
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Test module connectivity and configuration.

    Validates that the module can connect to its required
    services and that its configuration is valid.

    Args:
        name: The module name to test

    Returns:
        Test result with connectivity status
    """
    try:
        logger.debug(f"Serving POST /api/modules/{name}/test")
        from backend.modules import MODULES
        from backend.util.config import load_config

        if name not in MODULES:
            return error(
                f"Module '{name}' not found",
                code="MODULE_NOT_FOUND",
                status_code=404,
            )

        config = load_config()
        module_config = getattr(config, name, None)
        if not module_config:
            return ok(f"Module '{name}' has no testable configuration", {"results": []})

        # Get instances from module config
        instances_list = getattr(module_config, "instances", None) or getattr(
            module_config, "instances_list", None
        )
        if not instances_list:
            return ok(
                f"Module '{name}' has no configured instances to test",
                {"results": []},
            )

        import requests as http_requests

        results = []
        for inst in instances_list:
            inst_name = (
                inst
                if isinstance(inst, str)
                else inst.get("instance", str(inst))
                if isinstance(inst, dict)
                else str(inst)
            )
            if isinstance(inst, dict) and not inst.get("instance"):
                inst_name = next(iter(inst.keys()), str(inst))

            details = None
            service = None
            for svc in ["radarr", "sonarr", "lidarr", "plex"]:
                svc_instances = getattr(config.instances, svc, {})
                if inst_name in svc_instances:
                    details = svc_instances[inst_name]
                    service = svc
                    break

            if not details:
                results.append({"instance": inst_name, "status": "not_found"})
                continue

            url = details.url.rstrip("/") if details.url else ""
            api = details.api or ""

            if service == "plex":
                headers = {"X-Plex-Token": api} if api else {}
                test_url = f"{url}/library/sections"
            else:
                headers = {"X-Api-Key": api} if api else {}
                test_url = f"{url}/api/v3/system/status"

            from backend.util.ssrf_guard import is_safe_url

            safe, reason = is_safe_url(test_url)
            if not safe:
                results.append(
                    {
                        "instance": inst_name,
                        "service": service,
                        "status": "blocked",
                        "error": f"URL refused: {reason}",
                    }
                )
                continue

            try:
                resp = http_requests.get(test_url, headers=headers, timeout=5)
                results.append(
                    {
                        "instance": inst_name,
                        "service": service,
                        "status": "healthy" if resp.ok else "unhealthy",
                        "status_code": resp.status_code,
                    }
                )
            except http_requests.exceptions.Timeout:
                results.append(
                    {"instance": inst_name, "service": service, "status": "timeout"}
                )
            except http_requests.exceptions.ConnectionError:
                results.append(
                    {"instance": inst_name, "service": service, "status": "unreachable"}
                )
            except Exception as exc:
                results.append(
                    {
                        "instance": inst_name,
                        "service": service,
                        "status": "error",
                        "error": str(exc),
                    }
                )

        healthy = sum(1 for r in results if r.get("status") == "healthy")
        return ok(
            f"Module '{name}' test: {healthy}/{len(results)} instances healthy",
            {"results": results},
        )

    except Exception as e:
        logger.error(f"Error testing module {name}: {e}")
        return error(
            f"Error testing module: {str(e)}",
            code="MODULE_TEST_ERROR",
            status_code=500,
        )


# --- Existing endpoints below ---


@router.post(
    "/modules/run",
    summary="Execute module",
    description="Execute a CHUB module immediately with real-time status monitoring.",
    responses={
        200: {
            "description": "Module executed successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Module sync_gdrive completed successfully",
                        "data": {"module": "sync_gdrive", "status": "completed"},
                    }
                }
            },
        },
        400: {"description": "Module already running or invalid module name"},
    },
)
async def run_module(
    request: Request,
    data: RunRequest,
    logger: Any = Depends(get_logger),
    orchestrator: Any = Depends(get_module_orchestrator),
) -> JSONResponse:
    """
    Execute a CHUB module immediately.

    Runs the specified module through the job queue system with
    real-time monitoring. Prevents duplicate executions of the
    same module and provides immediate feedback on completion.

    Args:
        data: Request containing the module name to execute

    Returns:
        Module execution result with status and any output data
    """
    module = data.module
    logger.debug("Serving POST /api/run for module: %s", module)

    try:
        # Check if module is already running
        status = orchestrator.get_module_status(module)
        if status["running"]:
            logger.warning(f"Module {module} is already running")
            return error(
                f"Module {module} is already running",
                code="MODULE_ALREADY_RUNNING",
                status_code=400,
            )

        # Enqueue module for async execution (non-blocking)
        result = orchestrator.run_module_async(module, origin="web")

        if result["success"]:
            job_id = result["data"]["job_id"]
            logger.info(f"Enqueued module: {module} (job {job_id})")
            return ok(
                f"Module {module} started",
                data={"module": module, "status": "started", "job_id": job_id},
            )
        else:
            logger.error(f"Failed to enqueue module {module}: {result['message']}")
            return error(
                result["message"],
                code=result.get("error_code", "MODULE_ENQUEUE_FAILED"),
                status_code=500,
            )

    except Exception as e:
        logger.error(f"Error running module {module}: {e}", exc_info=True)
        return error(
            f"Error running module: {str(e)}",
            code="MODULE_START_ERROR",
            status_code=500,
        )
