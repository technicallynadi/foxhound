"""Claude Sonnet synthesis for full dossiers.

Takes all TinyFish source data + job posting + user profile and produces a
comprehensive intelligence report: executive summary, interview process,
culture report, outreach drafts, interview prep, and overall assessment.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)

_SYNTHESIS_PROMPT = """\
You are a senior career intelligence analyst writing a comprehensive research \
brief for a job seeker. You have collected company data from 8 sources including \
the company website, careers page, news, team contacts, Glassdoor, Reddit \
interview experiences, Reddit culture/WLB posts, and engineering blog articles.

Your job is to synthesize ALL available data into a detailed, actionable intelligence \
report. Write in PROSE where indicated — not bullet fragments. Be specific: use real \
names, real data, real details from the sources provided. Never fabricate data.

Return ONLY valid JSON with this structure:
{
  "executive_summary": "3-4 sentence overview of the company, its trajectory, and what the candidate should know going in.",

  "company_overview": {
    "mission": "1-2 sentence company mission",
    "founded": "Year founded (e.g. '2019')",
    "size": "Employee count (e.g. '400+')",
    "funding": "Latest funding info (e.g. 'Series C, $60M')",
    "locations": ["List of office locations"],
    "products": ["List of main products or brands"]
  },

  "hiring_summary": {
    "open_roles": 97,
    "top_departments": ["Engineering", "Marketing", "Product"],
    "hiring_velocity": "growing or stable or slowing",
    "growth_signals": "1-2 sentence summary of hiring trends"
  },

  "recent_news": [
    {"title": "Headline of relevant company news", "source": "Source name", "date": "Date or timeframe", "url": "URL if available"}
  ],

  "interview_process": {
    "stages": ["List each stage: phone screen, technical, system design, behavioral, etc."],
    "timeline": "Typical timeline from application to offer (e.g. '2-3 weeks')",
    "tips": ["3-5 actionable tips from real candidate experiences"],
    "common_questions": ["5-8 specific questions candidates reported being asked, especially technical ones"],
    "difficulty": "Easy / Medium / Hard with brief explanation"
  },

  "culture_report": "2-3 paragraphs of prose about what it is really like to work there. Cite Reddit posts, Glassdoor reviews. Cover: management style, work-life balance, growth opportunities, compensation satisfaction. Be honest about red flags.",

  "outreach_draft": {
    "linkedin_message": "Personalized LinkedIn message (under 300 chars) referencing specific company details",
    "email_draft": "3-4 sentence email to hiring manager. Reference specific news, projects, or team details.",
    "contact_name": "Name of best person to reach out to, if found"
  },

  "interview_prep": {
    "key_themes": ["5 themes to prepare for"],
    "talking_points": ["5 specific things to reference to show company knowledge — cite actual news, blog posts, projects"],
    "technical_focus": ["3-5 specific technical areas to study based on the tech stack and interview reports"]
  },

  "salary_estimate": {
    "range": "Base salary range (e.g. '$150k - $200k')",
    "total_comp": "Total compensation range including stock + bonus (e.g. '$200k - $350k')",
    "median": "Median total comp (e.g. '$275k')",
    "source": "levels.fyi" or "estimated from posting/market data",
    "by_level": [{"level": "str", "total_comp": "str"}]
  },

  "overall_assessment": "3-4 sentences: honest match assessment, company health, growth trajectory, compensation outlook, and one specific recommendation."
}

