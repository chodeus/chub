"""Tests for backend/util/webhook_provisioner.py — arr webhook auto-provisioning."""

from types import SimpleNamespace

from backend.util import webhook_provisioner as wp
from backend.util.webhook_provisioner import (
    CHUB_NOTIFICATION_NAME,
    build_webhook_url,
    deprovision_instance,
    desired_webhook_body,
    diff_notification,
    normalize_base_url,
    provision_all,
    provision_instance,
)


class StubClient:
    """Mimics the arr client's notification CRUD surface."""

    def __init__(
        self,
        notifications=None,
        schema=None,
        unreachable=False,
        add_result="auto",
        update_result="auto",
        delete_result=True,
        lands_on_write=False,
    ):
        self._notifications = [] if notifications is None else notifications
        self._schema = schema
        self._unreachable = unreachable
        self._add_result = add_result
        self._update_result = update_result
        self._delete_result = delete_result
        # When True, a write mutates the stored notifications (as if the arr
        # saved it) even though the call returns a non-success — simulating a
        # lost/timed-out HTTP reply for verify-after-write.
        self._lands_on_write = lands_on_write
        self.calls = []
        self.session = SimpleNamespace(close=lambda: None)

    def is_connected(self):
        return True

    def get_notifications(self):
        return None if self._unreachable else self._notifications

    def get_notification_schema(self):
        return self._schema

    def add_notification(self, body, force_save=False):
        self.calls.append(("add", body, force_save))
        if self._add_result == "auto":
            return {"id": 7, **body}
        if self._lands_on_write:
            self._notifications = [{"id": 7, **body}]
        return self._add_result

    def update_notification(self, notification_id, body, force_save=False):
        self.calls.append(("update", notification_id, body, force_save))
        if self._update_result == "auto":
            return {"id": notification_id, **body}
        if self._lands_on_write:
            self._notifications = [{"id": notification_id, **body}]
        return self._update_result

    def delete_notification(self, notification_id):
        self.calls.append(("delete", notification_id))
        return self._delete_result


def _existing(url, *, onDownload=True, onUpgrade=False, added_key="onMovieAdded"):
    return {
        "id": 5,
        "name": CHUB_NOTIFICATION_NAME,
        "fields": [{"name": "url", "value": url}, {"name": "method", "value": 1}],
        "onDownload": onDownload,
        "onUpgrade": onUpgrade,
        added_key: False,
    }


# --- build_webhook_url / normalize_base_url ---


def test_build_webhook_url_encodes_instance_and_secret():
    url = build_webhook_url("http://h:8060/", "Radarr 4K", "a b&c")
    assert url == (
        "http://h:8060/api/webhooks/poster/add?instance=Radarr%204K&secret=a%20b%26c"
    )


def test_build_webhook_url_no_secret():
    url = build_webhook_url("http://h:8060", "Radarr", None)
    assert url == "http://h:8060/api/webhooks/poster/add?instance=Radarr"
    assert "secret=" not in url


def test_normalize_base_url_ok_strips_trailing_slash():
    norm, err = normalize_base_url("http://192.168.1.10:8060/")
    assert err is None
    assert norm == "http://192.168.1.10:8060"


def test_normalize_base_url_rejects_localhost():
    for bad in ("http://localhost:8060", "http://127.0.0.1:8060"):
        norm, err = normalize_base_url(bad)
        assert norm is None and err


def test_normalize_base_url_rejects_empty_and_non_http():
    assert normalize_base_url("")[0] is None
    assert normalize_base_url("   ")[0] is None
    assert normalize_base_url("ftp://x")[0] is None
    assert normalize_base_url("radarr.local:7878")[0] is None  # no scheme


# --- desired_webhook_body ---


