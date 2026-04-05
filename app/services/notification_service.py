import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import settings


def default_notification_status(config: dict | None = None) -> dict:
    notify = config or {}
    return {
        "discord": _blank_channel_state(enabled=bool(notify.get("discord"))),
        "slack": _blank_channel_state(enabled=bool(notify.get("slack"))),
        "sms": _blank_channel_state(enabled=bool(notify.get("sms"))),
    }


def is_retryable_notification_failure(state: dict | None) -> bool:
    if not state or state.get("status") != "failed":
        return False
    http_status = state.get("http_status")
    if http_status in {408, 409, 425, 429}:
        return True
    if isinstance(http_status, int) and 500 <= http_status <= 599:
        return True
    message = (state.get("message") or "").lower()
    retryable_markers = [
        "timed out",
        "timeout",
        "temporary failure",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "connection refused",
        "rate limit",
        "too many requests",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
    ]
    return any(marker in message for marker in retryable_markers)


def _channel_audience(destinations: dict, channel: str) -> str:
    audience = (destinations or {}).get(f"{channel}_audience_type", "human")
    if audience not in {"human", "agent", "hybrid"}:
        return "human"
    return audience


def _channel_event_types(destinations: dict, channel: str) -> list[str]:
    values = (destinations or {}).get(f"{channel}_event_types", [])
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def _event_allowed(destinations: dict, channel: str, event_type: str) -> bool:
    allowed = _channel_event_types(destinations, channel)
    if not allowed:
        return True
    return event_type in allowed


async def deliver_run_notifications(
    run_id: str,
    query: str,
    status: str,
    notify_config: dict | None,
    destination_config: dict | None,
    output: dict | None = None,
) -> dict:
    return await deliver_event_notifications(
        run_id=run_id,
        query=query,
        notify_config=notify_config,
        destination_config=destination_config,
        event_type="run.completed" if status in {"completed", "partial_success"} else "run.failed",
        payload={"status": status},
        output=output,
    )


async def deliver_event_notifications(
    run_id: str,
    query: str,
    notify_config: dict | None,
    destination_config: dict | None,
    event_type: str,
    payload: dict | None = None,
    output: dict | None = None,
) -> dict:
    notify = notify_config or {}
    destinations = destination_config or {}
    state = default_notification_status(notify)
    base_payload = _build_notification_payload(run_id, query, event_type, payload or {}, output)

    if notify.get("discord"):
        webhook_url = destinations.get("discord_webhook_url") or settings.discord_webhook_url
        if not _event_allowed(destinations, "discord", event_type):
            state["discord"] = _skipped_state(f"Destination not subscribed to {event_type}")
        elif webhook_url:
            state["discord"] = await _send_discord(
                webhook_url,
                _render_notification_payload(base_payload, _channel_audience(destinations, "discord")),
            )
        else:
            state["discord"] = _skipped_state("FOXHOUND_DISCORD_WEBHOOK_URL not configured")

    if notify.get("slack"):
        webhook_url = destinations.get("slack_webhook_url") or settings.slack_webhook_url
        if not _event_allowed(destinations, "slack", event_type):
            state["slack"] = _skipped_state(f"Destination not subscribed to {event_type}")
        elif webhook_url:
            state["slack"] = await _send_slack(
                webhook_url,
                _render_notification_payload(base_payload, _channel_audience(destinations, "slack")),
            )
        else:
            state["slack"] = _skipped_state("FOXHOUND_SLACK_WEBHOOK_URL not configured")

    if notify.get("sms"):
        webhook_url = settings.sms_webhook_url
        if not _event_allowed(destinations, "sms", event_type):
            state["sms"] = _skipped_state(f"Destination not subscribed to {event_type}")
        elif webhook_url:
            phone_number = destinations.get("sms_phone_number", "")
            if phone_number:
                state["sms"] = await _send_sms(
                    webhook_url,
                    _render_notification_payload(base_payload, _channel_audience(destinations, "sms")),
                    phone_number,
                )
            else:
                state["sms"] = _skipped_state("No SMS phone number configured")
        else:
            state["sms"] = _skipped_state("FOXHOUND_SMS_WEBHOOK_URL not configured")

    return state


