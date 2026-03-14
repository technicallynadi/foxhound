"""Code review agent — evaluates execution output before human approval.

The CodeReviewWorker is a helper worker that analyzes diffs and produces
structured findings across five categories: correctness, security,
architecture, style, and completeness. It reads code and produces findings.
Nothing else.

Supports multiple review strategies with tier-based model routing:
- full_reasoning: reasoning tier for all categories (default)
- budget_balanced: balanced tier for all categories (budget-constrained)
- cost_optimized: multi-pass with escalating tiers per category
- ralph_intermediate: fast tier for lightweight regression checks
- ralph_final: reasoning tier for full review of complete Ralph output
"""

import time
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from foxhound.core.models import (
    ExecutionMode,
    ModelTier,
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
from foxhound.sanitization.pipeline import redact_secrets

# =========================================================================
# Review Models
# =========================================================================


class ReviewCategory(StrEnum):
    """Categories evaluated by the code review agent."""

    CORRECTNESS = "correctness"
    SECURITY = "security"
    ARCHITECTURE = "architecture"
    STYLE = "style"
    COMPLETENESS = "completeness"


class FindingSeverity(StrEnum):
    """Severity levels for review findings."""

    CRITICAL = "critical"
    WARNING = "warning"
    SUGGESTION = "suggestion"


class ReviewVerdict(StrEnum):
    """Overall review verdict."""

    PASS = "pass"
    PASS_WITH_WARNINGS = "pass_with_warnings"
    NEEDS_REVIEW = "needs_review"
    RECOMMEND_REJECT = "recommend_reject"


class CategoryResult(StrEnum):
    """Per-category result."""

    PASS = "pass"
    WARNING = "warning"
    CRITICAL = "critical"
    SUGGESTION = "suggestion"


class ReviewStrategy(StrEnum):
    """Review strategy determining model routing."""

    FULL_REASONING = "full_reasoning"
    BUDGET_BALANCED = "budget_balanced"
    COST_OPTIMIZED = "cost_optimized"
    RALPH_INTERMEDIATE = "ralph_intermediate"
    RALPH_FINAL = "ralph_final"


class Finding(BaseModel):
    """A single review finding with location and recommendation."""

    category: ReviewCategory = Field(..., description="Finding category")
    severity: FindingSeverity = Field(..., description="Finding severity")
    file: str = Field(..., description="File path where finding was identified")
    line: int | None = Field(default=None, description="Line number if available")
    description: str = Field(..., description="Description of the issue")
    recommendation: str = Field(..., description="Recommended action")


class ReviewResult(BaseModel):
    """Structured output from the code review agent."""

    review_id: str = Field(..., description="Unique review identifier")
    run_id: str = Field(..., description="Associated run ID")
    model_tier: str = Field(..., description="Model tier used")
    review_strategy: ReviewStrategy = Field(
        ..., description="Review strategy applied"
    )
    duration_seconds: float = Field(
        default=0.0, ge=0.0, description="Review duration"
    )
    cost: float = Field(default=0.0, ge=0.0, description="Review cost")
    overall_verdict: ReviewVerdict = Field(
        ..., description="Overall review verdict"
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Confidence score 0-1"
    )
    summary: str = Field(
        default="", description="Human-readable 2-3 sentence summary"
    )
    findings: list[Finding] = Field(
        default_factory=list, description="All review findings"
    )
    category_results: dict[str, CategoryResult] = Field(
        default_factory=dict, description="Per-category results"
    )


# =========================================================================
# Review Strategy Routing (#47)
# =========================================================================


# Tier assignments per strategy and category
_STRATEGY_TIER_MAP: dict[ReviewStrategy, dict[ReviewCategory, ModelTier]] = {
    ReviewStrategy.FULL_REASONING: {
        ReviewCategory.CORRECTNESS: ModelTier.REASONING,
        ReviewCategory.SECURITY: ModelTier.REASONING,
        ReviewCategory.ARCHITECTURE: ModelTier.REASONING,
        ReviewCategory.STYLE: ModelTier.REASONING,
        ReviewCategory.COMPLETENESS: ModelTier.REASONING,
    },
    ReviewStrategy.BUDGET_BALANCED: {
        ReviewCategory.CORRECTNESS: ModelTier.BALANCED,
        ReviewCategory.SECURITY: ModelTier.BALANCED,
        ReviewCategory.ARCHITECTURE: ModelTier.BALANCED,
        ReviewCategory.STYLE: ModelTier.BALANCED,
        ReviewCategory.COMPLETENESS: ModelTier.BALANCED,
    },
    ReviewStrategy.COST_OPTIMIZED: {
        ReviewCategory.CORRECTNESS: ModelTier.REASONING,
        ReviewCategory.SECURITY: ModelTier.REASONING,
        ReviewCategory.ARCHITECTURE: ModelTier.BALANCED,
        ReviewCategory.STYLE: ModelTier.FAST,
        ReviewCategory.COMPLETENESS: ModelTier.FAST,
    },
    ReviewStrategy.RALPH_INTERMEDIATE: {
        ReviewCategory.CORRECTNESS: ModelTier.FAST,
        ReviewCategory.SECURITY: ModelTier.FAST,
        ReviewCategory.ARCHITECTURE: ModelTier.FAST,
        ReviewCategory.STYLE: ModelTier.FAST,
        ReviewCategory.COMPLETENESS: ModelTier.FAST,
    },
    ReviewStrategy.RALPH_FINAL: {
        ReviewCategory.CORRECTNESS: ModelTier.REASONING,
        ReviewCategory.SECURITY: ModelTier.REASONING,
        ReviewCategory.ARCHITECTURE: ModelTier.REASONING,
        ReviewCategory.STYLE: ModelTier.REASONING,
        ReviewCategory.COMPLETENESS: ModelTier.REASONING,
    },
}


def get_tier_for_category(
    strategy: ReviewStrategy, category: ReviewCategory
) -> ModelTier:
    """Get the model tier for a specific category under a given strategy.

    Args:
        strategy: The review strategy being used.
        category: The review category to look up.

    Returns:
        The ModelTier to use for this category.
    """
    return _STRATEGY_TIER_MAP[strategy][category]


def get_primary_tier(strategy: ReviewStrategy) -> ModelTier:
    """Get the primary (highest) model tier used by a strategy.

    For manifest recording — returns the most capable tier used.

    Args:
        strategy: The review strategy.

    Returns:
        The highest tier used in this strategy.
    """
    tiers = set(_STRATEGY_TIER_MAP[strategy].values())
    if ModelTier.REASONING in tiers:
        return ModelTier.REASONING
    if ModelTier.BALANCED in tiers:
        return ModelTier.BALANCED
    return ModelTier.FAST


def select_review_strategy(
    is_ralph_intermediate: bool = False,
    is_ralph_final: bool = False,
    budget_constrained: bool = False,
    cost_optimized: bool = False,
) -> ReviewStrategy:
    """Select the appropriate review strategy based on context.

    Args:
        is_ralph_intermediate: Whether this is a Ralph intermediate review.
        is_ralph_final: Whether this is a Ralph final review.
        budget_constrained: Whether the budget is limited.
        cost_optimized: Whether to use cost-optimized multi-pass mode.

    Returns:
        The selected ReviewStrategy.
    """
    if is_ralph_intermediate:
        return ReviewStrategy.RALPH_INTERMEDIATE
    if is_ralph_final:
        return ReviewStrategy.RALPH_FINAL
    if cost_optimized:
        return ReviewStrategy.COST_OPTIMIZED
    if budget_constrained:
        return ReviewStrategy.BUDGET_BALANCED
    return ReviewStrategy.FULL_REASONING


def get_review_passes(strategy: ReviewStrategy) -> list[tuple[ModelTier, list[ReviewCategory]]]:
    """Get the review passes for a strategy, grouped by tier.

    For cost_optimized, returns three separate passes with escalating tiers.
    For all others, returns a single pass with all categories.

    Args:
        strategy: The review strategy.

    Returns:
        List of (tier, categories) tuples representing each pass.
    """
    tier_map = _STRATEGY_TIER_MAP[strategy]

    if strategy == ReviewStrategy.COST_OPTIMIZED:
        # Group categories by tier for multi-pass
        tier_groups: dict[ModelTier, list[ReviewCategory]] = {}
        for cat, tier in tier_map.items():
            tier_groups.setdefault(tier, []).append(cat)
        # Order: fast -> balanced -> reasoning
        ordered_tiers = [ModelTier.FAST, ModelTier.BALANCED, ModelTier.REASONING]
        return [
            (tier, tier_groups[tier])
            for tier in ordered_tiers
            if tier in tier_groups
        ]

    # Single pass for all other strategies
    primary_tier = get_primary_tier(strategy)
    return [(primary_tier, list(ReviewCategory))]


# =========================================================================
# Review Evaluation Logic
# =========================================================================


def compute_verdict(findings: list[Finding]) -> ReviewVerdict:
    """Compute the overall verdict from findings.

    Args:
        findings: List of review findings.

    Returns:
        The overall ReviewVerdict.
    """
    if not findings:
        return ReviewVerdict.PASS

    severities = {f.severity for f in findings}

    if FindingSeverity.CRITICAL in severities:
        critical_count = sum(
            1 for f in findings if f.severity == FindingSeverity.CRITICAL
        )
        if critical_count >= 3:
            return ReviewVerdict.RECOMMEND_REJECT
        return ReviewVerdict.NEEDS_REVIEW

    if FindingSeverity.WARNING in severities:
        return ReviewVerdict.PASS_WITH_WARNINGS

    return ReviewVerdict.PASS


def compute_category_results(
    findings: list[Finding],
) -> dict[str, CategoryResult]:
    """Compute per-category results from findings.

    Args:
        findings: List of review findings.

    Returns:
        Dict mapping category names to their results.
    """
    results: dict[str, CategoryResult] = {}

    for category in ReviewCategory:
        cat_findings = [f for f in findings if f.category == category]
        if not cat_findings:
            results[category.value] = CategoryResult.PASS
            continue

        severities = {f.severity for f in cat_findings}
        if FindingSeverity.CRITICAL in severities:
            results[category.value] = CategoryResult.CRITICAL
        elif FindingSeverity.WARNING in severities:
            results[category.value] = CategoryResult.WARNING
        else:
            results[category.value] = CategoryResult.SUGGESTION

    return results


def compute_confidence(
    findings: list[Finding], strategy: ReviewStrategy
) -> float:
    """Compute confidence score based on findings and strategy.

    Higher-tier strategies produce higher base confidence. Critical findings
    reduce confidence.

    Args:
        findings: List of review findings.
        strategy: The review strategy used.

    Returns:
        Confidence score between 0 and 1.
    """
    base_confidence: dict[ReviewStrategy, float] = {
        ReviewStrategy.FULL_REASONING: 0.95,
        ReviewStrategy.RALPH_FINAL: 0.95,
        ReviewStrategy.BUDGET_BALANCED: 0.80,
        ReviewStrategy.COST_OPTIMIZED: 0.90,
        ReviewStrategy.RALPH_INTERMEDIATE: 0.70,
    }

    confidence = base_confidence.get(strategy, 0.80)

    critical_count = sum(
        1 for f in findings if f.severity == FindingSeverity.CRITICAL
    )
    warning_count = sum(
        1 for f in findings if f.severity == FindingSeverity.WARNING
    )

    confidence -= critical_count * 0.10
    confidence -= warning_count * 0.03

    return max(0.0, min(1.0, confidence))


def build_review_summary(
    findings: list[Finding], verdict: ReviewVerdict
) -> str:
    """Build a human-readable summary from findings and verdict.

    Args:
        findings: List of review findings.
        verdict: The overall verdict.

    Returns:
        A 2-3 sentence summary string.
    """
    if not findings:
        return "No issues found. All categories passed review."

    critical = [f for f in findings if f.severity == FindingSeverity.CRITICAL]
    warnings = [f for f in findings if f.severity == FindingSeverity.WARNING]
    suggestions = [f for f in findings if f.severity == FindingSeverity.SUGGESTION]

    parts: list[str] = []

    if verdict == ReviewVerdict.RECOMMEND_REJECT:
        parts.append(
            f"Found {len(critical)} critical issue(s) that should be addressed before merging."
        )
    elif verdict == ReviewVerdict.NEEDS_REVIEW:
        parts.append(
            f"Found {len(critical)} critical issue(s) requiring human review."
        )
    elif verdict == ReviewVerdict.PASS_WITH_WARNINGS:
        parts.append(
            f"Code looks good overall with {len(warnings)} warning(s) to consider."
        )
    else:
        parts.append("All checks passed.")

    if warnings and verdict != ReviewVerdict.PASS_WITH_WARNINGS:
        parts.append(f"{len(warnings)} warning(s) noted.")
    if suggestions:
        parts.append(f"{len(suggestions)} suggestion(s) for improvement.")

    return " ".join(parts)


# =========================================================================
# Review Manifest Fields
# =========================================================================


def build_review_manifest_fields(result: ReviewResult) -> dict[str, Any]:
    """Build review-specific manifest fields from a ReviewResult.

    Args:
        result: The review result to extract fields from.

    Returns:
        Dict of manifest fields to merge into the run manifest.
    """
    finding_counts: dict[str, int] = {
        "critical": 0,
        "warning": 0,
        "suggestion": 0,
    }
    for finding in result.findings:
        finding_counts[finding.severity.value] += 1

    return {
        "review_id": result.review_id,
        "review_model": result.model_tier,
        "review_strategy": result.review_strategy.value,
        "review_cost": result.cost,
        "review_duration": result.duration_seconds,
        "overall_verdict": result.overall_verdict.value,
        "finding_count_by_severity": finding_counts,
        "category_results": result.category_results,
        "confidence_score": result.confidence,
    }


# =========================================================================
# Ralph Review Integration (#49)
# =========================================================================


def run_intermediate_review(
    diff_text: str,
    validation_results: list[dict[str, Any]],
    run_id: str,
    iteration: int,
) -> ReviewResult:
    """Run a lightweight intermediate review for a Ralph iteration.

    Checks for regressions: test failures, new security issues, increasing
    lint errors. Uses fast tier.

    Args:
        diff_text: Git diff of the iteration's changes.
        validation_results: Validation command results from the iteration.
        run_id: The run ID.
        iteration: The iteration number.

    Returns:
        ReviewResult with fast-tier regression checks.
    """
    start = time.time()
    strategy = ReviewStrategy.RALPH_INTERMEDIATE
    findings: list[Finding] = []

    # Check for test regressions in validation results
    for result in validation_results:
        if not result.get("passed", False):
            cmd = result.get("command", "unknown")
            error = result.get("error", result.get("stderr", ""))
            if isinstance(error, str) and len(error) > 200:
                error = error[:200]
            findings.append(Finding(
                category=ReviewCategory.CORRECTNESS,
                severity=FindingSeverity.WARNING,
                file="<validation>",
                line=None,
                description=f"Validation command '{cmd}' failed in iteration {iteration}",
                recommendation=f"Investigate failure: {error}",
            ))

    # Check diff for obvious security patterns
    security_patterns = [
        ("api_key", "Potential API key in diff"),
        ("password", "Potential password in diff"),
        ("secret", "Potential secret in diff"),
        ("eval(", "Use of eval() detected"),
        ("exec(", "Use of exec() detected"),
    ]
    for line_num, line in enumerate(diff_text.splitlines(), 1):
        if not line.startswith("+"):
            continue
        line_lower = line.lower()
        for pattern, desc in security_patterns:
            if pattern in line_lower:
                findings.append(Finding(
                    category=ReviewCategory.SECURITY,
                    severity=FindingSeverity.WARNING,
                    file="<diff>",
                    line=line_num,
                    description=desc,
                    recommendation="Verify this is not a security issue",
                ))
                break

    verdict = compute_verdict(findings)
    category_results = compute_category_results(findings)
    confidence = compute_confidence(findings, strategy)
    summary = build_review_summary(findings, verdict)
    elapsed = time.time() - start

    return ReviewResult(
        review_id=f"rev_{uuid.uuid4().hex[:12]}",
        run_id=run_id,
        model_tier=ModelTier.FAST.value,
        review_strategy=strategy,
        duration_seconds=elapsed,
        cost=0.0,
        overall_verdict=verdict,
        confidence=confidence,
        summary=summary,
        findings=findings,
        category_results=category_results,
    )


def should_pause_ralph(review: ReviewResult) -> bool:
    """Determine if a Ralph loop should pause based on intermediate review.

    Pauses on critical findings or multiple warnings that indicate regression.

    Args:
        review: The intermediate review result.

    Returns:
        True if the Ralph loop should pause for human review.
    """
    critical_count = sum(
        1 for f in review.findings if f.severity == FindingSeverity.CRITICAL
    )
    if critical_count > 0:
        return True

    warning_count = sum(
        1 for f in review.findings if f.severity == FindingSeverity.WARNING
    )
    return warning_count >= 3


def run_final_review(
    diff_text: str,
    files_changed: list[str],
    validation_results: list[dict[str, Any]],
    run_id: str,
) -> ReviewResult:
    """Run a full final review for completed Ralph output.

    Evaluates the complete accumulated diff as a cohesive whole. Uses
    reasoning tier for maximum accuracy.

    Args:
        diff_text: Complete git diff from execution branch.
        files_changed: List of all files changed.
        validation_results: Final validation results.
        run_id: The run ID.

    Returns:
        ReviewResult with reasoning-tier comprehensive review.
    """
    start = time.time()
    strategy = ReviewStrategy.RALPH_FINAL
    findings: list[Finding] = []

    # Check validation results
    for result in validation_results:
        if not result.get("passed", False):
            cmd = result.get("command", "unknown")
            error = result.get("error", result.get("stderr", ""))
            if isinstance(error, str) and len(error) > 200:
                error = error[:200]
            findings.append(Finding(
                category=ReviewCategory.CORRECTNESS,
                severity=FindingSeverity.CRITICAL,
                file="<validation>",
                line=None,
                description=f"Validation command '{cmd}' failed in final output",
                recommendation=f"Fix before merging: {error}",
            ))

    # Analyze diff for issues across all categories
    _analyze_diff_for_findings(diff_text, findings)

    # Check completeness — missing test files for changed source files
    source_files = [f for f in files_changed if not f.startswith("test")]
    test_files = {f for f in files_changed if f.startswith("test") or "/test" in f}
    for src in source_files:
        stem = Path(src).stem
        has_test = any(stem in t for t in test_files)
        if not has_test and src.endswith(".py"):
            findings.append(Finding(
                category=ReviewCategory.COMPLETENESS,
                severity=FindingSeverity.SUGGESTION,
                file=src,
                line=None,
                description=f"No corresponding test file found for {src}",
                recommendation="Consider adding tests for this module",
            ))

    verdict = compute_verdict(findings)
    category_results = compute_category_results(findings)
    confidence = compute_confidence(findings, strategy)
    summary = build_review_summary(findings, verdict)
    elapsed = time.time() - start

    return ReviewResult(
        review_id=f"rev_{uuid.uuid4().hex[:12]}",
        run_id=run_id,
        model_tier=ModelTier.REASONING.value,
        review_strategy=strategy,
        duration_seconds=elapsed,
        cost=0.0,
        overall_verdict=verdict,
        confidence=confidence,
        summary=summary,
        findings=findings,
        category_results=category_results,
    )


def _analyze_diff_for_findings(diff_text: str, findings: list[Finding]) -> None:
    """Analyze a diff for common issues across all categories.

    This is a static analysis pass. Full LLM-based review is deferred
    until model adapter integration.

    Args:
        diff_text: The git diff text.
        findings: Findings list to append to (mutated in place).
    """
    import re

    added_lines = [
        (i, line[1:])
        for i, line in enumerate(diff_text.splitlines(), 1)
        if line.startswith("+") and not line.startswith("+++")
    ]

    for line_num, line in added_lines:
        line_stripped = line.strip()

        # Security: hardcoded secrets
        secret_patterns = [
            (r'(?:api[_-]?key|token|secret|password)\s*[=:]\s*["\'][^"\']{8,}',
             "Potential hardcoded secret"),
            (r'sk-[a-zA-Z0-9]{20,}', "OpenAI-style API key detected"),
            (r'ghp_[a-zA-Z0-9]{36,}', "GitHub PAT detected"),
        ]
        for pat, desc in secret_patterns:
            if re.search(pat, line_stripped, re.IGNORECASE):
                findings.append(Finding(
                    category=ReviewCategory.SECURITY,
                    severity=FindingSeverity.CRITICAL,
                    file="<diff>",
                    line=line_num,
                    description=desc,
                    recommendation="Remove secret and use environment variable",
                ))
                break

        # Style: TODO/FIXME left in code
        if re.search(r'\b(TODO|FIXME|HACK|XXX)\b', line_stripped):
            findings.append(Finding(
                category=ReviewCategory.COMPLETENESS,
                severity=FindingSeverity.SUGGESTION,
                file="<diff>",
                line=line_num,
                description="TODO/FIXME comment left in code",
                recommendation="Resolve or track as a separate work item",
            ))


# =========================================================================
# CodeReviewWorker (#46)
# =========================================================================


class CodeReviewWorker:
    """Helper worker that evaluates execution output before human approval.

    The most restricted worker in the system: repo_read only. Cannot write
    to repo, access network, execute shell commands, or spawn children.

    Evaluates diffs across five categories: correctness, security,
    architecture, style, and completeness.
    """

    worker_name: str = "code_review_worker"
    worker_class: WorkerClass = WorkerClass.HELPER
    capabilities: set[Capability] = {Capability.REPO_READ}
    allowed_spawn_targets: list[str] = []
    default_timeout_seconds: int = 120
    default_budget: float = 0.50

    def __init__(
        self,
        diff_text: str = "",
        files_changed: list[str] | None = None,
        validation_results: list[dict[str, Any]] | None = None,
        review_strategy: ReviewStrategy = ReviewStrategy.FULL_REASONING,
        run_id: str = "",
        workspace_path: Path | None = None,
    ) -> None:
        self._diff_text = diff_text
        self._files_changed = files_changed or []
        self._validation_results = validation_results or []
        self._review_strategy = review_strategy
        self._run_id = run_id
        self._workspace_path = workspace_path
        self._review_result: ReviewResult | None = None

    def validate_input(self, task: TaskEnvelope) -> ValidationResult:
        """Validate that the task has diff data to review."""
        errors: list[str] = []
        warnings: list[str] = []

        if not task.job_id:
            errors.append("Missing job_id in task envelope")

        if not self._diff_text and not self._files_changed:
            errors.append("No diff text or files to review")

        if task.execution_mode not in (
            ExecutionMode.READ_ONLY,
            ExecutionMode.FULL_EXECUTE,
        ):
            warnings.append(
                f"Review worker is read-only but got mode '{task.execution_mode.value}'"
            )

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def build_context(self, task: TaskEnvelope) -> ContextBuildResult:
        """Build review context from diff and validation results."""
        context: dict[str, Any] = {
            "diff_text": self._diff_text[:50000],
            "files_changed": self._files_changed,
            "validation_results": self._validation_results,
            "review_strategy": self._review_strategy.value,
        }

        trust_labels: dict[str, str] = {
            "diff_text": TrustLevel.SEMI_TRUSTED.value,
            "validation_results": TrustLevel.SEMI_TRUSTED.value,
            "review_strategy": TrustLevel.TRUSTED.value,
        }

        return ContextBuildResult(
            context_pack=context,
            context_hash="",
            files_included=self._files_changed,
            trust_labels=trust_labels,
        )

    def execute(
        self, task: TaskEnvelope, runtime: RuntimeHandle
    ) -> WorkerOutput:
        """Run the code review analysis.

        In v1, this performs static analysis of the diff. Full LLM-based
        review will be wired when model adapter integration is complete.
        """
        start = time.time()

        if self._review_strategy in (
            ReviewStrategy.RALPH_INTERMEDIATE,
        ):
            self._review_result = run_intermediate_review(
                diff_text=self._diff_text,
                validation_results=self._validation_results,
                run_id=self._run_id,
                iteration=task.input_payload.get("iteration", 0),
            )
        elif self._review_strategy == ReviewStrategy.RALPH_FINAL:
            self._review_result = run_final_review(
                diff_text=self._diff_text,
                files_changed=self._files_changed,
                validation_results=self._validation_results,
                run_id=self._run_id,
            )
        else:
            self._review_result = self._run_standard_review(task)

        elapsed = time.time() - start
        self._review_result.duration_seconds = elapsed

        cost = self._review_result.cost
        if cost > 0:
            runtime.consume_budget(cost)

        return WorkerOutput(
            payload={
                "review_result": self._review_result.model_dump(),
                "review_id": self._review_result.review_id,
                "overall_verdict": self._review_result.overall_verdict.value,
                "finding_count": len(self._review_result.findings),
            },
            commands_run=[],
            files_changed=[],
            cost=cost,
            artifact_paths=[],
        )

    def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput:
        """Sanitize review output by redacting any secrets in findings."""
        sanitized_payload: dict[str, Any] = {}
        redactions: list[str] = []

        for key, value in output.payload.items():
            if isinstance(value, str):
                cleaned, found = redact_secrets(value)
                sanitized_payload[key] = cleaned
                if found:
                    redactions.append(f"Redacted secrets in '{key}'")
            else:
                sanitized_payload[key] = value

        return SanitizedOutput(
            payload=sanitized_payload,
            commands_run=output.commands_run,
            files_changed=output.files_changed,
            cost=output.cost,
            artifact_paths=output.artifact_paths,
            redactions_applied=redactions,
        )

    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult:
        """Evaluate the review output quality."""
        if self._review_result is None:
            return EvaluationResult(
                passed=False,
                confidence=0.0,
                safety_flags=["No review result produced"],
                evaluator_notes=["Review execution produced no result"],
                recommended_next_action="retry",
            )

        safety_flags: list[str] = []
        notes: list[str] = []

        if output.redactions_applied:
            safety_flags.append("Secrets detected in review output")

        verdict = self._review_result.overall_verdict
        if verdict == ReviewVerdict.RECOMMEND_REJECT:
            notes.append("Review recommends rejection")
        elif verdict == ReviewVerdict.NEEDS_REVIEW:
            notes.append("Review found critical issues requiring attention")

        return EvaluationResult(
            passed=True,
            confidence=self._review_result.confidence,
            safety_flags=safety_flags,
            evaluator_notes=notes,
            recommended_next_action="present_review",
        )

    def finalize(self, result: EvaluationResult) -> ResultEnvelope:
        """Produce the final result envelope with review data."""
        payload: dict[str, Any] = {}

        if self._review_result:
            payload = {
                "review_id": self._review_result.review_id,
                "overall_verdict": self._review_result.overall_verdict.value,
                "confidence": self._review_result.confidence,
                "finding_count": len(self._review_result.findings),
                "category_results": self._review_result.category_results,
                "summary": self._review_result.summary,
            }

        return ResultEnvelope(
            status=ResultStatus.SUCCESS if result.passed else ResultStatus.FAILED,
            payload=payload,
            confidence=result.confidence,
            safety_flags=result.safety_flags,
            artifact_refs=[],
            recommended_next_action=result.recommended_next_action,
        )

    @property
    def review_result(self) -> ReviewResult | None:
        """Access the review result after execution."""
        return self._review_result

    def _run_standard_review(self, task: TaskEnvelope) -> ReviewResult:
        """Run a standard review (non-Ralph) with the configured strategy."""
        findings: list[Finding] = []

        # Check validation results
        for result in self._validation_results:
            if not result.get("passed", False):
                cmd = result.get("command", "unknown")
                error = result.get("error", result.get("stderr", ""))
                if isinstance(error, str) and len(error) > 200:
                    error = error[:200]
                findings.append(Finding(
                    category=ReviewCategory.CORRECTNESS,
                    severity=FindingSeverity.WARNING,
                    file="<validation>",
                    line=None,
                    description=f"Validation command '{cmd}' failed",
                    recommendation=f"Fix before merging: {error}",
                ))

        # Analyze diff for issues
        _analyze_diff_for_findings(self._diff_text, findings)

        # Check completeness
        source_files = [
            f for f in self._files_changed if not f.startswith("test")
        ]
        test_files = {
            f for f in self._files_changed
            if f.startswith("test") or "/test" in f
        }
        for src in source_files:
            stem = Path(src).stem
            has_test = any(stem in t for t in test_files)
            if not has_test and src.endswith(".py"):
                findings.append(Finding(
                    category=ReviewCategory.COMPLETENESS,
                    severity=FindingSeverity.SUGGESTION,
                    file=src,
                    line=None,
                    description=f"No corresponding test file found for {src}",
                    recommendation="Consider adding tests for this module",
                ))

        primary_tier = get_primary_tier(self._review_strategy)
        verdict = compute_verdict(findings)
        category_results = compute_category_results(findings)
        confidence = compute_confidence(findings, self._review_strategy)
        summary = build_review_summary(findings, verdict)

        return ReviewResult(
            review_id=f"rev_{uuid.uuid4().hex[:12]}",
            run_id=self._run_id,
            model_tier=primary_tier.value,
            review_strategy=self._review_strategy,
            duration_seconds=0.0,
            cost=0.0,
            overall_verdict=verdict,
            confidence=confidence,
            summary=summary,
            findings=findings,
            category_results=category_results,
        )


# =========================================================================
# CLI Display Helpers (#48)
# =========================================================================


def format_review_cli(review: ReviewResult) -> str:
    """Format a ReviewResult as a rich-formatted CLI string.

    Returns markup compatible with rich console printing.

    Args:
        review: The review result to format.

    Returns:
        Rich-formatted string for console output.
    """
    # Verdict colors
    verdict_styles: dict[str, str] = {
        "pass": "bold green",
        "pass_with_warnings": "bold yellow",
        "needs_review": "bold red",
        "recommend_reject": "bold red on white",
    }
    verdict_style = verdict_styles.get(review.overall_verdict.value, "bold")
    verdict_display = review.overall_verdict.value.upper().replace("_", " ")

    # Category indicators
    cat_indicators: dict[str, str] = {
        "pass": "[green]\\u2713[/green]",
        "warning": "[yellow]\\u26a0[/yellow]",
        "critical": "[red]\\u2717[/red]",
        "suggestion": "[blue]\\u2713[/blue]",
    }

    lines: list[str] = []
    lines.append(f"  [{verdict_style}]Verdict: {verdict_display}[/{verdict_style}]")

    # Category row
    cat_parts: list[str] = []
    cat_labels = {
        "correctness": "Correctness",
        "security": "Security",
        "architecture": "Architecture",
        "style": "Style",
        "completeness": "Complete",
    }
    for cat_key, label in cat_labels.items():
        result = review.category_results.get(cat_key, CategoryResult.PASS)
        result_val = result.value if isinstance(result, CategoryResult) else result
        indicator = cat_indicators.get(result_val, "[dim]?[/dim]")
        cat_parts.append(f"{label}: {indicator}")

    lines.append(f"  {cat_parts[0]}  {cat_parts[1]}")
    lines.append(f"  {cat_parts[2]}  {cat_parts[3]}  {cat_parts[4]}")

    # Confidence
    lines.append(f"  Confidence: {review.confidence:.0%}")

    # Finding counts
    if review.findings:
        critical = sum(1 for f in review.findings if f.severity == FindingSeverity.CRITICAL)
        warnings = sum(1 for f in review.findings if f.severity == FindingSeverity.WARNING)
        suggestions = sum(1 for f in review.findings if f.severity == FindingSeverity.SUGGESTION)

        count_parts: list[str] = []
        if critical:
            count_parts.append(f"[red]{critical} critical[/red]")
        if warnings:
            count_parts.append(f"[yellow]{warnings} warning(s)[/yellow]")
        if suggestions:
            count_parts.append(f"[blue]{suggestions} suggestion(s)[/blue]")
        lines.append(f"  {', '.join(count_parts)}")

    # Findings detail
    for finding in review.findings:
        severity_icons = {
            "critical": "[red]\\u2717[/red]",
            "warning": "[yellow]\\u26a0[/yellow]",
            "suggestion": "[blue]\\u2139[/blue]",
        }
        icon = severity_icons.get(finding.severity.value, " ")
        location = finding.file
        if finding.line:
            location = f"{finding.file}:{finding.line}"
        lines.append(f"  {icon} {finding.description}")
        lines.append(f"    at {location}")
        lines.append(f"    Recommend: {finding.recommendation}")

    return "\n".join(lines)


def render_review_panel(review: ReviewResult, title: str = "Code Review") -> Any:
    """Create a rich Panel for displaying review results.

    Args:
        review: The review result to display.
        title: Panel title.

    Returns:
        A rich Panel object ready for console.print().
    """
    from rich.panel import Panel

    content = format_review_cli(review)
    verdict = review.overall_verdict.value

    border_styles = {
        "pass": "green",
        "pass_with_warnings": "yellow",
        "needs_review": "red",
        "recommend_reject": "red",
    }
    border = border_styles.get(verdict, "cyan")

    strategy_label = review.review_strategy.value.replace("_", " ").title()
    subtitle = f"Strategy: {strategy_label} | Duration: {review.duration_seconds:.1f}s"

    return Panel(
        content,
        title=f"Review: {title}",
        subtitle=subtitle,
        border_style=border,
    )
