"""Stack Overflow adapter via the public API.

Free, no auth required (300 requests/day without key, 10K with key).
https://api.stackexchange.com/docs
"""

import logging
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)

SO_API = "https://api.stackexchange.com/2.3"


async def fetch_so_questions(
    topic: str,
    limit: int = 20,
    min_score: int = 3,
    tagged: str | None = None,
) -> list[dict]:
    """Search SO questions by topic, sorted by votes."""
    # Use the full query as the search term, not just intitle
    # intitle alone matches generic popular questions
    params = {
        "order": "desc",
        "sort": "relevance",
        "q": topic,
        "site": "stackoverflow",
        "pagesize": min(limit, 30),
        "filter": "withbody",
    }
    if tagged:
        params["tagged"] = tagged

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{SO_API}/search/advanced", params=params)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            quota = data.get("quota_remaining", "?")
            logger.info("SO search: %d results, %s quota remaining", len(items), quota)
    except Exception as e:
        logger.warning("SO search failed for '%s': %s", topic, e)
        return []

    results = []
    for item in items:
        if item.get("score", 0) < min_score:
            continue
        parsed = _parse_question(item)
        if parsed:
            results.append(parsed)

    return results[:limit]


async def fetch_so_signals(topic: str, limit: int = 20) -> list[dict]:
    """Fetch questions + answers for a topic."""
    questions = await fetch_so_questions(topic, limit=limit)

    # For top questions, also fetch the accepted/top answer
    if questions:
        top_ids = [q["source_id"].replace("so_", "") for q in questions[:5]]
        answers = await _fetch_answers(top_ids)
        # Merge answers into questions
        answer_map = {}
        for a in answers:
            qid = a.get("question_id", "")
            if qid not in answer_map or a.get("score", 0) > answer_map[qid].get("score", 0):
                answer_map[qid] = a
        for q in questions:
            qid = q["source_id"].replace("so_", "")
            if qid in answer_map:
                ans = answer_map[qid]
                q["top_answer"] = _strip_html(ans.get("body", ""))[:500]
                q["top_answer_score"] = ans.get("score", 0)

    return questions


async def _fetch_answers(question_ids: list[str]) -> list[dict]:
    """Fetch answers for specific questions."""
    if not question_ids:
        return []
    ids_str = ";".join(question_ids[:5])
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{SO_API}/questions/{ids_str}/answers",
                params={
                    "order": "desc",
                    "sort": "votes",
                    "site": "stackoverflow",
                    "pagesize": 10,
                    "filter": "withbody",
                },
            )
            resp.raise_for_status()
            return resp.json().get("items", [])
    except Exception as e:
        logger.debug("SO answer fetch failed: %s", e)
        return []


def _parse_question(item: dict) -> dict | None:
    if not item.get("title"):
        return None

    body = _strip_html(item.get("body", ""))
    created = None
    if item.get("creation_date"):
        created = datetime.fromtimestamp(item["creation_date"], tz=UTC).isoformat()

    return {
        "source_id": f"so_{item.get('question_id', '')}",
        "url": item.get("link", ""),
        "title": item.get("title", ""),
        "text": f"{item.get('title', '')}\n\n{body[:500]}",
        "author": item.get("owner", {}).get("display_name", ""),
        "created_utc": item.get("creation_date", 0),
        "created_at": created,
        "score": item.get("score", 0),
        "num_comments": item.get("answer_count", 0),
        "view_count": item.get("view_count", 0),
        "tags": item.get("tags", []),
        "is_answered": item.get("is_answered", False),
        "source": "stackoverflow",
        "source_type": "so_question",
        "source_platform": "stackoverflow",
    }


def _strip_html(text: str) -> str:
    import re

    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
