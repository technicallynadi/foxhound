"""Dispatch API — Agent job lifecycle: list, detail, approve, deny, cancel, DAG view.

Phase 2 of Agent Dispatch (FOX-66 / design plan FOX-58).

NOTE: Endpoints that query parent_job_id, agent_type, user_id (on FoxhoundJob),
approval_required, approval_status, and result_json are gated behind Phase 0
DB migrations (FOX-64). Those columns are marked with # PHASE-0-REQUIRED comments.
The router is fully wired and all auth/response shapes are final — only the
inner query bodies need updating once Phase 0 lands.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.foxhound_job import FoxhoundJob
from app.db.session import get_db
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/api/v1/dispatch", tags=["dispatch"])

# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class DispatchJobSummary(BaseModel):
    id: str
    job_type: str
    agent_type: str | None          # PHASE-0-REQUIRED
    status: str
    priority: int
    approval_required: bool         # PHASE-0-REQUIRED
    approval_status: str | None     # PHASE-0-REQUIRED
    parent_job_id: str | None       # PHASE-0-REQUIRED
    child_count: int                # PHASE-0-REQUIRED (stub returns 0 until parent_job_id lands)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    canceled_at: datetime | None
    error_message: str | None


class DispatchJobDetail(DispatchJobSummary):
    payload_json: str
    context_snapshot_json: str | None   # PHASE-0-REQUIRED
    result_json: str | None             # PHASE-0-REQUIRED
    children: list[DispatchJobSummary]


class DAGNode(BaseModel):
    id: str
    job_type: str
    agent_type: str | None      # PHASE-0-REQUIRED
    status: str
    children: list[DAGNode]

DAGNode.model_rebuild()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_job(job: FoxhoundJob) -> dict:
    """Map FoxhoundJob ORM row to DispatchJobSummary dict.

    Phase-0 columns are read with getattr(..., None) so this works before
    and after the migration.
    """
    return {
        "id": job.id,
        "job_type": job.job_type,
        "agent_type": getattr(job, "agent_type", None),
        "status": job.status,
        "priority": job.priority,
        "approval_required": bool(getattr(job, "approval_required", False)),
        "approval_status": getattr(job, "approval_status", None),
        "parent_job_id": getattr(job, "parent_job_id", None),
        # PHASE-0-REQUIRED: replace with real child count query once parent_job_id exists
        "child_count": 0,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
        "canceled_at": job.canceled_at,
        "error_message": job.error_message,
    }


def _serialize_job_detail(job: FoxhoundJob, children: list[FoxhoundJob]) -> dict:
    return {
        **_serialize_job(job),
        "payload_json": job.payload_json,
        "context_snapshot_json": getattr(job, "context_snapshot_json", None),
        "result_json": getattr(job, "result_json", None),
        "children": [_serialize_job(c) for c in children],
    }


def _build_dag_node(job: FoxhoundJob, children: list[FoxhoundJob]) -> dict:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "agent_type": getattr(job, "agent_type", None),
        "status": job.status,
        "children": [
            {"id": c.id, "job_type": c.job_type, "agent_type": getattr(c, "agent_type", None),
             "status": c.status, "children": []}
            for c in children
        ],
    }


# ---------------------------------------------------------------------------
# GET /api/v1/dispatch/jobs
# List all active dispatch jobs for the authenticated user.
# ---------------------------------------------------------------------------

@router.get("/jobs", response_model=list[DispatchJobSummary])
async def list_dispatch_jobs(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return active (non-completed, non-canceled) dispatch jobs for the user."""
    user_id = user["user_id"]

    # PHASE-0-REQUIRED: filter by user_id column on FoxhoundJob.
    # For now, user_id is embedded in payload_json — full filter lands with Phase 0.
    stmt = (
        select(FoxhoundJob)
        .where(FoxhoundJob.status.notin_(["completed", "canceled", "failed"]))
        .order_by(FoxhoundJob.priority.desc(), FoxhoundJob.created_at.asc())
        .limit(100)
    )
    result = await db.execute(stmt)
    jobs = result.scalars().all()

    # PHASE-0-REQUIRED: replace payload scan with `FoxhoundJob.user_id == user_id`
    user_jobs = [j for j in jobs if _job_belongs_to_user(j, user_id)]
    return [_serialize_job(j) for j in user_jobs]


