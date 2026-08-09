"""Tests for /cl2k-maker/test-ai — the AI provider connectivity probe.

The point of the endpoint is to tell apart states that all look identical from
the UI today: unreachable, reachable-but-key-rejected, and reachable-but-the-
sidecar-isn't-enforcing-a-key-at-all. The last one is why /health can't be used:
it is deliberately open, so it answers 200 with a wrong key or none.
"""

import json
import types

import pytest

pytest.importorskip("wand.image")  # backend.api.cl2k_maker pulls in the renderer

import backend.api.cl2k_maker as cl2k_api  # noqa: E402


def _logger():
    noop = lambda *a, **k: None  # noqa: E731
    return types.SimpleNamespace(debug=noop, info=noop, warning=noop, error=noop)


def _resp(status):
    return types.SimpleNamespace(status_code=status, ok=200 <= status < 300)


@pytest.fixture
def provider(monkeypatch):
    """Configure the provider and script the HTTP layer.

    ``posts`` maps "authenticated"/"bare" to a status code so a test can make the
    keyless re-probe differ from the authenticated one.
    """
    calls = []

    def _set(ai_provider="lama_sidecar", client_key="s3cret", api_key="",
             posts=None, gets=None, raises=None):
        cfg = types.SimpleNamespace(
            ai_provider=ai_provider,
            ai_endpoint="http://lama-sidecar:8418",
            client_key=client_key,
            api_key=api_key,
            ai_timeout=120,
        )
        monkeypatch.setattr(
            cl2k_api, "load_config", lambda: types.SimpleNamespace(cl2k_maker=cfg)
        )
        posts = posts or {}

        def fake_post(url, json=None, headers=None, timeout=None):
            authed = bool(headers and headers.get("X-API-Key"))
            calls.append(("post", authed))
            if raises:
                raise raises
            return _resp(posts.get("authenticated" if authed else "bare", 200))

        def fake_get(url, headers=None, timeout=None):
            calls.append(("get", bool(headers and headers.get("Authorization"))))
            if raises:
                raise raises
            return _resp((gets or {}).get("status", 200))

        monkeypatch.setitem(
            __import__("sys").modules,
            "requests",
            types.SimpleNamespace(post=fake_post, get=fake_get),
        )
        return calls

    return _set


def _call():
    return cl2k_api.test_ai(db=object(), logger=_logger())


def _body(resp):
    return json.loads(bytes(resp.body))


def test_no_provider_is_reported_not_probed(provider):
    provider(ai_provider="none")
    resp = _call()
    assert resp.status_code == 400
    assert _body(resp)["error_code"] == "CL2K_AI_UNAVAILABLE"


def test_unreachable_sidecar_names_the_endpoint(provider):
    provider(raises=OSError("connection refused"))
    resp = _call()
    assert resp.status_code == 400
    body = _body(resp)
    assert body["error_code"] == "CL2K_AI_TEST"
    assert "lama-sidecar:8418" in body["message"]


def test_rejected_key_is_distinguished_from_unreachable(provider):
    provider(posts={"authenticated": 401})
    resp = _call()
    assert resp.status_code == 400
    assert "match" in _body(resp)["message"]


def test_key_accepted_and_enforced(provider):
    # authenticated 200, unauthenticated 401 => the sidecar really is protected
    provider(posts={"authenticated": 200, "bare": 401})
    resp = _call()
    assert resp.status_code == 200
    assert "refused" in _body(resp)["message"]


def test_warns_when_the_sidecar_ignores_the_key(provider):
    """A 200 alone can't prove the key is doing anything — a keyless sidecar
    ignores the header. This is the exact state CHUB was in before LAMA_API_KEY
    was set, and nothing reported it."""
    provider(posts={"authenticated": 200, "bare": 200})
    resp = _call()
    assert resp.status_code == 200
    assert "not set on the container" in _body(resp)["message"]


def test_keyless_config_says_so_without_a_second_probe(provider):
    calls = provider(client_key="")
    resp = _call()
    assert resp.status_code == 200
    assert "accepting anyone" in _body(resp)["message"]
    assert len(calls) == 1, "no point re-probing when no key is configured"


def test_keyed_sidecar_but_empty_chub_key_is_named_precisely(provider):
    """Container keyed, CHUB not — the exact asymmetry that silently 401s every
    erase. Reporting it as "rejected the key... must match" would send you
    comparing two values when one of them isn't set."""
    provider(client_key="", posts={"bare": 401})
    resp = _call()
    assert resp.status_code == 400
    msg = _body(resp)["message"]
    assert "is empty" in msg and "must match" not in msg


def test_openai_key_rejected(provider):
    provider(ai_provider="openai", client_key="", api_key="sk-bad", gets={"status": 401})
    resp = _call()
    assert resp.status_code == 400
    assert "rejected" in _body(resp)["message"]


def test_openai_ok(provider):
    calls = provider(ai_provider="openai", client_key="", api_key="sk-good")
    resp = _call()
    assert resp.status_code == 200
    assert calls == [("get", True)], "must send the key, and must not touch the sidecar"
