import logging
import re

from app.core.vertical_config import get_domain_terms, get_tool_terms
from app.services.evidence.taxonomy import evidence_class_queries
from app.services.workflow.spacy_pipeline import _get_nlp

logger = logging.getLogger(__name__)

INTENT_PATTERNS = {
    "alternatives": [
        r"alternative(?:s)?\s+to\s+(\w+)",
        r"instead\s+of\s+(\w+)",
        r"replace\s+(\w+)",
        r"switch(?:ing)?\s+from\s+(\w+)",
        r"better\s+than\s+(\w+)",
    ],
    "reviews": [
        r"reviews?\s+(?:of|for)\s+(\w+)",
        r"(\w+)\s+reviews?",
    ],
    "comparison": [
        r"(\w+)\s+vs\.?\s+(\w+)",
        r"compare\s+(\w+)\s+(?:and|with|to)\s+(\w+)",
        r"(\w+)\s+or\s+(\w+)",
    ],
}

WORKFLOW_VERBS = {
    "track", "manage", "schedule", "coordinate", "assign", "monitor",
    "review", "approve", "deploy", "onboard", "notify", "debug",
    "test", "build", "ship", "verify", "automate", "sync",
    "migrate", "configure", "maintain", "troubleshoot", "audit",
    "invoice", "bill", "report", "prioritize",
}


def analyze_query(query: str) -> dict:
    """Analyze a user query using spaCy NLP to produce a query_profile.

    Returns structured insights for driving discovery and seed URL generation.
    """
    try:
        nlp = _get_nlp()
        doc = nlp(query.lower())
    except Exception as exc:
        logger.warning("spaCy query analysis unavailable, using fallback: %s", exc)
        return _fallback_analyze_query(query)

    # Lemmatized terms
    lemmas = list(dict.fromkeys(
        token.lemma_ for token in doc
        if token.pos_ in ("NOUN", "VERB", "PROPN", "ADJ")
        and len(token.lemma_) > 2
        and not token.is_stop
    ))

    # Key nouns
    nouns = [chunk.text.strip() for chunk in doc.noun_chunks if len(chunk.text.strip()) > 2]

    # Action verbs (workflow intent)
    verbs = [
        token.lemma_ for token in doc
        if token.pos_ == "VERB" and token.lemma_ in WORKFLOW_VERBS
    ]

    # Detect tool names from query (match against YAML tool_terms)
    tool_terms = get_tool_terms(query)
    query_lower = query.lower()
    tools_mentioned = [t for t in tool_terms if t.lower() in query_lower]

    # Also check domain terms
    domain_terms = get_domain_terms(query)
    domain_hits = [t for t in domain_terms if t.lower() in query_lower]

    # Detect intent
    intent, intent_targets = _detect_intent(query_lower)

    topic_phrase = " ".join(nouns[:3]) if nouns else query

    # Generate search queries for TinyFish web search
    search_queries = _generate_search_queries(query, nouns, tools_mentioned, intent)
    evidence_queries = evidence_class_queries(base_query=topic_phrase if len(query.split()) > 4 else query, limit=5)

    profile = {
        "raw_query": query,
        "lemmas": lemmas,
        "nouns": nouns,
        "verbs": verbs,
        "tools_mentioned": tools_mentioned,
        "domain_hits": domain_hits,
        "intent": intent,
        "intent_targets": intent_targets,
        "search_queries": search_queries,
        "evidence_queries": evidence_queries,
    }

    logger.info(
        "Query analyzed: intent=%s tools=%s verbs=%s searches=%d",
        intent, tools_mentioned, verbs, len(search_queries),
    )
    return profile


def _fallback_analyze_query(query: str) -> dict:
    query_lower = query.lower()
    tokens = re.findall(r"[a-z0-9]+", query_lower)
    lemmas = list(dict.fromkeys(token for token in tokens if len(token) > 2))
    nouns = [token for token in lemmas if token not in WORKFLOW_VERBS][:6]
    verbs = [token for token in lemmas if token in WORKFLOW_VERBS][:6]

    tool_terms = get_tool_terms(query)
    tools_mentioned = [t for t in tool_terms if t.lower() in query_lower]

    domain_terms = get_domain_terms(query)
    domain_hits = [t for t in domain_terms if t.lower() in query_lower]

    intent, intent_targets = _detect_intent(query_lower)
    topic_phrase = " ".join(nouns[:3]) if nouns else query
    search_queries = _generate_search_queries(query, nouns, tools_mentioned, intent)
    evidence_queries = evidence_class_queries(
        base_query=topic_phrase if len(query.split()) > 4 else query,
        limit=5,
    )

    return {
        "raw_query": query,
        "lemmas": lemmas,
        "nouns": nouns,
        "verbs": verbs,
        "tools_mentioned": tools_mentioned,
        "domain_hits": domain_hits,
        "intent": intent,
        "intent_targets": intent_targets,
        "search_queries": search_queries,
        "evidence_queries": evidence_queries,
        "analysis_fallback": "regex",
    }


def _detect_intent(query_lower: str) -> tuple[str, list[str]]:
    """Detect user intent from query patterns."""
    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                targets = [g for g in match.groups() if g]
                return intent, targets

    # Fallback intent from verb presence
    if any(v in query_lower for v in ["track", "manage", "schedule", "automate"]):
        return "workflow_tool", []
    if any(v in query_lower for v in ["debug", "test", "verify", "build"]):
        return "dev_tool", []

    return "general", []


def _generate_search_queries(
    query: str,
    nouns: list[str],
    tools: list[str],
    intent: str,
) -> list[str]:
    """Generate search queries for TinyFish web search."""
    queries = []

    # Build a clean topic phrase from nouns (not the full sentence)
    topic_phrase = " ".join(nouns[:3]) if nouns else query

    # Short queries (1-4 words) use the raw query; longer ones use extracted nouns
    if len(query.split()) <= 4:
        base = query
    else:
        base = topic_phrase

    # Primary: topic + reviews/complaints
    queries.append(f"{base} software reviews complaints")

    # Intent-specific searches
    if intent == "alternatives" and tools:
        queries.append(f"alternatives to {tools[0]} reviews")
        queries.append(f"{tools[0]} competitors comparison")
    elif intent == "reviews" and tools:
        queries.append(f"{tools[0]} reviews pros cons")
    elif intent == "comparison" and len(tools) >= 2:
        queries.append(f"{tools[0]} vs {tools[1]} comparison")
    elif intent == "workflow_tool":
        if nouns:
            queries.append(f"best {nouns[0]} software tools")

    # Tool-specific searches
    for tool in tools[:2]:
        queries.append(f"{tool} alternatives reviews")

    # Deduplicate
    return list(dict.fromkeys(queries))[:5]
