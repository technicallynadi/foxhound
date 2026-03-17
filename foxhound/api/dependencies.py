"""FastAPI dependency injection providers."""

from fastapi import Depends, Request

from foxhound.scout.opportunity import OpportunityManager
from foxhound.storage.database import Database, OpportunityStore


def get_db(request: Request) -> Database:
    """Return the Database instance from application state."""
    return request.app.state.db


def get_opportunity_store(db: Database = Depends(get_db)) -> OpportunityStore:
    """Return an OpportunityStore bound to the current database."""
    return OpportunityStore(db)


def get_opportunity_manager(db: Database = Depends(get_db)) -> OpportunityManager:
    """Return an OpportunityManager bound to the current database."""
    return OpportunityManager(db)
