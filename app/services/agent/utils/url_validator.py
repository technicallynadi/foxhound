"""ATS URL allowlist for TinyFish navigation safety."""

from __future__ import annotations

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
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    # Must be HTTPS
    if parsed.scheme != "https":
        return False

    host = (parsed.hostname or "").lower()
    if not host:
        return False

    # Block private/reserved ranges
    if _is_private_host(host):
        return False

    # Check exact matches
    if host in ATS_DOMAIN_ALLOWLIST:
        return True

    # Check wildcard suffixes
    for suffix in ATS_WILDCARD_SUFFIXES:
        if host.endswith(suffix):
            return True

    return False


def _is_private_host(host: str) -> bool:
    """Check if a hostname resolves to a private/reserved IP range."""
    # Block common private hostnames
    private_patterns = [
        "localhost", "127.0.0.1", "0.0.0.0",
        "169.254.", "10.", "172.16.", "172.17.", "172.18.",
        "172.19.", "172.20.", "172.21.", "172.22.", "172.23.",
        "172.24.", "172.25.", "172.26.", "172.27.", "172.28.",
        "172.29.", "172.30.", "172.31.", "192.168.",
        "::1", "fc00:", "fe80:",
    ]
    for pattern in private_patterns:
        if host.startswith(pattern) or host == pattern:
            return True
    return False
