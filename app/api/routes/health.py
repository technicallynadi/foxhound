from fastapi import APIRouter

from app.api.schemas.response import HealthResponse
from app.services.run_service import get_queue_health

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health():
    queue = await get_queue_health()
    return HealthResponse(status="ok", version="0.1.0", queue=queue)
