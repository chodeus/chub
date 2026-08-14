"""Regression tests for the 2026-07 adversarial review.

One focused test per confirmed backend bug class so these can't silently come
back. See CHUB_ADVERSARIAL_REVIEW.md for the full findings.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.util.config import ChubConfig, ConfigError, ConfigParseError
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
    imported = {"eventType": "Download", "movie": movie}

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
        auth=SimpleNamespace(username="u", password_hash="h", jwt_secret=secret)
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
        client.get(
            "/api/other", headers={"Authorization": f"Bearer {full}"}
        ).status_code
        == 200
    )


# 8. Renaming an instance must migrate rows even when the historical `source` is
#    title-cased (the doubled-instance bug).
def test_rename_instance_migrates_title_cased_source(db):
    db.media.upsert(
        dict(
            title="M",
            normalized_title=normalize_titles("M"),
            year=2020,
            alternate_titles=[],
            normalized_alternate_titles=[],
            tmdb_id=1,
        ),
        "movie",
        "radarr",
        "radarr",  # old instance_name
    )
    # Simulate a pre-normalization row whose source is title-cased.
    db.media.execute_query("UPDATE media_cache SET source='Radarr'")

    migrated = db.rename_instance("radarr", "Radarr", "radarr")
    assert migrated >= 1

    names = {
        r["instance_name"]
        for r in (
            db.media.execute_query(
                "SELECT DISTINCT instance_name FROM media_cache", fetch_all=True
            )
            or []
        )
    }
    assert names == {"Radarr"}  # no ghost "radarr" left behind


# 9. Worker startup reset must be scoped to this worker's job partition, so a
#    catch-all worker can't revert a webhook job the webhook worker just claimed.
def test_worker_startup_reset_scoped_to_partition(db):
    db.worker.enqueue_job("jobs", {}, job_type="webhook")
    db.worker.enqueue_job(
        "jobs", {}, job_type="module_run"
    )  # no module_name → no dedup
    db.worker.execute_query("UPDATE jobs SET status='running'")

    def status_by_type():
        rows = db.worker.execute_query("SELECT type, status FROM jobs", fetch_all=True)
        return {r["type"]: r["status"] for r in (rows or [])}

    # Catch-all (background) worker resets only non-webhook jobs.
    db.create_worker(worker_name="bg", job_type_filter=None)._reset_stuck_jobs("jobs")
    st = status_by_type()
    assert st["webhook"] == "running"  # sibling's in-flight job untouched
    assert st["module_run"] == "pending"

    # Webhook worker resets only webhook jobs.
    db.worker.execute_query("UPDATE jobs SET status='running'")
    db.create_worker(worker_name="wh", job_type_filter="webhook")._reset_stuck_jobs(
        "jobs"
    )
    st = status_by_type()
    assert st["webhook"] == "pending"
    assert st["module_run"] == "running"


# 10. Every SSRF-validated instance probe must disable redirects, else a 302 to a
#     metadata endpoint bypasses is_safe_url.
def test_instance_probes_disable_redirects():
    import inspect

    import backend.api.instances as inst

    src = inspect.getsource(inst)
    for bad in (
        "requests.get(test_url, headers=headers, timeout=2)",
        "requests.get(test_url, headers=headers, timeout=5)",
        "requests.get(url, headers=headers, timeout=5)",
    ):
        assert bad not in src, f"probe follows redirects: {bad}"
    # All external probes now opt out of redirects.
    assert src.count("allow_redirects=False") >= 4


# 11. A malformed schedule string must be rejected, not persisted (it would then
#     silently never fire).
def test_validate_schedule_rejects_malformed_accepts_valid():
    from backend.util.scheduler import validate_schedule

    for good in (
        "",
        "hourly(30)",
        "daily(07:00|19:00)",
        "weekly(mon@09:00|fri@18:30)",
        "monthly(1@09:00|15@21:00)",
        "cron(0 2 * * *)",
    ):
        validate_schedule(good)

    for bad in (
        "daily(2am)",
        "daily(25:00)",
        "hourly(99)",
        "weekly(someday@09:00)",
        "monthly(40@09:00)",
        "cron(not a valid cron)",
        "banana(1)",
        "daily(07:00",
    ):
        with pytest.raises(ValueError):
            validate_schedule(bad)


# --- Round 2: secrets-at-rest + authz/fail-open audit ---


# 12. AuthMiddleware must fail CLOSED (deny) when config can't load, not pass
#     the request through unauthenticated.
def test_auth_middleware_fails_closed_on_config_error(monkeypatch):
    import backend.api.main as apimain
    from backend.util.config import ConfigError

    def boom():
        raise ConfigError("corrupt config")

    monkeypatch.setattr(apimain, "load_config", boom)

    app = FastAPI()
    app.add_middleware(apimain.AuthMiddleware)

    @app.get("/api/media/1")
    def protected():
        return {"ok": True}

    @app.get("/api/health")
    def health():
        return {"ok": True}

    client = TestClient(app)
    # Protected route denied (503), NOT passed through unauthenticated.
    assert client.get("/api/media/1").status_code == 503
    # Exempt route (checked before load_config) still works.
    assert client.get("/api/health").status_code == 200


# 13. verify_webhook_secret must fail CLOSED on config error — the exempt webhook
#     endpoints rely solely on it; ConfigError propagates to the shared handler.
def test_verify_webhook_secret_fails_closed_on_config_error(monkeypatch):
    from backend.api.webhooks import verify_webhook_secret
    from backend.util.config import ConfigError

    def boom():
        raise ConfigError("corrupt config")

    monkeypatch.setattr("backend.api.webhooks.load_config", boom)

    class _Req:
        headers = {}
        query_params = {}

    with pytest.raises(ConfigError):
        verify_webhook_secret(_Req())


# 14. GET /api/modules/{name} must redact secrets in the returned config section.
def test_module_config_section_is_redacted():
    import inspect

    import backend.api.modules as mod
    from backend.util.config import REDACTED_PLACEHOLDER, redact_secrets

    src = inspect.getsource(mod)
    assert "redact_secrets(config_data.get(name" in src, "get_module must redact"
    # And redaction actually masks the sync_gdrive OAuth leaves.
    red = redact_secrets(
        {
            "client_secret": "GOCSPX-secretvalue",
            "token": {"refresh_token": "r" * 40, "access_token": "a" * 40},
        }
    )
    assert red["client_secret"] == REDACTED_PLACEHOLDER
    assert red["token"]["refresh_token"] == REDACTED_PLACEHOLDER
    assert red["token"]["access_token"] == REDACTED_PLACEHOLDER


# 15. The log formatter must redact secrets in the exc_info traceback, which the
#     record-level filter (msg/args only) never sees.
def test_formatter_redacts_secret_in_traceback():
    import logging
    import sys

    from backend.util.logger import SafeFormatter

    fmt = SafeFormatter("%(message)s")
    try:
        raise ValueError("http://plex:32400/library?X-Plex-Token=SECRETTOKEN1234567890")
    except ValueError:
        rec = logging.LogRecord(
            "m", logging.ERROR, __file__, 1, "upload failed", None, sys.exc_info()
        )
    out = fmt.format(rec)
    assert "SECRETTOKEN1234567890" not in out
    assert "X-Plex-Token=SECR…" in out  # key stays visible, value masked


# 16. The redaction filter must mask a Notifiarr passthrough API key (URL path,
#     not a query param).
def test_redact_notifiarr_passthrough_key():
    from backend.util.log_redaction import redact

    s = (
        "ConnectionError: HTTPSConnectionPool ... url: "
        "https://notifiarr.com/api/v1/notification/passthrough/abcd1234efgh5678ijkl"
    )
    out = redact(s)
    assert "abcd1234efgh5678ijkl" not in out
    assert "passthrough/[redacted]" in out


# 17. OAuth tokens in yaml/unquoted key:value form must redact too — a dumped
#     gdrive config leaked access_token / refresh_token to sync_gdrive.log.
def test_redact_oauth_tokens_in_yaml_form():
    from backend.util.log_redaction import redact

    s = (
        "token:\n"
        "  access_token: ya29.a0AfB_verylongsecretvalue1234567890\n"
        "  refresh_token: 1//0gLongRefreshTokenValue1234567890abcd\n"
    )
    out = redact(s)
    assert "ya29.a0AfB_verylongsecretvalue1234567890" not in out
    assert "1//0gLongRefreshTokenValue1234567890abcd" not in out
    assert "access_token: ya29…" in out
    assert "refresh_token: 1//0…" in out


# --- Round 3: backend correctness + perf audit ---


class _StubLog:
    """Swallows every log call; get_adapter returns itself."""

    def __getattr__(self, _):
        """Any log method is a no-op."""
        return lambda *a, **k: None

    def get_adapter(self, *_a, **_kw):
        """Adapters are the same sink."""
        return self


def _app(router, db=None):
    """Mount `router` on a bare app carrying main.py's real ConfigError handler."""
    import backend.api.main as apimain

    app = FastAPI()
    app.state.logger = _StubLog()
    app.state.db = db
    app.add_exception_handler(ConfigError, apimain.handle_config_error)
    app.include_router(router)
    # raise_server_exceptions=False so the handler answers instead of re-raising.
    return TestClient(app, raise_server_exceptions=False)


