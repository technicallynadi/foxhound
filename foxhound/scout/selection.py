"""Opportunity selection and task generation flow.

When a user approves an opportunity, this module handles deep analysis
and task breakdown generation. Creates executable work items from
approved opportunities. For repo-type opportunities, handles the
clone-with-review flow before task generation.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from foxhound.core.models import (
    OpportunityState,
    TrustLevel,
    WorkItem,
    WorkItemKind,
    WorkItemState,
)
from foxhound.scout.clone import CloneConfig, CloneManager, CloneRequest, CloneStatus
from foxhound.scout.opportunity import OpportunityManager
from foxhound.storage.database import Database, RawOpportunityStore, WorkItemStore


class GeneratedTask(BaseModel):
    """A task generated from deep analysis of an opportunity."""

    title: str = Field(..., description="Task title")
    description: str = Field(default="", description="Detailed description")
    complexity: str = Field(
        default="medium", description="Estimated complexity: low, medium, high"
    )
    tags: list[str] = Field(default_factory=list, description="Task tags")

    model_config = {"extra": "forbid"}


@dataclass
class DeepAnalysis:
    """Result of deep analysis on an approved opportunity."""

    opportunity_id: str
    summary: str = ""
    gaps: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    differentiation: str = ""
    tasks: list[GeneratedTask] = field(default_factory=list)


def analyze_opportunity(
    opportunity_id: str,
    raw_payload: dict[str, Any],
    source_type: str,
) -> DeepAnalysis:
    """Perform deep analysis on an approved opportunity.

    In V2 this will call the balanced tier model. For now, generates
    structured analysis from the raw data.
    """
    analysis = DeepAnalysis(opportunity_id=opportunity_id)

    title = raw_payload.get("name") or raw_payload.get("title", "")
    description = raw_payload.get("description") or raw_payload.get("selftext", "")
    language = raw_payload.get("language", "")
    stars = raw_payload.get("stars") or raw_payload.get("upvotes", 0)
    topics = raw_payload.get("topics", [])

    analysis.summary = (
        f"{title}: {description[:200]}"
        if description
        else f"{title} ({language or 'unknown language'}, {stars} stars)"
    )

    if not description or len(description) < 50:
        analysis.gaps.append("Missing or minimal documentation")
    if not topics:
        analysis.gaps.append("No topic tags or categorization")

    open_issues = raw_payload.get("open_issues", 0)
    if open_issues > 50:
        analysis.gaps.append(f"High open issue count ({open_issues})")

    if stars < 100:
        analysis.risks.append("Low traction — may not have market validation")
    if not language:
        analysis.risks.append("No primary language detected")

    analysis.differentiation = (
        f"Build a focused, well-documented alternative to {title} "
        f"with better developer experience"
    )

    tasks = _generate_tasks(title, language, analysis.gaps, topics)
    analysis.tasks = tasks

    return analysis


def _generate_tasks(
    title: str,
    language: str,
    gaps: list[str],
    topics: list[str],
) -> list[GeneratedTask]:
    """Generate a task breakdown from analysis results."""
    tasks: list[GeneratedTask] = []

    tasks.append(GeneratedTask(
        title=f"Set up project scaffold for {title} alternative",
        description=(
            f"Initialize project structure with {language or 'appropriate language'}, "
            f"configure build tools, linting, and CI"
        ),
        complexity="low",
        tags=["setup", "scaffold"],
    ))

    tasks.append(GeneratedTask(
        title="Implement core functionality",
        description=(
            f"Build the primary feature set based on {title}'s capabilities "
            f"with improved API design"
        ),
        complexity="high",
        tags=["core", "implementation"],
    ))

    if "Missing or minimal documentation" in gaps:
        tasks.append(GeneratedTask(
            title="Write comprehensive documentation",
            description="Create README, API docs, and usage examples",
            complexity="medium",
            tags=["docs"],
        ))

    tasks.append(GeneratedTask(
        title="Add test suite",
        description="Write unit and integration tests for core functionality",
        complexity="medium",
        tags=["testing"],
    ))

    return tasks


_REPO_SOURCE_TYPES = {
    "github_trending", "hackernews", "reddit",
    "devto", "lobsters", "github_events", "newsapi", "producthunt", "rss",
}

_REPO_URL_HINTS = ("github.com/", "gitlab.com/", "bitbucket.org/")


def _looks_like_repo_url(url: str | None) -> bool:
    """Check if a source URL looks like a cloneable git repository."""
    if not url:
        return False
    return any(hint in url for hint in _REPO_URL_HINTS)


class SelectionPipeline:
    """Handles opportunity selection, deep analysis, and task creation.

    Bridges scout discovery with the execution engine by converting
    approved opportunities into executable work items. For repo-type
    opportunities, manages the clone-with-review flow.
    """

    def __init__(
        self,
        db: Database,
        clone_config: CloneConfig | None = None,
    ) -> None:
        self._db = db
        self._opp_mgr = OpportunityManager(db)
        self._raw_store = RawOpportunityStore(db)
        self._work_item_store = WorkItemStore(db)
        self._clone_mgr = CloneManager(clone_config)

    def deep_analyze(self, opportunity_id: str) -> DeepAnalysis:
        """Run deep analysis on an approved opportunity."""
        item = self._opp_mgr.get(opportunity_id)
        if item is None:
            raise ValueError(f"Opportunity {opportunity_id} not found")

        raw_payload = item.evidence or {}

        if not raw_payload and item.source_url:
            raw_payload = {"name": item.title, "description": item.description}

        return analyze_opportunity(
            opportunity_id=opportunity_id,
            raw_payload=raw_payload,
            source_type=item.source_type,
        )

    def create_tasks_from_analysis(
        self,
        opportunity_id: str,
        analysis: DeepAnalysis,
        repo_id: str,
        approved_indices: list[int] | None = None,
    ) -> list[WorkItem]:
        """Create work items from approved tasks in the analysis.

        Args:
            opportunity_id: The source opportunity.
            analysis: Deep analysis result.
            repo_id: Target repository ID.
            approved_indices: Indices of tasks to create. None means all.

        Returns:
            List of created work items.
        """
        tasks = analysis.tasks
        if approved_indices is not None:
            tasks = [tasks[i] for i in approved_indices if i < len(tasks)]

        created: list[WorkItem] = []
        for task in tasks:
            work_item = WorkItem(
                work_item_id=f"wi_{uuid4().hex[:12]}",
                repo_id=repo_id,
                kind=WorkItemKind.EXECUTION,
                title=task.title,
                description=task.description,
                source_type=f"scout:{analysis.opportunity_id}",
                source_fingerprint=f"task_{uuid4().hex[:8]}",
                trust_level=TrustLevel.SEMI_TRUSTED,
                state=WorkItemState.APPROVED,
                evidence={
                    "opportunity_id": opportunity_id,
                    "complexity": task.complexity,
                    "analysis_summary": analysis.summary,
                    "gaps": analysis.gaps,
                    "risks": analysis.risks,
                },
            )
            self._work_item_store.save(work_item)
            created.append(work_item)

        if created:
            item = self._opp_mgr.get(opportunity_id)
            if item and item.state == OpportunityState.APPROVED:
                self._opp_mgr.advance(
                    opportunity_id,
                    OpportunityState.CONVERTED_TO_PROJECT,
                )

        return created

    def is_repo_opportunity(self, opportunity_id: str) -> bool:
        """Check if an opportunity points to a cloneable repository."""
        item = self._opp_mgr.get(opportunity_id)
        if item is None:
            return False
        return _looks_like_repo_url(item.source_url)

    def prepare_clone_review(
        self, opportunity_id: str
    ) -> CloneRequest | None:
        """Prepare a clone request for user review.

        Returns None if the opportunity doesn't point to a repo.
        Does NOT clone — returns a CloneRequest in PENDING_REVIEW
        state with disclaimers for the user to review.
        """
        item = self._opp_mgr.get(opportunity_id)
        if item is None:
            raise ValueError(f"Opportunity {opportunity_id} not found")

        if not _looks_like_repo_url(item.source_url):
            return None

        return self._clone_mgr.prepare_clone(
            opportunity_id=opportunity_id,
            source_url=item.source_url or "",
        )

    def get_clone_review_summary(
        self, request: CloneRequest
    ) -> dict[str, object]:
        """Get the review summary with disclaimers for user display."""
        return self._clone_mgr.get_review_summary(request)

    def execute_approved_clone(
        self, request: CloneRequest
    ) -> CloneRequest:
        """Execute a clone after user has approved it.

        The request must have been explicitly set to APPROVED by
        the caller after the user reviewed the disclaimers.
        """
        return self._clone_mgr.execute_clone(request)

    def approve_and_generate(
        self,
        opportunity_id: str,
        repo_id: str,
    ) -> tuple[DeepAnalysis, list[WorkItem]]:
        """Full flow: approve opportunity, analyze, and generate all tasks."""
        item = self._opp_mgr.get(opportunity_id)
        if item is None:
            raise ValueError(f"Opportunity {opportunity_id} not found")

        if item.state == OpportunityState.SUGGESTED:
            self._opp_mgr.approve(opportunity_id)

        analysis = self.deep_analyze(opportunity_id)
        tasks = self.create_tasks_from_analysis(
            opportunity_id, analysis, repo_id,
        )
        return analysis, tasks

    def approve_and_clone(
        self,
        opportunity_id: str,
        clone_request: CloneRequest,
    ) -> tuple[CloneRequest, DeepAnalysis | None, list[WorkItem]]:
        """Full flow for repo opportunities: clone, analyze, generate tasks.

        The clone_request must already be in APPROVED state (user reviewed
        disclaimers and confirmed). Returns the clone result, analysis,
        and generated work items.
        """
        item = self._opp_mgr.get(opportunity_id)
        if item is None:
            raise ValueError(f"Opportunity {opportunity_id} not found")

        if item.state == OpportunityState.SUGGESTED:
            self._opp_mgr.approve(opportunity_id)

        result = self._clone_mgr.execute_clone(clone_request)

        if result.status != CloneStatus.CLONED:
            return result, None, []

        repo_id = str(result.clone_path) if result.clone_path else opportunity_id

        analysis = self.deep_analyze(opportunity_id)
        tasks = self.create_tasks_from_analysis(
            opportunity_id, analysis, repo_id,
        )
        return result, analysis, tasks
