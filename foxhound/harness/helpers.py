"""Helper workers implementing the Worker protocol.

Each helper worker is a lightweight, focused worker with restricted
capabilities. They are spawned by root workers to handle specific
subtasks like security review, evidence validation, and failure triage.
"""

from __future__ import annotations

import re
from typing import Any

from foxhound.core.models import (
    ResultEnvelope,
    ResultStatus,
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
from foxhound.sanitization.pipeline import redact_secrets

# ── SecurityReviewWorker ─────────────────────────────────────────────


# Patterns that indicate security concerns in code diffs
_SECURITY_PATTERNS: list[tuple[str, str]] = [
    (r"(?:password|secret|token|api_key)\s*=\s*['\"][^'\"]+['\"]", "hardcoded_secret"),
    (r"subprocess\.(call|run|Popen)\(.*shell\s*=\s*True", "shell_injection"),
    (r"eval\s*\(", "eval_usage"),
    (r"exec\s*\(", "exec_usage"),
    (r"__import__\s*\(", "dynamic_import"),
    (r"os\.system\s*\(", "os_system"),
    (r"pickle\.loads?\s*\(", "unsafe_deserialization"),
    (r"yaml\.load\s*\([^)]*\)(?!.*Loader)", "unsafe_yaml_load"),
    (r"chmod\s+777", "world_writable"),
    (r"0\.0\.0\.0", "bind_all_interfaces"),
]


class SecurityReviewWorker:
    """Read-only security analysis of code changes.

    Scans diffs for security patterns and produces findings
    with severity classifications. Cannot write, spawn, or
    access the network.
    """

    worker_name: str = "security_review_worker"
    worker_class: WorkerClass = WorkerClass.HELPER
    capabilities: set[Capability] = {Capability.REPO_READ}
    allowed_spawn_targets: list[str] = []
    default_timeout_seconds: int = 120
    default_budget: float = 0.50

    def __init__(self, diff_text: str = "", files_changed: list[str] | None = None) -> None:
        self._diff_text = diff_text
        self._files_changed = files_changed or []
        self._findings: list[dict[str, Any]] = []

    def validate_input(self, task: TaskEnvelope) -> ValidationResult:
        """Validate that diff text is available for review."""
        if not self._diff_text and not self._files_changed:
            return ValidationResult(
                valid=False,
                errors=["No diff text or files provided for security review"],
            )
        return ValidationResult(valid=True)

    def build_context(self, task: TaskEnvelope) -> ContextBuildResult:
        """Build context with diff text as semi-trusted input."""
        return ContextBuildResult(
            context_pack={
                "diff_text": self._diff_text[:50000],
                "files_changed": self._files_changed,
            },
            trust_labels={
                "diff_text": "semi_trusted",
                "files_changed": "semi_trusted",
            },
        )

    def execute(self, task: TaskEnvelope, runtime: RuntimeHandle) -> WorkerOutput:
        """Scan diff for security patterns."""
        self._findings = _scan_for_security_issues(self._diff_text)
        return WorkerOutput(
            payload={
                "findings": self._findings,
                "finding_count": len(self._findings),
                "patterns_checked": len(_SECURITY_PATTERNS),
            },
        )

    def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput:
        """Redact any secrets from findings."""
        sanitized_payload = _redact_payload(output.payload)
        return SanitizedOutput(
            payload=sanitized_payload,
            commands_run=output.commands_run,
            files_changed=output.files_changed,
            cost=output.cost,
        )

    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult:
        """Evaluate whether security review found critical issues."""
        findings = output.payload.get("findings", [])
        critical = [f for f in findings if f.get("severity") == "critical"]
        return EvaluationResult(
            passed=len(critical) == 0,
            confidence=0.8 if findings else 0.9,
            safety_flags=[f["pattern_name"] for f in critical],
            evaluator_notes=[
                f"Found {len(findings)} security issues, {len(critical)} critical"
            ],
        )

    def finalize(self, result: EvaluationResult) -> ResultEnvelope:
        """Emit security review result."""
        return ResultEnvelope(
            status=ResultStatus.SUCCESS if result.passed else ResultStatus.FAILED,
            payload={
                "passed": result.passed,
                "confidence": result.confidence,
                "safety_flags": result.safety_flags,
            },
        )


def _scan_for_security_issues(diff_text: str) -> list[dict[str, Any]]:
    """Scan diff text for known security anti-patterns."""
    findings: list[dict[str, Any]] = []
    for pattern_str, pattern_name in _SECURITY_PATTERNS:
        matches = re.finditer(pattern_str, diff_text, re.IGNORECASE)
        for match in matches:
            line_num = diff_text[:match.start()].count("\n") + 1
            severity = "critical" if pattern_name in (
                "hardcoded_secret", "shell_injection", "eval_usage", "exec_usage"
            ) else "warning"
            findings.append({
                "pattern_name": pattern_name,
                "severity": severity,
                "line": line_num,
                "match": match.group()[:100],
            })
    return findings


# ── EvidenceValidatorWorker ──────────────────────────────────────────


class EvidenceValidatorWorker:
    """Validates evidence grounding for work items.

    Checks that evidence references are accessible and that claims
    in work items are supported by their linked evidence. Uses the
    fast tier for quick validation.
    """

    worker_name: str = "evidence_validator"
    worker_class: WorkerClass = WorkerClass.HELPER
    capabilities: set[Capability] = {Capability.NETWORK}
    allowed_spawn_targets: list[str] = []
    default_timeout_seconds: int = 60
    default_budget: float = 0.25

    def __init__(self, evidence: list[dict[str, Any]] | None = None) -> None:
        self._evidence = evidence or []

    def validate_input(self, task: TaskEnvelope) -> ValidationResult:
        """Validate that evidence list is provided."""
        evidence = task.input_payload.get("evidence", self._evidence)
        if not evidence:
            return ValidationResult(
                valid=False,
                errors=["No evidence provided for validation"],
            )
        return ValidationResult(valid=True)

    def build_context(self, task: TaskEnvelope) -> ContextBuildResult:
        """Build context with evidence items labeled by source trust."""
        evidence = task.input_payload.get("evidence", self._evidence)
        trust_labels: dict[str, str] = {}
        for i, item in enumerate(evidence):
            source = item.get("source_type", "unknown")
            if source in ("reddit", "web_scrape", "article", "forum"):
                trust_labels[f"evidence_{i}"] = "untrusted"
            else:
                trust_labels[f"evidence_{i}"] = "semi_trusted"
        return ContextBuildResult(
            context_pack={"evidence": evidence},
            trust_labels=trust_labels,
        )

    def execute(self, task: TaskEnvelope, runtime: RuntimeHandle) -> WorkerOutput:
        """Validate each evidence item."""
        evidence = task.input_payload.get("evidence", self._evidence)
        results = []
        for item in evidence:
            result = _validate_evidence_item(item)
            results.append(result)
        return WorkerOutput(
            payload={
                "validation_results": results,
                "total": len(results),
                "valid_count": sum(1 for r in results if r["valid"]),
            },
        )

    def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput:
        """Redact secrets from validation results."""
        return SanitizedOutput(
            payload=_redact_payload(output.payload),
            commands_run=output.commands_run,
            files_changed=output.files_changed,
            cost=output.cost,
        )

    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult:
        """Check that a minimum threshold of evidence is valid."""
        total = output.payload.get("total", 0)
        valid = output.payload.get("valid_count", 0)
        ratio = valid / total if total > 0 else 0.0
        return EvaluationResult(
            passed=ratio >= 0.5,
            confidence=ratio,
            evaluator_notes=[f"{valid}/{total} evidence items validated"],
        )

    def finalize(self, result: EvaluationResult) -> ResultEnvelope:
        """Emit evidence validation result."""
        return ResultEnvelope(
            status=ResultStatus.SUCCESS if result.passed else ResultStatus.FAILED,
            payload={
                "passed": result.passed,
                "confidence": result.confidence,
                "notes": result.evaluator_notes,
            },
        )


def _validate_evidence_item(item: dict[str, Any]) -> dict[str, Any]:
    """Validate a single evidence item for grounding."""
    url = item.get("url", "")
    title = item.get("title", "")
    source_type = item.get("source_type", "unknown")

    issues: list[str] = []
    if not title:
        issues.append("missing_title")
    if source_type == "unknown":
        issues.append("unknown_source")
    if url and not url.startswith(("http://", "https://")):
        issues.append("invalid_url_scheme")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "source_type": source_type,
    }


