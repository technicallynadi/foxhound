"""Deterministic rules engine for evaluating condition-action logic."""

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RuleType(StrEnum):
    """Rule classification determining enforcement behavior."""

    HARD = "hard"
    SOFT = "soft"
    ADVISORY = "advisory"


class RuleOutcome(StrEnum):
    """Result of rule evaluation."""

    PASS = "pass"
    BLOCK = "block"
    REROUTE = "reroute"
    REQUIRE_APPROVAL = "require_approval"
    ADVISORY = "advisory"


class RuleCheckpoint(StrEnum):
    """Evaluation checkpoints where rules are applied."""

    DISCOVERY = "discovery"
    PRE_EXECUTION = "pre_execution"
    PRE_PROMOTION = "pre_promotion"


class RuleSuggestionState(StrEnum):
    """State machine for analyzer-proposed rule suggestions."""

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVATED = "activated"


class Rule(BaseModel):
    """A single deterministic rule with condition-action logic."""

    rule_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    rule_type: RuleType
    checkpoint: RuleCheckpoint
    condition: str = Field(..., description="Human-readable condition description")
    action: str = Field(..., description="Action to take when condition matches")
    description: str = Field(default="")
    enabled: bool = Field(default=True)
    priority: int = Field(default=100, ge=0)


class RuleEvaluationResult(BaseModel):
    """Result of evaluating a single rule against context."""

    rule: Rule
    outcome: RuleOutcome
    matched: bool
    details: str = Field(default="")


class RuleSetResult(BaseModel):
    """Result of evaluating all rules at a checkpoint."""

    checkpoint: RuleCheckpoint
    results: list[RuleEvaluationResult] = Field(default_factory=list)
    blocked: bool = Field(default=False)
    requires_approval: bool = Field(default=False)
    rerouted: bool = Field(default=False)
    advisory_notes: list[str] = Field(default_factory=list)


class RuleSuggestion(BaseModel):
    """Analyzer-proposed rule requiring human approval before activation."""

    suggestion_id: str = Field(default_factory=lambda: f"rs_{uuid.uuid4().hex[:12]}")
    repo_id: str | None = Field(default=None)
    rule_name: str
    rule_type: RuleType
    condition: str
    action: str
    evidence: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    state: RuleSuggestionState = Field(default=RuleSuggestionState.PENDING_REVIEW)
    suggested_by: str = Field(default="analyzer")


def _default_hard_rules() -> list[Rule]:
    """Built-in hard rules that cannot be bypassed."""
    return [
        Rule(
            rule_id="hard_no_env_files",
            name="block_env_files",
            rule_type=RuleType.HARD,
            checkpoint=RuleCheckpoint.PRE_EXECUTION,
            condition="Context pack or output references .env files",
            action="Block execution and emit policy violation",
            description="Never read or write .env files",
            priority=10,
        ),
        Rule(
            rule_id="hard_no_install_scripts",
            name="block_install_scripts",
            rule_type=RuleType.HARD,
            checkpoint=RuleCheckpoint.PRE_EXECUTION,
            condition="Command is an install script (pip install, npm install, etc.)",
            action="Block command and emit policy violation",
            description="Block install scripts without explicit approval",
            priority=10,
        ),
        Rule(
            rule_id="hard_max_retries",
            name="enforce_max_retries",
            rule_type=RuleType.HARD,
            checkpoint=RuleCheckpoint.PRE_EXECUTION,
            condition="Retry count exceeds recipe max_retries setting",
            action="Block execution and mark run as failed",
            description="Stop execution after max retries exceeded",
            priority=20,
        ),
        Rule(
            rule_id="hard_no_secret_leak",
            name="block_secret_in_output",
            rule_type=RuleType.HARD,
            checkpoint=RuleCheckpoint.PRE_PROMOTION,
            condition="Output contains potential secret patterns",
            action="Block promotion and quarantine output",
            description="Secrets must never appear in outputs",
            priority=5,
        ),
    ]


