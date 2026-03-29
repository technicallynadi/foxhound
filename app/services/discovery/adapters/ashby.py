"""Ashby job board adapter.

Ashby exposes a public JSON API at:
  https://api.ashbyhq.com/posting-api/job-board/{company_slug}

No auth required. Returns structured job data with optional compensation.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.services.discovery.ats_detector import detect_ats, is_auto_apply_supported
from app.services.discovery.deduplicator import compute_dedup_hash

logger = logging.getLogger(__name__)

DEFAULT_COMPANIES: list[tuple[str, str]] = [
    # Tier 1 — top AI companies
    ("openai", "OpenAI"), ("anthropic", "Anthropic"), ("perplexity", "Perplexity"),
    ("cohere", "Cohere"), ("cognition", "Cognition"), ("cursor", "Cursor"),
    ("runway", "Runway"), ("harvey", "Harvey"), ("scaleai", "Scale AI"),
    # Tier 2 — high-growth tech
    ("notion", "Notion"), ("ramp", "Ramp"), ("reddit", "Reddit"),
    ("deel", "Deel"), ("rippling", "Rippling"), ("snowflake", "Snowflake"),
    ("linear", "Linear"), ("vercel", "Vercel"), ("retool", "Retool"),
    ("webflow", "Webflow"),
    # Tier 3 — promising startups
    ("zip", "Zip"), ("handshake", "Handshake"), ("evenup", "EvenUp"),
    ("modern-treasury", "Modern Treasury"), ("stainlessapi", "Stainless"),
    ("mintlify", "Mintlify"), ("pylon-labs", "Pylon"), ("kikoff", "Kikoff"),
    ("loom", "Loom"), ("ashby", "Ashby"), ("opendoor", "Opendoor"),
]

API_BASE = "https://api.ashbyhq.com/posting-api/job-board"


class AshbyAdapter:
    source_name = "ashby"

    def __init__(self, companies: list[tuple[str, str]] | None = None) -> None:
        self.companies = companies or DEFAULT_COMPANIES

    async def fetch_listings(self) -> list[dict]:
        """Fetch jobs from all configured Ashby companies."""
        all_listings: list[dict] = []

        async with httpx.AsyncClient(timeout=15.0) as client:
            tasks = [self._fetch_company(client, slug, name) for slug, name in self.companies]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for (slug, name), result in zip(self.companies, results):
            if isinstance(result, Exception):
                logger.warning("Ashby company %s failed: %s", slug, result)
                continue
            all_listings.extend(result)

        logger.info("Ashby: fetched %d listings from %d companies", len(all_listings), len(self.companies))
        return all_listings

    async def _fetch_company(self, client: httpx.AsyncClient, slug: str, display_name: str) -> list[dict]:
        """Fetch all jobs from a single Ashby company board."""
        url = f"{API_BASE}/{slug}"
        resp = await client.get(url, params={"includeCompensation": "true"})

        if resp.status_code == 404:
            logger.debug("Ashby company not found: %s", slug)
            return []
        resp.raise_for_status()

        data = resp.json()
        jobs = data.get("jobs", [])

        listings = []
        for job in jobs:
            apply_url = job.get("jobUrl", "")
            ats_type = detect_ats(apply_url) or "ashby"

            location = job.get("location", "")
            if isinstance(location, dict):
                location = location.get("name", "")

            # Parse compensation if available
            salary_min = None
            salary_max = None
            salary_currency = None
            comp = job.get("compensation")
            if comp:
                salary_min = comp.get("min")
                salary_max = comp.get("max")
                salary_currency = comp.get("currency", "USD")

            department = job.get("department", "")
            team = job.get("team", "")

            listings.append({
                "external_id": job.get("id", ""),
                "title": job.get("title", ""),
                "company": display_name,
                "company_url": f"https://jobs.ashbyhq.com/{slug}",
                "description": job.get("descriptionPlain", "") or job.get("description", ""),
                "description_html": job.get("description", ""),
                "location": location,
                "remote_type": _infer_remote(location, job),
                "salary_min": salary_min,
                "salary_max": salary_max,
                "salary_currency": salary_currency,
                "apply_url": apply_url,
                "ats_type": ats_type,
                "auto_apply_supported": is_auto_apply_supported(ats_type),
                "source": "ashby",
                "source_url": apply_url,
                "posted_at": job.get("publishedAt"),
                "dedup_hash": compute_dedup_hash(slug, job.get("title", ""), location),
            })

        return listings


def _infer_remote(location: str, job: dict) -> str | None:
    loc = (location or "").lower()
    if "remote" in loc:
        return "remote"
    if "hybrid" in loc:
        return "hybrid"
    # Some Ashby jobs have an isRemote field
    if job.get("isRemote"):
        return "remote"
    return None
