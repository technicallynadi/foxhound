"""Tests for SQLite storage layer.

Validates database operations for all entity stores: WorkItem, Job, Run,
Event, and Opportunity.
"""

import pytest
from datetime import datetime

from foxhound.core.models import (
    EventEnvelope,
    EventSeverity,
    EventType,
    ExecutionSnapshot,
    ExecutionStrategy,
    JobEnvelope,
    JobPriority,
    JobStatus,
    JobType,
    OpportunityDiscoveryItem,
    OpportunityState,
    PolicyRef,
    RecipeRef,
    RiskLevel,
    RunRecord,
    RunState,
    TrustLevel,
    WorkItem,
    WorkItemKind,
    WorkItemState,
)
from foxhound.storage import (
    Database,
    EventStore,
    JobStore,
    OpportunityStore,
    RunStore,
    WorkItemStore,
)


@pytest.fixture
def db() -> Database:
    """Create an in-memory database for testing."""
    return Database(":memory:")


@pytest.fixture
def work_item_store(db: Database) -> WorkItemStore:
    return WorkItemStore(db)


@pytest.fixture
def job_store(db: Database) -> JobStore:
    return JobStore(db)


@pytest.fixture
def run_store(db: Database) -> RunStore:
    return RunStore(db)


@pytest.fixture
def event_store(db: Database) -> EventStore:
    return EventStore(db)


@pytest.fixture
def opportunity_store(db: Database) -> OpportunityStore:
    return OpportunityStore(db)


def make_execution_snapshot() -> ExecutionSnapshot:
    """Create a test execution snapshot."""
    return ExecutionSnapshot(
        recipe_ref=RecipeRef(name="test_recipe", version="1.0.0", content_hash="abc123"),
        policy_ref=PolicyRef(name="default_policy", version="1.0.0", content_hash="def456"),
        config_hash="combined789",
    )


class TestDatabase:
    """Test database initialization and connection."""

    def test_create_in_memory_db(self) -> None:
        db = Database(":memory:")
        assert db.db_path == ":memory:"

    def test_schema_created(self, db: Database) -> None:
        """Verify all tables are created."""
        with db.connection() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [t["name"] for t in tables]

            expected_tables = [
                "repos",
                "work_items",
                "jobs",
                "runs",
                "events",
                "locks",
                "opportunity_items",
                "recipe_versions",
                "policy_versions",
                "artifacts",
            ]
            for table in expected_tables:
                assert table in table_names, f"Table {table} not found"

    def test_indexes_created(self, db: Database) -> None:
        """Verify indexes are created."""
        with db.connection() as conn:
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            ).fetchall()
            index_names = [i["name"] for i in indexes]

            assert "idx_work_items_repo_state" in index_names
            assert "idx_jobs_status_priority" in index_names
            assert "idx_runs_job" in index_names


