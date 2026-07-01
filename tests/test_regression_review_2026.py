"""Regression tests for the 2026-07 adversarial review.

One focused test per confirmed backend bug class so these can't silently come
back. See CHUB_ADVERSARIAL_REVIEW.md for the full findings.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.util.database import ChubDB
from backend.util.normalization import normalize_titles


def _logger():
    from backend.util.logger import Logger

    return Logger("ERROR", "test")


@pytest.fixture
def db(tmp_path):
    with ChubDB(_logger(), db_path=str(tmp_path / "chub.db")) as database:
        yield database


def _poster(file_path, folder):
    return {
        "asset_type": "movie",
        "title": "Inception",
        "normalized_title": "inception",
        "year": 2010,
        "tmdb_id": 27205,
        "tvdb_id": None,
        "imdb_id": "tt1375666",
        "season_number": None,
        "folder": folder,
        "file": file_path,
        "style": None,
        "priority": 0,
    }


# 1. poster_cache delete-by-prefix must escape LIKE metacharacters (_ / %).
def test_delete_by_path_prefix_escapes_like_wildcards(db):
    db.poster.upsert(_poster("/data/My_Movies/p.jpg", "/data/My_Movies"))
    db.poster.upsert(_poster("/data/MyXMovies/p.jpg", "/data/MyXMovies"))

    db.poster.delete_by_path_prefix("/data/My_Movies")

    files = {r["file"] for r in db.poster.get_all()}
    # The '_' must be literal — the sibling folder must survive.
    assert "/data/MyXMovies/p.jpg" in files
    assert "/data/My_Movies/p.jpg" not in files


# 2. media search: a numeric rating filter must not drop certification rows.
def test_numeric_rating_filter_does_not_drop_certified_rows(db):
    item = dict(
        title="Dune",
        normalized_title=normalize_titles("Dune"),
        year=2021,
        alternate_titles=[],
        normalized_alternate_titles=[],
        monitored=True,
        has_content=True,
        tmdb_id=438631,
        rating="PG-13",  # a TEXT certification, not a numeric score
    )
    db.media.upsert(item, "movie", "radarr", "main")

    res = db.media.search(rating_min=5.0)
    titles = {row.get("title") for row in res.get("items", res.get("results", []))}
    assert "Dune" in titles


# 3. A malformed (non-hex) Discord colour must not drop the notification.
def test_non_hex_notification_color_does_not_raise():
    from backend.util.notification import NotificationManager

    out = NotificationManager.build_discord_payload(
        "Title", [], "2026-01-01 00:00:00", color="not-a-colour"
    )
    assert isinstance(out, list)


# 4. Webhook dedup: the pre-download (added) and import phases for the same media
#    must NOT collapse into one fingerprint.
def test_webhook_dedup_separates_added_and_import_phase():
    from backend.api.webhooks import _is_duplicate_webhook

    seen = set()
    captured = []

    class _Cache:
        def is_duplicate(self, item_type, item_name, ttl_seconds=0):
            captured.append(item_name)
            key = (item_type, item_name)
            if key in seen:
                return True
            seen.add(key)
            return False

    stub_db = SimpleNamespace(webhook_cache=_Cache())
    movie = {"title": "M", "year": 2020, "tmdbId": 1}

    added = {"eventType": "MovieAdded", "movie": movie}
    imported = {"eventType": "MovieFileImported", "movie": movie}

    assert _is_duplicate_webhook(added, stub_db) is False
    # Same media, different phase → a fresh fingerprint, not a debounced dup.
    assert _is_duplicate_webhook(imported, stub_db) is False
    assert captured[0] != captured[1]


# 5. Holiday migration must emit a valid schedule (str), never None.
def test_holiday_migration_emits_empty_schedule_not_none():
    from backend.util.config_migrator import _rule_border_holidays_dict_to_list

    raw = {"border_replacerr": {"holidays": {"Xmas": {"color": "#ffffff"}}}}
    _rule_border_holidays_dict_to_list(raw, [])

    holidays = raw["border_replacerr"]["holidays"]
    assert isinstance(holidays, list) and holidays
    assert holidays[0]["schedule"] == ""  # not None (which fails validation)


# 6. instance test must not resolve/send a stored key to a mismatched URL.
def test_instance_test_does_not_leak_key_to_mismatched_url(monkeypatch):
    import backend.api.instances as inst
    from backend.util.config import (
        REDACTED_PLACEHOLDER,
        ChubConfig,
        InstanceDetail,
    )

    cfg = ChubConfig()
    cfg.instances.sonarr["main"] = InstanceDetail(url="http://s:8989", api="REALKEY")
    monkeypatch.setattr(inst, "load_config", lambda: cfg)
    monkeypatch.setattr("backend.util.ssrf_guard.is_safe_url", lambda u: (True, ""))

    captured = {}

    class _Resp:
        ok = True
        status_code = 200

    def fake_get(url, headers=None, timeout=None, **kwargs):
        captured["headers"] = headers or {}
        return _Resp()

    monkeypatch.setattr(inst.requests, "get", fake_get)

    app = FastAPI()

    class _Log:
        def __getattr__(self, _):
            return lambda *a, **k: None

        def get_adapter(self, *_):
            return self

    app.state.logger = _Log()
    app.state.db = None
    app.include_router(inst.router)

    resp = TestClient(app).post(
        "/api/instances/test",
        json={
            "service": "sonarr",
            "name": "main",  # a real stored name…
            "url": "http://attacker:9999",  # …but a URL that isn't the stored one
            "api": REDACTED_PLACEHOLDER,
        },
    )
    assert resp.status_code in (200, 400, 502)
    # The real key must never be sent to the attacker URL.
    assert captured.get("headers", {}).get("X-Api-Key") != "REALKEY"


# 7. AuthMiddleware: a scope=stream token is GET-only and allowlist-restricted.
def test_stream_token_rejected_off_allowlist(monkeypatch):
    import backend.api.main as apimain
    from backend.util.auth import (
        create_access_token,
        create_stream_token,
        generate_jwt_secret,
    )

    secret = generate_jwt_secret()
    cfg = SimpleNamespace(
        auth=SimpleNamespace(
            username="u", password_hash="h", jwt_secret=secret
        )
    )
    monkeypatch.setattr(apimain, "load_config", lambda: cfg)

    app = FastAPI()
    app.add_middleware(apimain.AuthMiddleware)

    @app.get("/api/other")
    def other():
        return {"ok": True}

    @app.get("/api/media/{mid}/poster")
    def poster(mid: str):
        return {"ok": True}

    client = TestClient(app)
    stream = create_stream_token("u", secret)
    full = create_access_token("u", secret)

    # Stream token on a non-stream route → rejected.
    assert client.get(f"/api/other?token={stream}").status_code == 403
    # Stream token on an allowlisted image route → allowed.
    assert client.get(f"/api/media/1/poster?token={stream}").status_code == 200
    # Full session token works everywhere.
    assert (
        client.get("/api/other", headers={"Authorization": f"Bearer {full}"}).status_code
        == 200
    )
