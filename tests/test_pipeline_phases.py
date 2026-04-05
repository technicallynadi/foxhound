"""Test the three-phase apply pipeline step by step.

Run each phase individually to see results before moving to the next:

  Phase 1 (TinyFish scan):   .venv/bin/python tests/test_pipeline_phases.py scan <url>
  Phase 2 (AgentQL locate):  .venv/bin/python tests/test_pipeline_phases.py locate <url>
  Phase 3 (Playwright fill): .venv/bin/python tests/test_pipeline_phases.py fill <url>

Each phase prints its results so you can inspect before spending credits on the next.
"""

import asyncio
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("pipeline_test")

# Load env
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
os.environ.setdefault("AGENTQL_API_KEY", os.environ.get("AGENTQL_KEY", ""))

TEST_URL = "https://job-boards.greenhouse.io/scaleai/jobs/4655744005"

# Test profile data — what would normally come from the user's profile
TEST_PROFILE = {
    "first_name": "Test",
    "last_name": "Foxhound",
    "email": "testfoxhound+pipeline@gmail.com",
    "phone": "2025551234",
    "linkedin": "https://linkedin.com/in/testfoxhound",
    "location": "Washington, DC",
}


# ═══════════════════════════════════════
# PHASE 1: TinyFish Scan
# ═══════════════════════════════════════


async def phase1_scan(url: str):
    """Use TinyFish to scan the form and return field definitions."""
    print("=" * 60)
    print("PHASE 1: TinyFish Form Scan")
    print("=" * 60)
    print(f"URL: {url}")
    print()

    from tinyfish import AsyncTinyFish, BrowserProfile, RunStatus

    client = AsyncTinyFish(api_key=os.environ.get("TINYFISH_API_KEY"))

    goal = (
        "You are on a job application page. "
        "List every visible form field with its label, field type "
        "(text, email, tel, select, textarea, file, checkbox, radio), "
        "and whether it's required. "
        "Return as JSON array: "
        '[{"label": "...", "field_type": "...", "required": true/false}]'
    )

    print("Sending to TinyFish...")
    result = await client.agent.run(
        goal=goal,
        url=url,
        browser_profile=BrowserProfile.LITE,
    )

    print(f"Status: {result.status}")
    print()

    if result.status == RunStatus.COMPLETED and result.result:
        raw = result.result if isinstance(result.result, str) else json.dumps(result.result)

        # Try to parse as JSON
        try:
            fields = json.loads(raw)
            if isinstance(fields, list):
                print(f"Found {len(fields)} fields:")
                print()
                for i, f in enumerate(fields):
                    req = "REQUIRED" if f.get("required") else "optional"
                    print(f"  {i + 1}. [{f.get('field_type', '?')}] {f.get('label', '?')} ({req})")
                print()

                # Save for Phase 2
                output_path = "/tmp/phase1_scan_result.json"
                with open(output_path, "w") as fp:
                    json.dump(fields, fp, indent=2)
                print(f"Saved to {output_path} — use this for Phase 2")
            else:
                print("Result is not a list:")
                print(raw[:2000])
        except json.JSONDecodeError:
            print("Could not parse as JSON:")
            print(raw[:2000])
    else:
        print("TinyFish scan failed:")
        print(f"  Status: {result.status}")
        print(f"  Error: {getattr(result, 'error', 'unknown')}")


# ═══════════════════════════════════════
# PHASE 2: AgentQL Locate
# ═══════════════════════════════════════


