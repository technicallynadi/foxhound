"""Tests for core Pydantic models.

Validates that all core models can be instantiated, serialized to JSON,
and properly enforce field constraints as defined in the specs.
"""

import pytest
from datetime import datetime

from foxhound.core.models import (
    EventEnvelope,
    EventSeverity,
    EventType,
    ExecutionMode,
    ExecutionSnapshot,
    ExecutionStrategy,
    JobEnvelope,
    JobPriority,
    JobStatus,
    JobType,
    Manifest,
    OpportunityDiscoveryItem,
    OpportunityState,
    PolicyRef,
    RecipeRef,
    ResultEnvelope,
    ResultStatus,
    RiskLevel,
    RunRecord,
    RunState,
    TaskEnvelope,
    TrustLevel,
    WorkItem,
    WorkItemKind,
    WorkItemState,
)


class TestEnums:
    """Test enum values match spec definitions."""

    def test_trust_level_values(self) -> None:
        assert TrustLevel.TRUSTED.value == "trusted"
        assert TrustLevel.SEMI_TRUSTED.value == "semi_trusted"
        assert TrustLevel.UNTRUSTED.value == "untrusted"

    def test_work_item_state_flow(self) -> None:
        """Verify all states in the work item state machine exist."""
        states = [s.value for s in WorkItemState]
        expected = [
            "discovered",
            "suggested",
            "approved",
            "edited",
            "rejected",
            "blocked",
            "executing",
            "completed",
            "failed",
        ]
        assert sorted(states) == sorted(expected)

    def test_run_state_flow(self) -> None:
        """Verify all states in the run state machine exist."""
        states = [s.value for s in RunState]
        expected = [
            "queued",
            "preparing",
            "context_built",
            "executing",
            "validating",
            "security_review",
            "branch_ready",
            "pr_draft_ready",
            "completed",
            "failed",
            "cancelled",
        ]
        assert sorted(states) == sorted(expected)

    def test_execution_strategies(self) -> None:
        """Verify execution strategies match Ralph spec."""
        assert ExecutionStrategy.ONE_SHOT.value == "one_shot"
        assert ExecutionStrategy.BOUNDED_RETRY.value == "bounded_retry"
        assert ExecutionStrategy.RALPH_LOOP.value == "ralph_loop"


class TestRecipeAndPolicyRef:
    """Test recipe and policy reference models."""

    def test_recipe_ref_creation(self) -> None:
        ref = RecipeRef(
            name="approved_ticket",
            version="1.2.0",
            content_hash="abc123",
        )
        assert ref.name == "approved_ticket"
        assert ref.version == "1.2.0"
        assert ref.content_hash == "abc123"
        assert ref.source_scope == "builtin"

    def test_policy_ref_creation(self) -> None:
        ref = PolicyRef(
            name="default_policy",
            version="1.0.0",
            content_hash="def456",
            source_scope="repo",
        )
        assert ref.name == "default_policy"
        assert ref.source_scope == "repo"

    def test_recipe_ref_json_serialization(self) -> None:
        ref = RecipeRef(
            name="ci_failure_repair",
            version="1.0.0",
            content_hash="xyz789",
        )
        json_data = ref.model_dump_json()
        assert "ci_failure_repair" in json_data
        assert "1.0.0" in json_data


class TestExecutionSnapshot:
    """Test execution snapshot immutability contract."""

    def test_execution_snapshot_creation(self) -> None:
        recipe = RecipeRef(name="test", version="1.0.0", content_hash="aaa")
        policy = PolicyRef(name="default", version="1.0.0", content_hash="bbb")
        snapshot = ExecutionSnapshot(
            recipe_ref=recipe,
            policy_ref=policy,
            config_hash="combined123",
        )
        assert snapshot.execution_strategy == ExecutionStrategy.ONE_SHOT
        assert snapshot.model_tier == "balanced"

    def test_execution_snapshot_with_ralph(self) -> None:
        recipe = RecipeRef(name="feature_build", version="2.0.0", content_hash="ccc")
        policy = PolicyRef(name="strict", version="1.1.0", content_hash="ddd")
        snapshot = ExecutionSnapshot(
            recipe_ref=recipe,
            policy_ref=policy,
            execution_strategy=ExecutionStrategy.RALPH_LOOP,
            model_tier="reasoning",
            config_hash="combined456",
        )
        assert snapshot.execution_strategy == ExecutionStrategy.RALPH_LOOP
        assert snapshot.model_tier == "reasoning"


