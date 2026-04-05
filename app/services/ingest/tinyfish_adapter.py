import asyncio
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from hashlib import md5

from tinyfish import AsyncTinyFish

from app.core.config import settings
from app.services.ingest.extraction_cache import cache_extraction, get_cached_extraction
from app.services.ingest.tinyfish_errors import TinyFishErrorType, classify_error, is_retryable

logger = logging.getLogger(__name__)


def _get_client() -> AsyncTinyFish:
    api_key = settings.tinyfish_api_key
    if not api_key:
        raise RuntimeError("TINYFISH_API_KEY not set")
    kwargs: dict = {"api_key": api_key}
    proxy_url = settings.tinyfish_proxy_url
    if proxy_url:
        kwargs["proxy_url"] = proxy_url
        logger.debug("TinyFish using proxy: %s", proxy_url)
    return AsyncTinyFish(**kwargs)


def _hash_id(text: str, prefix: str = "tf") -> str:
    return f"{prefix}_{md5(text.encode()).hexdigest()[:12]}"


async def _save_run(run_record: dict) -> None:
    """Persist a TinyFishRun record to the database."""
    try:
        from app.db.models.tinyfish_run import TinyFishRun
        from app.db.session import async_session

        async with async_session() as session:
            session.add(TinyFishRun(**run_record))
            await session.commit()
    except Exception as e:
        logger.debug("Failed to save TinyFish run record: %s", e)


def _summarize_result_payload(result: dict | None) -> dict:
    if not isinstance(result, dict):
        return {}

    summary: dict[str, object] = {"keys": sorted(result.keys())[:20]}
    for key in (
        "signals",
        "items",
        "results",
        "workflows",
        "gaps",
        "comparisons",
        "questions",
        "posts",
        "discovered_pages",
    ):
        value = result.get(key)
        if isinstance(value, list):
            summary[f"{key}_count"] = len(value)
    for key in ("source_url", "search_query"):
        value = result.get(key)
        if isinstance(value, str) and value:
            summary[key] = value
    return summary


# =============================================================================
# PROMPT A — Category Discovery
# =============================================================================

# =============================================================================
# V2 PROMPTS — Efficient extraction with zero unnecessary navigation
# =============================================================================

DISCOVER_AND_EXTRACT_GOAL = """Search for "{search_query}" and extract pain signals from the top results.

NAVIGATION RULES (MANDATORY — read these first):
- Start at this search results page
- Click into up to {max_pages} result links from the search page
- On each result page: read ONLY what is visible. Scroll down once if needed.
- Do NOT click into sub-pages, linked issues, "load more", comment expansions, related threads, or any internal navigation
- Do NOT visit more than {max_pages} result pages total
- If a page is blocked, paywalled, or requires login: skip it immediately, set blocked=true

ON EACH RESULT PAGE, extract up to 5 of the strongest signals where someone describes:
- A specific frustration or complaint (signal_type: "pain")
- A manual workaround or hack they use (signal_type: "workaround")
- A feature they wish existed (signal_type: "request")
- A failure with a specific tool (signal_type: "incumbent_failure")

For every signal, copy an exact quote from the page as evidence.

Return JSON:
{{
  "search_query": "{search_query}",
  "pages": [
    {{
      "url": "string",
      "title": "string",
      "page_type": "reddit|forum|github|blog|review|comparison|docs|other",
      "blocked": false,
      "signals": [
        {{
          "signal_type": "pain|workaround|request|incumbent_failure",
          "text": "one sentence summarizing the signal",
          "tool_mentioned": "specific tool name or null",
          "evidence_quote": "exact quote from the page, max 200 chars"
        }}
      ]
    }}
  ]
}}

QUALITY OVER QUANTITY: A single specific signal with an exact quote is worth more than 5 vague ones.
Skip generic content, marketing copy, and documentation without pain signals.
If you have extracted 8+ signals with exact quotes, you may stop visiting additional pages and return early.
If blocked by CAPTCHA or login wall, return partial results immediately.
Return ONLY valid JSON."""


SINGLE_PAGE_FORUM_GOAL = """Read this forum/discussion page and extract pain signals related to "{topic}".

NAVIGATION RULES (MANDATORY — read these first):
- Read ONLY this URL: {url}
- Do NOT click "load more comments", "continue thread", related posts, or any links
- Do NOT navigate to linked issues, repos, articles, or other threads
- Read only the original post and the comments already rendered on the page
- If blocked or login-required: return {{"blocked": true, "signals": []}} immediately

Read the original post and visible comments. Extract up to 5 of the strongest signals.

Prioritize:
- Complaints with specific tool names ("X is broken because...")
- Workarounds people describe ("I ended up writing a script to...")
- Feature requests with context ("I wish X could...")
- High-engagement comments (many upvotes/replies visible)

Return JSON:
{{
  "url": "{url}",
  "blocked": false,
  "page_title": "string",
  "signals": [
    {{
      "signal_type": "pain|workaround|request|incumbent_failure",
      "text": "one sentence summarizing the signal",
      "tool_mentioned": "specific tool name or null",
      "evidence_quote": "exact quote, max 200 chars",
      "author": "username or null"
    }}
  ]
}}

Return ONLY valid JSON."""


SINGLE_PAGE_GITHUB_GOAL = """Read this GitHub page and extract intelligence related to "{topic}".

NAVIGATION RULES (MANDATORY — read these first):
- Read ONLY this URL: {url}
- Do NOT click linked issues, PRs, other repos, user profiles, or any navigation
- Do NOT visit the issues tab, releases, or discussions from a repo page
- Read only what is on THIS page
- If blocked: return {{"blocked": true, "signals": []}} immediately

If this is an ISSUE or DISCUSSION:
- Extract the problem described in the original post
- Read visible comments for workarounds and feature requests
- Note reaction counts if visible

If this is a REPOSITORY page or README:
- Extract stated limitations, known issues, alternatives mentioned
- Look for "Limitations", "Caveats", "Not supported" sections

Return JSON:
{{
  "url": "{url}",
  "blocked": false,
  "page_title": "string",
  "signals": [
    {{
      "signal_type": "pain|workaround|request|incumbent_failure|limitation",
      "text": "one sentence summarizing the signal",
      "tool_mentioned": "specific tool or repo name",
      "evidence_quote": "exact quote, max 200 chars",
      "author": "username or null"
    }}
  ]
}}

Return ONLY valid JSON."""


SINGLE_PAGE_REVIEW_GOAL = """Read this review/product page and extract user complaints related to "{topic}".

NAVIGATION RULES (MANDATORY — read these first):
- Read ONLY this URL: {url}
- Do NOT click "read more reviews", pagination, "show all", or any navigation
- Read only the reviews already visible on this page
- If blocked or login-required: return {{"blocked": true, "signals": []}} immediately

From visible reviews, extract up to 5 of the strongest negative signals:
- Specific feature complaints ("lacks X", "X doesn't support Y")
- Pricing/value frustrations
- Missing capabilities users need

Focus on "Cons", "What do you dislike?", and low-star reviews. Ignore positive reviews.

Return JSON:
{{
  "url": "{url}",
  "blocked": false,
  "page_title": "string",
  "product_name": "string or null",
  "signals": [
    {{
      "signal_type": "pain|request|incumbent_failure",
      "text": "one sentence summarizing the complaint",
      "tool_mentioned": "the product being reviewed",
      "evidence_quote": "exact quote from the review, max 200 chars"
    }}
  ]
}}

Return ONLY valid JSON."""


SINGLE_PAGE_COMPARISON_GOAL = """Read this comparison/alternatives page and extract competitive gaps related to "{topic}".

NAVIGATION RULES (MANDATORY — read these first):
- Read ONLY this URL: {url}
- Do NOT click into individual product pages, review links, or "read more"
- Read only what is visible on this page
- If blocked: return {{"blocked": true, "signals": []}} immediately

Extract up to 5 signals about product weaknesses, missing features, or reasons people switch tools.

Return JSON:
{{
  "url": "{url}",
  "blocked": false,
  "page_title": "string",
  "products_compared": ["string"],
  "signals": [
    {{
      "signal_type": "pain|request|incumbent_failure",
      "text": "one sentence: what product lacks what",
      "tool_mentioned": "the product with the weakness",
      "evidence_quote": "exact quote, max 200 chars"
    }}
  ]
}}

Return ONLY valid JSON."""


