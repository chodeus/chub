"""
Configuration management API endpoints for CHUB.

Provides configuration retrieval, updates, and validation
with support for section-based filtering and change tracking.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from backend.api.utils import error, get_logger, ok
from backend.util.config import (
    ConfigError,
    ChubConfig,
    REDACTED_PLACEHOLDER,
    SENSITIVE_FIELD_NAMES,
    load_config,
    redact_secrets,
    save_config,
    strip_redacted_placeholders,
)
from backend.util.helper import dict_diff


def get_config_dep() -> ChubConfig:
    """Load and return the current configuration (FastAPI dependency)."""
    return load_config()


def save_config_model(cfg: ChubConfig) -> None:
    """Save configuration model to disk."""
    save_config(cfg)


router = APIRouter(
    prefix="/api",
    tags=["Configuration"],
    responses={
        500: {"description": "Internal server error"},
        400: {"description": "Configuration validation error"},
    },
)


@router.get(
    "/config",
    summary="Get configuration",
    description="Retrieve CHUB configuration data with optional section filtering.",
    responses={
        200: {
            "description": "Configuration retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Configuration retrieved successfully",
                        "data": {"instances": {"plex": {}, "radarr": {}, "sonarr": {}}},
                    }
                }
            },
        },
        404: {"description": "Configuration section not found"},
    },
)
async def get_config(
    config: ChubConfig = Depends(get_config_dep),
    logger: Any = Depends(get_logger),
    section: Optional[str] = Query(
        None, description="Optional config section to retrieve"
    ),
) -> JSONResponse:
    """
    Retrieve CHUB configuration data.

    Returns the complete configuration or a specific section if requested.
    Used by the frontend for populating configuration forms and displaying
    current settings.

    Args:
        section: Optional section name to filter results (e.g., 'instances', 'modules')

    Returns:
        Configuration data (complete or filtered by section)
    """
    logger.debug(f"Serving GET /api/config section={section!r}")

    try:
        data = redact_secrets(config.model_dump(mode="python"))

        if section:
            if section in data:
                return ok(
                    f"Configuration section '{section}' retrieved",
                    {section: data[section]},
                )
            else:
                return error(
                    f"Configuration section '{section}' not found",
                    "SECTION_NOT_FOUND",
                    status_code=404,
                )

        return ok("Configuration retrieved successfully", data)

    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        return error(
            f"Configuration error: {str(e)}",
            "CONFIG_ERROR",
            status_code=500,
        )
    except Exception as e:
        logger.error(f"Error retrieving configuration: {e}")
        return error(
            f"Error retrieving configuration: {str(e)}",
            "CONFIG_RETRIEVAL_ERROR",
            status_code=500,
        )


@router.post(
    "/config",
    summary="Update configuration",
    description="Update CHUB configuration with validation and change tracking.",
    responses={
        200: {
            "description": "Configuration updated successfully",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "Configuration updated with 3 changes",
                        "data": {"changes_count": 3},
                    }
                }
            },
        },
        400: {"description": "Configuration validation failed"},
    },
)
async def update_config(
    request: Request, logger: Any = Depends(get_logger)
) -> JSONResponse:
    """
    Update CHUB configuration with validation.

    Accepts partial or complete configuration updates, validates them
    against the configuration schema, tracks changes for logging,
    and persists valid changes to disk.

    The request body should contain configuration data in the same
    structure as the GET endpoint returns.

    Returns:
        Confirmation of update with count of changes applied
    """
    try:
        incoming = await request.json()
        logger.debug("Serving POST /api/config")

        current_config = load_config()
        config_dict = current_config.model_dump(mode="python")

        # Merge incoming over current, but preserve real secrets when
        # the frontend sends back the redacted placeholder.
        for k, v in incoming.items():
            if isinstance(v, dict) and isinstance(config_dict.get(k), dict):
                config_dict[k] = strip_redacted_placeholders(v, config_dict[k])
            elif v == REDACTED_PLACEHOLDER and isinstance(config_dict.get(k), str):
                pass  # keep existing value
            else:
                config_dict[k] = v

        old_config = current_config.model_dump(mode="python")
        new_config = config_dict

        diffs = dict_diff(old_config, new_config)
        config_logger = logger.get_adapter("CONFIG_UPDATE")
        for path, old, new in diffs:
            # Structured secret-safe logging: redact values for sensitive fields
            field_name = path.rsplit(".", 1)[-1] if "." in path else path
            if field_name in SENSITIVE_FIELD_NAMES:
                config_logger.debug(f"Updated: {path} | [redacted]")
            else:
                config_logger.debug(f"Updated: {path} | old={old!r} | new={new!r}")

        updated_config = ChubConfig.model_validate(config_dict)
        save_config(updated_config)

        logger.info("Configuration updated successfully")
        return ok(
            f"Configuration updated with {len(diffs)} changes",
            {"changes_count": len(diffs)},
        )

    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        return error(
            f"Configuration error: {str(e)}",
            code="CONFIG_ERROR",
            status_code=500,
        )
    except ValueError as e:
        logger.error(f"Configuration validation failed: {e}")
        return error(
            f"Configuration validation failed: {str(e)}",
            "CONFIG_VALIDATION_ERROR",
            status_code=400,
        )
    except Exception as e:
        logger.error(f"Configuration update failed: {e}")
        return error(
            f"Configuration update failed: {str(e)}",
            code="CONFIG_UPDATE_ERROR",
            status_code=500,
        )
