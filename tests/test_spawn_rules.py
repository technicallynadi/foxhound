"""Tests for spawn authorization rules."""


from foxhound.core.models import JobType
from foxhound.core.spawn_rules import validate_spawn


class TestSelfSpawning:
    def test_no_self_spawn(self) -> None:
        violations = validate_spawn(
            "scout_worker", "scout_worker",
            JobType.SCOUT, JobType.SCOUT,
        )
        assert any(v.rule == "no_self_spawn" for v in violations)

    def test_different_workers_allowed(self) -> None:
        violations = validate_spawn(
            "execution_worker", "security_review_worker",
            JobType.EXECUTION, JobType.EXECUTION,
        )
        self_spawn = [v for v in violations if v.rule == "no_self_spawn"]
        assert len(self_spawn) == 0


class TestScoutRestrictions:
    def test_scout_cannot_spawn_execution(self) -> None:
        violations = validate_spawn(
            "scout_worker", "execution_worker",
            JobType.SCOUT, JobType.EXECUTION,
        )
        assert any(v.rule == "scout_no_execution" for v in violations)

    def test_scout_can_spawn_evidence_validator(self) -> None:
        violations = validate_spawn(
            "scout_worker", "evidence_validator",
            JobType.SCOUT, JobType.SCOUT,
        )
        assert not any(v.rule == "target_not_allowed" for v in violations)


class TestAllowedTargets:
    def test_execution_can_spawn_security_review(self) -> None:
        violations = validate_spawn(
            "execution_worker", "security_review_worker",
            JobType.EXECUTION, JobType.EXECUTION,
        )
        target_violations = [v for v in violations if v.rule == "target_not_allowed"]
        assert len(target_violations) == 0

    def test_execution_cannot_spawn_scout(self) -> None:
        violations = validate_spawn(
            "execution_worker", "scout_worker",
            JobType.EXECUTION, JobType.SCOUT,
        )
        assert any(v.rule == "target_not_allowed" for v in violations)

    def test_discovery_can_spawn_evidence_validator(self) -> None:
        violations = validate_spawn(
            "discovery_worker", "evidence_validator",
            JobType.DISCOVERY, JobType.DISCOVERY,
        )
        target_violations = [v for v in violations if v.rule == "target_not_allowed"]
        assert len(target_violations) == 0

    def test_analyzer_can_spawn_rule_validator(self) -> None:
        violations = validate_spawn(
            "analyzer_worker", "rule_validator",
            JobType.ANALYZER, JobType.ANALYZER,
        )
        target_violations = [v for v in violations if v.rule == "target_not_allowed"]
        assert len(target_violations) == 0


class TestPrivilegeEscalation:
    def test_scout_spawning_execution_escalates(self) -> None:
        violations = validate_spawn(
            "scout_worker", "execution_worker",
            JobType.SCOUT, JobType.EXECUTION,
        )
        assert any(v.rule == "privilege_escalation" for v in violations)

    def test_discovery_spawning_evidence_validator_escalates_network(self) -> None:
        violations = validate_spawn(
            "discovery_worker", "evidence_validator",
            JobType.DISCOVERY, JobType.DISCOVERY,
        )
        # evidence_validator has NETWORK which discovery_worker doesn't
        assert any(v.rule == "privilege_escalation" for v in violations)


class TestUnknownWorkers:
    def test_unknown_parent_no_target_violation(self) -> None:
        violations = validate_spawn(
            "custom_worker", "evidence_validator",
            JobType.EXECUTION, JobType.EXECUTION,
        )
        target_violations = [v for v in violations if v.rule == "target_not_allowed"]
        assert len(target_violations) == 0
