"""LinkedIn and Google search URL builders for hiring manager discovery.

Constructs clickable URLs the user can open to find the likely hiring manager
on LinkedIn or via Google. No API calls — pure URL construction.
"""

from __future__ import annotations

from urllib.parse import quote_plus


def build_linkedin_search_url(company: str, title: str) -> str:
    """Build a LinkedIn people search URL for a given company and title.

    Example output:
        https://www.linkedin.com/search/results/people/?keywords=Engineering+Manager+Stripe
    """
    keywords = f"{title} {company}".strip()
    return f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(keywords)}"


def build_google_search_url(company: str, title: str) -> str:
    """Build a Google search URL targeting LinkedIn profiles.

    Example output:
        https://www.google.com/search?q=site:linkedin.com/in+"Engineering+Manager"+"Stripe"
    """
    query = f'site:linkedin.com/in "{title}" "{company}"'
    return f"https://www.google.com/search?q={quote_plus(query)}"


def build_search_urls(company: str, title: str) -> dict[str, str]:
    """Build both LinkedIn and Google search URLs.

    Returns:
        {"linkedin": "...", "google": "..."}
    """
    return {
        "linkedin": build_linkedin_search_url(company, title),
        "google": build_google_search_url(company, title),
    }
