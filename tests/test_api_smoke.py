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
    """The /gdrive-presets endpoint serves the bundled CL2K/MM2K JSON."""
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
        assert entry["style"] in ("CL2K", "MM2K")
    # Spot-check a couple of canonical entries so we'd notice if the
    # bundled JSON gets mangled in a future commit.
    by_id = {e["id"]: e for e in presets}
    assert "1MiNjT3t_eIdaMTiQ4E89IMNXasco7r6q" in by_id  # CL2K Mario
    assert by_id["1MiNjT3t_eIdaMTiQ4E89IMNXasco7r6q"]["style"] == "CL2K"


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


def test_allowed_roots_returns_empty_when_no_config(monkeypatch, app_with_router):
    """Pre-onboarding (no config yet) the endpoint returns [] without crashing."""
    from backend.util.config import ConfigError

    def _raise(*_a, **_kw):
        raise ConfigError("no config")

    monkeypatch.setattr(system_router, "load_config", _raise)
    app = app_with_router(system_router.router)
    client = TestClient(app)
    resp = client.get("/api/allowed-roots")
    assert resp.status_code == 200
    assert resp.json()["data"]["roots"] == []
