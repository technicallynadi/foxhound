"""Worker Protocol defining the contract all workers must implement.

Every worker in Foxhound implements this protocol, ensuring consistent
lifecycle handling across Scout, Discovery, Execution, Analyzer, and
helper workers. The harness enforces that these methods are called in
the correct order.
"""

from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from foxhound.core.models import (
    ExecutionMode,
    ResultEnvelope,
    TaskEnvelope,
)


class WorkerClass(StrEnum):
    """Worker classification."""

    ROOT = "root"
    HELPER = "helper"


class Capability(StrEnum):
    """Declared worker capabilities (permissions)."""

    REPO_READ = "repo_read"
    REPO_WRITE = "repo_write"
    NETWORK = "network"
    SHELL = "shell"
    SPAWN = "spawn"


class ValidationResult(BaseModel):
    """Result of input validation."""

    valid: bool = Field(..., description="Whether the input is valid")
    errors: list[str] = Field(default_factory=list, description="Validation error messages")
    warnings: list[str] = Field(default_factory=list, description="Validation warnings")

    model_config = {"extra": "forbid"}


class ContextBuildResult(BaseModel):
    """Result of context assembly."""

    context_pack: dict[str, Any] = Field(
        default_factory=dict, description="Assembled context data"
    )
    context_hash: str = Field(default="", description="Hash of context pack")
    files_included: list[str] = Field(
        default_factory=list, description="Files included in context"
    )
    trust_labels: dict[str, str] = Field(
        default_factory=dict, description="Trust labels for context sources"
    )

    model_config = {"extra": "forbid"}


class WorkerOutput(BaseModel):
    """Raw output from worker execution before sanitization."""

    payload: dict[str, Any] = Field(
        default_factory=dict, description="Worker-specific raw output"
    )
    commands_run: list[str] = Field(
        default_factory=list, description="Commands that were executed"
    )
    files_changed: list[str] = Field(
        default_factory=list, description="Files that were modified"
    )
    cost: float = Field(default=0.0, ge=0.0, description="Observed execution cost")
    artifact_paths: list[str] = Field(
        default_factory=list, description="Paths to generated artifacts"
    )

    model_config = {"extra": "forbid"}


class SanitizedOutput(BaseModel):
    """Output after sanitization (dangerous patterns stripped)."""

    payload: dict[str, Any] = Field(
        default_factory=dict, description="Sanitized worker output"
    )
    commands_run: list[str] = Field(
        default_factory=list, description="Commands that were executed"
    )
    files_changed: list[str] = Field(
        default_factory=list, description="Files that were modified"
    )
    cost: float = Field(default=0.0, ge=0.0, description="Observed execution cost")
    artifact_paths: list[str] = Field(
        default_factory=list, description="Paths to generated artifacts"
    )
    redactions_applied: list[str] = Field(
        default_factory=list, description="Redaction actions taken"
    )

    model_config = {"extra": "forbid"}


class EvaluationResult(BaseModel):
    """Result of output evaluation (quality and security checks)."""

    passed: bool = Field(..., description="Whether evaluation passed")
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Confidence score"
    )
    safety_flags: list[str] = Field(
        default_factory=list, description="Security or trust warnings"
    )
    evaluator_notes: list[str] = Field(
        default_factory=list, description="Evaluator observations"
    )
    recommended_next_action: str | None = Field(
        default=None, description="Suggested follow-up action"
    )

    model_config = {"extra": "forbid"}


class RuntimeHandle:
    """Handle provided by the harness for worker execution.

    Workers use this handle to access tools, models, and other
    harness-mediated capabilities during execution.
    """

    def __init__(
        self,
        *,
        execution_mode: ExecutionMode,
        capabilities: set[Capability],
        budget_remaining: float,
        timeout_remaining: float,
    ) -> None:
        self.execution_mode = execution_mode
        self.capabilities = capabilities
        self.budget_remaining = budget_remaining
        self.timeout_remaining = timeout_remaining

    def has_capability(self, cap: Capability) -> bool:
        """Check if a capability is available."""
        return cap in self.capabilities

    def consume_budget(self, amount: float) -> None:
        """Consume budget, raising if insufficient.

        Args:
            amount: Budget amount to consume.

        Raises:
            RuntimeError: If budget would be exceeded.
        """
        if amount > self.budget_remaining:
            raise RuntimeError(
                f"Budget exceeded: requested {amount}, remaining {self.budget_remaining}"
            )
        self.budget_remaining -= amount


@runtime_checkable
class Worker(Protocol):
    """Protocol that all Foxhound workers must implement.

    Workers declare their identity, capabilities, and implement the
    six-method lifecycle contract enforced by the harness.

    Example:
        >>> class MyWorker:
        ...     worker_name = "my_worker"
        ...     worker_class = WorkerClass.HELPER
        ...     capabilities = {Capability.REPO_READ}
        ...     allowed_spawn_targets: list[str] = []
        ...     default_timeout_seconds = 300
        ...     default_budget = 1.0
        ...
        ...     def validate_input(self, task: TaskEnvelope) -> ValidationResult: ...
        ...     def build_context(self, task: TaskEnvelope) -> ContextBuildResult: ...
        ...     def execute(self, task: TaskEnvelope, runtime: RuntimeHandle) -> WorkerOutput: ...
        ...     def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput: ...
        ...     def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult: ...
        ...     def finalize(self, result: EvaluationResult) -> ResultEnvelope: ...
    """

    worker_name: str
    worker_class: WorkerClass
    capabilities: set[Capability]
    allowed_spawn_targets: list[str]
    default_timeout_seconds: int
    default_budget: float

    def validate_input(self, task: TaskEnvelope) -> ValidationResult:
        """Validate task envelope and preflight requirements."""
        ...

    def build_context(self, task: TaskEnvelope) -> ContextBuildResult:
        """Build or load sanitized context pack with trust labels."""
        ...

    def execute(
        self, task: TaskEnvelope, runtime: RuntimeHandle
    ) -> WorkerOutput:
        """Run worker logic with exposed tools and model access."""
        ...

    def sanitize_output(self, output: WorkerOutput) -> SanitizedOutput:
        """Normalize output and strip dangerous patterns."""
        ...

    def evaluate_output(self, output: SanitizedOutput) -> EvaluationResult:
        """Run evaluator/security hooks."""
        ...

    def finalize(self, result: EvaluationResult) -> ResultEnvelope:
        """Emit structured result envelope, events, artifacts."""
        ...
