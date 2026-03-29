"""Unified parser for focused TinyFish extraction results.

All focused prompts return the same base schema:
  {items: [{text, signal_type, tool_mentioned, evidence_quote}]}

URL discovery returns:
  {urls: [{url, title, comment_count}]}

This parser handles both and normalizes the output."""

import hashlib
import json
import logging

logger = logging.getLogger(__name__)


def _unwrap_result(result: dict | None) -> dict:
    """Unwrap nested result structures TinyFish sometimes returns.

    Handles: {"result": "```json\\n{...}\\n```"} and {"result": {...}} patterns."""
    if not result or not isinstance(result, dict):
        return {}

    # if there's a "result" key containing a string, parse it
    inner = result.get("result")
    if isinstance(inner, str):
        cleaned = inner.strip()
        # strip markdown code blocks
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]  # remove first line
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    if isinstance(inner, dict):
        return inner

    return result


def parse_signal_result(result: dict | None, url: str) -> list[dict]:
    """Parse a signal extraction result (pain, workaround, tool_complaint, request, workflow).

    Returns list of normalized signal dicts."""
    unwrapped = _unwrap_result(result)
    if not unwrapped:
        return []

    # try multiple keys for robustness
    items = (
        unwrapped.get("items")
        or unwrapped.get("results")
        or unwrapped.get("signals")
        or unwrapped.get("data")
        or []
    )
    if not isinstance(items, list):
        return []

    parsed = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or item.get("description") or item.get("content") or "").strip()
        if not text:
            continue

        signal_type = (item.get("signal_type") or item.get("type") or "pain").strip().lower()
        tool = item.get("tool_mentioned") or item.get("tool") or item.get("product") or None
        if tool and str(tool).lower() in ("null", "none", "n/a", ""):
            tool = None
        quote = item.get("evidence_quote") or item.get("quote") or item.get("excerpt") or None
        if quote and str(quote).lower() in ("null", "none", ""):
            quote = None

        source_id = hashlib.md5(f"{url}:{text[:100]}".encode()).hexdigest()[:12]

        parsed.append({
            "source_id": source_id,
            "url": url,
            "text": text,
            "signal_type": signal_type,
            "tool_mentioned": str(tool).strip() if tool else None,
            "evidence_quote": str(quote).strip() if quote else None,
        })

    logger.info("Parsed %d signals from %s", len(parsed), url)
    return parsed


def parse_url_discovery_result(result: dict | None) -> list[dict]:
    """Parse a URL discovery result.

    Returns list of {url, title, comment_count} dicts."""
    if not result or not isinstance(result, dict):
        return []

    urls = (
        result.get("urls")
        or result.get("items")
        or result.get("results")
        or result.get("threads")
        or result.get("links")
        or []
    )
    if not isinstance(urls, list):
        return []

    parsed = []
    for item in urls:
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or item.get("link") or item.get("href") or "").strip()
        if not url or not url.startswith("http"):
            continue

        parsed.append({
            "url": url,
            "title": (item.get("title") or item.get("name") or "").strip(),
            "comment_count": item.get("comment_count") or item.get("comments") or item.get("num_comments"),
        })

    logger.info("Discovered %d URLs", len(parsed))
    return parsed


def signals_to_raw_documents(signals: list[dict], topic: str, source_type: str) -> list[dict]:
    """Convert parsed signals into raw document format for the pipeline.

    This bridges the new focused extraction output into the existing
    pipeline's expected document format."""
    docs = []
    for signal in signals:
        doc = {
            "id": signal["source_id"],
            "source": source_type,
            "url": signal["url"],
            "title": signal.get("tool_mentioned") or topic,
            "text": signal["text"],
            "evidence_quote": signal.get("evidence_quote"),
            "signal_type": signal["signal_type"],
            "tool_mentioned": signal.get("tool_mentioned"),
            "topic": topic,
        }
        docs.append(doc)
    return docs
