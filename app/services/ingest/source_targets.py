"""Source targets for TinyFish extraction.

Maps topics/verticals to direct content page URLs.
TinyFish visits these pages directly — no Google search needed.

Phase A: TinyFish visits listing URLs → discovers thread/content URLs
Phase B: TinyFish visits content URLs → extracts signals
"""

import logging
import re

logger = logging.getLogger(__name__)


# ─── Source Registry ───
# Each source has: url_pattern, source_type, browser_profile, signal_types

SOURCES = {
    # Tier 1 — Proven/High Signal
    "github_issues": {
        "url_pattern": "https://github.com/search?q={query}+is:issue+is:open+sort:comments&type=issues",
        "source_type": "github",
        "browser_profile": "lite",
        "signal_types": ["pain", "workaround", "request"],
        "phase": "listing",
    },
    "github_discussions": {
        "url_pattern": "https://github.com/search?q={query}+is:open&type=discussions",
        "source_type": "github",
        "browser_profile": "lite",
        "signal_types": ["pain", "request", "workflow"],
        "phase": "listing",
    },
    # Tier 1 — Feature Requests (public, vote-weighted, sorted by most upvoted)
    "github_feature_requests": {
        "url_pattern": "https://github.com/search?q={query}+label%3Aenhancement+OR+label%3A%22feature+request%22+is:open+sort:reactions-%2B1-desc&type=issues",
        "source_type": "github",
        "browser_profile": "lite",
        "signal_types": ["request", "pain"],
        "phase": "listing",
    },
    "github_ideas": {
        "url_pattern": "https://github.com/search?q={query}+category%3AIdeas+OR+category%3A%22Feature+Requests%22&type=discussions",
        "source_type": "github",
        "browser_profile": "lite",
        "signal_types": ["request"],
        "phase": "listing",
    },
    # Tier 1 — GitHub Trends (what new tools people are building = signals unmet needs)
    "github_trending_weekly": {
        "url_pattern": "https://github.com/trending?since=weekly&spoken_language_code=en",
        "source_type": "github",
        "browser_profile": "lite",
        "signal_types": ["market_pull"],
        "phase": "content",
    },
    "github_trending_daily": {
        "url_pattern": "https://github.com/trending?since=daily&spoken_language_code=en",
        "source_type": "github",
        "browser_profile": "lite",
        "signal_types": ["market_pull"],
        "phase": "content",
    },
    # Tier 1 — Canny feature boards via Google (direct access is SPA-gated)
    # Google indexes Canny pages and shows titles + descriptions in snippets
    "canny_google": {
        "url_pattern": "https://www.google.com/search?q=site:canny.io+{short_query}+feature+request",
        "source_type": "feature_board",
        "browser_profile": "stealth",
        "signal_types": ["request"],
        "phase": "listing",
        "query_strategy": "short",
    },
    # Tier 1 — Discourse Feature Request categories (direct, no login)
    "discourse_fly_features": {
        "url_pattern": "https://community.fly.io/c/feature-requests/32",
        "source_type": "discourse",
        "browser_profile": "lite",
        "signal_types": ["request"],
        "phase": "listing",
    },
    "discourse_obsidian_features": {
        "url_pattern": "https://forum.obsidian.md/c/feature-requests/8",
        "source_type": "discourse",
        "browser_profile": "lite",
        "signal_types": ["request"],
        "phase": "listing",
    },
    "discourse_netlify_features": {
        "url_pattern": "https://answers.netlify.com/c/feature-requests/41",
        "source_type": "discourse",
        "browser_profile": "lite",
        "signal_types": ["request"],
        "phase": "listing",
    },
    "discourse_ghost_features": {
        "url_pattern": "https://forum.ghost.org/c/feature-requests/8",
        "source_type": "discourse",
        "browser_profile": "lite",
        "signal_types": ["request"],
        "phase": "listing",
    },
    "discourse_n8n_features": {
        "url_pattern": "https://community.n8n.io/c/feature-requests/6",
        "source_type": "discourse",
        "browser_profile": "lite",
        "signal_types": ["request"],
        "phase": "listing",
    },
    # Tier 1 — Developer Communities
    "lobsters": {
        "url_pattern": "https://lobste.rs/search?q={query}&what=comments&order=relevance",
        "source_type": "lobsters",
        "browser_profile": "lite",
        "signal_types": ["pain", "tool_complaint"],
        "phase": "content",
    },
    # Tier 1 — Discourse Forums (append .json for API access)
    "discourse_hashicorp": {
        "url_pattern": "https://discuss.hashicorp.com/search?q={query}",
        "source_type": "discourse",
        "browser_profile": "lite",
        "signal_types": ["pain", "workaround"],
        "phase": "listing",
        "verticals": ["devtools", "devops"],
    },
    "discourse_kubernetes": {
        "url_pattern": "https://discuss.kubernetes.io/search?q={query}",
        "source_type": "discourse",
        "browser_profile": "lite",
        "signal_types": ["pain", "workaround"],
        "phase": "listing",
        "verticals": ["devtools", "devops"],
    },
    "discourse_fly": {
        "url_pattern": "https://community.fly.io/search?q={query}",
        "source_type": "discourse",
        "browser_profile": "lite",
        "signal_types": ["pain", "workaround"],
        "phase": "listing",
        "verticals": ["devtools"],
    },
    # Tier 2 — Blog/Content Platforms
    "devto": {
        "url_pattern": "https://dev.to/search?q={query}",
        "source_type": "blog",
        "browser_profile": "lite",
        "signal_types": ["workflow", "pain"],
        "phase": "listing",
    },
    "hashnode": {
        "url_pattern": "https://hashnode.com/search?q={query}",
        "source_type": "blog",
        "browser_profile": "lite",
        "signal_types": ["workflow", "pain"],
        "phase": "listing",
    },
    "medium": {
        "url_pattern": "https://medium.com/search?q={query}",
        "source_type": "blog",
        "browser_profile": "lite",
        "signal_types": ["workflow", "pain"],
        "phase": "listing",
    },
    # Tier 2 — Q&A
    "stackoverflow": {
        "url_pattern": "https://stackoverflow.com/search?q={query}&tab=votes",
        "source_type": "stackoverflow",
        "browser_profile": "lite",
        "signal_types": ["so_extract"],
        "phase": "listing",
    },
    "hackernews": {
        "url_pattern": "https://hn.algolia.com/?q={query}&sort=byPopularity&type=story",
        "source_type": "hackernews",
        "browser_profile": "lite",
        "signal_types": ["pain", "tool_complaint"],
        "phase": "listing",
    },
    # Tier 2 — Feature Request Boards
    "canny": {
        "url_pattern": "https://www.google.com/search?q=site:canny.io+{query}",
        "source_type": "canny",
        "browser_profile": "stealth",
        "signal_types": ["request"],
        "phase": "listing",
    },
    # Tier 2 — Curated Lists
    "awesome_lists": {
        "url_pattern": "https://github.com/search?q=awesome+{query}&type=repositories&sort=stars",
        "source_type": "github",
        "browser_profile": "lite",
        "signal_types": ["workflow"],
        "phase": "listing",
    },
    # Tier 2 — Product Launches & Market Signals
    # NOTE: These sites need simplified queries — use {short_query} (1-2 keywords)
    # or {tool} (first detected tool name) instead of the full query slug.
    "producthunt": {
        "url_pattern": "https://www.producthunt.com/search?q={short_query}",
        "source_type": "producthunt",
        "browser_profile": "stealth",
        "signal_types": ["market_pull", "pain", "migration"],
        "phase": "listing",
        "query_strategy": "short",
    },
    "producthunt_topics": {
        "url_pattern": "https://www.producthunt.com/topics/{topic_slug}",
        "source_type": "producthunt",
        "browser_profile": "stealth",
        "signal_types": ["market_pull"],
        "phase": "listing",
        "query_strategy": "topic_slug",
    },
    "indiehackers": {
        "url_pattern": "https://www.indiehackers.com/search?q={short_query}",
        "source_type": "indiehackers",
        "browser_profile": "lite",
        "signal_types": ["market_pull", "pain", "operator_practice"],
        "phase": "listing",
        "query_strategy": "short",
    },
    # Tier 2 — Developer Newsletters & Blogs
    "substack": {
        "url_pattern": "https://substack.com/search/{short_query}",
        "source_type": "newsletter",
        "browser_profile": "lite",
        "signal_types": ["workflow", "operator_practice"],
        "phase": "listing",
        "query_strategy": "short",
    },
    # Tier 2 — Investor / YC Signals
    "yc_companies": {
        "url_pattern": "https://www.ycombinator.com/companies?q={short_query}",
        "source_type": "investor",
        "browser_profile": "lite",
        "signal_types": ["market_pull"],
        "phase": "listing",
        "query_strategy": "short",
    },
    "wellfound_startups": {
        "url_pattern": "https://wellfound.com/search?q={short_query}",
        "source_type": "investor",
        "browser_profile": "stealth",
        "signal_types": ["market_pull"],
        "phase": "listing",
        "query_strategy": "short",
    },
    # Tier 2 — Tool Comparison / Migration
    "stackshare": {
        "url_pattern": "https://stackshare.io/search/q={short_query}",
        "source_type": "comparison",
        "browser_profile": "lite",
        "signal_types": ["migration", "market_pull"],
        "phase": "listing",
        "query_strategy": "short",
    },
    # Tier 2 — Social / Real-time signals
    # X/Twitter requires login — use Google site:x.com as proxy to find tweets
    "twitter_pain": {
        "url_pattern": "https://www.google.com/search?q=site:x.com+{short_query}+broken+OR+bug+OR+frustrating+OR+%22switched+to%22",
        "source_type": "twitter",
        "browser_profile": "stealth",
        "signal_types": ["pain", "migration"],
        "phase": "content",
        "query_strategy": "short",
    },
    "twitter_alternatives": {
        "url_pattern": "https://www.google.com/search?q=site:x.com+{short_query}+alternative+OR+%22looking+for%22+OR+%22moved+to%22",
        "source_type": "twitter",
        "browser_profile": "stealth",
        "signal_types": ["migration", "market_pull"],
        "phase": "content",
        "query_strategy": "short",
    },
    # Tier 3 — Protected Sites (stealth + proxy)
    "reddit": {
        "url_pattern": "https://www.reddit.com/search/?q={query}&sort=relevance&t=year",
        "source_type": "reddit",
        "browser_profile": "stealth",
        "signal_types": ["pain", "workaround"],
        "phase": "listing",
    },
    "g2_reviews": {
        "url_pattern": "https://www.g2.com/search?query={query}",
        "source_type": "g2",
        "browser_profile": "stealth",
        "signal_types": ["tool_complaint"],
        "phase": "listing",
    },
}