def _build_notification_payload(
    run_id: str,
    query: str,
    event_type: str,
    payload: dict,
    output: dict | None,
) -> dict:
    opportunities = (output or {}).get("results") or (output or {}).get("opportunities", [])
    top_opportunities = [
        {
            "title": item.get("title", ""),
            "score": item.get("opportunity_score", 0.0),
            "workflow": item.get("workflow", ""),
            "breakpoint": item.get("breakpoint"),
            "wedge": item.get("build_wedge") or item.get("wedge", ""),
            "summary": item.get("summary", ""),
            "one_liner": item.get("one_liner", ""),
            "effort_tier": item.get("effort_tier", ""),
            "form_factor": item.get("form_factor", ""),
            "signal_strength": item.get("signal_strength", ""),
            "mvp_plan": item.get("mvp_plan", [])[:3],
            "evidence": item.get("evidence", [])[:2],
        }
        for item in opportunities[:3]
        if item.get("title")
    ]
    marketplace_ids = ((output or {}).get("debug", {}) or {}).get("marketplace_ids", [])
    for index, item in enumerate(top_opportunities):
        opportunity_id = marketplace_ids[index] if index < len(marketplace_ids) else None
        if opportunity_id:
            item["opportunity_id"] = opportunity_id
            item["artifact_id"] = f"artifact_{opportunity_id}"
            item["opportunity_url"] = (
                f"{settings.APP_BASE_URL.rstrip('/')}/v1/marketplace/opportunities/{opportunity_id}"
            )
            item["artifact_url"] = (
                f"{settings.APP_BASE_URL.rstrip('/')}/v1/marketplace/opportunities/{opportunity_id}/artifact"
            )
            item["build_plan_url"] = (
                f"{settings.APP_BASE_URL.rstrip('/')}/v1/marketplace/opportunities/{opportunity_id}/build-plans"
            )
    top_titles = [item["title"] for item in top_opportunities]
    message = _build_message(event_type, query, payload, top_titles)
    return {
        "run_id": run_id,
        "query": query,
        "event_type": event_type,
        "payload": payload,
        "status": payload.get("status"),
        "opportunities_found": len(opportunities),
        "top_opportunities": top_titles,
        "top_opportunity_items": top_opportunities,
        "top_build_plan_ids": [
            item.get("plan_id") for item in ((output or {}).get("build_plans", [])[:3]) if item.get("plan_id")
        ],
        "marketplace_ids": marketplace_ids,
        "run_url": f"{settings.APP_BASE_URL.rstrip('/')}/v1/runs/{run_id}",
        "marketplace_url": f"{settings.APP_BASE_URL.rstrip('/')}/",
        "message": message,
    }


def _render_notification_payload(payload: dict, audience_type: str) -> dict:
    rendered = dict(payload)
    rendered["audience_type"] = audience_type
    if audience_type in {"agent", "hybrid"}:
        rendered["message"] = _build_agent_message(payload)
    else:
        rendered["message"] = _build_human_message(payload)
    return rendered


def _truncate(text: str | None, limit: int = 160) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _top_human_lines(payload: dict) -> list[str]:
    lines = []
    for index, item in enumerate(payload.get("top_opportunity_items", [])[:3], start=1):
        title = item.get("title", "Untitled")
        score = item.get("score", 0.0)
        effort = item.get("effort_tier", "")
        one_liner = _truncate(item.get("one_liner", ""), 140)
        wedge = _truncate(item.get("wedge", ""), 110)
        breakpoint = _truncate(item.get("breakpoint", ""), 110)
        signal = item.get("signal_strength", "")
        summary = _truncate(item.get("summary", ""), 140)
        tier_badge = f" [{effort}]" if effort else ""
        lines.append(f"{index}. *{title}*{tier_badge} ({score:.2f})")
        if one_liner:
            lines.append(f"   {one_liner}")
        if breakpoint:
            lines.append(f"   Broken step: {breakpoint}")
        if wedge:
            lines.append(f"   Wedge: {wedge}")
        elif summary:
            lines.append(f"   Why it matters: {summary}")
        if signal:
            lines.append(f"   {signal}")
    return lines


