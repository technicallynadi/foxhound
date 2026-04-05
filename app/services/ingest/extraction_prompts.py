"""Focused TinyFish extraction prompts.

Each prompt is short, single-purpose, and returns a unified schema.
All signal prompts return: {items: [{text, signal_type, tool_mentioned, evidence_quote}]}
URL discovery returns: {urls: [{url, title, comment_count}]}
"""

PROMPTS = {
    "url_discovery": (
        "Find ALL discussion thread URLs on this page related to {topic}.\n"
        'Return JSON: {{"urls": [{{"url": "full URL", "title": "thread title", "comment_count": number_or_null}}]}}\n'
        "Only return URLs that link to individual threads, posts, or questions — not other listing pages. Read the entire page and include every relevant thread."
    ),
    "pain": (
        "Read the ENTIRE page including ALL comments. Extract every user complaint and frustration about {topic}.\n"
        "Return JSON matching this exact structure:\n"
        '{{"items": [{{"text": "Users cannot cancel a running workflow without admin access", "signal_type": "pain", "tool_mentioned": "GitHub Actions", "breakpoint": "cancelling a running workflow requires admin permissions", "evidence_quote": "I have to ask my manager to cancel my own CI runs every time"}}]}}\n'
        "Scroll through all comments. Include every distinct complaint. For tool_mentioned, if the user doesn't name a specific tool, use the primary tool discussed on the page. Never return null for tool_mentioned."
    ),
    "workaround": (
        "Read the ENTIRE page including ALL comments. Extract every manual workaround, hack, and makeshift solution people describe related to {topic}.\n"
        'Return JSON: {{"items": [{{"text": "description of the workaround", "signal_type": "workaround", "tool_mentioned": "tool being worked around or null", "evidence_quote": "exact quote from page"}}]}}\n'
        "Scroll through all comments. Include every workaround — spreadsheets, scripts, copy-paste, custom tools. Do not skip any."
    ),
    "tool_complaint": (
        "Read the ENTIRE page including ALL comments. Extract every complaint about specific software tools related to {topic}.\n"
        'Return JSON: {{"items": [{{"text": "what is wrong with the tool", "signal_type": "incumbent_failure", "tool_mentioned": "the tool being complained about", "evidence_quote": "exact quote from page"}}]}}\n'
        "Scroll through all comments. Only include items that name a specific tool AND describe a specific failure. Include every distinct complaint."
    ),
    "request": (
        "Read the ENTIRE page including ALL comments. Extract every feature request, wish, and unmet need related to {topic}.\n"
        'Return JSON: {{"items": [{{"text": "what the user wants that does not exist", "signal_type": "request", "tool_mentioned": "tool the request is about or null", "evidence_quote": "exact quote from page"}}]}}\n'
        'Scroll through all comments. Look for "wish there was", "looking for", "need a tool that". Include every request.'
    ),
    "workflow": (
        "Read the ENTIRE page including ALL comments. Extract every step-by-step workflow or process people describe related to {topic}.\n"
        'Return JSON: {{"items": [{{"text": "description of the workflow including steps", "signal_type": "workflow", "tool_mentioned": "primary tool used or null", "evidence_quote": "exact quote from page"}}]}}\n'
        "Scroll through all comments. Focus on concrete multi-step processes. Include every workflow described."
    ),
    "discover_projects": (
        "Read this page and extract every project, tool, or repository listed related to {topic}.\n"
        "Return JSON matching this exact structure:\n"
        '{{"items": [{{"text": "Brief description of what this project does and why it was built", "signal_type": "workflow", "tool_mentioned": "project or repo name", "evidence_quote": "the project tagline or first sentence of its README"}}]}}\n'
        "For each project, explain what problem it solves and why someone built it. Include stars count if visible."
    ),
    "repo_readme": (
        "Read the README of this repository. Extract what problem it solves, who it's for, and any pain points it addresses.\n"
        "Return JSON matching this exact structure:\n"
        '{{"items": [{{"text": "What this project does and what pain it solves", "signal_type": "workflow", "tool_mentioned": "the project name", "evidence_quote": "key sentence from the README about the problem"}}]}}\n'
        "Focus on: what was broken before this existed, who uses it, what alternatives exist."
    ),
    "issue_list": (
        "Read this GitHub issues page. Extract the top issues by reactions or comments.\n"
        "Return JSON matching this exact structure:\n"
        '{{"urls": [{{"url": "full issue URL", "title": "issue title", "comment_count": number_or_null}}]}}\n'
        "Sort by most reactions or most comments first. Only include open issues. Maximum 10 issues."
    ),
    "full_page": (
        "Extract ALL text content from this page. Include the title, body text, all comments, all replies, all code blocks, and all user-generated content.\n"
        'Return JSON: {{"title": "page title", "body": "the full text of the article or README", "comments": ["comment 1 full text", "comment 2 full text", ...]}}\n'
        "Do not summarize. Include every piece of text on the page."
    ),
}

# SO-specific prompt that works with Q&A format
PROMPTS["so_extract"] = (
    "Read the question and ALL answers on this Stack Overflow page related to {topic}.\n"
    "Extract the original problem from the question, and pain points, workarounds, and tool complaints from the highest-voted answers and comments.\n"
    'Return JSON: {{"items": [{{"text": "the problem or pain point described", "signal_type": "pain or workaround or request", "tool_mentioned": "tool name or null", "evidence_quote": "exact quote from the question or answer"}}]}}\n'
    "Focus on the question's core problem and the top answers. Include workarounds people describe in their answers."
)

# Which prompts to run per source type
SOURCE_PROMPT_MAP = {
    "github": ["pain", "workaround", "request"],
    "lobsters": ["pain", "tool_complaint"],
    "discourse": ["pain", "workaround"],
    "blog": ["workflow", "pain"],
    "hackernews": ["pain", "tool_complaint"],
    "stackoverflow": ["so_extract"],
    "reddit": ["pain", "workaround"],
    "g2": ["tool_complaint"],
    "capterra": ["tool_complaint"],
    "canny": ["request"],
    "default": ["pain"],
}


def get_prompt(name: str, topic: str) -> str:
    """Get a formatted prompt by name."""
    template = PROMPTS.get(name)
    if not template:
        raise ValueError(f"Unknown prompt: {name}. Available: {list(PROMPTS.keys())}")
    return template.format(topic=topic)


def get_prompts_for_source(source_type: str) -> list[str]:
    """Get the list of prompt names to run for a given source type."""
    return SOURCE_PROMPT_MAP.get(source_type, SOURCE_PROMPT_MAP["default"])


def classify_source_type(url: str) -> str:
    """Classify a URL into a source type."""
    lowered = url.lower()
    if "reddit.com" in lowered:
        return "reddit"
    if "news.ycombinator.com" in lowered or "hn.algolia.com" in lowered:
        return "hackernews"
    if "github.com" in lowered:
        return "github"
    if "stackoverflow.com" in lowered or "stackexchange.com" in lowered:
        return "stackoverflow"
    if "g2.com" in lowered:
        return "g2"
    if "capterra.com" in lowered:
        return "capterra"
    return "default"