# 18. /api/posters/list must resolve through STATIC_DIR, not a hardcoded
#     templates/ path that doesn't exist in the Docker image (empty list).
def test_poster_list_uses_static_dir(monkeypatch, tmp_path):
    """The list endpoint reads STATIC_DIR/posters, not templates/posters."""
    import backend.api.posters as posters

    posters_dir = tmp_path / "posters"
    posters_dir.mkdir()
    (posters_dir / "default-movie.jpg").write_bytes(b"x")
    (posters_dir / "notes.txt").write_text("ignored")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))

    resp = _app(posters.router).get("/api/posters/list")
    assert resp.status_code == 200
    assert resp.json()["data"]["files"] == ["default-movie.jpg"]


# 19a. has_rows_under_prefix must escape LIKE metacharacters, or a sibling
#      folder makes the skip-on-zero-change guard wrongly believe rows exist.
def test_has_rows_under_prefix_escapes_like_wildcards(db):
    """`_` in a folder name must not wildcard-match a sibling folder."""
    db.poster.upsert(_poster("/data/MyXMovies/p.jpg", "/data/MyXMovies"))

    assert db.poster.has_rows_under_prefix("/data/MyXMovies") is True
    assert db.poster.has_rows_under_prefix("/data/My_Movies") is False


# 19b. poster_cache.search must escape too — the raw `title LIKE` branch keeps
#      the metacharacters that normalize_titles strips.
def test_poster_search_escapes_like_wildcards(db):
    """The raw `title LIKE` branch keeps metacharacters — escape them too."""
    for title, tmdb_id in (("My_Movies", 1), ("MyXMovies", 2)):
        item = _poster(f"/data/{title}/p.jpg", f"/data/{title}")
        item.update(
            title=title, normalized_title=normalize_titles(title), tmdb_id=tmdb_id
        )
        db.poster.upsert(item)

    titles = {row["title"] for row in db.poster.search("My_Movies")["items"]}
    assert titles == {"My_Movies"}


