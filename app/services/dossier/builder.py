"""DossierBuilder: background task orchestrator for company intelligence reports.

User clicks "Get Report" -> returns immediately with "building" status ->
TinyFish runs 8 sources in background -> each section updates the DB as it
completes -> Claude synthesis -> Slack notification when done.

Uses asyncio.create_task() for true background execution (not blocking
the request). Uses fresh DB sessions for background writes since the
original request session will be closed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.core.config import settings
from app.db.models.application import Application
from app.db.models.dossier import Dossier
from app.db.models.job_listing import JobListing
from app.db.models.user_profile import UserProfile
from app.db.session import async_session

logger = logging.getLogger(__name__)

DASHBOARD_BASE = "https://usefoxhound.com"


class DossierBuilder:
    """Orchestrates background dossier building."""

    async def start(self, application_id: str, user_id: str) -> dict:
        """Create a dossier record and launch background build.

        Returns immediately with {status, dossier_id} so the API
        can respond without waiting for TinyFish.
        """
        async with async_session() as db:
            # Check for existing dossier on this application
            result = await db.execute(
                select(Dossier).where(
                    Dossier.application_id == application_id,
                    Dossier.user_id == user_id,
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                # Already building or ready -- return existing
                return {
                    "status": existing.status,
                    "dossier_id": existing.id,
                    "existing": True,
                }

            # Load application to get company name
            app_result = await db.execute(
                select(Application, JobListing)
                .join(JobListing, Application.job_id == JobListing.id)
                .where(Application.id == application_id)
            )
            row = app_result.first()
            if not row:
                return {"status": "error", "message": "Application not found"}

            application, job = row
            company = (job.company or "").strip()
            if not company:
                return {"status": "error", "message": "No company name on this application"}

            company_normalized = company.lower().replace(" ", "_")

            # Create dossier record
            dossier_id = str(uuid4())
            dossier = Dossier(
                id=dossier_id,
                application_id=application_id,
                user_id=user_id,
                company_normalized=company_normalized,
                status="building",
            )
            db.add(dossier)
            await db.commit()

        # Launch background task (non-blocking)
        asyncio.create_task(
            self._build_background(dossier_id),
            name=f"dossier-{dossier_id[:8]}",
        )

        return {
            "status": "building",
            "dossier_id": dossier_id,
            "existing": False,
        }

    async def _build_background(self, dossier_id: str) -> None:
        """Run all sources, update DB after each, synthesize, notify.

        This runs in a background task -- any exception is caught and
        the dossier is marked as failed.
        """
        start_time = time.monotonic()

        try:
            # Load context with a fresh session
            async with async_session() as db:
                dossier = await db.get(Dossier, dossier_id)
                if not dossier:
                    logger.error("Dossier %s not found for background build", dossier_id)
                    return

                app_result = await db.execute(
                    select(Application, JobListing)
                    .join(JobListing, Application.job_id == JobListing.id)
                    .where(Application.id == dossier.application_id)
                )
                row = app_result.first()
                if not row:
                    await self._mark_failed(dossier_id, "Application not found")
                    return

                application, job = row
                company = job.company or ""
                company_url = getattr(job, "company_url", None)
                job_title = job.title or ""

                # Load posting data for instant analysis + synthesis
                posting_data = self._extract_posting_data(job)

            # --- Step 1: Instant analysis (Claude from job posting) ---
            instant = await self._run_instant_analysis(company, posting_data)
            if instant:
                await self._update_section(dossier_id, "instant_analysis", instant)

            # --- Step 2: TinyFish sources in parallel ---
            source_results = await self._run_all_sources(
                company, company_url, posting_data, job_title
            )

            # Save each source result
            sources_completed: list[str] = []
            sources_failed: list[str] = []
            credits_used = 0

            for source_name, field_name, data in source_results:
                if data is not None:
                    await self._update_section(dossier_id, field_name, data)
                    sources_completed.append(source_name)
                    credits_used += 1
                else:
                    sources_failed.append(source_name)

            # Update metadata
            async with async_session() as db:
                dossier = await db.get(Dossier, dossier_id)
                dossier.sources_completed = json.dumps(sources_completed)
                dossier.sources_failed = json.dumps(sources_failed)
                dossier.tinyfish_credits = credits_used
                dossier.status = "partial" if sources_completed else "building"
                await db.commit()

            # --- Step 3: Claude final synthesis ---
            # Reload all source data for synthesis
            async with async_session() as db:
                dossier = await db.get(Dossier, dossier_id)

                # Load user profile for personalization
                profile_result = await db.execute(
                    select(UserProfile).where(
                        UserProfile.user_id == dossier.user_id
                    )
                )
                profile = profile_result.scalar_one_or_none()
                user_summary = None
                if profile:
                    user_summary = (
                        f"Skills: {getattr(profile, 'skills_json', '[]')}. "
                        f"Experience: {getattr(profile, 'years_experience', 'Not specified')} years. "
                        f"Summary: {getattr(profile, 'experience_summary', 'Not specified')}."
                    )

            from app.services.dossier.synthesizer import synthesize_dossier

            synthesis = await synthesize_dossier(
                company_name=company,
                posting_data=posting_data,
                company_data=_safe_json_load(dossier.company_data),
                careers_data=_safe_json_load(dossier.careers_data),
                news_data=_safe_json_load(dossier.news_data),
                team_contacts=_safe_json_load(dossier.team_contacts),
                glassdoor_data=_safe_json_load(dossier.glassdoor_data),
                reddit_interviews=_safe_json_load(dossier.reddit_interviews_data),
                reddit_culture=_safe_json_load(dossier.reddit_culture_data),
                engineering_blog=_safe_json_load(dossier.engineering_blog_data),
                levels_fyi=_safe_json_load(dossier.levels_fyi_data),
                user_summary=user_summary,
            )

            # Save ALL synthesis sections
            synthesis_fields = [
                "executive_summary",
                "outreach_draft",
                "interview_prep",
                "overall_assessment",
                "interview_process",
                "culture_report",
                "salary_estimate",
                "company_data",
                "careers_data",
                "news_data",
            ]
            # Map synthesis keys to DB field names
            synthesis_key_map = {
                "company_overview": "company_data",
                "hiring_summary": "careers_data",
                "recent_news": "news_data",
            }
            for field in synthesis_fields:
                value = synthesis.get(field)
                if value:
                    await self._update_section(dossier_id, field, value)
            # Save mapped keys (synthesis uses different names than DB)
            for synth_key, db_field in synthesis_key_map.items():
                value = synthesis.get(synth_key)
                if value:
                    await self._update_section(dossier_id, db_field, value)

            # --- Step 4: Mark ready and notify ---
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            async with async_session() as db:
                dossier = await db.get(Dossier, dossier_id)
                dossier.status = "ready"
                dossier.completed_at = datetime.now(timezone.utc)
                await db.commit()

            logger.info(
                "Dossier %s ready for %s in %dms (%d/%d sources)",
                dossier_id[:8],
                company,
                elapsed_ms,
                len(sources_completed),
                len(sources_completed) + len(sources_failed),
            )

            # Send notification
            await self._send_notification(
                dossier_id, company, job_title, sources_completed, sources_failed
            )

        except Exception:
            logger.exception("Dossier background build failed: %s", dossier_id)
            await self._mark_failed(dossier_id, "Internal error during build")

    async def _resynthesize(self, dossier_id: str) -> None:
        """Re-run Claude synthesis using saved TinyFish data.

        Called when the original synthesis failed but source data is in the DB.
        """
        try:
            async with async_session() as db:
                dossier = await db.get(Dossier, dossier_id)
                if not dossier:
                    return

                # Mark as building during re-synthesis
                dossier.status = "partial"
                await db.commit()

                app_result = await db.execute(
                    select(Application, JobListing)
                    .join(JobListing, Application.job_id == JobListing.id)
                    .where(Application.id == dossier.application_id)
                )
                row = app_result.first()
                if not row:
                    await self._mark_failed(dossier_id, "Application not found")
                    return

                application, job = row
                company = job.company or ""
                job_title = job.title or ""
                posting_data = self._extract_posting_data(job)

                # Load user profile
                profile_result = await db.execute(
                    select(UserProfile).where(UserProfile.user_id == dossier.user_id)
                )
                profile = profile_result.scalar_one_or_none()
                user_summary = None
                if profile:
                    user_summary = (
                        f"Skills: {getattr(profile, 'skills_json', '[]')}. "
                        f"Experience: {getattr(profile, 'years_experience', 'Not specified')} years. "
                        f"Summary: {getattr(profile, 'experience_summary', 'Not specified')}."
                    )

            # Reload source data
            async with async_session() as db:
                dossier = await db.get(Dossier, dossier_id)

            from app.services.dossier.synthesizer import synthesize_dossier

            synthesis = await synthesize_dossier(
                company_name=company,
                posting_data=posting_data,
                company_data=_safe_json_load(dossier.company_data),
                careers_data=_safe_json_load(dossier.careers_data),
                news_data=_safe_json_load(dossier.news_data),
                team_contacts=_safe_json_load(dossier.team_contacts),
                glassdoor_data=_safe_json_load(dossier.glassdoor_data),
                reddit_interviews=_safe_json_load(dossier.reddit_interviews_data),
                reddit_culture=_safe_json_load(dossier.reddit_culture_data),
                engineering_blog=_safe_json_load(dossier.engineering_blog_data),
                levels_fyi=_safe_json_load(dossier.levels_fyi_data),
                user_summary=user_summary,
            )

            # Save all synthesis fields
            synthesis_fields = [
                "executive_summary", "outreach_draft", "interview_prep",
                "overall_assessment", "interview_process", "culture_report",
                "salary_estimate",
            ]
            synthesis_key_map = {
                "company_overview": "company_data",
                "hiring_summary": "careers_data",
                "recent_news": "news_data",
            }
            for field in synthesis_fields:
                value = synthesis.get(field)
                if value:
                    await self._update_section(dossier_id, field, value)
            for synth_key, db_field in synthesis_key_map.items():
                value = synthesis.get(synth_key)
                if value:
                    await self._update_section(dossier_id, db_field, value)

            # Mark ready
            async with async_session() as db:
                dossier = await db.get(Dossier, dossier_id)
                dossier.status = "ready"
                dossier.completed_at = datetime.now(timezone.utc)
                await db.commit()

            logger.info("Dossier %s re-synthesized for %s", dossier_id[:8], company)

            # Notify
            sources_completed = json.loads(dossier.sources_completed or "[]")
            sources_failed = json.loads(dossier.sources_failed or "[]")
            await self._send_notification(
                dossier_id, company, job_title, sources_completed, sources_failed
            )

        except Exception:
            logger.exception("Dossier re-synthesis failed: %s", dossier_id)
            await self._mark_failed(dossier_id, "Re-synthesis failed")

    async def _run_instant_analysis(
        self, company: str, posting_data: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Run Claude instant analysis on the job posting (tech stack, insider tip)."""
        if not posting_data:
            return None

        from app.services.recon.synthesizer import synthesize_dossier as recon_synthesize

        try:
            result = await recon_synthesize(
                company_name=company,
                careers_data=None,
                company_data=None,
                posting_data=posting_data,
            )
            return result
        except Exception as e:
            logger.warning("Instant analysis failed for %s: %s", company, str(e)[:200])
            return None

    async def _run_all_sources(
        self,
        company: str,
        company_url: str | None,
        posting_data: dict[str, Any] | None,
        job_title: str | None = None,
    ) -> list[tuple[str, str, dict[str, Any] | None]]:
        """Run all 9 TinyFish sources in parallel.

        Returns list of (source_name, field_name, data_or_none).
        """
        from app.services.dossier.sources import (
            fetch_careers_page,
            fetch_company_page,
            fetch_engineering_blog,
            fetch_glassdoor,
            fetch_levels_fyi,
            fetch_news,
            fetch_reddit_culture,
            fetch_reddit_interviews,
            fetch_team_page,
        )

        # Infer department from posting data
        department = None
        if posting_data:
            title = (posting_data.get("title") or "").lower()
            if any(kw in title for kw in ["engineer", "developer", "sre", "devops", "backend", "frontend", "fullstack"]):
                department = "engineering"
            elif any(kw in title for kw in ["design", "ux", "ui"]):
                department = "design"
            elif any(kw in title for kw in ["product", "pm"]):
                department = "product"
            elif any(kw in title for kw in ["data", "analytics", "ml", "ai"]):
                department = "data"
            elif any(kw in title for kw in ["marketing", "growth"]):
                department = "marketing"
            elif any(kw in title for kw in ["sales", "account"]):
                department = "sales"

        # Define source tasks
        tasks = {
            "company": ("company_data", fetch_company_page(company, company_url)),
            "careers": ("careers_data", fetch_careers_page(company, company_url)),
            "news": ("news_data", fetch_news(company)),
            "team": ("team_contacts", fetch_team_page(company, company_url, department)),
            "glassdoor": ("glassdoor_data", fetch_glassdoor(company)),
            "reddit_interviews": ("reddit_interviews_data", fetch_reddit_interviews(company)),
            "reddit_culture": ("reddit_culture_data", fetch_reddit_culture(company)),
            "engineering_blog": ("engineering_blog_data", fetch_engineering_blog(company, company_url)),
            "levels_fyi": ("levels_fyi_data", fetch_levels_fyi(company, job_title)),
        }

        results: list[tuple[str, str, dict[str, Any] | None]] = []

        # Use global TinyFish concurrency limit
        from app.services.tinyfish_concurrency import TINYFISH_SEMAPHORE

        async def _run_source(name: str, field: str, coro):
            async with TINYFISH_SEMAPHORE:
                try:
                    data = await coro
                    if data:
                        logger.info("Dossier source '%s' completed for %s", name, company)
                    else:
                        logger.warning("Dossier source '%s' returned empty for %s", name, company)
                    return (name, field, data)
                except Exception as e:
                    logger.warning("Dossier source '%s' failed for %s: %s", name, company, str(e)[:200])
                    return (name, field, None)

        gathered = await asyncio.gather(
            *[_run_source(name, field, coro) for name, (field, coro) in tasks.items()]
        )
        results.extend(gathered)

        return results

    async def _update_section(
        self, dossier_id: str, field_name: str, data: Any
    ) -> None:
        """Update a single dossier section in the DB with a fresh session."""
        async with async_session() as db:
            dossier = await db.get(Dossier, dossier_id)
            if not dossier:
                return

            if isinstance(data, (dict, list)):
                value = json.dumps(data, default=str)
            else:
                value = str(data)

            setattr(dossier, field_name, value)
            await db.commit()

    async def _mark_failed(self, dossier_id: str, reason: str) -> None:
        """Mark a dossier as failed."""
        async with async_session() as db:
            dossier = await db.get(Dossier, dossier_id)
            if dossier:
                dossier.status = "failed"
                dossier.overall_assessment = reason
                dossier.completed_at = datetime.now(timezone.utc)
                await db.commit()

    async def _send_notification(
        self,
        dossier_id: str,
        company: str,
        job_title: str,
        sources_completed: list[str],
        sources_failed: list[str],
    ) -> None:
        """Send Slack notification when dossier is ready.

        Tries the Slack Bot first (direct DM), falls back to webhook.
        """
        # Try Slack Bot first (sends to linked user's DM)
        if settings.slack_bot_token:
            try:
                await self._send_bot_notification(
                    dossier_id, company, job_title, sources_completed, sources_failed
                )
                return
            except Exception:
                logger.warning("Slack bot notification failed, trying webhook", exc_info=True)

        from app.services.notification_service import send_slack_blocks

        webhook_url = settings.slack_webhook_url
        if not webhook_url:
            logger.info(
                "No Slack webhook configured — report %s ready for %s "
                "(in-app notification will be shown)",
                dossier_id[:8], company,
            )
            return

        # Build section status lines
        source_labels = {
            "company": "Company overview",
            "careers": "Hiring velocity",
            "news": "Recent news",
            "team": "Team contacts",
            "glassdoor": "Glassdoor signals",
            "reddit_interviews": "Reddit interviews",
            "reddit_culture": "Reddit culture",
            "engineering_blog": "Engineering blog",
            "levels_fyi": "Levels.fyi salary",
        }

        status_lines = []
        for source_key, label in source_labels.items():
            if source_key in sources_completed:
                status_lines.append(f"* {label}")
            elif source_key in sources_failed:
                status_lines.append(f"* {label} — unavailable")
            else:
                status_lines.append(f"* {label} — skipped")

        dossier_url = f"{DASHBOARD_BASE}/dossier/{dossier_id}"

        # Build inline summary from dossier data
        async with async_session() as db:
            dossier_obj = await db.get(Dossier, dossier_id)

        inline_parts = []
        if dossier_obj:
            instant = _safe_json_load(dossier_obj.instant_analysis) if dossier_obj.instant_analysis else None
            if instant and instant.get("insider_tip"):
                inline_parts.append(f"*Insider Tip:* {instant['insider_tip'][:300]}")
            if dossier_obj.overall_assessment:
                inline_parts.append(f"*Assessment:* {dossier_obj.overall_assessment[:300]}")
            if dossier_obj.culture_report:
                inline_parts.append(f"*Culture:* {dossier_obj.culture_report[:200]}")

        blocks: list[dict] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Intelligence Report Ready: {company}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Company:*\n{company}"},
                    {"type": "mrkdwn", "text": f"*Role:*\n{job_title}"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{len(sources_completed)}/{len(sources_completed) + len(sources_failed)} sources compiled",
                },
            },
        ]

        # Add inline findings
        if inline_parts:
            blocks.append({"type": "divider"})
            for part in inline_parts:
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": part},
                })

        fallback = f"Intelligence Report ready: {company} — {job_title}"

        try:
            await send_slack_blocks(webhook_url, blocks, fallback_text=fallback)

            # Mark notified
            async with async_session() as db:
                dossier = await db.get(Dossier, dossier_id)
                if dossier:
                    dossier.notified_at = datetime.now(timezone.utc)
                    await db.commit()

        except Exception:
            logger.exception("Dossier notification failed: %s", dossier_id)

    async def _send_bot_notification(
        self,
        dossier_id: str,
        company: str,
        job_title: str,
        sources_completed: list[str],
        sources_failed: list[str],
    ) -> None:
        """Send dossier-ready notification via Slack Bot DM with key findings."""
        from app.db.models.user_profile import UserProfile
        from app.services.slack.client import send_message

        # Load dossier + user
        async with async_session() as db:
            dossier = await db.get(Dossier, dossier_id)
            if not dossier:
                return

            from sqlalchemy import select
            result = await db.execute(
                select(UserProfile).where(UserProfile.user_id == dossier.user_id)
            )
            profile = result.scalar_one_or_none()
            if not profile or not getattr(profile, "slack_user_id", None):
                logger.info(
                    "No slack_user_id on profile for dossier %s — "
                    "skipping Slack DM, in-app notification will show",
                    dossier_id[:8],
                )
                return

        dossier_url = f"{DASHBOARD_BASE}/dossier/{dossier_id}"
        n_ok = len(sources_completed)
        n_total = n_ok + len(sources_failed)

        # Build summary from actual report data
        summary_parts = []

        # Insider tip
        instant = _safe_json_load(dossier.instant_analysis) if dossier.instant_analysis else None
        if instant and instant.get("insider_tip"):
            tip = instant["insider_tip"][:300]
            summary_parts.append(f"*Insider Tip:* {tip}")

        # Overall assessment
        if dossier.overall_assessment:
            assessment = dossier.overall_assessment[:300]
            summary_parts.append(f"*Assessment:* {assessment}")

        # Interview process
        interview = _safe_json_load(dossier.interview_process) if dossier.interview_process else None
        if interview:
            if interview.get("stages"):
                stages = " → ".join(interview["stages"][:5])
                summary_parts.append(f"*Interview:* {stages}")
            if interview.get("difficulty"):
                summary_parts.append(f"*Difficulty:* {interview['difficulty']}")

        # Culture
        if dossier.culture_report:
            culture = dossier.culture_report[:200]
            summary_parts.append(f"*Culture:* {culture}")

        summary_text = "\n\n".join(summary_parts) if summary_parts else "Report compiled."

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Intelligence Report Ready: {company}"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{company}* — {job_title}\n{n_ok}/{n_total} sources compiled",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": summary_text,
                },
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View Full Report"},
                        "url": dossier_url,
                    },
                ],
            },
        ]

        await send_message(
            channel=profile.slack_user_id,
            text=f"Intelligence Report ready: {company} — {job_title}\n{summary_text}",
            blocks=blocks,
        )

        # Mark notified
        async with async_session() as db:
            dossier = await db.get(Dossier, dossier_id)
            if dossier:
                dossier.notified_at = datetime.now(timezone.utc)
                await db.commit()

    def _extract_posting_data(self, job: Any) -> dict[str, Any]:
        """Extract posting data from a JobListing for synthesis."""
        try:
            required_skills = json.loads(getattr(job, "required_skills_json", "[]") or "[]")
        except (json.JSONDecodeError, TypeError):
            required_skills = []

        try:
            preferred_skills = json.loads(getattr(job, "preferred_skills_json", "[]") or "[]")
        except (json.JSONDecodeError, TypeError):
            preferred_skills = []

        data: dict[str, Any] = {
            "title": job.title,
            "company": job.company,
            "company_url": getattr(job, "company_url", None),
            "description": (job.description or "")[:3000],
            "seniority": getattr(job, "seniority", None),
            "remote_type": getattr(job, "remote_type", None),
            "location": getattr(job, "location", None),
            "salary_min": getattr(job, "salary_min", None),
            "salary_max": getattr(job, "salary_max", None),
        }

        all_skills = required_skills + preferred_skills
        if all_skills:
            data["tech_stack"] = all_skills

        return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_json_load(text: str | None) -> dict[str, Any] | None:
    """Safely parse a JSON text field."""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