def test_desired_body_import_only_radarr():
    body = desired_webhook_body("radarr", "http://h/hook", None)
    assert body["name"] == CHUB_NOTIFICATION_NAME
    assert body["implementation"] == "Webhook"
    assert body["configContract"] == "WebhookSettings"
    assert body["onDownload"] is True
    assert body["onUpgrade"] is False
    assert body["onGrab"] is False
    assert body["onMovieAdded"] is False
    assert "onSeriesAdd" not in body
    field = {f["name"]: f["value"] for f in body["fields"]}
    assert field["url"] == "http://h/hook"
    assert field["method"] == 1


def test_desired_body_include_upgrade():
    body = desired_webhook_body("radarr", "http://h/hook", None, include_upgrade=True)
    assert body["onUpgrade"] is True


def test_desired_body_sonarr_uses_series_add():
    body = desired_webhook_body("sonarr", "http://h/hook", None)
    assert body["onSeriesAdd"] is False
    assert "onMovieAdded" not in body


def test_desired_body_uses_schema_template():
    schema = [
        {"implementation": "Discord", "fields": []},
        {
            "implementation": "Webhook",
            "implementationName": "Webhook",
            "configContract": "WebhookSettings",
            "fields": [
                {"name": "url", "value": ""},
                {"name": "method", "value": 1},
                {"name": "username", "value": ""},
                {"name": "password", "value": ""},
            ],
        },
    ]
    body = desired_webhook_body("radarr", "http://h/hook", schema)
    names = {f["name"] for f in body["fields"]}
    assert names == {"url", "method", "username", "password"}  # template preserved
    field = {f["name"]: f["value"] for f in body["fields"]}
    assert field["url"] == "http://h/hook"
    assert field["method"] == 1


# --- diff_notification ---


def test_diff_no_drift():
    url = "http://h:8060/api/webhooks/poster/add?instance=Radarr"
    desired = desired_webhook_body("radarr", url, None)
    assert diff_notification(_existing(url), desired, "radarr") == []


def test_diff_url_change():
    desired = desired_webhook_body(
        "radarr", "http://new:8060/api/webhooks/poster/add?instance=Radarr", None
    )
    drift = diff_notification(_existing("http://old/hook"), desired, "radarr")
    assert "url" in drift


def test_diff_trigger_change():
    url = "http://h/hook"
    desired = desired_webhook_body("radarr", url, None, include_upgrade=True)
    drift = diff_notification(_existing(url, onUpgrade=False), desired, "radarr")
    assert "onUpgrade" in drift


# --- provision_instance ---


def test_provision_creates_when_absent():
    client = StubClient(notifications=[])
    res = provision_instance(client, "radarr", "Radarr", "http://chub:8060", None)
    assert res["status"] == "connected"
    assert res["action"] == "created"
    assert any(c[0] == "add" for c in client.calls)
    added_body = next(c[1] for c in client.calls if c[0] == "add")
    field = {f["name"]: f["value"] for f in added_body["fields"]}
    assert field["url"] == ("http://chub:8060/api/webhooks/poster/add?instance=Radarr")


def test_provision_noop_when_already_correct():
    url = build_webhook_url("http://chub:8060", "Radarr", None)
    client = StubClient(notifications=[_existing(url)])
    res = provision_instance(client, "radarr", "Radarr", "http://chub:8060", None)
    assert res["status"] == "connected"
    assert res["action"] == "noop"
    assert not any(c[0] in ("add", "update") for c in client.calls)


def test_provision_updates_on_drift():
    client = StubClient(notifications=[_existing("http://old/hook")])
    res = provision_instance(client, "radarr", "Radarr", "http://chub:8060", None)
    assert res["status"] == "connected"
    assert res["action"] == "updated"
    assert "url" in res["drift_fields"]
    upd = next(c for c in client.calls if c[0] == "update")
    assert upd[1] == 5  # existing id preserved


def test_provision_bakes_secret_into_url():
    client = StubClient(notifications=[])
    provision_instance(client, "radarr", "Radarr", "http://chub:8060", "topsecret")
    body = next(c[1] for c in client.calls if c[0] == "add")
    url = {f["name"]: f["value"] for f in body["fields"]}["url"]
    assert "secret=topsecret" in url and "instance=Radarr" in url