SINGLE_PAGE_WORKFLOW_GOAL = """Read this page and extract workflow details and pain points related to "{topic}".

NAVIGATION RULES (MANDATORY — read these first):
- Read ONLY this URL: {url}
- Do NOT click links to other articles, docs pages, or referenced tools
- If blocked: return {{"blocked": true, "signals": []}} immediately

Extract up to 5 signals focusing on:
- Multi-step processes described ("first we X, then Y")
- Manual or tedious steps in a workflow
- Tool gaps ("we couldn't find a tool that...")
- Workarounds or custom scripts people built

Return JSON:
{{
  "url": "{url}",
  "blocked": false,
  "page_title": "string",
  "signals": [
    {{
      "signal_type": "pain|workaround|request|workflow",
      "text": "one sentence summarizing the signal",
      "tool_mentioned": "specific tool name or null",
      "evidence_quote": "exact quote, max 200 chars"
    }}
  ]
}}

Return ONLY valid JSON."""


SINGLE_PAGE_SO_GOAL = """Read this Stack Overflow question and its top answer related to "{topic}".

NAVIGATION RULES (MANDATORY — read these first):
- Read ONLY this URL: {url}
- Do NOT click linked questions, related questions, or "more answers"
- Read only the question and the accepted/top answer
- If blocked: return {{"blocked": true, "signals": []}} immediately

Extract up to 3 signals:
- The core problem from the question
- Workarounds or hacks described in the top answer
- Tool-specific limitations mentioned

Return JSON:
{{
  "url": "{url}",
  "blocked": false,
  "page_title": "string",
  "signals": [
    {{
      "signal_type": "pain|workaround|request|incumbent_failure",
      "text": "one sentence summarizing the signal",
      "tool_mentioned": "specific tool or library name",
      "evidence_quote": "exact quote, max 200 chars"
    }}
  ]
}}

Return ONLY valid JSON."""


# =============================================================================
# LEGACY PROMPTS — kept for backward compatibility, used by focused extraction
# =============================================================================

CATEGORY_DISCOVERY_GOAL = """Discover high-value pages in the {vertical} ecosystem.

Return JSON:
{{
  "vertical": "{vertical}",
  "seed_url": "{seed_url}",
  "discovered_pages": [
    {{
      "page_type": "category|product|comparison|alternatives|review",
      "title": "string",
      "url": "string",
      "product_name": "string or null",
      "category_name": "string or null",
      "reason_relevant": "string"
    }}
  ]
}}

Stop when:
- 25 pages found
- 5 pages visited
- no more links

If blocked, stop and return partial results."""


async def discover_categories(seed_url: str, vertical: str, topic: str | None = None) -> list[dict]:
    """Prompt A — Discover relevant pages in a vertical."""
    goal = CATEGORY_DISCOVERY_GOAL.format(vertical=vertical, seed_url=seed_url)
    return await _run_extraction(seed_url, goal, extraction_type="category_discovery", topic=topic or vertical)


# =============================================================================
# PROMPT B — Review Harvest
# =============================================================================

REVIEW_HARVEST_GOAL = """Extract structured review intelligence from this page.

Return JSON:
{{
  "source_url": "{url}",
  "items": [
    {{
      "product_name": "string",
      "review_body": "string",
      "pros": ["string"],
      "cons": ["string"],
      "missing_features": ["string"],
      "persona_clues": ["string"],
      "workflow_clues": ["string"],
      "complaint_signals": ["string"]
    }}
  ]
}}

Stop when:
- 20 reviews extracted
- 5 pages processed
- a login wall or CAPTCHA appears

If a field is missing, return null or an empty list.
If blocked, stop and return partial results."""


async def fetch_reviews(url: str, topic: str | None = None) -> list[dict]:
    """Prompt B — Review harvest job."""
    goal = REVIEW_HARVEST_GOAL.format(url=url)
    if topic:
        goal = f"Focus on reviews related to '{topic}'.\n\n{goal}"
    return await _run_extraction(url, goal, extraction_type="reviews", topic=topic)


# =============================================================================
# PROMPT C — Incumbent Gap Extraction
# =============================================================================

INCUMBENT_GAP_GOAL = """Extract failures and unmet needs from existing products on this page.

Return JSON:
{{
  "source_url": "{url}",
  "gaps": [
    {{
      "product_name": "string",
      "failure_type": "missing_feature|too_expensive|too_bloated|poor_ux|reliability",
      "failure_text": "string",
      "workflow_clue": "string or null",
      "persona_clue": "string or null"
    }}
  ]
}}

Focus on:
- Repeated complaints about specific products
- Missing features users explicitly ask for
- Pricing friction and value concerns
- Reliability and UX problems
- Workflow gaps where existing tools fail

If a field is missing, return null.
If blocked, stop and return partial results."""


async def fetch_incumbent_gaps(url: str, topic: str | None = None) -> list[dict]:
    """Prompt C — Incumbent gap extraction job."""
    goal = INCUMBENT_GAP_GOAL.format(url=url)
    if topic:
        goal = f"Focus on gaps related to '{topic}'.\n\n{goal}"
    return await _run_extraction(url, goal, extraction_type="incumbent_gaps", topic=topic)


# =============================================================================
# PROMPT D — Comparison Extraction
# =============================================================================

COMPARISON_GOAL = """Extract competitor intelligence from this page.

Return JSON:
{{
  "source_url": "{url}",
  "comparisons": [
    {{
      "product_name": "string",
      "strengths": ["string"],
      "weaknesses": ["string"],
      "missing_capabilities": ["string"],
      "persona_clues": ["string"],
      "workflow_clues": ["string"]
    }}
  ]
}}

Stop when:
- 10 products compared
- no more comparison data
- a login wall or CAPTCHA appears

Focus on weaknesses, missing capabilities, and what users wish was different.
If a field is missing, return an empty list."""


async def fetch_comparison_page(url: str, topic: str | None = None) -> list[dict]:
    """Prompt D — Comparison extraction job."""
    goal = COMPARISON_GOAL.format(url=url)
    if topic:
        goal = f"Focus on comparisons related to '{topic}'.\n\n{goal}"
    return await _run_extraction(url, goal, extraction_type="comparison", topic=topic)


# =============================================================================
# PROMPT E — Forum Deep Harvest
# =============================================================================

FORUM_DEEP_HARVEST_GOAL = """Extract workflow pain signals from this forum/discussion page.

Return JSON:
{{
  "post": {{
    "title": "string",
    "body": "string",
    "author": "string or null"
  }},
  "comments": [
    {{
      "author": "string or null",
      "text": "string",
      "score": "string or null"
    }}
  ],
  "signals": [
    {{
      "signal_type": "pain|workaround|request|incumbent_failure",
      "text": "string",
      "evidence_quote": "string",
      "tools_mentioned": ["string"],
      "persona_clue": "string or null",
      "workflow_clue": "string or null"
    }}
  ]
}}

Stop when:
- 20 comments captured
- 20 signals extracted
- 5 pages processed
- a login wall or CAPTCHA appears

Focus on:
- Workflow pain and frustrations
- Manual workarounds people describe
- Explicit requests for tools or features
- Complaints about existing tools failing
- The main post and the most relevant visible comments

If a field is missing, return null.
If blocked, stop and return partial results."""


async def fetch_forum_signals(url: str, topic: str | None = None) -> list[dict]:
    """Prompt E — Forum deep harvest job."""
    goal = FORUM_DEEP_HARVEST_GOAL.format(url=url)
    if topic:
        goal = f"Focus on signals related to '{topic}'.\n\n{goal}"
    return await _run_extraction(url, goal, extraction_type="forum_signals", topic=topic)


# =============================================================================
# PROMPT F — Workflow Description Harvest
# =============================================================================

