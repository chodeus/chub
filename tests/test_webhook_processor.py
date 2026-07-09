"""Tests for backend/util/webhook_processor.py — webhook parsing & instance routing."""

from types import SimpleNamespace

import pytest

from backend.util.config import ChubConfig, InstanceDetail, InstancesConfig
from backend.util.webhook_processor import WebhookProcessor


class StubLogger:
    def debug(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def get_adapter(self, *_a, **_kw):
        return self


@pytest.fixture
def wp(monkeypatch):
    """A processor with a known instance config."""
    cfg = ChubConfig(
        instances=InstancesConfig(
            radarr={"main": InstanceDetail(url="http://192.168.1.10:7878", api="x")},
            sonarr={"main": InstanceDetail(url="http://192.168.1.11:8989", api="y")},
        ),
    )
    monkeypatch.setattr("backend.util.webhook_processor.load_config", lambda: cfg)
    return WebhookProcessor(logger=StubLogger())


# --- _extract_media_block ---


def test_extract_media_block_series(wp):
    payload = {"series": {"id": 42, "title": "Show"}}
    block, type_, id_ = wp._extract_media_block(payload)
    assert type_ == "series"
    assert id_ == 42


def test_processor_fallback_retry_defaults_match_general_config(monkeypatch):
    cfg = SimpleNamespace(instances=InstancesConfig())
    monkeypatch.setattr("backend.util.webhook_processor.load_config", lambda: cfg)

    processor = WebhookProcessor(logger=StubLogger())

    assert processor.initial_delay == 30
    assert processor.retry_delay == 30
    assert processor.max_retries == 10


def test_extract_media_block_movie(wp):
    payload = {"movie": {"id": 99, "title": "Movie"}}
    block, type_, id_ = wp._extract_media_block(payload)
    assert type_ == "movie"
    assert id_ == 99


def test_extract_media_block_unknown_returns_none(wp):
    block, type_, id_ = wp._extract_media_block({"foo": "bar"})
    assert (block, type_, id_) == (None, None, None)


# --- _extract_season_number ---


def test_extract_season_number_from_episodes():
    assert (
        WebhookProcessor._extract_season_number({"episodes": [{"seasonNumber": 3}]})
        == 3
    )


def test_extract_season_number_no_episodes():
    assert WebhookProcessor._extract_season_number({}) is None
    assert WebhookProcessor._extract_season_number({"episodes": []}) is None


def test_extract_season_number_invalid_value():
    assert (
        WebhookProcessor._extract_season_number(
            {"episodes": [{"seasonNumber": "not-a-number"}]}
        )
        is None
    )


def test_extract_season_number_zero_valid():
    # Specials = 0; valid integer
    assert (
        WebhookProcessor._extract_season_number({"episodes": [{"seasonNumber": 0}]})
        == 0
    )


# --- _find_arr_instance ---


def test_find_arr_instance_matches_radarr(wp):
    result = wp._find_arr_instance(
        {"client_host": "192.168.1.10", "scheme": "http"}, "movie"
    )
    assert result["found"] is True
    assert result["type"] == "radarr"
    assert result["name"] == "main"


def test_find_arr_instance_matches_sonarr(wp):
    result = wp._find_arr_instance({"client_host": "192.168.1.11"}, "series")
    assert result["found"] is True
    assert result["type"] == "sonarr"


def test_find_arr_instance_ignores_source_port(wp):
    # The connection's source port is never the arr's listen port, so a
    # non-8989 port must NOT block a peer-IP match (the old host+port check did).
    result = wp._find_arr_instance(
        {"client_host": "192.168.1.11", "client_port": 51234}, "series"
    )
    assert result["found"] is True
    assert result["type"] == "sonarr"


def test_find_arr_instance_normalizes_localhost(monkeypatch):
    cfg = ChubConfig(
        instances=InstancesConfig(
            radarr={
                "main": InstanceDetail(url="http://localhost:7878", api="x"),
            }
        ),
    )
    monkeypatch.setattr("backend.util.webhook_processor.load_config", lambda: cfg)
    wp = WebhookProcessor(logger=StubLogger())

    # 127.0.0.1 normalizes to localhost -> matches
    result = wp._find_arr_instance({"client_host": "127.0.0.1"}, "movie")
    assert result["found"] is True


def test_find_arr_instance_no_client_info_returns_not_found(wp):
    result = wp._find_arr_instance(None)
    assert result["found"] is False


def test_find_arr_instance_unknown_host_no_match(wp):
    # Two candidate buckets, a peer IP matching neither -> fail closed rather
    # than guess (the single-instance fallback only applies when exactly one
    # instance of the media type exists).
    result = wp._find_arr_instance({"client_host": "10.0.0.99"}, media_type=None)
    assert result["found"] is False


def _two_sonarr_wp(monkeypatch, resolver):
    cfg = ChubConfig(
        instances=InstancesConfig(
            sonarr={
                "Shows": InstanceDetail(url="http://sonarr:8989", api="a"),
                "Anime": InstanceDetail(url="http://sonarr-anime:8989", api="b"),
            }
        ),
    )
    monkeypatch.setattr("backend.util.webhook_processor.load_config", lambda: cfg)
    monkeypatch.setattr(
        "backend.util.webhook_processor._resolve_ips",
        lambda host: frozenset(resolver.get(host, set())),
    )
    return WebhookProcessor(logger=StubLogger())


def test_find_arr_instance_resolves_docker_service_name(monkeypatch):
    # The reported case: instances configured by Docker service name, webhook
    # arrives from the container's IP with no usable port. DNS resolution of the
    # service name disambiguates the two Sonarr instances by IP.
    wp = _two_sonarr_wp(
        monkeypatch,
        {"sonarr": {"10.200.10.26"}, "sonarr-anime": {"10.200.10.27"}},
    )
    result = wp._find_arr_instance(
        {"client_host": "10.200.10.26", "client_port": None}, "series"
    )
    assert result["found"] is True
    assert result["name"] == "Shows"


def test_find_arr_instance_ambiguous_shared_ip_fails_closed(monkeypatch):
    # Host networking: both service names resolve to the same IP -> can't tell
    # them apart -> must fail closed rather than mis-route.
    wp = _two_sonarr_wp(
        monkeypatch,
        {"sonarr": {"10.200.10.26"}, "sonarr-anime": {"10.200.10.26"}},
    )
    result = wp._find_arr_instance({"client_host": "10.200.10.26"}, "series")
    assert result["found"] is False


def _same_host_two_sonarr_wp(monkeypatch, labels=("Shows", "Anime")):
    # Two Sonarr instances on the SAME host IP, different listen ports.
    a, b = labels
    cfg = ChubConfig(
        instances=InstancesConfig(
            sonarr={
                a: InstanceDetail(url="http://192.168.2.206:8989", api="a"),
                b: InstanceDetail(url="http://192.168.2.206:8990", api="b"),
            }
        ),
    )
    monkeypatch.setattr("backend.util.webhook_processor.load_config", lambda: cfg)
    return WebhookProcessor(logger=StubLogger())


def test_find_arr_instance_same_ip_diff_port_by_label(monkeypatch):
    # Same host IP, different ports: the listen port is unrecoverable, so the
    # payload instanceName (== the CHUB label here) breaks the tie with no
    # network call.
    wp = _same_host_two_sonarr_wp(monkeypatch)
    result = wp._find_arr_instance(
        {"client_host": "192.168.2.206", "client_port": 41999},
        "series",
        instance_name="Anime",
    )
    assert result["found"] is True
    assert result["name"] == "Anime"


def test_find_arr_instance_same_ip_diff_port_by_live_name(monkeypatch):
    # The CHUB labels differ from the arr instance names, so the tie is broken by
    # each candidate's live /system/status instanceName.
    wp = _same_host_two_sonarr_wp(monkeypatch, labels=("A", "B"))

    def fake_client(url, api, logger):
        name = "ShowsArr" if url.endswith(":8989") else "AnimeArr"
        return SimpleNamespace(
            instance_name=name,
            get_instance_name=lambda: name,
            session=SimpleNamespace(close=lambda: None),
        )

    monkeypatch.setattr("backend.util.arr.create_arr_client", fake_client)
    result = wp._find_arr_instance(
        {"client_host": "192.168.2.206"}, "series", instance_name="AnimeArr"
    )
    assert result["found"] is True
    assert result["name"] == "B"


def test_find_arr_instance_same_ip_same_name_fails_closed(monkeypatch):
    # Same IP and both report the same instanceName -> genuinely ambiguous ->
    # fail closed (the explicit ?instance= override is the remedy).
    wp = _same_host_two_sonarr_wp(monkeypatch, labels=("A", "B"))

    def fake_client(url, api, logger):
        return SimpleNamespace(
            instance_name="Sonarr",
            get_instance_name=lambda: "Sonarr",
            session=SimpleNamespace(close=lambda: None),
        )

    monkeypatch.setattr("backend.util.arr.create_arr_client", fake_client)
    result = wp._find_arr_instance(
        {"client_host": "192.168.2.206"}, "series", instance_name="Sonarr"
    )
    assert result["found"] is False


def test_find_arr_instance_same_ip_no_name_fails_closed(monkeypatch):
    # Same IP, no instanceName in the payload -> nothing to disambiguate on.
    wp = _same_host_two_sonarr_wp(monkeypatch)
    result = wp._find_arr_instance({"client_host": "192.168.2.206"}, "series")
    assert result["found"] is False


def test_find_arr_instance_override_wins(monkeypatch):
    # Explicit ?instance= selector routes deterministically, even when the peer
    # IP would auto-match a different instance.
    wp = _two_sonarr_wp(
        monkeypatch,
        {"sonarr": {"10.200.10.26"}, "sonarr-anime": {"10.200.10.27"}},
    )
    result = wp._find_arr_instance(
        {"client_host": "10.200.10.26", "instance_override": "Anime"}, "series"
    )
    assert result["found"] is True
    assert result["name"] == "Anime"


def test_find_arr_instance_override_unknown_fails_closed(monkeypatch):
    wp = _two_sonarr_wp(
        monkeypatch,
        {"sonarr": {"10.200.10.26"}, "sonarr-anime": {"10.200.10.27"}},
    )
    result = wp._find_arr_instance(
        {"client_host": "10.200.10.26", "instance_override": "Nope"}, "series"
    )
    assert result["found"] is False


def test_find_arr_instance_single_instance_fallback(monkeypatch):
    # One Sonarr behind a reverse proxy: peer IP is the proxy (matches nothing),
    # but a series webhook can only be the one configured Sonarr.
    cfg = ChubConfig(
        instances=InstancesConfig(
            sonarr={"Shows": InstanceDetail(url="http://sonarr:8989", api="a")},
        ),
    )
    monkeypatch.setattr("backend.util.webhook_processor.load_config", lambda: cfg)
    monkeypatch.setattr(
        "backend.util.webhook_processor._resolve_ips",
        lambda host: frozenset({"10.200.10.26"}),
    )
    wp = WebhookProcessor(logger=StubLogger())
    result = wp._find_arr_instance({"client_host": "172.20.0.5"}, "series")
    assert result["found"] is True
    assert result["name"] == "Shows"


def test_find_arr_instance_disabled_instance_skipped(monkeypatch):
    cfg = ChubConfig(
        instances=InstancesConfig(
            sonarr={
                "Shows": InstanceDetail(
                    url="http://sonarr:8989", api="a", enabled=False
                ),
            },
        ),
    )
    monkeypatch.setattr("backend.util.webhook_processor.load_config", lambda: cfg)
    monkeypatch.setattr(
        "backend.util.webhook_processor._resolve_ips",
        lambda host: frozenset({"10.200.10.26"}),
    )
    wp = WebhookProcessor(logger=StubLogger())
    result = wp._find_arr_instance({"client_host": "10.200.10.26"}, "series")
    assert result["found"] is False


# --- _validate_webhook ---


def test_validate_webhook_no_media_block(wp):
    result = wp._validate_webhook({"eventType": "Test"}, client_info={})
    assert result["success"] is False
    assert result["error_code"] == "INVALID_WEBHOOK_DATA"


def test_validate_webhook_no_instance(monkeypatch):
    # Two Sonarr instances, a peer IP matching neither -> ambiguous -> the
    # single-instance fallback does not apply, so validation fails closed.
    cfg = ChubConfig(
        instances=InstancesConfig(
            sonarr={
                "Shows": InstanceDetail(url="http://192.168.1.11:8989", api="a"),
                "Anime": InstanceDetail(url="http://192.168.1.12:8989", api="b"),
            }
        ),
    )
    monkeypatch.setattr("backend.util.webhook_processor.load_config", lambda: cfg)
    wp = WebhookProcessor(logger=StubLogger())

    payload = {"series": {"id": 1, "title": "Show"}}
    result = wp._validate_webhook(
        payload, client_info={"client_host": "10.0.0.50", "client_port": 1234}
    )
    assert result["success"] is False
    assert result["error_code"] == "NO_INSTANCE"


def test_validate_webhook_success(wp):
    payload = {
        "series": {"id": 1, "title": "Show"},
        "episodes": [{"seasonNumber": 2}],
    }
    client = {"client_host": "192.168.1.11", "client_port": 8989, "scheme": "http"}
    result = wp._validate_webhook(payload, client_info=client)
    assert result["success"] is True
    assert result["media_type"] == "series"
    assert result["media_id"] == 1
    assert result["season_number"] == 2
    assert result["instance_info"]["type"] == "sonarr"


# --- season-aware wait_for_plex_availability (consolidated season retry) ---


def _plex_with(season_index, episodes, show_title="The Show", show_year=2020):
    season = SimpleNamespace(index=season_index, episodes=lambda: episodes)
    show = SimpleNamespace(title=show_title, year=show_year, seasons=lambda: [season])
    section = SimpleNamespace(type="show", search=lambda **k: [show])
    return SimpleNamespace(library=SimpleNamespace(sections=lambda: [section]))


def test_season_present_true_when_scanned():
    plex = _plex_with(2, [object()])
    assert WebhookProcessor._season_present(plex, "The Show", 2020, 2) is True


def test_season_present_false_when_other_season_only():
    plex = _plex_with(1, [object()])  # season 1 present, asked for 2
    assert WebhookProcessor._season_present(plex, "The Show", 2020, 2) is False


def test_season_present_false_when_season_has_no_episodes():
    plex = _plex_with(2, [])  # folder seen but not scanned yet
    assert WebhookProcessor._season_present(plex, "The Show", 2020, 2) is False


def test_season_present_false_when_show_absent():
    section = SimpleNamespace(type="show", search=lambda **k: [])
    plex = SimpleNamespace(library=SimpleNamespace(sections=lambda: [section]))
    assert WebhookProcessor._season_present(plex, "Missing Show", None, 1) is False
