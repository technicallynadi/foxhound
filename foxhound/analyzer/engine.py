"""Analyzer engine for post-run diagnosis and rule suggestions.

Performs failure classification, context gap detection, readiness feedback,
and generates rule suggestions that require human approval before activation.
"""

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from foxhound.core.models import (
    EventType,
    ResultEnvelope,
    ResultStatus,
    RunRecord,
    RunState,
    TaskEnvelope,
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
from foxhound.storage.database import (
    ArtifactStore,
    Database,
    EventStore,
    RuleSuggestionStore,
    RunStore,
)


class FailureClass(StrEnum):
    """Classification of run failures."""

    BAD_TICKET = "bad_ticket"
    CONTEXT_GAP = "context_gap"
    WRONG_MODEL = "wrong_model"
    VALIDATION_FAILURE = "validation_failure"
    TIMEOUT = "timeout"
    BUDGET_EXCEEDED = "budget_exceeded"
    SECURITY_VIOLATION = "security_violation"
    UNKNOWN = "unknown"


class RuleSuggestionState(StrEnum):
    """State machine for rule suggestions."""

    PROPOSED = "proposed"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVATED = "activated"


class AnalysisDiagnosis(BaseModel):
    """Structured diagnosis from analyzer."""

    run_id: str = Field(..., description="Analyzed run ID")
    failure_class: FailureClass | None = Field(
        default=None, description="Failure classification if failed"
    )
    context_gaps: list[str] = Field(
        default_factory=list, description="Detected context gaps"
    )
    readiness_issues: list[str] = Field(
        default_factory=list, description="Readiness problems detected"
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Human-readable recommendations"
    )
    rule_suggestions: list[dict[str, Any]] = Field(
        default_factory=list, description="Proposed rule changes"
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Analysis confidence"
    )

    model_config = {"extra": "forbid"}


class AnalyzerEngine:
    """Post-run analysis engine.

    Analyzes completed and failed runs to classify failures, detect
    context gaps, assess readiness, and propose rule suggestions.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._run_store = RunStore(db)
        self._event_store = EventStore(db)
        self._artifact_store = ArtifactStore(db)
        self._suggestion_store = RuleSuggestionStore(db)

    def analyze_run(self, run_id: str) -> AnalysisDiagnosis:
        """Analyze a completed or failed run."""
        run = self._run_store.get(run_id)
        if run is None:
            return AnalysisDiagnosis(
                run_id=run_id,
                recommendations=["Run not found"],
                confidence=0.0,
            )

        diagnosis = AnalysisDiagnosis(run_id=run_id)

        if run.state == RunState.FAILED:
            diagnosis.failure_class = self._classify_failure(run)
            diagnosis.recommendations.extend(
                self._failure_recommendations(diagnosis.failure_class, run)
            )

        diagnosis.context_gaps = self._detect_context_gaps(run)
        if diagnosis.context_gaps:
            diagnosis.recommendations.append(
                f"Context gaps detected: {', '.join(diagnosis.context_gaps)}"
            )

        diagnosis.readiness_issues = self._assess_readiness(run)

        diagnosis.rule_suggestions = self._generate_rule_suggestions(run, diagnosis)
        for suggestion in diagnosis.rule_suggestions:
            self._persist_rule_suggestion(suggestion, run)

        diagnosis.confidence = self._compute_confidence(diagnosis, run)
        return diagnosis

    def _classify_failure(self, run: RunRecord) -> FailureClass:
        """Classify the type of failure for a failed run."""
        reason = (run.failure_reason or "").lower()

        if "timeout" in reason or "timed out" in reason:
            return FailureClass.TIMEOUT

        if "budget" in reason or "cost" in reason:
            return FailureClass.BUDGET_EXCEEDED

        if "security" in reason or "violation" in reason:
            return FailureClass.SECURITY_VIOLATION

        if "validation" in reason or "lint" in reason or "test" in reason:
            return FailureClass.VALIDATION_FAILURE

        if "model" in reason or "provider" in reason or "api" in reason:
            return FailureClass.WRONG_MODEL

        if "context" in reason or "missing" in reason or "not found" in reason:
            return FailureClass.CONTEXT_GAP

        if "ticket" in reason or "description" in reason or "criteria" in reason:
            return FailureClass.BAD_TICKET

        return FailureClass.UNKNOWN

    def _failure_recommendations(
        self, failure_class: FailureClass, run: RunRecord
    ) -> list[str]:
        """Generate recommendations based on failure class."""
        recs: dict[FailureClass, list[str]] = {
            FailureClass.BAD_TICKET: [
                "Work item may lack clear acceptance criteria",
                "Consider editing the work item with more specific requirements",
            ],
            FailureClass.CONTEXT_GAP: [
                "Context assembly may have missed required files",
                "Check include/exclude patterns in the recipe",
            ],
            FailureClass.WRONG_MODEL: [
                "Model tier may be insufficient for this task complexity",
                "Consider upgrading to reasoning tier for complex tasks",
            ],
            FailureClass.VALIDATION_FAILURE: [
                "Validation commands failed after execution",
                "Review validation command output for specific errors",
            ],
            FailureClass.TIMEOUT: [
                "Execution exceeded timeout limit",
                f"Current timeout may be too short (retry_count: {run.retry_count})",
            ],
            FailureClass.BUDGET_EXCEEDED: [
                "Execution exceeded budget allocation",
                f"Total cost was ${run.total_cost:.4f}",
            ],
            FailureClass.SECURITY_VIOLATION: [
                "Security review detected violations",
                "Review security findings before retrying",
            ],
            FailureClass.UNKNOWN: [
                f"Unclassified failure: {run.failure_reason or 'no reason recorded'}",
            ],
        }
        return recs.get(failure_class, [])

    def _detect_context_gaps(self, run: RunRecord) -> list[str]:
        """Detect potential context gaps from run events."""
        gaps: list[str] = []
        events = self._event_store.list_by_run(run.run_id)

        has_eval_events = False
        has_security_events = False

        for event in events:
            if event.event_type in (
                EventType.EVALUATION_PASSED,
                EventType.EVALUATION_FAILED,
            ):
                has_eval_events = True
            if event.event_type in (
                EventType.SECURITY_SCAN_STARTED,
                EventType.SECURITY_VIOLATION_DETECTED,
            ):
                has_security_events = True

            if event.event_type == EventType.EVALUATION_FAILED:
                reason = event.payload.get("reason", "")
                if "missing" in reason.lower() or "not found" in reason.lower():
                    gaps.append(f"Missing resource: {reason}")

        if run.state == RunState.FAILED:
            if not has_eval_events:
                gaps.append(
                    "No evaluation events found — execution may have failed before evaluation"
                )
            if not has_security_events:
                gaps.append("No security scan events — security review may not have run")

        return gaps

    def _assess_readiness(self, run: RunRecord) -> list[str]:
        """Assess readiness issues from run metadata."""
        issues: list[str] = []

        if run.retry_count > 2:
            issues.append(
                f"High retry count ({run.retry_count}) — task may need human intervention"
            )

        if run.state == RunState.FAILED and not run.failure_reason:
            issues.append("Failed run has no failure reason recorded")

        return issues

    def _generate_rule_suggestions(
        self, run: RunRecord, diagnosis: AnalysisDiagnosis
    ) -> list[dict[str, Any]]:
        """Generate rule suggestions based on analysis patterns."""
        suggestions: list[dict[str, Any]] = []

        if diagnosis.failure_class == FailureClass.CONTEXT_GAP and diagnosis.context_gaps:
            suggestions.append({
                "rule_name": "include_missing_resources",
                "rule_type": "context_inclusion",
                "condition": "context_gap_detected",
                "action": "add_include_patterns",
                "evidence": f"Gaps: {', '.join(diagnosis.context_gaps)}",
                "confidence": 0.6,
            })

        if run.retry_count > 2 and diagnosis.failure_class == FailureClass.TIMEOUT:
            suggestions.append({
                "rule_name": "increase_timeout",
                "rule_type": "resource_limit",
                "condition": "retry_count > 2 and timeout failures",
                "action": "increase_timeout_seconds",
                "evidence": f"Run {run.run_id} failed {run.retry_count} times with timeout",
                "confidence": 0.7,
            })

        return suggestions

    def _persist_rule_suggestion(
        self, suggestion: dict[str, Any], run: RunRecord
    ) -> None:
        """Persist a rule suggestion to the database."""
        suggestion_id = f"sug_{uuid.uuid4().hex[:12]}"
        self._suggestion_store.save(
            suggestion_id=suggestion_id,
            rule_name=suggestion["rule_name"],
            rule_type=suggestion["rule_type"],
            condition=suggestion["condition"],
            action=suggestion["action"],
            evidence=suggestion.get("evidence"),
            confidence=suggestion.get("confidence", 0.0),
            suggested_by="analyzer",
        )

    def _compute_confidence(
        self, diagnosis: AnalysisDiagnosis, run: RunRecord
    ) -> float:
        """Compute overall analysis confidence."""
        confidence = 0.5

        if diagnosis.failure_class and diagnosis.failure_class != FailureClass.UNKNOWN:
            confidence += 0.2

        events = self._event_store.list_by_run(run.run_id)
        if len(events) > 3:
            confidence += 0.1

        if run.failure_reason:
            confidence += 0.1

        return min(confidence, 1.0)

    def get_pending_suggestions(self) -> list[dict[str, Any]]:
        """Get all rule suggestions pending review."""
        return self._suggestion_store.list_by_state("pending_review")

    def approve_suggestion(
        self, suggestion_id: str, reviewed_by: str = "user"
    ) -> bool:
        """Approve a rule suggestion."""
        return self._suggestion_store.update_state(
            suggestion_id, "approved", reviewed_by=reviewed_by
        )

    def reject_suggestion(
        self, suggestion_id: str, reviewed_by: str = "user"
    ) -> bool:
        """Reject a rule suggestion."""
        return self._suggestion_store.update_state(
            suggestion_id, "rejected", reviewed_by=reviewed_by
        )


class AnalyzerWorker:
    """Worker that performs post-run analysis.

    Implements the Worker Protocol for integration with the harness.
    Capabilities: read artifacts only, no repo write, no shell.
    """

    worker_name = "analyzer_worker"
    worker_class = WorkerClass.HELPER
    capabilities = {Capability.REPO_READ, Capability.SPAWN}
    allowed_spawn_targets: list[str] = []
    default_timeout_seconds = 120
    default_budget = 0.5

    def __init__(self, db: Database) -> None:
        self._engine = AnalyzerEngine(db)

    def validate_input(self, task: TaskEnvelope) -> ValidationResult:
        """Validate that task contains a run_id to analyze."""
        run_id = task.input_payload.get("run_id")
        if not run_id:
            return ValidationResult(
                valid=False,
                errors=["input_payload must contain 'run_id'"],
            )
        return ValidationResult(valid=True)

    def build_context(self, task: TaskEnvelope) -> ContextBuildResult:
        """Build context from run artifacts."""
        return ContextBuildResult(
            context_pack={"run_id": task.input_payload.get("run_id", "")},
            context_hash="analyzer_context",
        )

    def execute(
        self, task: TaskEnvelope, runtime: RuntimeHandle
    ) -> WorkerOutput:
        """Run analysis on the specified run."""
        run_id = task.input_payload["run_id"]
        diagnosis = self._engine.analyze_run(run_id)

        return WorkerOutput(
            payload=diagnosis.model_dump(),
            cost=0.0,
        )

    def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput:
        """Pass through — analyzer output is already structured."""
        return SanitizedOutput(
            payload=output.payload,
            commands_run=output.commands_run,
            files_changed=output.files_changed,
            cost=output.cost,
            artifact_paths=output.artifact_paths,
        )

    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult:
        """Evaluate analyzer output quality."""
        has_diagnosis = bool(output.payload.get("run_id"))
        return EvaluationResult(
            passed=has_diagnosis,
            confidence=output.payload.get("confidence", 0.0),
        )

    def finalize(self, result: EvaluationResult) -> ResultEnvelope:
        """Emit structured result envelope."""
        return ResultEnvelope(
            status=ResultStatus.SUCCESS if result.passed else ResultStatus.FAILED,
            confidence=result.confidence,
            safety_flags=result.safety_flags,
        )
