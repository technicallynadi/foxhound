"""Test AgentQL form filling on a real Greenhouse application.

Run: .venv/bin/python tests/test_agentql_apply.py

This test:
1. Opens a Greenhouse job application page
2. Uses AgentQL to find all form fields semantically
3. Fills them with test data
4. Uploads a resume
5. Takes a screenshot before submitting
6. Submits the application
7. Takes a screenshot after submitting
8. Reports what happened
"""

import asyncio
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("agentql_test")

# Test data — use a throwaway email so we don't spam real inboxes
TEST_DATA = {
    "first_name": "Test",
    "last_name": "Foxhound",
    "email": "testfoxhound+scale@gmail.com",
    "phone": "2025551234",
    "linkedin": "https://linkedin.com/in/testfoxhound",
    "location": "Washington, DC",
    "resume_path": None,  # Will be set below
}

JOB_URL = "https://job-boards.greenhouse.io/scaleai/jobs/4655744005"


async def run_test():
    import agentql
    from playwright.async_api import async_playwright

    # Find a resume to upload
    resume_path = None
    for candidate in [
        os.path.expanduser("~/Desktop/Dev-Repos/foxhound/tests/fixtures/test_resume.pdf"),
        os.path.expanduser("~/Desktop/resume.pdf"),
        os.path.expanduser("~/Documents/resume.pdf"),
    ]:
        if os.path.exists(candidate):
            resume_path = candidate
            break

    if not resume_path:
        # Create a minimal test PDF
        resume_path = "/tmp/test_resume.pdf"
        try:
            import pdfplumber  # noqa — just checking if we can make a PDF

            # Simple approach: write minimal PDF bytes
            with open(resume_path, "wb") as f:
                f.write(
                    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
                    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
                    b"0000000058 00000 n \n0000000115 00000 n \n"
                    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n206\n%%EOF"
                )
            logger.info("Created minimal test PDF at %s", resume_path)
        except Exception:
            logger.warning("No resume found and couldn't create one — will skip upload")

    TEST_DATA["resume_path"] = resume_path

    async with async_playwright() as pw:
        # Launch visible browser so we can watch
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # Wrap with AgentQL
        page = await agentql.wrap_async(page)
        await page.enable_stealth_mode()

        logger.info("Navigating to %s", JOB_URL)
        await page.goto(JOB_URL, wait_until="domcontentloaded")
        await page.wait_for_page_ready_state()

        # Step 1: Query the form fields
        logger.info("Querying form fields with AgentQL...")
        form_response = await page.query_elements("""
        {
            first_name_input
            last_name_input
            email_input
            phone_input
            resume_upload_btn(the button or link to attach a resume file)
            linkedin_url_input
            location_input
        }
        """)

        # Step 2: Fill basic fields
        fields_filled = []

        if form_response.first_name_input:
            await form_response.first_name_input.fill(TEST_DATA["first_name"])
            fields_filled.append("first_name")
            logger.info("Filled: first_name")

        if form_response.last_name_input:
            await form_response.last_name_input.fill(TEST_DATA["last_name"])
            fields_filled.append("last_name")
            logger.info("Filled: last_name")

        if form_response.email_input:
            await form_response.email_input.fill(TEST_DATA["email"])
            fields_filled.append("email")
            logger.info("Filled: email")

        if form_response.phone_input:
            await form_response.phone_input.fill(TEST_DATA["phone"])
            fields_filled.append("phone")
            logger.info("Filled: phone")

        if form_response.linkedin_url_input:
            await form_response.linkedin_url_input.fill(TEST_DATA["linkedin"])
            fields_filled.append("linkedin")
            logger.info("Filled: linkedin")

        if form_response.location_input:
            await form_response.location_input.press_sequentially(TEST_DATA["location"], delay=50)
            await page.wait_for_timeout(1000)
            # Try to click first autocomplete suggestion
            try:
                suggestion = await page.get_by_prompt("the first location autocomplete suggestion")
                if suggestion:
                    await suggestion.click()
                    fields_filled.append("location")
                    logger.info("Filled: location (with autocomplete)")
            except Exception:
                fields_filled.append("location_typed")
                logger.info("Filled: location (typed, no autocomplete)")

        # Step 3: Upload resume
        if TEST_DATA["resume_path"] and form_response.resume_upload_btn:
            try:
                async with page.expect_file_chooser() as fc:
                    await form_response.resume_upload_btn.click()
                file_chooser = await fc.value
                await file_chooser.set_files(TEST_DATA["resume_path"])
                fields_filled.append("resume")
                logger.info("Uploaded: resume")
                await page.wait_for_timeout(2000)  # Wait for upload to process
            except Exception as e:
                logger.warning("Resume upload failed: %s", e)

        # Step 4: Check for additional fields (dropdowns, custom questions)
        logger.info("Checking for additional form fields...")
        try:
            extra_response = await page.query_elements("""
            {
                how_did_you_hear_dropdown(dropdown for how did you hear about us)
                work_authorization_dropdown(dropdown about work authorization or legal right to work)
                gender_dropdown(dropdown for gender)
                race_dropdown(dropdown for race or ethnicity)
                veteran_dropdown(dropdown for veteran status)
            }
            """)

            if extra_response.how_did_you_hear_dropdown:
                try:
                    await extra_response.how_did_you_hear_dropdown.select_option(label="LinkedIn")
                    fields_filled.append("how_heard")
                    logger.info("Filled: how_did_you_hear -> LinkedIn")
                except Exception:
                    # Custom dropdown — try click approach
                    try:
                        await extra_response.how_did_you_hear_dropdown.click()
                        option = await page.get_by_prompt("the option for LinkedIn in the dropdown")
                        if option:
                            await option.click()
                            fields_filled.append("how_heard")
                            logger.info("Filled: how_did_you_hear -> LinkedIn (click)")
                    except Exception as e:
                        logger.warning("how_did_you_hear failed: %s", e)

            if extra_response.work_authorization_dropdown:
                try:
                    await extra_response.work_authorization_dropdown.select_option(label="Yes")
                    fields_filled.append("work_auth")
                    logger.info("Filled: work_authorization -> Yes")
                except Exception:
                    try:
                        await extra_response.work_authorization_dropdown.click()
                        option = await page.get_by_prompt("the Yes option")
                        if option:
                            await option.click()
                            fields_filled.append("work_auth")
                    except Exception as e:
                        logger.warning("work_authorization failed: %s", e)

        except Exception as e:
            logger.info("No additional dropdowns found or query failed: %s", str(e)[:100])

        # Step 5: Screenshot before submit
        pre_screenshot = "/tmp/agentql_pre_submit.png"
        await page.screenshot(path=pre_screenshot, full_page=True)
        logger.info("Pre-submit screenshot saved: %s", pre_screenshot)

        # Step 6: Find and click submit
        logger.info("Looking for submit button...")
        submit_btn = await page.get_by_prompt("the submit application button")

        if submit_btn:
            logger.info("Found submit button — clicking...")
            await submit_btn.click()
            await page.wait_for_timeout(3000)
            await page.wait_for_page_ready_state()

            # Step 7: Screenshot after submit
            post_screenshot = "/tmp/agentql_post_submit.png"
            await page.screenshot(path=post_screenshot, full_page=True)
            logger.info("Post-submit screenshot saved: %s", post_screenshot)

            # Step 8: Check for confirmation
            page_text = await page.content()
            confirmation_patterns = [
                "application has been submitted",
                "thank you for applying",
                "thanks for applying",
                "application received",
                "successfully submitted",
                "we have received your application",
            ]
            confirmed = any(p in page_text.lower() for p in confirmation_patterns)

            if confirmed:
                logger.info("CONFIRMED: Application submitted successfully!")
            else:
                # Check for errors
                try:
                    error = await page.get_by_prompt("any form validation error message")
                    if error:
                        error_text = await error.text_content()
                        logger.warning("Form error found: %s", error_text)
                    else:
                        logger.info("Submit clicked, no confirmation or error detected. Check screenshots.")
                except Exception:
                    logger.info("Submit clicked. Check screenshots to verify.")
        else:
            logger.warning("Could not find submit button!")

        # Summary
        print("\n" + "=" * 50)
        print("AGENTQL FORM FILL TEST RESULTS")
        print("=" * 50)
        print(f"URL: {JOB_URL}")
        print(f"Fields filled: {len(fields_filled)}")
        for f in fields_filled:
            print(f"  + {f}")
        print(f"Pre-submit screenshot: {pre_screenshot}")
        if submit_btn:
            print(f"Post-submit screenshot: {post_screenshot}")
            print(f"Submission confirmed: {'YES' if confirmed else 'CHECK SCREENSHOTS'}")
        else:
            print("Submit: BUTTON NOT FOUND")
        print("=" * 50)

        # Keep browser open for 10 seconds so user can see
        await page.wait_for_timeout(10000)
        await browser.close()


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    os.environ.setdefault("AGENTQL_API_KEY", os.environ.get("AGENTQL_KEY", ""))
    asyncio.run(run_test())
