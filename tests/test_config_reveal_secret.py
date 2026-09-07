"""The on-demand secret-reveal path (GET /api/config/secret) backs the "show"
eye-toggle on secret inputs. Every other read path redacts secrets to
'********'; this one deliberately returns the real value, so it must be tight:
only genuine secret leaves, never password_hash / jwt_secret, and no-store.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from backend.util.config import (  # noqa: E402
    ChubConfig,
    NotificationDestination,
    SecretNotRevealable,
    resolve_secret_path,
)


# ---- resolve_secret_path (pure resolver) -----------------------------------


def test_resolve_nested_dict_secret():
    data = {"tmdb": {"apikey": "REAL-KEY"}}
    assert resolve_secret_path(data, "tmdb.apikey") == "REAL-KEY"


def test_resolve_list_item_by_id():
    data = {
        "notifications": {
            "destinations": [
                {"id": "a", "config": {"webhook": "WH-A"}},
                {"id": "b", "config": {"webhook": "WH-B"}},
            ]
        }
    }
    # Match by stable id, not list position.
    assert (
        resolve_secret_path(data, "notifications.destinations.b.config.webhook")
        == "WH-B"
    )


def test_resolve_none_secret_returns_empty_string():
    assert resolve_secret_path({"tmdb": {"apikey": None}}, "tmdb.apikey") == ""


def test_non_secret_leaf_is_refused():
    with pytest.raises(SecretNotRevealable):
        resolve_secret_path(
            {"user_interface": {"theme": "dark"}}, "user_interface.theme"
        )


def test_never_reveal_fields_are_refused():
    for leaf in ("password_hash", "jwt_secret"):
        with pytest.raises(SecretNotRevealable):
            resolve_secret_path({"auth": {leaf: "x"}}, f"auth.{leaf}")


def test_missing_sensitive_path_raises_keyerror():
    # Leaf name is a real secret, but the path doesn't resolve.
    with pytest.raises(KeyError):
        resolve_secret_path({"instances": {"radarr": {}}}, "instances.radarr.Ghost.api")


def test_empty_path_raises_keyerror():
    with pytest.raises(KeyError):
        resolve_secret_path({}, "")


# ---- GET /api/config/secret (endpoint) -------------------------------------

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.api import config as cfg_api  # noqa: E402


class _StubLog:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def get_adapter(self, *a, **k):
        return self


def _client(cfg):
    app = FastAPI()
    app.state.logger = _StubLog()
    app.include_router(cfg_api.router)

    def _load():
        return cfg

    app.dependency_overrides[cfg_api.get_config_dep] = _load
    return TestClient(app)


def _cfg():
    cfg = ChubConfig()
    cfg.tmdb.apikey = "REAL-TMDB-KEY"
    cfg.auth.password_hash = "SECRET-HASH"
    cfg.notifications.destinations.append(
        NotificationDestination(
            id="dest1",
            method="discord",
            config={"webhook": "https://discord.com/api/webhooks/xyz"},
        )
    )
    return cfg


def test_reveal_returns_real_secret_and_no_store():
    resp = _client(_cfg()).get("/api/config/secret", params={"path": "tmdb.apikey"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["value"] == "REAL-TMDB-KEY"
    assert resp.headers.get("cache-control") == "no-store"


def test_reveal_resolves_destination_webhook_by_id():
    resp = _client(_cfg()).get(
        "/api/config/secret",
        params={"path": "notifications.destinations.dest1.config.webhook"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["value"] == "https://discord.com/api/webhooks/xyz"


def test_reveal_refuses_password_hash():
    resp = _client(_cfg()).get(
        "/api/config/secret", params={"path": "auth.password_hash"}
    )
    assert resp.status_code == 403


def test_reveal_refuses_non_secret_field():
    resp = _client(_cfg()).get(
        "/api/config/secret", params={"path": "user_interface.theme"}
    )
    assert resp.status_code == 403


def test_reveal_missing_path_is_404():
    resp = _client(_cfg()).get(
        "/api/config/secret", params={"path": "instances.radarr.Ghost.api"}
    )
    assert resp.status_code == 404