class TestWorkItemStore:
    """Test WorkItem storage operations."""

    def test_save_and_get(self, work_item_store: WorkItemStore) -> None:
        item = WorkItem(
            work_item_id="wi_001",
            repo_id="repo_123",
            title="Fix authentication bug",
            source_type="github_issue",
            source_fingerprint="hash123",
        )
        work_item_store.save(item)

        retrieved = work_item_store.get("wi_001")
        assert retrieved is not None
        assert retrieved.work_item_id == "wi_001"
        assert retrieved.title == "Fix authentication bug"
        assert retrieved.state == WorkItemState.DISCOVERED

    def test_get_nonexistent(self, work_item_store: WorkItemStore) -> None:
        result = work_item_store.get("nonexistent")
        assert result is None

    def test_save_with_all_fields(self, work_item_store: WorkItemStore) -> None:
        item = WorkItem(
            work_item_id="wi_002",
            repo_id="repo_456",
            kind=WorkItemKind.EXECUTION,
            title="Update dependencies",
            description="CVE-2024-1234 fix required",
            source_type="dependency_alert",
            source_fingerprint="hash456",
            trust_level=TrustLevel.TRUSTED,
            state=WorkItemState.APPROVED,
            confidence=0.95,
            risk=RiskLevel.HIGH,
            recipe_name="dependency_security_update",
            evidence={"cve": "CVE-2024-1234"},
            likely_files=["requirements.txt", "poetry.lock"],
        )
        work_item_store.save(item)

        retrieved = work_item_store.get("wi_002")
        assert retrieved is not None
        assert retrieved.confidence == 0.95
        assert retrieved.risk == RiskLevel.HIGH
        assert retrieved.evidence["cve"] == "CVE-2024-1234"
        assert "requirements.txt" in retrieved.likely_files

    def test_list_by_repo(self, work_item_store: WorkItemStore) -> None:
        # Create multiple items
        for i in range(3):
            item = WorkItem(
                work_item_id=f"wi_list_{i}",
                repo_id="repo_list",
                title=f"Item {i}",
                source_type="manual",
                source_fingerprint=f"hash_{i}",
                state=WorkItemState.SUGGESTED if i < 2 else WorkItemState.APPROVED,
            )
            work_item_store.save(item)

        # List all
        all_items = work_item_store.list_by_repo("repo_list")
        assert len(all_items) == 3

        # List by state
        suggested = work_item_store.list_by_repo("repo_list", state=WorkItemState.SUGGESTED)
        assert len(suggested) == 2

    def test_update_state(self, work_item_store: WorkItemStore) -> None:
        item = WorkItem(
            work_item_id="wi_update",
            repo_id="repo_123",
            title="Test",
            source_type="manual",
            source_fingerprint="hash",
        )
        work_item_store.save(item)

        success = work_item_store.update_state("wi_update", WorkItemState.APPROVED)
        assert success

        retrieved = work_item_store.get("wi_update")
        assert retrieved is not None
        assert retrieved.state == WorkItemState.APPROVED

    def test_delete(self, work_item_store: WorkItemStore) -> None:
        item = WorkItem(
            work_item_id="wi_delete",
            repo_id="repo_123",
            title="To be deleted",
            source_type="manual",
            source_fingerprint="hash",
        )
        work_item_store.save(item)

        success = work_item_store.delete("wi_delete")
        assert success

        retrieved = work_item_store.get("wi_delete")
        assert retrieved is None


class TestJobStore:
    """Test Job storage operations."""

    def test_save_and_get(self, job_store: JobStore) -> None:
        job = JobEnvelope(
            job_id="job_001",
            work_item_id="wi_001",
            repo_id="repo_123",
            job_type=JobType.EXECUTION,
            execution_snapshot=make_execution_snapshot(),
        )
        job_store.save(job)

        retrieved = job_store.get("job_001")
        assert retrieved is not None
        assert retrieved.job_id == "job_001"
        assert retrieved.status == JobStatus.QUEUED
        assert retrieved.execution_snapshot.recipe_ref.name == "test_recipe"

    def test_list_by_status(self, job_store: JobStore) -> None:
        # Create jobs with different priorities
        for priority in [JobPriority.LOW, JobPriority.NORMAL, JobPriority.HIGH]:
            job = JobEnvelope(
                job_id=f"job_{priority.value}",
                work_item_id="wi_001",
                repo_id="repo_123",
                job_type=JobType.EXECUTION,
                priority=priority,
                execution_snapshot=make_execution_snapshot(),
            )
            job_store.save(job)

        queued_jobs = job_store.list_by_status(JobStatus.QUEUED)
        assert len(queued_jobs) == 3
        # High priority should be first
        assert queued_jobs[0].priority == JobPriority.HIGH

    def test_update_status_running(self, job_store: JobStore) -> None:
        job = JobEnvelope(
            job_id="job_running",
            work_item_id="wi_001",
            repo_id="repo_123",
            job_type=JobType.EXECUTION,
            execution_snapshot=make_execution_snapshot(),
        )
        job_store.save(job)

        started = datetime.now()
        success = job_store.update_status("job_running", JobStatus.RUNNING, started_at=started)
        assert success

        retrieved = job_store.get("job_running")
        assert retrieved is not None
        assert retrieved.status == JobStatus.RUNNING
        assert retrieved.started_at is not None

    def test_spawned_job(self, job_store: JobStore) -> None:
        job = JobEnvelope(
            job_id="job_child",
            work_item_id="wi_001",
            repo_id="repo_123",
            job_type=JobType.ANALYZER,
            execution_snapshot=make_execution_snapshot(),
            spawn_depth=1,
            parent_job_id="job_parent",
        )
        job_store.save(job)

        retrieved = job_store.get("job_child")
        assert retrieved is not None
        assert retrieved.spawn_depth == 1
        assert retrieved.parent_job_id == "job_parent"


