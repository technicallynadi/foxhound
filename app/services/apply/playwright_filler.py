"""Playwright CDP form filler: Phase 2 of the two-phase apply flow.

Replaces TinyFish agent.run() for form filling and submission.
Phase 1 (unchanged): TinyFish scans the form -> returns structured fields.
Phase 2 (this module): Playwright connects via CDP and fills everything.

Architecture:
1. Create TinyFish browser session -> get cdp_url
2. Connect Playwright via connect_over_cdp()
3. Dismiss cookie/consent banners
4. Match each scanned field to its DOM element and fill it
5. Upload resume via set_input_files()
6. Click Submit/Apply
7. Wait for confirmation, capture screenshot
8. Return structured result
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

from app.core.config import settings
from app.services.apply.ats_profiles import (
    ATSProfile,
    get_ats_profile,
    get_dropdown_selection,
)
from app.services.apply.form_scanner import (
    FormField,
    ScanResult,
    match_field_to_profile,
)
from app.services.discovery.ats_detector import detect_ats

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class FieldFillResult:
    label: str
    status: str  # "filled" | "skipped" | "not_found" | "error"
    value_used: str = ""
    error: str = ""


@dataclass
class FillResult:
    status: str  # "submitted" | "captcha" | "needs_manual" | "error"
    fields: list[FieldFillResult] = field(default_factory=list)
    fields_filled_count: int = 0
    fields_skipped_count: int = 0
    fields_errored_count: int = 0
    screenshot_bytes: bytes | None = None
    pre_submit_screenshot_bytes: bytes | None = None
    confirmation_text: str = ""
    error: str = ""
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Cookie/consent banner dismissal
# ---------------------------------------------------------------------------

# Selectors tried in order. First match wins.
_BANNER_DISMISS_SELECTORS = [
    # Common consent management platforms
    'button[id*="accept"]',
    'button[id*="consent"]',
    'button[class*="accept"]',
    'button[class*="consent"]',
    # Text-based matching (broadest)
    'button:has-text("Accept")',
    'button:has-text("Accept All")',
    'button:has-text("Accept Cookies")',
    'button:has-text("I Agree")',
    'button:has-text("Got it")',
    'button:has-text("OK")',
    'button:has-text("Close")',
    # CookieBot, OneTrust, etc.
    'a[id="CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"]',
    'button[id="onetrust-accept-btn-handler"]',
]


async def _dismiss_banners(page: Page) -> None:
    """Try to dismiss cookie/consent banners. Best-effort, no errors raised."""
    for selector in _BANNER_DISMISS_SELECTORS:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=500):
                await btn.click(timeout=2000)
                logger.debug("Dismissed banner via: %s", selector)
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Field matching and filling
# ---------------------------------------------------------------------------

# Ashby renders custom dropdowns as divs, not <select> elements.
# This detects them and handles them differently.
_ASHBY_CUSTOM_SELECT = '[class*="ashby-select"], [data-testid*="select"], [role="combobox"]'


async def _find_field(page: Page, form_field: FormField, ats: str | None) -> object | None:
    """Multi-strategy field locator. Returns a Playwright Locator or None.

    Strategy order (first match wins):
    1. get_by_label() -- works when <label for="..."> is properly linked
    2. label text -> associated input via for attribute
    3. placeholder text match
    4. aria-label match
    5. name attribute match (if field_name is available from scan)
    """
    label = form_field.label
    if not label:
        return None

    # Strategy 1: Playwright's built-in label association
    try:
        locator = page.get_by_label(label, exact=False)
        if await locator.count() > 0:
            first = locator.first
            if await first.is_visible(timeout=1000):
                return first
    except Exception:
        pass

    # Strategy 2: Find <label> by text, then follow its `for` attribute
    try:
        label_el = page.locator(f'label:has-text("{label}")').first
        if await label_el.is_visible(timeout=500):
            for_attr = await label_el.get_attribute("for")
            if for_attr:
                target = page.locator(f"#{for_attr}")
                if await target.count() > 0:
                    return target.first
            # No `for` -- look for the next sibling input/select/textarea
            parent = label_el.locator("xpath=..")
            for tag in ("input", "select", "textarea"):
                child = parent.locator(tag).first
                if await child.count() > 0 and await child.is_visible(timeout=500):
                    return child
    except Exception:
        pass

    # Strategy 3: Placeholder text
    try:
        placeholder_input = page.locator(
            f'input[placeholder*="{label}" i], textarea[placeholder*="{label}" i]'
        ).first
        if await placeholder_input.count() > 0 and await placeholder_input.is_visible(timeout=500):
            return placeholder_input
    except Exception:
        pass

    # Strategy 4: aria-label
    try:
        aria_input = page.locator(f'[aria-label*="{label}" i]').first
        if await aria_input.count() > 0 and await aria_input.is_visible(timeout=500):
            return aria_input
    except Exception:
        pass

    # Strategy 5: name attribute (if scan captured it)
    if form_field.field_name:
        try:
            named = page.locator(f'[name="{form_field.field_name}"]').first
            if await named.count() > 0 and await named.is_visible(timeout=500):
                return named
        except Exception:
            pass

    # Strategy 6: Partial text match on first ~40 chars of label
    # (long question labels often get truncated in DOM)
    if len(label) > 30:
        short_label = label[:40].rstrip()
        try:
            # Find any element containing the short text
            text_el = page.locator(f'text="{short_label}"').first
            if await text_el.count() > 0 and await text_el.is_visible(timeout=500):
                # Look for the nearest input/select/textarea
                parent = text_el.locator("xpath=ancestor::div[.//input or .//select or .//textarea][1]")
                if await parent.count() > 0:
                    for tag in ("select", "input", "textarea"):
                        child = parent.locator(tag).first
                        if await child.count() > 0 and await child.is_visible(timeout=500):
                            return child
        except Exception:
            pass

    # Strategy 7: Find by role with partial name
    if form_field.field_type == "radio":
        try:
            short = label[:50] if len(label) > 50 else label
            group = page.get_by_text(short, exact=False).first
            if await group.count() > 0:
                parent = group.locator("xpath=ancestor::fieldset[1] | xpath=ancestor::div[.//input[@type='radio']][1]")
                if await parent.count() > 0:
                    radio = parent.locator("input[type='radio']").first
                    if await radio.count() > 0:
                        return radio
        except Exception:
            pass

    return None


async def _fill_greenhouse_phone_country(
    page: Page, phone_locator, phone_value: str, location: str
) -> None:
    """Select the correct country code in Greenhouse's embedded phone dropdown.

    Greenhouse phone fields have a small country code select embedded
    inside the phone input container. It's a native <select> with id
    containing 'phone_country_code' or similar. The options look like
    'United States (+1)', 'Australia (+61)', etc.
    """
    # Extract country code from phone number
    phone_code = ""
    if phone_value:
        code_match = re.match(r"\+(\d{1,3})", phone_value)
        if code_match:
            phone_code = code_match.group(1)

    if not phone_code and not location:
        return  # Nothing to match on

    # Map country codes to search terms
    code_to_search = {
        "1": "United States", "44": "United Kingdom", "61": "Australia",
        "64": "New Zealand", "91": "India", "49": "Germany", "33": "France",
        "81": "Japan", "86": "China", "82": "Korea", "65": "Singapore",
        "852": "Hong Kong", "971": "United Arab Emirates", "353": "Ireland",
        "31": "Netherlands", "46": "Sweden", "47": "Norway", "45": "Denmark",
        "358": "Finland", "41": "Switzerland", "39": "Italy", "34": "Spain",
        "55": "Brazil", "52": "Mexico", "27": "South Africa", "63": "Philippines",
        "66": "Thailand", "60": "Malaysia", "62": "Indonesia", "84": "Vietnam",
        "886": "Taiwan", "972": "Israel", "966": "Saudi Arabia",
    }

    search_term = ""
    if phone_code and phone_code in code_to_search:
        search_term = code_to_search[phone_code]
    elif location:
        # Try to use location to find country
        abbrev_map = {
            "uk": "United Kingdom", "us": "United States", "usa": "United States",
            "au": "Australia", "nz": "New Zealand", "sg": "Singapore",
            "hk": "Hong Kong", "ie": "Ireland", "ca": "Canada",
        }
        parts = [p.strip().lower() for p in location.replace(",", " ").split()]
        for part in parts:
            if part in abbrev_map:
                search_term = abbrev_map[part]
                break
            if len(part) > 3:
                search_term = part.title()

    if not search_term:
        return

    try:
        # Strategy 1: intl-tel-input widget (most common on Greenhouse)
        # The phone input sits inside a .iti container with a flag dropdown
        iti_container = phone_locator.locator("xpath=ancestor::div[contains(@class, 'iti')]")
        if await iti_container.count() > 0:
            # Click the flag dropdown button to open the country list
            flag_btn = iti_container.locator(
                '.iti__selected-country, .iti__selected-flag, .iti__flag-container, '
                'button[aria-label*="country"], [class*="selected-flag"]'
            ).first
            if await flag_btn.count() > 0:
                await flag_btn.click()
                await page.wait_for_timeout(500)

                # The dropdown renders a .iti__country-list with <li> items
                # Each <li> has data-country-code and data-dial-code attributes
                # Try selecting by dial code first (most reliable)
                if phone_code:
                    country_item = iti_container.locator(
                        f'li[data-dial-code="{phone_code}"]'
                    ).first
                    if await country_item.count() > 0:
                        await country_item.click()
                        logger.info("Set phone country by dial code +%s", phone_code)
                        return

                # Try the search input if available (some ITI versions have it)
                search_input = iti_container.locator(
                    'input[type="search"], input.iti__search-input, input[placeholder*="search"]'
                ).first
                if await search_input.count() > 0 and await search_input.is_visible(timeout=500):
                    await search_input.fill(search_term)
                    await page.wait_for_timeout(500)
                    # Click first visible result
                    first_result = iti_container.locator(
                        'li.iti__country:not(.iti__hide)'
                    ).first
                    if await first_result.count() > 0:
                        await first_result.click()
                        logger.info("Set phone country via ITI search: %s", search_term)
                        return

                # Fallback: scroll through list and click matching country name
                country_items = iti_container.locator('li.iti__country, li[data-dial-code]')
                count = await country_items.count()
                for i in range(count):
                    item = country_items.nth(i)
                    text = await item.inner_text()
                    if search_term.lower() in text.lower():
                        await item.scroll_into_view_if_needed()
                        await item.click()
                        logger.info("Set phone country via ITI list scan: %s", text.strip()[:60])
                        return

                # Close dropdown if nothing matched
                await page.keyboard.press("Escape")
                logger.warning("Could not find country '%s' in ITI dropdown", search_term)
                return

        # Strategy 2: Native <select> for country code
        country_select = page.locator(
            'select[id*="phone_country"], '
            'select[id*="country_code"], '
            'select[name*="phone_country"], '
            'select[name*="country_code"]'
        ).first

        if await country_select.count() > 0 and await country_select.is_visible(timeout=2000):
            options = await country_select.locator("option").all_text_contents()
            best = None
            for opt in options:
                if search_term.lower() in opt.lower():
                    best = opt
                    break
            if not best and phone_code:
                for opt in options:
                    if f"+{phone_code}" in opt:
                        best = opt
                        break
            if best:
                await country_select.select_option(label=best, timeout=3000)
                logger.info("Set phone country via native select: %s", best)
                return

    except Exception as e:
        logger.warning("Failed to set Greenhouse phone country: %s", str(e)[:200])


async def _fill_text(page: Page, locator, value: str) -> None:
    """Fill a text input or textarea.

    Short values (<100 chars): types character-by-character to trigger
    autocomplete suggestions (location, country fields).
    Long values (>100 chars): uses instant fill() to avoid timeouts.
    """
    await locator.click()
    await locator.fill("")  # clear

    if len(value) > 100:
        # Long text (textareas, essays) — instant fill, no autocomplete needed
        await locator.fill(value)
        return

    # Short text — type slowly to trigger autocomplete suggestions
    await locator.press_sequentially(value, delay=50)
    await page.wait_for_timeout(800)

    # Check if an autocomplete dropdown appeared — click first suggestion
    suggestion_selectors = [
        '[role="option"]',
        '[role="listbox"] >> li',
        'ul[class*="autocomplete"] >> li',
        'div[class*="suggestion"]',
        'div[class*="dropdown"] >> li',
        'div[class*="menu"] >> div[class*="option"]',
    ]
    for sel in suggestion_selectors:
        try:
            suggestion = page.locator(sel).first
            if await suggestion.is_visible(timeout=500):
                await suggestion.click()
                logger.info("Clicked autocomplete suggestion")
                return
        except Exception:
            continue


async def _fill_select(page: Page, locator, form_field: FormField, value: str, ats: str | None) -> None:
    """Fill a <select> dropdown or a custom React dropdown.

    Native <select>: use select_option(label=...).
    Custom dropdown (Ashby, React Select): click to open, then click option.
    """
    tag = await locator.evaluate("el => el.tagName.toLowerCase()")

    if tag == "select":
        # Native select -- try exact label match first, then fuzzy
        try:
            await locator.select_option(label=value, timeout=2000)
            return
        except Exception:
            pass
        # Fuzzy: find the closest option text
        options = await locator.locator("option").all_text_contents()
        best = _fuzzy_match_option(value, options)
        if best:
            await locator.select_option(label=best, timeout=2000)
        return

    # Custom dropdown (common in Ashby, React apps)
    await _fill_custom_dropdown(page, locator, value)


async def _fill_custom_dropdown(page: Page, locator, value: str) -> None:
    """Handle non-native dropdowns: click to open, then click the matching option."""
    await locator.click()
    await page.wait_for_timeout(500)  # wait for dropdown panel to render

    # Look for the option in common dropdown panel patterns
    option_selectors = [
        f'[role="option"]:has-text("{value}")',
        f'[role="listbox"] >> text="{value}"',
        f'li:has-text("{value}")',
        f'div[class*="option"]:has-text("{value}")',
        f'div[class*="menu"] >> text="{value}"',
    ]

    for sel in option_selectors:
        try:
            opt = page.locator(sel).first
            if await opt.is_visible(timeout=1000):
                await opt.click()
                return
        except Exception:
            continue

    # Last resort: type the value to filter, then press Enter
    try:
        await locator.fill(value)
        await page.wait_for_timeout(300)
        await page.keyboard.press("Enter")
    except Exception:
        pass


async def _fill_radio(page: Page, form_field: FormField, value: str) -> None:
    """Click the radio button matching the value text.

    Radio buttons are tricky -- they share a name, so we find
    the group by label text then click the option matching value.
    """
    # Find all radio inputs in the group near the label
    selectors = [
        f'input[type="radio"][value="{value}"]',
        f'label:has-text("{value}") >> input[type="radio"]',
        f'label:has-text("{value}")',
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=1000):
                await el.click()
                return
        except Exception:
            continue


async def _fill_checkbox(page: Page, form_field: FormField, value: str) -> None:
    """Check a checkbox if the value indicates it should be checked."""
    should_check = value.lower() in ("true", "yes", "1", "checked")
    try:
        locator = page.get_by_label(form_field.label, exact=False).first
        if locator:
            is_checked = await locator.is_checked()
            if should_check and not is_checked:
                await locator.check()
            elif not should_check and is_checked:
                await locator.uncheck()
    except Exception:
        # Fallback: click the label
        try:
            label_el = page.locator(f'label:has-text("{form_field.label}")').first
            await label_el.click()
        except Exception:
            pass


async def _upload_file(page: Page, pdf_bytes: bytes, filename: str) -> bool:
    """Upload resume by clicking the upload button and intercepting the file dialog.

    Strategy: click the visible "Select file" / upload button, intercept the
    native file chooser dialog via Playwright, and provide the file.
    This goes through the React component's normal event flow, so it works
    on custom upload components (Ashby, Greenhouse, etc.).

    Falls back to set_input_files() on the hidden input if no clickable
    upload button is found.
    """
    file_data = {"name": filename, "mimeType": "application/pdf", "buffer": pdf_bytes}

    # Strategy 1: Click upload button + intercept file chooser (works with React components)
    upload_button_selectors = [
        'button:has-text("Upload file")',
        'button:has-text("Select file")',
        'button:has-text("Upload")',
        'button:has-text("Choose file")',
        'label:has-text("Upload file")',
        'label:has-text("Select file")',
        'label:has-text("Upload")',
        'span:has-text("Upload file")',
        'span:has-text("Select file")',
        'div[class*="upload"]',
        'div[class*="dropzone"]',
    ]

    for sel in upload_button_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                logger.info("Clicking upload button: %s", sel)
                async with page.expect_file_chooser(timeout=5000) as fc_info:
                    await btn.click()
                file_chooser = await fc_info.value
                await file_chooser.set_files(file_data)
                await page.wait_for_timeout(2000)
                logger.info("Resume uploaded via file chooser: %s (%d bytes)", filename, len(pdf_bytes))
                return True
        except Exception as e:
            logger.debug("Upload button %s failed: %s", sel, e)
            continue

    # Strategy 2: Direct set_input_files on hidden input + React events (fallback)
    try:
        file_input = page.locator('input[type="file"]').first
        if await file_input.count() > 0:
            await file_input.set_input_files(file_data)
            await file_input.evaluate("""el => {
                const tracker = el._valueTracker;
                if (tracker) tracker.setValue('');
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""")
            await page.wait_for_timeout(2000)
            logger.info("Resume uploaded via set_input_files fallback: %s (%d bytes)", filename, len(pdf_bytes))
            return True
    except Exception as e:
        logger.warning("set_input_files fallback failed: %s", e)

    logger.warning("No file upload method worked")
    return False


def _fuzzy_match_option(target: str, options: list[str]) -> str | None:
    """Find the best matching option text. Case-insensitive substring match."""
    target_lower = target.lower().strip()

    # Exact match (case-insensitive)
    for opt in options:
        if opt.strip().lower() == target_lower:
            return opt

    # Substring match
    for opt in options:
        if target_lower in opt.lower() or opt.lower() in target_lower:
            return opt

    return None


# ---------------------------------------------------------------------------
# Submit button detection
# ---------------------------------------------------------------------------

_SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Submit Application")',
    'button:has-text("Submit")',
    'button:has-text("Apply")',
    'button:has-text("Apply Now")',
    'button:has-text("Send Application")',
    # Ashby-specific
    'button[data-testid="submit-application"]',
]

# Confirmation page detection patterns
_CONFIRMATION_PATTERNS = [
    "your application has been submitted",
    "application has been submitted",
    "application submitted",
    "successfully submitted",
    "thank you for applying",
    "thanks for applying",
    "thank you for your interest",
    "thank you for your application",
    "we have received your application",
    "application received",
    "we received your application",
]


async def _click_submit(page: Page, ats_profile: ATSProfile | None) -> bool:
    """Find and click the submit button. Returns True if clicked."""
    # Use ATS-specific button text first
    selectors = list(_SUBMIT_SELECTORS)
    if ats_profile and ats_profile.submit_button_text:
        for text in ats_profile.submit_button_text:
            selectors.insert(0, f'button:has-text("{text}")')

    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                await btn.scroll_into_view_if_needed()
                await page.wait_for_timeout(300)
                await btn.click()
                logger.info("Clicked submit via: %s", sel)
                # Wait a moment to see if form actually submits
                await page.wait_for_timeout(2000)
                return True
        except Exception:
            continue

    # Fallback: try form.submit() via JavaScript
    try:
        submitted = await page.evaluate("""() => {
            const form = document.querySelector('form');
            if (form) {
                // Try clicking the submit button via JS (bypasses some overlay issues)
                const btn = form.querySelector('button[type="submit"], input[type="submit"]');
                if (btn) {
                    btn.click();
                    return 'button_js';
                }
                // Last resort: form.submit() — may skip validation
                form.submit();
                return 'form_submit';
            }
            return null;
        }""")
        if submitted:
            logger.info("Submit fallback via JS: %s", submitted)
            await page.wait_for_timeout(2000)
            return True
    except Exception as e:
        logger.warning("JS submit fallback failed: %s", str(e)[:200])

    return False


async def _wait_for_confirmation(page: Page, ats_profile: ATSProfile | None) -> str:
    """Wait for confirmation page after submit. Returns confirmation text or empty.

    Checks immediately after submit, then again after a short wait.
    CDP sessions can close quickly so we check fast.
    """
    patterns = list(_CONFIRMATION_PATTERNS)
    if ats_profile and ats_profile.confirmation_patterns:
        patterns = ats_profile.confirmation_patterns + patterns

    # Check immediately — don't wait, CDP sessions can close fast
    result = await _check_page_for_patterns(page, patterns)
    if result:
        return result

    # Brief wait then check again
    try:
        await page.wait_for_timeout(2000)
    except Exception:
        pass

    result = await _check_page_for_patterns(page, patterns)
    if result:
        return result

    # Check if URL changed to a confirmation page
    try:
        current_url = page.url
        if any(kw in current_url.lower() for kw in ["confirm", "success", "thank"]):
            return f"Redirected to: {current_url}"
    except Exception:
        pass

    return ""


async def _check_page_for_patterns(page, patterns: list[str]) -> str:
    """Check current page text against confirmation patterns."""
    try:
        body_text = await page.inner_text("body")
        body_lower = body_text.lower()
        for pattern in patterns:
            if pattern in body_lower:
                idx = body_lower.index(pattern)
                start = max(0, idx - 20)
                end = min(len(body_text), idx + len(pattern) + 80)
                return body_text[start:end].strip()
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Profile data -> field value resolution
# ---------------------------------------------------------------------------


def _resolve_field_value(
    form_field: FormField,
    profile_data: dict,
    custom_answers: dict[str, str],
) -> str | None:
    """Determine what value to fill for a given form field.

    Priority:
    1. Custom answers (user-provided or LLM-drafted)
    2. Profile field match (auto-fill from resume data)
    3. Dropdown default selection (EEO/demographic)
    4. None (skip this field)
    """
    label = form_field.label
    label_lower = label.lower().strip()

    # 1. Check custom answers (exact label match)
    if label in custom_answers:
        return custom_answers[label]
    # Fuzzy match on custom answers
    for q, a in custom_answers.items():
        if q.lower().strip() == label_lower:
            return a

    # 2. Country phone code dropdown — match full option with code
    _is_phone_country = (
        form_field.field_type == "select"
        and form_field.options
        and any("+" in opt for opt in form_field.options)
        and any(
            kw in label_lower
            for kw in ("country", "country code", "phone country", "dialing", "dial code")
        )
    )
    if _is_phone_country:
        # Try to extract country from profile phone number first
        phone = profile_data.get("phone", "")
        phone_code = ""
        if phone:
            import re as _re
            code_match = _re.match(r"\+(\d{1,3})", phone)
            if code_match:
                phone_code = code_match.group(1)

        # Map phone country codes to country names for matching
        code_to_country = {
            "1": ["United States", "US", "USA", "Canada"],
            "44": ["United Kingdom", "UK", "Great Britain"],
            "61": ["Australia"],
            "64": ["New Zealand"],
            "91": ["India"],
            "49": ["Germany"],
            "33": ["France"],
            "81": ["Japan"],
            "86": ["China"],
            "82": ["South Korea", "Korea"],
            "65": ["Singapore"],
            "852": ["Hong Kong"],
            "971": ["United Arab Emirates", "UAE"],
            "353": ["Ireland"],
            "31": ["Netherlands"],
            "46": ["Sweden"],
            "47": ["Norway"],
            "45": ["Denmark"],
            "358": ["Finland"],
            "41": ["Switzerland"],
            "39": ["Italy"],
            "34": ["Spain"],
            "351": ["Portugal"],
            "48": ["Poland"],
            "55": ["Brazil"],
            "52": ["Mexico"],
            "7": ["Russia"],
            "972": ["Israel"],
            "966": ["Saudi Arabia"],
            "27": ["South Africa"],
            "234": ["Nigeria"],
            "254": ["Kenya"],
            "63": ["Philippines"],
            "66": ["Thailand"],
            "60": ["Malaysia"],
            "62": ["Indonesia"],
            "84": ["Vietnam"],
            "886": ["Taiwan"],
        }

        # Strategy 1: Match by phone country code from profile phone number
        if phone_code and phone_code in code_to_country:
            country_names = code_to_country[phone_code]
            for name in country_names:
                for opt in form_field.options:
                    if name.lower() in opt.lower():
                        return opt
            # Also try matching the raw code like "+1" or "+44"
            for opt in form_field.options:
                if f"+{phone_code}" in opt:
                    return opt

        # Strategy 2: Match by location from profile
        location = profile_data.get("location", "")
        country_hints = []
        if location:
            parts = [p.strip() for p in location.replace(",", " ").split()]
            country_hints.extend(parts)
            country_hints.append(location)
        # Map common abbreviations
        abbrev_map = {
            "uk": "United Kingdom", "us": "United States", "usa": "United States",
            "uae": "United Arab Emirates", "hk": "Hong Kong", "sg": "Singapore",
            "au": "Australia", "nz": "New Zealand", "ca": "Canada",
            "de": "Germany", "fr": "France", "jp": "Japan", "in": "India",
            "ie": "Ireland", "nl": "Netherlands", "se": "Sweden",
            "no": "Norway", "dk": "Denmark", "fi": "Finland", "ch": "Switzerland",
            "br": "Brazil", "mx": "Mexico", "za": "South Africa",
            "ph": "Philippines", "th": "Thailand", "my": "Malaysia",
            "id": "Indonesia", "vn": "Vietnam", "tw": "Taiwan",
            "kr": "South Korea", "il": "Israel",
        }
        expanded = []
        for h in country_hints:
            expanded.append(h)
            if h.lower() in abbrev_map:
                expanded.append(abbrev_map[h.lower()])
        # Find the matching option
        for hint in expanded:
            for opt in form_field.options:
                if hint.lower() in opt.lower():
                    return opt
        # Fallback to first option with +1 (US) or first non-placeholder option
        for opt in form_field.options:
            if "+1" in opt and ("united states" in opt.lower() or "us" in opt.lower()):
                return opt
        return form_field.options[0] if form_field.options else None

    # 2a. Plain country dropdown (no "+" in options) — Greenhouse style
    # Greenhouse puts a "Country" select with 200+ plain country names next to the phone field
    _is_plain_country = (
        form_field.field_type == "select"
        and form_field.options
        and len(form_field.options) > 50
        and label_lower in ("country", "country *")
        and not any("+" in opt for opt in form_field.options[:20])
    )
    if _is_plain_country:
        phone = profile_data.get("phone", "")
        location = profile_data.get("location", "")

        # Extract country code from phone number
        phone_code = ""
        if phone:
            import re as _re
            code_match = _re.match(r"\+(\d{1,3})", phone)
            if code_match:
                phone_code = code_match.group(1)

        # Map dial codes to country names for plain-text matching
        code_to_country = {
            "1": "United States", "44": "United Kingdom", "61": "Australia",
            "64": "New Zealand", "91": "India", "49": "Germany", "33": "France",
            "81": "Japan", "86": "China", "82": "South Korea", "65": "Singapore",
            "852": "Hong Kong", "971": "United Arab Emirates", "353": "Ireland",
            "31": "Netherlands", "46": "Sweden", "47": "Norway", "45": "Denmark",
            "41": "Switzerland", "39": "Italy", "34": "Spain", "55": "Brazil",
            "52": "Mexico", "27": "South Africa", "63": "Philippines",
            "66": "Thailand", "60": "Malaysia", "62": "Indonesia",
            "7": "Russia", "48": "Poland", "351": "Portugal",
            "972": "Israel", "966": "Saudi Arabia", "234": "Nigeria",
        }
        abbrev_map = {
            "uk": "United Kingdom", "us": "United States", "usa": "United States",
            "au": "Australia", "nz": "New Zealand", "sg": "Singapore",
            "hk": "Hong Kong", "ie": "Ireland", "ca": "Canada",
            "de": "Germany", "fr": "France", "jp": "Japan", "in": "India",
        }

        # Strategy 1: Match by phone country code
        search_terms = []
        if phone_code and phone_code in code_to_country:
            search_terms.append(code_to_country[phone_code])

        # Strategy 2: Match by location
        if location:
            parts = [p.strip() for p in location.replace(",", " ").split()]
            for part in parts:
                if part.lower() in abbrev_map:
                    search_terms.append(abbrev_map[part.lower()])
                elif len(part) > 3:
                    search_terms.append(part)

        for term in search_terms:
            for opt in form_field.options:
                if term.lower() == opt.lower():
                    return opt
            for opt in form_field.options:
                if term.lower() in opt.lower():
                    return opt

        # Default to United States
        for opt in form_field.options:
            if opt.lower() == "united states":
                return opt

    # 2b. Profile field auto-fill
    profile_key = match_field_to_profile(label)
    if profile_key:
        val = profile_data.get(profile_key)
        if val:
            # Strip country code from phone when form has a separate country dropdown
            if profile_key == "phone":
                import re
                val = re.sub(r"^\+\d{1,3}\s*", "", val)
            return val

    # 3. Dropdown/radio defaults (EEO, "how did you hear", etc.)
    if form_field.field_type in ("select", "radio") and form_field.options:
        selection = get_dropdown_selection(label, form_field.options, profile_data)
        if selection:
            return selection

    # 4. Working arrangement / hybrid / office policy questions
    if form_field.field_type in ("select", "radio") and form_field.options:
        work_keywords = ["working policy", "work arrangement", "office", "hybrid", "remote", "on-site"]
        if any(kw in label_lower for kw in work_keywords):
            # Prefer hybrid, then office, then remote
            for opt in form_field.options:
                if "hybrid" in opt.lower():
                    return opt
            for opt in form_field.options:
                if "office" in opt.lower() and "remote" not in opt.lower():
                    return opt
            if form_field.options:
                return form_field.options[0]

    # 5. Common yes/no confirmation questions
    confirm_patterns = [
        "confirm", "suitable", "agree", "acknowledge", "consent",
        "reasonable adjustments", "accommodations", "disability",
    ]
    if any(p in label_lower for p in confirm_patterns):
        # For "do you require adjustments" type questions, answer No
        if "require" in label_lower and ("adjust" in label_lower or "accommodat" in label_lower):
            return "No"
        # For select fields, find a "Yes" option
        if form_field.field_type in ("select", "radio") and form_field.options:
            for opt in form_field.options:
                if opt.lower().startswith("yes"):
                    return opt
        return "Yes"

    return None


def _build_profile_data(profile) -> dict:
    """Extract a flat dict of fillable values from a UserProfile."""
    import json

    experience = json.loads(profile.experience_json or "[]")
    current = experience[0] if experience else {}

    name = f"{profile.first_name or ''} {profile.last_name or ''}".strip()

    return {
        "first_name": profile.first_name or "",
        "last_name": profile.last_name or "",
        "full_name": name,
        "email": profile.email or "",
        "phone": profile.phone or "",
        "linkedin": profile.linkedin_url or "",
        "portfolio": profile.portfolio_url or "",
        "location": profile.location or "",
        "current_company": current.get("company", ""),
        "current_title": current.get("title", ""),
        "years_experience": str(profile.years_experience or ""),
        # Application-specific fields (set in profile settings)
        "salary": getattr(profile, "salary_expectation", "") or "",
        "start_date": getattr(profile, "notice_period", "") or "",
        "visa_status": getattr(profile, "visa_status", "") or "",
        "clearance": getattr(profile, "clearance_type", "") or "",
        "work_preference": getattr(profile, "work_preference", "") or "",
        "gender": getattr(profile, "gender", "") or "",
        "race": getattr(profile, "race", "") or "",
        "hispanic_latino": getattr(profile, "hispanic_latino", None),
        "veteran_status": getattr(profile, "veteran_status", "") or "",
        "disability_status": getattr(profile, "disability_status", "") or "",
        "how_did_you_hear": getattr(profile, "how_did_you_hear", "") or "",
    }


# ---------------------------------------------------------------------------
# CDP session management
# ---------------------------------------------------------------------------


async def _create_cdp_session(apply_url: str) -> dict:
    """Create a TinyFish CDP browser session.

    POST https://agent.tinyfish.ai/v1/browser
    Returns: {"cdp_url": "wss://...", "session_id": "..."}
    """
    api_key = settings.tinyfish_api_key
    if not api_key:
        raise RuntimeError("TINYFISH_API_KEY not set")

    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.post(
            "https://agent.tinyfish.ai/v1/browser",
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            json={"url": apply_url},
        )
        resp.raise_for_status()
        session = resp.json()

    cdp_url = session.get("cdp_url")
    if not cdp_url:
        raise RuntimeError(f"No cdp_url in browser session response: {session}")

    logger.info("CDP session created: %s", session.get("session_id", "?"))
    return session


# ---------------------------------------------------------------------------
# ATS-aware navigation: get from job page to actual application form
# ---------------------------------------------------------------------------

# Selectors that indicate we are already on the application form page
_FORM_PRESENT_SELECTORS = [
    'form input[type="text"]',
    'form input[type="email"]',
    'input[name*="name"]',
    'input[name*="email"]',
    '[data-testid="application-form"]',
]

# Regex pattern for any button/link containing "apply" (case-insensitive)
_APPLY_REGEX = re.compile(r"apply", re.IGNORECASE)


async def _has_form_on_page(page: Page) -> bool:
    """Check whether the current page already has application form inputs."""
    for sel in _FORM_PRESENT_SELECTORS:
        try:
            if await page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


async def _navigate_to_form(page: Page, apply_url: str, ats: str | None) -> None:
    """Navigate from job description page to the actual application form.

    This is the "smart navigation" layer that replaces TinyFish agent
    intelligence for the bounded problem of reaching the form.

    Strategies per ATS:
    - Greenhouse: Form is directly on the page. No navigation needed.
    - Ashby: Append /application to the URL, or click the Apply button.
    - Unknown ATS: Check for form; if absent, try clicking Apply buttons.
    """
    # If the form is already on the page, nothing to do
    if await _has_form_on_page(page):
        logger.info("Form inputs already present on page")
        return

    # --- Ashby: click Apply button on job page ---
    if ats == "ashby":
        clicked = False
        for role in ["link", "button"]:
            try:
                apply_el = page.get_by_role(role, name=_APPLY_REGEX).first
                if await apply_el.is_visible(timeout=3000):
                    logger.info("Ashby: clicking Apply %s on job page", role)
                    await apply_el.click()
                    clicked = True
                    break
            except Exception:
                continue

        if clicked:
            # Wait for navigation to complete (Ashby SPA route change)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception:
                pass
            # Wait for React form to render — poll until inputs appear
            for attempt in range(10):
                await page.wait_for_timeout(1500)
                if await _has_form_on_page(page):
                    logger.info("Ashby: form appeared after %d.5s", attempt + 1)
                    return
                # Keep page active to prevent CDP timeout
                try:
                    await page.evaluate("document.readyState")
                except Exception:
                    break
            logger.warning("Ashby: form not found after Apply click + 15s wait")

    # --- Generic: click any visible link/button containing "apply" ---
    try:
        # Playwright's get_by_role with regex matches any a/button with "apply" in the text
        apply_link = page.get_by_role("link", name=_APPLY_REGEX).first
        if await apply_link.is_visible(timeout=2000):
            logger.info("Clicking apply link: %s", await apply_link.text_content())
            await apply_link.click()
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception:
                pass
            await page.wait_for_timeout(2000)
            if await _has_form_on_page(page):
                return
    except Exception:
        pass

    try:
        apply_btn = page.get_by_role("button", name=_APPLY_REGEX).first
        if await apply_btn.is_visible(timeout=1500):
            logger.info("Clicking apply button: %s", await apply_btn.text_content())
            await apply_btn.click()
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception:
                pass
            await page.wait_for_timeout(2000)
            if await _has_form_on_page(page):
                return
    except Exception:
        pass

    # Fallback: href containing /application
    try:
        app_href = page.locator('a[href*="/application"]').first
        if await app_href.is_visible(timeout=1500):
            logger.info("Clicking application href link")
            await app_href.click()
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception:
                pass
            await page.wait_for_timeout(2000)
            if await _has_form_on_page(page):
                return
    except Exception:
        pass

    # --- Last resort: scroll down and check again ---
    # Some sites have the form below the fold on the same page
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1500)
        if await _has_form_on_page(page):
            logger.info("Form found after scrolling")
            return
    except Exception:
        pass

    logger.warning("Could not find application form via navigation — proceeding with current page")


# ---------------------------------------------------------------------------
# Ashby-specific handling
# ---------------------------------------------------------------------------


async def _wait_for_react_form(page: Page, ats: str | None) -> None:
    """Wait for JS-rendered forms to appear in the DOM.

    IMPORTANT: TinyFish CDP sessions have short idle timeouts.
    Keep waits minimal and stay active (no long pauses).

    Ashby forms are React SPAs that render after hydration.
    Greenhouse forms are mostly server-rendered.
    """
    selectors = "form, [data-testid='application-form'], input[type='text'], input[type='email']"
    timeout = 8_000 if ats == "ashby" else 5_000

    try:
        await page.wait_for_selector(selectors, timeout=timeout)
    except Exception:
        logger.warning("Form elements not found within %dms — proceeding anyway", timeout)
        # Scroll to trigger lazy loading
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def fill_and_submit(
    apply_url: str,
    scan_result: ScanResult,
    profile,
    custom_answers: list[dict] | None = None,
    resume_bytes: bytes | None = None,
    resume_filename: str = "resume.pdf",
) -> FillResult:
    """Phase 2: Connect to CDP browser, fill form fields, submit.

    Args:
        apply_url: The job application URL.
        scan_result: Output from Phase 1 scan (field definitions).
        profile: UserProfile ORM object.
        custom_answers: List of {"question": ..., "answer": ...} dicts.
        resume_bytes: PDF bytes for file upload (None to skip).
        resume_filename: Filename for the uploaded resume.

    Returns:
        FillResult with status, per-field results, and optional screenshot.
    """
    from playwright.async_api import async_playwright

    t0 = time.monotonic()
    ats = detect_ats(apply_url)
    ats_profile = get_ats_profile(ats)

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
        # 1. Create CDP session
        session = await _create_cdp_session(apply_url)
        cdp_url = session["cdp_url"]

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()

            # 2. Check if TinyFish already navigated (POST /v1/browser takes url param)
            current_url = page.url
            if current_url and current_url != "about:blank":
                logger.info("TinyFish pre-navigated to %s", current_url)
            else:
                await page.goto(apply_url, wait_until="domcontentloaded", timeout=60_000)
                logger.info("Navigated to %s", apply_url)

            # 3. Dismiss cookie/consent banners (before navigation so overlays don't block clicks)
            await _dismiss_banners(page)

            # 4. Navigate to application form if not already there
            #    Handles: Ashby /application sub-path, "Apply" button clicks, scroll-to-form
            await _navigate_to_form(page, apply_url, ats)

            # 5. Wait for form to render (critical for Ashby React SPA)
            await _wait_for_react_form(page, ats)

            # 6. Scroll to make form visible
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
            await page.wait_for_timeout(500)

            # 7. Check for blockers (CAPTCHA, login wall)
            body_text_lower = ""
            try:
                body_text_lower = (await page.inner_text("body")).lower()
            except Exception:
                pass

            if "captcha" in body_text_lower and any(
                kw in body_text_lower for kw in ["verify", "robot", "human"]
            ):
                return FillResult(
                    status="captcha",
                    error="CAPTCHA detected on form page",
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )

            if any(kw in body_text_lower for kw in ["sign in", "log in", "create account"]):
                # Check if this is really a login wall, not just a nav link
                login_form = await page.locator('input[type="password"]').count()
                if login_form > 0:
                    return FillResult(
                        status="needs_manual",
                        error="Login/account creation required",
                        duration_ms=int((time.monotonic() - t0) * 1000),
                    )

            # 8. Fill each field
            for form_field in scan_result.fields:
                if form_field.field_type == "file":
                    # Handle file upload separately below
                    continue
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

                # Find the DOM element — scroll down and retry if not found
                locator = await _find_field(page, form_field, ats)
                if not locator:
                    # Scroll down and try again
                    await page.evaluate("window.scrollBy(0, 500)")
                    await page.wait_for_timeout(500)
                    locator = await _find_field(page, form_field, ats)
                if not locator:
                    # Scroll to bottom and try once more
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(500)
                    locator = await _find_field(page, form_field, ats)
                if not locator:
                    field_results.append(FieldFillResult(
                        label=form_field.label, status="not_found",
                        error="Could not locate field in DOM",
                    ))
                    errored += 1
                    logger.warning("Not found in DOM: '%s'", form_field.label)
                    continue

                # Fill based on field type
                try:
                    await locator.scroll_into_view_if_needed(timeout=3000)

                    if form_field.field_type in ("text", "email", "tel", "url", "number", "date"):
                        # Greenhouse phone fields have an embedded country code dropdown
                        if form_field.field_type == "tel" and ats == "greenhouse":
                            await _fill_greenhouse_phone_country(
                                page, locator, profile_data.get("phone", ""),
                                profile_data.get("location", ""),
                            )
                        await _fill_text(page, locator, value)
                    elif form_field.field_type == "textarea":
                        await _fill_text(page, locator, value)
                    elif form_field.field_type == "select":
                        await _fill_select(page, locator, form_field, value, ats)
                    elif form_field.field_type == "radio":
                        await _fill_radio(page, form_field, value)
                    elif form_field.field_type == "checkbox":
                        await _fill_checkbox(page, form_field, value)
                    else:
                        # Unknown type -- try text fill as fallback
                        await _fill_text(page, locator, value)

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

                # Minimal pause between fields — CDP sessions have short timeouts
                await page.wait_for_timeout(100)

            logger.info("Field fill summary: %d filled, %d skipped, %d errors out of %d", filled, skipped, errored, len(scan_result.fields))

            # 9. Upload resume
            resume_attached = False
            if resume_bytes and scan_result.has_file_upload:
                resume_attached = await _upload_file(page, resume_bytes, resume_filename)

            # 10. Screenshot BEFORE submit (shows filled form)
            pre_submit_screenshot = await _safe_screenshot(page)

            # 11. Scroll to bottom (submit buttons are usually there)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(500)

            # 12. Click submit
            submitted = await _click_submit(page, ats_profile)
            if not submitted:
                # Capture screenshot before returning
                screenshot = await _safe_screenshot(page)
                return FillResult(
                    status="needs_manual",
                    fields=field_results,
                    fields_filled_count=filled,
                    fields_skipped_count=skipped,
                    fields_errored_count=errored,
                    screenshot_bytes=screenshot,
                    error="Submit button not found or not clickable",
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )

            # 12. Wait for confirmation
            confirmation = await _wait_for_confirmation(page, ats_profile)

            # 13. Check for post-submit blockers
            post_body = ""
            try:
                post_body = (await page.inner_text("body")).lower()
            except Exception:
                pass

            if "captcha" in post_body:
                screenshot = await _safe_screenshot(page)
                return FillResult(
                    status="captcha",
                    fields=field_results,
                    fields_filled_count=filled,
                    fields_skipped_count=skipped,
                    fields_errored_count=errored,
                    screenshot_bytes=screenshot,
                    error="CAPTCHA appeared after submit",
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )

            # 14. Capture screenshot
            screenshot = await _safe_screenshot(page)

            if confirmation:
                status = "submitted"
            else:
                # Check URL change — redirect usually means submitted
                try:
                    current_url = page.url
                    if current_url != apply_url:
                        status = "submitted"
                        confirmation = f"Redirected to: {current_url}"
                    else:
                        # Submit clicked but no confirmation detected
                        # Mark as needs_manual — don't lie about status
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

    except httpx.HTTPStatusError as e:
        return FillResult(
            status="error",
            error=f"CDP session creation failed: {e.response.status_code} {e.response.text[:200]}",
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as e:
        logger.exception("Playwright fill failed")
        return FillResult(
            status="error",
            fields=field_results,
            fields_filled_count=filled,
            fields_skipped_count=skipped,
            fields_errored_count=errored,
            error=str(e),
            duration_ms=int((time.monotonic() - t0) * 1000),
        )


async def _safe_screenshot(page: Page) -> bytes | None:
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
    """Full convenience wrapper: downloads resume, then fills.

    This is the entry point the orchestrator should call.
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

    return await fill_and_submit(
        apply_url=apply_url,
        scan_result=scan_result,
        profile=profile,
        custom_answers=custom_answers,
        resume_bytes=resume_bytes,
        resume_filename=resume_filename,
    )
