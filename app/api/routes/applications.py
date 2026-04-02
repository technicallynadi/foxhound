"""Applications API routes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.application import Application
from app.db.models.foxhound_brief import FoxhoundBrief
from app.db.models.job_listing import JobListing
from app.db.session import get_db
from app.api.rate_limit import rate_limit
from app.services.apply.orchestrator import ApplicationOrchestrator
from app.services.auth_service import get_current_user
from app.services.discovery.ats_detector import detect_ats

router = APIRouter(prefix="/api/v1/applications", tags=["applications"])

orchestrator = ApplicationOrchestrator()


class ApplyBody(BaseModel):
    job_id: str
    trigger: str = "manual"


class ManualTrackBody(BaseModel):
    company: str
    title: str
    apply_url: str
    location: str | None = None
    notes: str | None = None
    submitted_at: datetime | None = None


@router.post("")
async def create_application(
    body: ApplyBody,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(rate_limit("apply", 5, 60)),  # 5 applies/min burst protection
):
    """Trigger a new job application via TinyFish."""
    user_id = user["user_id"]
    try:
        app = await orchestrator.apply(
            db=db,
            user_id=user_id,
            job_id=body.job_id,
            trigger=body.trigger,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {
        "application_id": app.id,
        "status": app.status,
        "tinyfish_status": app.tinyfish_status,
    }


@router.post("/manual-track")
async def create_manual_tracked_application(
    body: ManualTrackBody,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Track an application the user already submitted outside Foxhound."""
    user_id = user["user_id"]
    company = body.company.strip()
    title = body.title.strip()
    apply_url = body.apply_url.strip()

    if not company or not title or not apply_url:
        raise HTTPException(400, "Company, title, and apply URL are required")

    existing_job = (
        await db.execute(
            select(JobListing).where(
                JobListing.company == company,
                JobListing.title == title,
                JobListing.apply_url == apply_url,
            )
        )
    ).scalar_one_or_none()

    job = existing_job
    if not job:
        ats_type = detect_ats(apply_url)
        job = JobListing(
            id=str(uuid4()),
            external_id=None,
            title=title,
            company=company,
            company_url=None,
            description=body.notes or "Manually tracked application imported by user.",
            description_html=None,
            location=body.location.strip() if body.location else None,
            remote_type=None,
            salary_min=None,
            salary_max=None,
            salary_currency=None,
            seniority=None,
            required_skills_json="[]",
            preferred_skills_json="[]",
            required_years=None,
            requires_clearance=False,
            visa_sponsorship=None,
            apply_url=apply_url,
            ats_type=ats_type,
            auto_apply_supported=False,
            source="manual_track",
            source_url=apply_url,
            posted_at=None,
            expires_at=None,
            status="active",
            dedup_hash=None,
            custom_questions_json=None,
            ghost_score=None,
            ghost_risk=None,
            ghost_factors_json=None,
            ghost_checked_at=None,
            repost_count=0,
        )
        db.add(job)
        await db.flush()

    existing_app = (
        await db.execute(
            select(Application).where(
                Application.user_id == user_id,
                Application.job_id == job.id,
            )
        )
    ).scalar_one_or_none()
    if existing_app:
        raise HTTPException(400, "This application is already being tracked")

    submitted_at = body.submitted_at or datetime.now(timezone.utc)
    app = Application(
        id=str(uuid4()),
        user_id=user_id,
        job_id=job.id,
        match_id=None,
        status="submitted",
        trigger="manual_track",
        phase="done",
        submission_method="manual",
        scan_result_json=None,
        scan_tinyfish_run_id=None,
        fields_filled_json="[]",
        custom_answers_json="[]",
        cover_letter=None,
        resume_version_path=None,
        tinyfish_run_id=None,
        tinyfish_status=None,
        tinyfish_duration_ms=None,
        tinyfish_streaming_url=None,
        pre_submit_screenshot_path=None,
        screenshot_storage_path=None,
        screenshot_captured_at=None,
        error_type=None,
        error_message=None,
        retry_count=0,
        max_retries=0,
        followup_day3_sent=False,
        followup_day7_sent=False,
        followup_day14_sent=False,
        notification_sent=False,
        notification_sent_at=None,
        posting_status="unknown",
        last_watchdog_check_at=None,
        posting_last_text=None,
        posting_diff_summary=None,
        watchdog_enabled=True,
        submitted_at=submitted_at,
    )
    db.add(app)
    await db.commit()

    return {
        "application_id": app.id,
        "status": app.status,
        "trigger": app.trigger,
        "job_id": job.id,
    }


