"""Scout connectors for external opportunity discovery."""

from foxhound.scout.connectors.base import (
    BaseScoutConnector,
    ConnectorConfig,
    RawOpportunity,
)
from foxhound.scout.connectors.hackernews import (
    HackerNewsConnector,
    HNConnectorConfig,
)

__all__ = [
    "BaseScoutConnector",
    "ConnectorConfig",
    "HackerNewsConnector",
    "HNConnectorConfig",
    "RawOpportunity",
]