class TestWorkItem:
    """Test work item model."""

    def test_work_item_creation(self) -> None:
        item = WorkItem(
            work_item_id="wi_001",
            repo_id="repo_123",
            title="Fix CI failure in auth module",
            source_type="ci_failure",
            source_fingerprint="hash123",
        )
        assert item.work_item_id == "wi_001"
        assert item.state == WorkItemState.DISCOVERED
        assert item.kind == WorkItemKind.EXECUTION
        assert item.trust_level == TrustLevel.SEMI_TRUSTED
        assert item.risk == RiskLevel.LOW
        assert item.confidence == 0.0

    def test_work_item_with_all_fields(self) -> None:
        item = WorkItem(
            work_item_id="wi_002",
            repo_id="repo_456",
            kind=WorkItemKind.EXECUTION,
            title="Update vulnerable dependency",
            description="CVE-2024-1234 in requests library",
            source_type="dependency_alert",
            source_fingerprint="hash456",
            trust_level=TrustLevel.TRUSTED,
            state=WorkItemState.APPROVED,
            confidence=0.95,
            risk=RiskLevel.HIGH,
            recipe_name="dependency_security_update",
            evidence={"cve": "CVE-2024-1234", "severity": "critical"},
            likely_files=["requirements.txt", "poetry.lock"],
        )
        assert item.confidence == 0.95
        assert item.recipe_name == "dependency_security_update"
        assert len(item.likely_files) == 2

    def test_work_item_confidence_bounds(self) -> None:
        with pytest.raises(ValueError):
            WorkItem(
                work_item_id="wi_bad",
                repo_id="repo",
                title="Bad",
                source_type="test",
                source_fingerprint="hash",
                confidence=1.5,  # Invalid: > 1.0
            )

    def test_work_item_json_roundtrip(self) -> None:
        item = WorkItem(
            work_item_id="wi_003",
            repo_id="repo_789",
            title="Test roundtrip",
            source_type="manual",
            source_fingerprint="hash789",
        )
        json_str = item.model_dump_json()
        restored = WorkItem.model_validate_json(json_str)
        assert restored.work_item_id == item.work_item_id
        assert restored.state == item.state


class TestOpportunityDiscoveryItem:
    """Test opportunity discovery item model."""

    def test_opportunity_item_creation(self) -> None:
        item = OpportunityDiscoveryItem(
            opportunity_id="opp_001",
            title="Popular CLI tool missing async support",
            source_type="reddit",
            source_fingerprint="hash123",
        )
        assert item.opportunity_id == "opp_001"
        assert item.state == OpportunityState.OBSERVED
        assert item.trust_level == TrustLevel.UNTRUSTED

    def test_opportunity_scores(self) -> None:
        item = OpportunityDiscoveryItem(
            opportunity_id="opp_002",
            title="Feature gap in competitor",
            source_type="article",
            source_fingerprint="hash456",
            credibility_score=0.7,
            novelty_score=0.8,
            actionability_score=0.6,
            business_value_score=0.9,
        )
        assert item.credibility_score == 0.7
        assert item.business_value_score == 0.9


