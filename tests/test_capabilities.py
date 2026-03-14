"""Tests for capabilities matrix enforcement."""

import pytest

from foxhound.core.models import (
    ExecutionMode,
    ExecutionSnapshot,
    ExecutionStrategy,
    PolicyRef,
    RecipeRef,
    ResultEnvelope,
    ResultStatus,
    TaskEnvelope,
)
from foxhound.harness.runtime import Harness, HarnessError
from foxhound.harness.worker_protocol import (
    CAPABILITIES_MATRIX,
    Capability,
    ContextBuildResult,
    EvaluationResult,
    SanitizedOutput,
    ValidationResult,
    WorkerClass,
    WorkerOutput,
    validate_worker_capabilities,
)

# ============================================================================
# validate_worker_capabilities
# ============================================================================


class TestValidateWorkerCapabilities:
    # --- Discovery worker ---

    def test_discovery_worker_valid_caps(self):
        violations = validate_worker_capabilities(
            "discovery_worker", {Capability.REPO_READ, Capability.SPAWN}
        )
        assert violations == []

    def test_discovery_worker_repo_read_only(self):
        violations = validate_worker_capabilities(
            "discovery_worker", {Capability.REPO_READ}
        )
        assert violations == []

    def test_discovery_worker_repo_write_rejected(self):
        violations = validate_worker_capabilities(
            "discovery_worker",
            {Capability.REPO_READ, Capability.REPO_WRITE},
        )
        assert len(violations) == 1
        assert "repo_write" in violations[0]

    def test_discovery_worker_shell_rejected(self):
        violations = validate_worker_capabilities(
            "discovery_worker",
            {Capability.REPO_READ, Capability.SHELL},
        )
        assert len(violations) == 1
        assert "shell" in violations[0]

    def test_discovery_worker_network_rejected(self):
        violations = validate_worker_capabilities(
            "discovery_worker",
            {Capability.REPO_READ, Capability.NETWORK},
        )
        assert len(violations) == 1
        assert "network" in violations[0]

    def test_discovery_worker_multiple_violations(self):
        violations = validate_worker_capabilities(
            "discovery_worker",
            {
                Capability.REPO_READ,
                Capability.REPO_WRITE,
                Capability.SHELL,
                Capability.NETWORK,
            },
        )
        assert len(violations) == 1
        # Single message listing all disallowed
        assert "repo_write" in violations[0]
        assert "shell" in violations[0]
        assert "network" in violations[0]

    # --- Scout worker ---

    def test_scout_worker_valid(self):
        violations = validate_worker_capabilities(
            "scout_worker", {Capability.NETWORK, Capability.SPAWN}
        )
        assert violations == []

    def test_scout_worker_network_only(self):
        violations = validate_worker_capabilities(
            "scout_worker", {Capability.NETWORK}
        )
        assert violations == []

    def test_scout_worker_repo_read_rejected(self):
        violations = validate_worker_capabilities(
            "scout_worker", {Capability.NETWORK, Capability.REPO_READ}
        )
        assert len(violations) == 1
        assert "repo_read" in violations[0]

    def test_scout_worker_repo_write_rejected(self):
        violations = validate_worker_capabilities(
            "scout_worker", {Capability.REPO_WRITE}
        )
        assert len(violations) == 1

    def test_scout_worker_shell_rejected(self):
        violations = validate_worker_capabilities(
            "scout_worker", {Capability.SHELL}
        )
        assert len(violations) == 1

    # --- Execution worker ---

    def test_execution_worker_all_caps_valid(self):
        violations = validate_worker_capabilities(
            "execution_worker",
            {
                Capability.REPO_READ,
                Capability.REPO_WRITE,
                Capability.NETWORK,
                Capability.SHELL,
                Capability.SPAWN,
            },
        )
        assert violations == []

    def test_execution_worker_subset_valid(self):
        violations = validate_worker_capabilities(
            "execution_worker", {Capability.REPO_READ, Capability.REPO_WRITE}
        )
        assert violations == []

    # --- Analyzer worker ---

    def test_analyzer_worker_valid(self):
        violations = validate_worker_capabilities(
            "analyzer_worker", {Capability.REPO_READ, Capability.SPAWN}
        )
        assert violations == []

    def test_analyzer_worker_write_rejected(self):
        violations = validate_worker_capabilities(
            "analyzer_worker",
            {Capability.REPO_READ, Capability.REPO_WRITE},
        )
        assert len(violations) == 1

    def test_analyzer_worker_shell_rejected(self):
        violations = validate_worker_capabilities(
            "analyzer_worker", {Capability.REPO_READ, Capability.SHELL}
        )
        assert len(violations) == 1

    def test_analyzer_worker_network_rejected(self):
        violations = validate_worker_capabilities(
            "analyzer_worker", {Capability.REPO_READ, Capability.NETWORK}
        )
        assert len(violations) == 1

    # --- Security review worker ---

    def test_security_review_worker_read_only(self):
        violations = validate_worker_capabilities(
            "security_review_worker", {Capability.REPO_READ}
        )
        assert violations == []

    def test_security_review_worker_spawn_rejected(self):
        violations = validate_worker_capabilities(
            "security_review_worker",
            {Capability.REPO_READ, Capability.SPAWN},
        )
        assert len(violations) == 1

    def test_security_review_worker_write_rejected(self):
        violations = validate_worker_capabilities(
            "security_review_worker",
            {Capability.REPO_READ, Capability.REPO_WRITE},
        )
        assert len(violations) == 1

    def test_security_review_worker_network_rejected(self):
        violations = validate_worker_capabilities(
            "security_review_worker",
            {Capability.REPO_READ, Capability.NETWORK},
        )
        assert len(violations) == 1

    # --- Unknown worker ---

    def test_unknown_worker_any_caps_allowed(self):
        violations = validate_worker_capabilities(
            "custom_worker",
            {
                Capability.REPO_READ,
                Capability.REPO_WRITE,
                Capability.NETWORK,
                Capability.SHELL,
                Capability.SPAWN,
            },
        )
        assert violations == []

    # --- Edge cases ---

    def test_empty_capabilities_valid(self):
        violations = validate_worker_capabilities("discovery_worker", set())
        assert violations == []

    def test_empty_capabilities_all_workers(self):
        for name in CAPABILITIES_MATRIX:
            violations = validate_worker_capabilities(name, set())
            assert violations == [], f"{name} should accept empty caps"

    def test_violation_message_includes_allowed(self):
        violations = validate_worker_capabilities(
            "discovery_worker", {Capability.SHELL}
        )
        assert "Allowed:" in violations[0]
        assert "repo_read" in violations[0]

    def test_violation_message_includes_worker_name(self):
        violations = validate_worker_capabilities(
            "discovery_worker", {Capability.SHELL}
        )
        assert "discovery_worker" in violations[0]


