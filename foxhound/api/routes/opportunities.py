"""Opportunity CRUD and lifecycle endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query

from foxhound.api.dependencies import get_db, get_opportunity_manager, get_opportunity_store
from foxhound.api.schemas import ApproveResponse, OpportunityListResponse, OpportunityResponse
from foxhound.core.models import OpportunityDiscoveryItem, OpportunityState
from foxhound.scout.opportunity import OpportunityManager
from foxhound.storage.database import Database, OpportunityStore

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


def _to_response(item: OpportunityDiscoveryItem) -> OpportunityResponse:
    """Convert a domain model to an API response."""
    return OpportunityResponse(
        opportunity_id=item.opportunity_id,
        title=item.title,
        description=item.description,
        source_type=item.source_type,
        source_url=item.source_url,
        source_fingerprint=item.source_fingerprint,
        trust_level=item.trust_level.value,
        state=item.state.value,
        signal_tier=item.signal_tier.value if item.signal_tier else None,
        signal_type=item.signal_type,
        problem_intensity=item.problem_intensity,
        frequency=item.frequency,
        workaround_presence=item.workaround_presence,
        market_potential=item.market_potential,
        build_feasibility=item.build_feasibility,
        topic_relevance=item.topic_relevance,
        opportunity_score=item.opportunity_score,
        confidence_level=item.confidence_level.value,
        ai_exposure_score=item.ai_exposure_score,
        ai_exposure_angle=item.ai_exposure_angle.value if item.ai_exposure_angle else None,
        matched_topic=item.matched_topic,
        enrichment_summary=item.enrichment_summary,
        distribution_channels=item.distribution_channels,
        recommended_product=item.recommended_product,
        mvp_features=item.mvp_features,
        suggested_stack=item.suggested_stack,
        estimated_build_time=item.estimated_build_time,
        estimated_build_cost=item.estimated_build_cost,
        credibility_score=item.credibility_score,
        novelty_score=item.novelty_score,
        actionability_score=item.actionability_score,
        business_value_score=item.business_value_score,
        evidence=item.evidence,
        tags=item.tags,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/", response_model=OpportunityListResponse)
def list_opportunities(
    state: str = Query("suggested", description="Filter by opportunity state"),
    sort_by: str = Query("score", description="Sort by 'score' or 'date'"),
    source_filter: str | None = Query(None, description="Filter by source_type"),
    topic_filter: str | None = Query(None, description="Filter by matched_topic"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_db),
) -> OpportunityListResponse:
    """List opportunities with filtering, sorting, and pagination."""
    try:
        opp_state = OpportunityState(state)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid state: {state}")

    order_col = "opportunity_score DESC" if sort_by == "score" else "updated_at DESC"

    where_clauses = ["state = ?"]
    params: list[str | int] = [opp_state.value]

    if source_filter:
        where_clauses.append("source_type = ?")
        params.append(source_filter)
    if topic_filter:
        where_clauses.append("matched_topic = ?")
        params.append(topic_filter)

    where_sql = " AND ".join(where_clauses)

    with db.connection() as conn:
        count_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM opportunity_items WHERE {where_sql}",
            tuple(params),
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        rows = conn.execute(
            f"SELECT * FROM opportunity_items WHERE {where_sql} "
            f"ORDER BY {order_col} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()

    store = OpportunityStore(db)
    items = [_to_response(store._row_to_model(row)) for row in rows]
    return OpportunityListResponse(items=items, total=total)


@router.get("/{opportunity_id}", response_model=OpportunityResponse)
def get_opportunity(
    opportunity_id: str,
    store: OpportunityStore = Depends(get_opportunity_store),
) -> OpportunityResponse:
    """Get a single opportunity with full detail."""
    item = store.get(opportunity_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return _to_response(item)


@router.post("/{opportunity_id}/approve", response_model=ApproveResponse)
def approve_opportunity(
    opportunity_id: str,
    manager: OpportunityManager = Depends(get_opportunity_manager),
) -> ApproveResponse:
    """Approve an opportunity."""
    try:
        item = manager.approve(opportunity_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ApproveResponse(opportunity_id=item.opportunity_id, new_state=item.state.value)


@router.post("/{opportunity_id}/dismiss", response_model=ApproveResponse)
def dismiss_opportunity(
    opportunity_id: str,
    manager: OpportunityManager = Depends(get_opportunity_manager),
) -> ApproveResponse:
    """Dismiss (reject) an opportunity."""
    try:
        item = manager.reject(opportunity_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ApproveResponse(opportunity_id=item.opportunity_id, new_state=item.state.value)
