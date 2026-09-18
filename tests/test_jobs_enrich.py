"""Tests for backend.api.jobs._enrich_jobs — module_name + trigger derivation
from the job payload's `origin` (drives the Jobs page TRIGGER column)."""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.api.jobs import _enrich_jobs  # noqa: E402


def test_enrich_maps_origin_to_trigger():
    jobs = [
        {
            "type": "module_run",
            "payload": json.dumps({"module_name": "labelarr", "origin": "scheduled"}),
        },
        {
            "type": "module_run",
            "payload": json.dumps({"module_name": "nestarr", "origin": "web"}),
        },
        {
            "type": "module_run",
            "payload": json.dumps({"module_name": "x", "origin": "cli"}),
        },
        {"type": "webhook", "payload": "{}"},
    ]
    out = _enrich_jobs(jobs)
    assert out[0]["trigger"] == "scheduled"
    assert out[0]["module_name"] == "labelarr"
    assert out[1]["trigger"] == "manual"  # web -> manual
    assert out[2]["trigger"] == "manual"  # cli -> manual
    assert out[3]["trigger"] == "webhook"


def test_enrich_unknown_origin_falls_back_to_manual():
    jobs = [{"type": "module_run", "payload": json.dumps({"module_name": "m"})}]
    out = _enrich_jobs(jobs)
    assert out[0]["trigger"] == "manual"