# ============================================================================
# CAPABILITIES_MATRIX constant
# ============================================================================


class TestCapabilitiesMatrix:
    def test_covers_all_known_workers(self):
        expected = {
            "discovery_worker",
            "scout_worker",
            "execution_worker",
            "analyzer_worker",
            "security_review_worker",
            "code_review_worker",
        }
        assert set(CAPABILITIES_MATRIX.keys()) == expected

    def test_discovery_allowed_set(self):
        assert CAPABILITIES_MATRIX["discovery_worker"] == {
            Capability.REPO_READ,
            Capability.SPAWN,
        }

    def test_scout_allowed_set(self):
        assert CAPABILITIES_MATRIX["scout_worker"] == {
            Capability.NETWORK,
            Capability.SPAWN,
        }

    def test_execution_allowed_set(self):
        assert CAPABILITIES_MATRIX["execution_worker"] == {
            Capability.REPO_READ,
            Capability.REPO_WRITE,
            Capability.NETWORK,
            Capability.SHELL,
            Capability.SPAWN,
        }

    def test_analyzer_allowed_set(self):
        assert CAPABILITIES_MATRIX["analyzer_worker"] == {
            Capability.REPO_READ,
            Capability.SPAWN,
        }

    def test_security_review_allowed_set(self):
        assert CAPABILITIES_MATRIX["security_review_worker"] == {
            Capability.REPO_READ,
        }

    def test_scout_cannot_read_repo(self):
        assert Capability.REPO_READ not in CAPABILITIES_MATRIX["scout_worker"]

    def test_security_review_cannot_spawn(self):
        assert Capability.SPAWN not in CAPABILITIES_MATRIX["security_review_worker"]

    def test_discovery_cannot_write(self):
        assert Capability.REPO_WRITE not in CAPABILITIES_MATRIX["discovery_worker"]

    def test_only_execution_has_shell(self):
        for name, caps in CAPABILITIES_MATRIX.items():
            if name != "execution_worker":
                assert Capability.SHELL not in caps, f"{name} should not have SHELL"


# ============================================================================
# Harness Integration
# ============================================================================


