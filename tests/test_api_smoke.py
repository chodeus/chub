"""Smoke tests for FastAPI API endpoints using TestClient.

Each test mounts an individual router on a fresh app to avoid the heavy
lifespan startup (database, workers) of the production app.
"""

import contextlib
import os
import sys

import pytest

# Starlette's TestClient requires httpx; skip the whole module cleanly
# when it's not installed (e.g. minimal local environments).
pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.api import auth as auth_router  # noqa: E402
from backend.api import border_replacerr as border_router  # noqa: E402
from backend.api import posters as posters_router  # noqa: E402
from backend.api import system as system_router  # noqa: E402
from backend.util.config import ChubConfig  # noqa: E402


class StubLogger:
    def debug(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def get_adapter(self, *_a, **_kw):
        return self


@pytest.fixture
def app_with_router():
    """Helper to build a fresh FastAPI app and attach state needed by handlers."""

    def _build(router):
        app = FastAPI()
        app.state.logger = StubLogger()
        app.state.db = None
        app.include_router(router)
        return app

    return _build


# --- Auth status endpoint (no auth required) ---


def test_auth_status_returns_unconfigured(monkeypatch, app_with_router, tmp_path):
    """A fresh install has no auth configured."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    # Override load_config in auth module so it picks up tmp env.
    # ChubConfig() builds a fresh default each time it's called, so the
    # class itself works as the patched factory.
    monkeypatch.setattr("backend.api.auth.load_config", ChubConfig)
    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["configured"] is False
    assert body["data"]["required"] is True


def test_auth_status_returns_configured(monkeypatch, app_with_router):
    config = ChubConfig()
    config.auth.username = "admin"
    config.auth.password_hash = "$2b$x"
    monkeypatch.setattr("backend.api.auth.load_config", lambda: config)
    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.get("/api/auth/status")
    assert resp.json()["data"]["configured"] is True


# --- Logout (stateless) ---


def test_logout_endpoint(app_with_router):
    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# --- Setup (first-run) ---


def test_setup_creates_credentials(monkeypatch, app_with_router):
    config = ChubConfig()
    saved = []
    monkeypatch.setattr("backend.api.auth.load_config", lambda: config)
    monkeypatch.setattr("backend.api.auth.save_config", lambda c: saved.append(c))

    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/setup", json={"username": "admin", "password": "hunter2hunter"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    # save_config was invoked
    assert len(saved) == 1
    assert saved[0].auth.username == "admin"
    assert saved[0].auth.password_hash  # hashed, not empty
    assert saved[0].auth.password_hash != "hunter2hunter"
    assert saved[0].auth.jwt_secret  # generated


def test_setup_rejects_when_already_configured(monkeypatch, app_with_router):
    config = ChubConfig()
    config.auth.username = "admin"
    config.auth.password_hash = "$2b$x"
    monkeypatch.setattr("backend.api.auth.load_config", lambda: config)

    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/setup", json={"username": "another", "password": "anotherpass"}
    )
    # Either 400 (bad request) or 403 (forbidden) — both mean "rejected"
    assert resp.status_code in (400, 403)
    assert resp.json()["success"] is False


# --- Login ---


def test_login_succeeds_with_correct_password(monkeypatch, app_with_router):
    from backend.util.auth import hash_password

    config = ChubConfig()
    config.auth.username = "admin"
    config.auth.password_hash = hash_password("secret123")
    config.auth.jwt_secret = "test-secret-very-long-test-secret-very-long"

    monkeypatch.setattr("backend.api.auth.load_config", lambda: config)

    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "secret123"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["token"]


def test_login_fails_with_wrong_password(monkeypatch, app_with_router):
    from backend.util.auth import hash_password

    config = ChubConfig()
    config.auth.username = "admin"
    config.auth.password_hash = hash_password("secret123")
    config.auth.jwt_secret = "test-secret-very-long-test-secret-very-long"

    monkeypatch.setattr("backend.api.auth.load_config", lambda: config)

    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "wrong"}
    )
    assert resp.status_code in (400, 401)
    assert resp.json()["success"] is False


def test_login_fails_with_unknown_user(monkeypatch, app_with_router):
    from backend.util.auth import hash_password

    config = ChubConfig()
    config.auth.username = "admin"
    config.auth.password_hash = hash_password("secret123")
    config.auth.jwt_secret = "test-secret-very-long-test-secret-very-long"

    monkeypatch.setattr("backend.api.auth.load_config", lambda: config)

    app = app_with_router(auth_router.router)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/login", json={"username": "unknown", "password": "secret123"}
    )
    assert resp.status_code in (400, 401)


# --- Border Replacerr: presets + borders catalogue ---


def test_border_presets_returns_catalogue(app_with_router):
    """The /presets endpoint surfaces the canonical holiday catalogue."""
    app = app_with_router(border_router.router)
    client = TestClient(app)
    resp = client.get("/api/border-replacerr/presets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    presets = body["data"]["presets"]
    # Every preset has name + schedule + colors, and the known holidays are
    # all represented so the frontend dropdown can render without a fallback.
    names = {p["name"] for p in presets}
    assert "🎄 Christmas" in names
    assert "🎃 Halloween" in names
    assert "🏳️‍🌈 Pride" in names
    for preset in presets:
        assert preset["name"]
        assert preset["schedule"].startswith("range(")
        assert isinstance(preset["colors"], list) and preset["colors"]


def test_border_list_returns_bundled_variants(tmp_path, monkeypatch, app_with_router):
    """A known holiday name returns its bundled PNGs and an empty user list."""
    # Fresh tmp config dir so no user-side variants exist.
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("DOCKER_ENV", "true")

    # Bundled PNGs are gitignored locally — drop a couple of stubs into
    # the bundled dir so the test can assert against a known set, then
    # clean them up regardless of result.
    bundled_dir = border_router._BUNDLED_BORDERS_DIR / "christmas"
    created = []
    from PIL import Image as _Image

    for stem in ("v1", "v2"):
        path = bundled_dir / f"{stem}.png"
        if not path.exists():
            bundled_dir.mkdir(parents=True, exist_ok=True)
            _Image.new("RGBA", (10, 15), (0, 0, 0, 0)).save(path)
            created.append(path)
    try:
        app = app_with_router(border_router.router)
        client = TestClient(app)
        resp = client.get("/api/border-replacerr/borders/%F0%9F%8E%84%20Christmas")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["folder"] == "christmas"
        assert {"v1", "v2"}.issubset(set(body["data"]["bundled"]))
        assert body["data"]["user"] == []
    finally:
        for path in created:
            # Teardown is best-effort: the file may already be gone if the
            # test cleaned it up, or the dir may be readonly in some CI envs.
            with contextlib.suppress(OSError):
                path.unlink()


def test_border_list_unknown_holiday_returns_empty(app_with_router):
    """Holiday names that don't map to a folder return null folder + empty lists."""
    app = app_with_router(border_router.router)
    client = TestClient(app)
    # "!!!" strips to nothing → _holiday_folder returns None.
    resp = client.get("/api/border-replacerr/borders/!!!")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["folder"] is None
    assert data["bundled"] == []
    assert data["user"] == []


def test_border_thumbnail_rejects_traversal(app_with_router):
    """The thumbnail endpoint must not serve files outside its source dirs."""
    app = app_with_router(border_router.router)
    client = TestClient(app)
    # Dots and slashes are stripped by Path(...).stem + the charset check,
    # but exercise the explicit guard anyway.
    resp = client.get(
        "/api/border-replacerr/borders/%F0%9F%8E%84%20Christmas/bundled/..%2Fetc%2Fpasswd.png"
    )
    assert resp.status_code == 404


# --- System: gdrive presets bundle ---


def test_gdrive_presets_returns_bundled_catalogue(app_with_router):
    """The /gdrive-presets endpoint serves the bundled CL2K/MM2K/Artwork JSON."""
    app = app_with_router(system_router.router)
    client = TestClient(app)
    resp = client.get("/api/gdrive-presets")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    presets = body["data"]
    assert isinstance(presets, list) and len(presets) > 0
    # Every preset must carry the three fields the frontend uses.
    for entry in presets:
        assert {"name", "id", "style"}.issubset(entry.keys())
        assert entry["style"] in ("CL2K", "MM2K", "Artwork")
    # Spot-check a couple of canonical entries so we'd notice if the
    # bundled JSON gets mangled in a future commit.
    by_id = {e["id"]: e for e in presets}
    assert "1MiNjT3t_eIdaMTiQ4E89IMNXasco7r6q" in by_id  # CL2K Mario
    assert by_id["1MiNjT3t_eIdaMTiQ4E89IMNXasco7r6q"]["style"] == "CL2K"
    # Artwork drives carry logos/backgrounds/squareart, not posters.
    assert by_id["1zUE6LDrrxPo66ch8voZlgVyG_wi-4V7s"]["style"] == "Artwork"


def test_gdrive_presets_missing_file_returns_500(monkeypatch, app_with_router):
    """If the bundled JSON is missing, surface a 500 (not a silent empty list)."""
    monkeypatch.setattr(
        system_router, "_GDRIVE_PRESETS_PATH", system_router.Path("/nonexistent.json")
    )
    monkeypatch.setattr(system_router, "_gdrive_presets_cache", None)
    app = app_with_router(system_router.router)
    client = TestClient(app)
    resp = client.get("/api/gdrive-presets")
    assert resp.status_code == 500
    assert resp.json()["success"] is False


# --- System: allowed roots ---


def test_allowed_roots_returns_configured_paths(monkeypatch, app_with_router, tmp_path):
    """The picker discovery endpoint surfaces config-derived roots."""
    posters = tmp_path / "posters"
    posters.mkdir()
    config = ChubConfig()
    config.poster_renamerr.source_dirs = [str(posters)]
    monkeypatch.setattr(system_router, "load_config", lambda: config)
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    (tmp_path / "config").mkdir()

    app = app_with_router(system_router.router)
    client = TestClient(app)
    resp = client.get("/api/allowed-roots")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    roots = body["data"]["roots"]
    assert isinstance(roots, list)
    # Configured poster source dir must be present.
    assert str(posters.resolve()) in roots


def test_allowed_roots_ok_when_config_file_absent(monkeypatch, app_with_router, tmp_path):
    """Real pre-onboarding: a missing file loads defaults, so the picker still answers."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    app = app_with_router(system_router.router)
    client = TestClient(app)
    resp = client.get("/api/allowed-roots")
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"]["roots"], list)


def test_allowed_roots_propagates_config_error(monkeypatch, app_with_router):
    """A malformed config must not masquerade as an empty allow-list."""
    from backend.util.config import ConfigError

    def _raise(*_a, **_kw):
        """Stand in for load_config on a malformed config file."""
        raise ConfigError("corrupt config")

    from backend.api.main import handle_config_error

    monkeypatch.setattr(system_router, "load_config", _raise)
    app = app_with_router(system_router.router)
    app.add_exception_handler(ConfigError, handle_config_error)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/allowed-roots")
    assert resp.status_code == 500
    assert resp.json()["error_code"] == "CONFIG_INVALID"


def test_delete_poster_aborts_before_row_delete_on_bad_config(
    monkeypatch, app_with_router, tmp_path
):
    """deleteFile + malformed config must abort BEFORE the irreversible row delete."""
    from backend.api.main import handle_config_error
    from backend.util.config import ConfigError, clear_config_cache

    (tmp_path / "config.yml").mkdir()  # OSError on open -> ConfigParseError
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    clear_config_cache()

    deleted = []

    class _Poster:
        """Tripwire recording any row deletion the handler attempts."""

        def delete_by_integer_id(self, poster_id):
            """Record the destructive call so the test can assert it never ran."""
            deleted.append(poster_id)
            return {"file": "x.jpg", "folder": "/tmp", "normalized_title": None}

    class _DB:
        """Minimal db stub exposing only the poster repository."""

        poster = _Poster()

    app = app_with_router(posters_router.router)
    app.state.db = _DB()
    app.add_exception_handler(ConfigError, handle_config_error)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.request("DELETE", "/api/posters/1", json={"deleteFile": True})

    assert resp.status_code == 500
    assert resp.json()["error_code"] == "CONFIG_INVALID"
    assert deleted == []  # the row survives a broken config
    clear_config_cache()


def test_delete_poster_refuses_file_outside_allowed_roots(
    monkeypatch, app_with_router, tmp_path
):
    """A poisoned folder/file row must not delete outside the configured roots."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "cfg"))
    victim_dir = tmp_path / "elsewhere"
    victim_dir.mkdir()
    victim = victim_dir / "victim.txt"
    victim.write_text("do not delete")

    class _Poster:
        """Stub returning a row that points outside every configured root."""

        def delete_by_integer_id(self, _pid):
            """Return the poisoned row and report it as deleted."""
            return {
                "file": victim.name,
                "folder": str(victim_dir),
                "normalized_title": None,
            }

    class _DB:
        """Minimal db stub exposing only the poster repository."""

        poster = _Poster()

    app = app_with_router(posters_router.router)
    app.state.db = _DB()
    client = TestClient(app)
    resp = client.request("DELETE", "/api/posters/1", json={"deleteFile": True})

    assert resp.status_code == 200
    # The row is still cleaned up, but the out-of-root file survives.
    assert resp.json()["data"]["file_deleted"] is False
    assert victim.exists()


# --- Poster file serving is confined to the configured roots ---


def _db_with_poster_row(row):
    """A db stub whose poster repo returns one fixed cache row."""

    class _Poster:
        """Stub poster repository."""

        def get_by_integer_id(self, _pid):
            """Return the seeded row for any id."""
            return row

    class _DB:
        """Minimal db stub exposing only the poster repository."""

        poster = _Poster()

    return _DB()


def _seed_poster_file(directory, name="Movie (2021).jpg"):
    """Write a real JPEG into *directory* and return its path."""
    from PIL import Image as _Image

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    _Image.new("RGB", (10, 15), (255, 0, 0)).save(path, "JPEG")
    return path


def _serving_app(app_with_router, monkeypatch, config, row):
    """Mount the posters router with a fixed config and one poster row."""
    monkeypatch.setattr("backend.util.config.load_config", lambda *a, **kw: config)
    app = app_with_router(posters_router.router)
    app.state.db = _db_with_poster_row(row)
    return TestClient(app, raise_server_exceptions=False)


def test_download_poster_serves_a_file_under_asset_renamerr_source_dir(
    monkeypatch, app_with_router, tmp_path
):
    """The gap-fill root: asset_renamerr rows must still download after confining."""
    src = tmp_path / "assets_src"
    poster = _seed_poster_file(src)
    config = ChubConfig()
    config.asset_renamerr.source_dirs = [str(src)]

    client = _serving_app(
        app_with_router,
        monkeypatch,
        config,
        # Production row shape: `folder` is a label, `file` the absolute path.
        {"file": str(poster), "folder": src.name},
    )
    resp = client.post("/api/posters/1/download")

    assert resp.status_code == 200, resp.text
    assert resp.content


def test_download_poster_refuses_a_file_outside_the_allowed_roots(
    monkeypatch, app_with_router, tmp_path
):
    """A poisoned row pointing outside every root is denied, not served."""
    src = tmp_path / "assets_src"
    src.mkdir()
    victim = _seed_poster_file(tmp_path / "elsewhere", "secret.jpg")
    config = ChubConfig()
    config.asset_renamerr.source_dirs = [str(src)]

    client = _serving_app(
        app_with_router,
        monkeypatch,
        config,
        {"file": str(victim), "folder": victim.parent.name},
    )
    resp = client.post("/api/posters/1/download")

    assert resp.status_code == 403, resp.text
    assert resp.json()["error_code"] == "PATH_TRAVERSAL_DENIED"


def test_poster_thumbnail_serves_a_file_under_music_source_dir(
    monkeypatch, app_with_router, tmp_path
):
    """The gap-fill root: music art rows must still thumbnail after confining."""
    music = tmp_path / "music_src"
    poster = _seed_poster_file(music, "Artist.jpg")
    config = ChubConfig()
    config.poster_renamerr.music_source_dirs = [str(music)]

    client = _serving_app(
        app_with_router,
        monkeypatch,
        config,
        {"file": str(poster), "folder": music.name},
    )
    resp = client.get("/api/posters/1/thumbnail")

    assert resp.status_code == 200, resp.text
    assert (music / ".thumbnails").is_dir()


def test_poster_thumbnail_refuses_a_file_outside_the_allowed_roots(
    monkeypatch, app_with_router, tmp_path
):
    """No thumbnail cache is written for a row that escapes the roots."""
    music = tmp_path / "music_src"
    music.mkdir()
    outside_dir = tmp_path / "elsewhere"
    victim = _seed_poster_file(outside_dir, "secret.jpg")
    config = ChubConfig()
    config.poster_renamerr.music_source_dirs = [str(music)]

    client = _serving_app(
        app_with_router,
        monkeypatch,
        config,
        {"file": str(victim), "folder": outside_dir.name},
    )
    resp = client.get("/api/posters/1/thumbnail")

    assert resp.status_code == 403, resp.text
    assert resp.json()["error_code"] == "PATH_TRAVERSAL_DENIED"
    assert not (outside_dir / ".thumbnails").exists()


# --- Inbound webhook verification under a broken config ---


def test_webhook_rejected_when_config_malformed(monkeypatch, app_with_router):
    """A malformed config must reject the webhook, never wave it through."""
    from backend.api import webhooks as webhooks_router
    from backend.util.config import ConfigError

    def _raise(*_a, **_kw):
        """Stand in for load_config on a malformed config file."""
        raise ConfigError("corrupt config")

    class _TripwireDB:
        """Records any attribute touch — a touch means the body got processed."""

        def __init__(self):
            """Start with no touches recorded."""
            self.touched = []

        def __getattr__(self, name):
            """Record the access and honor the special-method contract."""
            self.touched.append(name)
            raise AttributeError(name)

    monkeypatch.setattr(webhooks_router, "load_config", _raise)
    app = app_with_router(webhooks_router.router)
    db = _TripwireDB()
    app.state.db = db
    from backend.api.main import handle_config_error
    from backend.util.config import ConfigError as _CfgErr

    app.add_exception_handler(_CfgErr, handle_config_error)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/webhooks/poster/add", json={"eventType": "Download"})

    # The shared contract: ConfigError propagates from the secret dependency.
    assert resp.status_code == 500
    assert resp.json()["error_code"] == "CONFIG_INVALID"
    assert db.touched == [], f"webhook body was processed: db.{db.touched}"


def test_webhook_config_read_failure_rejects_without_enqueue(
    monkeypatch, app_with_router, tmp_path
):
    """An unreadable config (OSError) rejects the webhook and enqueues nothing."""
    from backend.api import webhooks as webhooks_router
    from backend.api.main import handle_config_error
    from backend.util.config import ConfigError, clear_config_cache

    # A directory where config.yml belongs -> open() raises IsADirectoryError,
    # which load_config wraps into ConfigParseError (a ConfigError).
    (tmp_path / "config.yml").mkdir()
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    clear_config_cache()

    enqueued = []

    class _Worker:
        """Tripwire: records any enqueue attempt instead of doing one."""

        def enqueue_job(self, *a, **k):
            """Record the call so the test can assert it never happened."""
            enqueued.append(a)
            return {"success": True, "data": {"job_id": 1}}

    class _DB:
        """Minimal db stub exposing only the job worker."""

        worker = _Worker()

    app = app_with_router(webhooks_router.router)
    app.state.db = _DB()
    app.add_exception_handler(ConfigError, handle_config_error)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/api/webhooks/poster/add", json={"eventType": "Download"})

    # The secret dependency propagates ConfigError to the shared handler
    # before the body runs — CONFIG_INVALID, and nothing was enqueued.
    assert resp.status_code == 500
    assert resp.json()["error_code"] == "CONFIG_INVALID"
    assert enqueued == []
    clear_config_cache()


def test_webhook_signed_path_still_accepted(monkeypatch):
    """A valid config still accepts the right secret and rejects a wrong one."""
    from types import SimpleNamespace

    from fastapi import HTTPException

    from backend.api import webhooks as webhooks_router

    cfg = ChubConfig()
    cfg.general.webhook_secret = "s3cret"
    monkeypatch.setattr(webhooks_router, "load_config", lambda *a, **k: cfg)

    good = SimpleNamespace(headers={"X-Webhook-Secret": "s3cret"}, query_params={})
    assert webhooks_router.verify_webhook_secret(good) is None

    bad = SimpleNamespace(headers={"X-Webhook-Secret": "nope"}, query_params={})
    with pytest.raises(HTTPException) as excinfo:
        webhooks_router.verify_webhook_secret(bad)
    assert excinfo.value.status_code == 401


# --- Error-response hygiene ---


def test_error_body_omits_exception_text(app_with_router):
    """A raising dependency yields the stable message — never the exception text."""

    class _BoomStats:
        """Stats interface that raises like a real internal failure."""

        def get_matched_posters_stats(self, *a, **kw):
            """Simulate an arbitrary internal error carrying sensitive text."""
            raise RuntimeError("LEAK_MARKER /srv/secret/chub.db")

    class _Boom:
        """Stub db exposing the raising stats interface the route reads."""

        stats = _BoomStats()

    app = app_with_router(posters_router.router)
    app.state.db = _Boom()
    client = TestClient(app)
    resp = client.get("/api/posters/stats")

    assert resp.status_code == 500
    body = resp.json()
    assert body["error_code"] == "POSTER_STATS_ERROR"
    assert body["message"] == "Error retrieving poster statistics"
    # The whole body, not just message — detail must not reach data/ either.
    assert "LEAK_MARKER" not in resp.text