WORKFLOW_DESCRIPTION_GOAL = """Extract workflow descriptions, step-by-step processes, and operational patterns from this page.

Return JSON:
{{
  "source_url": "{url}",
  "workflows": [
    {{
      "workflow_name": "string",
      "description": "string",
      "steps": ["string"],
      "tools_used": ["string"],
      "pain_points": ["string"],
      "persona_clue": "string or null",
      "frequency": "string or null"
    }}
  ]
}}

Stop when:
- 15 workflows extracted
- 5 pages processed
- a login wall or CAPTCHA appears

Focus on:
- Operator blogs describing their daily processes
- Product documentation showing multi-step workflows
- How-to guides with sequential tasks
- Workflow writeups that mention tool gaps or manual steps

If a field is missing, return null or an empty list.
If blocked, stop and return partial results."""


async def fetch_workflow_descriptions(url: str, topic: str | None = None) -> list[dict]:
    """Prompt F — Workflow description harvest job."""
    goal = WORKFLOW_DESCRIPTION_GOAL.format(url=url)
    if topic:
        goal = f"Focus on workflows related to '{topic}'.\n\n{goal}"
    return await _run_extraction(url, goal, extraction_type="workflow_descriptions", topic=topic)


# =============================================================================
# Existing extraction types (README, StackOverflow, discussions)
# =============================================================================

README_PAIN_GOAL = """Analyze this GitHub repository page and extract pain signals, limitations, and gaps. Return JSON with:
{
  "repo_name": "string",
  "description": "string or null",
  "limitations": ["string"],
  "known_issues": ["string"],
  "alternatives_mentioned": ["string"],
  "missing_features": ["string"],
  "pain_signals_from_readme": ["string"],
  "workarounds_mentioned": ["string"],
  "comparison_notes": ["string"]
}

Look specifically for:
- Sections titled "Limitations", "Known Issues", "Caveats", "Gotchas", "FAQ", "Troubleshooting"
- Mentions of what the tool does NOT do
- Comparisons with other tools ("unlike X", "compared to Y", "alternative to Z")
- Warnings or notes about missing functionality
- Workarounds described in documentation

If a section is not found, return an empty list for that field.
Do NOT make up information — only extract what is explicitly stated.
If the page is not a GitHub repo or README, return empty lists for all fields."""


STACKOVERFLOW_GOAL = """Extract questions and top answers from this Stack Overflow page. Return JSON with:
{
  "questions": [
    {
      "title": "string",
      "body": "string",
      "votes": "number",
      "answers_count": "number",
      "tags": ["string"],
      "top_answer": "string or null",
      "url": "string or null",
      "has_accepted_answer": "boolean"
    }
  ]
}

Stop when:
- 15 questions extracted
- no next-page button
- 3 pages processed

Focus on questions that express problems, frustrations, or requests for alternatives.
If a field is missing, return null or an empty list."""


DISCUSSION_EXTRACTION_GOAL = """Extract discussion posts and comments from this page and return JSON with:
{
  "posts": [
    {
      "title": "string or null",
      "body": "string",
      "author": "string or null",
      "date": "string or null",
      "replies": ["string"],
      "url": "string or null"
    }
  ]
}

Stop when:
- 20 posts extracted
- no next-page button or load-more button
- 3 pages processed
- a login wall or CAPTCHA appears

If a field is missing, return null or an empty list.
If blocked, stop and return partial results."""


async def fetch_readme_pain(url: str, topic: str | None = None) -> list[dict]:
    goal = README_PAIN_GOAL
    if topic:
        goal = f"Focus on aspects related to '{topic}'.\n\n{goal}"
    return await _run_extraction(url, goal, extraction_type="readme", topic=topic)


async def fetch_stackoverflow(url: str, topic: str | None = None) -> list[dict]:
    goal = STACKOVERFLOW_GOAL
    if topic:
        goal = f"Focus on questions related to '{topic}'.\n\n{goal}"
    return await _run_extraction(url, goal, extraction_type="stackoverflow", topic=topic)


async def fetch_discussions(url: str, topic: str | None = None) -> list[dict]:
    goal = DISCUSSION_EXTRACTION_GOAL
    if topic:
        goal = f"Focus on discussions related to '{topic}'.\n\n{goal}"
    return await _run_extraction(url, goal, extraction_type="discussions", topic=topic)


async def fetch_with_goal(url: str, goal: str) -> dict:
    """Run a custom TinyFish extraction with a caller-defined goal."""
    client = _get_client()
    try:
        async with client:
            response = await client.agent.run(url=url, goal=goal)
            if response.status == "COMPLETED" and response.result:
                return {"run_id": response.run_id, "status": "completed", "result": response.result}
            error_msg = response.error.message if response.error else "Unknown error"
            logger.warning("TinyFish run failed for %s: %s", url, error_msg)
            return {"run_id": response.run_id, "status": "failed", "error": error_msg}
    except Exception as e:
        logger.error("TinyFish error for %s: %s", url, e)
        return {"run_id": None, "status": "error", "error": str(e)}


async def batch_extract(urls_and_goals: list[tuple[str, str]]) -> list[dict]:
    """Stream multiple TinyFish extractions in parallel via SSE."""
    import asyncio
    import json as _json

    if not urls_and_goals:
        return []

    async def _stream_one(url: str, goal: str) -> dict:
        client = _get_client()
        try:
            async with client:
                body = {"url": url, "goal": goal, "browser_profile": _get_browser_profile()}
                result_data = None
                lines = client.agent._post_stream("/v1/automation/run-sse", json=body)
                async for line in lines:
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    try:
                        event = _json.loads(line[6:])
                    except _json.JSONDecodeError:
                        continue
                    if event.get("type") == "PROGRESS":
                        print(f"  [TinyFish] batch | {url.split('/')[-1][:30]} | {event.get('purpose', '')}", flush=True)
                    elif event.get("type") == "COMPLETE":
                        result_data = event.get("result")
                if result_data:
                    return {"url": url, "status": "completed", "result": result_data}
                return {"url": url, "status": "failed", "result": None}
        except Exception as e:
            logger.warning("TinyFish batch stream failed for %s: %s", url, e)
            return {"url": url, "status": "error", "result": None}

    tasks = [_stream_one(url, goal) for url, goal in urls_and_goals]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, dict) and r.get("result")]


GITHUB_INTELLIGENCE_GOAL = """Browse this GitHub page and extract ALL intelligence signals related to "{topic}".

Return JSON:
{{
  "source_url": "{url}",
  "items": [
    {{
      "url": "string",
      "title": "string",
      "item_type": "issue|discussion|readme|release_note|migration_guide|trending_repo",
      "signal_type": "pain|workaround|feature_request|breaking_change|migration|limitation|alternative",
      "text": "string (the relevant content)",
      "stars_or_comments": "number or null",
      "tools_mentioned": ["string"],
      "alternatives_mentioned": ["string"]
    }}
  ]
}}

For repositories (50+ stars only):
- Read the README and extract: limitations, known issues, "not supported", alternatives mentioned
- Check recent releases: look for BREAKING CHANGE entries
- Skip tutorials, boilerplates, personal projects

For issues (5+ comments only):
- Focus on: bugs, feature requests, help-wanted
- Extract: the problem described, any workarounds mentioned, what users wish existed
- Skip: dependency updates, typo fixes, CI/CD issues, version bumps

For discussions:
- Focus on real user pain, workflow questions, "how do I" posts
- Skip announcements, release notes without user complaints

For migration guides:
- Extract: what tool people are migrating FROM and TO, and why they're switching

Stop when 20 items found or 5 pages visited.
If blocked, return partial results."""


# V2 prompt mapping — single-page, zero-navigation prompts
GOAL_TEMPLATES_BY_PAGE_TYPE = {
    "review": ("signals", SINGLE_PAGE_REVIEW_GOAL),
    "comparison": ("signals", SINGLE_PAGE_COMPARISON_GOAL),
    "alternatives": ("signals", SINGLE_PAGE_COMPARISON_GOAL),
    "product": ("signals", SINGLE_PAGE_REVIEW_GOAL),
    "directory": ("signals", SINGLE_PAGE_REVIEW_GOAL),
    "forum": ("signals", SINGLE_PAGE_FORUM_GOAL),
    "reddit": ("signals", SINGLE_PAGE_FORUM_GOAL),
    "discourse": ("signals", SINGLE_PAGE_FORUM_GOAL),
    "lobsters": ("signals", SINGLE_PAGE_FORUM_GOAL),
    "indiehackers": ("signals", SINGLE_PAGE_FORUM_GOAL),
    "twitter": ("signals", SINGLE_PAGE_FORUM_GOAL),
    "stackoverflow": ("signals", SINGLE_PAGE_SO_GOAL),
    "producthunt": ("signals", SINGLE_PAGE_REVIEW_GOAL),
    "feature_board": ("signals", SINGLE_PAGE_REVIEW_GOAL),
    "newsletter": ("signals", SINGLE_PAGE_WORKFLOW_GOAL),
    "engineering_blog": ("signals", SINGLE_PAGE_WORKFLOW_GOAL),
    "workflow": ("signals", SINGLE_PAGE_WORKFLOW_GOAL),
    "blog": ("signals", SINGLE_PAGE_WORKFLOW_GOAL),
    "github": ("signals", SINGLE_PAGE_GITHUB_GOAL),
}