@router.get("")
async def list_applications(
    user: dict = Depends(get_current_user),
    status: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List user's applications."""
    user_id = user["user_id"]
    offset = (page - 1) * per_page

    query = (
        select(Application, JobListing)
        .join(JobListing, Application.job_id == JobListing.id)
        .where(Application.user_id == user_id)
    )
    if status:
        query = query.where(Application.status == status)

    query = query.order_by(Application.created_at.desc()).offset(offset).limit(per_page)

    result = await db.execute(query)
    rows = result.all()
    application_ids = [app.id for app, _ in rows]

    brief_status_by_application: dict[str, str] = {}
    if application_ids:
        brief_rows = await db.execute(
            select(FoxhoundBrief.application_id, FoxhoundBrief.status).where(
                FoxhoundBrief.user_id == user_id,
                FoxhoundBrief.application_id.in_(application_ids),
            )
        )
        brief_status_by_application = {
            application_id: brief_status
            for application_id, brief_status in brief_rows.all()
        }

    count_query = (
        select(func.count())
        .select_from(Application)
        .where(Application.user_id == user_id)
    )
    if status:
        count_query = count_query.where(Application.status == status)
    total = (await db.execute(count_query)).scalar() or 0

    items = []
    for app, job in rows:
        # Generate signed URLs for screenshots if they exist
        screenshot_signed = None
        pre_submit_screenshot_signed = None
        from app.services.storage.supabase_storage import get_signed_url
        if app.screenshot_storage_path:
            try:
                parts = app.screenshot_storage_path.split("/", 1)
                if len(parts) == 2:
                    screenshot_signed = await get_signed_url(parts[0], parts[1])
            except Exception:
                pass
        if app.pre_submit_screenshot_path:
            try:
                parts = app.pre_submit_screenshot_path.split("/", 1)
                if len(parts) == 2:
                    pre_submit_screenshot_signed = await get_signed_url(parts[0], parts[1])
            except Exception:
                pass

        items.append({
            "id": app.id,
            "status": app.status,
            "trigger": app.trigger,
            "brief_ready": app.id in brief_status_by_application,
            "brief_status": brief_status_by_application.get(app.id),
            "job": {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "ats_type": job.ats_type,
            },
            "tinyfish_status": app.tinyfish_status,
            "posting_status": getattr(app, "posting_status", None),
            "posting_diff_summary": getattr(app, "posting_diff_summary", None),
            "last_watchdog_check_at": (
                app.last_watchdog_check_at.isoformat()
                if getattr(app, "last_watchdog_check_at", None)
                else None
            ),
            "screenshot_url": screenshot_signed,
            "pre_submit_screenshot_url": pre_submit_screenshot_signed,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
            "created_at": app.created_at.isoformat() if app.created_at else None,
        })

    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/stats")
async def application_stats(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get application statistics."""
    user_id = user["user_id"]
    from app.db.models.user_profile import UserProfile

    # Get profile for tier/limits
    profile_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()

    # Count by status
    result = await db.execute(
        select(Application.status, func.count())
        .where(Application.user_id == user_id)
        .group_by(Application.status)
    )
    status_counts = dict(result.all())

    return {
        "total": sum(status_counts.values()),
        "submitted": status_counts.get("submitted", 0),
        "confirmed": status_counts.get("confirmed", 0),
        "failed": status_counts.get("failed", 0),
        "needs_manual": status_counts.get("needs_manual", 0),
        "in_progress": status_counts.get("in_progress", 0),
        "this_month": profile.applications_this_month if profile else 0,
        "monthly_limit": profile.monthly_apply_limit if profile else 0,
        "tier": profile.tier if profile else "free",
    }


@router.get("/{application_id}")
async def get_application(
    application_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full application detail."""
    user_id = user["user_id"]
    result = await db.execute(
        select(Application, JobListing)
        .join(JobListing, Application.job_id == JobListing.id)
        .where(Application.id == application_id, Application.user_id == user_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(404, "Application not found")

    app, job = row
    return {
        "id": app.id,
        "status": app.status,
        "trigger": app.trigger,
        "job": {
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "apply_url": job.apply_url,
            "ats_type": job.ats_type,
        },
        "fields_filled": json.loads(app.fields_filled_json or "[]"),
        "custom_answers": json.loads(app.custom_answers_json or "[]"),
        "tinyfish_status": app.tinyfish_status,
        "tinyfish_duration_ms": app.tinyfish_duration_ms,
        "screenshot_url": app.screenshot_storage_path,
        "pre_submit_screenshot_url": app.pre_submit_screenshot_path,
        "error_type": app.error_type,
        "error_message": app.error_message,
        "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
        "created_at": app.created_at.isoformat() if app.created_at else None,
    }


@router.patch("/{application_id}/archive")
async def archive_application(
    application_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Archive an application so Foxhound stops prioritizing it."""
    user_id = user["user_id"]
    result = await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.user_id == user_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(404, "Application not found")

    app.status = "canceled"
    app.watchdog_enabled = False
    await db.commit()

    return {"ok": True, "application_id": app.id, "status": app.status}