async def _send_discord(webhook_url: str, payload: dict) -> dict:
    body = {"content": payload["message"]}
    if payload.get("audience_type") in {"agent", "hybrid"}:
        lines = [
            f"run_id: {payload['run_id']}",
            f"event: {payload['event_type']}",
            f"run_url: {payload['run_url']}",
        ]
        if payload["top_opportunity_items"]:
            for item in payload["top_opportunity_items"]:
                lines.append(
                    "opportunity: "
                    f"{item.get('title', '')} | "
                    f"opportunity_id={item.get('opportunity_id', 'pending')} | "
                    f"artifact_id={item.get('artifact_id', 'pending')}"
                )
                if item.get("opportunity_url"):
                    lines.append(f"opportunity_url: {item['opportunity_url']}")
                if item.get("artifact_url"):
                    lines.append(f"artifact_url: {item['artifact_url']}")
                if item.get("build_plan_url"):
                    lines.append(f"build_plan_url: {item['build_plan_url']}")
        if payload["top_build_plan_ids"]:
            lines.append(f"build_plan_ids: {', '.join(payload['top_build_plan_ids'])}")
        body["embeds"] = [
            {
                "title": f"Foxhound result: {payload['query']}",
                "description": "\n".join(lines),
            }
        ]
        return await _post_webhook(webhook_url, body)
    if payload["event_type"] == "run.completed":
        description_lines = [
            f"Opportunities found: {payload['opportunities_found']}",
            f"Run: {payload['run_url']}",
        ]
        if payload["top_opportunity_items"]:
            description_lines.append("")
            description_lines.extend(_top_human_lines(payload))
        body["embeds"] = [
            {
                "title": f"Foxhound completed: {payload['query']}",
                "description": "\n".join(description_lines),
            }
        ]
    elif payload["event_type"] == "run.milestone":
        body["embeds"] = [
            {
                "title": payload.get("message") or "Foxhound milestone",
                "description": f"Progress: {payload.get('status') or ''}\nRun: {payload['run_url']}",
            }
        ]
    elif payload["event_type"] == "opportunity.created":
        event = payload.get("payload", {})
        evidence = event.get("evidence", []) or []
        evidence_line = ""
        if evidence:
            first = evidence[0]
            quote = first.get("quote") or first.get("text", "")
            evidence_line = f"\nEvidence: {first.get('type', 'signal')}: {_truncate(quote, 120)}"
        body["embeds"] = [
            {
                "title": event.get("title", "Foxhound opportunity"),
                "description": "\n".join(
                    line
                    for line in [
                        f"_{event.get('one_liner', '')}_" if event.get("one_liner") else "",
                        f"Effort: {event.get('effort_tier', '')}" if event.get("effort_tier") else "",
                        f"Workflow: {event.get('workflow', '')}",
                        f"Broken step: {_truncate(event.get('breakpoint', ''), 130)}"
                        if event.get("breakpoint")
                        else "",
                        f"Wedge: {_truncate(event.get('wedge', ''), 130)}" if event.get("wedge") else "",
                        f"Score: {event.get('score', 0.0):.2f}",
                        evidence_line.strip(),
                    ]
                    if line
                ),
            }
        ]
    elif payload["event_type"] == "build_plan.created":
        event = payload.get("payload", {})
        mvp_scope = event.get("mvp_scope", [])[:3]
        body["embeds"] = [
            {
                "title": f"Build plan ready: {event.get('opportunity_title', 'Untitled opportunity')}",
                "description": "\n".join(
                    [f"Wedge: {_truncate(event.get('wedge', ''), 130)}"]
                    + [f"MVP {index + 1}: {_truncate(item, 120)}" for index, item in enumerate(mvp_scope)]
                ),
            }
        ]
    return await _post_webhook(webhook_url, body)