# =============================================================================
# Discover + Extract: single-call discovery and signal extraction
# =============================================================================

async def discover_and_extract(
    search_query: str,
    max_pages: int = 5,
    timeout_seconds: float = 45.0,
) -> dict:
    """Single TinyFish call: search DuckDuckGo, visit top results, extract signals.

    Replaces the old two-pass flow (search for URLs → revisit each URL).
    Returns both discovered pages and extracted signals in one pass.
    """
    import json as _json

    goal = DISCOVER_AND_EXTRACT_GOAL.format(
        search_query=search_query,
        max_pages=max_pages,
    )
    url = f"https://duckduckgo.com/?q={search_query.replace(' ', '+')}"

    client = _get_client()
    try:
        async with client:
            body = {"url": url, "goal": goal, "browser_profile": _get_browser_profile()}
            result_data = None
            lines = client.agent._post_stream("/v1/automation/run-sse", json=body)

            async def _collect():
                nonlocal result_data
                async for line in lines:
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    try:
                        event = _json.loads(line[6:])
                    except _json.JSONDecodeError:
                        continue
                    etype = event.get("type", "")
                    if etype == "PROGRESS":
                        print(f"  [discover+extract] {event.get('purpose', '')}", flush=True)
                    elif etype == "COMPLETE":
                        result_data = event.get("result")

            if timeout_seconds and timeout_seconds > 0:
                await asyncio.wait_for(_collect(), timeout=timeout_seconds)
            else:
                await _collect()  # no timeout — run until TinyFish completes

            if not result_data:
                return {"pages": [], "signals": []}

            # Parse — handle both the expected schema and raw text
            if isinstance(result_data, str):
                try:
                    result_data = _json.loads(result_data)
                except _json.JSONDecodeError:
                    # Try to extract JSON from markdown code blocks
                    if "```" in result_data:
                        text = result_data.split("```")[1]
                        if text.startswith("json"):
                            text = text[4:]
                        result_data = _json.loads(text.strip())
                    else:
                        return {"pages": [], "signals": []}

            pages = result_data.get("pages", [])
            # Flatten signals from all pages
            all_signals = []
            for page in pages:
                for sig in page.get("signals", []):
                    sig["source_url"] = page.get("url", "")
                    sig["source_platform"] = page.get("page_type", "")
                    all_signals.append(sig)

            logger.info("discover_and_extract: %d pages, %d signals for '%s'",
                        len(pages), len(all_signals), search_query[:50])

            # Persist raw results to disk for debugging + future reprocessing
            _persist_discovery_results(search_query, pages, all_signals)

            return {"pages": pages, "signals": all_signals}

    except TimeoutError:
        logger.warning("discover_and_extract timed out after %.0fs for '%s'",
                        timeout_seconds, search_query[:50])
        return {"pages": [], "signals": []}
    except Exception as e:
        logger.warning("discover_and_extract error for '%s': %s", search_query[:50], e)
        return {"pages": [], "signals": []}


def _persist_discovery_results(
    search_query: str, pages: list[dict], signals: list[dict],
) -> None:
    """Save raw discovery+extraction results to disk for debugging and reprocessing.

    Files are saved to data/discoveries/ as JSONL, one per search query.
    These can be fed back into the pipeline via run_pipeline_v2_from_documents()
    without re-crawling.
    """
    import json as _json
    from hashlib import md5
    from pathlib import Path

    try:
        out_dir = Path("data/discoveries")
        out_dir.mkdir(parents=True, exist_ok=True)

        query_hash = md5(search_query.encode()).hexdigest()[:10]
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"{ts}_{query_hash}.jsonl"

        with open(path, "w") as f:
            record = {
                "search_query": search_query,
                "timestamp": datetime.now(UTC).isoformat(),
                "pages_count": len(pages),
                "signals_count": len(signals),
                "pages": pages,
                "signals": signals,
            }
            f.write(_json.dumps(record, default=str) + "\n")

        logger.info("Persisted discovery results to %s (%d signals)", path.name, len(signals))
    except Exception as e:
        logger.debug("Failed to persist discovery results: %s", e)


async def batch_extract_pages(pages: list[dict], topic: str) -> list[dict]:
    """Batch-extract a list of discovered pages in parallel.

    Each page dict should have 'url' and 'page_type'.
    Returns flattened parsed items from all pages.
    """
    if not pages:
        return []

    urls_and_goals = []
    page_meta = []  # track extraction_type per page for parsing
    for page in pages:
        page_type = page.get("page_type", "review")
        template = GOAL_TEMPLATES_BY_PAGE_TYPE.get(page_type)
        if not template:
            continue
        extraction_type, goal_template = template
        # Format goal — some templates use {url}, some use {topic}, some use both
        try:
            goal = goal_template.format(url=page["url"], topic=topic or "")
        except KeyError:
            goal = goal_template.format(url=page["url"])
        if topic and "{topic}" not in goal_template:
            goal = f"Focus on content related to '{topic}'.\n\n{goal}"
        urls_and_goals.append((page["url"], goal))
        page_meta.append({"url": page["url"], "extraction_type": extraction_type})

    if not urls_and_goals:
        return []

    raw_results = await batch_extract(urls_and_goals)

    all_items = []
    # Match results back to their extraction types
    url_to_meta = {m["url"]: m for m in page_meta}
    for result in raw_results:
        url = result.get("url", "")
        meta = url_to_meta.get(url)
        if not meta or not result.get("result"):
            continue
        items = _parse_result(result["result"], meta["extraction_type"], url)
        for item in items:
            item["discovery_source"] = "batch_extract"
            item["discovery_page_type"] = meta["extraction_type"]
        all_items.extend(items)

    logger.info("Batch extracted %d items from %d pages", len(all_items), len(pages))
    return all_items


def generate_target_urls(topic: str, repos: list[dict] | None = None) -> dict[str, list[str]]:
    """Generate high-value URLs for TinyFish to scrape given a topic."""
    topic_slug = topic.lower().replace(" ", "+")
    topic_hyphen = topic.lower().replace(" ", "-")
    targets: dict[str, list[str]] = {
        "stackoverflow": [
            f"https://stackoverflow.com/questions/tagged/{topic_hyphen}?tab=votes",
        ],
        "comparison": [
            f"https://alternativeto.net/software/{topic_hyphen}/",
        ],
        "readme": [],
        "category_discovery": [
            f"https://www.g2.com/search?query={topic_slug}",
        ],
        "workflow_descriptions": [
            f"https://www.google.com/search?q={topic_slug}+workflow+process+how+to",
        ],
    }
    if repos:
        for repo in repos[:5]:
            readme_url = repo.get("readme_url") or repo.get("url", "")
            if readme_url:
                targets["readme"].append(readme_url)
    return targets


# =============================================================================
# Stealth mode routing
# =============================================================================

def _get_browser_profile() -> str:
    """Always use stealth — handles CAPTCHAs, anti-bot, rate limiting."""
    return "stealth"


# =============================================================================
# Web Search — TinyFish finds sites to crawl
# =============================================================================

