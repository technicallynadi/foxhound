import logging
import time
from contextlib import asynccontextmanager
from importlib import import_module

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

load_dotenv(override=True)

from app.core.logging import setup_logging
from app.db.session import init_db

_BOOT_T0 = time.perf_counter()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_t0 = time.perf_counter()
    setup_logging()
    logger.info("App import completed in %.3fs", time.perf_counter() - _BOOT_T0)
    await init_db()
    logger.info("Lifespan startup completed in %.3fs", time.perf_counter() - startup_t0)

    # Register event handlers (import triggers @on_event decorators)
    import app.services.events.handlers  # noqa: F401

    # Register recurring scheduled jobs
    from app.services.scheduling.scheduler import ensure_recurring_jobs
    await ensure_recurring_jobs()

    # Start background loops
    import asyncio
    from app.services.apply.timeout_loop import application_timeout_loop
    from app.services.run_service import worker_loop

    timeout_task = asyncio.create_task(application_timeout_loop())
    worker_task = asyncio.create_task(worker_loop(poll_interval=5.0))

    yield

    timeout_task.cancel()
    worker_task.cancel()


app = FastAPI(
    title="Foxhound",
    version="0.1.0",
    description="AI Job Agent — Find jobs, apply automatically",
    lifespan=lifespan,
)

from app.core.errors import FoxhoundError, foxhound_error_handler
app.add_exception_handler(FoxhoundError, foxhound_error_handler)

from starlette.middleware.cors import CORSMiddleware
import os as _os

_cors_origins = _os.environ.get("FOXHOUND_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str((__import__("pathlib").Path(__file__).resolve().parent / "static"))), name="static")


def _include_router(module_path: str) -> None:
    module = import_module(module_path)
    app.include_router(module.router)


for module_path in (
    "app.api.routes.auth",
    "app.api.routes.health",
    "app.api.routes.notifications",
    "app.api.routes.notification_destinations",
    "app.api.routes.waitlist",
    "app.api.routes.feedback",
    # --- Foxhound core ---
    "app.api.routes.profile",
    "app.api.routes.jobs",
    "app.api.routes.applications",
    # --- Foxhound Recon ---
    "app.api.routes.recon",
    # --- Foxhound Pathfinder ---
    "app.api.routes.pathfinder",
    # --- Foxhound Watchdog ---
    "app.api.routes.watchdog",
    # --- Foxhound Dossier ---
    "app.api.routes.dossier",
    # --- Ghost Job Detector ---
    "app.api.routes.ghost_check",
    # --- Intelligence Hub ---
    "app.api.routes.intelligence",
    # --- Slack Bot ---
    "app.api.routes.slack_bot",
    # --- Activity Feed + Brief ---
    "app.api.routes.activity",
    "app.api.routes.brief",
    # --- FoxhoundAgent ---
    "app.api.routes.agent",
    "app.api.routes.agent_webhooks",
    "app.api.routes.dashboard",
    "app.api.routes.settings",
    "app.api.routes.matches",
    "app.api.routes.files",
):
    _include_router(module_path)
