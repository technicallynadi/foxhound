"""Domain-level failure tracking for TinyFish extraction.

Tracks which domains have blocked access (CAPTCHA, login wall, 403) within
a pipeline run. Once a domain is blocked, all subsequent URLs from that
domain are skipped immediately instead of burning TinyFish budget.

Extraction timeouts are tracked separately — a timeout means the page was
too heavy, not that the domain is hostile. Timeouts don't block the domain.
"""

import logging
from collections import defaultdict
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class DomainTracker:
    def __init__(self):
        self._blocked: set[str] = set()
        self._failures: dict[str, list[str]] = defaultdict(list)

    @staticmethod
    def _domain(url: str) -> str:
        return urlparse(url).netloc.lower().replace("www.", "")

    def record_failure(self, url: str, error_type: str) -> None:
        """Record a failure. Hard blocks (CAPTCHA, login, 403) block the domain immediately."""
        domain = self._domain(url)
        self._failures[domain].append(error_type)

        hard_block_types = {"blocked", "captcha", "login_wall", "forbidden"}
        if error_type in hard_block_types:
            self._blocked.add(domain)
            logger.info("Domain blocked: %s (reason: %s on %s)", domain, error_type, url[:60])

    def record_blocked_page(self, url: str) -> None:
        """Called when TinyFish returns {blocked: true} for a page."""
        self.record_failure(url, "blocked")

    def is_blocked(self, url: str) -> bool:
        return self._domain(url) in self._blocked

    def blocked_domains(self) -> set[str]:
        return set(self._blocked)

    def record_success(self, url: str) -> None:
        domain = self._domain(url)
        self._failures.pop(domain, None)
        self._blocked.discard(domain)


# Module-level singleton, reset per pipeline run
_tracker: DomainTracker | None = None


def get_domain_tracker() -> DomainTracker:
    global _tracker
    if _tracker is None:
        _tracker = DomainTracker()
    return _tracker


def reset_domain_tracker() -> None:
    global _tracker
    _tracker = DomainTracker()
