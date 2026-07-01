"""ATS URL allowlist for TinyFish navigation safety."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# Known ATS domains that TinyFish is allowed to navigate to
ATS_DOMAIN_ALLOWLIST: set[str] = {
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "apply.workable.com",
}

# Wildcard suffixes (e.g., *.myworkdayjobs.com)
ATS_WILDCARD_SUFFIXES: list[str] = [
    ".myworkdayjobs.com",
    ".lever.co",
    ".greenhouse.io",
]


def validate_apply_url(url: str) -> bool:
    """Validate that a URL points to a known ATS domain.

    Returns True if the URL is safe for TinyFish to navigate to.
    Blocks: private IPs, non-HTTPS, non-allowlisted domains.

    TOCTOU limitation: this validator resolves DNS at check time, but the
    TinyFish browser re-resolves the host at navigation time and follows
    redirects the validator never sees. A host that resolved to a public
    address here can point at an internal one by the time the browser
    connects, and a public page can 3xx-redirect into the private network.
    The DNS-rebind guard below only narrows the window — it does not close
    it. Network-level egress-proxy IP filtering (deny RFC1918/link-local at
    the proxy) is the real backstop and should be configured in infra;
    this function is defence-in-depth, not the sole control.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    # Must be HTTPS (no http:// downgrade — that path is rejected here).
    if parsed.scheme != "https":
        return False

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        return False

    # Check exact matches
    if host in ATS_DOMAIN_ALLOWLIST:
        allowed = True
    else:
        # Check wildcard suffixes
        allowed = False
        for suffix in ATS_WILDCARD_SUFFIXES:
            if host.endswith(suffix):
                allowed = True
                break

    if not allowed:
        return False

    # Block private/reserved literal hosts (IPv4 + IPv6).
    if _is_private_or_reserved_ip(host):
        return False

    # Best-effort DNS rebinding guard:
    # if DNS resolves and any address is non-public, reject.
    # If DNS cannot be resolved in this environment, keep allowlist decision.
    for ip_text in _resolve_host_ips(host):
        if _is_private_or_reserved_ip(ip_text):
            return False

    return True


def is_public_http_url(url: str) -> bool:
    """Validate that a URL is a public http(s) URL safe to navigate to.

    Unlike ``validate_apply_url`` this does NOT require the ATS allowlist —
    any public host is allowed. It is the less-restrictive guard used by the
    ingest path, where TinyFish drives a browser to arbitrary URLs sourced
    from LLM/search output.

    Returns True only when the URL is safe. Rejects:
    - non-http(s) schemes (e.g. ftp://, file://)
    - hosts that are IP literals in private/loopback/link-local/reserved ranges
    - hosts whose resolved A/AAAA records are private/reserved (rebind guard)

    Shares the private-IP and DNS-resolution helpers with ``validate_apply_url``.
    The same TOCTOU caveat applies: egress-proxy IP filtering is the real
    backstop; this is defence-in-depth.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        return False

    # Block private/reserved literal hosts (IPv4 + IPv6).
    if _is_private_or_reserved_ip(host):
        return False

    # Best-effort DNS rebinding guard: if DNS resolves and any address is
    # non-public, reject. If DNS cannot be resolved, allow the public host.
    for ip_text in _resolve_host_ips(host):
        if _is_private_or_reserved_ip(ip_text):
            return False

    return True


def assert_public_http_url(url: str) -> None:
    """Raise ``ValueError`` if ``url`` is not a public http(s) URL.

    Convenience wrapper around ``is_public_http_url`` for call sites that
    want to fail fast before any network/browser call.
    """
    if not is_public_http_url(url):
        raise ValueError(f"Refusing to navigate to non-public or unsafe URL: {url!r}")


def _resolve_host_ips(host: str) -> set[str]:
    """Resolve hostname to IPv4/IPv6 strings (best effort)."""
    try:
        records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        return set()
    ips: set[str] = set()
    for rec in records:
        sockaddr = rec[4]
        if not sockaddr:
            continue
        ips.add(str(sockaddr[0]))
    return ips


def _is_private_or_reserved_ip(value: str) -> bool:
    """True if a literal IP address is not globally routable."""
    if value == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    return False