# ---------------------------------------------------------------------------
# GET /api/v1/dispatch/jobs/{job_id}
# Job detail with immediate children.
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}", response_model=DispatchJobDetail)
async def get_dispatch_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_job_for_user(job_id, user["user_id"], db)

    # PHASE-0-REQUIRED: replace with FoxhoundJob.parent_job_id == job_id
    children = await _get_children(job_id, db)
    return _serialize_job_detail(job, children)


# ---------------------------------------------------------------------------
# POST /api/v1/dispatch/jobs/{job_id}/approve
# Approve a job that is awaiting_approval.
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/approve", response_model=DispatchJobSummary)
async def approve_dispatch_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_job_for_user(job_id, user["user_id"], db)

    # PHASE-0-REQUIRED: check approval_required and approval_status columns
    approval_status = getattr(job, "approval_status", None)
    if job.status != "awaiting_approval" or approval_status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is not awaiting approval (status={job.status})",
        )

    # Approve: transition to queued so worker_loop picks it up
    # PHASE-0-REQUIRED: set job.approval_status = "approved"
    _set_attr(job, "approval_status", "approved")
    job.status = "queued"
    job.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(job)
    return _serialize_job(job)


# ---------------------------------------------------------------------------
# POST /api/v1/dispatch/jobs/{job_id}/deny
# Deny a job that is awaiting_approval.
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/deny", response_model=DispatchJobSummary)
async def deny_dispatch_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_job_for_user(job_id, user["user_id"], db)

    approval_status = getattr(job, "approval_status", None)
    if job.status != "awaiting_approval" or approval_status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is not awaiting approval (status={job.status})",
        )

    # PHASE-0-REQUIRED: set job.approval_status = "denied", cancelled_by = user_id
    _set_attr(job, "approval_status", "denied")
    _set_attr(job, "cancelled_by", user["user_id"])
    job.status = "canceled"
    job.canceled_at = datetime.now(UTC)
    job.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(job)
    return _serialize_job(job)


# ---------------------------------------------------------------------------
# POST /api/v1/dispatch/jobs/{job_id}/cancel
# Cancel a queued or running job.
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/cancel", response_model=DispatchJobSummary)
async def cancel_dispatch_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_job_for_user(job_id, user["user_id"], db)

    if job.status in ("completed", "canceled", "failed"):
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is already terminal (status={job.status})",
        )

    # PHASE-0-REQUIRED: set job.cancelled_by = user_id
    _set_attr(job, "cancelled_by", user["user_id"])
    job.status = "canceled"
    job.canceled_at = datetime.now(UTC)
    job.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(job)
    return _serialize_job(job)


# ---------------------------------------------------------------------------
# GET /api/v1/dispatch/dag/{root_job_id}
# Full DAG tree rooted at root_job_id (two levels deep, per design plan).
# ---------------------------------------------------------------------------

@router.get("/dag/{root_job_id}", response_model=DAGNode)
async def get_dispatch_dag(
    root_job_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    root = await _get_job_for_user(root_job_id, user["user_id"], db)

    # PHASE-0-REQUIRED: query by parent_job_id once column exists
    children = await _get_children(root_job_id, db)
    return _build_dag_node(root, children)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _job_belongs_to_user(job: FoxhoundJob, user_id: str) -> bool:
    """Temporary user filter until Phase 0 adds user_id column."""
    # PHASE-0-REQUIRED: replace body with `return job.user_id == user_id`
    import json as _json
    try:
        payload = _json.loads(job.payload_json or "{}")
        return payload.get("user_id") == user_id or payload.get("run_id", "").startswith(user_id + "_")
    except Exception:
        return False


async def _get_job_for_user(job_id: str, user_id: str, db: AsyncSession) -> FoxhoundJob:
    result = await db.execute(select(FoxhoundJob).where(FoxhoundJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if not _job_belongs_to_user(job, user_id):
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


async def _get_children(parent_job_id: str, db: AsyncSession) -> list[FoxhoundJob]:
    """Fetch immediate children of a job.

    PHASE-0-REQUIRED: replace body with:
        result = await db.execute(
            select(FoxhoundJob).where(FoxhoundJob.parent_job_id == parent_job_id)
        )
        return result.scalars().all()
    """
    # Pre-Phase-0 stub: no children queryable yet
    return []


def _set_attr(obj: object, attr: str, value: object) -> None:
    """Set an attribute only if it exists on the model (Phase-0 guard)."""
    if hasattr(obj, attr):
        setattr(obj, attr, value)
