"""Redacted-secret round-trip safety. A config GET redacts secrets to the
placeholder; a save that sends the placeholder back must keep the stored secret,
never persist '********'. Covers TMDB/Fanart (scalar keys) and the
secret-bearing destinations list (must resolve by id, not list position).
"""

from backend.util.config import (
    REDACTED_PLACEHOLDER,
    redact_secrets,
    strip_redacted_placeholders,
)


def test_tmdb_and_fanart_keys_survive_redacted_save():
    current = {
        "tmdb": {"api_key": "TMDB-REAL"},
        "fanart": {"api_key": "FANART-REAL", "client_key": "FANART-CLIENT"},
    }
    # What the frontend receives on GET.
    redacted = redact_secrets(current)
    assert redacted["tmdb"]["api_key"] == REDACTED_PLACEHOLDER
    assert redacted["fanart"]["api_key"] == REDACTED_PLACEHOLDER
    assert redacted["fanart"]["client_key"] == REDACTED_PLACEHOLDER

    # Saving without retyping the keys sends the redacted values back.
    merged = strip_redacted_placeholders(redacted, current)
    assert merged["tmdb"]["api_key"] == "TMDB-REAL"
    assert merged["fanart"]["api_key"] == "FANART-REAL"
    assert merged["fanart"]["client_key"] == "FANART-CLIENT"


def test_real_new_key_overwrites_stored():
    current = {"tmdb": {"api_key": "OLD"}}
    incoming = {"tmdb": {"api_key": "NEW-REAL-KEY"}}
    assert (
        strip_redacted_placeholders(incoming, current)["tmdb"]["api_key"]
        == "NEW-REAL-KEY"
    )


def test_reordered_secret_list_resolves_by_id_not_position():
    current = [
        {"id": "a", "config": {"webhook": "SECRET-A"}},
        {"id": "b", "config": {"webhook": "SECRET-B"}},
    ]
    # Same list, reordered, both webhooks redacted (as a GET would return).
    incoming = [
        {"id": "b", "config": {"webhook": REDACTED_PLACEHOLDER}},
        {"id": "a", "config": {"webhook": REDACTED_PLACEHOLDER}},
    ]
    merged = strip_redacted_placeholders(incoming, current)
    by_id = {d["id"]: d["config"]["webhook"] for d in merged}
    # Each secret stays with its own id — NOT swapped by position.
    assert by_id == {"a": "SECRET-A", "b": "SECRET-B"}


def test_deleted_middle_item_does_not_shift_secrets():
    current = [
        {"id": "a", "config": {"webhook": "SECRET-A"}},
        {"id": "b", "config": {"webhook": "SECRET-B"}},
        {"id": "c", "config": {"webhook": "SECRET-C"}},
    ]
    incoming = [  # 'b' removed; a and c sent redacted
        {"id": "a", "config": {"webhook": REDACTED_PLACEHOLDER}},
        {"id": "c", "config": {"webhook": REDACTED_PLACEHOLDER}},
    ]
    merged = strip_redacted_placeholders(incoming, current)
    by_id = {d["id"]: d["config"]["webhook"] for d in merged}
    assert by_id == {"a": "SECRET-A", "c": "SECRET-C"}
