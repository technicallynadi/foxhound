"""Greenhouse job board adapter.

Greenhouse exposes a public JSON API at:
  https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs

No auth required. Returns structured job data.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.services.discovery.ats_detector import detect_ats, is_auto_apply_supported
from app.services.discovery.deduplicator import compute_dedup_hash

logger = logging.getLogger(__name__)

# (slug, display_name) — slug is the API identifier, display_name is what users see
DEFAULT_BOARDS: list[tuple[str, str]] = [
    # Tier 1 — high volume, always hiring
    ("airbnb", "Airbnb"), ("lyft", "Lyft"), ("databricks", "Databricks"),
    ("datadog", "Datadog"), ("cloudflare", "Cloudflare"), ("twilio", "Twilio"),
    ("figma", "Figma"), ("mongodb", "MongoDB"), ("doordash", "DoorDash"),
    ("duolingo", "Duolingo"), ("robinhood", "Robinhood"), ("instacart", "Instacart"),
    ("plaid", "Plaid"), ("hubspot", "HubSpot"), ("pinterest", "Pinterest"),
    ("crowdstrike", "CrowdStrike"), ("okta", "Okta"), ("brex", "Brex"),
    ("asana", "Asana"), ("squarespace", "Squarespace"),
    # Tier 2 — strong eng brands
    ("cockroachlabs", "Cockroach Labs"), ("grafanalabs", "Grafana Labs"),
    ("hashicorp", "HashiCorp"), ("snyk", "Snyk"), ("gusto", "Gusto"),
    ("airtable", "Airtable"), ("benchling", "Benchling"), ("apolloio", "Apollo.io"),
    ("sentinellabs", "SentinelOne"), ("abnormalsecurity", "Abnormal Security"),
    ("synthesia", "Synthesia"), ("brave", "Brave"),
    # Tier 3 — niche / smaller
    ("remotecom", "Remote.com"), ("flexport", "Flexport"), ("fireblocks", "Fireblocks"),
    ("eucalyptus", "Eucalyptus"), ("stokespacetechnologies", "Stoke Space"),
    ("spacex", "SpaceX"), ("redventures", "Red Ventures"),
    ("appliedintuition", "Applied Intuition"),
]

API_BASE = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseAdapter:
    source_name = "greenhouse"

    def __init__(self, boards: list[tuple[str, str]] | None = None) -> None:
        self.boards = boards or DEFAULT_BOARDS

    async def fetch_listings(self) -> list[dict]:
        """Fetch jobs from all configured Greenhouse boards."""
        all_listings: list[dict] = []

        async with httpx.AsyncClient(timeout=15.0) as client:
            tasks = [self._fetch_board(client, slug, name) for slug, name in self.boards]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for (slug, name), result in zip(self.boards, results):
            if isinstance(result, Exception):
                logger.warning("Greenhouse board %s failed: %s", slug, result)
                continue
            all_listings.extend(result)

        logger.info("Greenhouse: fetched %d listings from %d boards", len(all_listings), len(self.boards))
        return all_listings

    async def _fetch_board(self, client: httpx.AsyncClient, slug: str, display_name: str) -> list[dict]:
        """Fetch all jobs from a single Greenhouse board."""
        url = f"{API_BASE}/{slug}/jobs"
        resp = await client.get(url, params={"content": "true"})

        if resp.status_code == 404:
            logger.debug("Greenhouse board not found: %s", slug)
            return []
        resp.raise_for_status()

        data = resp.json()
        jobs = data.get("jobs", [])

        listings = []
        for job in jobs:
            apply_url = job.get("absolute_url", "")
            ats_type = detect_ats(apply_url) or "greenhouse"

            location_name = ""
            if job.get("location", {}).get("name"):
                location_name = job["location"]["name"]

            listings.append({
                "external_id": str(job.get("id", "")),
                "title": job.get("title", ""),
                "company": display_name,
                "company_url": f"https://boards.greenhouse.io/{slug}",
                "description": job.get("content", ""),
                "description_html": job.get("content", ""),
                "location": location_name,
                "remote_type": _infer_remote(location_name),
                "apply_url": apply_url,
                "ats_type": ats_type,
                "auto_apply_supported": is_auto_apply_supported(ats_type),
                "source": "greenhouse",
                "source_url": apply_url,
                "posted_at": job.get("updated_at"),
                "dedup_hash": compute_dedup_hash(slug, job.get("title", ""), location_name),
            })

        return listings


def _infer_remote(location: str) -> str | None:
    loc = (location or "").lower()
    if "remote" in loc:
        return "remote"
    if "hybrid" in loc:
        return "hybrid"
    return None
