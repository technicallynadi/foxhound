"""Engineering blog RSS aggregator.

Maintains a registry of ~50 engineering blogs and fetches new posts
via RSS/Atom feeds. Posts are pre-indexed as signal sources so the
pipeline can use them without TinyFish calls.

Usage:
    from app.services.ingest.engineering_blogs import fetch_recent_posts, BLOG_REGISTRY

    # Get recent posts relevant to a topic
    posts = await fetch_recent_posts(topic="CI/CD", max_age_days=30, limit=20)
"""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

# ─── Blog Registry ───
# Each entry: (name, rss_url, topics/verticals it covers)

BLOG_REGISTRY = [
    # FAANG / Major tech
    ("Netflix Tech Blog", "https://netflixtechblog.com/feed", ["infra", "data", "streaming"]),
    ("Uber Engineering", "https://eng.uber.com/feed/", ["infra", "data", "mobile"]),
    ("Spotify Engineering", "https://engineering.atspotify.com/feed/", ["data", "infra", "ml"]),
    ("Stripe Engineering", "https://stripe.com/blog/engineering/feed", ["payments", "infra", "api"]),
    ("GitHub Engineering", "https://github.blog/category/engineering/feed/", ["devtools", "git", "infra"]),
    ("Cloudflare Blog", "https://blog.cloudflare.com/rss/", ["infra", "security", "cdn"]),
    ("Discord Engineering", "https://discord.com/blog/engineering/rss.xml", ["infra", "realtime"]),
    ("Figma Engineering", "https://www.figma.com/blog/section/engineering/rss.xml", ["frontend", "design"]),
    ("Slack Engineering", "https://slack.engineering/feed/", ["infra", "realtime", "devtools"]),
    ("LinkedIn Engineering", "https://engineering.linkedin.com/blog.rss", ["data", "ml", "infra"]),
    ("Pinterest Engineering", "https://medium.com/feed/@Pinterest_Engineering", ["data", "ml"]),
    ("Dropbox Tech", "https://dropbox.tech/feed", ["infra", "sync", "storage"]),
    ("Airbnb Tech", "https://medium.com/feed/airbnb-engineering", ["data", "frontend", "ml"]),
    # Developer tools
    ("Vercel Blog", "https://vercel.com/blog/rss.xml", ["frontend", "devtools", "deployment"]),
    ("Supabase Blog", "https://supabase.com/blog/rss.xml", ["database", "backend", "auth"]),
    ("PlanetScale Blog", "https://planetscale.com/blog/rss.xml", ["database", "mysql"]),
    ("Prisma Blog", "https://www.prisma.io/blog/rss.xml", ["database", "orm", "devtools"]),
    ("Railway Blog", "https://blog.railway.app/rss.xml", ["deployment", "devtools"]),
    ("Fly.io Blog", "https://fly.io/blog/feed.xml", ["deployment", "infra", "edge"]),
    ("Render Blog", "https://render.com/blog/rss.xml", ["deployment", "devtools"]),
    ("Neon Blog", "https://neon.tech/blog/rss.xml", ["database", "serverless"]),
    ("Turso Blog", "https://blog.turso.tech/rss.xml", ["database", "edge"]),
    ("Deno Blog", "https://deno.com/blog/rss.xml", ["runtime", "devtools"]),
    ("Bun Blog", "https://bun.sh/blog/rss.xml", ["runtime", "devtools"]),
    # Data / ML
    ("dbt Labs Blog", "https://www.getdbt.com/blog/rss.xml", ["data", "analytics"]),
    ("Dagster Blog", "https://dagster.io/blog/rss.xml", ["data", "orchestration"]),
    ("Prefect Blog", "https://www.prefect.io/blog/rss.xml", ["data", "orchestration"]),
    ("Modal Blog", "https://modal.com/blog/rss.xml", ["ml", "infra", "serverless"]),
    ("Weights & Biases", "https://wandb.ai/fully-connected/rss.xml", ["ml", "experiment-tracking"]),
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml", ["ml", "nlp", "ai"]),
    # Infrastructure / DevOps
    ("HashiCorp Blog", "https://www.hashicorp.com/blog/feed.xml", ["devops", "infra", "terraform"]),
    ("Datadog Blog", "https://www.datadoghq.com/blog/engineering/feed/", ["monitoring", "observability"]),
    ("Grafana Blog", "https://grafana.com/blog/rss.xml", ["monitoring", "observability"]),
    ("Pulumi Blog", "https://www.pulumi.com/blog/rss.xml", ["iac", "devops"]),
    # Security
    ("Trail of Bits Blog", "https://blog.trailofbits.com/feed/", ["security", "audit"]),
    ("Snyk Blog", "https://snyk.io/blog/feed/", ["security", "devsecops"]),
    # AI / LLM
    ("Anthropic Research", "https://www.anthropic.com/research/rss.xml", ["ai", "llm", "safety"]),
    ("OpenAI Blog", "https://openai.com/blog/rss.xml", ["ai", "llm"]),
    ("LangChain Blog", "https://blog.langchain.dev/rss/", ["ai", "agents", "llm"]),
    ("LlamaIndex Blog", "https://www.llamaindex.ai/blog/rss.xml", ["ai", "rag", "llm"]),
    # General / Aggregators
    ("The Pragmatic Engineer", "https://newsletter.pragmaticengineer.com/feed", ["engineering", "career", "infra"]),
    ("ByteByteGo", "https://blog.bytebytego.com/feed", ["system-design", "infra"]),
    ("InfoQ", "https://feed.infoq.com/", ["engineering", "architecture"]),
]