# 19c. The tag→collection query must escape as well, or one tag silently
#      sweeps in every similarly-named tag's media.
def test_collection_from_tag_escapes_like_wildcards(db):
    """One tag must not sweep in every similarly-named tag's media."""
    import backend.api.media_api as media_api

    for title, tag in (("Dune", "4K_UHD"), ("Sicario", "4KxUHD")):
        db.media.upsert(
            {
                "title": title,
                "normalized_title": normalize_titles(title),
                "year": 2021,
                "tags": [tag],
            },
            "movie",
            "radarr",
            "radarr",
        )

    resp = _app(media_api.router, db).post(
        "/api/media/collections/from-tag", json={"tag": "4K_UHD"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["matched_media"] == 1


# 20. The duplicate-exclusion filter must fail CLOSED: a config it can't read
#     has to deny, since a bulk-delete button sits next to these results.
def test_duplicates_denies_when_config_unreadable(db, monkeypatch):
    """An unreadable config yields CONFIG_INVALID, never unfiltered duplicates."""
    import backend.api.media_api as media_api

    client = _app(media_api.router, db)

    cfg = ChubConfig()
    cfg.general.duplicate_exclude_groups = [["radarr", "radarr4k"]]
    monkeypatch.setattr(media_api, "load_config", lambda: cfg)
    assert client.get("/api/media/duplicates").status_code == 200

    def boom():
        """Stand-in load_config that fails."""
        raise ConfigParseError("corrupt config")

    monkeypatch.setattr(media_api, "load_config", boom)
    body = client.get("/api/media/duplicates")
    assert body.status_code == 500
    assert body.json()["error_code"] == "CONFIG_INVALID"


# 20b. duplicate_exclude_groups is List[Any] — a non-string member must skip
#      that group, not blow up set() and surface as DUPLICATES_ERROR.
def test_duplicates_skips_malformed_exclude_group_members(db, monkeypatch):
    """A group holding an unhashable member is skipped, not a 500."""
    import backend.api.media_api as media_api

    cfg = ChubConfig()
    cfg.general.duplicate_exclude_groups = [
        [{"instances": "nope"}, "radarr4k"],
        ["radarr", "radarr4k"],
    ]
    monkeypatch.setattr(media_api, "load_config", lambda: cfg)

    resp = _app(media_api.router, db).get("/api/media/duplicates")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# 21. preview_poster_file must authorize the RESOLVED path — a symlink inside an
#     allowed root must not serve whatever it points at outside the roots.
def test_poster_preview_denies_a_symlink_escaping_the_roots(tmp_path, monkeypatch):
    """A link inside an allowed root must not serve its target outside them."""
    from backend.api.posters import files as posters_files

    root = tmp_path / "posters"
    root.mkdir()
    secret = tmp_path / "outside" / "secret.jpg"
    secret.parent.mkdir()
    secret.write_bytes(b"top-secret-bytes")
    link = root / "innocent.jpg"
    link.symlink_to(secret)

    monkeypatch.setattr("backend.util.config.load_config", lambda *a, **k: object())
    monkeypatch.setattr(
        "backend.util.path_safety.is_path_allowed",
        lambda p, cfg: str(p).startswith(str(root)),
    )

    import asyncio

    class _Log:
        """Quiet logger stub."""

        def __getattr__(self, _n):
            """Return a no-op for any log method."""
            return lambda *a, **k: None

    resp = asyncio.run(
        posters_files.preview_poster_file(
            location=str(root), path=str(link), logger=_Log()
        )
    )
    assert getattr(resp, "status_code", 200) == 403, "symlink escape was served"