WEB_SEARCH_GOAL = """Visit the input search results page and find direct content pages about "{search_query}".

Return JSON:
{{
  "search_query": "{search_query}",
  "results": [
    {{
      "url": "string",
      "title": "string",
      "page_type": "reddit|forum|github|docs|blog|review|comparison|workflow|product|directory|other",
      "recommended_extractor": "forum|github|workflow|review|comparison|skip",
      "content_signals": {{
        "has_operator_pain": true,
        "has_workarounds": false,
        "has_feature_requests": false,
        "has_incumbent_failures": false,
        "has_workflow_context": false,
        "has_direct_quotes": false,
        "has_user_generated_content": false
      }},
      "reason": "string"
    }}
  ]
}}

Return only direct content pages, up to {max_results} results.

Prioritize:
1. Reddit or forum threads with real operator discussion
2. GitHub issues, discussions, or repositories with real product gaps
3. Documentation, guides, runbooks, or workflow pages
4. Practitioner blog posts with concrete workflow details
5. Review, comparison, or alternatives pages with concrete user complaints

Exclude:
- search result pages
- landing pages
- pricing pages
- vendor marketing
- generic listicles
- news articles with no workflow or product evidence
- pages with no readable content

For each result:
- set page_type to the closest content type
- set recommended_extractor based on the content on the page
- set content_signals based only on what is visible from the result context or page preview

If blocked, return partial results."""


async def search_for_sources(search_query: str, max_results: int = 8, evidence_class: str | None = None) -> list[dict]:
    """Use TinyFish streaming to search Google for high-quality pages."""
    import json as _json

    goal = WEB_SEARCH_GOAL.format(search_query=search_query, max_results=max_results)
    url = f"https://www.google.com/search?q={search_query.replace(' ', '+')}"

    client = _get_client()
    try:
        async with client:
            result_data = None
            body = {"url": url, "goal": goal, "browser_profile": _get_browser_profile()}
            lines = client.agent._post_stream("/v1/automation/run-sse", json=body)
            async for line in lines:
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue
                try:
                    event_data = _json.loads(line[6:])
                except _json.JSONDecodeError:
                    continue
                if event_data.get("type") == "PROGRESS":
                    print(f"  [TinyFish] search | {event_data.get('purpose', '')}", flush=True)
                elif event_data.get("type") == "COMPLETE":
                    result_data = event_data.get("result")

            if not result_data:
                logger.warning("Web search failed for '%s'", search_query)
                return []

            results = result_data.get("results", [])
            if not isinstance(results, list):
                return []

            parsed = []
            for r in results:
                if not isinstance(r, dict) or not r.get("url"):
                    continue
                parsed.append({
                    "url": r["url"],
                    "title": r.get("title", ""),
                    "page_type": r.get("page_type", "review"),
                    "recommended_extractor": r.get("recommended_extractor", ""),
                    "content_signals": r.get("content_signals", {}) if isinstance(r.get("content_signals"), dict) else {},
                    "reason": r.get("reason", ""),
                    "source": "web_search",
                    "search_query": search_query,
                    "evidence_class": evidence_class,
                })

            logger.info("Web search found %d sources for '%s'", len(parsed), search_query)
            return parsed

    except Exception as e:
        logger.error("Web search error for '%s': %s", search_query, e)
        return []


async def search_multiple_queries(queries: list, max_results_per: int = 8) -> list[dict]:
    """Run multiple Google searches in parallel and deduplicate results."""
    import asyncio

    if not queries:
        return []

    tasks = []
    for item in queries[:4]:
        if isinstance(item, dict):
            tasks.append(search_for_sources(item.get("query", ""), max_results_per, evidence_class=item.get("evidence_class")))
        else:
            tasks.append(search_for_sources(str(item), max_results_per))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    seen_urls: set[str] = set()
    all_results: list[dict] = []
    for result in results:
        if isinstance(result, list):
            for item in result:
                url = item.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(item)

    logger.info("Multi-query search found %d unique sources from %d queries",
                len(all_results), len(queries))
    return all_results


# =============================================================================
# Stream mode for debugging
# =============================================================================

async def stream_extraction(url: str, goal: str):
    """Run a TinyFish extraction in stream mode for debugging.

    Yields SSE events as they arrive.
    """
    client = _get_client()
    events = []
    try:
        async with client:
            async with client.agent.stream(url=url, goal=goal) as stream:
                async for event in stream:
                    event_data = {
                        "type": type(event).__name__,
                    }
                    if hasattr(event, "run_id"):
                        event_data["run_id"] = event.run_id
                    if hasattr(event, "purpose"):
                        event_data["purpose"] = event.purpose
                    if hasattr(event, "status"):
                        event_data["status"] = event.status
                    if hasattr(event, "result"):
                        event_data["result"] = event.result
                    if hasattr(event, "streaming_url"):
                        event_data["streaming_url"] = event.streaming_url
                    events.append(event_data)
        return events
    except Exception as e:
        logger.error("Stream extraction error: %s", e)
        return [{"type": "error", "message": str(e)}]


# =============================================================================
# List recent runs
# =============================================================================

async def list_recent_runs(limit: int = 20) -> list[dict]:
    """List recent TinyFish runs for monitoring."""
    client = _get_client()
    try:
        async with client:
            response = await client.runs.list(limit=limit)
            run_list = getattr(response, "runs", None) or getattr(response, "data", None) or []
            if not isinstance(run_list, list):
                run_list = list(run_list) if hasattr(run_list, "__iter__") else []
            runs = []
            for run in run_list:
                runs.append({
                    "run_id": getattr(run, "id", ""),
                    "status": getattr(run, "status", ""),
                    "goal": (getattr(run, "goal", "") or "")[:100],
                    "created_at": str(getattr(run, "created_at", "")),
                })
            return runs
    except Exception as e:
        logger.error("List runs error: %s", e)
        return []


# =============================================================================
# Internal extraction runner
# =============================================================================

