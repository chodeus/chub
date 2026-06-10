"""Tests for SmartRedactionFilter — especially secrets embedded in URL query
parameters, which requests exceptions surface verbatim."""

from backend.util.logger import SmartRedactionFilter


def _r(text: str) -> str:
    return SmartRedactionFilter.redact(text)


def test_plex_token_in_url_query_redacted():
    msg = (
        "Failed to download database: 401 Client Error for url: "
        "http://plex:32400/diagnostics/databases?X-Plex-Token=abc123SECRETtoken"
    )
    out = _r(msg)
    assert "abc123SECRETtoken" not in out
    assert "X-Plex-Token=[redacted]" in out


def test_fanart_client_key_in_url_query_redacted():
    msg = (
        "fanart.tv request failed for logo: HTTPSConnectionPool host="
        "'webservice.fanart.tv' url: /v3/movies/123?client_key=0123456789abcdef0123456789abcdef"
    )
    out = _r(msg)
    assert "0123456789abcdef0123456789abcdef" not in out
    assert "client_key=[redacted]" in out


def test_generic_token_query_param_redacted():
    out = _r("GET /api/modules/events?token=eyNotAJwtButStillAToken123 failed")
    assert "eyNotAJwtButStillAToken123" not in out


def test_query_param_redaction_stops_at_next_param():
    out = _r("http://h/x?client_key=sekret&page=2")
    assert "sekret" not in out
    assert "page=2" in out


def test_plain_urls_without_secrets_untouched():
    msg = "Fetched http://radarr:7878/api/v3/movie?page=2&sort=title fine"
    assert _r(msg) == msg
