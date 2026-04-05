#!/usr/bin/env python3
"""Validate required PR evidence packet sections for Foxhound."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PLACEHOLDER_VALUES = {
    "",
    "tbd",
    "todo",
    "fill",
    "fill me",
    "replace me",
    "pending",
}


def normalize(value: str) -> str:
    return re.sub(r"[`*_]", "", value).strip().lower()


def is_placeholder(value: str | None) -> bool:
    if value is None:
        return True
    return normalize(value) in PLACEHOLDER_VALUES


def get_label_value(body: str, label: str) -> str | None:
    pattern = re.compile(rf"(?im)^\s*-\s*{re.escape(label)}\s*:\s*(.*)$")
    match = pattern.search(body)
    if not match:
        return None
    return match.group(1).strip()


def has_url(value: str | None) -> bool:
    if value is None:
        return False
    return bool(re.search(r"https?://\S+", value))


def get_checkbox_state(body: str, label: str) -> str | None:
    pattern = re.compile(rf"(?im)^\s*-\s*\[(?P<state>[ xX])\]\s*{re.escape(label)}\s*$")
    match = pattern.search(body)
    if not match:
        return None
    return match.group("state")


def require_heading(body: str, heading: str, errors: list[str]) -> None:
    if re.search(rf"(?im)^\s*#+\s*{re.escape(heading)}\s*$", body) is None:
        errors.append(f"Missing heading: `{heading}`.")


def validate(body: str) -> list[str]:
    errors: list[str] = []

    if not body.strip():
        return ["PR body is empty. Paste and complete `.github/pull_request_template.md`."]

    required_headings = [
        "1) Links",
        "2) Work-Type Classification",
        "3) Commands + Pass Evidence (or CI Links)",
        "4) QA Verification Notes",
        "5) UI Evidence (Desktop + Mobile when relevant)",
        "6) Migration Evidence (when relevant)",
    ]
    for heading in required_headings:
        require_heading(body, heading, errors)

    pr_url = get_label_value(body, "PR URL")
    issue_url = get_label_value(body, "Linked Issue URL")
    if not has_url(pr_url):
        errors.append("`PR URL` must include a valid `http(s)://` URL.")
    if not has_url(issue_url):
        errors.append("`Linked Issue URL` must include a valid `http(s)://` URL.")

    checkbox_labels = [
        "Backend",
        "Frontend",
        "Migration",
        "Docs/Process only (no code-path impact)",
    ]
    selected_count = 0
    for label in checkbox_labels:
        state = get_checkbox_state(body, label)
        if state is None:
            errors.append(f"Missing checkbox line for `{label}`.")
            continue
        if state.lower() == "x":
            selected_count += 1
    if selected_count == 0:
        errors.append("Select at least one work-type checkbox.")

    for label in (
        "Backend commands/evidence",
        "Frontend commands/evidence",
        "Migration commands/evidence",
    ):
        value = get_label_value(body, label)
        if is_placeholder(value):
            errors.append(f"`{label}` is required. Use `N/A` only when untouched.")

    for label in ("Expected behavior", "What changed", "Known risks"):
        value = get_label_value(body, label)
        if is_placeholder(value):
            errors.append(f"`{label}` is required.")

    ui_na = get_label_value(body, "UI evidence N/A reason")
    if is_placeholder(ui_na):
        desktop = get_label_value(body, "Desktop screenshot(s)")
        mobile = get_label_value(body, "Mobile screenshot(s)")
        if is_placeholder(desktop):
            errors.append("`Desktop screenshot(s)` is required for UI changes (or provide `UI evidence N/A reason`).")
        if is_placeholder(mobile):
            errors.append("`Mobile screenshot(s)` is required for UI changes (or provide `UI evidence N/A reason`).")

    migration_na = get_label_value(body, "Migration evidence N/A reason")
    if is_placeholder(migration_na):
        for label in ("Migration plan", "Rollback plan", "Data/backfill risk notes"):
            value = get_label_value(body, label)
            if is_placeholder(value):
                errors.append(
                    f"`{label}` is required for migration changes (or provide `Migration evidence N/A reason`)."
                )

    return errors


def load_body(args: argparse.Namespace) -> str:
    if args.body_file:
        return Path(args.body_file).read_text(encoding="utf-8")

    event_path = args.event_path or os.getenv("GITHUB_EVENT_PATH")
    if not event_path:
        raise SystemExit("No event path found. Pass --event-path or set GITHUB_EVENT_PATH.")

    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pull_request = payload.get("pull_request")
    if not pull_request:
        print("No pull_request payload found; skipping PR evidence validation.")
        raise SystemExit(0)
    return pull_request.get("body") or ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-path", help="Path to GitHub event payload JSON.")
    parser.add_argument("--body-file", help="Path to a file containing PR body markdown.")
    args = parser.parse_args()

    body = load_body(args)
    errors = validate(body)

    if not errors:
        print("PR evidence packet validation passed.")
        return 0

    print("PR evidence packet validation failed.")
    print("")
    for error in errors:
        print(f"- {error}")
        print(f"::error::{error}")

    print("")
    print("How to fix:")
    print("1. Open `.github/pull_request_template.md` and copy any missing sections into the PR body.")
    print("2. Fill every required label with concrete evidence (`N/A reason` only for non-applicable sections).")
    print("3. Re-run the check by updating the PR description.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