async def _run_extraction(
    url: str, goal: str, extraction_type: str, topic: str | None = None,
    max_retries: int = 2,
    event_callback=None,
) -> list[dict]:
    """Run a TinyFish extraction using SSE streaming (fast) instead of blocking run()."""
    import json as _json

    from app.services.ingest.extraction_cache import cache_extraction, get_cached_extraction

    # Check extraction cache first — avoids re-crawling already-seen URLs
    cached = get_cached_extraction(url, extraction_type)
    if cached is not None:
        logger.info("Cache hit (%d items) for %s [%s] — skipping TinyFish call", len(cached), url, extraction_type)
        return cached

    run_id = str(uuid.uuid4())
    start = time.monotonic()
    goal_hash = md5(goal.encode()).hexdigest()[:16]
    browser_profile = _get_browser_profile()
    last_error_type = TinyFishErrorType.unknown
    last_error_msg = ""

    for attempt in range(max_retries + 1):
        client = _get_client()
        try:
            async with client:
                async def _collect_stream() -> tuple[str | None, str | None, dict | None, str, object | None]:
                    tf_run_id = None
                    streaming_url = None
                    result_data = None
                    final_status = "FAILED"
                    error_obj = None

                    # Use raw SSE stream to get result (SDK has a field name mismatch for result_json)
                    body = {"url": url, "goal": goal}
                    if browser_profile:
                        body["browser_profile"] = browser_profile
                    lines = client.agent._post_stream("/v1/automation/run-sse", json=body)
                    async for line in lines:
                        line = line.strip()
                        if not line or not line.startswith("data: "):
                            continue
                        try:
                            event_data = _json.loads(line[6:])
                        except _json.JSONDecodeError:
                            continue
                        etype = event_data.get("type", "")
                        if "run_id" in event_data:
                            tf_run_id = event_data["run_id"]
                        if "streaming_url" in event_data:
                            streaming_url = event_data["streaming_url"]
                        if etype == "PROGRESS":
                            print(f"  [TinyFish] {extraction_type} | {event_data.get('purpose', '')}", flush=True)
                        elif etype == "COMPLETE":
                            final_status = event_data.get("status", "FAILED")
                            result_data = event_data.get("result")
                            error_msg_raw = event_data.get("error")
                            if error_msg_raw and isinstance(error_msg_raw, dict):
                                error_obj = type("Err", (), {"message": error_msg_raw.get("message", "")})()
                            elif error_msg_raw:
                                error_obj = type("Err", (), {"message": str(error_msg_raw)})()
                    return tf_run_id, streaming_url, result_data, final_status, error_obj

                tf_run_id, streaming_url, result_data, final_status, error_obj = await asyncio.wait_for(
                    _collect_stream(),
                    timeout=settings.tinyfish_timeout_seconds,
                )

                duration_ms = int((time.monotonic() - start) * 1000)

                if final_status != "COMPLETED" or not result_data:
                    last_error_msg = error_obj.message if error_obj else "No result"
                    last_error_type = classify_error(exception=Exception(last_error_msg))
                    logger.warning("TinyFish %s failed for %s (attempt %d, %dms): %s",
                                   extraction_type, url, attempt + 1, duration_ms, last_error_msg)

                    if attempt < max_retries and is_retryable(last_error_type):
                        backoff = 5.0 if last_error_type == TinyFishErrorType.rate_limit else 2.0
                        await asyncio.sleep(backoff * (2 ** attempt))
                        continue

                    await _save_run({
                        "id": run_id, "tinyfish_run_id": tf_run_id,
                        "job_type": extraction_type, "url": url, "goal_hash": goal_hash,
                        "status": "failed", "error_type": last_error_type.value,
                        "error_message": last_error_msg, "browser_profile": browser_profile,
                        "streaming_url": streaming_url,
                        "items_extracted": 0, "duration_ms": duration_ms,
                        "result_summary_json": json.dumps(_summarize_result_payload(result_data), default=str),
                        "topic": topic, "retry_count": attempt,
                        "created_at": datetime.now(UTC),
                        "completed_at": datetime.now(UTC),
                    })
                    if event_callback:
                        await event_callback("tinyfish.extraction.failed", {
                            "url": url,
                            "extraction_type": extraction_type,
                            "tinyfish_run_id": tf_run_id,
                            "streaming_url": streaming_url,
                            "attempt": attempt + 1,
                            "duration_ms": duration_ms,
                            "error_type": last_error_type.value,
                            "error_message": last_error_msg,
                            "result_summary": _summarize_result_payload(result_data),
                        })
                    return []

                items = _parse_result(result_data, extraction_type, url)
                logger.info("TinyFish extracted %d %s items from %s (run=%s, %dms, attempt=%d)",
                            len(items), extraction_type, url, tf_run_id, duration_ms, attempt + 1)

                # Cache successful extractions for future runs
                if items:
                    try:
                        cache_extraction(url, extraction_type, items, topic or "")
                    except Exception as cache_err:
                        logger.debug("Failed to cache extraction for %s: %s", url, cache_err)

                await _save_run({
                    "id": run_id, "tinyfish_run_id": tf_run_id,
                    "job_type": extraction_type, "url": url, "goal_hash": goal_hash,
                    "status": "completed", "error_type": None, "error_message": None,
                    "browser_profile": browser_profile,
                    "streaming_url": streaming_url,
                    "items_extracted": len(items), "duration_ms": duration_ms,
                    "result_summary_json": json.dumps(_summarize_result_payload(result_data), default=str),
                    "topic": topic, "retry_count": attempt,
                    "created_at": datetime.now(UTC),
                    "completed_at": datetime.now(UTC),
                })
                if event_callback:
                    await event_callback("tinyfish.extraction.completed", {
                        "url": url,
                        "extraction_type": extraction_type,
                        "tinyfish_run_id": tf_run_id,
                        "streaming_url": streaming_url,
                        "attempt": attempt + 1,
                        "duration_ms": duration_ms,
                        "raw_result_summary": _summarize_result_payload(result_data),
                        "parsed_item_count": len(items),
                        "sample_titles": [item.get("title", "") for item in items[:3] if item.get("title")],
                    })
                return items
        except TimeoutError:
            last_error_type = TinyFishErrorType.timeout
            last_error_msg = f"TinyFish timed out after {settings.tinyfish_timeout_seconds:.0f}s"
            logger.warning("TinyFish %s timed out for %s (attempt %d)", extraction_type, url, attempt + 1)

            if attempt < max_retries and is_retryable(last_error_type):
                await asyncio.sleep(2.0 * (2 ** attempt))
                continue

            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error("TinyFish %s permanently timed out for %s after %d attempts",
                         extraction_type, url, attempt + 1)
            await _save_run({
                "id": run_id, "tinyfish_run_id": None,
                "job_type": extraction_type, "url": url, "goal_hash": goal_hash,
                "status": "failed", "error_type": last_error_type.value,
                "error_message": last_error_msg, "browser_profile": browser_profile,
                "items_extracted": 0, "duration_ms": duration_ms,
                "result_summary_json": json.dumps({}, default=str),
                "topic": topic, "retry_count": attempt,
                "created_at": datetime.now(UTC),
                "completed_at": datetime.now(UTC),
            })
            if event_callback:
                await event_callback("tinyfish.extraction.failed", {
                    "url": url,
                    "extraction_type": extraction_type,
                    "tinyfish_run_id": None,
                    "streaming_url": None,
                    "attempt": attempt + 1,
                    "duration_ms": duration_ms,
                    "error_type": last_error_type.value,
                    "error_message": last_error_msg,
                    "result_summary": {},
                })
            return []
        except Exception as e:
            last_error_type = classify_error(exception=e)
            last_error_msg = str(e)
            logger.warning("TinyFish error for %s (attempt %d): %s", url, attempt + 1, e)

            if attempt < max_retries and is_retryable(last_error_type):
                backoff = 5.0 if last_error_type == TinyFishErrorType.rate_limit else 2.0
                await asyncio.sleep(backoff * (2 ** attempt))
                continue

            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error("TinyFish %s permanently failed for %s after %d attempts: %s",
                         extraction_type, url, attempt + 1, e)
            await _save_run({
                "id": run_id, "tinyfish_run_id": None,
                "job_type": extraction_type, "url": url, "goal_hash": goal_hash,
                "status": "failed", "error_type": last_error_type.value,
                "error_message": last_error_msg, "browser_profile": browser_profile,
                "items_extracted": 0, "duration_ms": duration_ms,
                "result_summary_json": json.dumps({}, default=str),
                "topic": topic, "retry_count": attempt,
                "created_at": datetime.now(UTC),
                "completed_at": datetime.now(UTC),
            })
            if event_callback:
                await event_callback("tinyfish.extraction.failed", {
                    "url": url,
                    "extraction_type": extraction_type,
                    "tinyfish_run_id": None,
                    "streaming_url": None,
                    "attempt": attempt + 1,
                    "duration_ms": duration_ms,
                    "error_type": last_error_type.value,
                    "error_message": last_error_msg,
                    "result_summary": {},
                })
            return []

    return []  # should not reach here


# =============================================================================
# Parsers
# =============================================================================

def _parse_result(result: dict, extraction_type: str, url: str = "") -> list[dict]:
    parsers = {
        "reviews": _parse_reviews,
        "discussions": _parse_discussions,
        "readme": _parse_readme,
        "stackoverflow": _parse_stackoverflow,
        "comparison": _parse_comparison,
        "category_discovery": _parse_category_discovery,
        "incumbent_gaps": _parse_incumbent_gaps,
        "forum_signals": _parse_forum_signals,
        "workflow_descriptions": _parse_workflow_descriptions,
        "github": _parse_github,
    }
    parser = parsers.get(extraction_type)
    return parser(result, url) if parser else []


def _parse_reviews(result: dict, url: str = "") -> list[dict]:
    """Parse Prompt B — Review Harvest results."""
    items = result.get("items", result.get("reviews", []))
    if not isinstance(items, list):
        items = [result] if "review_body" in result else []

    parsed = []
    for review in items:
        if not isinstance(review, dict):
            continue
        body = review.get("review_body", "") or ""
        if not body.strip():
            continue

        parts = [body]
        pros = review.get("pros", []) or []
        cons = review.get("cons", []) or []
        missing = review.get("missing_features", []) or []
        complaints = review.get("complaint_signals", []) or []
        persona_clues = review.get("persona_clues", []) or []
        workflow_clues = review.get("workflow_clues", []) or []

        if pros:
            parts.append(f"Pros: {', '.join(pros)}")
        if cons:
            parts.append(f"Cons: {', '.join(cons)}")
        if missing:
            parts.append(f"Missing features: {', '.join(missing)}")
        if complaints:
            parts.append(f"Complaints: {', '.join(complaints)}")

        text = "\n\n".join(parts)

        parsed.append({
            "source_id": _hash_id(body[:100], "review"),
            "url": url,
            "title": review.get("product_name", ""),
            "text": text.strip(),
            "product_name": review.get("product_name", ""),
            "persona_clues": persona_clues,
            "workflow_clues": workflow_clues,
        })
    return parsed


