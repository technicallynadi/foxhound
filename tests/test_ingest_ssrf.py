"""SSRF guard tests for the ingest path's public-URL validator.

The ingest adapter drives a browser to URLs sourced from LLM/search output,
so ``is_public_http_url`` / ``assert_public_http_url`` must reject internal
targets (cloud metadata, loopback, RFC1918, link-local) and non-http(s)
schemes before any navigation happens.
"""

import pytest

from app.services.agent.utils.url_validator import assert_public_http_url, is_public_http_url

# URLs the guard MUST reject. IP literals and bad schemes are caught before
# any DNS resolution, so these cases need no network stubbing.
BLOCKED_URLS = [
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://10.0.0.5",
    "http://192.168.1.1",
    "ftp://example.com",
    "file:///etc/passwd",
]


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_is_public_http_url_rejects_unsafe(url):
    assert is_public_http_url(url) is False


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_assert_public_http_url_raises_on_unsafe(url):
    with pytest.raises(ValueError):
        assert_public_http_url(url)


def test_is_public_http_url_accepts_public_https(monkeypatch):
    # Patch the same resolver the guard uses so no real DNS/network happens.
    monkeypatch.setattr(
        "app.services.agent.utils.url_validator._resolve_host_ips",
        lambda host: {"93.184.216.34"},
    )
    assert is_public_http_url("https://example.com/some/path") is True


def test_assert_public_http_url_allows_public_https(monkeypatch):
    monkeypatch.setattr(
        "app.services.agent.utils.url_validator._resolve_host_ips",
        lambda host: {"93.184.216.34"},
    )
    # Should not raise.
    assert_public_http_url("https://example.com/some/path")


def test_is_public_http_url_blocks_dns_rebinding(monkeypatch):
    # A public-looking host that resolves to a private address is rejected.
    monkeypatch.setattr(
        "app.services.agent.utils.url_validator._resolve_host_ips",
        lambda host: {"10.1.2.3"},
    )
    assert is_public_http_url("https://example.com/some/path") is False
