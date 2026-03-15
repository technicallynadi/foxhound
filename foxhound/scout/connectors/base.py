"""Base protocol and models for Scout connectors."""

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class RawOpportunity(BaseModel):
    """Raw opportunity discovered by a Scout connector."""

    source_type: str = Field(..., description="Connector source identifier")
    source_url: str = Field(..., description="Direct link to original resource")
    title: str = Field(..., description="Opportunity title")
    description: str | None = Field(default=None, description="Brief description or context")
    raw_metadata: dict = Field(default_factory=dict, description="Connector-specific raw data")
    discovered_at: datetime = Field(..., description="When this opportunity was discovered")
    trust_level: str = Field(default="external_untrusted", description="Trust tier")

    model_config = {"extra": "forbid"}


class ConnectorConfig(BaseModel):
    """Configuration for a Scout connector."""

    enabled: bool = Field(default=True)
    fetch_interval_hours: int = Field(default=6)

    model_config = {"extra": "forbid"}


@runtime_checkable
class BaseScoutConnector(Protocol):
    """Protocol that all Scout connectors must implement."""

    def configure(self, config: ConnectorConfig) -> None:
        """Apply configuration to the connector."""
        ...

    async def fetch(self) -> list[RawOpportunity]:
        """Fetch raw opportunities from the external source."""
        ...

    def connector_name(self) -> str:
        """Return the unique name for this connector."""
        ...