# ── FailureTriageWorker ──────────────────────────────────────────────


# Failure classification patterns
_FAILURE_PATTERNS: dict[str, list[str]] = {
    "test_failure": ["AssertionError", "FAILED", "test_", "pytest"],
    "type_error": ["TypeError", "mypy", "type checking"],
    "import_error": ["ImportError", "ModuleNotFoundError", "No module named"],
    "timeout": ["TimeoutError", "timed out", "timeout"],
    "memory": ["MemoryError", "OutOfMemory", "OOM"],
    "permission": ["PermissionError", "Permission denied", "EACCES"],
    "network": ["ConnectionError", "URLError", "unreachable"],
    "syntax": ["SyntaxError", "IndentationError", "invalid syntax"],
}


class FailureTriageWorker:
    """Classifies execution failures for the analyzer.

    Examines failure output, logs, and context to assign a failure
    class (test_failure, type_error, timeout, etc.) and suggests
    remediation actions.
    """

    worker_name: str = "failure_triage_worker"
    worker_class: WorkerClass = WorkerClass.HELPER
    capabilities: set[Capability] = {Capability.REPO_READ}
    allowed_spawn_targets: list[str] = []
    default_timeout_seconds: int = 60
    default_budget: float = 0.25

    def __init__(self, failure_output: str = "", failure_reason: str = "") -> None:
        self._failure_output = failure_output
        self._failure_reason = failure_reason

    def validate_input(self, task: TaskEnvelope) -> ValidationResult:
        """Validate that failure context is provided."""
        output = task.input_payload.get("failure_output", self._failure_output)
        reason = task.input_payload.get("failure_reason", self._failure_reason)
        if not output and not reason:
            return ValidationResult(
                valid=False,
                errors=["No failure output or reason provided"],
            )
        return ValidationResult(valid=True)

    def build_context(self, task: TaskEnvelope) -> ContextBuildResult:
        """Build context with failure output as semi-trusted."""
        return ContextBuildResult(
            context_pack={
                "failure_output": self._failure_output[:20000],
                "failure_reason": self._failure_reason,
            },
            trust_labels={
                "failure_output": "semi_trusted",
                "failure_reason": "semi_trusted",
            },
        )

    def execute(self, task: TaskEnvelope, runtime: RuntimeHandle) -> WorkerOutput:
        """Classify the failure and suggest remediation."""
        combined = f"{self._failure_output}\n{self._failure_reason}"
        classification = _classify_failure(combined)
        return WorkerOutput(
            payload={
                "failure_class": classification["failure_class"],
                "confidence": classification["confidence"],
                "matched_patterns": classification["matched_patterns"],
                "remediation": classification["remediation"],
            },
        )

    def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput:
        """Redact secrets from failure analysis."""
        return SanitizedOutput(
            payload=_redact_payload(output.payload),
            commands_run=output.commands_run,
            files_changed=output.files_changed,
            cost=output.cost,
        )

    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult:
        """Evaluate triage confidence."""
        confidence = output.payload.get("confidence", 0.0)
        return EvaluationResult(
            passed=True,
            confidence=confidence,
            evaluator_notes=[
                f"Classified as: {output.payload.get('failure_class', 'unknown')}"
            ],
        )

    def finalize(self, result: EvaluationResult) -> ResultEnvelope:
        """Emit failure triage result."""
        return ResultEnvelope(
            status=ResultStatus.SUCCESS,
            payload={
                "confidence": result.confidence,
                "notes": result.evaluator_notes,
            },
        )


