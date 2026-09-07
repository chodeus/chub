"""GET /api/config/gdrive-credentials backs the settings-page shared-client
notice. The browser cannot stat the service-account keyfile, so the server
answers with the same predicate sync_gdrive uses at run time.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.api import config as cfg_api  # noqa: E402
from backend.util.config import ChubConfig  # noqa: E402


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


def _shared(cfg) -> bool:
    app = FastAPI()
    app.state.logger = _StubLog()
    app.include_router(cfg_api.router)
    app.dependency_overrides[cfg_api.get_config_dep] = lambda: cfg
    resp = TestClient(app).get("/api/config/gdrive-credentials")
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["shared_client_id"]


def _cfg(sa="", client_id=""):
    cfg = ChubConfig()
    cfg.sync_gdrive.gdrive_sa_location = sa
    cfg.sync_gdrive.client_id = client_id
    return cfg


def test_no_credentials_reports_the_shared_client():
    assert _shared(_cfg()) is True


def test_own_client_id_reports_not_shared():
    assert _shared(_cfg(client_id="mine.apps.google")) is False


def test_existing_service_account_reports_not_shared(tmp_path):
    sa = tmp_path / "sa.json"
    sa.write_text("{}")
    assert _shared(_cfg(sa=str(sa))) is False


def test_missing_service_account_reports_the_shared_client(tmp_path):
    """The case the form alone gets wrong — a path set, but no file behind it."""
    assert _shared(_cfg(sa=str(tmp_path / "nope.json"))) is True