async def _send_slack(webhook_url: str, payload: dict) -> dict:
    body = {"text": payload["message"]}
    if payload.get("audience_type") in {"agent", "hybrid"}:
        lines = [
            f"*run_id:* `{payload['run_id']}`",
            f"*event:* `{payload['event_type']}`",
            f"*run:* <{payload['run_url']}|Open run resource>",
        ]
        if payload["top_opportunity_items"]:
            for item in payload["top_opportunity_items"]:
                lines.append(
                    f"*opportunity:* {item.get('title', '')} | "
                    f"`opportunity_id={item.get('opportunity_id', 'pending')}` | "
                    f"`artifact_id={item.get('artifact_id', 'pending')}`"
                )
                if item.get("opportunity_url"):
                    lines.append(f"*opportunity_url:* {item['opportunity_url']}")
                if item.get("artifact_url"):
                    lines.append(f"*artifact_url:* {item['artifact_url']}")
                if item.get("build_plan_url"):
                    lines.append(f"*build_plan_url:* {item['build_plan_url']}")
        if payload["top_build_plan_ids"]:
            lines.append(f"*build_plan_ids:* {', '.join(payload['top_build_plan_ids'])}")
        body["blocks"] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": payload["message"]}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
        ]
        return await _post_webhook(webhook_url, body)
    if payload["event_type"] == "run.started":
        body["blocks"] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": payload["message"]}},
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "View run"}, "url": payload["run_url"]}
                ],
            },
        ]
    elif payload["event_type"] == "run.completed":
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Foxhound completed:* {payload['query']}"}},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Opportunities found:* {payload['opportunities_found']}"},
            },
        ]
        if payload["top_opportunity_items"]:
            lines = "\n".join(_top_human_lines(payload))
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": lines}})
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "View run"}, "url": payload["run_url"]}
                ],
            }
        )
        body["blocks"] = blocks
    elif payload["event_type"] == "run.milestone":
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": payload["message"]}},
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "View run"}, "url": payload["run_url"]}
                ],
            },
        ]
        body["blocks"] = blocks
    elif payload["event_type"] == "opportunity.created":
        event = payload.get("payload", {})
        evidence = event.get("evidence", []) or []
        evidence_text = ""
        if evidence:
            first = evidence[0]
            quote = first.get("quote") or first.get("text", "")
            evidence_text = f"*Evidence:* {first.get('type', 'signal')}: {_truncate(quote, 120)}"
        details = [
            f"_{event.get('one_liner', '')}_" if event.get("one_liner") else "",
            f"*Effort:* {event.get('effort_tier', '')}" if event.get("effort_tier") else "",
            f"*Workflow:* {event.get('workflow', '')}",
            f"*Broken step:* {_truncate(event.get('breakpoint', ''), 140)}" if event.get("breakpoint") else "",
            f"*Wedge:* {_truncate(event.get('wedge', ''), 140)}" if event.get("wedge") else "",
            f"*Score:* {event.get('score', 0.0):.2f}",
            evidence_text,
        ]
        body["blocks"] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": payload["message"]}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(line for line in details if line)}},
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "View run"}, "url": payload["run_url"]}
                ],
            },
        ]
    elif payload["event_type"] == "build_plan.created":
        event = payload.get("payload", {})
        mvp_scope = event.get("mvp_scope", [])[:3]
        bullets = [f"• {_truncate(item, 120)}" for item in mvp_scope]
        body["blocks"] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": payload["message"]}},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "\n".join([f"*Wedge:* {_truncate(event.get('wedge', ''), 140)}"] + bullets),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "View run"}, "url": payload["run_url"]}
                ],
            },
        ]
    return await _post_webhook(webhook_url, body)


async def _send_sms(webhook_url: str, payload: dict, phone_number: str) -> dict:
    return await _post_webhook(
        webhook_url,
        {"text": payload["message"], "run_id": payload["run_id"], "query": payload["query"], "to": phone_number},
    )


