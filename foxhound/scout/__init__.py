"""External opportunity discovery."""

from foxhound.scout.engine import ScoutEngine, ScoutSource, ScoutWorker
from foxhound.scout.fetcher import FetchResult, FetchSummary, ScoutConfig, ScoutFetcher
from foxhound.scout.opportunity import OpportunityManager
from foxhound.scout.scoring import ScoringPipeline, ScoringPreferences, ScoringResult
from foxhound.scout.selection import DeepAnalysis, GeneratedTask, SelectionPipeline

__all__ = [
    "DeepAnalysis",
    "FetchResult",
    "FetchSummary",
    "GeneratedTask",
    "OpportunityManager",
    "ScoutConfig",
    "ScoutEngine",
    "ScoutFetcher",
    "ScoutSource",
    "ScoutWorker",
    "ScoringPipeline",
    "ScoringPreferences",
    "ScoringResult",
    "SelectionPipeline",
]
