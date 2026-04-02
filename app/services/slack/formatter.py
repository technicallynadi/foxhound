"""Format FoxhoundAgent responses as Slack Block Kit messages.

Handles different tool result types: job matches, application status,
questions, and screenshots.
"""

from __future__ import annotations

from urllib.parse import quote_plus


def format_agent_response(response_dict: dict) -> list[dict]:
    """Convert a FoxhoundAgent response dict into Slack Block Kit blocks.

    The response_dict has the shape returned by ``FoxhoundAgent.respond()``:
        {
            "response": str,          # main text
            "tool_calls": [...],       # tools invoked
            "tool_results": [...],     # tool outputs
            ...
        }

    Returns a list of Block Kit block dicts ready for chat.postMessage.
    """
    blocks: list[dict] = []

    # Always include the main text response
    text = response_dict.get("response", "")
    if text:
        blocks.append(_section(text))

    # Process tool results for rich formatting
    for result_entry in response_dict.get("tool_results", []):
        tool_name = result_entry.get("tool", "")
        result = result_entry.get("result", {})

        if not isinstance(result, dict):
            continue

        tool_blocks = _format_tool_result(tool_name, result)
        if tool_blocks:
            blocks.extend(tool_blocks)

    return blocks or [_section(text or "Done.")]


def _format_tool_result(tool_name: str, result: dict) -> list[dict]:
    """Dispatch to specialised formatters based on tool name."""
    if tool_name in ("search_jobs", "get_job_matches"):
        return _format_job_matches(result)
    if tool_name == "discover_jobs":
        return _format_discovery(result)
    if tool_name in ("apply_to_job", "get_application_status", "check_application"):
        return _format_application_status(result)
    if tool_name == "answer_application_questions":
        return _format_questions(result)
    if tool_name in ("get_applications", "list_applications"):
        return _format_applications_list(result)
    if tool_name == "get_dossier":
        return _format_dossier(result)
    if tool_name == "interview_prep":
        return _format_interview_prep(result)
    return []


# ------------------------------------------------------------------
# Job matches: compact table
# ------------------------------------------------------------------


def _format_job_matches(result: dict) -> list[dict]:
    matches = result.get("matches") or result.get("jobs") or result.get("results", [])
    if not matches:
        return []

    blocks: list[dict] = [_divider()]
    lines: list[str] = []

    for i, match in enumerate(matches[:10], 1):
        title = match.get("title", "Unknown")
        company = match.get("company", "")
        score = match.get("match_score") or match.get("score", 0)
        location = match.get("location", "")

        line = f"*{i}. {title}*"
        if company:
            line += f" at {company}"
        if score:
            line += f" ({score}% match)"
        if location:
            line += f"\n    {location}"
        lines.append(line)

    blocks.append(_section("\n".join(lines)))
    return blocks


def _format_discovery(result: dict) -> list[dict]:
    jobs = result.get("jobs") or result.get("matches") or []
    query = result.get("query") or "your search"
    status = result.get("status", "unknown")
    count = result.get("count") or len(jobs)

    if not jobs and status == "no_results":
        return [
            _divider(),
            _section(
                f"*Research search found no new jobs for* `{query}`.\n"
                "Try broadening the title, location, or industry and Foxhound will keep looking."
            ),
            _action_row(
                _button("/jobs", "Open Jobs", emphasis=True),
                _button(_research_href("discovery", query=query), "Open Research"),
            ),
        ]

    if not jobs:
        return []

    lines = [f"*Foxhound found {count} jobs for* `{query}`"]
    for i, job in enumerate(jobs[:5], 1):
        title = job.get("title", "Unknown")
        company = job.get("company", "")
        location = job.get("location", "")
        line = f"{i}. *{title}*"
        if company:
            line += f" at {company}"
        if location:
            line += f"\n    {location}"
        lines.append(line)

    blocks: list[dict] = [
        _divider(),
        _section("\n".join(lines)),
        _context("Reply with a company or role and Foxhound can refine the search."),
        _action_row(
            _button("/jobs", "Open Jobs", emphasis=True),
            _button(_research_href("discovery", query=query), "Open Research"),
        ),
    ]
    return blocks


# ------------------------------------------------------------------
# Application status: card
# ------------------------------------------------------------------


def _format_application_status(result: dict) -> list[dict]:
    status = result.get("status", "unknown")
    company = result.get("company") or result.get("company_name", "")
    title = result.get("title") or result.get("job_title", "")
    fields_filled = result.get("fields_filled", 0)
    fields_total = result.get("fields_total", 0)

    emoji = {"submitted": "white_check_mark", "in_progress": "hourglass_flowing_sand",
             "failed": "x", "questions_pending": "question"}.get(status, "clipboard")

    header = f":{emoji}: *Application: {title}*"
    if company:
        header += f" at {company}"

    blocks: list[dict] = [_divider(), _section(header)]

    details: list[str] = [f"*Status:* {status.replace('_', ' ').title()}"]
    if fields_total:
        details.append(f"*Fields:* {fields_filled}/{fields_total} filled")

    blocks.append(_section("\n".join(details)))

    # If there are questions, format them
    questions = result.get("questions") or result.get("pending_questions", [])
    if questions:
        blocks.extend(_format_questions_list(questions))

    # Screenshot URL
    screenshot_url = result.get("screenshot_url") or result.get("screenshot", "")
    if screenshot_url:
        blocks.append(_image(screenshot_url, "Application screenshot"))

    return blocks