class TestRunStore:
    """Test Run storage operations."""

    def test_save_and_get(self, run_store: RunStore) -> None:
        run = RunRecord(
            run_id="run_001",
            job_id="job_001",
            worker_type="ExecutionWorker",
        )
        run_store.save(run)

        retrieved = run_store.get("run_001")
        assert retrieved is not None
        assert retrieved.run_id == "run_001"
        assert retrieved.state == RunState.QUEUED

    def test_save_with_results(self, run_store: RunStore) -> None:
        run = RunRecord(
            run_id="run_complete",
            job_id="job_001",
            worker_type="ExecutionWorker",
            state=RunState.COMPLETED,
            branch_name="foxhound/fix-123",
            workspace_path="/tmp/workspace",
            total_cost=0.45,
            manifest_path=".foxhound/manifests/run_001.json",
            artifact_refs=["log_001", "diff_001"],
        )
        run_store.save(run)

        retrieved = run_store.get("run_complete")
        assert retrieved is not None
        assert retrieved.branch_name == "foxhound/fix-123"
        assert retrieved.total_cost == 0.45
        assert len(retrieved.artifact_refs) == 2

    def test_list_by_job(self, run_store: RunStore) -> None:
        for i in range(3):
            run = RunRecord(
                run_id=f"run_multi_{i}",
                job_id="job_multi",
                worker_type="ExecutionWorker",
                retry_count=i,
            )
            run_store.save(run)

        runs = run_store.list_by_job("job_multi")
        assert len(runs) == 3

    def test_update_state(self, run_store: RunStore) -> None:
        run = RunRecord(
            run_id="run_update",
            job_id="job_001",
            worker_type="ExecutionWorker",
        )
        run_store.save(run)

        success = run_store.update_state("run_update", RunState.EXECUTING)
        assert success

        retrieved = run_store.get("run_update")
        assert retrieved is not None
        assert retrieved.state == RunState.EXECUTING


class TestEventStore:
    """Test Event storage operations."""

    def test_save_and_get(self, event_store: EventStore) -> None:
        event = EventEnvelope(
            event_id="evt_001",
            event_type=EventType.RUN_STARTED,
            source_module="execution_engine",
            run_id="run_001",
        )
        event_store.save(event)

        retrieved = event_store.get("evt_001")
        assert retrieved is not None
        assert retrieved.event_type == EventType.RUN_STARTED

    def test_save_with_payload(self, event_store: EventStore) -> None:
        event = EventEnvelope(
            event_id="evt_payload",
            event_type=EventType.RUN_COMPLETED,
            source_module="execution_engine",
            run_id="run_001",
            payload={"duration_seconds": 84, "status": "success"},
        )
        event_store.save(event)

        retrieved = event_store.get("evt_payload")
        assert retrieved is not None
        assert retrieved.payload["duration_seconds"] == 84

    def test_list_by_run(self, event_store: EventStore) -> None:
        events = [
            EventEnvelope(
                event_id=f"evt_run_{i}",
                event_type=EventType.RUN_STARTED if i == 0 else EventType.RUN_COMPLETED,
                source_module="execution_engine",
                run_id="run_events",
            )
            for i in range(2)
        ]
        for event in events:
            event_store.save(event)

        retrieved = event_store.list_by_run("run_events")
        assert len(retrieved) == 2

    def test_list_recent(self, event_store: EventStore) -> None:
        for i in range(5):
            event = EventEnvelope(
                event_id=f"evt_recent_{i}",
                event_type=EventType.RUN_STARTED,
                source_module="test",
            )
            event_store.save(event)

        recent = event_store.list_recent(limit=3)
        assert len(recent) == 3

    def test_list_recent_by_type(self, event_store: EventStore) -> None:
        event_store.save(EventEnvelope(
            event_id="evt_type_1",
            event_type=EventType.RUN_STARTED,
            source_module="test",
        ))
        event_store.save(EventEnvelope(
            event_id="evt_type_2",
            event_type=EventType.RUN_COMPLETED,
            source_module="test",
        ))

        started = event_store.list_recent(event_type=EventType.RUN_STARTED)
        assert len(started) == 1
        assert started[0].event_type == EventType.RUN_STARTED