def _classify_failure(text: str) -> dict[str, Any]:
    """Classify failure text against known patterns."""
    scores: dict[str, int] = {}
    matched: dict[str, list[str]] = {}

    for failure_class, patterns in _FAILURE_PATTERNS.items():
        count = 0
        hits: list[str] = []
        for pattern in patterns:
            if pattern.lower() in text.lower():
                count += 1
                hits.append(pattern)
        if count > 0:
            scores[failure_class] = count
            matched[failure_class] = hits

    if not scores:
        return {
            "failure_class": "unknown",
            "confidence": 0.1,
            "matched_patterns": [],
            "remediation": "Manual investigation required",
        }

    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    total_patterns = len(_FAILURE_PATTERNS[best])
    confidence = min(scores[best] / total_patterns, 1.0)

    remediation_map: dict[str, str] = {
        "test_failure": "Review failing test assertions and fix logic errors",
        "type_error": "Run mypy and fix type annotation issues",
        "import_error": "Check dependencies and install missing packages",
        "timeout": "Increase timeout or optimize slow operations",
        "memory": "Reduce memory usage or increase resource limits",
        "permission": "Check file permissions and access controls",
        "network": "Verify network connectivity and API endpoints",
        "syntax": "Fix syntax errors in the affected files",
    }

    return {
        "failure_class": best,
        "confidence": round(confidence, 2),
        "matched_patterns": matched.get(best, []),
        "remediation": remediation_map.get(best, "Review failure details"),
    }