# Subreddits by vertical (for direct thread discovery)
SUBREDDITS = {
    "devtools": ["r/programming", "r/webdev", "r/devops", "r/sysadmin", "r/ExperiencedDevs", "r/selfhosted"],
    "ai_developer_tooling": ["r/LocalLLaMA", "r/MachineLearning", "r/ChatGPTPro", "r/ClaudeAI"],
    "data": ["r/dataengineering", "r/datascience", "r/analytics"],
    "security": ["r/netsec", "r/cybersecurity", "r/AskNetsec"],
    "frontend": ["r/webdev", "r/reactjs", "r/nextjs", "r/frontend"],
    "nocode": ["r/nocode", "r/lowcode", "r/zapier", "r/Airtable"],
    "startups": ["r/startups", "r/SaaS", "r/Entrepreneur", "r/indiebiz"],
    "default": ["r/programming", "r/webdev", "r/SaaS", "r/startups", "r/selfhosted"],
}

# Known GitHub repos with high-signal issues per vertical
GITHUB_REPOS = {
    "devtools": ["actions/runner", "docker/compose", "hashicorp/terraform", "vercel/next.js"],
    "ai_developer_tooling": [
        "langchain-ai/langchain",
        "openai/openai-python",
        "anthropics/anthropic-sdk-python",
        "run-llama/llama_index",
    ],
    "data": ["apache/airflow", "dbt-labs/dbt-core", "apache/spark"],
    "default": [],
}

