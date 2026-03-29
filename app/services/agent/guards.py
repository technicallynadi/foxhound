"""Pre-execution tool guards.

Code-enforced constraints that run BEFORE any tool executes.
These cannot be bypassed by prompt injection — they are hard boundaries.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.application import Application
from app.db.models.job_listing import JobListing
from app.db.models.user_profile import UserProfile
from app.services.agent.registry import get_tool_spec

logger = logging.getLogger(__name__)


class ToolBlocked(Exception):
    """Raised when a guard blocks tool execution."""

    def __init__(self, code: str, message: str, suggestion: str = ""):
        self.code = code
        self.message = message
        self.suggestion = suggestion
        super().__init__(message)

    def to_dict(self) -> dict:
        result = {"error": self.code, "message": self.message}
        if self.suggestion:
            result["suggestion"] = self.suggestion
        return result


class ToolGuard:
    """Pre-execution checks for tool calls."""

    async def check(
        self,
        db: AsyncSession,
        user_id: str,
        tool_name: str,
        params: dict,
    ) -> None:
        """Run all applicable guards. Raises ToolBlocked if any fail."""
        spec = get_tool_spec(tool_name)
        if not spec:
            return

        # Only guard tools with side effects or apply permission
        if "apply" in spec.permissions:
            await self._check_tier(db, user_id)
            await self._check_monthly_limit(db, user_id)
            if params.get("job_id") or params.get("company_name"):
                await self._check_duplicate(db, user_id, params)
                await self._check_blacklist(db, user_id, params)

    async def _check_tier(self, db: AsyncSession, user_id: str) -> None:
        """Free tier cannot apply."""
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            raise ToolBlocked("no_profile", "No profile found. Upload your resume first.",
                              "Upload your resume to get started.")
        if profile.tier == "free":
            raise ToolBlocked("browse_tier", "Browse tier cannot apply. Upgrade to Agent to start applying.",
                              "Upgrade to Agent ($39/mo) for unlimited applications.")

    async def _check_monthly_limit(self, db: AsyncSession, user_id: str) -> None:
        """Check monthly application cap."""
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            return
        if profile.applications_this_month >= profile.monthly_apply_limit:
            raise ToolBlocked(
                "monthly_limit",
                f"You've used all {profile.monthly_apply_limit} applications this month.",
                "Your limit resets next month, or upgrade your plan for more."
            )

    async def _check_duplicate(self, db: AsyncSession, user_id: str, params: dict) -> None:
        """Prevent applying to the same job twice."""
        job_id = params.get("job_id")
        if not job_id:
            return

        result = await db.execute(
            select(func.count(Application.id)).where(
                Application.user_id == user_id,
                Application.job_id == job_id,
                Application.status.notin_(["failed", "canceled"]),
            )
        )
        count = result.scalar() or 0
        if count > 0:
            raise ToolBlocked(
                "duplicate_application",
                "You already have an active application for this job.",
                "Check your application status instead."
            )

    async def _check_blacklist(self, db: AsyncSession, user_id: str, params: dict) -> None:
        """Check company blacklist."""
        company_name = params.get("company_name", "").lower()
        job_id = params.get("job_id")

        if job_id and not company_name:
            job = await db.get(JobListing, job_id)
            if job:
                company_name = (job.company or "").lower()

        if not company_name:
            return

        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            return

        blacklist = json.loads(profile.blacklisted_companies_json or "[]")
        if any(company_name == b.lower() for b in blacklist):
            raise ToolBlocked(
                "blacklisted_company",
                f"{company_name.title()} is on your blacklist.",
                "Remove it from your blacklist in settings if you've changed your mind."
            )