async def _post_webhook(webhook_url: str, body: dict) -> dict:
    def _send() -> dict:
        request = Request(
            webhook_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:  # noqa: S310
                return {
                    "enabled": True,
                    "status": "sent",
                    "http_status": getattr(response, "status", 200),
                    "message": "Delivered",
                }
        except HTTPError as exc:
            return {
                "enabled": True,
                "status": "failed",
                "http_status": getattr(exc, "code", None),
                "message": str(exc),
            }
        except URLError as exc:
            return {
                "enabled": True,
                "status": "failed",
                "message": str(exc),
            }
        except Exception as exc:  # pragma: no cover - defensive
            return {
                "enabled": True,
                "status": "failed",
                "message": str(exc),
            }

    return await asyncio.to_thread(_send)


async def send_slack_blocks(
    webhook_url: str,
    blocks: list[dict],
    fallback_text: str = "Foxhound notification",
) -> dict:
    """Send a Slack Block Kit message to a webhook URL.

    Slack requires a top-level ``text`` field as a fallback for clients
    that cannot render blocks (e.g. push notifications).  The ``blocks``
    list carries the rich Block Kit payload.

    Args:
        webhook_url: Slack incoming-webhook URL.
        blocks: List of Block Kit block dicts.
        fallback_text: Plain-text summary shown in push notifications.

    Returns:
        Delivery status dict (same shape as ``_post_webhook``).
    """
    body = {"text": fallback_text, "blocks": blocks}
    return await _post_webhook(webhook_url, body)


def _blank_channel_state(enabled: bool) -> dict:
    return {
        "enabled": enabled,
        "status": "pending" if enabled else "disabled",
        "message": None,
    }


def _skipped_state(message: str) -> dict:
    return {
        "enabled": True,
        "status": "skipped",
        "message": message,
    }


def _build_message(event_type: str, query: str, payload: dict, top_titles: list[str]) -> str:
    return _build_human_message(
        {
            "event_type": event_type,
            "query": query,
            "status": payload.get("status"),
            "top_opportunities": top_titles,
            "payload": payload,
        }
    )


def _build_human_message(payload: dict) -> str:
    event_type = payload.get("event_type")
    query = payload.get("query", "")
    payload.get("status")
    top_titles = payload.get("top_opportunities", [])
    event_payload = payload.get("payload", payload)
    if event_type == "run.started":
        return (
            f"Foxhound is working on your request for “{query}.”\n\n"
            "We’re gathering and ranking the strongest opportunities now."
        )
    if event_type == "run.milestone":
        title = event_payload.get("title") or event_payload.get("step") or "Milestone"
        progress = event_payload.get("progress_percent")
        if progress is not None:
            return f"Foxhound update for “{query}”:\n{title} ({progress}% complete)"
        return f"Foxhound update for “{query}”:\n{title}"
    if event_type == "opportunity.created":
        return f"Foxhound found an early opportunity for “{query}”:\n{event_payload.get('title', 'Untitled')}"
    if event_type == "build_plan.created":
        return f"Foxhound generated a build plan for “{query}”:\n{event_payload.get('opportunity_title', 'Untitled opportunity')}"
    if event_type == "run.completed":
        return (
            f"Foxhound finished your request for “{query}.”\n\n"
            f"Top opportunities: {', '.join(top_titles) if top_titles else 'none yet'}."
        )
    if event_type == "run.failed":
        return f"Foxhound hit a problem while processing “{query}.”"
    return f"Foxhound update for “{query}”:\n{event_type}"


def _build_agent_message(payload: dict) -> str:
    titles = payload.get("top_opportunities", [])
    top_line = ", ".join(titles[:3]) if titles else "none"
    return (
        f"Foxhound update for {payload.get('query', '')}. "
        f"event={payload.get('event_type')} "
        f"run_id={payload.get('run_id')} "
        f"top_opportunities={top_line}"
    )