# GitHub trending and discovery patterns
GITHUB_DISCOVERY = {
    "trending": "https://github.com/trending?since=weekly&spoken_language_code=en",
    "trending_topic": "https://github.com/trending/{topic}?since=weekly",
    "most_starred": "https://github.com/search?q={query}+stars:>100&sort=stars&type=repositories",
    "recently_created": "https://github.com/search?q={query}+created:>2026-01-01&sort=stars&type=repositories",
}


def get_source_targets(topic: str, vertical: str | None = None, budget: int = 10) -> list[dict]:
    """Get prioritized source targets for extraction.

    Sources are query-driven, not sector-locked.  The topic drives what gets
    searched everywhere — verticals only add *bonus* targets (known repos,
    niche subreddits) on top of the universal set.

    Returns a flat list of targets, ordered by priority, up to budget * 2
    (since not all listing pages will yield content URLs).
    """
    v = vertical or _guess_vertical(topic) or "default"
    slug = _topic_to_slug(topic)
    qv = _build_query_variants(topic)
    targets = []

    # Priority 1: Known GitHub repos for this vertical (bonus, not exclusive)
    repos = GITHUB_REPOS.get(v, GITHUB_REPOS["default"])
    for repo in repos[:3]:
        targets.append(
            {
                "url": f"https://github.com/{repo}/issues?q=is:open+sort:comments",
                "source_type": "github",
                "browser_profile": "lite",
                "prompt_names": ["pain", "workaround", "request"],
                "phase": "listing",
                "priority": 1,
            }
        )

    # Priority 2: GitHub search (issues + starred + new + TRENDING)
    targets.append(
        {
            "url": SOURCES["github_issues"]["url_pattern"].format(query=slug),
            "source_type": "github",
            "browser_profile": "lite",
            "prompt_names": ["issue_list"],
            "phase": "listing",
            "priority": 2,
        }
    )
    targets.append(
        {
            "url": GITHUB_DISCOVERY["most_starred"].format(query=slug),
            "source_type": "github",
            "browser_profile": "lite",
            "prompt_names": ["discover_projects"],
            "phase": "content",
            "priority": 2,
        }
    )
    targets.append(
        {
            "url": GITHUB_DISCOVERY["recently_created"].format(query=slug),
            "source_type": "github",
            "browser_profile": "lite",
            "prompt_names": ["discover_projects"],
            "phase": "content",
            "priority": 2,
        }
    )
    # GitHub trending — catches new tools people are building (signals unmet needs)
    targets.append(
        {
            "url": GITHUB_DISCOVERY["trending"],
            "source_type": "github",
            "browser_profile": "lite",
            "prompt_names": ["discover_projects"],
            "phase": "content",
            "priority": 2,
        }
    )
    # Topic-specific trending (if topic maps to a GitHub topic slug)
    topic_slug = slug.replace("+", "-").lower()
    if topic_slug:
        targets.append(
            {
                "url": GITHUB_DISCOVERY["trending_topic"].format(topic=topic_slug),
                "source_type": "github",
                "browser_profile": "lite",
                "prompt_names": ["discover_projects"],
                "phase": "content",
                "priority": 2,
            }
        )

    # Priority 3: Feature requests (GitHub + Canny via Google)
    targets.append(
        {
            "url": SOURCES["github_feature_requests"]["url_pattern"].format(query=slug),
            "source_type": "github",
            "browser_profile": "lite",
            "prompt_names": ["request", "pain"],
            "phase": "listing",
            "priority": 3,
        }
    )
    targets.append(
        {
            "url": SOURCES["github_ideas"]["url_pattern"].format(query=slug),
            "source_type": "github",
            "browser_profile": "lite",
            "prompt_names": ["request"],
            "phase": "listing",
            "priority": 3,
        }
    )
    # Canny boards via Google site search (direct access is SPA-gated)
    canny_url = _format_source_url(SOURCES["canny_google"], qv)
    if canny_url:
        targets.append(
            {
                "url": canny_url,
                "source_type": "feature_board",
                "browser_profile": "stealth",
                "prompt_names": ["request"],
                "phase": "listing",
                "priority": 3,
            }
        )

    # Priority 4: Lobsters
    targets.append(
        {
            "url": SOURCES["lobsters"]["url_pattern"].format(query=slug),
            "source_type": "lobsters",
            "browser_profile": "lite",
            "prompt_names": ["pain", "tool_complaint"],
            "phase": "content",
            "priority": 4,
        }
    )

    # Priority 5: Discourse forums — ALL forums + dedicated feature request categories
    for key, source in SOURCES.items():
        if source["source_type"] == "discourse":
            targets.append(
                {
                    "url": source["url_pattern"].format(query=slug),
                    "source_type": "discourse",
                    "browser_profile": "lite",
                    "prompt_names": source["signal_types"],
                    "phase": "listing",
                    "priority": 4,
                }
            )

    # Priority 5: Blog platforms + newsletters + engineering blogs
    for platform in ["devto", "hashnode", "medium"]:
        targets.append(
            {
                "url": SOURCES[platform]["url_pattern"].format(query=slug),
                "source_type": "blog",
                "browser_profile": "lite",
                "prompt_names": ["workflow", "pain"],
                "phase": "listing",
                "priority": 5,
            }
        )
    # Engineering blogs matched by topic
    from app.services.ingest.engineering_blogs import get_blog_urls_for_topic

    for blog_url in get_blog_urls_for_topic(topic):
        targets.append(
            {
                "url": blog_url["url"],
                "source_type": "engineering_blog",
                "browser_profile": "lite",
                "prompt_names": ["workflow", "operator_practice"],
                "phase": "content",
                "priority": 5,
            }
        )
    substack_url = _format_source_url(SOURCES["substack"], qv)
    if substack_url:
        targets.append(
            {
                "url": substack_url,
                "source_type": "newsletter",
                "browser_profile": "lite",
                "prompt_names": ["workflow", "operator_practice"],
                "phase": "listing",
                "priority": 5,
            }
        )

    # Priority 6: HN, SO, and Product Hunt
    targets.append(
        {
            "url": SOURCES["hackernews"]["url_pattern"].format(query=slug),
            "source_type": "hackernews",
            "browser_profile": "lite",
            "prompt_names": ["pain", "tool_complaint"],
            "phase": "listing",
            "priority": 6,
        }
    )
    targets.append(
        {
            "url": SOURCES["stackoverflow"]["url_pattern"].format(query=slug),
            "source_type": "stackoverflow",
            "browser_profile": "lite",
            "prompt_names": ["so_extract"],
            "phase": "listing",
            "priority": 6,
        }
    )
    # Product Hunt — search with short keywords + browse topic category
    ph_search_url = _format_source_url(SOURCES["producthunt"], qv)
    if ph_search_url:
        targets.append(
            {
                "url": ph_search_url,
                "source_type": "producthunt",
                "browser_profile": "stealth",
                "prompt_names": ["market_pull", "pain"],
                "phase": "listing",
                "priority": 6,
            }
        )
    ph_topic_url = _format_source_url(SOURCES["producthunt_topics"], qv)
    if ph_topic_url:
        targets.append(
            {
                "url": ph_topic_url,
                "source_type": "producthunt",
                "browser_profile": "stealth",
                "prompt_names": ["market_pull"],
                "phase": "listing",
                "priority": 6,
            }
        )
    ih_url = _format_source_url(SOURCES["indiehackers"], qv)
    if ih_url:
        targets.append(
            {
                "url": ih_url,
                "source_type": "indiehackers",
                "browser_profile": "lite",
                "prompt_names": ["market_pull", "pain", "operator_practice"],
                "phase": "listing",
                "priority": 6,
            }
        )

    # X/Twitter via Google site search (login-free)
    for tw_key in ["twitter_pain", "twitter_alternatives"]:
        tw_url = _format_source_url(SOURCES[tw_key], qv)
        if tw_url:
            targets.append(
                {
                    "url": tw_url,
                    "source_type": "twitter",
                    "browser_profile": "stealth",
                    "prompt_names": SOURCES[tw_key]["signal_types"],
                    "phase": "content",
                    "priority": 6,
                }
            )

    # Priority 7: Reddit — combine vertical-specific + default subs (query-driven)
    vertical_subs = SUBREDDITS.get(v, []) if v != "default" else []
    default_subs = SUBREDDITS["default"]
    # Merge: vertical-specific first, then defaults, deduplicated
    seen_subs: set[str] = set()
    all_subs: list[str] = []
    for sub in vertical_subs + default_subs:
        if sub not in seen_subs:
            seen_subs.add(sub)
            all_subs.append(sub)
    for sub in all_subs[:4]:
        targets.append(
            {
                "url": f"https://www.reddit.com/{sub}/search/?q={slug}&restrict_sr=1&sort=top&t=year",
                "source_type": "reddit",
                "browser_profile": "stealth",
                "prompt_names": ["pain", "workaround"],
                "phase": "listing",
                "priority": 7,
            }
        )

    # Priority 8: Investor / market signals (short queries for these sites)
    yc_url = _format_source_url(SOURCES["yc_companies"], qv)
    if yc_url:
        targets.append(
            {
                "url": yc_url,
                "source_type": "investor",
                "browser_profile": "lite",
                "prompt_names": ["market_pull"],
                "phase": "listing",
                "priority": 8,
            }
        )
    ss_url = _format_source_url(SOURCES["stackshare"], qv)
    if ss_url:
        targets.append(
            {
                "url": ss_url,
                "source_type": "comparison",
                "browser_profile": "lite",
                "prompt_names": ["migration", "market_pull"],
                "phase": "listing",
                "priority": 8,
            }
        )

    # sort by priority, limit to budget * 2 listing targets
    targets.sort(key=lambda t: t["priority"])
    limited = targets[: budget * 2]

    logger.info("Generated %d source targets for topic='%s' vertical='%s'", len(limited), topic, v)
    return limited


