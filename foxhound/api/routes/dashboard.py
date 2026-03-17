"""Dashboard aggregate endpoints."""

from fastapi import APIRouter, Depends

from foxhound.api.dependencies import get_db
from foxhound.api.schemas import ActivityItem, DashboardStatsResponse
from foxhound.storage.database import Database

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStatsResponse)
def get_stats(db: Database = Depends(get_db)) -> DashboardStatsResponse:
    """Return aggregate opportunity statistics."""
    with db.connection() as conn:
        total_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM opportunity_items"
        ).fetchone()
        total = total_row["cnt"] if total_row else 0

        approved_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM opportunity_items WHERE state = 'approved'"
        ).fetchone()
        approved = approved_row["cnt"] if approved_row else 0

        topic_rows = conn.execute(
            "SELECT DISTINCT matched_topic FROM opportunity_items "
            "WHERE matched_topic != '' AND matched_topic IS NOT NULL"
        ).fetchall()
        topics = [row["matched_topic"] for row in topic_rows]

        avg_row = conn.execute(
            "SELECT AVG(opportunity_score) as avg_score FROM opportunity_items "
            "WHERE state = 'suggested'"
        ).fetchone()
        avg_score = avg_row["avg_score"] if avg_row and avg_row["avg_score"] else 0.0

    return DashboardStatsResponse(
        total_opportunities=total,
        total_approved=approved,
        active_topics=topics,
        recent_score_avg=round(avg_score, 2),
    )


@router.get("/activity", response_model=list[ActivityItem])
def get_activity(db: Database = Depends(get_db)) -> list[ActivityItem]:
    """Return recent activity feed from opportunity state changes."""
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT opportunity_id, title, state, updated_at "
            "FROM opportunity_items ORDER BY updated_at DESC LIMIT 20"
        ).fetchall()

    return [
        ActivityItem(
            description=f"{row['title']} moved to {row['state']}",
            timestamp=row["updated_at"],
            type=row["state"],
        )
        for row in rows
    ]