def _default_soft_rules() -> list[Rule]:
    """Built-in soft rules that may reroute or request approval."""
    return [
        Rule(
            rule_id="soft_escalate_model_tier",
            name="escalate_on_failure",
            rule_type=RuleType.SOFT,
            checkpoint=RuleCheckpoint.PRE_EXECUTION,
            condition="Previous attempt failed with a retriable error class",
            action="Escalate to next higher model tier for retry",
            description="Escalate to stronger model after failure",
            priority=50,
        ),
        Rule(
            rule_id="soft_approval_high_risk",
            name="require_approval_high_risk",
            rule_type=RuleType.SOFT,
            checkpoint=RuleCheckpoint.PRE_EXECUTION,
            condition="Work item has risk level 'high'",
            action="Require explicit approval before execution",
            description="High-risk items need approval",
            priority=30,
        ),
    ]


def _default_advisory_rules() -> list[Rule]:
    """Built-in advisory rules recorded for analysis only."""
    return [
        Rule(
            rule_id="advisory_missing_tests",
            name="suggest_test_coverage",
            rule_type=RuleType.ADVISORY,
            checkpoint=RuleCheckpoint.PRE_PROMOTION,
            condition="Changed files have no corresponding test files",
            action="Log advisory note recommending test coverage",
            description="Recommend adding tests for changed code",
            priority=100,
        ),
        Rule(
            rule_id="advisory_large_diff",
            name="flag_large_diff",
            rule_type=RuleType.ADVISORY,
            checkpoint=RuleCheckpoint.PRE_PROMOTION,
            condition="Diff exceeds 500 lines of changes",
            action="Log advisory note about large change size",
            description="Flag unusually large diffs for review attention",
            priority=100,
        ),
    ]


