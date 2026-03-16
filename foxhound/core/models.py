"""Core Pydantic models for Foxhound."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


# =============================================================================
# Enums
# =============================================================================


class TrustLevel(StrEnum):
    """Trust tiers enforced at all boundaries."""

    TRUSTED = "trusted"
    SEMI_TRUSTED = "semi_trusted"
    UNTRUSTED = "untrusted"


class WorkItemKind(StrEnum):
    """Type of work item."""

    EXECUTION = "execution"
    OPPORTUNITY = "opportunity"
    SCOUT = "scout"


class WorkItemState(StrEnum):
    """Work item state machine states.

    Flow: discovered -> suggested -> approved|edited|rejected|blocked ->
          executing -> completed|failed
    """

    DISCOVERED = "discovered"
    SUGGESTED = "suggested"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class OpportunityState(StrEnum):
    """Opportunity discovery item state machine.

    Flow: observed -> sanitized -> evaluated -> suggested ->
          approved|rejected -> converted_to_project
    """

    OBSERVED = "observed"
    SANITIZED = "sanitized"
    EVALUATED = "evaluated"
    SUGGESTED = "suggested"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONVERTED_TO_PROJECT = "converted_to_project"


class SignalTier(StrEnum):
    """Signal classification tiers ordered by evidence strength.

    Tier 1-3 are primary targets. Tier 4-5 are lower priority.
    """

    PAIN = "pain"
    WORKAROUND = "workaround"
    REPEATED_QUESTION = "repeated_question"
    FEATURE_GAP = "feature_gap"
    TREND = "trend"


SIGNAL_TIER_RANK: dict["SignalTier", int] = {
    SignalTier.PAIN: 1,
    SignalTier.WORKAROUND: 2,
    SignalTier.REPEATED_QUESTION: 3,
    SignalTier.FEATURE_GAP: 4,
    SignalTier.TREND: 5,
}


class AIExposureAngle(StrEnum):
    """AI exposure analysis angle for an opportunity."""

    DISRUPTION = "disruption"
    GREENFIELD = "greenfield"


class ConfidenceLevel(StrEnum):
    """Opportunity confidence level derived from composite score."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RiskLevel(StrEnum):
    """Risk classification for work items."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class JobType(StrEnum):
    """Type of queued job."""

    DISCOVERY = "discovery"
    SCOUT = "scout"
    EXECUTION = "execution"
    ANALYZER = "analyzer"
    NOTIFICATION = "notification"


class JobStatus(StrEnum):
    """Job queue status."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPriority(StrEnum):
    """Job priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class RunState(StrEnum):
    """Run state machine states.

    Flow: queued -> preparing -> context_built -> executing -> validating ->
          security_review -> branch_ready -> pr_draft_ready -> completed|failed|cancelled
    """

    QUEUED = "queued"
    PREPARING = "preparing"
    CONTEXT_BUILT = "context_built"
    EXECUTING = "executing"
    VALIDATING = "validating"
    SECURITY_REVIEW = "security_review"
    BRANCH_READY = "branch_ready"
    PR_DRAFT_READY = "pr_draft_ready"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionStrategy(StrEnum):
    """Execution strategy for jobs."""

    ONE_SHOT = "one_shot"
    BOUNDED_RETRY = "bounded_retry"
    RALPH_LOOP = "ralph_loop"


class ModelTier(StrEnum):
    """Capability tiers for model routing.

    Workers and recipes reference tiers, never model names.
    Users map tiers to specific models in foxhound.yaml.
    """

    REASONING = "reasoning"
    BALANCED = "balanced"
    FAST = "fast"
    CREATIVE = "creative"


class ExecutionMode(StrEnum):
    """Execution mode controlling worker capabilities."""

    READ_ONLY = "read_only"
    PLAN_ONLY = "plan_only"
    PATCH_ONLY = "patch_only"
    FULL_EXECUTE = "full_execute"


class ResultStatus(StrEnum):
    """Worker result status."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class EventSeverity(StrEnum):
    """Event severity levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class EventType(StrEnum):
    """Core event types emitted by the system."""

    # Discovery Events
    WORK_ITEM_DISCOVERED = "WorkItemDiscovered"
    DISCOVERY_SCAN_COMPLETED = "DiscoveryScanCompleted"

    # Execution Events
    RUN_QUEUED = "RunQueued"
    RUN_STARTED = "RunStarted"
    RUN_COMPLETED = "RunCompleted"
    RUN_FAILED = "RunFailed"

    # Evaluation Events
    EVALUATION_STARTED = "EvaluationStarted"
    EVALUATION_PASSED = "EvaluationPassed"
    EVALUATION_FAILED = "EvaluationFailed"

    # Security Events
    SECURITY_SCAN_STARTED = "SecurityScanStarted"
    SECURITY_VIOLATION_DETECTED = "SecurityViolationDetected"

    # Approval Events
    APPROVAL_REQUESTED = "ApprovalRequested"
    APPROVAL_GRANTED = "ApprovalGranted"
    APPROVAL_REJECTED = "ApprovalRejected"

    # Ralph Events
    RALPH_ITERATION_COMPLETED = "RalphIterationCompleted"

    # Spawning Events
    WORKER_SPAWN_REQUESTED = "WorkerSpawnRequested"
    WORKER_SPAWN_APPROVED = "WorkerSpawnApproved"
    WORKER_SPAWN_FAILED = "WorkerSpawnFailed"

    # Promotion Events
    PROMOTION_STARTED = "PromotionStarted"
    PROMOTION_SUCCEEDED = "PromotionSucceeded"
    PROMOTION_FAILED = "PromotionFailed"

    # Rules/Policies Events
    RULE_SUGGESTION_CREATED = "RuleSuggestionCreated"
    POLICY_BLOCKED_ACTION = "PolicyBlockedAction"
    RULE_APPLIED = "RuleApplied"


# =============================================================================
# Reference Models
# =============================================================================


class RecipeRef(BaseModel):
    """Recipe reference with semantic version and content hash."""

    name: str = Field(..., description="Recipe name")
    version: str = Field(..., description="Semantic version (e.g., '1.2.0')")
    content_hash: str = Field(..., description="Content hash for integrity verification")
    source_scope: str = Field(
        default="builtin", description="Source scope: 'builtin', 'global', or 'repo'"
    )


class PolicyRef(BaseModel):
    """Policy reference with semantic version and content hash."""

    name: str = Field(..., description="Policy pack name")
    version: str = Field(..., description="Semantic version (e.g., '1.0.0')")
    content_hash: str = Field(..., description="Content hash for integrity verification")
    source_scope: str = Field(
        default="builtin", description="Source scope: 'builtin', 'global', or 'repo'"
    )


# =============================================================================
# Execution Models
# =============================================================================


class ExecutionSnapshot(BaseModel):
    """Frozen execution configuration captured at queue time.

    Once a job is queued, recipe/policy versions cannot change.
    """

    recipe_ref: RecipeRef = Field(..., description="Frozen recipe reference")
    policy_ref: PolicyRef = Field(..., description="Frozen policy reference")
    execution_strategy: ExecutionStrategy = Field(
        default=ExecutionStrategy.ONE_SHOT, description="Selected execution strategy"
    )
    model_tier: ModelTier = Field(
        default=ModelTier.BALANCED, description="Model capability tier"
    )
    config_hash: str = Field(..., description="Hash of combined configuration")


# =============================================================================
# Work Item Models
# =============================================================================


class WorkItem(BaseModel):
    """Repo-executable task candidate with state tracking."""

    work_item_id: str = Field(..., description="Canonical work item ID")
    repo_id: str = Field(..., description="Owning repository ID")
    kind: WorkItemKind = Field(default=WorkItemKind.EXECUTION, description="Work item type")
    title: str = Field(..., description="Human-readable summary")
    description: str = Field(default="", description="Detailed description")
    source_type: str = Field(
        ..., description="Source type: 'ci_failure', 'github_issue', 'dependency_alert', etc."
    )
    source_fingerprint: str = Field(..., description="Hash of evidence payload")
    trust_level: TrustLevel = Field(
        default=TrustLevel.SEMI_TRUSTED, description="Trust classification"
    )
    state: WorkItemState = Field(default=WorkItemState.DISCOVERED, description="Current state")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score 0-1")
    risk: RiskLevel = Field(default=RiskLevel.LOW, description="Risk classification")
    recipe_name: str | None = Field(default=None, description="Selected or suggested recipe")
    evidence: dict[str, Any] = Field(
        default_factory=dict, description="Supporting evidence payload"
    )
    likely_files: list[str] = Field(
        default_factory=list, description="Likely affected files or repo zones"
    )
    created_at: datetime = Field(default_factory=_utc_now, description="Creation timestamp")
    updated_at: datetime = Field(
        default_factory=_utc_now, description="Last update timestamp"
    )

    model_config = {"extra": "forbid"}


class OpportunityDiscoveryItem(BaseModel):
    """External opportunity candidate from scout (non-executable, evidence-only)."""

    opportunity_id: str = Field(..., description="Unique opportunity identifier")
    title: str = Field(..., description="Human-readable opportunity title")
    description: str = Field(default="", description="Detailed description")
    source_type: str = Field(
        ..., description="Source type: 'reddit', 'github_trending', 'article', etc."
    )
    source_url: str | None = Field(default=None, description="Original source URL")
    source_fingerprint: str = Field(..., description="Hash of evidence payload")
    trust_level: TrustLevel = Field(
        default=TrustLevel.UNTRUSTED, description="Always untrusted for scout items"
    )
    state: OpportunityState = Field(
        default=OpportunityState.OBSERVED, description="Current state"
    )

    # Signal classification
    signal_tier: SignalTier | None = Field(
        default=None, description="Signal tier (pain, workaround, etc.)"
    )
    signal_type: str = Field(default="", description="Signal type label for display")

    # 6-dimension scoring (each 0-5)
    problem_intensity: float = Field(
        default=0.0, ge=0.0, le=5.0, description="How painful the problem is (weight 2x)"
    )
    frequency: float = Field(
        default=0.0, ge=0.0, le=5.0, description="How often the issue appears across sources"
    )
    workaround_presence: float = Field(
        default=0.0, ge=0.0, le=5.0, description="Whether users built workarounds"
    )
    market_potential: float = Field(
        default=0.0, ge=0.0, le=5.0, description="How many users might be affected"
    )
    build_feasibility: float = Field(
        default=0.0, ge=0.0, le=5.0, description="How easily an MVP could be built"
    )
    topic_relevance: float = Field(
        default=0.0, ge=0.0, le=5.0, description="How closely it matches user topics"
    )
    opportunity_score: float = Field(
        default=0.0, ge=0.0, le=35.0, description="Composite score (max 35)"
    )
    confidence_level: ConfidenceLevel = Field(
        default=ConfidenceLevel.LOW, description="Score-derived confidence level"
    )

    # AI exposure analysis
    ai_exposure_score: float = Field(
        default=0.0, ge=0.0, le=10.0, description="AI exposure scale (0-10)"
    )
    ai_exposure_angle: AIExposureAngle | None = Field(
        default=None, description="Disruption or greenfield angle"
    )

    # Enrichment and matching
    matched_topic: str = Field(default="", description="Which user topic matched")
    enrichment_summary: str = Field(default="", description="TinyFish enrichment summary")
    distribution_channels: list[str] = Field(
        default_factory=list, description="Identified distribution channels"
    )

    # Build artifact hints
    recommended_product: str = Field(default="", description="Suggested product concept")
    mvp_features: list[str] = Field(default_factory=list, description="Minimal MVP features")
    suggested_stack: str = Field(default="", description="Suggested tech stack")
    estimated_build_time: str = Field(default="", description="Estimated build time")
    estimated_build_cost: str = Field(default="", description="Estimated build cost")

    # Legacy scores (kept for backward compatibility during migration)
    credibility_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Source credibility score"
    )
    novelty_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Novelty/uniqueness score"
    )
    actionability_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Actionability score"
    )
    business_value_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Business value score"
    )

    evidence: dict[str, Any] = Field(
        default_factory=dict, description="Raw evidence from source"
    )
    tags: list[str] = Field(default_factory=list, description="Classification tags")
    created_at: datetime = Field(default_factory=_utc_now, description="Discovery timestamp")
    updated_at: datetime = Field(
        default_factory=_utc_now, description="Last update timestamp"
    )

    model_config = {"extra": "forbid"}

    def compute_opportunity_score(self) -> float:
        """Compute composite opportunity score from 6 dimensions."""
        score = (
            (self.problem_intensity * 2)
            + self.frequency
            + self.workaround_presence
            + self.market_potential
            + self.build_feasibility
            + self.topic_relevance
        )
        return min(score, 35.0)

    def derive_confidence_level(
        self, high: float = 25.0, medium: float = 18.0
    ) -> ConfidenceLevel:
        """Derive confidence level from opportunity score."""
        if self.opportunity_score >= high:
            return ConfidenceLevel.HIGH
        if self.opportunity_score >= medium:
            return ConfidenceLevel.MEDIUM
        return ConfidenceLevel.LOW


# =============================================================================
# Job and Run Models
# =============================================================================


class JobEnvelope(BaseModel):
    """Queued work unit with immutable execution snapshot."""

    job_id: str = Field(..., description="Unique job identifier")
    work_item_id: str = Field(..., description="Originating work item ID")
    repo_id: str = Field(..., description="Target repository ID")
    job_type: JobType = Field(..., description="Type of job")
    priority: JobPriority = Field(default=JobPriority.NORMAL, description="Job priority")
    status: JobStatus = Field(default=JobStatus.QUEUED, description="Current status")
    execution_snapshot: ExecutionSnapshot = Field(
        ..., description="Frozen recipe/policy/config snapshot"
    )
    budget: float = Field(default=1.0, ge=0.0, description="Allocated budget")
    timeout_seconds: int = Field(default=300, ge=0, description="Hard timeout in seconds")
    spawn_depth: int = Field(default=0, ge=0, description="0 for root jobs, increments for spawned")
    parent_job_id: str | None = Field(default=None, description="Parent job ID for spawned jobs")
    queued_at: datetime = Field(default_factory=_utc_now, description="Queue timestamp")
    started_at: datetime | None = Field(default=None, description="Run start timestamp")
    finished_at: datetime | None = Field(default=None, description="Run end timestamp")

    model_config = {"extra": "forbid"}


class RunRecord(BaseModel):
    """Single worker execution record with runtime metadata."""

    run_id: str = Field(..., description="Unique run identifier")
    job_id: str = Field(..., description="Owning job ID")
    worker_type: str = Field(
        ..., description="Worker type: 'ExecutionWorker', 'DiscoveryWorker', etc."
    )
    state: RunState = Field(default=RunState.QUEUED, description="Current run state")
    branch_name: str | None = Field(default=None, description="Created branch name if applicable")
    workspace_path: str | None = Field(default=None, description="Temp workspace path used")
    total_cost: float = Field(default=0.0, ge=0.0, description="Observed cost")
    retry_count: int = Field(default=0, ge=0, description="Number of retries used")
    failure_reason: str | None = Field(default=None, description="Normalized failure class")
    manifest_path: str | None = Field(default=None, description="Path to manifest artifact")
    security_review_passed: bool = Field(
        default=False, description="Whether security review has explicitly passed"
    )
    artifact_refs: list[str] = Field(
        default_factory=list, description="References to generated artifacts"
    )
    created_at: datetime = Field(default_factory=_utc_now, description="Run creation time")
    updated_at: datetime = Field(
        default_factory=_utc_now, description="Last state update time"
    )

    model_config = {"extra": "forbid"}


# =============================================================================
# Task and Result Envelopes
# =============================================================================


class TaskEnvelope(BaseModel):
    """Worker task input with frozen recipe/policy/config."""

    task_id: str = Field(..., description="Stable task identifier")
    job_id: str = Field(..., description="Owning job ID")
    run_id: str = Field(..., description="Owning run ID")
    repo_id: str = Field(..., description="Repository scope")
    execution_snapshot: ExecutionSnapshot = Field(
        ..., description="Frozen recipe/policy/config snapshot"
    )
    trust_metadata: dict[str, TrustLevel] = Field(
        default_factory=dict, description="Trust labels for all source inputs"
    )
    budget: float = Field(default=1.0, ge=0.0, description="Allocated budget")
    timeout_seconds: int = Field(default=300, ge=0, description="Hard timeout")
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.FULL_EXECUTE, description="Execution mode"
    )
    input_payload: dict[str, Any] = Field(
        default_factory=dict, description="Worker-specific input"
    )

    model_config = {"extra": "forbid"}


class ResultEnvelope(BaseModel):
    """Worker output with status, payload, confidence, evidence, and artifacts."""

    status: ResultStatus = Field(..., description="Result status")
    payload: dict[str, Any] = Field(default_factory=dict, description="Worker-specific output")
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Normalized confidence score"
    )
    evidence: dict[str, Any] = Field(
        default_factory=dict, description="Supporting structured evidence"
    )
    safety_flags: list[str] = Field(
        default_factory=list, description="Rule or trust warnings"
    )
    artifact_refs: list[str] = Field(
        default_factory=list, description="Paths or IDs of generated artifacts"
    )
    recommended_next_action: str | None = Field(
        default=None, description="Optional follow-up or spawn suggestion"
    )

    model_config = {"extra": "forbid"}


# =============================================================================
# Event Model
# =============================================================================


class EventEnvelope(BaseModel):
    """Structured event with event_id, event_type, timestamp, source_module, and payload."""

    event_id: str = Field(..., description="Unique event identifier")
    event_type: EventType = Field(..., description="Type of event")
    timestamp: datetime = Field(default_factory=_utc_now, description="Event timestamp")
    source_module: str = Field(..., description="Module that emitted the event")
    run_id: str | None = Field(default=None, description="Associated run ID")
    repo_id: str | None = Field(default=None, description="Associated repository ID")
    job_id: str | None = Field(default=None, description="Associated job ID")
    severity: EventSeverity = Field(default=EventSeverity.INFO, description="Event severity")
    payload: dict[str, Any] = Field(default_factory=dict, description="Structured event payload")

    model_config = {"extra": "forbid"}


# =============================================================================
# Manifest Model
# =============================================================================


class Manifest(BaseModel):
    """Canonical provenance record with hashes, versions, sources, commands, outputs."""

    manifest_id: str = Field(..., description="Unique manifest identifier")
    run_id: str = Field(..., description="Associated run ID")
    work_item_id: str = Field(..., description="Source work item ID")
    repo_id: str = Field(..., description="Target repository ID")

    # Recipe and policy provenance
    recipe_ref: RecipeRef = Field(..., description="Recipe reference used")
    policy_ref: PolicyRef = Field(..., description="Policy reference used")
    context_pack_hash: str = Field(..., description="Hash of context pack used")
    execution_environment_fingerprint: str = Field(
        ..., description="Execution environment fingerprint"
    )

    # Execution metadata
    execution_strategy: ExecutionStrategy = Field(..., description="Strategy used")
    model_provider: str = Field(..., description="Model provider used")
    model_tier: ModelTier = Field(..., description="Model tier requested")
    model_resolved: str = Field(default="", description="Actual model identifier that ran")
    workspace_id: str = Field(..., description="Workspace identifier")

    # Cost and timing
    total_cost: float = Field(default=0.0, ge=0.0, description="Total execution cost")
    duration_seconds: float = Field(default=0.0, ge=0.0, description="Total duration in seconds")

    # Outputs
    commands_run: list[str] = Field(default_factory=list, description="Commands executed")
    files_changed: list[str] = Field(default_factory=list, description="Files modified")
    branch_ref: str | None = Field(default=None, description="Created branch reference")
    commit_ref: str | None = Field(default=None, description="Created commit reference")
    pr_ref: str | None = Field(default=None, description="Created PR reference")
    artifact_refs: list[str] = Field(
        default_factory=list, description="Generated artifact references"
    )

    # Evaluation results
    evaluator_result: str | None = Field(default=None, description="Evaluator outcome")
    security_result: str | None = Field(default=None, description="Security review outcome")

    # Ralph-specific fields (optional, for ralph_loop strategy)
    iteration_count: int | None = Field(default=None, description="Total iterations for Ralph")
    max_iterations: int | None = Field(default=None, description="Max iterations configured")
    per_iteration_costs: list[float] | None = Field(
        default=None, description="Cost per iteration"
    )
    per_iteration_tasks_completed: list[int] | None = Field(
        default=None, description="Tasks completed per iteration"
    )
    commit_refs: list[str] | None = Field(
        default=None, description="Commit refs per iteration"
    )
    progress_file_path: str | None = Field(
        default=None, description="Path to Ralph progress file"
    )
    completion_status: str | None = Field(
        default=None, description="'complete', 'partial', or 'failed' for Ralph"
    )

    created_at: datetime = Field(default_factory=_utc_now, description="Manifest creation")

    model_config = {"extra": "forbid"}
