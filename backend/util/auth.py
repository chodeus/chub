"""
Authentication utilities for CHUB.

Provides password hashing (bcrypt) and JWT token management
for the built-in authentication system.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

# JWT configuration
JWT_ALGORITHM = "HS256"
DEFAULT_TOKEN_EXPIRY_HOURS = 24


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def generate_jwt_secret() -> str:
    """Generate a cryptographically secure random secret for JWT signing."""
    return secrets.token_urlsafe(64)


def create_access_token(
    username: str,
    jwt_secret: str,
    expires_hours: int = DEFAULT_TOKEN_EXPIRY_HOURS,
) -> str:
    """Create a JWT access token."""
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=expires_hours),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, jwt_secret: str) -> Optional[dict]:
    """
    Decode and validate a JWT access token.

    Returns the payload dict on success, None on any failure.
    """
    try:
        return jwt.decode(token, jwt_secret, algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
