"""Match scorer: score how well a job matches a user's profile."""

from __future__ import annotations

import json
import logging
import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.job_listing import JobListing
from app.db.models.job_match import JobMatch
from app.db.models.user_profile import UserProfile

logger = logging.getLogger(__name__)

# Common skill aliases for normalization
SKILL_ALIASES: dict[str, str] = {
    "k8s": "kubernetes",
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "rb": "ruby",
    "pg": "postgresql",
    "postgres": "postgresql",
    "react.js": "react",
    "reactjs": "react",
    "node.js": "nodejs",
    "vue.js": "vue",
    "next.js": "nextjs",
    "go": "golang",
    "c++": "cpp",
    "c#": "csharp",
    "aws": "amazon web services",
    "gcp": "google cloud",
}

SENIORITY_ORDER = ["intern", "junior", "mid", "senior", "staff", "principal", "director"]


class MatchScorer:
    async def score_jobs_for_user(
        self, db: AsyncSession, user_id: str
    ) -> list[JobMatch]:
        """Score all unscored active jobs for a user."""
        # Get profile
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            logger.warning("No profile found for user %s", user_id)
            return []

        # Get jobs that don't have a match for this user yet
        result = await db.execute(
            select(JobListing).where(
                JobListing.status == "active",
                ~JobListing.id.in_(
                    select(JobMatch.job_id).where(JobMatch.user_id == user_id)
                ),
            )
        )
        unscored_jobs = result.scalars().all()

        if not unscored_jobs:
            return []

        matches = []
        for job in unscored_jobs:
            # Pass 1: hard disqualification
            disqualify = self._check_disqualifiers(profile, job)
            if disqualify:
                match = JobMatch(
                    id=str(uuid4()),
                    user_id=user_id,
                    job_id=job.id,
                    match_score=0,
                    disqualified=True,
                    disqualify_reason=disqualify,
                )
                matches.append(match)
                db.add(match)
                continue

            # Pass 2: weighted component scoring
            scores = self._score_components(profile, job)
            composite = int(sum(scores.values()))

            match = JobMatch(
                id=str(uuid4()),
                user_id=user_id,
                job_id=job.id,
                match_score=min(composite, 100),
                **scores,
            )
            matches.append(match)
            db.add(match)

        await db.commit()
        logger.info("Scored %d jobs for user %s", len(matches), user_id)
        return matches

    def _check_disqualifiers(
        self, profile: UserProfile, job: JobListing
    ) -> str | None:
        if job.requires_clearance and not profile.has_clearance:
            return "clearance_required"
        if not self._location_compatible(profile, job):
            return "location_mismatch"
        if self._seniority_gap(profile, job) > 2:
            return "seniority_mismatch"
        return None

    def _score_components(self, profile: UserProfile, job: JobListing) -> dict:
        return {
            "title_score": self._title_similarity(profile, job) * 30,
            "skills_score": self._skills_overlap(profile, job) * 25,
            "experience_score": self._experience_fit(profile, job) * 15,
            "location_score": self._location_fit(profile, job) * 15,
            "salary_score": self._salary_fit(profile, job) * 10,
            "recency_score": self._recency_score(job) * 5,
        }

    def _title_similarity(self, profile: UserProfile, job: JobListing) -> float:
        """Keyword-based title similarity (V1 — swap for embeddings later)."""
        target_titles = json.loads(profile.target_titles_json or "[]")
        if not target_titles:
            return 0.5  # Neutral if no preferences

        job_title_lower = job.title.lower()
        job_desc_lower = (job.description or "")[:500].lower()
        combined = job_title_lower + " " + job_desc_lower

        best = 0.0
        for target in target_titles:
            words = target.lower().split()
            matched = sum(1 for w in words if w in combined)
            score = matched / max(len(words), 1)
            best = max(best, score)

        return best

    def _skills_overlap(self, profile: UserProfile, job: JobListing) -> float:
        """Jaccard-like skill overlap with alias normalization."""
        user_skills = {
            _normalize_skill(s)
            for s in json.loads(profile.skills_json or "[]")
        }
        required = {
            _normalize_skill(s)
            for s in json.loads(job.required_skills_json or "[]")
        }
        preferred = {
            _normalize_skill(s)
            for s in json.loads(job.preferred_skills_json or "[]")
        }

        all_job_skills = required | preferred
        if not all_job_skills:
            # If job doesn't list skills, do keyword matching against description
            return self._skills_from_description(user_skills, job.description)

        if not user_skills:
            return 0.0

        overlap = len(user_skills & all_job_skills)
        # Weight required skills more heavily
        required_overlap = len(user_skills & required) if required else 0
        total = len(all_job_skills)

        base = overlap / total if total > 0 else 0
        # Bonus for matching required skills
        req_bonus = (required_overlap / max(len(required), 1)) * 0.3 if required else 0

        return min(base + req_bonus, 1.0)

    def _skills_from_description(
        self, user_skills: set[str], description: str
    ) -> float:
        """Fallback: match user skills against job description text."""
        if not description or not user_skills:
            return 0.3  # Neutral

        desc_lower = description.lower()
        matched = sum(1 for s in user_skills if s in desc_lower)
        return min(matched / max(len(user_skills), 1), 1.0)

    def _experience_fit(self, profile: UserProfile, job: JobListing) -> float:
        """How well does user's experience level match the job?"""
        user_years = profile.years_experience or 0
        required_years = job.required_years

        if required_years is None:
            return 0.7  # Neutral if not specified

        diff = abs(user_years - required_years)
        if diff == 0:
            return 1.0
        elif diff <= 1:
            return 0.8
        elif diff <= 3:
            return 0.5
        else:
            return 0.2

    def _location_compatible(self, profile: UserProfile, job: JobListing) -> bool:
        """Check if location preferences are compatible.

        Lenient: only disqualify if we're SURE it's incompatible.
        Unknown remote_type passes through to scoring.
        """
        pref = profile.remote_preference
        if pref == "any" or not pref:
            return True
        if job.remote_type == "remote":
            return True  # Remote jobs are always compatible
        if pref == "remote_only" and job.remote_type == "onsite":
            return False  # Explicitly onsite + user wants remote = disqualify
        # For everything else (null remote_type, hybrid, etc.) — let it through
        # The location_fit scorer will penalize it
        return True

    def _location_fit(self, profile: UserProfile, job: JobListing) -> float:
        """Score location fit (not just pass/fail)."""
        pref = profile.remote_preference
        if pref == "remote_only" and job.remote_type == "remote":
            return 1.0
        if job.remote_type == "remote":
            return 0.9  # Remote is always good

        user_locations = json.loads(profile.target_locations_json or "[]")
        if not user_locations:
            return 0.7

        job_loc = (job.location or "").lower()
        for loc in user_locations:
            if loc.lower() in job_loc or job_loc in loc.lower():
                return 1.0

        return 0.3

    def _salary_fit(self, profile: UserProfile, job: JobListing) -> float:
        """Score salary alignment."""
        floor = profile.salary_floor
        if floor is None or job.salary_max is None:
            return 0.5  # Unknown

        if job.salary_max >= floor:
            return 1.0
        elif job.salary_max >= floor * 0.9:
            return 0.6
        else:
            return 0.2

    def _recency_score(self, job: JobListing) -> float:
        """Fresher jobs score higher."""
        from datetime import datetime, timezone

        if not job.posted_at:
            return 0.5

        now = datetime.now(timezone.utc)
        if job.posted_at.tzinfo is None:
            from datetime import timezone as tz
            posted = job.posted_at.replace(tzinfo=tz.utc)
        else:
            posted = job.posted_at

        days_old = (now - posted).days
        if days_old <= 1:
            return 1.0
        elif days_old <= 7:
            return 0.8
        elif days_old <= 14:
            return 0.5
        elif days_old <= 30:
            return 0.3
        else:
            return 0.1

    def _seniority_gap(self, profile: UserProfile, job: JobListing) -> int:
        """Return the gap in seniority levels between profile and job."""
        user_level = (profile.seniority_level or "mid").lower()
        job_level = (job.seniority or "mid").lower()

        try:
            user_idx = SENIORITY_ORDER.index(user_level)
        except ValueError:
            user_idx = 2  # default to mid
        try:
            job_idx = SENIORITY_ORDER.index(job_level)
        except ValueError:
            job_idx = 2

        return abs(user_idx - job_idx)


def _normalize_skill(skill: str) -> str:
    """Normalize a skill name for comparison."""
    s = skill.lower().strip()
    return SKILL_ALIASES.get(s, s)