def _parse_category_discovery(result: dict, url: str = "") -> list[dict]:
    """Parse Prompt A — Category Discovery results."""
    pages = result.get("discovered_pages", [])
    if not isinstance(pages, list):
        return []

    parsed = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_url = page.get("url", "")
        title = page.get("title", "")
        if not page_url:
            continue
        parsed.append({
            "source_id": _hash_id(page_url, "cat"),
            "url": page_url,
            "title": title,
            "text": f"[{page.get('page_type', 'page')}] {title}: {page.get('reason_relevant', '')}",
            "page_type": page.get("page_type", ""),
            "product_name": page.get("product_name", ""),
            "category_name": page.get("category_name", ""),
        })
    return parsed


def _parse_incumbent_gaps(result: dict, url: str = "") -> list[dict]:
    """Parse Prompt C — Incumbent Gap results."""
    gaps = result.get("gaps", [])
    if not isinstance(gaps, list):
        return []

    parsed = []
    for gap in gaps:
        if not isinstance(gap, dict):
            continue
        failure_text = gap.get("failure_text", "") or ""
        if not failure_text.strip():
            continue

        product = gap.get("product_name", "") or ""
        failure_type = gap.get("failure_type", "") or ""
        workflow_clue = gap.get("workflow_clue", "") or ""
        persona_clue = gap.get("persona_clue", "") or ""

        parts = []
        if product:
            parts.append(f"Product: {product}")
        parts.append(f"Failure ({failure_type}): {failure_text}")
        if workflow_clue:
            parts.append(f"Workflow: {workflow_clue}")
        if persona_clue:
            parts.append(f"Persona: {persona_clue}")

        text = "\n".join(parts)

        parsed.append({
            "source_id": _hash_id(f"{product}_{failure_text[:50]}", "gap"),
            "url": url,
            "title": f"{product} - {failure_type}" if product else failure_type,
            "text": text,
            "product_name": product,
            "failure_type": failure_type,
            "persona_clues": [persona_clue] if persona_clue else [],
            "workflow_clues": [workflow_clue] if workflow_clue else [],
        })
    return parsed


def _parse_forum_signals(result: dict, url: str = "") -> list[dict]:
    """Parse Prompt E — Forum Deep Harvest results."""
    signals = result.get("signals", [])
    if not isinstance(signals, list):
        return []

    post = result.get("post", {}) if isinstance(result.get("post"), dict) else {}
    comments = result.get("comments", []) if isinstance(result.get("comments"), list) else []
    post_title = post.get("title", "") or ""
    post_body = post.get("body", "") or ""
    post_author = post.get("author", "") or ""

    parsed = []
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        text = sig.get("text", "") or ""
        if not text.strip() or len(text.strip()) < 10:
            continue

        signal_type = sig.get("signal_type", "pain") or "pain"
        persona_clue = sig.get("persona_clue", "") or ""
        workflow_clue = sig.get("workflow_clue", "") or ""
        evidence_quote = sig.get("evidence_quote", "") or ""
        tools_mentioned = sig.get("tools_mentioned", []) or []

        full_text = f"[{signal_type}] {text}"
        if evidence_quote:
            full_text += f"\nQuote: {evidence_quote}"
        if workflow_clue:
            full_text += f"\nWorkflow: {workflow_clue}"
        if persona_clue:
            full_text += f"\nPersona: {persona_clue}"
        if tools_mentioned:
            full_text += f"\nTools: {', '.join(str(item) for item in tools_mentioned)}"
        if post_title:
            full_text += f"\nPost: {post_title}"
        if post_author:
            full_text += f"\nAuthor: {post_author}"

        parsed.append({
            "source_id": _hash_id(text[:80], "forum"),
            "url": url,
            "title": post_title or f"{signal_type}: {text[:60]}",
            "text": full_text,
            "signal_type": signal_type,
            "evidence_quote": evidence_quote,
            "tools_mentioned": tools_mentioned,
            "post_body": post_body,
            "comment_count": len(comments),
            "persona_clues": [persona_clue] if persona_clue else [],
            "workflow_clues": [workflow_clue] if workflow_clue else [],
        })
    return parsed


def _parse_comparison(result: dict, url: str = "") -> list[dict]:
    """Parse Prompt D — Comparison results."""
    comparisons = result.get("comparisons", [])
    if not isinstance(comparisons, list):
        return []

    parsed = []
    for comp in comparisons:
        if not isinstance(comp, dict):
            continue
        product = comp.get("product_name", "") or ""
        if not product:
            continue

        parts = [f"Product: {product}"]
        weaknesses = comp.get("weaknesses", comp.get("cons", [])) or []
        missing = comp.get("missing_capabilities", comp.get("limitations", [])) or []
        strengths = comp.get("strengths", comp.get("pros", [])) or []
        persona_clues = comp.get("persona_clues", []) or []
        workflow_clues = comp.get("workflow_clues", []) or []

        if weaknesses:
            parts.append(f"Weaknesses: {'; '.join(weaknesses)}")
        if missing:
            parts.append(f"Missing capabilities: {'; '.join(missing)}")
        if strengths:
            parts.append(f"Strengths: {'; '.join(strengths)}")

        text = "\n".join(parts)

        parsed.append({
            "source_id": _hash_id(f"comp_{product[:30]}", "comp"),
            "url": url,
            "title": f"{product} - comparison",
            "text": text,
            "product_name": product,
            "persona_clues": persona_clues,
            "workflow_clues": workflow_clues,
        })
    return parsed


def _parse_discussions(result: dict, url: str = "") -> list[dict]:
    posts = result.get("posts", [])
    if not isinstance(posts, list):
        posts = [result] if "body" in result else []
    parsed = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        body = post.get("body", "") or ""
        if not body.strip():
            continue
        title = post.get("title") or ""
        text = f"{title}\n\n{body}" if title else body
        replies = post.get("replies", []) or []
        if replies:
            text += "\n\nReplies:\n" + "\n---\n".join(str(r) for r in replies[:5])
        parsed.append({
            "source_id": _hash_id(body[:100], "disc"),
            "url": post.get("url", url),
            "title": title,
            "text": text.strip(),
            "author": post.get("author", ""),
            "date": post.get("date", ""),
        })
    return parsed


def _parse_readme(result: dict, url: str = "") -> list[dict]:
    parsed = []
    repo_name = result.get("repo_name", "")
    signal_fields = [
        ("limitations", "limitation"), ("known_issues", "known_issue"),
        ("missing_features", "missing_feature"), ("pain_signals_from_readme", "readme_pain"),
        ("workarounds_mentioned", "readme_workaround"),
    ]
    for field, signal_type in signal_fields:
        items = result.get(field, [])
        if not isinstance(items, list):
            continue
        for item_text in items:
            if not item_text or not isinstance(item_text, str) or len(item_text.strip()) < 10:
                continue
            parsed.append({
                "source_id": _hash_id(f"{repo_name}_{item_text[:50]}", "readme"),
                "url": url,
                "title": f"{repo_name} - {signal_type}",
                "text": f"[{repo_name}] {signal_type}: {item_text}",
                "repo": repo_name,
                "signal_type": signal_type,
            })
    for alt in (result.get("alternatives_mentioned", []) if isinstance(result.get("alternatives_mentioned"), list) else []):
        if alt and isinstance(alt, str) and len(alt.strip()) >= 5:
            parsed.append({
                "source_id": _hash_id(f"{repo_name}_alt_{alt[:30]}", "readme"),
                "url": url, "title": f"{repo_name} - alternative",
                "text": f"[{repo_name}] alternative: {alt}", "repo": repo_name, "signal_type": "alternative",
            })
    return parsed


def _parse_stackoverflow(result: dict, url: str = "") -> list[dict]:
    questions = result.get("questions", [])
    if not isinstance(questions, list):
        return []
    parsed = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        title = q.get("title", "") or ""
        body = q.get("body", "") or ""
        if not (title or body):
            continue
        text = title
        if body:
            text += f"\n\n{body}"
        top_answer = q.get("top_answer", "") or ""
        if top_answer:
            text += f"\n\nTop Answer:\n{top_answer}"
        tags = q.get("tags", []) or []
        if tags:
            text += f"\n\nTags: {', '.join(tags)}"
        parsed.append({
            "source_id": _hash_id(f"so_{title[:50]}", "so"),
            "url": q.get("url", url),
            "title": title,
            "text": text.strip(),
            "votes": q.get("votes", 0),
        })
    return parsed


