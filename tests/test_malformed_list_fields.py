"""Malformed array fields must fail in the direction that is safe for the site.

as_list coerces to [] where empty is harmless. Where empty means "delete" or
"write a degraded record", the malformed value has to be rejected instead —
coercing there turns a loud crash into silent data loss.
"""

import pytest

from backend.util.helper import as_list
from backend.util.webhook_provisioner import _webhook_template


@pytest.mark.parametrize("bad", [1, "oops", {"a": 1}, None])
def test_as_list_coerces_where_empty_is_safe(bad):
    assert as_list(bad) == []


@pytest.mark.parametrize("bad", [1, "fields", {"name": "url"}])
def test_webhook_template_rejected_when_fields_is_not_a_list(bad):
    """A coerced [] would submit a webhook with no url and no method; returning
    None instead selects the caller's stable fallback body."""
    schema = [{"implementation": "Webhook", "fields": bad}]
    assert _webhook_template(schema) is None


def test_webhook_template_accepted_when_fields_is_a_list():
    tmpl = {"implementation": "Webhook", "fields": [{"name": "url"}]}
    assert _webhook_template([tmpl]) == tmpl


def test_webhook_template_accepted_when_fields_absent():
    tmpl = {"implementation": "Webhook"}
    assert _webhook_template([tmpl]) == tmpl


@pytest.mark.parametrize("bad", [1, "seasons", {"a": 1}])
def test_connector_rejects_malformed_seasons(bad):
    """sync_for_instance deletes rows absent from fresh_media, so coercing a
    malformed seasons value to [] would delete the artist's cached albums."""
    from backend.util.connector import Connector

    conn = object.__new__(Connector)
    with pytest.raises(ValueError, match="refusing to sync"):
        conn._process_arr_media(
            [{"title": "A", "musicbrainz_id": "x", "seasons": bad}], "artist"
        )


def test_connector_accepts_absent_seasons():
    """seasons=None is normal when include_episode=False."""
    from backend.util.connector import Connector

    conn = object.__new__(Connector)
    rows = conn._process_arr_media(
        [{"title": "A", "musicbrainz_id": "x", "seasons": None}], "artist"
    )
    assert len(rows) == 1 and rows[0]["title"] == "A"
