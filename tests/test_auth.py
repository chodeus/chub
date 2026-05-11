"""Tests for backend/util/auth.py — bcrypt + JWT helpers."""

import time

import jwt

from backend.util.auth import (
    JWT_ALGORITHM,
    create_access_token,
    decode_access_token,
    generate_jwt_secret,
    hash_password,
    verify_password,
)


def test_hash_password_returns_string():
    h = hash_password("hunter2")
    assert isinstance(h, str)
    assert h != "hunter2"


def test_verify_password_succeeds_with_correct_password():
    h = hash_password("hunter2")
    assert verify_password("hunter2", h) is True


def test_verify_password_fails_with_wrong_password():
    h = hash_password("hunter2")
    assert verify_password("wrong", h) is False


def test_hash_password_unique_per_call():
    """bcrypt salts each hash; same password yields different hashes."""
    assert hash_password("same") != hash_password("same")


def test_generate_jwt_secret_long_and_unique():
    a = generate_jwt_secret()
    b = generate_jwt_secret()
    assert isinstance(a, str)
    assert len(a) >= 32
    assert a != b


def test_create_and_decode_token_roundtrip():
    secret = generate_jwt_secret()
    token = create_access_token("alice", secret)
    payload = decode_access_token(token, secret)
    assert payload is not None
    assert payload["sub"] == "alice"
    assert "exp" in payload
    assert "iat" in payload


def test_decode_with_wrong_secret_returns_none():
    secret = generate_jwt_secret()
    token = create_access_token("bob", secret)
    other_secret = generate_jwt_secret()
    assert decode_access_token(token, other_secret) is None


def test_decode_expired_token_returns_none():
    secret = generate_jwt_secret()
    # Create a token that's already expired
    expired_payload = {
        "sub": "carol",
        "exp": int(time.time()) - 60,
        "iat": int(time.time()) - 120,
    }
    expired = jwt.encode(expired_payload, secret, algorithm=JWT_ALGORITHM)
    assert decode_access_token(expired, secret) is None


def test_decode_malformed_token_returns_none():
    secret = generate_jwt_secret()
    assert decode_access_token("not.a.jwt", secret) is None
    assert decode_access_token("", secret) is None
