"""Tests for backend/api/utils.py — response factories and the module logger."""

import json
import logging
from types import SimpleNamespace

import pytest

from backend.api.utils import error, ok


def _decode(resp):
    return resp.status_code, json.loads(resp.body)


def test_ok_basic():
    code, body = _decode(ok("Hello"))
    assert code == 200
    assert body == {"success": True, "message": "Hello"}


def test_ok_with_data():
    code, body = _decode(ok("Hello", {"x": 1}))
    assert body["data"] == {"x": 1}


def test_ok_custom_status():
    code, _ = _decode(ok("Created", status_code=201))
    assert code == 201


def test_ok_data_none_omitted():
    """When data is None, the 'data' key should not be present."""
    _, body = _decode(ok("Hello", data=None))
    assert "data" not in body


def test_error_basic():
    code, body = _decode(error("Bad", code="X_ERR"))
    assert code == 400
    assert body == {"success": False, "message": "Bad", "error_code": "X_ERR"}


def test_error_with_data_and_status():
    code, body = _decode(error("Oops", code="VAL", data={"field": "x"}, status_code=422))
    assert code == 422
    assert body["data"] == {"field": "x"}
    assert body["error_code"] == "VAL"


def test_error_default_code():
    _, body = _decode(error("Bad"))
    assert body["error_code"] == "UNKNOWN_ERROR"


# --- get_module_logger reads live config -----------------------------------

_PROBE = "cr_logger_probe"


@pytest.fixture
def probe_logger(monkeypatch, tmp_path):
    """Isolate one module logger: own log dir, own caches, torn down after."""
    from backend.api import utils as api_utils
    from backend.util.logger import Logger

    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    yield api_utils
    stdlib = logging.getLogger(_PROBE)
    for handler in list(stdlib.handlers):
        stdlib.removeHandler(handler)
        handler.close()
    api_utils._module_loggers.pop(_PROBE, None)
    Logger._initialized = {key for key in Logger._initialized if key[0] != _PROBE}


def _config(log_level, max_logs=9):
    """Stand-in load_config exposing one module section plus general."""
    return lambda *a, **kw: SimpleNamespace(
        **{
            _PROBE: SimpleNamespace(log_level=log_level),
            "general": SimpleNamespace(max_logs=max_logs),
        }
    )


def test_module_logger_picks_up_a_config_change_between_calls(
    probe_logger, monkeypatch
):
    """A log_level edit must reach the next request, not stay frozen at first use."""
    monkeypatch.setattr("backend.util.config.load_config", _config("info"))
    probe_logger.get_module_logger(None, _PROBE)
    assert logging.getLogger(_PROBE).level == logging.INFO

    monkeypatch.setattr("backend.util.config.load_config", _config("debug"))
    adapter = probe_logger.get_module_logger(None, _PROBE)

    assert logging.getLogger(_PROBE).level == logging.DEBUG
    assert adapter.isEnabledFor(logging.DEBUG)


def _rotating_handlers():
    """The probe logger's rotating file handlers, in attach order."""
    return [h for h in logging.getLogger(_PROBE).handlers if hasattr(h, "backupCount")]


def test_module_logger_applies_max_logs_without_reopening_the_file(
    probe_logger, monkeypatch
):
    """max_logs rides onto the live handler — same handler object, new backupCount."""
    monkeypatch.setattr("backend.util.config.load_config", _config("info", max_logs=3))
    probe_logger.get_module_logger(None, _PROBE)
    handlers = _rotating_handlers()
    assert [h.backupCount for h in handlers] == [3]

    monkeypatch.setattr("backend.util.config.load_config", _config("info", max_logs=7))
    probe_logger.get_module_logger(None, _PROBE)

    assert [h.backupCount for h in handlers] == [7]
    assert _rotating_handlers() == handlers
