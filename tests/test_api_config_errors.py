"""Tests for the ConfigError FastAPI exception handler.

A malformed or unmigratable config used to surface as an opaque
"Internal server error" 500 with the per-field detail stripped. The
handler under test turns those into a clear CONFIG_INVALID envelope and
logs the parse/validation detail. We register the real handler on a fresh
minimal app (the production app's lifespan is heavy) and drive it with
routes that raise the two ConfigError subclasses.
"""

import os
import sys

import pytest

pytest.importorskip("httpx")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("CONFIG_DIR", os.path.join(os.path.dirname(__file__), ".cfgtmp"))

from backend.api.main import handle_config_error  # noqa: E402
from backend.util.config import (  # noqa: E402
    ChubConfig,
    ConfigError,
    ConfigParseError,
    ConfigValidationError,
)


class StubLogger:
    def __init__(self):
        self.errors = []

    def error(self, msg, *a, **kw):
        self.errors.append(msg)

    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def debug(self, *a, **kw):
        pass

    def get_adapter(self, *_a, **_kw):
        return self


def _client():
    app = FastAPI()
    logger = StubLogger()
    app.state.logger = logger
    app.add_exception_handler(ConfigError, handle_config_error)

    @app.get("/parse")
    def _parse():
        raise ConfigParseError(
            "Invalid YAML syntax in /config/config.yml: line 309 column 3"
        )

    @app.get("/validate")
    def _validate():
        try:
            ChubConfig.model_validate(
                {"poster_cleanarr": {"instances": [{"plex": {}}]}}
            )
        except ValidationError as e:
            raise ConfigValidationError(
                "Configuration validation failed in /config/config.yml",
                validation_error=e,
            ) from e

    # raise_server_exceptions=False so the handler runs instead of re-raising.
    return TestClient(app, raise_server_exceptions=False), logger


def test_parse_error_returns_clear_envelope():
    client, logger = _client()
    resp = client.get("/parse")
    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] is False
    assert body["error_code"] == "CONFIG_INVALID"
    # The YAML line detail is preserved in the message, not buried as a 500.
    assert "line 309" in body["message"]
    # And it was logged, not swallowed.
    assert any("line 309" in str(m) for m in logger.errors)


def test_validation_error_includes_per_field_detail():
    client, logger = _client()
    resp = client.get("/validate")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error_code"] == "CONFIG_INVALID"
    # Per-field detail is surfaced in the response data...
    errors = body["data"]["errors"]
    assert any("poster_cleanarr" in line and "instances" in line for line in errors)
    # ...and each field line is logged individually (the previously-dead
    # format_validation_errors output now reaches the log).
    assert any("poster_cleanarr" in str(m) for m in logger.errors)
