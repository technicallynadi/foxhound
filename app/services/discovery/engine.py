"""Job discovery engine — orchestrates crawling across all job sources."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.discovery_run import DiscoveryRun
from app.db.models.job_listing import JobListing
from app.services.discovery.adapters.ashby import AshbyAdapter
from app.services.discovery.adapters.greenhouse import GreenhouseAdapter
from app.services.discovery.adapters.hn_hiring import HNHiringAdapter
from app.services.discovery.adapters.lever import LeverAdapter

logger = logging.getLogger(__name__)


class JobDiscoveryEngine:
    """Orchestrates job crawling across sources."""

    def __init__(self) -> None:
        self.adapters = {
            "greenhouse": GreenhouseAdapter(),
            "lever": LeverAdapter(),
            "ashby": AshbyAdapter(),
            "hn_hiring": HNHiringAdapter(),
        }

    async def run_discovery(
        self, db: AsyncSession, source: str | None = None, job_id: str | None = None
    ) -> list[DiscoveryRun]:
        """Run crawl for one or all sources. Returns DiscoveryRun records."""
        sources = [source] if source else list(self.adapters.keys())
        runs: list[DiscoveryRun] = []

        for src in sources:
            adapter = self.adapters.get(src)
            if not adapter:
                logger.warning("Unknown source: %s", src)
                continue

            run = DiscoveryRun(
                id=str(uuid4()),
                job_id=job_id,
                source=src,
                status="running",
            )
            db.add(run)
            await db.flush()

            t0 = time.monotonic()
            try:
                raw_listings = await adapter.fetch_listings()
                normalized = raw_listings  # Already normalized by adapters

                stored = await self._store_listings(db, normalized)
                run.listings_found = len(raw_listings)
                run.listings_new = stored["new"]
                run.listings_updated = stored["updated"]
                run.listings_deduplicated = stored["deduplicated"]
                run.status = "completed"
            except Exception as e:
                logger.error("Discovery failed for %s: %s", src, e)
                run.status = "failed"
                run.error_message = str(e)

            run.duration_ms = int((time.monotonic() - t0) * 1000)
            run.completed_at = datetime.now(UTC)
            runs.append(run)

        await db.commit()
        return runs

    async def _store_listings(
        self, db: AsyncSession, listings: list[dict]
    ) -> dict:
        """Batch upsert listings into job_listings table. Returns counts."""
        if not listings:
            return {"new": 0, "updated": 0, "deduplicated": 0}

        # Step 1: Collect all dedup hashes and external IDs for batch lookup
        dedup_hashes = [l.get("dedup_hash") for l in listings if l.get("dedup_hash")]
        ext_ids = [(l.get("external_id"), l.get("source")) for l in listings if l.get("external_id")]

        # Batch query existing by dedup hash
        existing_by_hash: set[str] = set()
        if dedup_hashes:
            # Query in chunks of 500 to avoid parameter limits
            for i in range(0, len(dedup_hashes), 500):
                chunk = dedup_hashes[i:i+500]
                result = await db.execute(
                    select(JobListing.dedup_hash).where(JobListing.dedup_hash.in_(chunk))
                )
                existing_by_hash.update(row[0] for row in result.all())

        # Batch query existing by external_id + source
        existing_by_ext: set[tuple[str, str]] = set()
        if ext_ids:
            ext_id_list = [eid for eid, _ in ext_ids if eid]
            if ext_id_list:
                for i in range(0, len(ext_id_list), 500):
                    chunk = ext_id_list[i:i+500]
                    result = await db.execute(
                        select(JobListing.external_id, JobListing.source)
                        .where(JobListing.external_id.in_(chunk))
                    )
                    existing_by_ext.update((row[0], row[1]) for row in result.all())

        # Step 2: Filter to new listings only
        new_listings = []
        dedup_count = 0

        for listing_data in listings:
            dedup_hash = listing_data.get("dedup_hash")
            external_id = listing_data.get("external_id")
            source = listing_data.get("source")

            if dedup_hash and dedup_hash in existing_by_hash:
                dedup_count += 1
                continue
            if external_id and (external_id, source) in existing_by_ext:
                dedup_count += 1
                continue

            new_listings.append(listing_data)

        # Step 3: Batch insert new listings in chunks
        new_count = 0
        BATCH_SIZE = 200

        for i in range(0, len(new_listings), BATCH_SIZE):
            batch = new_listings[i:i+BATCH_SIZE]
            objects = []
            for listing_data in batch:
                posted_at = listing_data.get("posted_at")
                if isinstance(posted_at, str):
                    try:
                        posted_at = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        posted_at = None

                objects.append(JobListing(
                    id=str(uuid4()),
                    external_id=listing_data.get("external_id"),
                    title=listing_data.get("title", ""),
                    company=listing_data.get("company", ""),
                    company_url=listing_data.get("company_url"),
                    description=listing_data.get("description", ""),
                    description_html=listing_data.get("description_html"),
                    location=listing_data.get("location"),
                    remote_type=listing_data.get("remote_type"),
                    apply_url=listing_data.get("apply_url", ""),
                    ats_type=listing_data.get("ats_type"),
                    auto_apply_supported=listing_data.get("auto_apply_supported", False),
                    source=listing_data.get("source", ""),
                    source_url=listing_data.get("source_url", ""),
                    posted_at=posted_at,
                    status="active",
                    dedup_hash=listing_data.get("dedup_hash"),
                ))

            db.add_all(objects)
            await db.flush()
            new_count += len(objects)
            logger.info("Batch inserted %d jobs (%d/%d)", len(objects), new_count, len(new_listings))

        return {"new": new_count, "updated": 0, "deduplicated": dedup_count}
