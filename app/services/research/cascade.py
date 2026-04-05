"""Post-apply research cascade.

Simplified for demo: runs Company Brief + Pathfinder as async tasks
after a successful application, then assembles a FoxhoundBrief.

Production version will use the full workflow DAG engine.
"""

from __future__ import annotations

import asyncio
import logging

from app.db.session import async_session
from app.services.activity.logger import log_activity

logger = logging.getLogger(__name__)


async def start_research_cascade(
    user_id: str,
    application_id: str,
    job_id: str,
    match_score: int | None = None,
) -> None:
    """Launch post-apply research as a background task.

    Runs asynchronously so it doesn't block the apply response.
    """
    task = asyncio.create_task(
        _run_cascade(user_id, application_id, job_id, match_score)
    )
    # Keep a strong reference and surface unexpected top-level failures.
    task.add_done_callback(
        lambda t: logger.error(
            "Research cascade task failed unexpectedly for application %s: %s",
            application_id,
            t.exception(),
        )
        if not t.cancelled() and t.exception() is not None
        else None
    )
    logger.info("Research cascade started for application %s", application_id)


async def _run_cascade(
    user_id: str,
    application_id: str,
    job_id: str,
    match_score: int | None,
) -> None:
    """Execute the research cascade steps sequentially."""
    try:
        # Load job info first, then close the session before calling tools
        async with async_session() as db:
            from app.db.models.job_listing import JobListing
            job = await db.get(JobListing, job_id)
            if not job:
                logger.warning("Research cascade: job %s not found", job_id)
                return
            company = job.company or "Unknown"
            title = job.title or "Unknown"

        # Load existing brief data to skip steps that are already done
        existing_brief = None
        try:
            from sqlalchemy import select

            from app.db.models.foxhound_brief import FoxhoundBrief
            async with async_session() as brief_db:
                result = await brief_db.execute(
                    select(FoxhoundBrief).where(FoxhoundBrief.application_id == application_id)
                )
                existing_brief = result.scalar_one_or_none()
        except Exception as e:
            logger.warning("Research cascade: failed to load existing brief for %s: %s", application_id, e)

        import json as _json
        brief_data: dict = {
            "application_id": application_id,
            "job_id": job_id,
            "company": company,
            "title": title,
        }

        await log_activity(
            user_id=user_id,
            event_type="research_started",
            title=f"Research started: {company} — {title}",
            description="Researching company context, finding the best contact, and assembling your brief.",
            metadata={
                "application_id": application_id,
                "job_id": job_id,
                "company": company,
                "title": title,
                "match_score": match_score,
            },
        )

        # Step 1: Company Brief
        # Flow: FoxhoundBrief → TinyFishBriefCache → TinyFish scrape → LLM synthesis
        has_company = existing_brief and existing_brief.company_brief_json
        if has_company:
            brief_data["company_brief"] = _json.loads(existing_brief.company_brief_json)
            logger.info("Research cascade: company brief exists, skipping for %s", company)
        if not has_company:
          try:
            from app.services.recon.synthesizer import synthesize_dossier

            # Get job details for synthesis context
            async with async_session() as url_db:
                from app.db.models.job_listing import JobListing as JL
                jl = await url_db.get(JL, job_id)
                company_url = getattr(jl, "company_url", None) or ""
                apply_url = jl.apply_url if jl else ""
                description = jl.description if jl else ""

            # Infer company URL from apply URL if not set
            if not company_url and apply_url:
                import re
                m = re.search(r'greenhouse\.io/([^/]+)', apply_url)
                if m:
                    company_url = f"https://{m.group(1)}.com"
                m2 = re.search(r'lever\.co/([^/]+)', apply_url)
                if m2:
                    company_url = f"https://{m2.group(1)}.com"
                m3 = re.search(r'ashbyhq\.com/([^/]+)', apply_url)
                if m3:
                    company_url = f"https://{m3.group(1)}.com"

            careers_data = None
            company_data = None
            posting_data = {"title": title, "company": company, "description": description[:3000]}

            # Check TinyFishBriefCache for existing scrape data
            cached_tf = None
            try:
                from sqlalchemy import select as _select

                from app.db.models.tinyfish_cache import TinyFishBriefCache
                _normalized = company.lower().strip()
                async with async_session() as cache_db:
                    result = await cache_db.execute(
                        _select(TinyFishBriefCache).where(
                            TinyFishBriefCache.user_id == user_id,
                            TinyFishBriefCache.company_normalized == _normalized
                        )
                    )
                    cached_tf = result.scalar_one_or_none()
            except Exception as e:
                logger.warning("Research cascade: TinyFish cache lookup failed: %s", e)

            if cached_tf:
                # Use cached TinyFish data — skip scraping entirely
                logger.info("Research cascade: using cached TinyFish data for %s", company)
                if cached_tf.careers_data:
                    try:
                        careers_data = _json.loads(cached_tf.careers_data)
                    except (ValueError, TypeError):
                        pass
                if cached_tf.company_data:
                    try:
                        company_data = _json.loads(cached_tf.company_data)
                    except (ValueError, TypeError):
                        pass
            elif company_url:
                # No cache — call TinyFish (import only when needed)
                logger.info("Research cascade: TinyFish scraping %s", company_url)
                from app.services.recon.sources import fetch_about_page, fetch_careers_page

                try:
                    careers_data = await fetch_careers_page(company, company_url)
                    logger.info("Research cascade: careers page scraped for %s", company)
                except Exception as e:
                    logger.warning("Research cascade: careers scrape failed: %s", e)

                try:
                    company_data = await fetch_about_page(company, company_url)
                    logger.info("Research cascade: about page scraped for %s", company)
                except Exception as e:
                    logger.warning("Research cascade: about scrape failed: %s", e)

                # Cache raw TinyFish data to dedicated table
                try:
                    from uuid import uuid4 as _uuid4

                    from app.db.models.tinyfish_cache import TinyFishBriefCache
                    async with async_session() as cache_db:
                        cached = TinyFishBriefCache(
                            id=f"tfc_{_uuid4().hex[:12]}",
                            user_id=user_id,
                            company_normalized=company.lower().strip(),
                            company_display=company,
                            careers_data=_json.dumps(careers_data, default=str) if careers_data else None,
                            company_data=_json.dumps(company_data, default=str) if company_data else None,
                            sources_completed=_json.dumps(["posting"] + (["careers"] if careers_data else []) + (["company"] if company_data else [])),
                            sources_failed=_json.dumps([]),
                        )
                        cache_db.add(cached)
                        await cache_db.commit()
                    logger.info("Research cascade: cached TinyFish data for %s", company)
                except Exception as e:
                    logger.warning("Research cascade: TinyFish cache save failed: %s", e)
            else:
                logger.info("Research cascade: no company URL for %s, LLM-only brief", company)

            # LLM synthesizes from TinyFish data (cached or fresh) + posting
            synthesis = await synthesize_dossier(company, careers_data, company_data, posting_data)
            brief_data["company_brief"] = {
                "summary": synthesis.get("summary"),
                "hiring_velocity": synthesis.get("hiring_velocity"),
                "tech_stack": synthesis.get("tech_stack", []),
                "team_insight": synthesis.get("team_insight"),
                "insider_tip": synthesis.get("insider_tip"),
                "confidence": synthesis.get("confidence", "low"),
            }
            await log_activity(
                user_id=user_id,
                event_type="research_completed",
                title=f"Company Brief ready: {company}",
                description="Foxhound researched this company and assembled your brief.",
                metadata={"application_id": application_id, "job_id": job_id, "company": company, "title": title, "section": "company_brief"},
            )
            logger.info("Research cascade: company brief done for %s", company)
          except Exception as e:
            logger.warning("Research cascade: company brief failed: %s", e)
            brief_data["company_brief"] = {"error": str(e)}

        # Save partial brief so the UI can show company data while LinkedIn runs
        from app.services.research.brief_assembler import assemble_brief
        await assemble_brief(user_id, application_id, brief_data)

        # Step 2: Network Map — re-check brief in case it was updated
        has_network = False
        try:
            async with async_session() as check_db:
                _br = await check_db.execute(
                    select(FoxhoundBrief).where(FoxhoundBrief.application_id == application_id)
                )
                _current = _br.scalar_one_or_none()
                if _current and _current.network_map_json:
                    nm_check = _json.loads(_current.network_map_json)
                    # Only skip if we have actual contacts, not a "no_results" placeholder
                    if nm_check.get("contacts") and len(nm_check["contacts"]) > 0:
                        has_network = True
                        brief_data["network_map"] = nm_check
                        logger.info("Research cascade: network map exists with %d contacts, skipping for %s", len(nm_check["contacts"]), company)
        except Exception as e:
            logger.warning("Research cascade: failed to check network map status for %s: %s", application_id, e)
        if not has_network:
          try:
            # Check TinyFishBriefCache for cached contacts first
            cached_contacts = None
            try:
                from app.db.models.tinyfish_cache import TinyFishBriefCache
                _normalized = company.lower().strip()
                async with async_session() as cache_db:
                    _cr = await cache_db.execute(
                        select(TinyFishBriefCache).where(
                            TinyFishBriefCache.user_id == user_id,
                            TinyFishBriefCache.company_normalized == _normalized
                        )
                    )
                    _cached = _cr.scalar_one_or_none()
                    if _cached and _cached.network_contacts:
                        cached_contacts = _json.loads(_cached.network_contacts)
            except Exception:
                pass

            if cached_contacts and len(cached_contacts) > 0:
                logger.info("Research cascade: using %d cached contacts for %s", len(cached_contacts), company)
                brief_data["network_map"] = {
                    "status": "found",
                    "company": company,
                    "contacts": cached_contacts,
                    "count": len(cached_contacts),
                }
            else:
                from app.services.agent.tools.network import network_map
                async with async_session() as net_db:
                    network_result = await network_map(net_db, user_id, {
                        "company_name": company,
                        "department": title,
                        "role_context": title,
                    })
                brief_data["network_map"] = network_result

                # Cache contacts to TinyFishBriefCache
                contacts_to_cache = network_result.get("contacts", [])
                if contacts_to_cache:
                    try:
                        from app.db.models.tinyfish_cache import TinyFishBriefCache
                        _normalized = company.lower().strip()
                        async with async_session() as cache_db:
                            _cr = await cache_db.execute(
                                select(TinyFishBriefCache).where(
                                    TinyFishBriefCache.user_id == user_id,
                                    TinyFishBriefCache.company_normalized == _normalized
                                )
                            )
                            _cached = _cr.scalar_one_or_none()
                            if _cached:
                                _cached.network_contacts = _json.dumps(contacts_to_cache)
                                cache_db.add(_cached)
                                await cache_db.commit()
                                logger.info("Research cascade: cached %d contacts for %s", len(contacts_to_cache), company)
                    except Exception as e:
                        logger.warning("Research cascade: contacts cache save failed: %s", e)

            await log_activity(
                user_id=user_id,
                event_type="research_completed",
                title=f"Contacts found: {company}",
                description=f"Foxhound searched LinkedIn for people at {company}.",
                metadata={"application_id": application_id, "job_id": job_id, "company": company, "title": title, "section": "network_map"},
            )
            logger.info("Research cascade: network map done for %s", company)
          except Exception as e:
            logger.warning("Research cascade: network map failed: %s", e)
            brief_data["network_map"] = {"error": str(e)}

        # Save partial brief again so contacts show while pathfinder runs
        await assemble_brief(user_id, application_id, brief_data)

        # Step 3: Pathfinder — runs LAST, uses company + contacts data
        has_pathfinder = False
        try:
            async with async_session() as check_db:
                _br = await check_db.execute(
                    select(FoxhoundBrief).where(FoxhoundBrief.application_id == application_id)
                )
                _current = _br.scalar_one_or_none()
                if _current and _current.pathfinder_json:
                    has_pathfinder = True
                    brief_data["pathfinder"] = _json.loads(_current.pathfinder_json)
                    logger.info("Research cascade: pathfinder exists, skipping for %s", company)
        except Exception as e:
            logger.warning("Research cascade: failed to check pathfinder status for %s: %s", application_id, e)
        if not has_pathfinder:
          try:
            # Extract context from previous steps to feed into outreach
            company_context = None
            contacts_found = None
            cb = brief_data.get("company_brief", {})
            if isinstance(cb, dict) and not cb.get("error"):
                parts = []
                if cb.get("summary"): parts.append(cb["summary"])
                if cb.get("hiring_velocity"): parts.append(f"Hiring pace: {cb['hiring_velocity']}")
                if cb.get("insider_tip"): parts.append(f"Insider tip: {cb['insider_tip']}")
                if cb.get("tech_stack"): parts.append(f"Tech stack: {', '.join(cb['tech_stack'][:10])}")
                company_context = "\n".join(parts) if parts else None

            nm = brief_data.get("network_map", {})
            if isinstance(nm, dict) and not nm.get("error") and nm.get("contacts"):
                contacts_found = nm["contacts"]

            from app.services.agent.tools.pathfinder import find_hiring_manager
            async with async_session() as pf_db:
                pathfinder_result = await find_hiring_manager(
                    pf_db, user_id, {
                        "job_id": job_id,
                        "_company_context": company_context,
                        "_contacts_found": contacts_found,
                    },
                )
            brief_data["pathfinder"] = pathfinder_result
            await log_activity(
                user_id=user_id,
                event_type="research_completed",
                title=f"Outreach ready: {company}",
                description="Foxhound identified the best contact and drafted personalized outreach.",
                metadata={"application_id": application_id, "job_id": job_id, "company": company, "title": title, "section": "people_research"},
            )
            logger.info("Research cascade: pathfinder done for %s", company)
          except Exception as e:
            logger.warning("Research cascade: pathfinder failed: %s", e)
            brief_data["pathfinder"] = {"error": str(e)}

        # Merge real contacts into pathfinder — use the actual top person
        # instead of the LLM-guessed generic title
        pf = brief_data.get("pathfinder", {})
        nm = brief_data.get("network_map", {})
        if (isinstance(pf, dict) and not pf.get("error")
                and isinstance(nm, dict) and nm.get("contacts")):
            high_contacts = [c for c in nm["contacts"]
                            if isinstance(c, dict) and c.get("relevance") == "high"]
            top = high_contacts[0] if high_contacts else None
            if top and top.get("name") and top.get("title"):
                pf.setdefault("manager_signals", {})
                pf["manager_signals"]["likely_title"] = top["title"]
                pf["manager_signals"]["likely_name"] = top["name"]
                if top.get("linkedin_url"):
                    pf.setdefault("search_urls", {})
                    pf["search_urls"]["linkedin"] = top["linkedin_url"]
                logger.info("Research cascade: best contact → %s (%s)", top["name"], top["title"])
                brief_data["pathfinder"] = pf

        # Final assembly
        from app.services.research.brief_assembler import assemble_brief
        brief = await assemble_brief(user_id, application_id, brief_data)

        # Step 4: Emit research.completed event
        from app.services.events import FoxhoundEvent, emit
        await emit(FoxhoundEvent(
            name="research.completed",
            data={
                "user_id": user_id,
                "application_id": application_id,
                "brief_id": brief.id if brief else None,
                "company": brief_data.get("company", "Unknown"),
                "title": brief_data.get("title"),
            },
        ))

    except Exception:
        logger.exception("Research cascade failed for application %s", application_id)