def test_provision_dry_run_reports_without_writing():
    absent = StubClient(notifications=[])
    res = provision_instance(
        absent, "radarr", "Radarr", "http://chub:8060", None, dry_run=True
    )
    assert res["status"] == "not_set_up"
    assert absent.calls == []

    drifted = StubClient(notifications=[_existing("http://old/hook")])
    res2 = provision_instance(
        drifted, "radarr", "Radarr", "http://chub:8060", None, dry_run=True
    )
    assert res2["status"] == "drift"
    assert res2["drift_fields"] == ["url"]
    assert drifted.calls == []


def test_provision_save_failure_surfaces_error():
    client = StubClient(notifications=[], add_result=None)  # arr rejected the save
    res = provision_instance(client, "radarr", "Radarr", "http://chub:8060", None)
    assert res["status"] == "failed"
    assert res["error"]


def test_provision_verify_after_write_recovers_lost_response():
    # The POST reply is lost (returns None) but the entry actually landed in the
    # arr — verify-after-write must report the true success, not a false failure.
    client = StubClient(notifications=[], add_result=None, lands_on_write=True)
    res = provision_instance(client, "radarr", "Radarr", "http://chub:8060", None)
    assert res["status"] == "connected"
    assert res["action"] == "created"


def test_provision_update_verify_after_write_recovers_lost_response():
    client = StubClient(
        notifications=[_existing("http://old/hook")],  # drift → triggers an update
        update_result=None,  # reply lost
        lands_on_write=True,  # but the update landed
    )
    res = provision_instance(client, "radarr", "Radarr", "http://chub:8060", None)
    assert res["status"] == "connected"
    assert res["action"] == "updated"


def test_provision_detects_foreign_webhook():
    foreign = {
        "id": 9,
        "name": "My Own Hook",
        "fields": [{"name": "url", "value": "http://x/api/webhooks/poster/add"}],
    }
    client = StubClient(notifications=[foreign])
    res = provision_instance(client, "radarr", "Radarr", "http://chub:8060", None)
    assert res["foreign_webhook"] == "My Own Hook"
    assert res["action"] == "created"  # still creates CHUB's own, doesn't touch theirs


def test_provision_unreachable_instance():
    client = StubClient(unreachable=True)
    res = provision_instance(client, "radarr", "Radarr", "http://chub:8060", None)
    assert res["status"] == "failed"
    assert res["error"]


# --- deprovision_instance ---


def test_deprovision_removes_existing():
    url = build_webhook_url("http://chub:8060", "Radarr", None)
    client = StubClient(notifications=[_existing(url)])
    res = deprovision_instance(client, "radarr", "Radarr")
    assert res["status"] == "not_set_up"
    assert res["action"] == "removed"
    assert ("delete", 5) in client.calls


def test_deprovision_noop_when_absent():
    client = StubClient(notifications=[])
    res = deprovision_instance(client, "radarr", "Radarr")
    assert res["action"] == "noop"
    assert not any(c[0] == "delete" for c in client.calls)


# --- provision_all (fleet: skip lidarr/disabled, per-instance isolation) ---


def _fake_config():
    return SimpleNamespace(
        general=SimpleNamespace(public_url=""),
        instances=SimpleNamespace(
            radarr={
                "Radarr": SimpleNamespace(url="http://r:7878", api="a", enabled=True),
                "Off": SimpleNamespace(url="http://o:7878", api="a", enabled=False),
            },
            sonarr={
                "Sonarr": SimpleNamespace(url="http://s:8989", api="b", enabled=True),
            },
            lidarr={
                "Lidarr": SimpleNamespace(url="http://l:8686", api="c", enabled=True),
            },
        ),
    )


