"""Application tools: apply, answer questions, check status."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.application import Application
from app.db.models.application_question import ApplicationQuestion
from app.db.models.job_listing import JobListing
from app.db.models.job_match import JobMatch
from app.db.models.user_profile import UserProfile
from app.services.agent.registry import tool
from app.services.agent.utils.profile_filler import update_answer_bank
from app.services.application_guidance import (
    build_application_context,
    build_recommended_next_action,
)

logger = logging.getLogger(__name__)


@tool(
    name="apply_to_job",
    description=(
        "Start an application to a specific job. Use this when the user wants "
        "to apply. Specify by job_id, company name/title to fuzzy match, or "
        "a direct job URL (e.g. 'apply to https://jobs.ashbyhq.com/...'). "
        "Returns immediately — the form scan runs in the background. "
        "If the form has questions, they'll be included in the result."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "Exact job ID if known"},
            "company_name": {"type": "string", "description": "Company name (fuzzy match)"},
            "job_title": {"type": "string", "description": "Job title (fuzzy match)"},
            "job_url": {"type": "string", "description": "Direct job application URL"},
        },
    },
    permissions=["apply"],
    side_effects=True,
    requires_confirmation=False,
    cost_estimate="medium",
)
async def apply_to_job(db: AsyncSession, user_id: str, params: dict) -> dict:
    job = await _resolve_job(db, params)
    if not job:
        return {"error": "job_not_found", "message": "Could not find that job.",
                "suggestion": "Try searching first with search_jobs."}

    # Skip quality floor for direct URL applications (no match data)
    is_url_apply = bool(params.get("job_url"))

    # Quality floor: check match score before applying
    match_result = await db.execute(
        select(JobMatch).where(JobMatch.user_id == user_id, JobMatch.job_id == job.id)
    )
    match = match_result.scalar_one_or_none()
    match_score = match.match_score if match else None

    profile_result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile or not profile.resume_storage_path:
        return {
            "error": "resume_required",
            "message": (
                "Foxhound can find jobs for you now, but it can't apply until you upload a resume."
            ),
            "suggestion": "Upload a resume in onboarding or profile, then try again.",
        }

    if not is_url_apply and match_score is not None and match_score < 55:
        # Below 55%: skip with gap analysis + suggest alternatives
        alt_result = await db.execute(
            select(JobMatch, JobListing)
            .join(JobListing, JobMatch.job_id == JobListing.id)
            .where(JobMatch.user_id == user_id, JobMatch.match_score >= 70, JobMatch.disqualified is False)
            .order_by(JobMatch.match_score.desc())
            .limit(3)
        )
        alternatives = [
            {"title": j.title, "company": j.company, "match_score": m.match_score}
            for m, j in alt_result.all()
        ]

        # Gap analysis: compare user skills vs job requirements
        gap_analysis = await _analyze_skill_gaps(db, user_id, job)

        return {
            "error": "below_quality_floor",
            "match_score": match_score,
            "message": (
                f"{job.company} — {job.title} is a {match_score}% match. "
                f"Below the 55% floor — applying to weak matches hurts your callback rate."
            ),
            "gap_analysis": gap_analysis,
            "alternatives": alternatives,
            "suggestion": "Here are stronger matches instead." if alternatives else "Try searching for better-fitting roles.",
            "override_available": True,
        }

    # Start the application via orchestrator
    from app.services.apply.orchestrator import ApplicationOrchestrator

    orchestrator = ApplicationOrchestrator()
    try:
        application = await orchestrator.apply(db=db, user_id=user_id, job_id=job.id, trigger="agent")
    except ValueError as e:
        return {"error": "apply_failed", "message": str(e)}

    result: dict = {
        "application_id": application.id,
        "status": application.status,
        "job_title": job.title,
        "company": job.company,
    }

    if application.status == "waiting_user_input":
        # Load pending questions from ApplicationQuestion or from custom_answers
        questions = await _load_pending_questions(db, application.id)
        if questions:
            result["pending_questions"] = questions
            result["message"] = (
                f"Scanning {job.company} — {job.title}. "
                f"The form has {len(questions)} question(s) that need your input."
            )
        else:
            result["message"] = f"Application to {job.company} is waiting for input."
    elif application.status == "submitted":
        result["message"] = f"Applied to {job.company} — {job.title}. Application submitted."
        if application.tinyfish_streaming_url:
            result["streaming_url"] = application.tinyfish_streaming_url
        if application.pre_submit_screenshot_path:
            result["pre_submit_screenshot"] = application.pre_submit_screenshot_path
        if application.screenshot_storage_path:
            result["screenshot"] = application.screenshot_storage_path
    elif application.status == "failed":
        result["message"] = f"Application to {job.company} failed: {application.error_message or application.error_type}"
    elif application.status == "needs_manual":
        result["message"] = (
            f"This application needs manual completion ({application.error_type}). "
            f"Apply here: {job.apply_url}"
        )
        result["apply_url"] = job.apply_url
    elif application.status == "scanning":
        result["message"] = f"Scanning the application form for {job.company} — {job.title}."
    else:
        result["message"] = f"Application started. Status: {application.status}"

    # Report auto-filled fields
    auto_filled = json.loads(application.custom_answers_json or "[]")
    auto_only = [a for a in auto_filled if not a.get("needs_approval")]
    if auto_only:
        result["auto_filled"] = [{"field": a["question"], "value": a["answer"][:50]} for a in auto_only]

    context = build_application_context(application, job)
    result["application_context"] = context
    result["recommended_next_action"] = build_recommended_next_action(context)

    return result


@tool(
    name="answer_application_questions",
    description=(
        "Submit answers to pending application form questions. Use this when "
        "the user provides answers. Accepts a structured list of answers with "
        "question index and action (approve draft or provide answer)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "answers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "Question number from the list (0-based: first question is 0, second is 1, etc.)"},
                        "action": {"type": "string", "enum": ["approve", "answer"],
                                   "description": "'approve' to accept draft, 'answer' to provide own"},
                        "answer": {"type": "string", "description": "The answer text (required if action is 'answer')"},
                    },
                    "required": ["index", "action"],
                },
                "description": "List of answers to pending questions",
            },
            "application_id": {"type": "string", "description": "Specific application ID (optional)"},
        },
        "required": ["answers"],
    },
    permissions=["write"],
    side_effects=True,
)
async def answer_application_questions(db: AsyncSession, user_id: str, params: dict) -> dict:
    answers = params.get("answers", [])
    target_app_id = params.get("application_id")

    # Find the application
    if target_app_id:
        app = await db.get(Application, target_app_id)
        if not app or app.user_id != user_id:
            return {"error": "not_found", "message": "Application not found."}
    else:
        result = await db.execute(
            select(Application)
            .where(Application.user_id == user_id, Application.status == "waiting_user_input")
            .order_by(Application.created_at.desc())
            .limit(1)
        )
        app = result.scalar_one_or_none()
        if not app:
            return {"error": "no_pending", "message": "No application waiting for answers.",
                    "suggestion": "Apply to a job first."}

    # Load pending questions
    q_result = await db.execute(
        select(ApplicationQuestion)
        .where(ApplicationQuestion.application_id == app.id, ApplicationQuestion.status == "pending")
        .order_by(ApplicationQuestion.question_index)
    )
    pending = list(q_result.scalars().all())

    if not pending:
        return {"error": "no_questions", "message": "No pending questions for this application."}

    # Get job + profile for answer bank
    job = await db.get(JobListing, app.job_id)
    profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = profile_result.scalar_one_or_none()

    now = datetime.now(UTC)
    for answer_data in answers:
        idx = answer_data.get("index")
        action = answer_data.get("action", "answer")
        text = answer_data.get("answer", "")

        # Agent sends 1-based indices, DB is 0-based — try both
        pq = next((q for q in pending if q.question_index == idx), None)
        if not pq and idx is not None:
            pq = next((q for q in pending if q.question_index == idx - 1), None)
        if not pq:
            continue

        if action == "approve":
            pq.status = "approved"
            pq.final_answer = pq.draft_answer
        else:
            pq.status = "answered"
            pq.final_answer = text

        pq.answered_at = now

        # Update answer bank for reusable answers
        if profile and pq.final_answer:
            update_answer_bank(profile, pq.field_label, pq.final_answer)

    # Check remaining
    remaining_result = await db.execute(
        select(ApplicationQuestion)
        .where(ApplicationQuestion.application_id == app.id, ApplicationQuestion.status == "pending")
        .order_by(ApplicationQuestion.question_index)
    )
    remaining = list(remaining_result.scalars().all())

    if not remaining:
        # All answered — collect answers and update application
        all_q_result = await db.execute(
            select(ApplicationQuestion)
            .where(ApplicationQuestion.application_id == app.id)
            .order_by(ApplicationQuestion.question_index)
        )
        all_qs = list(all_q_result.scalars().all())

        existing = json.loads(app.custom_answers_json or "[]")
        for q in all_qs:
            if q.final_answer:
                existing.append({
                    "question": q.field_label,
                    "answer": q.final_answer,
                    "confidence": 0.9 if q.status == "approved" else 0.8,
                    "needs_approval": False,
                })
        app.custom_answers_json = json.dumps(existing)
        app.phase = "fill"
        app.status = "in_progress"

        await db.commit()

        # Trigger Phase 2 — fill and submit
        company = job.company if job else "this company"
        import logging
        _logger = logging.getLogger(__name__)
        _logger.info("All questions answered for %s — triggering Phase 2 resume_fill", company)
        try:
            from app.services.apply.orchestrator import ApplicationOrchestrator
            orchestrator = ApplicationOrchestrator()
            result_app = await orchestrator.resume_fill(db=db, application_id=app.id)
            _logger.info("Phase 2 complete for %s — status: %s", company, result_app.status)
            resp = {
                "status": result_app.status,
                "application_id": app.id,
                "message": f"Application to {company} — {result_app.status}.",
            }
            if result_app.tinyfish_streaming_url:
                resp["streaming_url"] = result_app.tinyfish_streaming_url
            if result_app.pre_submit_screenshot_path:
                resp["pre_submit_screenshot"] = result_app.pre_submit_screenshot_path
            if result_app.screenshot_storage_path:
                resp["screenshot"] = result_app.screenshot_storage_path
            return resp
        except Exception as e:
            return {
                "status": "all_answered",
                "application_id": app.id,
                "message": f"All questions answered for {company}. Phase 2 failed: {str(e)[:200]}",
            }

    await db.commit()

    # Return remaining questions
    remaining_data = []
    for pq in remaining:
        q: dict = {"index": pq.question_index, "question": pq.field_label}
        if pq.draft_answer:
            q["suggested_answer"] = pq.draft_answer
        remaining_data.append(q)

    company = job.company if job else "this company"
    return {
        "status": "partial",
        "remaining_questions": remaining_data,
        "message": f"Got some answers. Still need {len(remaining)} more for {company}.",
    }


@tool(
    name="check_application_status",
    description=(
        "Check the current status of a job application. Use this when the user "
        "asks about an in-progress application or to see if a pending scan completed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "application_id": {"type": "string", "description": "Application ID to check"},
            "company_name": {"type": "string", "description": "Company name to find the application"},
        },
    },
    permissions=["read"],
    side_effects=False,
)
async def check_application_status(db: AsyncSession, user_id: str, params: dict) -> dict:
    app_id = params.get("application_id")
    company = params.get("company_name", "").lower()

    if app_id:
        app = await db.get(Application, app_id)
        if not app or app.user_id != user_id:
            return {"error": "not_found", "message": "Application not found."}
    elif company:
        result = await db.execute(
            select(Application, JobListing)
            .join(JobListing, Application.job_id == JobListing.id)
            .where(Application.user_id == user_id)
            .order_by(Application.created_at.desc())
        )
        for a, j in result.all():
            if company in (j.company or "").lower():
                app = a
                break
        else:
            return {"error": "not_found", "message": f"No application found for {company}."}
    else:
        # Most recent
        result = await db.execute(
            select(Application).where(Application.user_id == user_id)
            .order_by(Application.created_at.desc()).limit(1)
        )
        app = result.scalar_one_or_none()
        if not app:
            return {"error": "no_applications", "message": "No applications yet."}

    job = await db.get(JobListing, app.job_id)
    data = {
        "application_id": app.id,
        "company": job.company if job else "Unknown",
        "title": job.title if job else "Unknown",
        "status": app.status,
        "phase": app.phase,
        "created_at": app.created_at.isoformat() if app.created_at else None,
    }

    if app.status == "waiting_user_input":
        q_result = await db.execute(
            select(ApplicationQuestion)
            .where(ApplicationQuestion.application_id == app.id, ApplicationQuestion.status == "pending")
            .order_by(ApplicationQuestion.question_index)
        )
        pending = []
        for pq in q_result.scalars():
            q: dict = {"index": pq.question_index, "question": pq.field_label}
            if pq.draft_answer:
                q["suggested_answer"] = pq.draft_answer
            pending.append(q)
        if pending:
            data["pending_questions"] = pending

    if app.submitted_at:
        data["submitted_at"] = app.submitted_at.isoformat()
    if app.error_type:
        data["error"] = app.error_type
    if app.pre_submit_screenshot_path:
        data["pre_submit_screenshot"] = app.pre_submit_screenshot_path
    if app.screenshot_storage_path:
        data["screenshot"] = app.screenshot_storage_path

    company_name = job.company if job else "this company"
    data["message"] = f"{company_name} — {data.get('title', '')}: {app.status}"
    context = build_application_context(app, job)
    data["application_context"] = context
    data["recommended_next_action"] = build_recommended_next_action(context)

    return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_job(db: AsyncSession, params: dict) -> JobListing | None:
    """Resolve a job from params (ID, fuzzy company+title match, or URL).

    If a job_url is provided and not in the DB, creates a temporary JobListing
    so the apply flow can proceed with any URL the user provides.
    """
    job_id = params.get("job_id")
    job_url = params.get("job_url", "").strip()
    company = params.get("company_name", "").lower()
    title = params.get("job_title", "").lower()

    if job_id:
        return await db.get(JobListing, job_id)

    # URL-based lookup: check if we have it, otherwise create a temp listing
    if job_url:
        result = await db.execute(
            select(JobListing).where(JobListing.apply_url == job_url)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        # Create a temporary job listing for this URL
        from uuid import uuid4

        from app.services.discovery.ats_detector import detect_ats
        ats = detect_ats(job_url) or "unknown"
        # Extract company name from URL
        url_company = _company_from_url(job_url)
        job = JobListing(
            id=str(uuid4()),
            title=title or "Job Application",
            company=url_company or company or "Unknown",
            apply_url=job_url,
            source_url=job_url,
            ats_type=ats,
            status="active",
            auto_apply_supported=True,
        )
        db.add(job)
        await db.flush()
        logger.info("Created temp job listing for URL: %s (%s)", job_url, url_company)
        return job

    if not company and not title:
        return None

    result = await db.execute(
        select(JobListing).where(JobListing.status == "active")
    )
    candidates = list(result.scalars().all())

    best_score = 0
    best_job = None
    for job in candidates:
        score = 0
        if company and company in (job.company or "").lower():
            score += 3
        if title:
            for term in title.split():
                if term in (job.title or "").lower():
                    score += 2
        if score > best_score:
            best_score = score
            best_job = job

    return best_job


def _company_from_url(url: str) -> str:
    """Extract a company name from a job URL."""
    import re
    # Greenhouse: job-boards.greenhouse.io/COMPANY/...
    m = re.search(r'greenhouse\.io/([^/]+)', url)
    if m:
        return m.group(1).replace('-', ' ').title()
    # Ashby: jobs.ashbyhq.com/COMPANY/...
    m = re.search(r'ashbyhq\.com/([^/]+)', url)
    if m:
        return m.group(1).replace('-', ' ').title()
    # Lever: jobs.lever.co/COMPANY/...
    m = re.search(r'lever\.co/([^/]+)', url)
    if m:
        return m.group(1).replace('-', ' ').title()
    return ""


async def _analyze_skill_gaps(db: AsyncSession, user_id: str, job: JobListing) -> dict:
    """Analyze the gap between user skills and job requirements."""
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return {"summary": "Set up your profile to see skill gap analysis."}

    user_skills = set(s.lower() for s in json.loads(profile.skills_json or "[]"))
    required = set(s.lower() for s in json.loads(job.required_skills_json or "[]"))
    preferred = set(s.lower() for s in json.loads(job.preferred_skills_json or "[]"))

    missing_required = sorted(required - user_skills)
    missing_preferred = sorted(preferred - user_skills)
    matching = sorted(required & user_skills)

    gap: dict = {
        "matching_skills": matching[:10],
        "missing_required": missing_required[:10],
        "missing_preferred": missing_preferred[:5],
    }

    # Build coaching message
    parts = []
    if missing_required:
        parts.append(f"Missing required skills: {', '.join(missing_required[:5])}")
    if missing_preferred:
        parts.append(f"Missing preferred skills: {', '.join(missing_preferred[:3])}")
    if matching:
        parts.append(f"You match on: {', '.join(matching[:5])}")

    if missing_required:
        parts.append(
            "To become qualified: add these skills to your resume if you have them, "
            "or consider projects/courses to build them."
        )
    elif not missing_required and missing_preferred:
        parts.append(
            "You meet the requirements but are missing preferred qualifications. "
            "This is a stretch role — consider applying if the company interests you."
        )

    gap["summary"] = " ".join(parts) if parts else "Could not determine specific skill gaps."
    return gap


async def _load_pending_questions(db: AsyncSession, application_id: str) -> list[dict]:
    """Load pending questions for an application."""
    result = await db.execute(
        select(ApplicationQuestion)
        .where(ApplicationQuestion.application_id == application_id, ApplicationQuestion.status == "pending")
        .order_by(ApplicationQuestion.question_index)
    )
    questions = []
    for pq in result.scalars():
        q: dict = {
            "index": pq.question_index,
            "question": pq.field_label,
            "category": pq.category,
            "field_type": pq.field_type,
        }
        if pq.draft_answer:
            q["suggested_answer"] = pq.draft_answer
        try:
            opts = json.loads(pq.options_json or "[]")
            if opts:
                q["options"] = opts
        except (json.JSONDecodeError, TypeError):
            pass
        questions.append(q)
    return questions
