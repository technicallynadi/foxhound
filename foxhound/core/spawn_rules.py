"""Spawn authorization rules for worker-to-worker spawning.

Enforces security constraints on which workers can spawn which helpers,
prevents privilege escalation, and blocks dangerous spawn patterns.
"""

from foxhound.core.models import JobType
from foxhound.harness.worker_protocol import Capability

SPAWN_ALLOWED_TARGETS: dict[str, set[str]] = {
    "scout_worker": {"evidence_validator"},
    "discovery_worker": {"evidence_validator", "context_gap_analyzer"},
    "execution_worker": {
        "patch_quality_evaluator",
        "task_decomposer",
        "context_gap_analyzer",
        "security_review_worker",
    },
    "analyzer_worker": {"rule_validator"},
}

WORKER_CAPABILITIES: dict[str, set[Capability]] = {
    "scout_worker": {Capability.NETWORK, Capability.SPAWN},
    "discovery_worker": {Capability.REPO_READ, Capability.SPAWN},
    "execution_worker": {
        Capability.REPO_READ,
        Capability.REPO_WRITE,
        Capability.NETWORK,
        Capability.SHELL,
        Capability.SPAWN,
    },
    "analyzer_worker": {Capability.REPO_READ, Capability.SPAWN},
    "security_review_worker": {Capability.REPO_READ},
    "evidence_validator": {Capability.NETWORK},
    "context_gap_analyzer": {Capability.REPO_READ},
    "patch_quality_evaluator": {Capability.REPO_READ},
    "task_decomposer": {Capability.REPO_READ},
    "rule_validator": {Capability.REPO_READ},
}


class SpawnViolation:
    """A spawn rule violation."""

    def __init__(self, rule: str, reason: str) -> None:
        self.rule = rule
        self.reason = reason

    def __repr__(self) -> str:
        return f"SpawnViolation(rule={self.rule!r}, reason={self.reason!r})"


def validate_spawn(
    parent_worker_type: str,
    child_worker_type: str,
    parent_job_type: JobType,
    child_job_type: JobType,
) -> list[SpawnViolation]:
    """Validate a spawn request against security rules.

    Returns:
        List of violations. Empty if spawn is allowed.
    """
    violations: list[SpawnViolation] = []

    if parent_worker_type == child_worker_type:
        violations.append(SpawnViolation(
            "no_self_spawn",
            f"Worker '{parent_worker_type}' cannot spawn itself",
        ))

    if parent_worker_type == "scout_worker" and child_job_type == JobType.EXECUTION:
        violations.append(SpawnViolation(
            "scout_no_execution",
            "Scout workers cannot spawn execution workers",
        ))

    allowed = SPAWN_ALLOWED_TARGETS.get(parent_worker_type)
    if allowed is not None and child_worker_type not in allowed:
        violations.append(SpawnViolation(
            "target_not_allowed",
            f"Worker '{parent_worker_type}' cannot spawn '{child_worker_type}'. "
            f"Allowed: {sorted(allowed)}",
        ))

    parent_caps = WORKER_CAPABILITIES.get(parent_worker_type, set())
    child_caps = WORKER_CAPABILITIES.get(child_worker_type, set())
    escalated = child_caps - parent_caps
    if escalated:
        violations.append(SpawnViolation(
            "privilege_escalation",
            f"Child '{child_worker_type}' would gain capabilities "
            f"not held by parent '{parent_worker_type}': "
            f"{sorted(c.value for c in escalated)}",
        ))

    return violations
