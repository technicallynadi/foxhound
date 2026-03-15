"""Opportunity item state machine and lifecycle management.

Scout items follow a separate state machine from work items.
They are never directly executable — must be explicitly converted
to work items after approval.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from foxhound.core.models import (
    OpportunityDiscoveryItem,
    OpportunityState,
    TrustLevel,
    WorkItem,
    WorkItemKind,
    WorkItemState,
)
from foxhound.storage.database import Database, OpportunityStore

# Valid opportunity state transitions
OPPORTUNITY_TRANSITIONS: dict[OpportunityState, set[OpportunityState]] = {
    OpportunityState.OBSERVED: {OpportunityState.SANITIZED},
    OpportunityState.SANITIZED: {OpportunityState.EVALUATED},
    OpportunityState.EVALUATED: {OpportunityState.SUGGESTED},
    OpportunityState.SUGGESTED: {
        OpportunityState.APPROVED,
        OpportunityState.REJECTED,
    },
    OpportunityState.APPROVED: {OpportunityState.CONVERTED_TO_PROJECT},
}


class OpportunityManager:
    """Manages the opportunity item lifecycle.

    Enforces state machine transitions, handles approval/rejection,
    and converts approved opportunities to executable work items.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._store = OpportunityStore(db)

    def create(
        self,
        title: str,
        source_type: str,
        source_url: str | None = None,
        evidence: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> OpportunityDiscoveryItem:
        """Create a new opportunity in OBSERVED state."""
        evidence_data = evidence or {}
        fingerprint = hashlib.sha256(
            f"{source_type}:{title}:{source_url or ''}".encode()
        ).hexdigest()[:16]

        item = OpportunityDiscoveryItem(
            opportunity_id=f"opp_{uuid4().hex[:12]}",
            title=title,
            source_type=source_type,
            source_url=source_url,
            source_fingerprint=fingerprint,
            trust_level=TrustLevel.UNTRUSTED,
            state=OpportunityState.OBSERVED,
            evidence=evidence_data,
            tags=tags or [],
        )
        self._store.save(item)
        return item

    def get(self, opportunity_id: str) -> OpportunityDiscoveryItem | None:
        """Get an opportunity by ID."""
        return self._store.get(opportunity_id)

    def list_by_state(
        self, state: OpportunityState, limit: int = 100
    ) -> list[OpportunityDiscoveryItem]:
        """List opportunities in a given state."""
        return self._store.list_by_state(state, limit=limit)

    def advance(
        self, opportunity_id: str, new_state: OpportunityState
    ) -> OpportunityDiscoveryItem:
        """Advance an opportunity through the state machine.

        Raises:
            ValueError: If the transition is invalid or item not found.
        """
        item = self._store.get(opportunity_id)
        if item is None:
            raise ValueError(f"Opportunity {opportunity_id} not found")

        valid_targets = OPPORTUNITY_TRANSITIONS.get(item.state, set())
        if new_state not in valid_targets:
            raise ValueError(
                f"Invalid transition: {item.state.value} -> {new_state.value}. "
                f"Valid targets: {[s.value for s in valid_targets]}"
            )

        item.state = new_state
        item.updated_at = datetime.now(UTC)
        self._store.save(item)
        return item

    def sanitize(self, opportunity_id: str) -> OpportunityDiscoveryItem:
        """Move from OBSERVED to SANITIZED."""
        return self.advance(opportunity_id, OpportunityState.SANITIZED)

    def evaluate(
        self,
        opportunity_id: str,
        credibility: float = 0.0,
        novelty: float = 0.0,
        actionability: float = 0.0,
        business_value: float = 0.0,
    ) -> OpportunityDiscoveryItem:
        """Evaluate and score an opportunity, moving to EVALUATED."""
        item = self._store.get(opportunity_id)
        if item is None:
            raise ValueError(f"Opportunity {opportunity_id} not found")

        item.credibility_score = credibility
        item.novelty_score = novelty
        item.actionability_score = actionability
        item.business_value_score = business_value
        self._store.save(item)

        return self.advance(opportunity_id, OpportunityState.EVALUATED)

    def suggest(self, opportunity_id: str) -> OpportunityDiscoveryItem:
        """Move from EVALUATED to SUGGESTED (ready for human review)."""
        return self.advance(opportunity_id, OpportunityState.SUGGESTED)

    def approve(self, opportunity_id: str) -> OpportunityDiscoveryItem:
        """Approve an opportunity for potential conversion."""
        return self.advance(opportunity_id, OpportunityState.APPROVED)

    def reject(self, opportunity_id: str) -> OpportunityDiscoveryItem:
        """Reject an opportunity."""
        return self.advance(opportunity_id, OpportunityState.REJECTED)

    def convert_to_work_item(
        self, opportunity_id: str, repo_id: str
    ) -> WorkItem:
        """Convert an approved opportunity to an executable work item.

        The opportunity must be in APPROVED state. Creates a new work item
        with the opportunity evidence attached, then marks the opportunity
        as CONVERTED_TO_PROJECT.

        Returns:
            The created WorkItem.

        Raises:
            ValueError: If opportunity is not approved.
        """
        item = self._store.get(opportunity_id)
        if item is None:
            raise ValueError(f"Opportunity {opportunity_id} not found")

        if item.state != OpportunityState.APPROVED:
            raise ValueError(
                f"Can only convert approved opportunities, "
                f"got state '{item.state.value}'"
            )

        work_item = WorkItem(
            work_item_id=f"wi_{uuid4().hex[:12]}",
            repo_id=repo_id,
            kind=WorkItemKind.OPPORTUNITY,
            title=item.title,
            description=item.description,
            source_type=f"scout:{item.source_type}",
            source_fingerprint=item.source_fingerprint,
            trust_level=TrustLevel.SEMI_TRUSTED,
            state=WorkItemState.DISCOVERED,
            confidence=item.actionability_score,
            evidence={
                "opportunity_id": item.opportunity_id,
                "source_url": item.source_url,
                "credibility_score": item.credibility_score,
                "novelty_score": item.novelty_score,
                "actionability_score": item.actionability_score,
                "business_value_score": item.business_value_score,
                "original_evidence": item.evidence,
                "tags": item.tags,
            },
        )

        self.advance(opportunity_id, OpportunityState.CONVERTED_TO_PROJECT)
        return work_item

    def find_by_fingerprint(
        self, source_fingerprint: str
    ) -> OpportunityDiscoveryItem | None:
        """Find an opportunity by fingerprint for dedup."""
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM opportunity_items WHERE source_fingerprint = ?",
                (source_fingerprint,),
            ).fetchone()
            if row is None:
                return None
            return self._store._row_to_model(row)