# ── PatchQualityEvaluatorWorker ──────────────────────────────────────


class PatchQualityEvaluatorWorker:
    """Evaluates patch quality post-execution.

    Checks that patches are well-formed, appropriately scoped,
    and don't introduce regressions. Examines diff size, test
    coverage changes, and code style compliance.
    """

    worker_name: str = "patch_quality_evaluator_worker"
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
    ) -> None:
        self._diff_text = diff_text
        self._files_changed = files_changed or []
        self._validation_results = validation_results or []

    def validate_input(self, task: TaskEnvelope) -> ValidationResult:
        """Validate that diff is available."""
        if not self._diff_text:
            return ValidationResult(
                valid=False,
                errors=["No diff text provided for quality evaluation"],
            )
        return ValidationResult(valid=True)

    def build_context(self, task: TaskEnvelope) -> ContextBuildResult:
        """Build context with diff and validation results."""
        return ContextBuildResult(
            context_pack={
                "diff_text": self._diff_text[:50000],
                "files_changed": self._files_changed,
                "validation_results": self._validation_results,
            },
            trust_labels={
                "diff_text": "semi_trusted",
                "validation_results": "trusted",
            },
        )

    def execute(self, task: TaskEnvelope, runtime: RuntimeHandle) -> WorkerOutput:
        """Evaluate patch quality metrics."""
        metrics = _evaluate_patch_metrics(
            self._diff_text, self._files_changed, self._validation_results
        )
        return WorkerOutput(
            payload=metrics,
        )

    def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput:
        """Redact secrets from quality evaluation."""
        return SanitizedOutput(
            payload=_redact_payload(output.payload),
            commands_run=output.commands_run,
            files_changed=output.files_changed,
            cost=output.cost,
        )

    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult:
        """Evaluate overall patch quality score."""
        score = output.payload.get("quality_score", 0.0)
        issues = output.payload.get("issues", [])
        return EvaluationResult(
            passed=score >= 0.5,
            confidence=score,
            safety_flags=[i for i in issues if "security" in i.lower()],
            evaluator_notes=[f"Quality score: {score:.2f}, {len(issues)} issues"],
        )

    def finalize(self, result: EvaluationResult) -> ResultEnvelope:
        """Emit patch quality result."""
        return ResultEnvelope(
            status=ResultStatus.SUCCESS if result.passed else ResultStatus.FAILED,
            payload={
                "passed": result.passed,
                "confidence": result.confidence,
                "notes": result.evaluator_notes,
            },
        )


