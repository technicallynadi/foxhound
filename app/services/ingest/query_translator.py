"""Query translator: converts conversational user input into sharp research queries.

Takes natural language like "I want to build a project that improves agent memory"
and produces:
1. Structured intent extraction (domain, focus, pain area)
2. 3-5 targeted research queries optimized for finding real workflow pain

This sits before the existing query_analyzer and pipeline — it translates
user intent into the kind of queries that produce strong evidence."""

import asyncio
import json
import logging
import os

logger = logging.getLogger(__name__)

TRANSLATION_PROMPT = """You are a product research query translator for Foxhound, a tool that discovers real software product opportunities by finding workflow pain in developer communities, forums, and review sites.

A user has described what they want to build or explore. Your job is to:

1. Extract structured intent from their input
2. Generate 3-5 sharp, specific research queries that will find REAL workflow pain, complaints, workarounds, and unmet needs related to their idea

The research queries should target:
- Specific frustrations developers/users have with existing tools
- Workarounds people use because no good tool exists
- Forum complaints and discussion threads about the pain area
- Comparison threads where people are looking for alternatives
- High-signal request language like "wish there was", "looking for a tool", or "we built an internal tool"

Rules:
- Each query should be specific enough to find real pain signals, not broad topic overviews
- Include the "worst part of", "frustrated with", "workaround for" framing that surfaces real complaints
- Target specific workflows and tools, not abstract concepts
- Prefer unmet-need and request language over generic "startup ideas" or "business ideas"
- Generate queries that would work well on Reddit, HackerNews, GitHub Discussions, and review sites

User input: {user_input}

Respond in this exact JSON format:
{{
  "intent": {{
    "domain": "the technical domain (e.g. AI agents, DevOps, data engineering)",
    "focus": "the specific area within the domain",
    "user_goal": "what the user wants to build or explore",
    "pain_area": "the underlying pain this would solve"
  }},
  "research_queries": [
    "specific research query 1",
    "specific research query 2",
    "specific research query 3"
  ]
}}"""


async def translate_query(user_input: str) -> dict:
    """Translate conversational input into structured intent + research queries.

    Returns {intent, research_queries, original_input} or falls back to
    basic extraction if the LLM call fails."""
    try:
        return await _llm_translate(user_input)
    except Exception as exc:
        logger.warning("LLM query translation failed, using fallback: %s", exc)
        return _fallback_translate(user_input)


async def _llm_translate(user_input: str) -> dict:
    """Use Claude to translate the query."""
    import anthropic
    from app.core.config import settings

    api_key = settings.anthropic_api_key
    if not api_key:
        return _fallback_translate(user_input)

    client = anthropic.AsyncAnthropic(api_key=api_key)
    model = settings.llm_model_default

    response = await asyncio.wait_for(
        client.messages.create(
            model=model,
            max_tokens=800,
            messages=[{
                "role": "user",
                "content": TRANSLATION_PROMPT.format(user_input=user_input),
            }],
        ),
        timeout=settings.translator_timeout_seconds,
    )

    text = response.content[0].text.strip()
    # extract JSON from response
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    parsed = json.loads(text)

    return {
        "original_input": user_input,
        "intent": parsed.get("intent", {}),
        "research_queries": parsed.get("research_queries", [])[:5],
        "translated": True,
    }


def _fallback_translate(user_input: str) -> dict:
    """Basic keyword extraction when LLM is unavailable."""
    words = user_input.lower().split()
    # extract nouns-ish (words > 3 chars, not common filler)
    filler = {"want", "build", "project", "that", "will", "would", "could", "make",
              "something", "tool", "thing", "like", "think", "need", "help", "with",
              "about", "this", "there", "have", "been", "also", "just", "really"}
    keywords = [w for w in words if len(w) > 3 and w not in filler]
    topic = " ".join(keywords[:5])

    return {
        "original_input": user_input,
        "intent": {
            "domain": "general",
            "focus": topic,
            "user_goal": user_input,
            "pain_area": topic,
        },
        "research_queries": [
            f"developers frustrated with {topic}",
            f"worst part of {topic}",
            f"{topic} workarounds and complaints",
            f'wish there was a tool for {topic}',
            f'we built an internal tool for {topic}',
        ],
        "translated": False,
    }


def is_conversational(query: str) -> bool:
    """Detect if a query is conversational vs a direct search topic.

    Conversational: "I want to build something that improves agent memory"
    Direct: "agent memory management tools" """
    lower = query.lower().strip()
    conversational_signals = [
        lower.startswith("i want"),
        lower.startswith("i need"),
        lower.startswith("i'm looking"),
        lower.startswith("how can i"),
        lower.startswith("what if"),
        lower.startswith("build a"),
        lower.startswith("build something"),
        lower.startswith("create a"),
        lower.startswith("make a"),
        "i want to" in lower,
        "i need to" in lower,
        "i'm trying to" in lower,
        "looking for" in lower,
        "interested in building" in lower,
        "idea for" in lower,
        len(lower.split()) > 8,
    ]
    return any(conversational_signals)
