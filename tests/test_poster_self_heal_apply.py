"""POST /api/poster-self-heal/reviews/{id}/apply — failure routing.

The handler owns ONE failure mode: the Drive rename. Everything else it touches
must keep its own. Config loading was inside the same guard, so a malformed
config.yml came back as a 400 "Google Drive rename failed" instead of reaching
main.py's ConfigError handler (500 CONFIG_INVALID) — the operator was sent to
look at Drive for a fault in their own file. And the rename's exception text
must stay in the log, never in the response (py/stack-trace-exposure).
"""

import json
import types

import pytest

from backend.api import poster_self_heal as heal
from backend.util.config import ConfigParseError

_SECRET = "rclone: /srv/media/posters token=hunter2"


def _logger():
    """Logger that records warnings/errors so the tests can read them back."""
    logged = []
    noop = lambda *a, **k: None  # noqa: E731
    return logged, types.SimpleNamespace(
        debug=noop,
        info=noop,
        warning=lambda m, *a, **k: logged.append(str(m)),
        error=lambda m, *a, **k: logged.append(str(m)),
    )


@pytest.fixture
def review(monkeypatch):
    """An open proposal the apply endpoint will act on."""
    row = {
        "id": 1,
        "status": "proposed",
        "current_filename": "Old (2020).jpg",
        "proposed_filename": "New (2020).jpg",
        "drift_type": "renamed",
        "poster_file": "",
    }
    monkeypatch.setattr(
        heal,
        "poster_heal_review_for",
        lambda db: types.SimpleNamespace(
            get=lambda rid: row, set_status=lambda *a, **k: None
        ),
    )
    return row


def _apply(logger):
    """Call the apply endpoint for the fixture review."""
    return heal.apply_review(1, db=object(), logger=logger)


def test_a_config_fault_is_not_reported_as_a_drive_failure(review, monkeypatch):
    """It must propagate to the shared ConfigError handler, not be swallowed."""
    monkeypatch.setattr(
        heal,
        "load_config",
        lambda: (_ for _ in ()).throw(ConfigParseError("bad YAML at line 3")),
    )
    monkeypatch.setattr(
        heal, "apply_proposal", lambda *a, **k: pytest.fail("ran despite a bad config")
    )
    _logged, logger = _logger()

    with pytest.raises(ConfigParseError):
        _apply(logger)


def test_a_rename_failure_keeps_its_reason_out_of_the_response(review, monkeypatch):
    """rclone quotes paths and tokens — that belongs in the log, not the body."""
    monkeypatch.setattr(
        heal, "load_config", lambda: types.SimpleNamespace(sync_gdrive=object())
    )

    def _boom(*a, **k):
        """Fail the rename with text that must not reach the response."""
        raise RuntimeError(_SECRET)

    monkeypatch.setattr(heal, "apply_proposal", _boom)
    logged, logger = _logger()

    resp = _apply(logger)

    assert resp.status_code == 400
    body = json.loads(bytes(resp.body))
    assert body["error_code"] == "DRIVE_RENAME"
    assert _SECRET not in body["message"]
    assert any(_SECRET in m for m in logged), "the reason must still be logged"
