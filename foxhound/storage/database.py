"""SQLite database access layer for Foxhound."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from foxhound.core.models import (
    EventEnvelope,
    EventSeverity,
    EventType,
    ExecutionSnapshot,
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

# SQL schema for all core tables
SCHEMA_SQL = """
-- Repositories table
CREATE TABLE IF NOT EXISTS repos (
    repo_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    default_branch TEXT DEFAULT 'main',
    repo_hash TEXT,
    language_meta TEXT,
    active_config_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Work items table
CREATE TABLE IF NOT EXISTS work_items (
    work_item_id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    source_type TEXT NOT NULL,
    source_fingerprint TEXT NOT NULL,
    trust_level TEXT NOT NULL,
    state TEXT NOT NULL,
    confidence REAL DEFAULT 0.0,
    risk TEXT DEFAULT 'low',
    recipe_name TEXT,
    evidence TEXT,
    likely_files TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (repo_id) REFERENCES repos(repo_id)
);

-- Jobs table
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    work_item_id TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    job_type TEXT NOT NULL,
    priority TEXT DEFAULT 'normal',
    status TEXT NOT NULL,
    execution_snapshot_json TEXT NOT NULL,
    budget REAL DEFAULT 1.0,
    timeout_seconds INTEGER DEFAULT 300,
    spawn_depth INTEGER DEFAULT 0,
    parent_job_id TEXT,
    queued_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY (work_item_id) REFERENCES work_items(work_item_id),
    FOREIGN KEY (repo_id) REFERENCES repos(repo_id)
);

-- Runs table
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    worker_type TEXT NOT NULL,
    state TEXT NOT NULL,
    branch_name TEXT,
    workspace_path TEXT,
    total_cost REAL DEFAULT 0.0,
    retry_count INTEGER DEFAULT 0,
    failure_reason TEXT,
    manifest_path TEXT,
    security_review_passed INTEGER DEFAULT 0,
    artifact_refs TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);

-- Events table
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    repo_id TEXT,
    run_id TEXT,
    job_id TEXT,
    severity TEXT DEFAULT 'info',
    payload_json TEXT,
    occurred_at TEXT NOT NULL
);

-- Locks table
CREATE TABLE IF NOT EXISTS locks (
    lock_id TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL,
    resource_key TEXT NOT NULL,
    owner_job_id TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT
);

-- Opportunity items table
CREATE TABLE IF NOT EXISTS opportunity_items (
    opportunity_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    source_type TEXT NOT NULL,
    source_url TEXT,
    source_fingerprint TEXT NOT NULL,
    trust_level TEXT NOT NULL,
    state TEXT NOT NULL,
    credibility_score REAL DEFAULT 0.0,
    novelty_score REAL DEFAULT 0.0,
    actionability_score REAL DEFAULT 0.0,
    business_value_score REAL DEFAULT 0.0,
    evidence TEXT,
    tags TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Recipe versions table
CREATE TABLE IF NOT EXISTS recipe_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_scope TEXT DEFAULT 'builtin',
    content_path TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(name, version)
);

-- Policy versions table
CREATE TABLE IF NOT EXISTS policy_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_scope TEXT DEFAULT 'builtin',
    content_path TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(name, version)
);

-- Artifacts index table
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER DEFAULT 0,
    retention_class TEXT DEFAULT 'B',
    pinned INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

-- Rule suggestions table
CREATE TABLE IF NOT EXISTS rule_suggestions (
    suggestion_id TEXT PRIMARY KEY,
    repo_id TEXT,
    rule_name TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    condition TEXT NOT NULL,
    action TEXT NOT NULL,
    evidence TEXT,
    confidence REAL DEFAULT 0.0,
    state TEXT DEFAULT 'pending_review',
    suggested_by TEXT DEFAULT 'analyzer',
    reviewed_by TEXT,
    created_at TEXT NOT NULL,
    reviewed_at TEXT
);

-- Scout raw opportunities staging table
CREATE TABLE IF NOT EXISTS scout_raw_opportunities (
    raw_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    raw_payload TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    scored INTEGER DEFAULT 0,
    dedupe_hash TEXT NOT NULL UNIQUE
);