class TestOpportunityStore:
    """Test Opportunity storage operations."""

    def test_save_and_get(self, opportunity_store: OpportunityStore) -> None:
        item = OpportunityDiscoveryItem(
            opportunity_id="opp_001",
            title="Missing async support in CLI tool",
            source_type="reddit",
            source_fingerprint="hash123",
        )
        opportunity_store.save(item)

        retrieved = opportunity_store.get("opp_001")
        assert retrieved is not None
        assert retrieved.title == "Missing async support in CLI tool"
        assert retrieved.state == OpportunityState.OBSERVED
        assert retrieved.trust_level == TrustLevel.UNTRUSTED

    def test_save_with_scores(self, opportunity_store: OpportunityStore) -> None:
        item = OpportunityDiscoveryItem(
            opportunity_id="opp_scored",
            title="Feature gap",
            source_type="article",
            source_fingerprint="hash456",
            credibility_score=0.8,
            novelty_score=0.7,
            actionability_score=0.6,
            business_value_score=0.9,
            evidence={"source": "techcrunch"},
            tags=["ai", "productivity"],
        )
        opportunity_store.save(item)

        retrieved = opportunity_store.get("opp_scored")
        assert retrieved is not None
        assert retrieved.credibility_score == 0.8
        assert retrieved.business_value_score == 0.9
        assert "ai" in retrieved.tags

    def test_list_by_state(self, opportunity_store: OpportunityStore) -> None:
        for i, state in enumerate([
            OpportunityState.OBSERVED,
            OpportunityState.EVALUATED,
            OpportunityState.SUGGESTED,
        ]):
            item = OpportunityDiscoveryItem(
                opportunity_id=f"opp_state_{i}",
                title=f"Opportunity {i}",
                source_type="test",
                source_fingerprint=f"hash_{i}",
                state=state,
            )
            opportunity_store.save(item)

        observed = opportunity_store.list_by_state(OpportunityState.OBSERVED)
        assert len(observed) == 1
        assert observed[0].state == OpportunityState.OBSERVED


class TestCrossStoreIntegration:
    """Test interactions between stores."""

    def test_work_item_to_job_to_run(
        self,
        work_item_store: WorkItemStore,
        job_store: JobStore,
        run_store: RunStore,
    ) -> None:
        """Test typical flow: WorkItem -> Job -> Run."""
        # Create work item
        work_item = WorkItem(
            work_item_id="wi_flow",
            repo_id="repo_flow",
            title="Integration test",
            source_type="manual",
            source_fingerprint="hash_flow",
            state=WorkItemState.APPROVED,
        )
        work_item_store.save(work_item)

        # Create job for work item
        job = JobEnvelope(
            job_id="job_flow",
            work_item_id="wi_flow",
            repo_id="repo_flow",
            job_type=JobType.EXECUTION,
            execution_snapshot=make_execution_snapshot(),
        )
        job_store.save(job)

        # Create run for job
        run = RunRecord(
            run_id="run_flow",
            job_id="job_flow",
            worker_type="ExecutionWorker",
        )
        run_store.save(run)

        # Verify relationships
        retrieved_job = job_store.get("job_flow")
        assert retrieved_job is not None
        assert retrieved_job.work_item_id == "wi_flow"

        retrieved_runs = run_store.list_by_job("job_flow")
        assert len(retrieved_runs) == 1
        assert retrieved_runs[0].run_id == "run_flow"