async def phase2_locate(url: str):
    """Use AgentQL to find DOM locators for each field from Phase 1."""
    print("=" * 60)
    print("PHASE 2: AgentQL Element Location")
    print("=" * 60)
    print(f"URL: {url}")
    print()

    # Load Phase 1 results
    scan_path = "/tmp/phase1_scan_result.json"
    if not os.path.exists(scan_path):
        print(f"ERROR: Run Phase 1 first. No file at {scan_path}")
        return

    with open(scan_path) as fp:
        fields = json.load(fp)

    print(f"Loaded {len(fields)} fields from Phase 1")
    print()

    import agentql
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        raw_page = await context.new_page()
        page = await agentql.wrap_async(raw_page)
        await page.enable_stealth_mode()

        print("Navigating...")
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_page_ready_state()
        print(f"On page: {page.url}")
        print()

        # Find each field
        results = []
        for f in fields:
            label = f.get("label", "")
            ftype = f.get("field_type", "text")

            if ftype in ("file", "hidden"):
                results.append({"label": label, "type": ftype, "found": ftype == "file", "note": "handled separately"})
                continue

            try:
                locator = await page.get_by_prompt(f"the form input field labeled '{label}'")
                if locator:
                    # Verify it's actually visible
                    visible = await locator.is_visible(timeout=2000)
                    tag = await locator.evaluate("el => el.tagName") if visible else "?"
                    results.append(
                        {
                            "label": label,
                            "type": ftype,
                            "found": True,
                            "visible": visible,
                            "tag": tag,
                        }
                    )
                    status = "FOUND" if visible else "FOUND (hidden)"
                    print(f"  {status}: [{ftype}] {label} <{tag}>")
                else:
                    results.append({"label": label, "type": ftype, "found": False})
                    print(f"  MISSING: [{ftype}] {label}")
            except Exception as e:
                results.append({"label": label, "type": ftype, "found": False, "error": str(e)[:100]})
                print(f"  ERROR: [{ftype}] {label} — {str(e)[:80]}")

        # Also find upload + submit buttons
        print()
        for btn_desc, btn_prompt in [
            ("Resume upload", "the button or link to attach or upload a resume file"),
            ("Submit button", "the submit application button"),
        ]:
            try:
                btn = await page.get_by_prompt(btn_prompt)
                if btn:
                    visible = await btn.is_visible(timeout=2000)
                    print(f"  FOUND: {btn_desc} (visible={visible})")
                    results.append({"label": btn_desc, "type": "button", "found": True, "visible": visible})
                else:
                    print(f"  MISSING: {btn_desc}")
                    results.append({"label": btn_desc, "type": "button", "found": False})
            except Exception as e:
                print(f"  ERROR: {btn_desc} — {str(e)[:80]}")

        await browser.close()

    # Summary
    found = sum(1 for r in results if r.get("found"))
    total = len(results)
    print()
    print(f"SUMMARY: {found}/{total} elements located")
    print()

    # Save for Phase 3
    output_path = "/tmp/phase2_locate_result.json"
    with open(output_path, "w") as fp:
        json.dump(results, fp, indent=2)
    print(f"Saved to {output_path} — use this for Phase 3")


# ═══════════════════════════════════════
# PHASE 3: Playwright Fill
# ═══════════════════════════════════════