def _build_query_variants(topic: str) -> dict[str, str]:
    """Build multiple query forms from a topic for different site search UIs.

    Returns:
        query    — full slug (CI/CD+pipeline+debugging)
        short    — 1-2 core keywords (CI/CD pipeline)
        tool     — first detected tool name (GitHub Actions) or short fallback
        topic_slug — hyphenated for URL paths (developer-tools)
    """
    slug = _topic_to_slug(topic)

    # Extract short form: prioritize tool names and specific nouns
    stop_words = {
        "how",
        "to",
        "for",
        "the",
        "a",
        "an",
        "with",
        "and",
        "or",
        "in",
        "on",
        "of",
        "that",
        "is",
        "are",
        "can",
        "do",
        "does",
        "should",
        "would",
        "i",
        "we",
        "my",
        "our",
        "build",
        "make",
        "create",
        "find",
        "want",
        "need",
        "looking",
        "something",
        "improve",
        "better",
        "help",
        "helps",
        "thing",
        "things",
        "tool",
        "tools",
        "way",
        "using",
        "like",
        "just",
        "really",
        "very",
        "good",
        "best",
        "new",
        "people",
        "teams",
        "team",
        "company",
        "companies",
        "someone",
    }
    # Prefer capitalized words (proper nouns / tool names) first
    all_words = re.findall(r"[a-zA-Z0-9/]+", topic)
    proper = [w for w in all_words if w[0].isupper() and w.lower() not in stop_words and len(w) > 1]
    regular = [w for w in all_words if w.lower() not in stop_words and w not in proper and len(w) > 2]
    # Combine: proper nouns first, then regular words
    keywords = proper + regular
    short = "+".join(keywords[:2]) if keywords else slug

    # Topic slug for URL path segments (developer-tools, not developer+tools)
    topic_slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")

    # Try to extract a tool name (capitalized proper nouns, known patterns)
    tool = None
    try:
        from app.core.vertical_config import get_tool_terms

        tool_terms = get_tool_terms(topic)
        matches = [t for t in tool_terms if t.lower() in topic.lower()]
        if matches:
            tool = matches[0].replace(" ", "+")
    except Exception:
        pass
    if not tool:
        tool = short

    return {
        "query": slug,
        "short_query": short,
        "tool": tool,
        "topic_slug": topic_slug,
    }


def _format_source_url(source: dict, variants: dict[str, str]) -> str | None:
    """Format a source URL pattern using the appropriate query variant."""
    pattern = source["url_pattern"]
    try:
        return pattern.format(**variants)
    except KeyError:
        # Fallback: try with just {query}
        try:
            return pattern.format(query=variants["query"])
        except KeyError:
            return None


def _topic_to_slug(topic: str) -> str:
    cleaned = re.sub(r"[^\w\s/-]", "", topic.lower())
    return re.sub(r"\s+", "+", cleaned.strip())


def _guess_vertical(topic: str) -> str | None:
    lower = topic.lower()
    if any(w in lower for w in ["ai", "llm", "agent", "gpt", "claude", "copilot", "ml", "langchain"]):
        return "ai_developer_tooling"
    if any(w in lower for w in ["devops", "ci/cd", "docker", "kubernetes", "deploy", "terraform"]):
        return "devtools"
    if any(w in lower for w in ["fintech", "payment", "banking", "trading"]):
        return "fintech"
    if any(w in lower for w in ["security", "vulnerability", "pentest"]):
        return "security"
    if any(w in lower for w in ["data", "pipeline", "etl", "analytics", "airflow"]):
        return "data"
    return None