class TestJobEnvelope:
    """Test job envelope model."""

    def test_job_envelope_creation(self) -> None:
        recipe = RecipeRef(name="test", version="1.0.0", content_hash="aaa")
        policy = PolicyRef(name="default", version="1.0.0", content_hash="bbb")
        snapshot = ExecutionSnapshot(
            recipe_ref=recipe,
            policy_ref=policy,
            config_hash="combined",
        )
        job = JobEnvelope(
            job_id="job_001",
            work_item_id="wi_001",
            repo_id="repo_123",
            job_type=JobType.EXECUTION,
            execution_snapshot=snapshot,
        )
        assert job.job_id == "job_001"
        assert job.status == JobStatus.QUEUED
        assert job.priority == JobPriority.NORMAL
        assert job.spawn_depth == 0
        assert job.parent_job_id is None

    def test_spawned_job(self) -> None:
        recipe = RecipeRef(name="test", version="1.0.0", content_hash="aaa")
        policy = PolicyRef(name="default", version="1.0.0", content_hash="bbb")
        snapshot = ExecutionSnapshot(
            recipe_ref=recipe,
            policy_ref=policy,
            config_hash="combined",
        )
        job = JobEnvelope(
            job_id="job_002",
            work_item_id="wi_001",
            repo_id="repo_123",
            job_type=JobType.ANALYZER,
            execution_snapshot=snapshot,
            spawn_depth=1,
            parent_job_id="job_001",
        )
        assert job.spawn_depth == 1
        assert job.parent_job_id == "job_001"


class TestRunRecord:
    """Test run record model."""

    def test_run_record_creation(self) -> None:
        run = RunRecord(
            run_id="run_001",
            job_id="job_001",
            worker_type="ExecutionWorker",
        )
        assert run.run_id == "run_001"
        assert run.state == RunState.QUEUED
        assert run.total_cost == 0.0
        assert run.retry_count == 0

    def test_run_record_with_results(self) -> None:
        run = RunRecord(
            run_id="run_002",
            job_id="job_002",
            worker_type="ExecutionWorker",
            state=RunState.COMPLETED,
            branch_name="foxhound/fix-auth-bug",
            workspace_path="/tmp/foxhound/ws_001",
            total_cost=0.45,
            manifest_path=".foxhound/artifacts/manifest_001.json",
            artifact_refs=["log_001", "diff_001"],
        )
        assert run.state == RunState.COMPLETED
        assert run.branch_name == "foxhound/fix-auth-bug"
        assert len(run.artifact_refs) == 2


class TestTaskEnvelope:
    """Test task envelope model."""

    def test_task_envelope_creation(self) -> None:
        recipe = RecipeRef(name="test", version="1.0.0", content_hash="aaa")
        policy = PolicyRef(name="default", version="1.0.0", content_hash="bbb")
        snapshot = ExecutionSnapshot(
            recipe_ref=recipe,
            policy_ref=policy,
            config_hash="combined",
        )
        task = TaskEnvelope(
            task_id="task_001",
            job_id="job_001",
            run_id="run_001",
            repo_id="repo_123",
            execution_snapshot=snapshot,
        )
        assert task.task_id == "task_001"
        assert task.execution_mode == ExecutionMode.FULL_EXECUTE
        assert task.budget == 1.0


class TestResultEnvelope:
    """Test result envelope model."""

    def test_result_envelope_success(self) -> None:
        result = ResultEnvelope(
            status=ResultStatus.SUCCESS,
            payload={"branch": "foxhound/fix-123", "commit": "abc123"},
            confidence=0.95,
        )
        assert result.status == ResultStatus.SUCCESS
        assert result.confidence == 0.95
        assert len(result.safety_flags) == 0

    def test_result_envelope_with_warnings(self) -> None:
        result = ResultEnvelope(
            status=ResultStatus.PARTIAL,
            payload={"partial_changes": True},
            confidence=0.6,
            safety_flags=["modified_sensitive_path", "high_complexity_change"],
            recommended_next_action="request_human_review",
        )
        assert result.status == ResultStatus.PARTIAL
        assert len(result.safety_flags) == 2