async def phase3_fill(url: str):
    """Use AgentQL to locate (empty form) then Playwright to fill (PII local only)."""
    print("=" * 60)
    print("PHASE 3: Playwright Fill (PII stays local)")
    print("=" * 60)
    print(f"URL: {url}")
    print()

    # Load Phase 1 results for field list
    scan_path = "/tmp/phase1_scan_result.json"
    if not os.path.exists(scan_path):
        print(f"ERROR: Run Phase 1 first. No file at {scan_path}")
        return

    with open(scan_path) as fp:
        fields = json.load(fp)

    import agentql
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)  # Visible so you can watch
        context = await browser.new_context()
        raw_page = await context.new_page()
        page = await agentql.wrap_async(raw_page)
        await page.enable_stealth_mode()

        print("Navigating...")
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_page_ready_state()

        # ── PHASE A: Find all locators on EMPTY form ──
        print()
        print("--- Phase A: AgentQL finding elements (empty form, no PII) ---")
        locator_map = {}
        upload_btn = None
        submit_btn = None

        for f in fields:
            label = f.get("label", "")
            ftype = f.get("field_type", "text")
            if ftype in ("file", "hidden"):
                continue
            try:
                locator = await page.get_by_prompt(f"the form input field labeled '{label}'")
                if locator:
                    locator_map[label] = {"locator": locator, "type": ftype}
                    print(f"  Found: {label}")
            except Exception:
                print(f"  Miss: {label}")

        try:
            upload_btn = await page.get_by_prompt("the button or link to attach or upload a resume file")
            if upload_btn:
                print("  Found: Resume upload button")
        except Exception:
            pass

        try:
            submit_btn = await page.get_by_prompt("the submit application button")
            if submit_btn:
                print("  Found: Submit button")
        except Exception:
            pass

        print(
            f"\nLocators cached: {len(locator_map)} fields + upload={upload_btn is not None} + submit={submit_btn is not None}"
        )

        # ── PHASE B: Fill with Playwright only (no more AgentQL calls) ──
        print()
        print("--- Phase B: Playwright filling (PII stays local) ---")

        # Map field labels to test values
        value_map = {
            "first name": TEST_PROFILE["first_name"],
            "last name": TEST_PROFILE["last_name"],
            "email": TEST_PROFILE["email"],
            "phone": TEST_PROFILE["phone"],
            "linkedin": TEST_PROFILE["linkedin"],
            "location": TEST_PROFILE["location"],
        }

        filled = 0
        for label, info in locator_map.items():
            locator = info["locator"]
            ftype = info["type"]

            # Find matching value
            value = None
            label_lower = label.lower()
            for key, val in value_map.items():
                if key in label_lower:
                    value = val
                    break

            if not value:
                print(f"  Skip: {label} (no test value)")
                continue

            try:
                await locator.scroll_into_view_if_needed(timeout=3000)

                if ftype == "select":
                    try:
                        await locator.select_option(label=value, timeout=2000)
                    except Exception:
                        await locator.click()
                        await page.wait_for_timeout(500)
                        option = raw_page.get_by_text(value, exact=False).first
                        await option.click()
                elif "location" in label_lower or "city" in label_lower:
                    await locator.fill("")
                    await locator.press_sequentially(value, delay=50)
                    await page.wait_for_timeout(1000)
                    try:
                        option = raw_page.get_by_role("option").first
                        await option.click()
                    except Exception:
                        pass
                else:
                    await locator.fill(value)

                filled += 1
                print(f"  Filled: {label} = {value}")
            except Exception as e:
                print(f"  Error: {label} — {str(e)[:80]}")

        print(f"\nFilled {filled} fields")

        # Screenshot
        screenshot_path = "/tmp/phase3_filled_form.png"
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"Screenshot saved: {screenshot_path}")

        # ── SUBMIT ──
        if submit_btn:
            print()
            print("--- Submitting ---")
            await submit_btn.click()
            await page.wait_for_timeout(3000)

            try:
                await page.wait_for_page_ready_state()
            except Exception:
                pass

            # Check for confirmation
            try:
                body_text = (await page.inner_text("body")).lower()
                confirmation_patterns = [
                    "application has been submitted",
                    "thank you for applying",
                    "thanks for applying",
                    "application received",
                    "successfully submitted",
                    "we have received your application",
                ]
                confirmed = False
                for pattern in confirmation_patterns:
                    if pattern in body_text:
                        print(f"CONFIRMED: {pattern}")
                        confirmed = True
                        break

                if not confirmed:
                    new_url = page.url
                    if new_url != url:
                        print(f"REDIRECTED: {new_url} (likely submitted)")
                    else:
                        print("No confirmation detected — check screenshots")
            except Exception as e:
                print(f"Confirmation check error: {e}")

            # Post-submit screenshot
            post_path = "/tmp/phase3_post_submit.png"
            await page.screenshot(path=post_path, full_page=True)
            print(f"Post-submit screenshot: {post_path}")
        else:
            print("No submit button found — cannot submit")

        # Keep browser open to inspect
        await page.wait_for_timeout(10000)
        await browser.close()


# ═══════════════════════════════════════
# CLI
# ═══════════════════════════════════════


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print(f"  {sys.argv[0]} scan [url]    — Phase 1: TinyFish scans the form")
        print(f"  {sys.argv[0]} locate [url]  — Phase 2: AgentQL finds DOM elements")
        print(f"  {sys.argv[0]} fill [url]    — Phase 3: Playwright fills the form")
        return

    command = sys.argv[1]
    url = sys.argv[2] if len(sys.argv) > 2 else TEST_URL

    if command == "scan":
        asyncio.run(phase1_scan(url))
    elif command == "locate":
        asyncio.run(phase2_locate(url))
    elif command == "fill":
        asyncio.run(phase3_fill(url))
    else:
        print(f"Unknown command: {command}")
        print("Use: scan, locate, or fill")


if __name__ == "__main__":
    main()
