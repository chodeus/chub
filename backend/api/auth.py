"""
Authentication API endpoints for CHUB.

Provides login, setup (first-run), and auth status endpoints.
"""

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.api.utils import error, get_logger, ok
from backend.util.auth import (
    create_access_token,
    generate_jwt_secret,
    hash_password,
    verify_password,
)
from backend.util.config import (
    ConfigError,
    load_config,
    save_config,
)
from backend.util.rate_limiter import login_limiter

router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"],
)


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str
    password: str


def _is_auth_configured() -> bool:
    """Check if authentication has been set up."""
    try:
        config = load_config()
        return bool(config.auth.username and config.auth.password_hash)
    except ConfigError:
        return False


@router.get(
    "/status",
    summary="Auth status",
    description="Check whether authentication is configured and required.",
)
async def auth_status(logger: Any = Depends(get_logger)) -> JSONResponse:
    """Return whether auth is set up. Used by frontend to decide login vs setup."""
    configured = _is_auth_configured()
    return ok(
        "Auth status retrieved",
        {"configured": configured, "required": True},
    )


@router.post(
    "/setup",
    summary="First-run auth setup",
    description="Set initial admin credentials. Only works when no credentials are configured.",
)
async def setup_auth(
    request_data: SetupRequest, logger: Any = Depends(get_logger)
) -> JSONResponse:
    """
    Create initial admin credentials.

    This endpoint is only available before authentication is configured.
    Once credentials are set, this endpoint returns 403.
    """
    if _is_auth_configured():
        return error(
            "Authentication is already configured",
            code="AUTH_ALREADY_CONFIGURED",
            status_code=403,
        )

    if not request_data.username or not request_data.password:
        return error(
            "Username and password are required",
            code="AUTH_SETUP_INVALID",
            status_code=400,
        )

    if len(request_data.password) < 8:
        return error(
            "Password must be at least 8 characters",
            code="AUTH_PASSWORD_TOO_SHORT",
            status_code=400,
        )

    try:
        config = load_config()
        config.auth.username = request_data.username
        config.auth.password_hash = hash_password(request_data.password)
        config.auth.jwt_secret = generate_jwt_secret()
        save_config(config)

        token = create_access_token(
            config.auth.username,
            config.auth.jwt_secret,
            config.auth.token_expiry_hours,
        )

        logger.info(f"Auth setup completed for user: {request_data.username}")
        return ok(
            "Authentication configured successfully",
            {"token": token, "username": config.auth.username},
        )
    except ConfigError as e:
        logger.error(f"Auth setup failed: {e}")
        return error(
            f"Failed to save auth configuration: {e}",
            code="AUTH_SETUP_ERROR",
            status_code=500,
        )


@router.post(
    "/login",
    summary="Login",
    description="Authenticate with username and password to receive a JWT token.",
    dependencies=[Depends(login_limiter)],
)
async def login(
    request_data: LoginRequest, logger: Any = Depends(get_logger)
) -> JSONResponse:
    """Validate credentials and return a JWT access token."""
    if not _is_auth_configured():
        return error(
            "Authentication is not configured. Use /api/auth/setup first.",
            code="AUTH_NOT_CONFIGURED",
            status_code=403,
        )

    try:
        config = load_config()
    except ConfigError as e:
        logger.error(f"Login failed — config error: {e}")
        return error(
            "Server configuration error",
            code="CONFIG_ERROR",
            status_code=500,
        )

    if (
        request_data.username != config.auth.username
        or not verify_password(request_data.password, config.auth.password_hash)
    ):
        logger.warning(f"Failed login attempt for user: {request_data.username}")
        return error(
            "Invalid username or password",
            code="AUTH_INVALID_CREDENTIALS",
            status_code=401,
        )

    token = create_access_token(
        config.auth.username,
        config.auth.jwt_secret,
        config.auth.token_expiry_hours,
    )

    logger.info(f"User logged in: {request_data.username}")
    return ok(
        "Login successful",
        {"token": token, "username": config.auth.username},
    )
