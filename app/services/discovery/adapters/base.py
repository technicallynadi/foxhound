"""Base protocol for job source adapters."""

from __future__ import annotations

from typing import Protocol


class JobSourceAdapter(Protocol):
    source_name: str

    async def fetch_listings(self) -> list[dict]:
        """Fetch raw job listings from source. Returns list of raw dicts."""
        ...
