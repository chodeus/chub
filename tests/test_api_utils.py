"""Tests for backend/api/utils.py — response factories."""

import json

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
