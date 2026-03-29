"""Profile & resume API routes."""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user_profile import UserProfile
from app.db.session import get_db
from app.services.auth_service import get_current_user
from app.services.resume.parser import ResumeParser
from app.services.storage.supabase_storage import upload_file

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])

parser = ResumeParser()


class ProfileUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    portfolio_url: str | None = None
    location: str | None = None
    summary: str | None = None
    skills: list[str] | None = None
    experience: list[dict] | None = None
    education: list[dict] | None = None
    archetype: str | None = None


class PreferencesUpdate(BaseModel):
    target_titles: list[str] | None = None
    target_locations: list[str] | None = None
    remote_preference: str | None = None
    salary_floor: int | None = None
    salary_currency: str | None = None
    industries: list[str] | None = None
    company_size_preference: str | None = None
    seniority_level: str | None = None


@router.post("/resume/upload")
async def upload_resume(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a resume PDF, parse it, and create/update the user profile."""
    user_id = user["user_id"]
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    pdf_bytes = await file.read()
    if len(pdf_bytes) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(400, "File too large (max 10MB)")

    # Store PDF in Supabase Storage
    storage_path = f"{user_id}/{file.filename}"
    await upload_file("resumes", storage_path, pdf_bytes, "application/pdf")

    # Parse the resume
    try:
        parsed = await parser.parse(pdf_bytes, file.filename)
    except ValueError as e:
        raise HTTPException(422, f"Failed to parse resume: {e}")

    # Create or update profile
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()

    if profile:
        # Update existing profile
        profile.first_name = parsed.first_name
        profile.last_name = parsed.last_name
        profile.email = parsed.email or profile.email
        profile.phone = parsed.phone
        profile.linkedin_url = parsed.linkedin_url
        profile.portfolio_url = parsed.portfolio_url
        profile.location = parsed.location
        profile.summary = parsed.summary
        profile.skills_json = json.dumps(parsed.skills)
        profile.experience_json = json.dumps(parsed.experience)
        profile.education_json = json.dumps(parsed.education)
        profile.certifications_json = json.dumps(parsed.certifications)
        profile.seniority_level = parsed.inferred_seniority
        profile.years_experience = parsed.inferred_years_experience
        profile.target_titles_json = json.dumps(parsed.inferred_target_titles)
        profile.resume_storage_path = f"resumes/{storage_path}"
        profile.resume_filename = file.filename
        profile.resume_text = ""  # TODO: store raw text
        profile.onboarding_step = "review_profile"
    else:
        profile = UserProfile(
            id=str(uuid4()),
            user_id=user_id,
            email=parsed.email or "",
            first_name=parsed.first_name,
            last_name=parsed.last_name,
            phone=parsed.phone,
            linkedin_url=parsed.linkedin_url,
            portfolio_url=parsed.portfolio_url,
            location=parsed.location,
            summary=parsed.summary,
            skills_json=json.dumps(parsed.skills),
            experience_json=json.dumps(parsed.experience),
            education_json=json.dumps(parsed.education),
            certifications_json=json.dumps(parsed.certifications),
            seniority_level=parsed.inferred_seniority,
            years_experience=parsed.inferred_years_experience,
            target_titles_json=json.dumps(parsed.inferred_target_titles),
            resume_storage_path=f"resumes/{storage_path}",
            resume_filename=file.filename,
            onboarding_step="review_profile",
        )
        db.add(profile)

    await db.commit()
    await db.refresh(profile)

    # Trigger initial job matching for this user against existing listings
    try:
        from app.services.matching.scorer import MatchScorer
        scorer = MatchScorer()
        matches = await scorer.score_jobs_for_user(db, profile.user_id)
        match_count = len([m for m in matches if not m.disqualified and m.match_score > 0])
    except Exception:
        match_count = 0

    return {
        "profile_id": profile.id,
        "status": "ready",
        "jobs_matched": match_count,
        "parsed": {
            "name": f"{parsed.first_name} {parsed.last_name}",
            "email": parsed.email,
            "skills": parsed.skills,
            "experience_count": len(parsed.experience),
            "inferred_titles": parsed.inferred_target_titles,
            "seniority": parsed.inferred_seniority,
        },
    }


@router.get("")
async def get_profile(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the full profile for the authenticated user."""
    user_id = user["user_id"]
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(404, "Profile not found. Upload a resume first.")

    return _serialize_profile(profile)


@router.put("")
async def update_profile(
    body: ProfileUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update profile fields (user corrects LLM parsing errors)."""
    user_id = user["user_id"]
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(404, "Profile not found")

    if body.first_name is not None:
        profile.first_name = body.first_name
    if body.last_name is not None:
        profile.last_name = body.last_name
    if body.phone is not None:
        profile.phone = body.phone
    if body.linkedin_url is not None:
        profile.linkedin_url = body.linkedin_url
    if body.portfolio_url is not None:
        profile.portfolio_url = body.portfolio_url
    if body.location is not None:
        profile.location = body.location
    if body.summary is not None:
        profile.summary = body.summary
    if body.skills is not None:
        profile.skills_json = json.dumps(body.skills)
    if body.experience is not None:
        profile.experience_json = json.dumps(body.experience)
    if body.education is not None:
        profile.education_json = json.dumps(body.education)
    if body.archetype is not None:
        valid_archetypes = {"tech", "business", "design", "science", "finance", "startup", "executive"}
        if body.archetype not in valid_archetypes:
            raise HTTPException(400, f"Invalid archetype. Must be one of: {', '.join(sorted(valid_archetypes))}")
        profile.archetype = body.archetype
        if profile.onboarding_step == "review_profile":
            profile.onboarding_step = "set_preferences"

    await db.commit()
    return _serialize_profile(profile)


@router.put("/preferences")
async def update_preferences(
    body: PreferencesUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update job preferences."""
    user_id = user["user_id"]
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(404, "Profile not found")

    if body.target_titles is not None:
        profile.target_titles_json = json.dumps(body.target_titles)
    if body.target_locations is not None:
        profile.target_locations_json = json.dumps(body.target_locations)
    if body.remote_preference is not None:
        profile.remote_preference = body.remote_preference
    if body.salary_floor is not None:
        profile.salary_floor = body.salary_floor
    if body.salary_currency is not None:
        profile.salary_currency = body.salary_currency
    if body.industries is not None:
        profile.industries_json = json.dumps(body.industries)
    if body.company_size_preference is not None:
        profile.company_size_preference = body.company_size_preference
    if body.seniority_level is not None:
        profile.seniority_level = body.seniority_level

    # Mark onboarding progress
    if profile.onboarding_step == "set_preferences":
        profile.onboarding_step = "ready"
        profile.profile_complete = True

    await db.commit()

    # Re-score jobs when preferences change
    try:
        from app.services.matching.scorer import MatchScorer
        # Delete old matches so they get rescored
        from app.db.models.job_match import JobMatch
        from sqlalchemy import delete
        await db.execute(
            delete(JobMatch).where(JobMatch.user_id == user_id)
        )
        await db.commit()
        scorer = MatchScorer()
        await scorer.score_jobs_for_user(db, user_id)
    except Exception:
        pass  # Non-fatal — scores will catch up on next discovery run

    return _serialize_profile(profile)


def _serialize_profile(profile: UserProfile) -> dict:
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "email": profile.email,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "phone": profile.phone,
        "linkedin_url": profile.linkedin_url,
        "portfolio_url": profile.portfolio_url,
        "location": profile.location,
        "summary": profile.summary,
        "skills": json.loads(profile.skills_json or "[]"),
        "experience": json.loads(profile.experience_json or "[]"),
        "education": json.loads(profile.education_json or "[]"),
        "certifications": json.loads(profile.certifications_json or "[]"),
        "target_titles": json.loads(profile.target_titles_json or "[]"),
        "target_locations": json.loads(profile.target_locations_json or "[]"),
        "remote_preference": profile.remote_preference,
        "salary_floor": profile.salary_floor,
        "seniority_level": profile.seniority_level,
        "years_experience": profile.years_experience,
        "tier": profile.tier,
        "onboarding_step": profile.onboarding_step,
        "profile_complete": bool(profile.profile_complete),
        "archetype": profile.archetype,
        "resume_filename": profile.resume_filename,
    }
