"""Evaluation engine for assessing sanitized worker outputs."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from foxhound.core.models import RiskLevel, TrustLevel
from foxhound.harness.worker_protocol import EvaluationResult, SanitizedOutput


class Classification(StrEnum):
    """Output classification after evaluation."""

    ACCEPTED = "accepted"
    REVIEW = "review"
    QUARANTINE = "quarantine"
    REJECT = "reject"


class ReadinessState(StrEnum):
    """Work item readiness assessment."""

    READY = "ready"
    NEEDS_EDIT = "needs_edit"
    BLOCKED = "blocked"
    TOO_BROAD = "too_broad"


class EvaluationCriteria(BaseModel):
    """Individual evaluation criterion result."""

    name: str
    passed: bool
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    details: str = Field(default="")


class DetailedEvaluationResult(BaseModel):
    """Full evaluation result with classification and evidence."""

    classification: Classification
    readiness: ReadinessState
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)
    criteria_results: list[EvaluationCriteria] = Field(default_factory=list)
    safety_flags: list[str] = Field(default_factory=list)
    evaluator_notes: list[str] = Field(default_factory=list)
    recommended_next_action: str | None = Field(default=None)

    def to_harness_result(self) -> EvaluationResult:
        """Convert to the harness EvaluationResult type."""
        return EvaluationResult(
            passed=self.classification in (Classification.ACCEPTED, Classification.REVIEW),
            confidence=self.confidence,
            safety_flags=self.safety_flags,
            evaluator_notes=self.evaluator_notes,
            recommended_next_action=self.recommended_next_action,
        )


def check_grounding(
    payload: dict[str, Any],
    trust_labels: dict[str, str],
) -> EvaluationCriteria:
    """Check if the output is based on real evidence.

    Grounded outputs reference concrete files, issues, or artifacts.
    Speculative outputs with no evidence score low.
    """
    evidence_keys = {"evidence", "source_files", "issue_ref", "ci_log", "diff",
                     "files_changed", "artifact_paths", "source_url"}
    found = [k for k in payload if k in evidence_keys]
    has_evidence = len(found) > 0

    # Trust labels boost grounding — trusted/semi-trusted sources are grounded
    trusted_sources = sum(
        1 for level in trust_labels.values()
        if level in (TrustLevel.TRUSTED.value, TrustLevel.SEMI_TRUSTED.value)
    )

    if has_evidence and trusted_sources > 0:
        score = min(1.0, 0.5 + trusted_sources * 0.1 + len(found) * 0.1)
        return EvaluationCriteria(
            name="grounding",
            passed=True,
            score=score,
            details=f"Grounded: {len(found)} evidence key(s), {trusted_sources} trusted source(s)",
        )
    elif has_evidence:
        return EvaluationCriteria(
            name="grounding",
            passed=True,
            score=0.5,
            details=f"Evidence present ({len(found)} key(s)) but no trusted sources",
        )
    else:
        return EvaluationCriteria(
            name="grounding",
            passed=False,
            score=0.1,
            details="No evidence keys found in output",
        )


def check_scope(
    payload: dict[str, Any],
    files_changed: list[str],
) -> EvaluationCriteria:
    """Check if the output is appropriately scoped for autonomous execution.

    Too-broad outputs (many files, vague descriptions) get flagged.
    """
    file_count = len(files_changed)

    if file_count > 20:
        return EvaluationCriteria(
            name="scope",
            passed=False,
            score=0.2,
            details=f"Too broad: {file_count} files changed (max 20 for auto)",
        )

    # Check payload for scope indicators
    description = str(payload.get("description", ""))
    title = str(payload.get("title", ""))

    vague_terms = ["everything", "all files", "entire codebase", "refactor all",
                   "rewrite everything"]
    is_vague = any(term in description.lower() or term in title.lower()
                   for term in vague_terms)

    if is_vague:
        return EvaluationCriteria(
            name="scope",
            passed=False,
            score=0.3,
            details="Scope appears too broad based on description",
        )

    score = max(0.5, 1.0 - file_count * 0.03)
    return EvaluationCriteria(
        name="scope",
        passed=True,
        score=score,
        details=f"Scope acceptable: {file_count} file(s) changed",
    )


def check_trust_compliance(
    trust_labels: dict[str, str],
    redactions_applied: list[str],
) -> EvaluationCriteria:
    """Check if trust boundaries are properly respected.

    Flags untrusted content that wasn't properly sanitized.
    """
    untrusted_count = sum(
        1 for level in trust_labels.values()
        if level == TrustLevel.UNTRUSTED.value
    )

    flags: list[str] = []
    if untrusted_count > 0 and not redactions_applied:
        flags.append(f"{untrusted_count} untrusted source(s) with no redactions")

    has_redactions = len(redactions_applied) > 0

    if untrusted_count > 0 and not has_redactions:
        return EvaluationCriteria(
            name="trust_compliance",
            passed=False,
            score=0.3,
            details=f"Untrusted content ({untrusted_count} source(s)) not sanitized",
        )

    if has_redactions:
        return EvaluationCriteria(
            name="trust_compliance",
            passed=True,
            score=0.9,
            details=f"Trust compliance met; {len(redactions_applied)} redaction(s) applied",
        )

    return EvaluationCriteria(
        name="trust_compliance",
        passed=True,
        score=1.0,
        details="All content from trusted/semi-trusted sources",
    )


def check_policy_compliance(
    safety_flags: list[str],
    redactions_applied: list[str],
) -> EvaluationCriteria:
    """Check if policy constraints are satisfied.

    Reviews sanitization results for policy violations.
    """
    # Safety flags from sanitization indicate policy issues
    critical_flags = [f for f in safety_flags if "BLOCK" in f.upper() or "VIOLATION" in f.upper()]

    if critical_flags:
        return EvaluationCriteria(
            name="policy_compliance",
            passed=False,
            score=0.0,
            details=f"Policy violations detected: {critical_flags}",
        )

    # Redactions suggest the pipeline caught issues — good sign
    pattern_strips = [r for r in redactions_applied if "Stripped" in r]
    if pattern_strips:
        return EvaluationCriteria(
            name="policy_compliance",
            passed=True,
            score=0.7,
            details=f"Dangerous patterns stripped ({len(pattern_strips)}), output now compliant",
        )

    return EvaluationCriteria(
        name="policy_compliance",
        passed=True,
        score=1.0,
        details="No policy violations detected",
    )


def classify_result(criteria: list[EvaluationCriteria]) -> Classification:
    """Determine classification from evaluation criteria results.

    - ACCEPTED: all criteria pass with high scores
    - REVIEW: some criteria marginal or low scores
    - QUARANTINE: safety/trust failures that need investigation
    - REJECT: hard failures on critical criteria
    """
    all_passed = all(c.passed for c in criteria)
    avg_score = sum(c.score for c in criteria) / len(criteria) if criteria else 0.0

    # Any trust or policy failure -> quarantine
    trust_and_policy = [c for c in criteria
                        if c.name in ("trust_compliance", "policy_compliance")]
    if any(not c.passed for c in trust_and_policy):
        return Classification.QUARANTINE

    # All pass with high confidence -> accepted
    if all_passed and avg_score >= 0.7:
        return Classification.ACCEPTED

    # All pass but low scores -> review
    if all_passed:
        return Classification.REVIEW

    # Scope too broad -> review (not reject, human can narrow)
    scope = next((c for c in criteria if c.name == "scope"), None)
    if scope and not scope.passed:
        return Classification.REVIEW

    # Grounding failure -> review
    grounding = next((c for c in criteria if c.name == "grounding"), None)
    if grounding and not grounding.passed:
        return Classification.REVIEW

    return Classification.REJECT


def assess_readiness(
    classification: Classification,
    criteria: list[EvaluationCriteria],
) -> ReadinessState:
    """Determine readiness state from classification and criteria."""
    if classification == Classification.ACCEPTED:
        return ReadinessState.READY

    if classification == Classification.QUARANTINE:
        return ReadinessState.BLOCKED

    # Check scope for too_broad
    scope = next((c for c in criteria if c.name == "scope"), None)
    if scope and not scope.passed and "too broad" in scope.details.lower():
        return ReadinessState.TOO_BROAD

    return ReadinessState.NEEDS_EDIT


def assess_risk(
    criteria: list[EvaluationCriteria],
    files_changed: list[str],
) -> RiskLevel:
    """Determine risk level from evaluation criteria and scope."""
    avg_score = sum(c.score for c in criteria) / len(criteria) if criteria else 0.0

    # Many files = higher risk
    if len(files_changed) > 10:
        return RiskLevel.HIGH

    # Low average score = higher risk
    if avg_score < 0.5:
        return RiskLevel.HIGH
    elif avg_score < 0.7:
        return RiskLevel.MEDIUM

    return RiskLevel.LOW


class EvaluationEngine:
    """Evaluates sanitized worker outputs for quality and safety.

    Runs four criteria checks:
    1. Grounding — is the output based on real evidence?
    2. Scope — is it appropriately scoped for autonomous execution?
    3. Trust compliance — does it respect trust boundaries?
    4. Policy compliance — does it pass policy constraints?

    Produces a classification (accepted/review/quarantine/reject),
    readiness state, confidence score, and risk level.
    """

    def evaluate(
        self,
        output: SanitizedOutput,
        trust_labels: dict[str, str] | None = None,
        safety_flags: list[str] | None = None,
    ) -> DetailedEvaluationResult:
        """Run full evaluation on a sanitized output.

        Args:
            output: Sanitized worker output to evaluate.
            trust_labels: Trust labels from sanitization (file -> trust level).
            safety_flags: Any safety flags from prior checks.

        Returns:
            DetailedEvaluationResult with classification, readiness, and scores.
        """
        labels = trust_labels or {}
        flags = safety_flags or []

        # Run all criteria checks
        criteria: list[EvaluationCriteria] = [
            check_grounding(output.payload, labels),
            check_scope(output.payload, output.files_changed),
            check_trust_compliance(labels, output.redactions_applied),
            check_policy_compliance(flags, output.redactions_applied),
        ]

        # Derive classification, readiness, risk
        classification = classify_result(criteria)
        readiness = assess_readiness(classification, criteria)
        risk = assess_risk(criteria, output.files_changed)

        # Overall confidence is average of all criteria scores
        confidence = sum(c.score for c in criteria) / len(criteria) if criteria else 0.0

        # Build evaluator notes
        notes: list[str] = []
        for c in criteria:
            if not c.passed:
                notes.append(f"[{c.name}] FAILED: {c.details}")
            elif c.score < 0.7:
                notes.append(f"[{c.name}] LOW: {c.details}")

        # Build safety flags from criteria
        eval_safety_flags = list(flags)
        for c in criteria:
            if not c.passed and c.name in ("trust_compliance", "policy_compliance"):
                eval_safety_flags.append(f"{c.name}_failed: {c.details}")

        # Recommended action
        action = None
        if classification == Classification.QUARANTINE:
            action = "quarantine_review"
        elif classification == Classification.REVIEW:
            action = "human_review"
        elif readiness == ReadinessState.TOO_BROAD:
            action = "narrow_scope"

        return DetailedEvaluationResult(
            classification=classification,
            readiness=readiness,
            confidence=round(confidence, 3),
            risk_level=risk,
            criteria_results=criteria,
            safety_flags=eval_safety_flags,
            evaluator_notes=notes,
            recommended_next_action=action,
        )
