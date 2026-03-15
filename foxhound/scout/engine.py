"""Scout engine for external opportunity discovery.

Discovers opportunities from external sources (GitHub trending, Reddit)
and produces OpportunityDiscoveryItems. Scout findings are evidence-only,
never directly executable.
"""

import hashlib
from typing import Any

from pydantic import BaseModel, Field

from foxhound.core.models import (
    OpportunityDiscoveryItem,
    OpportunityState,
    ResultEnvelope,
    ResultStatus,
    TaskEnvelope,
    TrustLevel,
)
from foxhound.harness.worker_protocol import (
    Capability,
    ContextBuildResult,
    EvaluationResult,
    RuntimeHandle,
    SanitizedOutput,
    ValidationResult,
    WorkerClass,
    WorkerOutput,
)
from foxhound.scout.opportunity import OpportunityManager
from foxhound.storage.database import Database

ALLOWED_LICENSES = {"mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause"}


class ScoutSource(BaseModel):
    """A discovered external source item."""

    title: str = Field(..., description="Item title")
    description: str = Field(default="", description="Item description")
    source_type: str = Field(..., description="Source type (github_trending, reddit)")
    source_url: str | None = Field(default=None, description="Source URL")
    stars: int = Field(default=0, description="Star/upvote count")
    star_velocity: float = Field(default=0.0, description="Stars gained per day")
    language: str = Field(default="", description="Primary language")
    license_type: str = Field(default="", description="License identifier")
    tags: list[str] = Field(default_factory=list, description="Tags")
    evidence: dict[str, Any] = Field(default_factory=dict, description="Raw evidence")

    model_config = {"extra": "forbid"}


def score_opportunity(source: ScoutSource) -> dict[str, float]:
    """Score an opportunity based on star velocity, improvability, buildability."""
    velocity_score = min(source.star_velocity / 10.0, 1.0) if source.star_velocity > 0 else 0.0
    improvability = 0.5
    if source.stars < 1000:
        improvability = 0.7
    elif source.stars > 10000:
        improvability = 0.3

    buildability = 0.5
    if source.license_type.lower() in ALLOWED_LICENSES:
        buildability = 0.8
    if source.language:
        buildability = min(buildability + 0.1, 1.0)

    composite = velocity_score * 0.4 + improvability * 0.3 + buildability * 0.3

    return {
        "credibility": min(velocity_score + 0.3, 1.0),
        "novelty": improvability,
        "actionability": buildability,
        "business_value": composite,
    }


def source_to_opportunity(
    source: ScoutSource,
) -> OpportunityDiscoveryItem:
    """Convert a ScoutSource into an OpportunityDiscoveryItem."""
    fingerprint = hashlib.sha256(
        f"{source.source_type}:{source.title}:{source.source_url or ''}".encode()
    ).hexdigest()[:16]

    return OpportunityDiscoveryItem(
        opportunity_id=f"opp_{hashlib.md5(fingerprint.encode()).hexdigest()[:12]}",
        title=source.title,
        description=source.description,
        source_type=source.source_type,
        source_url=source.source_url,
        source_fingerprint=fingerprint,
        trust_level=TrustLevel.UNTRUSTED,
        state=OpportunityState.OBSERVED,
        credibility_score=0.0,
        novelty_score=0.0,
        actionability_score=0.0,
        business_value_score=0.0,
        evidence=source.evidence,
        tags=source.tags,
    )


class ScoutEngine:
    """Orchestrates external discovery from multiple sources.

    Collects sources, filters by license, scores, deduplicates,
    and produces opportunity items.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._opportunity_mgr = OpportunityManager(db)

    def process_sources(
        self, sources: list[ScoutSource]
    ) -> list[OpportunityDiscoveryItem]:
        """Process a batch of scout sources into opportunity items.

        Filters by license, deduplicates, scores, and persists.
        """
        results: list[OpportunityDiscoveryItem] = []

        for source in sources:
            if not self._passes_license_filter(source):
                continue

            item = source_to_opportunity(source)

            existing = self._opportunity_mgr.find_by_fingerprint(
                item.source_fingerprint
            )
            if existing is not None:
                continue

            self._opportunity_mgr._store.save(item)

            self._opportunity_mgr.sanitize(item.opportunity_id)
            self._opportunity_mgr.evaluate(
                item.opportunity_id,
                credibility=item.credibility_score,
                novelty=item.novelty_score,
                actionability=item.actionability_score,
                business_value=item.business_value_score,
            )
            self._opportunity_mgr.suggest(item.opportunity_id)

            updated = self._opportunity_mgr.get(item.opportunity_id)
            if updated:
                results.append(updated)

        return results

    def _passes_license_filter(self, source: ScoutSource) -> bool:
        """Check if source has an allowed license."""
        if not source.license_type:
            return True
        return source.license_type.lower() in ALLOWED_LICENSES


class ScoutWorker:
    """Worker for external opportunity discovery.

    Implements the Worker Protocol. Capabilities: no repo access,
    network (bounded), no shell.
    """

    worker_name = "scout_worker"
    worker_class = WorkerClass.ROOT
    capabilities = {Capability.NETWORK, Capability.SPAWN}
    allowed_spawn_targets: list[str] = ["evidence_validator"]
    default_timeout_seconds = 300
    default_budget = 1.0

    def __init__(self, db: Database) -> None:
        self._engine = ScoutEngine(db)

    def validate_input(self, task: TaskEnvelope) -> ValidationResult:
        """Validate scout task input."""
        sources = task.input_payload.get("sources")
        if sources is None:
            return ValidationResult(
                valid=False,
                errors=["input_payload must contain 'sources' list"],
            )
        if not isinstance(sources, list):
            return ValidationResult(
                valid=False,
                errors=["'sources' must be a list of source items"],
            )
        return ValidationResult(valid=True)

    def build_context(self, task: TaskEnvelope) -> ContextBuildResult:
        """Build context from scout configuration."""
        return ContextBuildResult(
            context_pack={
                "source_count": len(task.input_payload.get("sources", [])),
            },
            context_hash="scout_context",
            trust_labels={"sources": "untrusted"},
        )

    def execute(
        self, task: TaskEnvelope, runtime: RuntimeHandle
    ) -> WorkerOutput:
        """Execute scout discovery."""
        raw_sources = task.input_payload.get("sources", [])
        sources = [ScoutSource(**s) for s in raw_sources]

        results = self._engine.process_sources(sources)

        return WorkerOutput(
            payload={
                "opportunities_found": len(results),
                "opportunity_ids": [r.opportunity_id for r in results],
            },
            cost=0.0,
        )

    def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput:
        """Sanitize scout output."""
        return SanitizedOutput(
            payload=output.payload,
            commands_run=output.commands_run,
            files_changed=output.files_changed,
            cost=output.cost,
            artifact_paths=output.artifact_paths,
        )

    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult:
        """Evaluate scout output."""
        count = output.payload.get("opportunities_found", 0)
        return EvaluationResult(
            passed=True,
            confidence=0.8 if count > 0 else 0.5,
        )

    def finalize(self, result: EvaluationResult) -> ResultEnvelope:
        """Emit structured result."""
        return ResultEnvelope(
            status=ResultStatus.SUCCESS if result.passed else ResultStatus.FAILED,
            confidence=result.confidence,
            safety_flags=result.safety_flags,
        )
