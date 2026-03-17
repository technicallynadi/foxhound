"""Scout session endpoints: start runs and stream progress via SSE."""

import asyncio
import json
import logging
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends
from starlette.responses import StreamingResponse

from foxhound.api.dependencies import get_db
from foxhound.api.schemas import ScoutStartRequest, ScoutStartResponse
from foxhound.scout.fetcher import ScoutConfig, ScoutFetcher
from foxhound.scout.scoring import ScoringPipeline
from foxhound.storage.database import Database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scout", tags=["scout"])

_sessions: dict[str, asyncio.Queue[dict | None]] = {}


def _run_scout(session_id: str, db: Database, topics: list[str]) -> None:
    """Execute fetch + score pipeline, pushing events to the session queue."""
    queue = _sessions.get(session_id)
    if queue is None:
        return

    loop = asyncio.new_event_loop()

    try:
        import json as json_mod
        import os
        import urllib.request
        from urllib.error import HTTPError, URLError

        from foxhound.adapters.github_connector import HttpResponse

        class _UrllibClient:
            """Minimal HTTP client implementing the HttpClient protocol."""

            def get(self, url: str, headers: dict | None = None, params: dict | None = None, timeout: int = 30) -> HttpResponse:
                if params:
                    from urllib.parse import urlencode
                    url = f"{url}?{urlencode(params)}"
                req = urllib.request.Request(url, headers=headers or {})
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as resp:
                        body = resp.read().decode()
                        try:
                            data = json_mod.loads(body)
                        except Exception:
                            data = None
                        return HttpResponse(
                            status_code=resp.status,
                            headers=dict(resp.headers),
                            json_data=data,
                        )
                except HTTPError as e:
                    return HttpResponse(
                        status_code=e.code,
                        headers=dict(e.headers) if e.headers else {},
                        json_data=None,
                    )
                except (URLError, TimeoutError):
                    return HttpResponse(status_code=0, headers={}, json_data=None)

        config = ScoutConfig(topics=topics)
        fetcher = ScoutFetcher(
            db=db,
            http_client=_UrllibClient(),
            config=config,
            github_token=os.environ.get("GITHUB_TOKEN"),
            reddit_client_id=os.environ.get("REDDIT_CLIENT_ID"),
            reddit_client_secret=os.environ.get("REDDIT_CLIENT_SECRET"),
        )
        summary = fetcher.fetch_all(force_refresh=True)

        for result in summary.results:
            event = {
                "event": "source_complete",
                "data": {
                    "source": result.source,
                    "items": result.items_fetched,
                    "new": result.new_items,
                    "error": result.error,
                },
            }
            loop.run_until_complete(queue.put(event))

        total_raw = summary.total_new + summary.total_updated
        loop.run_until_complete(queue.put({
            "event": "enriching",
            "data": {"count": total_raw},
        }))

        pipeline = ScoringPipeline(db=db, topics=topics)
        scoring_result = pipeline.score_all()

        loop.run_until_complete(queue.put({
            "event": "complete",
            "data": {
                "total": scoring_result.passed,
                "filtered": scoring_result.filtered,
                "processed": scoring_result.processed,
            },
        }))
    except Exception:
        logger.exception("Scout session %s failed", session_id)
        loop.run_until_complete(queue.put({
            "event": "error",
            "data": {"message": "Scout run failed unexpectedly"},
        }))
    finally:
        loop.run_until_complete(queue.put(None))
        loop.close()


@router.post("/start", response_model=ScoutStartResponse)
def start_scout(
    request: ScoutStartRequest,
    background_tasks: BackgroundTasks,
    db: Database = Depends(get_db),
) -> ScoutStartResponse:
    """Start a new scout session as a background task."""
    session_id = f"scout_{uuid4().hex[:12]}"
    _sessions[session_id] = asyncio.Queue()
    background_tasks.add_task(_run_scout, session_id, db, request.topics)
    return ScoutStartResponse(session_id=session_id, status="started")


@router.get("/stream/{session_id}")
async def stream_scout(session_id: str) -> StreamingResponse:
    """Stream scout progress as Server-Sent Events."""
    queue = _sessions.get(session_id)
    if queue is None:
        async def not_found() -> None:
            yield f"data: {json.dumps({'event': 'error', 'data': {'message': 'Session not found'}})}\n\n"
        return StreamingResponse(not_found(), media_type="text/event-stream")

    async def event_generator() -> None:
        try:
            while True:
                event = await queue.get()
                if event is None:
                    yield f"event: done\ndata: {json.dumps({})}\n\n"
                    break
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
        finally:
            _sessions.pop(session_id, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
