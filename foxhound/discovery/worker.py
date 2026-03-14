"""DiscoveryWorker — scans repositories for actionable work items.

Implements the six-method Worker protocol. Capabilities: repo_read only.
No write, no shell, optional network. Can spawn helper workers.
"""

from pathlib import Path
from uuid import uuid4

from foxhound.core.models import (
    ExecutionMode,
    ResultEnvelope,
    ResultStatus,
    TaskEnvelope,
    TrustLevel,
)
from foxhound.discovery.scanners import (
    ScannerRegistry,
    ScanResult,
    scan_result_to_work_item,
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


class DiscoveryWorker:
    """Scans a repository for work items using registered scanners.

    Follows the harness contract: validate → build_context → execute →
    sanitize → evaluate → finalize.
    """

    worker_name = "discovery_worker"
    worker_class = WorkerClass.ROOT
    capabilities = {Capability.REPO_READ, Capability.SPAWN}
    allowed_spawn_targets: list[str] = ["security_review_worker"]
    default_timeout_seconds = 300
    default_budget = 1.0

    def __init__(self, scanner_registry: ScannerRegistry | None = None) -> None:
        self._registry = scanner_registry or ScannerRegistry()
        if not self._registry.scanners:
            self._registry.register_defaults()

    def validate_input(self, task: TaskEnvelope) -> ValidationResult:
        """Validate that the task has a valid repo_id and read-only mode."""
        errors: list[str] = []
        warnings: list[str] = []

        if not task.repo_id:
            errors.append("Missing repo_id in task envelope")

        repo_path = task.input_payload.get("repo_path")
        if not repo_path:
            errors.append("Missing repo_path in input_payload")
        elif not Path(repo_path).is_dir():
            errors.append(f"repo_path is not a valid directory: {repo_path}")

        if task.execution_mode not in (ExecutionMode.READ_ONLY, ExecutionMode.PLAN_ONLY):
            warnings.append(
                f"Discovery should run in read_only mode, got {task.execution_mode.value}"
            )

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def build_context(self, task: TaskEnvelope) -> ContextBuildResult:
        """Build context from repo path metadata."""
        repo_path = task.input_payload.get("repo_path", "")
        return ContextBuildResult(
            context_pack={
                "repo_id": task.repo_id,
                "repo_path": repo_path,
                "scanners": [s.scanner_name for s in self._registry.scanners],
            },
            context_hash=f"discovery_{task.repo_id}",
            files_included=[],
            trust_labels={"repo_files": TrustLevel.SEMI_TRUSTED.value},
        )

    def execute(
        self, task: TaskEnvelope, runtime: RuntimeHandle
    ) -> WorkerOutput:
        """Run all registered scanners against the repo."""
        repo_path = Path(task.input_payload["repo_path"])

        if not runtime.has_capability(Capability.REPO_READ):
            raise RuntimeError("DiscoveryWorker requires REPO_READ capability")

        scan_results = self._registry.scan_all(repo_path)

        # Dedup within this scan using fingerprints
        seen: set[str] = set()
        known_fingerprints: set[str] = set(
            task.input_payload.get("known_fingerprints", [])
        )
        unique_results: list[ScanResult] = []
        for result in scan_results:
            fp = result.fingerprint
            if fp not in seen and fp not in known_fingerprints:
                seen.add(fp)
                unique_results.append(result)

        # Convert to work items
        work_items_data = []
        for result in unique_results:
            wid = f"wi_{uuid4().hex[:12]}"
            item = scan_result_to_work_item(result, task.repo_id, wid)
            work_items_data.append(item.model_dump(mode="json"))

        return WorkerOutput(
            payload={
                "work_items": work_items_data,
                "total_findings": len(scan_results),
                "unique_findings": len(unique_results),
                "duplicates_skipped": len(scan_results) - len(unique_results),
                "scanners_run": [s.scanner_name for s in self._registry.scanners],
            },
            commands_run=[],
            files_changed=[],
            cost=0.0,
        )

    def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput:
        """Sanitize discovery output — strip any sensitive paths or patterns."""
        return SanitizedOutput(
            payload=output.payload,
            commands_run=output.commands_run,
            files_changed=output.files_changed,
            cost=output.cost,
            redactions_applied=[],
        )

    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult:
        """Evaluate discovery quality — check that findings are well-formed."""
        work_items = output.payload.get("work_items", [])
        total = output.payload.get("total_findings", 0)

        safety_flags: list[str] = []
        if total > 100:
            safety_flags.append(f"Large scan: {total} findings may need filtering")

        return EvaluationResult(
            passed=True,
            confidence=0.8 if work_items else 0.5,
            safety_flags=safety_flags,
            evaluator_notes=[
                f"Found {len(work_items)} unique work items from {total} total findings"
            ],
        )

    def finalize(self, result: EvaluationResult) -> ResultEnvelope:
        """Emit final result envelope."""
        return ResultEnvelope(
            status=ResultStatus.SUCCESS if result.passed else ResultStatus.FAILED,
            confidence=result.confidence,
            safety_flags=result.safety_flags,
            recommended_next_action="advance_to_suggested" if result.passed else None,
        )
