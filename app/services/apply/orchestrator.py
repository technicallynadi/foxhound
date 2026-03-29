"""Application orchestrator: coordinates the full apply flow."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.application import Application
from app.db.models.job_listing import JobListing
from app.db.models.user_profile import UserProfile
from app.services.apply.prompts import build_prompt

logger = logging.getLogger(__name__)

# Status messages for applications that need manual completion
_MANUAL_MESSAGES = {
    "captcha_detected": "This form has a CAPTCHA that requires human verification.",
    "captcha": "This form has a CAPTCHA that requires human verification.",
    "email_verification_required": "This form requires email verification. Check your inbox for a verification code.",
    "needs_account": "This form requires creating an account on the company's career site.",
    "personal_certification_required": "This form has a certification statement that must be completed by you personally.",
    "spam_flagged": "The application was flagged by the company's spam filter. Try applying directly.",
}


def _build_manual_message(result: dict, job: "JobListing") -> str:
    """Build a user-friendly message for needs_manual applications."""
    status = result.get("status", "unknown")
    base = _MANUAL_MESSAGES.get(status, "This application needs manual completion.")
    fields_filled = result.get("fields_filled", [])

    parts = [base]
    if fields_filled:
        parts.append(f"Foxhound filled {len(fields_filled)} fields before stopping.")
    parts.append(f"Complete it here: {job.apply_url}")
    return " ".join(parts)


class ApplicationOrchestrator:
    """Two-phase apply flow: scan form -> classify fields -> fill + submit.

    Phase 1 (scan): TinyFish reads the form, returns all fields as JSON.
    Phase 2 (fill): After all answers are ready, TinyFish fills and submits.
    """

    async def apply(
        self,
        db: AsyncSession,
        user_id: str,
        job_id: str,
        trigger: str = "manual",
    ) -> Application:
        # 1. Pre-flight checks
        profile = await self._get_profile(db, user_id)
        job = await self._get_job(db, job_id)
        self._check_limits(profile)

        # 2. Create application record
        app = Application(
            id=str(uuid4()),
            user_id=user_id,
            job_id=job_id,
            status="scanning",
            trigger=trigger,
            resume_version_path=profile.resume_storage_path,
        )
        db.add(app)
        await db.flush()

        # 3. PHASE 1: Scan the form to discover fields
        from app.services.apply.form_scanner import scan_form, analyze_scan

        scan_result = await scan_form(job.apply_url)

        if scan_result.status != "scannable":
            app.status = "failed" if scan_result.status == "error" else "needs_manual"
            app.error_type = scan_result.status
            app.error_message = scan_result.error or f"Form scan: {scan_result.status}"
            await db.commit()
            return app

        # 4. Classify fields and determine what we can auto-fill
        analysis = analyze_scan(scan_result)

        # Store scan results on the job for future reference
        if not job.custom_questions_json:
            custom_qs = [
                {"field_label": f["label"], "field_type": f["field_type"], "required": f["required"]}
                for f in analysis["narrative"] + analysis["sensitive"] + analysis["unknown"]
            ]
            if custom_qs:
                job.custom_questions_json = json.dumps(custom_qs)

        # 5. Generate answers for all fields
        custom_answers = []
        if analysis["needs_user_input"]:
            # For narrative questions, draft answers with LLM
            for field_info in analysis["narrative"]:
                draft = await self._draft_answer(profile, job, field_info["label"])
                custom_answers.append({
                    "question": field_info["label"],
                    "answer": draft,
                    "confidence": 0.5,
                    "needs_approval": True,
                })

            # For sensitive/unknown, we need user input
            needs_input = analysis["sensitive"] + analysis["unknown"]
            if needs_input:
                # Start conversation for user input
                from app.services.apply.notifications import send_conversation_question

                questions_for_user = [
                    {"question": f["label"], "field_type": f["field_type"]}
                    for f in needs_input
                ]
                # Also include narrative drafts for approval
                for ans in custom_answers:
                    if ans["needs_approval"]:
                        questions_for_user.append({
                            "question": ans["question"],
                            "suggested_answer": ans["answer"],
                            "field_type": "textarea",
                        })

                app.status = "waiting_user_input"
                app.custom_answers_json = json.dumps(custom_answers)
                await db.commit()

                # Notify user
                await send_conversation_question(profile, app.id, job, questions_for_user)
                return app  # Will resume when user responds

        # Also auto-fill from profile for known fields
        for field_info in analysis["auto_fill"]:
            answer = self._auto_fill(profile, field_info["label"])
            if answer:
                custom_answers.append({
                    "question": field_info["label"],
                    "answer": answer,
                    "confidence": 0.95,
                    "needs_approval": False,
                })

        # 6. PHASE 2: Build TinyFish prompt and fill + submit
        #    Pass scan_fields so the prompt only includes profile fields the form has.
        app.status = "in_progress"
        raw_fields = [
            {"label": f.label, "field_type": f.field_type, "required": f.required, "options": f.options}
            for f in scan_result.fields
        ]
        prompt = build_prompt(profile, job, custom_answers, scan_fields=raw_fields)

        # 7. Execute TinyFish fill call
        t0 = time.monotonic()
        result = await self._execute_tinyfish(prompt, job.apply_url)
        duration_ms = int((time.monotonic() - t0) * 1000)

        # 8. Update application with results
        app.tinyfish_status = result.get("status", "unknown")
        app.tinyfish_duration_ms = duration_ms
        app.tinyfish_streaming_url = result.get("streaming_url")
        app.fields_filled_json = json.dumps(result.get("fields_filled", []))

        if result.get("status") == "submitted":
            app.status = "submitted"
            app.submitted_at = datetime.now(timezone.utc)
        elif result.get("status") in ("captcha_detected", "captcha", "personal_certification_required"):
            app.status = "needs_manual"
            app.error_type = result["status"]
            app.error_message = _build_manual_message(result, job)
        elif result.get("status") in ("email_verification_required", "needs_account"):
            app.status = "needs_manual"
            app.error_type = result["status"]
            app.error_message = _build_manual_message(result, job)
        elif result.get("status") == "spam_flagged":
            app.status = "needs_manual"
            app.error_type = "spam_flagged"
            app.error_message = _build_manual_message(result, job)
        else:
            app.status = "failed"
            app.error_type = result.get("status", "unknown")
            app.error_message = result.get("error", "")

        # 7. Capture screenshot if we have a streaming URL
        if result.get("streaming_url"):
            try:
                screenshot_path = await self._capture_screenshot(
                    result["streaming_url"], app.id, user_id
                )
                app.screenshot_storage_path = screenshot_path
                app.screenshot_captured_at = datetime.now(timezone.utc)
            except Exception as e:
                logger.warning("Screenshot capture failed: %s", e)

        # 8. Send notification
        from app.services.apply.notifications import send_application_receipt

        try:
            await send_application_receipt(
                profile=profile,
                application=app,
                job=job,
                screenshot_url=app.screenshot_storage_path,
            )
            app.notification_sent = True
            app.notification_sent_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.warning("Notification failed: %s", e)

        # 9. Increment monthly counter + handle needs_manual notification
        if app.status == "submitted":
            profile.applications_this_month += 1
        elif app.status == "needs_manual":
            await self._send_needs_manual_notification(profile, app, job)

        await db.commit()
        return app

    async def _get_profile(self, db: AsyncSession, user_id: str) -> UserProfile:
        result = await db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if not profile:
            raise ValueError(f"No profile found for user {user_id}")
        return profile

    async def _get_job(self, db: AsyncSession, job_id: str) -> JobListing:
        result = await db.execute(
            select(JobListing).where(JobListing.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        return job

    def _check_limits(self, profile: UserProfile) -> None:
        if profile.tier == "free":
            raise ValueError("Browse tier cannot apply. Upgrade to Agent ($39/mo) to start applying.")
        if profile.applications_this_month >= profile.monthly_apply_limit:
            raise ValueError(
                f"Monthly application limit reached ({profile.monthly_apply_limit})"
            )

    async def _generate_answers(
        self, profile: UserProfile, job: JobListing, questions: list[dict]
    ) -> list[dict]:
        """Generate answers for custom application questions."""
        # For V1, auto-fill factual questions, leave narrative for later
        answers = []
        for q in questions:
            label = q.get("field_label", "").lower()
            answer = self._auto_fill(profile, label)
            if answer:
                answers.append({"question": q.get("field_label", ""), "answer": answer})
        return answers

    def _auto_fill(self, profile: UserProfile, label: str) -> str | None:
        """Try to auto-fill a question from the profile."""
        if any(kw in label for kw in ["name", "full name"]):
            return f"{profile.first_name or ''} {profile.last_name or ''}".strip()
        if "email" in label:
            return profile.email
        if "phone" in label:
            return profile.phone
        if "linkedin" in label:
            return profile.linkedin_url
        if any(kw in label for kw in ["website", "portfolio", "url"]):
            return profile.portfolio_url
        if "location" in label or "city" in label:
            return profile.location
        return None

    async def _draft_answer(
        self, profile: UserProfile, job: JobListing, question: str
    ) -> str:
        """Use LLM to draft a contextual answer for a narrative question."""
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        experience = json.loads(profile.experience_json or "[]")
        skills = json.loads(profile.skills_json or "[]")

        prompt_text = (
            f"Draft a brief, natural answer to this job application question.\n"
            f"Use details from the candidate's resume. Keep it under 150 words.\n\n"
            f"Question: {question}\n"
            f"Job: {job.title} at {job.company}\n"
            f"Job description: {(job.description or '')[:500]}\n"
            f"Candidate summary: {profile.summary or ''}\n"
            f"Candidate experience: {json.dumps(experience[:3])}\n"
            f"Candidate skills: {json.dumps(skills[:15])}\n\n"
            f"Answer:"
        )

        try:
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt_text}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.warning("Failed to draft answer for '%s': %s", question, e)
            return ""

    async def _execute_tinyfish(self, prompt: str, url: str) -> dict:
        """Execute a TinyFish form-fill call.

        Browser profile selected per ATS:
        - Greenhouse: STEALTH + proxy
        - Ashby: LITE (stealth triggers spam detection)
        - Lever: LITE (hCaptcha blocks regardless)
        """
        from app.services.apply.form_scanner import _pick_browser_profile
        from app.services.ingest.tinyfish_adapter import _get_client

        try:
            client = _get_client()
            browser_profile, proxy_config = _pick_browser_profile(url)
            kwargs: dict = {
                "goal": prompt,
                "url": url,
                "browser_profile": browser_profile,
            }
            if proxy_config:
                kwargs["proxy_config"] = proxy_config
            result = await client.agent.run(**kwargs)
            return self._parse_tinyfish_result(result)
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT_EXCEEDED" in error_str:
                return {"status": "rate_limited", "error": "TinyFish rate limited"}
            if "INSUFFICIENT_CREDITS" in error_str:
                return {"status": "no_credits", "error": "TinyFish credits exhausted"}
            return {"status": "failed", "error": error_str}

    def _parse_tinyfish_result(self, result: object) -> dict:
        """Parse TinyFish AgentRunResponse into structured dict.

        Prefers result.result (dict) from the SDK, falls back to string parsing.
        """
        # Try the structured result first (SDK returns result.result as dict)
        if hasattr(result, "result") and isinstance(result.result, dict):
            data = result.result
            # Map TinyFish result to our status format
            if data.get("status"):
                return data
            # If no explicit status, check for success indicators
            if data.get("confirmation_text") or data.get("form_submitted"):
                return {**data, "status": "submitted"}
            return {**data, "status": "unknown"}

        # Check RunStatus
        if hasattr(result, "status"):
            from tinyfish import RunStatus
            if result.status == RunStatus.FAILED:
                return {"status": "failed", "error": result.error or "TinyFish run failed"}

        # Fallback: string parsing
        text = str(result)
        try:
            json_match = re.search(r'\{[\s\S]*"status"[\s\S]*?\}', text)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, AttributeError):
            pass

        if "submitted" in text.lower() or "success" in text.lower():
            return {"status": "submitted"}
        if "captcha" in text.lower():
            return {"status": "captcha_detected"}
        return {"status": "unknown", "raw_output": text[:500]}

    async def _send_needs_manual_notification(
        self, profile: UserProfile, app: Application, job: JobListing
    ) -> None:
        """Notify user when an application needs manual completion."""
        from app.services.apply.notifications import send_status_update

        try:
            await send_status_update(profile, job, "in_progress", "needs_manual")
        except Exception as e:
            logger.warning("Needs-manual notification failed: %s", e)

    async def _capture_screenshot(
        self, streaming_url: str, application_id: str, user_id: str
    ) -> str:
        """Capture screenshot via Playwright on TinyFish streaming URL."""
        from playwright.async_api import async_playwright
        from app.services.storage.supabase_storage import upload_file

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(streaming_url)
            await page.wait_for_load_state("networkidle", timeout=30_000)
            screenshot_bytes = await page.screenshot(full_page=True)
            await browser.close()

        path = f"{user_id}/{application_id}.png"
        await upload_file("screenshots", path, screenshot_bytes, "image/png")
        return f"screenshots/{path}"