def test_provision_all_skips_lidarr_and_disabled(monkeypatch):
    clients = {
        "http://r:7878": StubClient(notifications=[]),
        "http://s:8989": StubClient(notifications=[]),
    }
    monkeypatch.setattr(
        wp, "create_arr_client", lambda url, api, logger: clients.get(url)
    )
    results = provision_all(_fake_config(), "http://chub:8060", None)
    by_name = {r["name"]: r for r in results}
    assert by_name["Radarr"]["status"] == "connected"
    assert by_name["Sonarr"]["status"] == "connected"
    assert by_name["Lidarr"]["status"] == "skipped"
    assert by_name["Off"]["status"] == "skipped"


# --- base-URL auto-detection + resolution ---


def test_base_of_extracts_scheme_host_port():
    assert (
        wp._base_of("http://192.168.2.206:8060/api/webhooks/poster/add?instance=Radarr")
        == "http://192.168.2.206:8060"
    )
    assert wp._base_of("https://chub.example.com/api/webhooks/poster/add") == (
        "https://chub.example.com"
    )
    assert wp._base_of("not-a-url") is None
    assert wp._base_of("ftp://x/y") is None


def test_detect_base_url_from_existing_webhook(monkeypatch):
    existing = {
        "id": 3,
        "name": "Some Hook",
        "fields": [
            {
                "name": "url",
                "value": "http://192.168.2.206:8060/api/webhooks/poster/add?instance=Radarr",
            }
        ],
    }
    clients = {
        "http://r:7878": StubClient(notifications=[existing]),
        "http://s:8989": StubClient(notifications=[]),
    }
    monkeypatch.setattr(
        wp, "create_arr_client", lambda url, api, logger: clients.get(url)
    )
    assert wp.detect_base_url(_fake_config()) == "http://192.168.2.206:8060"


def test_detect_base_url_none_when_no_matching_webhook(monkeypatch):
    clients = {
        "http://r:7878": StubClient(notifications=[]),
        "http://s:8989": StubClient(notifications=[]),
    }
    monkeypatch.setattr(
        wp, "create_arr_client", lambda url, api, logger: clients.get(url)
    )
    assert wp.detect_base_url(_fake_config()) is None


def test_resolve_base_url_precedence(monkeypatch):
    cfg = _fake_config()
    monkeypatch.setattr(wp, "detect_base_url", lambda *a, **k: "http://detected:8060")

    # 1) explicit wins, and detection is skipped
    base, detected, err = wp.resolve_base_url(
        cfg, "http://explicit:8060", origin_hint="http://origin:8060"
    )
    assert (base, detected, err) == ("http://explicit:8060", "", None)

    # 2) saved public_url beats detection + origin
    cfg.general.public_url = "http://public:8060"
    base, detected, err = wp.resolve_base_url(cfg, "", origin_hint="http://origin:8060")
    assert base == "http://public:8060" and detected == ""

    # 3) detection used when neither explicit nor public_url is set
    cfg.general.public_url = ""
    base, detected, err = wp.resolve_base_url(cfg, "", origin_hint="http://origin:8060")
    assert base == "http://detected:8060" and detected == "http://detected:8060"

    # 4) origin hint is the last resort
    monkeypatch.setattr(wp, "detect_base_url", lambda *a, **k: None)
    base, detected, err = wp.resolve_base_url(cfg, "", origin_hint="http://origin:8060")
    assert base == "http://origin:8060" and detected == ""


def test_status_report_reconciles_against_detected_base(monkeypatch):
    clients = {
        "http://r:7878": StubClient(notifications=[]),
        "http://s:8989": StubClient(notifications=[]),
    }
    monkeypatch.setattr(
        wp, "create_arr_client", lambda url, api, logger: clients.get(url)
    )
    monkeypatch.setattr(wp, "detect_base_url", lambda *a, **k: "http://detected:8060")
    report = wp.status_report(
        _fake_config(), None, explicit="", origin_hint="http://origin:8060"
    )
    assert report["base_url"] == "http://detected:8060"
    assert report["detected_base_url"] == "http://detected:8060"
    names = {r["name"] for r in report["instances"]}
    assert {"Radarr", "Sonarr"} <= names