def _format_dossier(result: dict) -> list[dict]:
    status = result.get("status", "unknown")
    dossier_id = result.get("dossier_id")
    message = result.get("message") or "Foxhound is building your report."

    label = "Foxhound Brief Ready" if status == "ready" else "Foxhound Brief Building"
    blocks: list[dict] = [
        _divider(),
        _section(f"*{label}*\n{message}"),
    ]

    if dossier_id:
        blocks.append(
            _action_row(
                _button(f"/dossier/{dossier_id}", "View Report", emphasis=True),
                _button(_research_href("brief", application_id=result.get("application_id")), "Open Research"),
            )
        )
    return blocks


def _format_interview_prep(result: dict) -> list[dict]:
    company = result.get("company", "Unknown company")
    role = result.get("role", "Interview prep")
    status = result.get("status", "unknown")
    sources = result.get("sources_found") or []
    message = result.get("message") or "Foxhound found interview signals."

    lines = [f"*{company}* — {role}", message]
    if sources:
        lines.append("")
        lines.append("*Sources found:* " + ", ".join(str(src) for src in sources[:5]))

    blocks: list[dict] = [
        _divider(),
        _section("\n".join(lines)),
        _context(
            "Reply with a different company or role if you want Foxhound to run more Research."
        ),
        _action_row(
            _button(_research_href("interview", company=company, role=role), "Open Research", emphasis=True),
            _button("/applications", "Open Applications"),
        ),
    ]

    if status == "no_data":
        blocks.insert(1, _section("Foxhound couldn't find much interview data, but it can keep searching if you want to broaden the target."))
    return blocks


# ------------------------------------------------------------------
# Questions: numbered list with reply instructions
# ------------------------------------------------------------------


def _format_questions(result: dict) -> list[dict]:
    questions = result.get("questions") or result.get("pending_questions", [])
    return _format_questions_list(questions)


def _format_questions_list(questions: list) -> list[dict]:
    if not questions:
        return []

    blocks: list[dict] = [_divider()]
    lines: list[str] = ["*I need your input on these questions:*\n"]

    for i, q in enumerate(questions, 1):
        if isinstance(q, dict):
            text = q.get("question") or q.get("text", str(q))
        else:
            text = str(q)
        lines.append(f"{i}. {text}")

    lines.append("\n*Reply with your answers:*")
    for i in range(1, len(questions) + 1):
        lines.append(f"{i}. [your answer]")

    blocks.append(_section("\n".join(lines)))
    return blocks


# ------------------------------------------------------------------
# Applications list
# ------------------------------------------------------------------


def _format_applications_list(result: dict) -> list[dict]:
    apps = result.get("applications") or result.get("results", [])
    if not apps:
        return []

    blocks: list[dict] = [_divider()]
    lines: list[str] = []

    for i, app in enumerate(apps[:10], 1):
        title = app.get("title") or app.get("job_title", "Unknown")
        company = app.get("company") or app.get("company_name", "")
        status = app.get("status", "unknown")
        emoji = {"submitted": "white_check_mark", "in_progress": "hourglass_flowing_sand",
                 "failed": "x"}.get(status, "clipboard")

        line = f":{emoji}: *{i}. {title}*"
        if company:
            line += f" at {company}"
        line += f" -- {status.replace('_', ' ').title()}"
        lines.append(line)

    blocks.append(_section("\n".join(lines)))
    return blocks


# ------------------------------------------------------------------
# Block Kit helpers
# ------------------------------------------------------------------


def _section(text: str) -> dict:
    """Markdown section block."""
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": text},
    }


def _divider() -> dict:
    return {"type": "divider"}


def _image(url: str, alt_text: str) -> dict:
    return {
        "type": "image",
        "image_url": url,
        "alt_text": alt_text,
    }


def _context(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _button(href: str, label: str, *, emphasis: bool = False) -> dict:
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": label},
        "url": href,
        **({"style": "primary"} if emphasis else {}),
    }


def _action_row(*elements: dict) -> dict:
    return {"type": "actions", "elements": list(elements)}


def _research_href(
    tab: str,
    *,
    company: str | None = None,
    role: str | None = None,
    application_id: str | None = None,
    query: str | None = None,
) -> str:
    params: list[str] = [f"tab={quote_plus(tab)}"]
    if company:
        params.append(f"company={quote_plus(company)}")
    if role:
        params.append(f"role={quote_plus(role)}")
    if application_id:
        params.append(f"applicationId={quote_plus(application_id)}")
    if query:
        params.append(f"query={quote_plus(query)}")
    return f"/intelligence?{'&'.join(params)}"
