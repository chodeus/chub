"""
Authentication API endpoints for CHUB.

Provides login, setup (first-run), and auth status endpoints.
"""

import hmac
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.api.utils import error, get_logger, ok
from backend.util.auth import (
    STREAM_TOKEN_EXPIRY_MINUTES,
    create_access_token,
    create_stream_token,
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


@router.get(
    "/me",
    summary="Current authenticated user",
    description="Return the username from the validated JWT session.",
)
async def current_user(request: Request) -> JSONResponse:
    """Return the authenticated user attached by AuthMiddleware."""
    username = getattr(request.state, "user", "")
    if not username:
        return error(
            "Authentication required",
            code="AUTH_REQUIRED",
            status_code=401,
        )
    return ok("Current user retrieved", {"username": username})


@router.post(
    "/logout",
    summary="Logout",
    description="Stateless JWT logout acknowledgement for frontend session cleanup.",
)
async def logout() -> JSONResponse:
    """Acknowledge logout. Token removal happens client-side."""
    return ok("Logout successful")


@router.post(
    "/stream-token",
    summary="Mint a short-lived stream token",
    description="Scope-limited token for URL-embedded auth on image/SSE routes, "
    "so the full session token never rides in a URL.",
)
async def stream_token(request: Request) -> JSONResponse:
    """Return a short-lived (scope=stream) token. Requires a full session token
    (enforced by AuthMiddleware); the stream token itself can't mint another."""
    username = getattr(request.state, "user", "") or ""
    try:
        config = load_config()
    except ConfigError:
        return error("Auth unavailable", code="AUTH_UNAVAILABLE", status_code=503)
    # First-run: no auth configured, nothing to scope — client falls back cleanly.
    if not config.auth.username or not config.auth.jwt_secret:
        return ok("Auth not configured", {"token": "", "expires_in": 0})
    token = create_stream_token(
        username or config.auth.username, config.auth.jwt_secret
    )
    return ok(
        "ok", {"token": token, "expires_in": STREAM_TOKEN_EXPIRY_MINUTES * 60}
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

    # Constant-time username compare + always run bcrypt, so an attacker
    # can't distinguish "wrong username" from "wrong password" by timing.
    username_ok = hmac.compare_digest(
        request_data.username.encode("utf-8"),
        (config.auth.username or "").encode("utf-8"),
    )
    password_ok = verify_password(
        request_data.password, config.auth.password_hash or ""
    )
    if not (username_ok and password_ok):
        # Deliberately don't echo the attempted username — logs rotate and
        # may be exposed, and this blocks a trivial enumeration channel.
        logger.warning("Failed login attempt")
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
