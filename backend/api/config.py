"""
Configuration management API endpoints for CHUB.

Provides configuration retrieval, updates, and validation
with support for section-based filtering and change tracking.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from backend.api.utils import (
    BODY_TOO_LARGE,
    body_too_large_error,
    error,
    get_logger,
    ok,
    read_request_json,
)
from backend.util.config import (
    config_write_lock,
    ConfigError,
    ChubConfig,
    REDACTED_PLACEHOLDER,
    SENSITIVE_FIELD_NAMES,
    SecretNotRevealable,
    load_config,
    redact_secrets,
    resolve_secret_path,
    save_config,
    strip_redacted_placeholders,
)
from backend.util.helper import dict_diff


def _reject_weak_webhook_secret(old_config: dict, new_config: dict) -> Optional[str]:
    """Return an error message if the webhook secret is being CHANGED to a new
    non-empty value shorter than 16 chars. Existing short secrets are left
    alone so old configs keep loading; empty means webhook auth is off."""
    gen_new = new_config.get("general")
    gen_old = old_config.get("general") or {}
    new_secret = (
        (gen_new.get("webhook_secret") or "").strip()
        if isinstance(gen_new, dict)
        else ""
    )
    old_secret = (gen_old.get("webhook_secret") or "").strip()
    if new_secret and new_secret != old_secret and len(new_secret) < 16:
        return "webhook_secret must be at least 16 characters (or empty to disable)"
    return None


def get_config_dep() -> ChubConfig:
    """Load and return the current configuration (FastAPI dependency)."""
    return load_config()


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
def get_config(
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
            "Configuration error",
            "CONFIG_ERROR",
            status_code=500,
        )
    except Exception as e:
        logger.error(f"Error retrieving configuration: {e}")
        return error(
            "Error retrieving configuration",
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
        incoming = await read_request_json(request)
        if incoming is BODY_TOO_LARGE:
            return body_too_large_error()
        # An unusable body must not reach the merge: it would re-save the
        # current config unchanged rather than fail the request.
        if not isinstance(incoming, dict) or not incoming:
            return error(
                "Configuration validation failed",
                "CONFIG_VALIDATION_ERROR",
                status_code=400,
            )
        logger.debug("Serving POST /api/config")

        with config_write_lock():
            current_config = load_config()
            config_dict = current_config.model_dump(mode="python")

            # The auth section (username / password_hash / jwt_secret) must never
            # be mutated through the generic config-save path: an authenticated
            # caller could otherwise blank the credentials (reopening the no-auth
            # first-run state) or overwrite the password hash. Credential changes
            # go through the dedicated auth endpoints only, so strip it here.
            if isinstance(incoming, dict) and "auth" in incoming:
                incoming.pop("auth", None)
                logger.warning(
                    "Ignored 'auth' section in POST /api/config — credentials are "
                    "managed only via the dedicated auth endpoints."
                )

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

            weak_secret_msg = _reject_weak_webhook_secret(old_config, new_config)
            if weak_secret_msg:
                return error(
                    weak_secret_msg,
                    "CONFIG_VALIDATION_ERROR",
                    status_code=400,
                )

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
            "Configuration error",
            code="CONFIG_ERROR",
            status_code=500,
        )
    except ValueError as e:
        logger.error(f"Configuration validation failed: {e}")
        return error(
            "Configuration validation failed",
            "CONFIG_VALIDATION_ERROR",
            status_code=400,
        )
    except Exception as e:
        logger.error(f"Configuration update failed: {e}")
        return error(
            "Configuration update failed",
            code="CONFIG_UPDATE_ERROR",
            status_code=500,
        )


@router.get(
    "/config/secret",
    summary="Reveal a single configured secret",
    description=(
        "Return the real value of one secret config field, resolved by dotted "
        "path against the unredacted configuration (e.g. 'tmdb.apikey'). Behind "
        "the same JWT auth as every config route; only fields whose leaf name is "
        "a known secret can be revealed, and never password_hash / jwt_secret."
    ),
)
def reveal_secret(
    path: str = Query(..., description="Dotted config path, e.g. 'tmdb.apikey'"),
    config: ChubConfig = Depends(get_config_dep),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """
    Reveal one configured secret on demand.

    Every other read path redacts secrets to ``********``; this is the single,
    deliberate, authenticated exception the UI's "show" eye-toggle calls. The
    path (never the value) is logged, the response forbids caching, and the
    resolver refuses any leaf that isn't a revealable secret.
    """
    logger.debug(f"Serving GET /api/config/secret path={path!r}")

    try:
        value = resolve_secret_path(config.model_dump(mode="python"), path)
    except SecretNotRevealable:
        return error(
            "That field is not a revealable secret",
            "SECRET_NOT_REVEALABLE",
            status_code=403,
        )
    except KeyError:
        return error(
            "Secret path not found",
            "SECRET_NOT_FOUND",
            status_code=404,
        )
    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        return error(
            "Configuration error",
            "CONFIG_ERROR",
            status_code=500,
        )

    resp = ok("Secret revealed", {"value": value})
    # The body carries a raw secret by design; keep it out of every cache.
    resp.headers["Cache-Control"] = "no-store"
    return resp


@router.get(
    "/config/gdrive-credentials",
    summary="Whether GDrive syncs fall back to rclone's shared client_id",
    description=(
        "Reports the credential sync_gdrive will actually use. The service "
        "account keyfile is stat'd server-side, so a configured but missing "
        "path reads as no credentials — which the settings form cannot tell."
    ),
)
def gdrive_credential_status(
    config: ChubConfig = Depends(get_config_dep),
    logger: Any = Depends(get_logger),
) -> JSONResponse:
    """Report whether sync_gdrive falls back to rclone's shared client_id."""
    # Imported lazily, as backend/api/main.py does — sync_gdrive pulls the
    # module stack in and config routes must stay cheap to import.
    from backend.modules.sync_gdrive import uses_shared_rclone_client_id

    sync_cfg = getattr(config, "sync_gdrive", None)
    shared = bool(sync_cfg) and uses_shared_rclone_client_id(sync_cfg)
    logger.debug(f"Serving GET /api/config/gdrive-credentials shared={shared}")
    return ok("GDrive credential status", {"shared_client_id": shared})