-- Scout fetch metadata table
CREATE TABLE IF NOT EXISTS scout_fetch_metadata (
    source TEXT PRIMARY KEY,
    last_fetched_at TEXT NOT NULL,
    items_fetched INTEGER DEFAULT 0,
    rate_limit_hits INTEGER DEFAULT 0
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_work_items_repo_state ON work_items(repo_id, state, kind);
CREATE INDEX IF NOT EXISTS idx_jobs_status_priority ON jobs(status, priority, queued_at);
CREATE INDEX IF NOT EXISTS idx_jobs_repo_type ON jobs(repo_id, job_type, status);
CREATE INDEX IF NOT EXISTS idx_runs_job ON runs(job_id);
CREATE INDEX IF NOT EXISTS idx_runs_state ON runs(state, updated_at);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_locks_resource ON locks(resource_type, resource_key);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id, artifact_type);
CREATE INDEX IF NOT EXISTS idx_raw_opps_source_scored ON scout_raw_opportunities(source, scored);
CREATE INDEX IF NOT EXISTS idx_raw_opps_dedupe ON scout_raw_opportunities(dedupe_hash);
CREATE INDEX IF NOT EXISTS idx_raw_opps_expires ON scout_raw_opportunities(expires_at);
"""


class Database:
    """SQLite database connection manager.

    Provides connection management and schema initialization for Foxhound's
    metadata storage. For in-memory databases, maintains a persistent connection
    to preserve data across operations.
    """

    def __init__(self, db_path: str | Path) -> None:
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file. Use ':memory:' for in-memory DB.
        """
        self.db_path = str(db_path)
        self._is_memory = db_path == ":memory:"
        self._persistent_conn: sqlite3.Connection | None = None

        if self._is_memory:
            # For in-memory DBs, we need to keep a connection alive
            self._persistent_conn = sqlite3.connect(":memory:")
            self._persistent_conn.row_factory = sqlite3.Row
            self._persistent_conn.executescript(SCHEMA_SQL)
            self._persistent_conn.commit()
        else:
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection with row factory enabled.

        Yields:
            SQLite connection with Row factory for dict-like access.
        """
        if self._is_memory and self._persistent_conn:
            # For in-memory DBs, reuse the persistent connection
            yield self._persistent_conn
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def close(self) -> None:
        """Close the persistent connection for in-memory databases."""
        if self._persistent_conn:
            self._persistent_conn.close()
            self._persistent_conn = None


class WorkItemStore:
    """Storage operations for WorkItem entities."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, item: WorkItem) -> None:
        """Save or update a work item."""
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO work_items (
                    work_item_id, repo_id, kind, title, description, source_type,
                    source_fingerprint, trust_level, state, confidence, risk,
                    recipe_name, evidence, likely_files, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.work_item_id,
                    item.repo_id,
                    item.kind.value,
                    item.title,
                    item.description,
                    item.source_type,
                    item.source_fingerprint,
                    item.trust_level.value,
                    item.state.value,
                    item.confidence,
                    item.risk.value,
                    item.recipe_name,
                    json.dumps(item.evidence),
                    json.dumps(item.likely_files),
                    item.created_at.isoformat(),
                    item.updated_at.isoformat(),
                ),
            )
            conn.commit()

    def get(self, work_item_id: str) -> WorkItem | None:
        """Get a work item by ID."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM work_items WHERE work_item_id = ?",
                (work_item_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_model(row)

    def list_by_repo(
        self,
        repo_id: str,
        state: WorkItemState | None = None,
        kind: WorkItemKind | None = None,
    ) -> list[WorkItem]:
        """List work items for a repository with optional filters."""
        query = "SELECT * FROM work_items WHERE repo_id = ?"
        params: list[Any] = [repo_id]

        if state is not None:
            query += " AND state = ?"
            params.append(state.value)
        if kind is not None:
            query += " AND kind = ?"
            params.append(kind.value)

        query += " ORDER BY updated_at DESC"

        with self.db.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_model(row) for row in rows]

    def update_state(self, work_item_id: str, new_state: WorkItemState) -> bool:
        """Update the state of a work item."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "UPDATE work_items SET state = ?, updated_at = ? WHERE work_item_id = ?",
                (new_state.value, datetime.now().isoformat(), work_item_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def find_by_fingerprint(
        self, repo_id: str, source_fingerprint: str
    ) -> WorkItem | None:
        """Find a work item by its source fingerprint for dedup."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM work_items WHERE repo_id = ? AND source_fingerprint = ?",
                (repo_id, source_fingerprint),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_model(row)

    def list_all(
        self,
        state: WorkItemState | None = None,
        limit: int = 100,
    ) -> list[WorkItem]:
        """List all work items with optional state filter."""
        query = "SELECT * FROM work_items"
        params: list[Any] = []

        if state is not None:
            query += " WHERE state = ?"
            params.append(state.value)

        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        with self.db.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_model(row) for row in rows]

    def get_fingerprints(self, repo_id: str) -> set[str]:
        """Get all source fingerprints for a repo (for dedup)."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT source_fingerprint FROM work_items WHERE repo_id = ?",
                (repo_id,),
            ).fetchall()
            return {row["source_fingerprint"] for row in rows}

    def delete(self, work_item_id: str) -> bool:
        """Delete a work item."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM work_items WHERE work_item_id = ?",
                (work_item_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def _row_to_model(self, row: sqlite3.Row) -> WorkItem:
        """Convert database row to WorkItem model."""
        return WorkItem(
            work_item_id=row["work_item_id"],
            repo_id=row["repo_id"],
            kind=WorkItemKind(row["kind"]),
            title=row["title"],
            description=row["description"] or "",
            source_type=row["source_type"],
            source_fingerprint=row["source_fingerprint"],
            trust_level=TrustLevel(row["trust_level"]),
            state=WorkItemState(row["state"]),
            confidence=row["confidence"],
            risk=RiskLevel(row["risk"]),
            recipe_name=row["recipe_name"],
            evidence=json.loads(row["evidence"]) if row["evidence"] else {},
            likely_files=json.loads(row["likely_files"]) if row["likely_files"] else [],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


class JobStore:
    """Storage operations for JobEnvelope entities."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, job: JobEnvelope) -> None:
        """Save or update a job."""
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO jobs (
                    job_id, work_item_id, repo_id, job_type, priority, status,
                    execution_snapshot_json, budget, timeout_seconds, spawn_depth,
                    parent_job_id, queued_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.work_item_id,
                    job.repo_id,
                    job.job_type.value,
                    job.priority.value,
                    job.status.value,
                    job.execution_snapshot.model_dump_json(),
                    job.budget,
                    job.timeout_seconds,
                    job.spawn_depth,
                    job.parent_job_id,
                    job.queued_at.isoformat(),
                    job.started_at.isoformat() if job.started_at else None,
                    job.finished_at.isoformat() if job.finished_at else None,
                ),
            )
            conn.commit()

    def get(self, job_id: str) -> JobEnvelope | None:
        """Get a job by ID."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_model(row)

    def list_by_status(
        self, status: JobStatus, limit: int = 100
    ) -> list[JobEnvelope]:
        """List jobs by status, ordered by priority and queue time."""
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status = ?
                ORDER BY
                    CASE priority
                        WHEN 'high' THEN 1
                        WHEN 'normal' THEN 2
                        WHEN 'low' THEN 3
                    END,
                    queued_at ASC
                LIMIT ?
                """,
                (status.value, limit),
            ).fetchall()
            return [self._row_to_model(row) for row in rows]

    def update_status(
        self,
        job_id: str,
        new_status: JobStatus,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> bool:
        """Update job status and timing fields."""
        with self.db.connection() as conn:
            if new_status == JobStatus.RUNNING and started_at:
                cursor = conn.execute(
                    "UPDATE jobs SET status = ?, started_at = ? WHERE job_id = ?",
                    (new_status.value, started_at.isoformat(), job_id),
                )
            elif new_status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                cursor = conn.execute(
                    "UPDATE jobs SET status = ?, finished_at = ? WHERE job_id = ?",
                    (new_status.value, (finished_at or datetime.now()).isoformat(), job_id),
                )
            else:
                cursor = conn.execute(
                    "UPDATE jobs SET status = ? WHERE job_id = ?",
                    (new_status.value, job_id),
                )
            conn.commit()
            return cursor.rowcount > 0

    def _row_to_model(self, row: sqlite3.Row) -> JobEnvelope:
        """Convert database row to JobEnvelope model."""
        snapshot_data = json.loads(row["execution_snapshot_json"])
        execution_snapshot = ExecutionSnapshot(
            recipe_ref=RecipeRef(**snapshot_data["recipe_ref"]),
            policy_ref=PolicyRef(**snapshot_data["policy_ref"]),
            execution_strategy=snapshot_data.get("execution_strategy", "one_shot"),
            model_tier=snapshot_data.get("model_tier", "balanced"),
            config_hash=snapshot_data["config_hash"],
        )
        return JobEnvelope(
            job_id=row["job_id"],
            work_item_id=row["work_item_id"],
            repo_id=row["repo_id"],
            job_type=JobType(row["job_type"]),
            priority=JobPriority(row["priority"]),
            status=JobStatus(row["status"]),
            execution_snapshot=execution_snapshot,
            budget=row["budget"],
            timeout_seconds=row["timeout_seconds"],
            spawn_depth=row["spawn_depth"],
            parent_job_id=row["parent_job_id"],
            queued_at=datetime.fromisoformat(row["queued_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        )


class RunStore:
    """Storage operations for RunRecord entities."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, run: RunRecord) -> None:
        """Save or update a run record."""
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id, job_id, worker_type, state, branch_name, workspace_path,
                    total_cost, retry_count, failure_reason, manifest_path,
                    security_review_passed, artifact_refs, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.job_id,
                    run.worker_type,
                    run.state.value,
                    run.branch_name,
                    run.workspace_path,
                    run.total_cost,
                    run.retry_count,
                    run.failure_reason,
                    run.manifest_path,
                    1 if run.security_review_passed else 0,
                    json.dumps(run.artifact_refs),
                    run.created_at.isoformat(),
                    run.updated_at.isoformat(),
                ),
            )
            conn.commit()

    def get(self, run_id: str) -> RunRecord | None:
        """Get a run by ID."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_model(row)

    def list_by_job(self, job_id: str) -> list[RunRecord]:
        """List all runs for a job."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE job_id = ? ORDER BY created_at DESC",
                (job_id,),
            ).fetchall()
            return [self._row_to_model(row) for row in rows]

    def update_state(self, run_id: str, new_state: RunState) -> bool:
        """Update run state."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "UPDATE runs SET state = ?, updated_at = ? WHERE run_id = ?",
                (new_state.value, datetime.now().isoformat(), run_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_manifest_path(self, run_id: str, manifest_path: str) -> bool:
        """Set the manifest_path for a run."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "UPDATE runs SET manifest_path = ?, updated_at = ? WHERE run_id = ?",
                (manifest_path, datetime.now().isoformat(), run_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_recent(self, limit: int = 50) -> list[RunRecord]:
        """List recent runs ordered by creation time."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_model(row) for row in rows]

    def _row_to_model(self, row: sqlite3.Row) -> RunRecord:
        """Convert database row to RunRecord model."""
        return RunRecord(
            run_id=row["run_id"],
            job_id=row["job_id"],
            worker_type=row["worker_type"],
            state=RunState(row["state"]),
            branch_name=row["branch_name"],
            workspace_path=row["workspace_path"],
            total_cost=row["total_cost"],
            retry_count=row["retry_count"],
            failure_reason=row["failure_reason"],
            manifest_path=row["manifest_path"],
            security_review_passed=bool(row["security_review_passed"]),
            artifact_refs=json.loads(row["artifact_refs"]) if row["artifact_refs"] else [],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


class EventStore:
    """Storage operations for EventEnvelope entities."""

    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _sanitize_payload_for_storage(payload: dict[str, Any]) -> dict[str, Any]:
        """Redact secrets from event payloads before persisting to DB."""
        from foxhound.sanitization.pipeline import redact_secrets

        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, str):
                sanitized[key], _ = redact_secrets(value)
            elif isinstance(value, dict):
                sanitized[key] = EventStore._sanitize_payload_for_storage(value)
            else:
                sanitized[key] = value
        return sanitized

    def save(self, event: EventEnvelope) -> None:
        """Save an event with payload redaction."""
        safe_payload = self._sanitize_payload_for_storage(event.payload)
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    event_id, event_type, repo_id, run_id, job_id,
                    severity, payload_json, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type.value,
                    event.repo_id,
                    event.run_id,
                    event.job_id,
                    event.severity.value,
                    json.dumps(safe_payload),
                    event.timestamp.isoformat(),
                ),
            )
            conn.commit()

    def get(self, event_id: str) -> EventEnvelope | None:
        """Get an event by ID."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_model(row)

    def list_by_run(self, run_id: str, limit: int = 100) -> list[EventEnvelope]:
        """List events for a run."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE run_id = ? ORDER BY occurred_at ASC LIMIT ?",
                (run_id, limit),
            ).fetchall()
            return [self._row_to_model(row) for row in rows]

    def list_recent(
        self,
        event_type: EventType | None = None,
        limit: int = 100,
    ) -> list[EventEnvelope]:
        """List recent events with optional type filter."""
        query = "SELECT * FROM events"
        params: list[Any] = []

        if event_type is not None:
            query += " WHERE event_type = ?"
            params.append(event_type.value)

        query += " ORDER BY occurred_at DESC LIMIT ?"
        params.append(limit)

        with self.db.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_model(row) for row in rows]

    def _row_to_model(self, row: sqlite3.Row) -> EventEnvelope:
        """Convert database row to EventEnvelope model."""
        return EventEnvelope(
            event_id=row["event_id"],
            event_type=EventType(row["event_type"]),
            timestamp=datetime.fromisoformat(row["occurred_at"]),
            source_module="storage",  # Not stored, use placeholder
            run_id=row["run_id"],
            repo_id=row["repo_id"],
            job_id=row["job_id"],
            severity=EventSeverity(row["severity"]),
            payload=json.loads(row["payload_json"]) if row["payload_json"] else {},
        )


class OpportunityStore:
    """Storage operations for OpportunityDiscoveryItem entities."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, item: OpportunityDiscoveryItem) -> None:
        """Save or update an opportunity item."""
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO opportunity_items (
                    opportunity_id, title, description, source_type, source_url,
                    source_fingerprint, trust_level, state, credibility_score,
                    novelty_score, actionability_score, business_value_score,
                    evidence, tags, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.opportunity_id,
                    item.title,
                    item.description,
                    item.source_type,
                    item.source_url,
                    item.source_fingerprint,
                    item.trust_level.value,
                    item.state.value,
                    item.credibility_score,
                    item.novelty_score,
                    item.actionability_score,
                    item.business_value_score,
                    json.dumps(item.evidence),
                    json.dumps(item.tags),
                    item.created_at.isoformat(),
                    item.updated_at.isoformat(),
                ),
            )
            conn.commit()

    def get(self, opportunity_id: str) -> OpportunityDiscoveryItem | None:
        """Get an opportunity by ID."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM opportunity_items WHERE opportunity_id = ?",
                (opportunity_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_model(row)

    def list_by_state(
        self, state: OpportunityState, limit: int = 100
    ) -> list[OpportunityDiscoveryItem]:
        """List opportunities by state."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM opportunity_items WHERE state = ? ORDER BY updated_at DESC LIMIT ?",
                (state.value, limit),
            ).fetchall()
            return [self._row_to_model(row) for row in rows]

    def _row_to_model(self, row: sqlite3.Row) -> OpportunityDiscoveryItem:
        """Convert database row to OpportunityDiscoveryItem model."""
        return OpportunityDiscoveryItem(
            opportunity_id=row["opportunity_id"],
            title=row["title"],
            description=row["description"] or "",
            source_type=row["source_type"],
            source_url=row["source_url"],
            source_fingerprint=row["source_fingerprint"],
            trust_level=TrustLevel(row["trust_level"]),
            state=OpportunityState(row["state"]),
            credibility_score=row["credibility_score"],
            novelty_score=row["novelty_score"],
            actionability_score=row["actionability_score"],
            business_value_score=row["business_value_score"],
            evidence=json.loads(row["evidence"]) if row["evidence"] else {},
            tags=json.loads(row["tags"]) if row["tags"] else [],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


class RecipeStore:
    """Storage operations for recipe version records."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(
        self,
        name: str,
        version: str,
        content_hash: str,
        source_scope: str = "builtin",
        content_path: str | None = None,
    ) -> None:
        """Save a recipe version record."""
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO recipe_versions
                    (name, version, content_hash, source_scope, content_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, version, content_hash, source_scope, content_path,
                 datetime.now().isoformat()),
            )
            conn.commit()

    def get(self, name: str, version: str) -> dict[str, Any] | None:
        """Get a recipe version by name and version."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM recipe_versions WHERE name = ? AND version = ?",
                (name, version),
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def get_latest(self, name: str) -> dict[str, Any] | None:
        """Get the latest version of a recipe by name."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM recipe_versions WHERE name = ? ORDER BY created_at DESC LIMIT 1",
                (name,),
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def list_all(self) -> list[dict[str, Any]]:
        """List all recipe versions."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM recipe_versions ORDER BY name, created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]


class PolicyStore:
    """Storage operations for policy version records."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(
        self,
        name: str,
        version: str,
        content_hash: str,
        source_scope: str = "builtin",
        content_path: str | None = None,
    ) -> None:
        """Save a policy version record."""
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO policy_versions
                    (name, version, content_hash, source_scope, content_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, version, content_hash, source_scope, content_path,
                 datetime.now().isoformat()),
            )
            conn.commit()

    def get(self, name: str, version: str) -> dict[str, Any] | None:
        """Get a policy version by name and version."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM policy_versions WHERE name = ? AND version = ?",
                (name, version),
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def get_latest(self, name: str) -> dict[str, Any] | None:
        """Get the latest version of a policy by name."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM policy_versions WHERE name = ? ORDER BY created_at DESC LIMIT 1",
                (name,),
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def list_all(self) -> list[dict[str, Any]]:
        """List all policy versions."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM policy_versions ORDER BY name, created_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]


class ArtifactStore:
    """Storage operations for artifact index records."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(
        self,
        artifact_id: str,
        run_id: str,
        artifact_type: str,
        path: str,
        size_bytes: int = 0,
        retention_class: str = "B",
        pinned: bool = False,
    ) -> None:
        """Save an artifact index entry."""
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO artifacts (
                    artifact_id, run_id, artifact_type, path, size_bytes,
                    retention_class, pinned, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    run_id,
                    artifact_type,
                    path,
                    size_bytes,
                    retention_class,
                    1 if pinned else 0,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        """Get an artifact by ID."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def list_by_run(self, run_id: str) -> list[dict[str, Any]]:
        """List all artifacts for a run."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at DESC",
                (run_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_by_retention_class(self, retention_class: str) -> list[dict[str, Any]]:
        """List artifacts by retention class."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE retention_class = ? ORDER BY created_at ASC",
                (retention_class,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_unpinned_before(
        self, retention_class: str, cutoff_iso: str
    ) -> list[dict[str, Any]]:
        """List unpinned artifacts older than cutoff for a retention class."""
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM artifacts
                WHERE retention_class = ? AND pinned = 0 AND created_at < ?
                ORDER BY created_at ASC
                """,
                (retention_class, cutoff_iso),
            ).fetchall()
            return [dict(row) for row in rows]

    def set_pinned(self, artifact_id: str, pinned: bool) -> bool:
        """Pin or unpin an artifact."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "UPDATE artifacts SET pinned = ? WHERE artifact_id = ?",
                (1 if pinned else 0, artifact_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete(self, artifact_id: str) -> bool:
        """Delete an artifact index entry."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def count_by_class(self) -> dict[str, int]:
        """Count artifacts by retention class."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT retention_class, COUNT(*) as cnt FROM artifacts GROUP BY retention_class"
            ).fetchall()
            return {row["retention_class"]: row["cnt"] for row in rows}

    def total_size_by_class(self) -> dict[str, int]:
        """Sum artifact sizes by retention class."""
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT retention_class, COALESCE(SUM(size_bytes), 0) as total
                FROM artifacts GROUP BY retention_class
                """
            ).fetchall()
            return {row["retention_class"]: row["total"] for row in rows}


