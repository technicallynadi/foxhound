"""Core models, coordinator, queue, locks, and event bus.

Note: To avoid circular imports, coordinator, queue, and lock_manager
must be imported from their modules directly:
    from foxhound.core.coordinator import Coordinator
    from foxhound.core.queue import JobQueue
    from foxhound.core.lock_manager import LockManager
"""

from foxhound.core.event_bus import EventBus
from foxhound.core.models import (
    EventEnvelope,
    EventSeverity,
    EventType,
    ExecutionMode,
    ExecutionSnapshot,
    ExecutionStrategy,
    JobEnvelope,
    JobPriority,
    JobStatus,
    JobType,
    Manifest,
    OpportunityDiscoveryItem,
    OpportunityState,
    PolicyRef,
    RecipeRef,
    ResultEnvelope,
    ResultStatus,
    RiskLevel,
    RunRecord,
    RunState,
    TaskEnvelope,
    TrustLevel,
    WorkItem,
    WorkItemKind,
    WorkItemState,
)

__all__ = [
    "EventBus",
    "EventEnvelope",
    "EventSeverity",
    "EventType",
    "ExecutionMode",
    "ExecutionSnapshot",
    "ExecutionStrategy",
    "JobEnvelope",
    "JobPriority",
    "JobStatus",
    "JobType",
    "Manifest",
    "OpportunityDiscoveryItem",
    "OpportunityState",
    "PolicyRef",
    "RecipeRef",
    "ResultEnvelope",
    "ResultStatus",
    "RiskLevel",
    "RunRecord",
    "RunState",
    "TaskEnvelope",
    "TrustLevel",
    "WorkItem",
    "WorkItemKind",
    "WorkItemState",
]
