"""Remotive remote jobs adapter.

Free public API at: https://remotive.com/api/remote-jobs
Rate limit: 2 req/min, recommended max 4x/day.
"""

from __future__ import annotations

import logging

import httpx

from app.services.discovery.ats_detector import detect_ats, is_auto_apply_supported
from app.services.discovery.deduplicator import compute_dedup_hash

logger = logging.getLogger(__name__)

API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveAdapter:
    source_name = "remotive"

    async def fetch_listings(self) -> list[dict]:
        """Fetch remote software dev jobs from Remotive."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(API_URL, params={
                "category": "software-dev",
                "limit": 100,
            })
            resp.raise_for_status()

        data = resp.json()
        jobs = data.get("jobs", [])

        listings = []
        for job in jobs:
            apply_url = job.get("url", "")
            ats_type = detect_ats(apply_url)
            company = job.get("company_name", "")
            title = job.get("title", "")
            location = job.get("candidate_required_location", "Worldwide")

            # Strip HTML from description
            import re
            description = re.sub(r"<[^>]+>", " ", job.get("description", "")).strip()

            listings.append({
                "external_id": str(job.get("id", "")),
                "title": title,
                "company": company,
                "company_url": job.get("company_logo_url"),
                "description": description[:5000],
                "description_html": job.get("description", ""),
                "location": location,
                "remote_type": "remote",
                "salary_min": None,
                "salary_max": None,
                "salary_currency": None,
                "apply_url": apply_url,
                "ats_type": ats_type,
                "auto_apply_supported": is_auto_apply_supported(ats_type),
                "source": "remotive",
                "source_url": apply_url,
                "posted_at": job.get("publication_date"),
                "dedup_hash": compute_dedup_hash(company, title, location),
            })

        logger.info("Remotive: fetched %d remote job listings", len(listings))
        return listings
