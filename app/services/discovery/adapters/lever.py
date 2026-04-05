"""Lever job board adapter.

Lever exposes a public JSON endpoint at:
  https://api.lever.co/v0/postings/{company}

No auth required. Returns structured job data.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.services.discovery.ats_detector import detect_ats, is_auto_apply_supported
from app.services.discovery.deduplicator import compute_dedup_hash

logger = logging.getLogger(__name__)

DEFAULT_COMPANIES: list[tuple[str, str]] = [
    # Tier 1 — high volume
    ("netflix", "Netflix"), ("spotify", "Spotify"), ("shopify", "Shopify"),
    ("atlassian", "Atlassian"), ("palantir", "Palantir"), ("coinbase", "Coinbase"),
    ("anduril", "Anduril"), ("nerdwallet", "NerdWallet"), ("upwork", "Upwork"),
    ("wealthsimple", "Wealthsimple"), ("carta", "Carta"), ("gusto", "Gusto"),
    ("samsara", "Samsara"), ("postman", "Postman"), ("elastic", "Elastic"),
    # Tier 2 — strong eng brands
    ("sentry", "Sentry"), ("launchdarkly", "LaunchDarkly"), ("mux", "Mux"),
    ("metabase", "Metabase"), ("contentful", "Contentful"), ("sourcegraph", "Sourcegraph"),
    ("gitpod", "Gitpod"), ("semgrep", "Semgrep"), ("temporal", "Temporal"),
    ("superblocks", "Superblocks"), ("risecalendar", "Rise Calendar"),
    # Tier 3 — smaller / niche
    ("twitch", "Twitch"), ("coursera", "Coursera"), ("grammarly", "Grammarly"),
    ("webflow", "Webflow"),
]

API_BASE = "https://api.lever.co/v0/postings"


class LeverAdapter:
    source_name = "lever"

    def __init__(self, companies: list[tuple[str, str]] | None = None) -> None:
        self.companies = companies or DEFAULT_COMPANIES

    async def fetch_listings(self) -> list[dict]:
        """Fetch jobs from all configured Lever companies."""
        all_listings: list[dict] = []

        async with httpx.AsyncClient(timeout=15.0) as client:
            tasks = [self._fetch_company(client, slug, name) for slug, name in self.companies]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for (slug, name), result in zip(self.companies, results):
            if isinstance(result, Exception):
                logger.warning("Lever company %s failed: %s", slug, result)
                continue
            all_listings.extend(result)

        logger.info("Lever: fetched %d listings from %d companies", len(all_listings), len(self.companies))
        return all_listings

    async def _fetch_company(self, client: httpx.AsyncClient, slug: str, display_name: str) -> list[dict]:
        """Fetch all postings from a single Lever company."""
        url = f"{API_BASE}/{slug}"
        resp = await client.get(url)

        if resp.status_code == 404:
            logger.debug("Lever company not found: %s", slug)
            return []
        resp.raise_for_status()

        postings = resp.json()
        if not isinstance(postings, list):
            return []

        listings = []
        for posting in postings:
            apply_url = posting.get("applyUrl") or posting.get("hostedUrl", "")
            ats_type = detect_ats(apply_url) or "lever"

            location = posting.get("categories", {}).get("location", "")
            posting.get("categories", {}).get("team", "")

            description_parts = []
            if posting.get("descriptionPlain"):
                description_parts.append(posting["descriptionPlain"])
            for lst in posting.get("lists", []):
                description_parts.append(lst.get("text", ""))
                description_parts.append(lst.get("content", ""))

            listings.append({
                "external_id": posting.get("id", ""),
                "title": posting.get("text", ""),
                "company": display_name,
                "company_url": f"https://jobs.lever.co/{slug}",
                "description": "\n".join(filter(None, description_parts)),
                "description_html": posting.get("description", ""),
                "location": location,
                "remote_type": _infer_remote(location),
                "apply_url": apply_url,
                "ats_type": ats_type,
                "auto_apply_supported": is_auto_apply_supported(ats_type),
                "source": "lever",
                "source_url": posting.get("hostedUrl", ""),
                "posted_at": None,  # Lever doesn't expose post date in public API
                "dedup_hash": compute_dedup_hash(slug, posting.get("text", ""), location),
            })

        return listings


def _infer_remote(location: str) -> str | None:
    loc = (location or "").lower()
    if "remote" in loc:
        return "remote"
    if "hybrid" in loc:
        return "hybrid"
    return None