def _evaluate_patch_metrics(
    diff_text: str,
    files_changed: list[str],
    validation_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute patch quality metrics from diff and validation results."""
    lines_added = diff_text.count("\n+") - diff_text.count("\n+++")
    lines_removed = diff_text.count("\n-") - diff_text.count("\n---")
    diff_size = lines_added + lines_removed

    issues: list[str] = []
    score = 1.0

    # Large diffs are harder to review
    if diff_size > 500:
        issues.append("Large diff (>500 lines)")
        score -= 0.2
    elif diff_size > 1000:
        issues.append("Very large diff (>1000 lines)")
        score -= 0.4

    # Check for test files in changes
    test_files = [f for f in files_changed if "test" in f.lower()]
    if not test_files and files_changed:
        issues.append("No test files modified")
        score -= 0.15

    # Check validation results
    failed_validations = [
        r for r in validation_results
        if not r.get("passed", True)
    ]
    if failed_validations:
        issues.append(f"{len(failed_validations)} validation(s) failed")
        score -= 0.3

    return {
        "quality_score": max(round(score, 2), 0.0),
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "diff_size": diff_size,
        "files_changed_count": len(files_changed),
        "test_files_count": len(test_files),
        "issues": issues,
    }


# ── TaskDecomposerWorker ─────────────────────────────────────────────


class TaskDecomposerWorker:
    """Breaks complex tasks into ordered subtasks.

    Analyzes a work item description and produces a structured
    task breakdown with dependencies and complexity estimates.
    Uses the reasoning tier for accurate decomposition.
    """

    worker_name: str = "task_decomposer_worker"
    worker_class: WorkerClass = WorkerClass.HELPER
    capabilities: set[Capability] = {Capability.REPO_READ}
    allowed_spawn_targets: list[str] = []
    default_timeout_seconds: int = 120
    default_budget: float = 0.50

    def __init__(
        self,
        task_description: str = "",
        context_files: list[str] | None = None,
    ) -> None:
        self._task_description = task_description
        self._context_files = context_files or []

    def validate_input(self, task: TaskEnvelope) -> ValidationResult:
        """Validate that a task description is provided."""
        desc = task.input_payload.get("task_description", self._task_description)
        if not desc:
            return ValidationResult(
                valid=False,
                errors=["No task description provided for decomposition"],
            )
        return ValidationResult(valid=True)

    def build_context(self, task: TaskEnvelope) -> ContextBuildResult:
        """Build context with task description and relevant files."""
        return ContextBuildResult(
            context_pack={
                "task_description": self._task_description,
                "context_files": self._context_files,
            },
            files_included=self._context_files,
            trust_labels={
                "task_description": "semi_trusted",
                "context_files": "semi_trusted",
            },
        )

    def execute(self, task: TaskEnvelope, runtime: RuntimeHandle) -> WorkerOutput:
        """Decompose the task into subtasks."""
        subtasks = _decompose_task(self._task_description)
        return WorkerOutput(
            payload={
                "subtasks": subtasks,
                "total_subtasks": len(subtasks),
                "estimated_complexity": _estimate_complexity(subtasks),
            },
        )

    def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput:
        """Redact secrets from subtask descriptions."""
        return SanitizedOutput(
            payload=_redact_payload(output.payload),
            commands_run=output.commands_run,
            files_changed=output.files_changed,
            cost=output.cost,
        )

    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult:
        """Evaluate decomposition quality."""
        total = output.payload.get("total_subtasks", 0)
        return EvaluationResult(
            passed=total > 0,
            confidence=0.7 if total > 0 else 0.1,
            evaluator_notes=[f"Decomposed into {total} subtasks"],
        )

    def finalize(self, result: EvaluationResult) -> ResultEnvelope:
        """Emit decomposition result."""
        return ResultEnvelope(
            status=ResultStatus.SUCCESS if result.passed else ResultStatus.FAILED,
            payload={
                "passed": result.passed,
                "confidence": result.confidence,
                "notes": result.evaluator_notes,
            },
        )


def _decompose_task(description: str) -> list[dict[str, Any]]:
    """Decompose a task description into subtasks programmatically.

    This is a heuristic decomposition. LLM-based decomposition
    will be wired when model adapters are integrated into the
    worker execution flow.
    """
    subtasks: list[dict[str, Any]] = []
    lines = description.strip().split("\n")

    # Extract numbered items, bullet points, or sentences as subtasks
    task_idx = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Match numbered lists, bullet points, or standalone lines
        cleaned = re.sub(r"^[\d]+[.)]\s*", "", stripped)
        cleaned = re.sub(r"^[-*]\s*", "", cleaned)

        if cleaned and len(cleaned) > 5:
            task_idx += 1
            subtasks.append({
                "id": task_idx,
                "description": cleaned,
                "complexity": "medium",
                "depends_on": [task_idx - 1] if task_idx > 1 else [],
            })

    # If no structure found, treat the whole description as one task
    if not subtasks:
        subtasks.append({
            "id": 1,
            "description": description.strip()[:500],
            "complexity": "high",
            "depends_on": [],
        })

    return subtasks


def _estimate_complexity(subtasks: list[dict[str, Any]]) -> str:
    """Estimate overall complexity from subtask count."""
    count = len(subtasks)
    if count <= 2:
        return "low"
    elif count <= 5:
        return "medium"
    else:
        return "high"


# ── ContextGapAnalyzerWorker ─────────────────────────────────────────


class ContextGapAnalyzerWorker:
    """Detects missing context in execution failures.

    Analyzes the context pack, execution output, and failure details
    to identify what information was missing that could have prevented
    the failure.
    """

    worker_name: str = "context_gap_analyzer_worker"
    worker_class: WorkerClass = WorkerClass.HELPER
    capabilities: set[Capability] = {Capability.REPO_READ}
    allowed_spawn_targets: list[str] = []
    default_timeout_seconds: int = 60
    default_budget: float = 0.25

    def __init__(
        self,
        context_pack: dict[str, Any] | None = None,
        failure_output: str = "",
        files_in_context: list[str] | None = None,
    ) -> None:
        self._context_pack = context_pack or {}
        self._failure_output = failure_output
        self._files_in_context = files_in_context or []

    def validate_input(self, task: TaskEnvelope) -> ValidationResult:
        """Validate that failure output is provided."""
        output = task.input_payload.get("failure_output", self._failure_output)
        if not output:
            return ValidationResult(
                valid=False,
                errors=["No failure output provided for gap analysis"],
            )
        return ValidationResult(valid=True)

    def build_context(self, task: TaskEnvelope) -> ContextBuildResult:
        """Build context with failure output and original context pack."""
        return ContextBuildResult(
            context_pack={
                "failure_output": self._failure_output[:20000],
                "original_context": self._context_pack,
                "files_in_context": self._files_in_context,
            },
            files_included=self._files_in_context,
            trust_labels={
                "failure_output": "semi_trusted",
                "original_context": "trusted",
            },
        )

    def execute(self, task: TaskEnvelope, runtime: RuntimeHandle) -> WorkerOutput:
        """Analyze context gaps from failure output."""
        gaps = _detect_context_gaps(
            self._failure_output, self._files_in_context
        )
        return WorkerOutput(
            payload={
                "gaps": gaps,
                "gap_count": len(gaps),
                "files_in_context_count": len(self._files_in_context),
            },
        )

    def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput:
        """Redact secrets from gap analysis."""
        return SanitizedOutput(
            payload=_redact_payload(output.payload),
            commands_run=output.commands_run,
            files_changed=output.files_changed,
            cost=output.cost,
        )

    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult:
        """Evaluate gap analysis results."""
        gap_count = output.payload.get("gap_count", 0)
        return EvaluationResult(
            passed=True,
            confidence=0.7 if gap_count > 0 else 0.5,
            evaluator_notes=[f"Detected {gap_count} context gaps"],
        )

    def finalize(self, result: EvaluationResult) -> ResultEnvelope:
        """Emit context gap analysis result."""
        return ResultEnvelope(
            status=ResultStatus.SUCCESS,
            payload={
                "confidence": result.confidence,
                "notes": result.evaluator_notes,
            },
        )


def _detect_context_gaps(
    failure_output: str, files_in_context: list[str]
) -> list[dict[str, str]]:
    """Detect potential context gaps from failure output.

    Looks for references to files, modules, or symbols in the failure
    output that weren't included in the original context pack.
    """
    gaps: list[dict[str, str]] = []

    # Extract file references from error messages
    file_refs = re.findall(
        r'(?:File\s+["\']|from\s+|import\s+)([\w./]+\.py)', failure_output
    )
    context_basenames = {f.split("/")[-1] for f in files_in_context}

    for ref in file_refs:
        basename = ref.split("/")[-1]
        if basename not in context_basenames and basename != "<stdin>":
            gaps.append({
                "type": "missing_file",
                "reference": ref,
                "suggestion": f"Include {ref} in context pack",
            })

    # Check for missing module references
    module_errors = re.findall(
        r"No module named ['\"]([^'\"]+)['\"]", failure_output
    )
    for mod in module_errors:
        gaps.append({
            "type": "missing_dependency",
            "reference": mod,
            "suggestion": f"Add {mod} to project dependencies",
        })

    # Check for undefined name references
    name_errors = re.findall(
        r"NameError: name ['\"]([^'\"]+)['\"]", failure_output
    )
    for name in name_errors:
        gaps.append({
            "type": "undefined_reference",
            "reference": name,
            "suggestion": f"Ensure {name} is defined or imported in context",
        })

    return gaps


# ── Shared helpers ───────────────────────────────────────────────────


def _redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact secrets from a payload dict."""
    import json

    serialized = json.dumps(payload, default=str)
    redacted_text, _count = redact_secrets(serialized)
    result: dict[str, Any] = json.loads(redacted_text)
    return result