def _make_worker(
    *,
    name: str = "discovery_worker",
    capabilities: set[Capability] | None = None,
):
    """Create a stub worker with configurable name and capabilities."""

    class _StubWorker:
        worker_name = name
        worker_class = WorkerClass.ROOT
        allowed_spawn_targets: list[str] = []
        default_timeout_seconds = 300
        default_budget = 1.0

        def validate_input(self, task):
            return ValidationResult(valid=True)

        def build_context(self, task):
            return ContextBuildResult()

        def execute(self, task, runtime):
            return WorkerOutput()

        def sanitize_output(self, output):
            return SanitizedOutput()

        def evaluate_output(self, output):
            return EvaluationResult(passed=True, confidence=0.9)

        def finalize(self, result):
            return ResultEnvelope(status=ResultStatus.SUCCESS)

    worker = _StubWorker()
    if capabilities is not None:
        worker.capabilities = capabilities
    else:
        worker.capabilities = {Capability.REPO_READ, Capability.SPAWN}
    return worker


@pytest.fixture()
def execution_snapshot():
    return ExecutionSnapshot(
        recipe_ref=RecipeRef(
            name="test", version="1.0.0", content_hash="abc"
        ),
        policy_ref=PolicyRef(
            name="test", version="1.0.0", content_hash="def"
        ),
        execution_strategy=ExecutionStrategy.ONE_SHOT,
        model_tier="balanced",
        config_hash="test",
    )


@pytest.fixture()
def task(execution_snapshot):
    return TaskEnvelope(
        task_id="t1",
        job_id="j1",
        run_id="r1",
        repo_id="repo_1",
        execution_snapshot=execution_snapshot,
        execution_mode=ExecutionMode.READ_ONLY,
    )


class TestHarnessCapabilitiesEnforcement:
    def test_compliant_worker_passes(self, task):
        harness = Harness()
        worker = _make_worker(
            name="discovery_worker",
            capabilities={Capability.REPO_READ, Capability.SPAWN},
        )
        result = harness.run(worker, task)
        assert result.result_envelope.status == ResultStatus.SUCCESS
        assert result.stage_reached == "finalize"

    def test_violating_worker_blocked(self, task):
        harness = Harness()
        worker = _make_worker(
            name="discovery_worker",
            capabilities={
                Capability.REPO_READ,
                Capability.REPO_WRITE,
                Capability.SHELL,
            },
        )
        with pytest.raises(HarnessError, match="Capabilities matrix violation"):
            harness.run(worker, task)

    def test_scout_with_repo_read_blocked(self, task):
        harness = Harness()
        worker = _make_worker(
            name="scout_worker",
            capabilities={Capability.NETWORK, Capability.REPO_READ},
        )
        with pytest.raises(HarnessError, match="Capabilities matrix violation"):
            harness.run(worker, task)

    def test_security_review_with_spawn_blocked(self, task):
        harness = Harness()
        worker = _make_worker(
            name="security_review_worker",
            capabilities={Capability.REPO_READ, Capability.SPAWN},
        )
        with pytest.raises(HarnessError, match="Capabilities matrix violation"):
            harness.run(worker, task)

    def test_execution_worker_all_caps_allowed(self, task):
        harness = Harness()
        worker = _make_worker(
            name="execution_worker",
            capabilities={
                Capability.REPO_READ,
                Capability.REPO_WRITE,
                Capability.NETWORK,
                Capability.SHELL,
                Capability.SPAWN,
            },
        )
        result = harness.run(worker, task)
        assert result.result_envelope.status == ResultStatus.SUCCESS

    def test_unknown_worker_passes_through(self, task):
        harness = Harness()
        worker = _make_worker(
            name="my_custom_worker",
            capabilities={Capability.REPO_READ, Capability.NETWORK},
        )
        result = harness.run(worker, task)
        assert result.result_envelope.status == ResultStatus.SUCCESS

    def test_analyzer_with_write_blocked(self, task):
        harness = Harness()
        worker = _make_worker(
            name="analyzer_worker",
            capabilities={Capability.REPO_READ, Capability.REPO_WRITE},
        )
        with pytest.raises(HarnessError, match="Capabilities matrix violation"):
            harness.run(worker, task)

    def test_empty_caps_always_allowed(self, task):
        harness = Harness()
        worker = _make_worker(
            name="discovery_worker",
            capabilities=set(),
        )
        result = harness.run(worker, task)
        assert result.result_envelope.status == ResultStatus.SUCCESS

    def test_error_message_contains_details(self, task):
        harness = Harness()
        worker = _make_worker(
            name="discovery_worker",
            capabilities={Capability.SHELL},
        )
        with pytest.raises(HarnessError) as exc_info:
            harness.run(worker, task)
        msg = str(exc_info.value)
        assert "discovery_worker" in msg
        assert "shell" in msg
