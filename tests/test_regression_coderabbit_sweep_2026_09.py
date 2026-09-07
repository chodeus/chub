"""Regression tests for the 2026-09 CodeRabbit full-codebase sweep.

One focused test per confirmed backend bug so these can't silently come back.
Findings that were refuted on inspection are deliberately not represented here.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _logger():
    return SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        get_adapter=lambda *a, **k: _logger(),
    )


# --- webhook secret comparison ---


def _request_with_secret(secret: str):
    """Secret via ?secret= — HTTP headers are latin-1, so a unicode secret can
    only realistically arrive percent-encoded in the query string."""
    from urllib.parse import urlencode

    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/webhooks/sonarr",
            "headers": [],
            "query_string": urlencode({"secret": secret}).encode("ascii"),
        }
    )


@pytest.mark.parametrize("supplied", ["ünïcode", "naïve", "日本語"])
def test_non_ascii_supplied_secret_is_rejected_not_a_crash(monkeypatch, supplied):
    """hmac.compare_digest raises TypeError on non-ASCII str. The ingest route
    is unauthenticated, so that turned any unicode ?secret= into a 500."""
    import backend.api.webhooks as webhooks

    monkeypatch.setattr(
        webhooks,
        "load_config",
        lambda: SimpleNamespace(general=SimpleNamespace(webhook_secret="correct")),
    )
    with pytest.raises(HTTPException) as exc:
        webhooks.verify_webhook_secret(_request_with_secret(supplied))
    assert exc.value.status_code == 401


def test_non_ascii_configured_secret_still_authenticates(monkeypatch):
    """A unicode secret in config must keep working, not 500 every webhook."""
    import backend.api.webhooks as webhooks

    monkeypatch.setattr(
        webhooks,
        "load_config",
        lambda: SimpleNamespace(general=SimpleNamespace(webhook_secret="ünïcode")),
    )
    assert webhooks.verify_webhook_secret(_request_with_secret("ünïcode")) is None


# --- URL-embedded tokens must be stream-scoped ---


def test_full_session_token_in_query_string_is_rejected(monkeypatch):
    """Query-param auth exists only for EventSource and <img>. A full session
    token in a URL is logged, cached and sent as a referer."""
    import backend.api.main as apimain
    from backend.util.auth import (
        create_access_token,
        create_stream_token,
        generate_jwt_secret,
    )

    secret = generate_jwt_secret()
    monkeypatch.setattr(
        apimain,
        "load_config",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(username="u", password_hash="h", jwt_secret=secret)
        ),
    )

    app = FastAPI()
    app.add_middleware(apimain.AuthMiddleware)

    @app.get("/api/media/{mid}/poster")
    def poster(mid: str):
        return {"ok": True}

    client = TestClient(app)
    full = create_access_token("u", secret)
    stream = create_stream_token("u", secret)

    # A full session token in the query string is refused even on a stream route.
    assert client.get(f"/api/media/1/poster?token={full}").status_code == 403
    # The stream token it exists for still works.
    assert client.get(f"/api/media/1/poster?token={stream}").status_code == 200
    # And the header path is untouched.
    assert (
        client.get(
            "/api/media/1/poster", headers={"Authorization": f"Bearer {full}"}
        ).status_code
        == 200
    )


# --- duplicate resolution must never remove the kept item ---


def test_resolve_duplicates_never_removes_the_kept_id(monkeypatch):
    """With deleteFiles the kept item would be taken off disk while the
    response still reported it as kept."""
    import backend.api.media_api as media_api

    removed_ids = []

    def _fake_remove(db, logger, rid, delete_files, add_exclusion):
        removed_ids.append(rid)
        return True, ""

    monkeypatch.setattr(media_api, "_remove_media_item", _fake_remove)

    media_api._resolve_duplicates_sync(
        db=SimpleNamespace(),
        logger=_logger(),
        keep_id=7,
        kept_item={"id": 7, "title": "Keeper"},
        remove_ids=[7, 8, 9],
        delete_files=True,
        add_exclusion=False,
    )
    assert 7 not in removed_ids
    assert removed_ids == [8, 9]


# --- destructive body flags must be coerced ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("false", False),
        ("0", False),
        ("False", False),
        ("no", False),
        (False, False),
        (0, False),
        ("true", True),
        ("1", True),
        (True, True),
    ],
)
def test_body_flag_coerces_string_booleans(raw, expected):
    """FastAPI coerces declared params; a raw JSON body value does not, so
    "false" and "0" were truthy and deleted files they were told to keep."""
    from backend.api.utils import body_flag

    assert body_flag({"deleteFiles": raw}, "deleteFiles") is expected


def test_body_flag_absent_key_uses_default():
    from backend.api.utils import body_flag

    assert body_flag({}, "deleteFiles") is False
    assert body_flag({}, "deleteFile", True) is True
    assert body_flag("not a dict", "deleteFile") is False  # type: ignore[arg-type]
