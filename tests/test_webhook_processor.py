"""Tests for backend/util/webhook_processor.py — webhook parsing & instance routing."""


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
    monkeypatch.setattr(
        "backend.util.webhook_processor.load_config", lambda: cfg
    )
    return WebhookProcessor(logger=StubLogger())


# --- _extract_media_block ---


def test_extract_media_block_series(wp):
    payload = {"series": {"id": 42, "title": "Show"}}
    block, type_, id_ = wp._extract_media_block(payload)
    assert type_ == "series"
    assert id_ == 42


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
    assert WebhookProcessor._extract_season_number(
        {"episodes": [{"seasonNumber": 3}]}
    ) == 3


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
        {"client_host": "192.168.1.10", "client_port": 7878, "scheme": "http"}
    )
    assert result["found"] is True
    assert result["type"] == "radarr"
    assert result["name"] == "main"


def test_find_arr_instance_matches_sonarr(wp):
    result = wp._find_arr_instance(
        {"client_host": "192.168.1.11", "client_port": 8989}
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
    monkeypatch.setattr(
        "backend.util.webhook_processor.load_config", lambda: cfg
    )
    wp = WebhookProcessor(logger=StubLogger())

    # 127.0.0.1 normalizes to localhost -> matches
    result = wp._find_arr_instance(
        {"client_host": "127.0.0.1", "client_port": 7878}
    )
    assert result["found"] is True


def test_find_arr_instance_no_client_info_returns_not_found(wp):
    result = wp._find_arr_instance(None)
    assert result["found"] is False


def test_find_arr_instance_port_mismatch(wp):
    result = wp._find_arr_instance(
        {"client_host": "192.168.1.10", "client_port": 9999}
    )
    assert result["found"] is False


# --- _validate_webhook ---


def test_validate_webhook_no_media_block(wp):
    result = wp._validate_webhook({"eventType": "Test"}, client_info={})
    assert result["success"] is False
    assert result["error_code"] == "INVALID_WEBHOOK_DATA"


def test_validate_webhook_no_instance(wp):
    payload = {"series": {"id": 1, "title": "Show"}}
    result = wp._validate_webhook(payload, client_info={"client_host": "10.0.0.50", "client_port": 1234})
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
