"""FastAPI application setup for Foxhound."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from foxhound.api.routes import dashboard, opportunities, scout
from foxhound.storage.database import Database

DEFAULT_DB_PATH = ".foxhound/foxhound.db"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize database on startup, clean up on shutdown."""
    db = Database(db_path=DEFAULT_DB_PATH)
    app.state.db = db
    yield


app = FastAPI(title="Foxhound API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scout.router)
app.include_router(opportunities.router)
app.include_router(dashboard.router)