async def fetch_recent_posts(
    topic: str | None = None,
    max_age_days: int = 30,
    limit: int = 20,
    verticals: list[str] | None = None,
) -> list[dict]:
    """Fetch recent blog posts, optionally filtered by topic relevance.

    Returns list of dicts with: title, url, published_at, blog_name, summary, topics.
    """
    try:
        import feedparser
    except ImportError:
        logger.warning("feedparser not installed — skipping engineering blog fetch")
        return []

    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    topic_lower = topic.lower() if topic else ""
    topic_words = set(re.findall(r"[a-z0-9]+", topic_lower)) if topic_lower else set()

    # Filter blogs by vertical if specified
    blogs = BLOG_REGISTRY
    if verticals:
        v_set = set(v.lower() for v in verticals)
        blogs = [b for b in blogs if any(t in v_set for t in b[2])]

    async def _fetch_one(name: str, rss_url: str, blog_topics: list[str]) -> list[dict]:
        try:
            loop = asyncio.get_event_loop()
            feed = await loop.run_in_executor(None, feedparser.parse, rss_url)
            posts = []
            for entry in feed.entries[:10]:
                # Parse date
                published = None
                for date_field in ("published_parsed", "updated_parsed"):
                    parsed = getattr(entry, date_field, None)
                    if parsed:
                        try:
                            published = datetime(*parsed[:6], tzinfo=UTC)
                        except (TypeError, ValueError):
                            pass
                        break

                if published and published < cutoff:
                    continue

                title = getattr(entry, "title", "")
                summary = getattr(entry, "summary", "")[:500]
                link = getattr(entry, "link", "")

                # Relevance check: does this post relate to the topic?
                if topic_words:
                    text_lower = f"{title} {summary}".lower()
                    text_words = set(re.findall(r"[a-z0-9]+", text_lower))
                    overlap = topic_words & text_words
                    if len(overlap) < 1:
                        continue

                posts.append(
                    {
                        "title": title,
                        "url": link,
                        "published_at": published.isoformat() if published else None,
                        "blog_name": name,
                        "summary": summary,
                        "topics": blog_topics,
                        "source_type": "engineering_blog",
                        "source_platform": name,
                    }
                )
            return posts
        except Exception as e:
            logger.debug("Failed to fetch %s: %s", name, e)
            return []

    # Fetch all feeds concurrently
    tasks = [_fetch_one(name, url, topics) for name, url, topics in blogs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_posts: list[dict] = []
    for result in results:
        if isinstance(result, list):
            all_posts.extend(result)

    # Sort by date (newest first) and limit
    all_posts.sort(key=lambda p: p.get("published_at") or "", reverse=True)
    return all_posts[:limit]


# Topic aliases: expand blog topic tags to catch more query variations
TOPIC_ALIASES = {
    "infra": {"infrastructure", "ci", "cd", "cicd", "pipeline", "deploy", "kubernetes", "k8s", "docker", "container"},
    "devops": {"ci", "cd", "cicd", "pipeline", "deploy", "terraform", "ansible", "jenkins", "github", "actions"},
    "devtools": {"developer", "tools", "ide", "cli", "sdk", "linter", "formatter", "build"},
    "data": {"data", "pipeline", "etl", "warehouse", "analytics", "spark", "airflow", "dbt"},
    "ml": {"machine", "learning", "model", "training", "inference", "gpu", "neural"},
    "ai": {"ai", "llm", "agent", "gpt", "claude", "openai", "anthropic", "langchain", "rag"},
    "database": {"database", "db", "sql", "postgres", "mysql", "sqlite", "mongo", "redis"},
    "frontend": {"frontend", "react", "vue", "svelte", "nextjs", "css", "ui", "ux", "web"},
    "security": {"security", "auth", "encryption", "vulnerability", "pentest", "firewall"},
    "monitoring": {"monitoring", "observability", "logging", "tracing", "metrics", "alerting"},
    "deployment": {"deploy", "deployment", "hosting", "cloud", "serverless", "edge"},
}


def get_blog_urls_for_topic(topic: str) -> list[dict]:
    """Get blog URLs as source targets for the pipeline (no RSS fetch needed).

    Returns URL dicts compatible with _dispatch_workers / source_targets.
    """
    topic_lower = topic.lower()
    topic_words = set(re.findall(r"[a-z0-9]+", topic_lower))

    urls: list[dict] = []
    for name, rss_url, blog_topics in BLOG_REGISTRY:
        # Check if any blog topic (or its aliases) matches the query
        blog_topic_words = set()
        for t in blog_topics:
            blog_topic_words.add(t.lower())
            blog_topic_words.update(TOPIC_ALIASES.get(t.lower(), set()))

        if topic_words & blog_topic_words:
            # Convert RSS URL to blog homepage for TinyFish crawling
            blog_url = rss_url.split("/feed")[0].split("/rss")[0]
            if blog_url.endswith("/"):
                blog_url = blog_url[:-1]
            urls.append(
                {
                    "url": blog_url,
                    "page_type": "engineering_blog",
                    "title": f"Engineering blog: {name}",
                    "source": "engineering_blog_registry",
                    "source_platform": name,
                    "evidence_class": "workflow",
                }
            )

    return urls[:5]  # cap to avoid over-crawling blogs
