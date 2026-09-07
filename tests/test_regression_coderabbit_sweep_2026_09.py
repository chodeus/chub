"""Regression tests for the 2026-09 review sweep — one per confirmed bug."""

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


def _request_with_secret(secret: str):
    """Secret via ?secret= — HTTP headers are latin-1, so unicode needs the query."""
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
    """A unicode ?secret= must 401, not 500 — the ingest route is unauthenticated."""
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
    verdict = webhooks.verify_webhook_secret(_request_with_secret("ünïcode"))
    assert verdict is None


def test_full_session_token_in_query_string_is_rejected(monkeypatch):
    """A full session token in a URL must be refused — URLs leak via referers."""
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

    # Bound first: -O strips asserts, taking the request with them.
    full_in_url = client.get(f"/api/media/1/poster?token={full}")
    stream_in_url = client.get(f"/api/media/1/poster?token={stream}")
    full_in_header = client.get(
        "/api/media/1/poster", headers={"Authorization": f"Bearer {full}"}
    )
    # A header does not excuse a session token sitting in the URL beside it.
    both = client.get(
        f"/api/media/1/poster?token={full}",
        headers={"Authorization": f"Bearer {full}"},
    )
    stream_url_plus_header = client.get(
        f"/api/media/1/poster?token={stream}",
        headers={"Authorization": f"Bearer {full}"},
    )
    assert full_in_url.status_code == 403
    assert stream_in_url.status_code == 200
    assert full_in_header.status_code == 200
    # Repeated parameters: .get() reads the last, hiding every earlier token.
    repeated = client.get(f"/api/media/1/poster?token={full}&token={stream}")
    assert both.status_code == 403
    assert stream_url_plus_header.status_code == 200
    assert repeated.status_code == 403


def test_resolve_duplicates_never_removes_the_kept_id(monkeypatch):
    """The kept item must survive even when named in remove_ids."""
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
    """A raw JSON body value is not coerced, so "false" and "0" were truthy."""
    from backend.api.utils import body_flag

    assert body_flag({"deleteFiles": raw}, "deleteFiles") is expected


def test_body_flag_absent_key_uses_default():
    from backend.api.utils import body_flag

    assert body_flag({}, "deleteFiles") is False
    assert body_flag({}, "deleteFile", True) is True
    assert body_flag("not a dict", "deleteFile") is False  # type: ignore[arg-type]