Rules:
- Be specific. Use real names, real data, real details from the sources provided.
- company_overview must contain real data from the company page. Fill every sub-field.
- hiring_summary must summarize the careers page data — count total open roles, list top hiring departments, assess velocity.
- recent_news must contain ONLY news about the COMPANY itself (acquisitions, funding, product launches, leadership). Filter out unrelated results that just mention the company name in passing. Max 5 items.
- If team contacts were found, use the best contact name in the outreach draft.
- If news was found, reference it in talking points.
- If Reddit interview data is available, use it heavily in interview_process and interview_prep.
- If Reddit culture data is available, use it heavily in culture_report.
- If engineering blog data is available, reference technologies and posts in talking_points and technical_focus.
- If levels.fyi data is available, use exact numbers in salary_estimate. If not, estimate from the job posting, company size, and market data.
- culture_report must be PROSE paragraphs, not bullet points. Write like a researcher briefing a candidate.
- interview_prep questions should be tailored to the specific tech stack and role.
- overall_assessment should be honest — flag red flags (layoffs, poor Glassdoor, negative Reddit sentiment) as well as positives.
- Keep outreach messages professional but warm, not generic.
- If a source is missing, work with what you have. Never fabricate data.
- Fill every field. If data is truly unavailable for a section, say so honestly rather than leaving it empty."""


async def synthesize_dossier(
    company_name: str,
    posting_data: dict[str, Any] | None,
    company_data: dict[str, Any] | None,
    careers_data: dict[str, Any] | None,
    news_data: dict[str, Any] | None,
    team_contacts: dict[str, Any] | None,
    glassdoor_data: dict[str, Any] | None,
    reddit_interviews: dict[str, Any] | None = None,
    reddit_culture: dict[str, Any] | None = None,
    engineering_blog: dict[str, Any] | None = None,
    levels_fyi: dict[str, Any] | None = None,
    user_summary: str | None = None,
) -> dict[str, Any]:
    """Run Claude Sonnet synthesis on all collected source data.

    Returns dict with executive_summary, interview_process, culture_report,
    outreach_draft, interview_prep, overall_assessment or fallback values
    if the API call fails.
    """
    sections = [
        f"Company: {company_name}",
        "",
        f"JOB POSTING:\n{json.dumps(posting_data, default=str) if posting_data else 'Not available'}",
        "",
        f"COMPANY OVERVIEW:\n{json.dumps(company_data, default=str) if company_data else 'Not available'}",
        "",
        f"CAREERS/HIRING DATA:\n{json.dumps(careers_data, default=str) if careers_data else 'Not available'}",
        "",
        f"RECENT NEWS:\n{json.dumps(news_data, default=str) if news_data else 'Not available'}",
        "",
        f"TEAM CONTACTS:\n{json.dumps(team_contacts, default=str) if team_contacts else 'Not available'}",
        "",
        f"GLASSDOOR DATA:\n{json.dumps(glassdoor_data, default=str) if glassdoor_data else 'Not available'}",
        "",
        f"REDDIT INTERVIEW EXPERIENCES:\n{json.dumps(reddit_interviews, default=str) if reddit_interviews else 'Not available'}",
        "",
        f"REDDIT CULTURE/WLB:\n{json.dumps(reddit_culture, default=str) if reddit_culture else 'Not available'}",
        "",
        f"ENGINEERING BLOG:\n{json.dumps(engineering_blog, default=str) if engineering_blog else 'Not available'}",
        "",
        f"LEVELS.FYI SALARY DATA:\n{json.dumps(levels_fyi, default=str) if levels_fyi else 'Not available'}",
    ]

    if user_summary:
        sections.append("")
        sections.append(f"CANDIDATE PROFILE:\n{user_summary}")

    user_content = "\n".join(sections)

    # Try models in order of capability — fall back if rate limited or unavailable
    _MODELS = [
        "claude-sonnet-4-5-20241022",
        "claude-haiku-4-5-20251001",
        "claude-3-haiku-20240307",
    ]

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = None
        last_error = None
        for model in _MODELS:
            try:
                response = await client.messages.create(
                    model=model,
                    max_tokens=8000,
                    temperature=0.3,
                    system=_SYNTHESIS_PROMPT,
                    messages=[{"role": "user", "content": user_content}],
                )
                logger.info("Dossier synthesis using model %s for %s", model, company_name)
                break
            except anthropic.NotFoundError:
                logger.info("Model %s not available, trying next", model)
                last_error = f"Model {model} not found"
                continue
            except anthropic.RateLimitError:
                logger.warning("Model %s rate limited, trying next", model)
                last_error = f"Model {model} rate limited"
                continue

        if response is None:
            raise RuntimeError(last_error or "All models failed")

        text = response.content[0].text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            text = "\n".join(lines)

        # Extract JSON object — handle trailing text after the closing brace
        # Find the outermost { ... } pair
        start = text.find("{")
        if start >= 0:
            depth = 0
            end = start
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            text = text[start:end]

        synthesis = json.loads(text)
        logger.info("Dossier synthesis complete for %s", company_name)
        return synthesis

    except json.JSONDecodeError as e:
        logger.warning("Dossier synthesis JSON parse failed for %s: %s", company_name, e)
        return _fallback_synthesis(
            company_name,
            posting_data,
            team_contacts,
            company_data=company_data,
            careers_data=careers_data,
            glassdoor_data=glassdoor_data,
            reddit_interviews=reddit_interviews,
            reddit_culture=reddit_culture,
            levels_fyi=levels_fyi,
        )
    except Exception as e:
        logger.warning("Dossier synthesis API failed for %s: %s", company_name, str(e)[:200])
        return _fallback_synthesis(
            company_name,
            posting_data,
            team_contacts,
            company_data=company_data,
            careers_data=careers_data,
            glassdoor_data=glassdoor_data,
            reddit_interviews=reddit_interviews,
            reddit_culture=reddit_culture,
            levels_fyi=levels_fyi,
        )


def _fallback_synthesis(
    company_name: str,
    posting_data: dict[str, Any] | None,
    team_contacts: dict[str, Any] | None,
    company_data: dict[str, Any] | None = None,
    careers_data: dict[str, Any] | None = None,
    glassdoor_data: dict[str, Any] | None = None,
    reddit_interviews: dict[str, Any] | None = None,
    reddit_culture: dict[str, Any] | None = None,
    levels_fyi: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build synthesis from raw source data when Claude fails.

    Uses whatever TinyFish data is available to populate every section
    instead of returning near-empty generic text.
    """
    title = (posting_data or {}).get("title", "the role")
    tech_stack = (posting_data or {}).get("tech_stack", [])

    # Contacts — handle both {contacts: [...]} and bare list
    raw_contacts = team_contacts
    if isinstance(raw_contacts, dict):
        raw_contacts = raw_contacts.get("contacts", [])
    if not isinstance(raw_contacts, list):
        raw_contacts = []
    contact_name = raw_contacts[0]["name"] if raw_contacts else "the hiring team"

    # --- Executive summary from company_data + posting ---
    summary_parts = []
    if company_data:
        if company_data.get("mission"):
            summary_parts.append(company_data["mission"])
        details = []
        if company_data.get("founded"):
            details.append(f"founded {company_data['founded']}")
        if company_data.get("size"):
            details.append(f"{company_data['size']} employees")
        if company_data.get("funding"):
            details.append(company_data["funding"])
        if details:
            summary_parts.append(f"{company_name}: {', '.join(details)}.")
    if not summary_parts:
        summary_parts.append(
            f"{company_name} is hiring for {title}. Review the job posting and company activity for more context."
        )
    executive_summary = " ".join(summary_parts)

    # --- Interview process from reddit_interviews or glassdoor ---
    interview_process: dict[str, Any] = {}
    if reddit_interviews:
        stages = reddit_interviews.get("stages") or reddit_interviews.get("process", [])
        if isinstance(stages, list) and stages:
            interview_process["stages"] = stages
        interview_process["timeline"] = reddit_interviews.get("timeline", "Not reported")
        interview_process["difficulty"] = reddit_interviews.get("difficulty", "Medium")
        tips = reddit_interviews.get("tips", [])
        if isinstance(tips, list):
            interview_process["tips"] = tips
        questions = reddit_interviews.get("common_questions") or reddit_interviews.get("questions", [])
        if isinstance(questions, list):
            interview_process["common_questions"] = questions
    if not interview_process.get("stages") and glassdoor_data:
        interview_process["difficulty"] = glassdoor_data.get("difficulty", "Medium")
        interview_process["timeline"] = glassdoor_data.get("timeline", "Not reported")

    # --- Culture from reddit_culture or glassdoor ---
    culture_report = None
    if reddit_culture:
        culture_parts = []
        for key in ("work_life_balance", "management", "culture", "growth", "summary", "pros", "cons"):
            val = reddit_culture.get(key)
            if val and isinstance(val, str):
                culture_parts.append(val)
        if culture_parts:
            culture_report = "\n\n".join(culture_parts)
    if not culture_report and glassdoor_data:
        reviews = glassdoor_data.get("reviews") or glassdoor_data.get("summary")
        if isinstance(reviews, str):
            culture_report = reviews
        elif isinstance(reviews, list):
            culture_report = "\n\n".join(str(r) for r in reviews[:5])

    # --- Salary from levels_fyi ---
    salary_estimate: dict[str, Any] | None = None
    if levels_fyi:
        salary_estimate = {
            "range": levels_fyi.get("range", ""),
            "total_comp": levels_fyi.get("total_comp", ""),
            "median": levels_fyi.get("median", ""),
            "source": "levels.fyi",
            "by_level": levels_fyi.get("by_level", []),
        }

    result: dict[str, Any] = {
        "executive_summary": executive_summary,
        "outreach_draft": {
            "linkedin_message": (
                f"Hi {contact_name}, I recently applied for {title} at {company_name} "
                f"and would love to connect and learn more about the team."
            ),
            "email_draft": (
                f"Hi {contact_name},\n\n"
                f"I recently applied for {title} at {company_name}. "
                f"I'd love to learn more about the team and how I could contribute. "
                f"Would you be open to a brief conversation?\n\nBest regards"
            ),
            "contact_name": contact_name,
        },
        "interview_prep": {
            "key_themes": (
                [f"Deep knowledge of {', '.join(tech_stack[:5])}"]
                if tech_stack
                else ["Review the job requirements and match your experience"]
            ),
            "likely_questions": [
                "Tell me about yourself and why you're interested in this role.",
                "What relevant experience do you bring?",
                "Describe a challenging project you've worked on recently.",
            ],
            "talking_points": [f"Research {company_name} thoroughly before the interview"],
            "technical_focus": tech_stack[:5] if tech_stack else [],
        },
        "overall_assessment": (
            f"Intelligence gathered from {company_name}. "
            f"Review the sections below for actionable insights compiled from available sources."
        ),
    }

    if interview_process:
        result["interview_process"] = interview_process
    if culture_report:
        result["culture_report"] = culture_report
    if salary_estimate:
        result["salary_estimate"] = salary_estimate

    return result