class TestEventEnvelope:
    """Test event envelope model."""

    def test_event_envelope_creation(self) -> None:
        event = EventEnvelope(
            event_id="evt_001",
            event_type=EventType.RUN_STARTED,
            source_module="execution_engine",
            run_id="run_001",
            repo_id="repo_123",
        )
        assert event.event_id == "evt_001"
        assert event.event_type == EventType.RUN_STARTED
        assert event.severity == EventSeverity.INFO

    def test_event_envelope_with_payload(self) -> None:
        event = EventEnvelope(
            event_id="evt_002",
            event_type=EventType.RUN_COMPLETED,
            source_module="execution_engine",
            run_id="run_001",
            severity=EventSeverity.INFO,
            payload={"status": "success", "duration_seconds": 84},
        )
        assert event.payload["duration_seconds"] == 84

    def test_ralph_iteration_event(self) -> None:
        event = EventEnvelope(
            event_id="evt_003",
            event_type=EventType.RALPH_ITERATION_COMPLETED,
            source_module="execution_engine",
            run_id="run_002",
            payload={
                "iteration": 3,
                "tasks_completed": 2,
                "tasks_remaining": 5,
                "iteration_cost": 0.12,
                "cumulative_cost": 0.45,
            },
        )
        assert event.event_type == EventType.RALPH_ITERATION_COMPLETED
        assert event.payload["iteration"] == 3


class TestManifest:
    """Test manifest model for provenance."""

    def test_manifest_creation(self) -> None:
        recipe = RecipeRef(name="approved_ticket", version="1.0.0", content_hash="aaa")
        policy = PolicyRef(name="default_policy", version="1.0.0", content_hash="bbb")
        manifest = Manifest(
            manifest_id="mfst_001",
            run_id="run_001",
            work_item_id="wi_001",
            repo_id="repo_123",
            recipe_ref=recipe,
            policy_ref=policy,
            context_pack_hash="ctx123",
            execution_environment_fingerprint="env456",
            execution_strategy=ExecutionStrategy.ONE_SHOT,
            model_provider="anthropic",
            model_tier="balanced",
            workspace_id="ws_001",
        )
        assert manifest.manifest_id == "mfst_001"
        assert manifest.execution_strategy == ExecutionStrategy.ONE_SHOT

    def test_manifest_with_ralph_fields(self) -> None:
        recipe = RecipeRef(name="feature_build", version="2.0.0", content_hash="ccc")
        policy = PolicyRef(name="default_policy", version="1.0.0", content_hash="ddd")
        manifest = Manifest(
            manifest_id="mfst_002",
            run_id="run_002",
            work_item_id="wi_002",
            repo_id="repo_456",
            recipe_ref=recipe,
            policy_ref=policy,
            context_pack_hash="ctx789",
            execution_environment_fingerprint="env012",
            execution_strategy=ExecutionStrategy.RALPH_LOOP,
            model_provider="anthropic",
            model_tier="reasoning",
            workspace_id="ws_002",
            total_cost=1.25,
            duration_seconds=420.5,
            iteration_count=5,
            max_iterations=10,
            per_iteration_costs=[0.2, 0.25, 0.3, 0.25, 0.25],
            per_iteration_tasks_completed=[3, 2, 2, 1, 2],
            commit_refs=["abc", "def", "ghi", "jkl", "mno"],
            progress_file_path=".foxhound/progress/run_002.json",
            completion_status="complete",
        )
        assert manifest.execution_strategy == ExecutionStrategy.RALPH_LOOP
        assert manifest.iteration_count == 5
        assert manifest.completion_status == "complete"
        assert len(manifest.per_iteration_costs) == 5


class TestModelExtraForbid:
    """Test that models reject extra fields."""

    def test_work_item_rejects_extra(self) -> None:
        with pytest.raises(ValueError):
            WorkItem(
                work_item_id="wi_001",
                repo_id="repo_123",
                title="Test",
                source_type="test",
                source_fingerprint="hash",
                unknown_field="should fail",  # type: ignore
            )

    def test_event_envelope_rejects_extra(self) -> None:
        with pytest.raises(ValueError):
            EventEnvelope(
                event_id="evt_001",
                event_type=EventType.RUN_STARTED,
                source_module="test",
                extra_data="should fail",  # type: ignore
            )
