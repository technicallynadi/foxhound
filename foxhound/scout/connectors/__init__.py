"""Scout connectors for external opportunity discovery."""

import logging
from typing import Any

from foxhound.scout.connectors.base import (
    BaseScoutConnector,
    ConnectorConfig,
    RawOpportunity,
)
from foxhound.scout.connectors.devto import DevToConnector, DevToConnectorConfig
from foxhound.scout.connectors.github_events import (
    GitHubEventsConnector,
    GitHubEventsConnectorConfig,
)
from foxhound.scout.connectors.hackernews import (
    HackerNewsConnector,
    HNConnectorConfig,
)
from foxhound.scout.connectors.lobsters import LobstersConnector, LobstersConnectorConfig
from foxhound.scout.connectors.newsapi import NewsAPIConnector, NewsAPIConnectorConfig
from foxhound.scout.connectors.producthunt import (
    ProductHuntConnector,
    ProductHuntConnectorConfig,
)
from foxhound.scout.connectors.reddit import (
    RedditConnector,
    RedditPost,
)
from foxhound.scout.connectors.rss import RSSConnector, RSSConnectorConfig

logger = logging.getLogger(__name__)

CONNECTOR_REGISTRY: dict[str, type] = {
    "hackernews": HackerNewsConnector,
    "devto": DevToConnector,
    "lobsters": LobstersConnector,
    "github_events": GitHubEventsConnector,
    "newsapi": NewsAPIConnector,
    "producthunt": ProductHuntConnector,
    "rss": RSSConnector,
    "reddit": RedditConnector,
}

CONFIG_REGISTRY: dict[str, type] = {
    "hackernews": HNConnectorConfig,
    "devto": DevToConnectorConfig,
    "lobsters": LobstersConnectorConfig,
    "github_events": GitHubEventsConnectorConfig,
    "newsapi": NewsAPIConnectorConfig,
    "producthunt": ProductHuntConnectorConfig,
    "rss": RSSConnectorConfig,
}


def load_enabled_connectors(config: dict[str, Any]) -> list[Any]:
    """Load and configure all enabled Scout connectors from foxhound.yaml."""
    connectors: list[Any] = []
    sources_config = config.get("scout", {}).get("sources", {})
    for name, source_config in sources_config.items():
        if not source_config.get("enabled", False):
            continue
        connector_class = CONNECTOR_REGISTRY.get(name)
        if connector_class is None:
            logger.warning("Unknown Scout source: %s", name)
            continue
        try:
            connector = connector_class()
        except TypeError:
            logger.warning(
                "Connector %s requires manual setup — skipping", name,
            )
            continue

        # Parse config through typed Pydantic model if available
        config_class = CONFIG_REGISTRY.get(name)
        if config_class:
            try:
                typed_config = config_class(**source_config)
                connector.configure(typed_config)
            except Exception:
                logger.warning("Invalid config for %s — skipping", name)
                continue
        else:
            connector.configure(source_config)
        connectors.append(connector)
    return connectors


__all__ = [
    "BaseScoutConnector",
    "CONNECTOR_REGISTRY",
    "ConnectorConfig",
    "DevToConnector",
    "DevToConnectorConfig",
    "GitHubEventsConnector",
    "GitHubEventsConnectorConfig",
    "HNConnectorConfig",
    "HackerNewsConnector",
    "LobstersConnector",
    "LobstersConnectorConfig",
    "NewsAPIConnector",
    "NewsAPIConnectorConfig",
    "ProductHuntConnector",
    "ProductHuntConnectorConfig",
    "RSSConnector",
    "RSSConnectorConfig",
    "RawOpportunity",
    "RedditConnector",
    "RedditPost",
    "load_enabled_connectors",
]