def _parse_workflow_descriptions(result: dict, url: str = "") -> list[dict]:
    """Parse Prompt F — Workflow Description Harvest results."""
    workflows = result.get("workflows", [])
    if not isinstance(workflows, list):
        return []

    parsed = []
    for wf in workflows:
        if not isinstance(wf, dict):
            continue
        name = wf.get("workflow_name", "") or ""
        description = wf.get("description", "") or ""
        if not (name or description):
            continue

        steps = wf.get("steps", []) or []
        tools_used = wf.get("tools_used", []) or []
        pain_points = wf.get("pain_points", []) or []
        persona_clue = wf.get("persona_clue", "") or ""
        frequency = wf.get("frequency", "") or ""

        parts = []
        if name:
            parts.append(f"Workflow: {name}")
        if description:
            parts.append(description)
        if steps:
            parts.append(f"Steps: {' -> '.join(steps)}")
        if tools_used:
            parts.append(f"Tools: {', '.join(tools_used)}")
        if pain_points:
            parts.append(f"Pain points: {'; '.join(pain_points)}")
        if frequency:
            parts.append(f"Frequency: {frequency}")

        text = "\n".join(parts)

        parsed.append({
            "source_id": _hash_id(f"wf_{name[:40]}_{description[:30]}", "wf"),
            "url": url,
            "title": name or description[:60],
            "text": text,
            "workflow_name": name,
            "tools_used": tools_used,
            "pain_points": pain_points,
            "persona_clues": [persona_clue] if persona_clue else [],
            "workflow_clues": [name] if name else [],
        })
    return parsed


def _parse_github(result: dict, url: str = "") -> list[dict]:
    """Parse GitHub intelligence results.

    Supports both the current GITHUB_INTELLIGENCE_GOAL shape and older
    field-based outputs so we do not silently discard valid TinyFish results.
    """
    items = result.get("items", [])
    if not isinstance(items, list):
        return []

    parsed = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = item.get("title", "") or ""
        item_url = item.get("url", url) or url
        item_type = item.get("item_type", "repo") or "repo"
        signal_type = item.get("signal_type", "") or ""
        text_value = item.get("text", "") or ""
        tools_mentioned = item.get("tools_mentioned", []) or []
        alternatives_mentioned = item.get("alternatives_mentioned", []) or []
        stars_or_comments = item.get("stars_or_comments")

        parts = [f"[{item_type}] {title}"]
        if signal_type:
            parts.append(f"Signal: {signal_type}")
        if text_value:
            parts.append(text_value)

        # Backward-compatible handling for older result shapes.
        for field in ("pain_signals", "limitations", "feature_requests", "workarounds"):
            values = item.get(field, []) or []
            if values:
                parts.append(f"{field.replace('_', ' ').title()}: {'; '.join(values)}")
        if stars_or_comments is not None:
            parts.append(f"Engagement: {stars_or_comments}")
        if tools_mentioned:
            parts.append(f"Tools mentioned: {', '.join(str(v) for v in tools_mentioned)}")
        if alternatives_mentioned:
            parts.append(f"Alternatives: {', '.join(str(v) for v in alternatives_mentioned)}")

        text = "\n".join(parts)
        if len(text.strip()) < 15:
            continue

        parsed.append({
            "source_id": _hash_id(f"gh_{title[:50]}_{item_type}", "gh"),
            "url": item_url,
            "title": title,
            "text": text,
            "item_type": item_type,
            "signal_type": signal_type,
            "persona_clues": [],
            "workflow_clues": [],
        })
    return parsed


# ─── Focused Extraction (using client.agent.run) ───


async def run_focused_extraction(
    url: str,
    prompt_name: str,
    topic: str,
    browser_profile: str | None = None,
    max_retries: int = 1,
    event_callback=None,
) -> list[dict]:
    """Run a focused extraction using client.agent.run() (blocking).

    This is the new extraction path that uses short, focused prompts
    and returns results reliably (unlike the SSE streaming path)."""
    from app.services.ingest.extraction_parser import parse_signal_result, parse_url_discovery_result
    from app.services.ingest.extraction_prompts import get_prompt

    goal = get_prompt(prompt_name, topic)

    # --- extraction cache: skip TinyFish call on retry if we already have results ---
    cached = get_cached_extraction(url, prompt_name)
    if cached is not None:
        logger.info("Using cached extraction (%d items) for %s [%s]", len(cached), url, prompt_name)
        return cached

    run_id = str(uuid.uuid4())
    start = time.monotonic()
    goal_hash = md5(goal.encode()).hexdigest()[:16]
    profile = browser_profile or _get_browser_profile()
    last_error_msg = ""

    for attempt in range(max_retries + 1):
        client = _get_client()
        try:
            async with client:
                kwargs = {"url": url, "goal": goal}
                if profile:
                    kwargs["browser_profile"] = profile

                logger.info("TinyFish focused %s on %s (attempt %d)", prompt_name, url, attempt + 1)
                response = await client.agent.run(**kwargs)

                duration_ms = int((time.monotonic() - start) * 1000)

                if response.status.value != "COMPLETED" or not response.result:
                    err_msg = str(response.error) if response.error else "No result"
                    last_error_msg = err_msg
                    logger.warning("TinyFish focused %s failed for %s (attempt %d, %dms): %s",
                                   prompt_name, url, attempt + 1, duration_ms, err_msg)

                    if attempt < max_retries:
                        await asyncio.sleep(3.0 * (2 ** attempt))
                        continue

                    await _save_run({
                        "id": run_id, "tinyfish_run_id": response.run_id,
                        "job_type": f"focused_{prompt_name}", "url": url, "goal_hash": goal_hash,
                        "status": "failed", "error_type": "extraction_failed",
                        "error_message": err_msg, "browser_profile": profile,
                        "items_extracted": 0, "duration_ms": duration_ms,
                        "topic": topic, "retry_count": attempt,
                        "created_at": datetime.now(UTC),
                        "completed_at": datetime.now(UTC),
                    })
                    return []

                # parse result
                result_data = response.result
                if prompt_name == "url_discovery":
                    items = parse_url_discovery_result(result_data)
                else:
                    items = parse_signal_result(result_data, url)

                logger.info("TinyFish focused %s extracted %d items from %s (run=%s, %dms)",
                            prompt_name, len(items), url, response.run_id, duration_ms)

                await _save_run({
                    "id": run_id, "tinyfish_run_id": response.run_id,
                    "job_type": f"focused_{prompt_name}", "url": url, "goal_hash": goal_hash,
                    "status": "completed", "error_type": None, "error_message": None,
                    "browser_profile": profile,
                    "items_extracted": len(items), "duration_ms": duration_ms,
                    "topic": topic, "retry_count": attempt,
                    "created_at": datetime.now(UTC),
                    "completed_at": datetime.now(UTC),
                })

                if event_callback:
                    await event_callback("tinyfish.focused.completed", {
                        "url": url, "prompt": prompt_name,
                        "item_count": len(items), "duration_ms": duration_ms,
                    })

                # cache successful extraction for pipeline retries
                if items:
                    cache_extraction(url, prompt_name, items, topic)

                return items

        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            last_error_msg = str(exc)
            logger.warning("TinyFish focused %s error for %s (attempt %d, %dms): %s",
                           prompt_name, url, attempt + 1, duration_ms, exc)

            if attempt < max_retries:
                await asyncio.sleep(3.0 * (2 ** attempt))
                continue

            await _save_run({
                "id": run_id, "tinyfish_run_id": None,
                "job_type": f"focused_{prompt_name}", "url": url, "goal_hash": goal_hash,
                "status": "failed", "error_type": "exception",
                "error_message": last_error_msg, "browser_profile": profile,
                "items_extracted": 0, "duration_ms": duration_ms,
                "topic": topic, "retry_count": attempt,
                "created_at": datetime.now(UTC),
                "completed_at": datetime.now(UTC),
            })
            return []

    return []
