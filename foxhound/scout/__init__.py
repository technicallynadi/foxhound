"""External opportunity discovery."""

from foxhound.scout.engine import ScoutEngine, ScoutSource, ScoutWorker
from foxhound.scout.opportunity import OpportunityManager

__all__ = [
    "OpportunityManager",
    "ScoutEngine",
    "ScoutSource",
    "ScoutWorker",
]
