"""Pydantic response models for the Foxhound API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class OpportunityResponse(BaseModel):
    """Serialized opportunity item for API responses."""

    opportunity_id: str
    title: str
    description: str = ""
    source_type: str
    source_url: str | None = None
    source_fingerprint: str
    trust_level: str
    state: str

    signal_tier: str | None = None
    signal_type: str = ""

    problem_intensity: float = 0.0
    frequency: float = 0.0
    workaround_presence: float = 0.0
    market_potential: float = 0.0
    build_feasibility: float = 0.0
    topic_relevance: float = 0.0
    opportunity_score: float = 0.0
    confidence_level: str = "low"

    ai_exposure_score: float = 0.0
    ai_exposure_angle: str | None = None

    matched_topic: str = ""
    enrichment_summary: str = ""
    distribution_channels: list[str] = Field(default_factory=list)

    recommended_product: str = ""
    mvp_features: list[str] = Field(default_factory=list)
    suggested_stack: str = ""
    estimated_build_time: str = ""
    estimated_build_cost: str = ""

    credibility_score: float = 0.0
    novelty_score: float = 0.0
    actionability_score: float = 0.0
    business_value_score: float = 0.0

    evidence: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OpportunityListResponse(BaseModel):
    """Paginated list of opportunities."""

    items: list[OpportunityResponse]
    total: int


class ScoutStartRequest(BaseModel):
    """Request to start a scout session."""

    topics: list[str]


class ScoutStartResponse(BaseModel):
    """Response after starting a scout session."""

    session_id: str
    status: str


class ScoutProgressEvent(BaseModel):
    """Progress event emitted during scout run."""

    source: str
    status: str
    items_found: int


class DashboardStatsResponse(BaseModel):
    """Aggregate dashboard statistics."""

    total_opportunities: int
    total_approved: int
    active_topics: list[str]
    recent_score_avg: float


class ActivityItem(BaseModel):
    """Single activity feed entry."""

    description: str
    timestamp: str
    type: str


class ApproveResponse(BaseModel):
    """Response after approving or dismissing an opportunity."""

    opportunity_id: str
    new_state: str