class RuleSuggestionStore:
    """Storage operations for rule suggestion records."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(
        self,
        suggestion_id: str,
        rule_name: str,
        rule_type: str,
        condition: str,
        action: str,
        repo_id: str | None = None,
        evidence: str | None = None,
        confidence: float = 0.0,
        suggested_by: str = "analyzer",
    ) -> None:
        """Save a rule suggestion."""
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO rule_suggestions
                    (suggestion_id, repo_id, rule_name, rule_type, condition, action,
                     evidence, confidence, state, suggested_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_review', ?, ?)
                """,
                (suggestion_id, repo_id, rule_name, rule_type, condition, action,
                 evidence, confidence, suggested_by, datetime.now().isoformat()),
            )
            conn.commit()

    def get(self, suggestion_id: str) -> dict[str, Any] | None:
        """Get a rule suggestion by ID."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM rule_suggestions WHERE suggestion_id = ?",
                (suggestion_id,),
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def list_by_state(self, state: str = "pending_review") -> list[dict[str, Any]]:
        """List rule suggestions by state."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM rule_suggestions WHERE state = ? ORDER BY created_at DESC",
                (state,),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_state(
        self,
        suggestion_id: str,
        new_state: str,
        reviewed_by: str | None = None,
    ) -> bool:
        """Update a rule suggestion's state."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE rule_suggestions
                SET state = ?, reviewed_by = ?, reviewed_at = ?
                WHERE suggestion_id = ?
                """,
                (new_state, reviewed_by, datetime.now().isoformat(), suggestion_id),
            )
            conn.commit()
            return cursor.rowcount > 0


