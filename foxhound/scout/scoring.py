"""Opportunity scoring and summarization pipeline.

Reads unscored raw opportunities from SQLite, scores them
(programmatically or via fast tier model), filters by user preferences,
and creates scored opportunity items.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from foxhound.core.models import (
    OpportunityState,
)
from foxhound.scout.engine import (
    ALLOWED_LICENSES,
    ScoutSource,
    score_opportunity,
    source_to_opportunity,
)
from foxhound.scout.opportunity import OpportunityManager
from foxhound.storage.database import Database, RawOpportunityStore

logger = logging.getLogger(__name__)

BATCH_SIZE = 10


@dataclass
class ScoringPreferences:
    """User preferences for filtering scored opportunities."""

    min_score: float = 0.3
    languages: list[str] = field(default_factory=list)
    exclude_licenses: list[str] = field(default_factory=list)
    exclude_repos: list[str] = field(default_factory=list)


@dataclass
class ScoringResult:
    """Result from a scoring pipeline run."""

    processed: int = 0
    passed: int = 0
    filtered: int = 0
    opportunity_ids: list[str] = field(default_factory=list)
    total_cost: float = 0.0


def _raw_to_scout_source(raw: dict[str, Any]) -> ScoutSource:
    """Convert a raw opportunity record to a ScoutSource."""
    raw_data = raw["raw_payload"]
    payload = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    source_type = raw["source"]

    if source_type == "github_trending":
        return ScoutSource(
            title=payload.get("name", raw["title"]),
            description=payload.get("description", ""),
            source_type="github_trending",
            source_url=payload.get("html_url", raw.get("source_url", "")),
            stars=payload.get("stars", 0),
            star_velocity=payload.get("star_velocity", 0.0),
            language=payload.get("language", ""),
            license_type=payload.get("license_type", ""),
            tags=payload.get("topics", []),
            evidence=payload,
        )
    elif source_type == "reddit":
        github_repos = payload.get("github_repos", [])
        return ScoutSource(
            title=payload.get("title", raw["title"]),
            description=payload.get("selftext", "")[:200],
            source_type="reddit",
            source_url=github_repos[0] if github_repos else raw.get("source_url", ""),
            stars=payload.get("upvotes", 0),
            star_velocity=payload.get("upvote_velocity", 0.0),
            language="",
            license_type="",
            tags=[payload.get("subreddit", "")],
            evidence=payload,
        )
    else:
        return ScoutSource(
            title=raw["title"],
            description="",
            source_type=source_type,
            source_url=raw.get("source_url", ""),
            evidence=payload,
        )


class ScoringPipeline:
    """Scores unscored raw opportunities and creates opportunity items.

    Reads from scout_raw_opportunities, scores each item, applies
    user preference filters, and persists passing items as opportunity
    discovery items in SUGGESTED state.
    """

    def __init__(
        self,
        db: Database,
        preferences: ScoringPreferences | None = None,
    ) -> None:
        self._db = db
        self._raw_store = RawOpportunityStore(db)
        self._opp_mgr = OpportunityManager(db)
        self._prefs = preferences or ScoringPreferences()

    def score_all(self) -> ScoringResult:
        """Process all unscored raw opportunities."""
        result = ScoringResult()
        unscored = self._raw_store.list_unscored(limit=200)

        if not unscored:
            return result

        for raw in unscored:
            result.processed += 1

            try:
                source = _raw_to_scout_source(raw)
            except Exception as exc:
                logger.warning("Failed to parse raw opportunity %s: %s", raw["raw_id"], exc)
                self._raw_store.mark_scored(raw["raw_id"])
                continue

            scores = score_opportunity(source)

            if not self._passes_filters(source, scores):
                result.filtered += 1
                self._raw_store.mark_scored(raw["raw_id"])
                continue

            item = source_to_opportunity(source)
            existing = self._opp_mgr.find_by_fingerprint(item.source_fingerprint)
            if existing is not None:
                self._raw_store.mark_scored(raw["raw_id"])
                result.filtered += 1
                continue

            self._opp_mgr._store.save(item)
            self._opp_mgr.sanitize(item.opportunity_id)
            self._opp_mgr.evaluate(
                item.opportunity_id,
                credibility=scores["credibility"],
                novelty=scores["novelty"],
                actionability=scores["actionability"],
                business_value=scores["business_value"],
            )
            self._opp_mgr.suggest(item.opportunity_id)

            result.passed += 1
            result.opportunity_ids.append(item.opportunity_id)
            self._raw_store.mark_scored(raw["raw_id"])

        return result

    def _passes_filters(
        self,
        source: ScoutSource,
        scores: dict[str, float],
    ) -> bool:
        """Apply user preference filters to a scored source."""
        if scores["business_value"] < self._prefs.min_score:
            return False

        if self._prefs.languages and source.language:
            if source.language.lower() not in [lang.lower() for lang in self._prefs.languages]:
                return False

        if source.license_type and source.license_type.lower() not in ALLOWED_LICENSES:
            return False

        if self._prefs.exclude_licenses:
            if source.license_type.lower() in [lic.lower() for lic in self._prefs.exclude_licenses]:
                return False

        if self._prefs.exclude_repos:
            normalized = source.title.lower()
            for excluded in self._prefs.exclude_repos:
                if excluded.lower() in normalized:
                    return False

        return True

    def get_suggested_opportunities(self, limit: int = 50) -> list[Any]:
        """Get all suggested opportunities ready for review."""
        return self._opp_mgr.list_by_state(OpportunityState.SUGGESTED, limit=limit)
