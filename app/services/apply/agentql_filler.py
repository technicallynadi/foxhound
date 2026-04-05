"""AgentQL form filler: Phase 2 of the two-phase apply flow.

Replaces playwright_filler.py's selector-based approach with AgentQL's
semantic element finding. Uses the same interface (FillResult, fill_from_profile)
so the orchestrator doesn't need to change.

Architecture:
1. Launch browser via AgentQL (no TinyFish CDP needed)
2. Navigate to application page
3. Use semantic queries to find and fill form fields
4. Upload resume via file chooser
5. Submit and verify
6. Return FillResult with screenshots
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field

from app.core.config import settings
from app.services.apply.form_scanner import ScanResult, match_field_to_profile
from app.services.apply.playwright_filler import (
    FillResult,
    FieldFillResult,
    _build_profile_data,
    _resolve_field_value,
)

logger = logging.getLogger(__name__)

# Ensure AgentQL picks up the API key
os.environ.setdefault("AGENTQL_API_KEY", os.environ.get("AGENTQL_KEY", ""))


# ---------------------------------------------------------------------------
# AgentQL fill and submit
# ---------------------------------------------------------------------------


async def agentql_fill_and_submit(
    apply_url: str,
    scan_result: ScanResult,
    profile,
    custom_answers: list[dict] | None = None,
    resume_bytes: bytes | None = None,
    resume_filename: str = "resume.pdf",
) -> FillResult:
    """Phase 2: Use AgentQL to find form fields semantically, fill, and submit.

    Same interface as playwright_filler.fill_and_submit — drop-in replacement.
    """
    import agentql
    from playwright.async_api import async_playwright

    t0 = time.monotonic()

    # Build lookup structures
    profile_data = _build_profile_data(profile)
    answers_map: dict[str, str] = {}
    if custom_answers:
        for a in custom_answers:
            answers_map[a["question"]] = a["answer"]

    field_results: list[FieldFillResult] = []
    filled = 0
    skipped = 0
    errored = 0

    try:
        async with async_playwright() as p:
            # 1. Launch browser directly — no TinyFish CDP needed
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            raw_page = await context.new_page()

            # 2. Wrap with AgentQL
            page = await agentql.wrap_async(raw_page)
            await page.enable_stealth_mode()

            # 3. Navigate to application
            await page.goto(apply_url, wait_until="domcontentloaded", timeout=60_000)
            current_url = page.url
            logger.info("AgentQL filler: on page %s", page.url)

            # 4. Wait for page to be ready
            await page.wait_for_page_ready_state()

            # 5. Dismiss cookie banners
            try:
                cookie_btn = await page.get_by_prompt(
                    "the button to accept cookies or dismiss the cookie consent banner"
                )
                if cookie_btn:
                    await cookie_btn.click()
                    await page.wait_for_timeout(500)
                    logger.info("Dismissed cookie banner")
            except Exception:
                pass

            # 6. Navigate to application form if needed
            try:
                # Some sites need you to click "Apply" first
                apply_btn = await page.get_by_prompt(
                    "the Apply or Apply Now button that opens the application form"
                )
                if apply_btn:
                    await apply_btn.click()
                    await page.wait_for_timeout(2000)
                    await page.wait_for_page_ready_state()
                    logger.info("Clicked Apply button to open form")
            except Exception:
                pass

            # 7. Check for blockers
            try:
                body_text = (await page.inner_text("body")).lower()
                if "captcha" in body_text and any(
                    kw in body_text for kw in ["verify", "robot", "human"]
                ):
                    return FillResult(
                        status="captcha",
                        error="CAPTCHA detected",
                        duration_ms=int((time.monotonic() - t0) * 1000),
                    )
            except Exception:
                pass

            # ── PHASE A: AgentQL finds ALL elements on the empty form ──
            # No PII has been entered yet. AgentQL cloud sees only field labels.
            logger.info("Phase A: Finding all form elements with AgentQL (no PII on page)...")

            # Build list of fields that need filling
            fields_to_fill = []
            for form_field in scan_result.fields:
                if form_field.field_type in ("file", "hidden"):
                    if form_field.field_type == "hidden":
                        field_results.append(FieldFillResult(
                            label=form_field.label, status="skipped", value_used="(hidden)",
                        ))
                        skipped += 1
                    continue

                value = _resolve_field_value(form_field, profile_data, answers_map)
                if not value:
                    field_results.append(FieldFillResult(
                        label=form_field.label, status="skipped", value_used="(no value)",
                    ))
                    skipped += 1
                    logger.info("Skipped: '%s' (no value)", form_field.label)
                    continue

                fields_to_fill.append((form_field, value))

            # Find ALL locators at once before any PII is on the page
            locator_map: dict[str, object] = {}  # label -> Playwright Locator
            upload_btn_locator = None
            submit_btn_locator = None

            for form_field, _ in fields_to_fill:
                try:
                    locator = await page.get_by_prompt(
                        f"the form input field labeled '{form_field.label}'"
                    )
                    if locator:
                        locator_map[form_field.label] = locator
                        logger.info("Found: '%s'", form_field.label)
                    else:
                        logger.warning("Not found: '%s'", form_field.label)
                except Exception as e:
                    logger.warning("AgentQL lookup failed for '%s': %s", form_field.label, str(e)[:100])

            # Also find upload and submit buttons while the form is still empty
            try:
                upload_btn_locator = await page.get_by_prompt(
                    "the button or link to attach or upload a resume file"
                )
                if upload_btn_locator:
                    logger.info("Found: resume upload button")
            except Exception:
                pass

            try:
                submit_btn_locator = await page.get_by_prompt(
                    "the submit application button or the apply button at the bottom of the form"
                )
                if submit_btn_locator:
                    logger.info("Found: submit button")
            except Exception:
                pass

            logger.info("Phase A complete: found %d/%d field locators",
                        len(locator_map), len(fields_to_fill))

            # ── PHASE B: Playwright fills using cached locators (local only) ──
            # AgentQL is NOT called again. All PII stays local.
            logger.info("Phase B: Filling form with Playwright (PII stays local)...")

            for form_field, value in fields_to_fill:
                locator = locator_map.get(form_field.label)
                if not locator:
                    field_results.append(FieldFillResult(
                        label=form_field.label, status="not_found",
                        error="AgentQL could not find field",
                    ))
                    errored += 1
                    continue

                try:
                    await locator.scroll_into_view_if_needed(timeout=3000)

                    if form_field.field_type == "select":
                        # Try native select first
                        try:
                            await locator.select_option(label=value, timeout=2000)
                        except Exception:
                            # Custom dropdown — click to open, find option with Playwright
                            await locator.click()
                            await page.wait_for_timeout(500)
                            # Use Playwright text matching (not AgentQL) to find the option
                            try:
                                option = raw_page.get_by_text(value, exact=False).first
                                await option.click()
                            except Exception:
                                await locator.fill(value)

                    elif form_field.field_type == "radio":
                        try:
                            # Use Playwright to find radio by value text
                            radio = raw_page.get_by_label(value, exact=False).first
                            await radio.click()
                        except Exception:
                            await locator.click()

                    elif form_field.field_type == "checkbox":
                        try:
                            if value.lower() in ("yes", "true", "1"):
                                await locator.check()
                            else:
                                await locator.uncheck()
                        except Exception:
                            await locator.click()

                    elif form_field.label.lower() in ("location", "city", "address"):
                        # Autocomplete — type slowly, pick first suggestion
                        await locator.fill("")
                        await locator.press_sequentially(value, delay=50)
                        await page.wait_for_timeout(1000)
                        try:
                            # Use Playwright role selector for autocomplete option
                            option = raw_page.get_by_role("option").first
                            await option.click()
                        except Exception:
                            pass

                    else:
                        await locator.fill(value)

                    field_results.append(FieldFillResult(
                        label=form_field.label, status="filled", value_used=value,
                    ))
                    filled += 1
                    logger.info("Filled: '%s'", form_field.label)

                except Exception as e:
                    logger.warning("Failed to fill '%s': %s", form_field.label, e)
                    field_results.append(FieldFillResult(
                        label=form_field.label, status="error",
                        value_used=value, error=str(e),
                    ))
                    errored += 1

                await page.wait_for_timeout(100)

            logger.info("Fill summary: %d filled, %d skipped, %d errors out of %d",
                        filled, skipped, errored, len(scan_result.fields))

            # 9. Upload resume (using pre-cached locator)
            if resume_bytes and scan_result.has_file_upload:
                try:
                    # Write resume to temp file
                    with tempfile.NamedTemporaryFile(
                        suffix=f"_{resume_filename}", delete=False
                    ) as tmp:
                        tmp.write(resume_bytes)
                        tmp_path = tmp.name

                    if upload_btn_locator:
                        async with page.expect_file_chooser(timeout=5000) as fc:
                            await upload_btn_locator.click()
                        file_chooser = await fc.value
                        await file_chooser.set_files(tmp_path)
                        await page.wait_for_timeout(2000)
                        logger.info("Resume uploaded: %s", resume_filename)
                        field_results.append(FieldFillResult(
                            label="Resume", status="filled", value_used=resume_filename,
                        ))
                        filled += 1
                    else:
                        logger.warning("Could not find resume upload button")
                        field_results.append(FieldFillResult(
                            label="Resume", status="not_found",
                            error="Upload button not found",
                        ))

                    # Cleanup temp file
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

                except Exception as e:
                    logger.warning("Resume upload failed: %s", e)
                    field_results.append(FieldFillResult(
                        label="Resume", status="error", error=str(e),
                    ))

            # 10. Pre-submit screenshot
            pre_submit_screenshot = await _safe_screenshot(page)

            # 11. Click submit (using pre-cached locator)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(500)

            if not submit_btn_locator:
                screenshot = await _safe_screenshot(page)
                return FillResult(
                    status="needs_manual",
                    fields=field_results,
                    fields_filled_count=filled,
                    fields_skipped_count=skipped,
                    fields_errored_count=errored,
                    screenshot_bytes=screenshot,
                    pre_submit_screenshot_bytes=pre_submit_screenshot,
                    error="Submit button not found",
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )

            logger.info("Clicking submit...")
            await submit_btn_locator.click()
            await page.wait_for_timeout(3000)

            try:
                await page.wait_for_page_ready_state()
            except Exception:
                pass

            # 12. Check for confirmation
            confirmation = ""
            try:
                body_text = (await page.inner_text("body")).lower()
                confirmation_patterns = [
                    "application has been submitted",
                    "thank you for applying",
                    "thanks for applying",
                    "application received",
                    "successfully submitted",
                    "we have received your application",
                    "your application has been received",
                ]
                for pattern in confirmation_patterns:
                    if pattern in body_text:
                        confirmation = pattern
                        break
            except Exception:
                pass

            # 13. Check for post-submit errors (Playwright only — no AgentQL)
            if not confirmation:
                try:
                    # Look for common error indicators via Playwright
                    error_el = raw_page.locator('[class*="error"], [role="alert"], .field-error').first
                    if await error_el.is_visible(timeout=1000):
                        error_text = await error_el.text_content()
                        if error_text:
                            logger.warning("Form error after submit: %s", error_text[:200])
                except Exception:
                    pass

            # 14. Post-submit screenshot
            screenshot = await _safe_screenshot(page)

            # Determine status
            if confirmation:
                status = "submitted"
            else:
                try:
                    new_url = page.url
                    if new_url != apply_url and new_url != current_url:
                        status = "submitted"
                        confirmation = f"Redirected to: {new_url}"
                    else:
                        status = "needs_manual"
                except Exception:
                    status = "needs_manual"

            await browser.close()

            return FillResult(
                status=status,
                fields=field_results,
                fields_filled_count=filled,
                fields_skipped_count=skipped,
                fields_errored_count=errored,
                screenshot_bytes=screenshot,
                pre_submit_screenshot_bytes=pre_submit_screenshot,
                confirmation_text=confirmation,
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

    except Exception as e:
        logger.exception("AgentQL fill failed")
        return FillResult(
            status="error",
            fields=field_results,
            fields_filled_count=filled,
            fields_skipped_count=skipped,
            fields_errored_count=errored,
            error=str(e),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


async def _safe_screenshot(page) -> bytes | None:
    """Capture a full-page screenshot, returning None on failure."""
    try:
        return await page.screenshot(full_page=True, timeout=10_000)
    except Exception as e:
        logger.warning("Screenshot failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Convenience: download resume from Supabase, then fill
# ---------------------------------------------------------------------------


async def fill_from_profile(
    apply_url: str,
    scan_result: ScanResult,
    profile,
    custom_answers: list[dict] | None = None,
) -> FillResult:
    """Full convenience wrapper: downloads resume, then fills with AgentQL.

    Drop-in replacement for playwright_filler.fill_from_profile.
    """
    resume_bytes: bytes | None = None
    resume_filename = profile.resume_filename or "resume.pdf"

    if profile.resume_storage_path and scan_result.has_file_upload:
        try:
            from app.services.storage.supabase_storage import download_file

            parts = profile.resume_storage_path.split("/", 1)
            if len(parts) == 2:
                resume_bytes = await download_file(parts[0], parts[1])
                logger.info("Resume downloaded: %d bytes", len(resume_bytes))
        except Exception as e:
            logger.warning("Resume download failed (will proceed without): %s", e)

    return await agentql_fill_and_submit(
        apply_url=apply_url,
        scan_result=scan_result,
        profile=profile,
        custom_answers=custom_answers,
        resume_bytes=resume_bytes,
        resume_filename=resume_filename,
    )