class RawOpportunityStore:
    """Storage operations for scout raw opportunity staging records."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert(
        self,
        raw_id: str,
        source: str,
        source_url: str,
        source_id: str,
        title: str,
        raw_payload: str,
        fetched_at: str,
        expires_at: str,
        dedupe_hash: str,
    ) -> bool:
        """Insert or update a raw opportunity. Returns True if new, False if updated."""
        with self.db.connection() as conn:
            existing = conn.execute(
                "SELECT raw_id FROM scout_raw_opportunities WHERE dedupe_hash = ?",
                (dedupe_hash,),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE scout_raw_opportunities
                    SET raw_payload = ?, fetched_at = ?, title = ?, source_url = ?
                    WHERE dedupe_hash = ?
                    """,
                    (raw_payload, fetched_at, title, source_url, dedupe_hash),
                )
                conn.commit()
                return False

            conn.execute(
                """
                INSERT INTO scout_raw_opportunities (
                    raw_id, source, source_url, source_id, title,
                    raw_payload, fetched_at, expires_at, scored, dedupe_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (raw_id, source, source_url, source_id, title,
                 raw_payload, fetched_at, expires_at, dedupe_hash),
            )
            conn.commit()
            return True

    def get(self, raw_id: str) -> dict[str, Any] | None:
        """Get a raw opportunity by ID."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM scout_raw_opportunities WHERE raw_id = ?",
                (raw_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_unscored(self, source: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """List unscored raw opportunities, optionally filtered by source."""
        query = "SELECT * FROM scout_raw_opportunities WHERE scored = 0"
        params: list[Any] = []
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY fetched_at DESC LIMIT ?"
        params.append(limit)

        with self.db.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def mark_scored(self, raw_id: str) -> bool:
        """Mark a raw opportunity as scored."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "UPDATE scout_raw_opportunities SET scored = 1 WHERE raw_id = ?",
                (raw_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def prune_expired(self) -> int:
        """Remove expired raw opportunities. Returns count deleted."""
        now = datetime.now().isoformat()
        with self.db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM scout_raw_opportunities WHERE expires_at < ?",
                (now,),
            )
            conn.commit()
            return cursor.rowcount

    def count_by_source(self) -> dict[str, int]:
        """Count raw opportunities by source."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT source, COUNT(*) as cnt FROM scout_raw_opportunities GROUP BY source"
            ).fetchall()
            return {row["source"]: row["cnt"] for row in rows}

    def get_fetch_metadata(self, source: str) -> dict[str, Any] | None:
        """Get fetch metadata for a source."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM scout_fetch_metadata WHERE source = ?",
                (source,),
            ).fetchone()
            return dict(row) if row else None

    def update_fetch_metadata(
        self,
        source: str,
        items_fetched: int = 0,
        rate_limit_hits: int = 0,
    ) -> None:
        """Update fetch metadata for a source."""
        now = datetime.now().isoformat()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO scout_fetch_metadata
                    (source, last_fetched_at, items_fetched, rate_limit_hits)
                VALUES (?, ?, ?, ?)
                """,
                (source, now, items_fetched, rate_limit_hits),
            )
            conn.commit()