class RulesEngine:
    """Evaluates deterministic rules at defined checkpoints.

    Rules come in three types:
    - Hard: Cannot be bypassed, block immediately
    - Soft: May reroute or request approval
    - Advisory: Recorded for analysis only, never block
    """

    def __init__(self) -> None:
        self._rules: list[Rule] = []
        self._load_defaults()

    def _load_defaults(self) -> None:
        """Load built-in default rules."""
        self._rules = (
            _default_hard_rules()
            + _default_soft_rules()
            + _default_advisory_rules()
        )

    @property
    def rules(self) -> list[Rule]:
        """Get all registered rules."""
        return list(self._rules)

    def add_rule(self, rule: Rule) -> None:
        """Register a new rule."""
        self._rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID."""
        original_len = len(self._rules)
        self._rules = [r for r in self._rules if r.rule_id != rule_id]
        return len(self._rules) < original_len

    def get_rules_for_checkpoint(self, checkpoint: RuleCheckpoint) -> list[Rule]:
        """Get all enabled rules for a specific checkpoint, sorted by priority."""
        return sorted(
            [r for r in self._rules if r.checkpoint == checkpoint and r.enabled],
            key=lambda r: r.priority,
        )

    def evaluate(
        self,
        checkpoint: RuleCheckpoint,
        context: dict[str, Any],
    ) -> RuleSetResult:
        """Evaluate all rules at a checkpoint against the given context.

        The context dictionary should contain relevant execution state:
        - paths: list of file paths being accessed
        - command: command being executed
        - retry_count: current retry count
        - max_retries: maximum retries allowed
        - risk_level: work item risk level
        - diff_lines: number of changed lines
        - has_tests: whether test files exist for changed files

        Args:
            checkpoint: The checkpoint being evaluated.
            context: Execution context for condition matching.

        Returns:
            RuleSetResult with all evaluation outcomes.
        """
        rules = self.get_rules_for_checkpoint(checkpoint)
        result = RuleSetResult(checkpoint=checkpoint)

        for rule in rules:
            eval_result = self._evaluate_rule(rule, context)
            result.results.append(eval_result)

            if not eval_result.matched:
                continue

            if eval_result.outcome == RuleOutcome.BLOCK:
                result.blocked = True
            elif eval_result.outcome == RuleOutcome.REQUIRE_APPROVAL:
                result.requires_approval = True
            elif eval_result.outcome == RuleOutcome.REROUTE:
                result.rerouted = True
            elif eval_result.outcome == RuleOutcome.ADVISORY:
                result.advisory_notes.append(
                    f"[{rule.name}] {eval_result.details}"
                )

        return result

    def _evaluate_rule(
        self,
        rule: Rule,
        context: dict[str, Any],
    ) -> RuleEvaluationResult:
        """Evaluate a single rule against context."""
        matched = False
        details = ""
        outcome = RuleOutcome.PASS

        if rule.rule_id == "hard_no_env_files":
            paths = context.get("paths", [])
            env_files = [p for p in paths if _is_env_file(p)]
            if env_files:
                matched = True
                details = f"Blocked .env files: {env_files}"
                outcome = RuleOutcome.BLOCK

        elif rule.rule_id == "hard_no_install_scripts":
            command = context.get("command", "")
            if _is_install_command(command):
                matched = True
                details = f"Blocked install command: {command}"
                outcome = RuleOutcome.BLOCK

        elif rule.rule_id == "hard_max_retries":
            retry_count = context.get("retry_count", 0)
            max_retries = context.get("max_retries", 2)
            if retry_count > max_retries:
                matched = True
                details = f"Retry count {retry_count} exceeds max {max_retries}"
                outcome = RuleOutcome.BLOCK

        elif rule.rule_id == "hard_no_secret_leak":
            has_secrets = context.get("has_secret_patterns", False)
            if has_secrets:
                matched = True
                details = "Output contains potential secret patterns"
                outcome = RuleOutcome.BLOCK

        elif rule.rule_id == "soft_escalate_model_tier":
            previous_failed = context.get("previous_attempt_failed", False)
            retriable = context.get("retriable_error", False)
            if previous_failed and retriable:
                matched = True
                details = "Escalating model tier after retriable failure"
                outcome = RuleOutcome.REROUTE

        elif rule.rule_id == "soft_approval_high_risk":
            risk_level = context.get("risk_level", "low")
            if risk_level == "high":
                matched = True
                details = "High-risk work item requires approval"
                outcome = RuleOutcome.REQUIRE_APPROVAL

        elif rule.rule_id == "advisory_missing_tests":
            has_tests = context.get("has_tests", True)
            if not has_tests:
                matched = True
                details = "Changed files have no corresponding test coverage"
                outcome = RuleOutcome.ADVISORY

        elif rule.rule_id == "advisory_large_diff":
            diff_lines = context.get("diff_lines", 0)
            if diff_lines > 500:
                matched = True
                details = f"Large diff: {diff_lines} lines changed"
                outcome = RuleOutcome.ADVISORY

        return RuleEvaluationResult(
            rule=rule,
            outcome=outcome,
            matched=matched,
            details=details,
        )

    def create_suggestion(
        self,
        rule_name: str,
        rule_type: RuleType,
        condition: str,
        action: str,
        evidence: str = "",
        confidence: float = 0.0,
        repo_id: str | None = None,
    ) -> RuleSuggestion:
        """Create a rule suggestion for human review.

        In v1, analyzer-proposed rules must be explicitly approved
        before activation.

        Args:
            rule_name: Proposed rule name.
            rule_type: Proposed rule type.
            condition: Proposed condition.
            action: Proposed action.
            evidence: Supporting evidence.
            confidence: Confidence score.
            repo_id: Associated repository.

        Returns:
            RuleSuggestion in pending_review state.
        """
        return RuleSuggestion(
            rule_name=rule_name,
            rule_type=rule_type,
            condition=condition,
            action=action,
            evidence=evidence,
            confidence=confidence,
            repo_id=repo_id,
        )


def _is_env_file(path: str) -> bool:
    """Check if a path refers to an environment file."""
    from pathlib import PurePosixPath

    name = PurePosixPath(path).name
    return name == ".env" or name.startswith(".env.")


def _is_install_command(command: str) -> bool:
    """Check if a command is an install script."""
    install_prefixes = [
        "pip install",
        "pip3 install",
        "npm install",
        "yarn add",
        "yarn install",
        "apt install",
        "apt-get install",
        "brew install",
    ]
    cmd_lower = command.lower().strip()
    return any(cmd_lower.startswith(prefix) for prefix in install_prefixes)
