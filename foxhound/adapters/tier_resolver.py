"""Tier resolution for execution.

Resolves the effective model tier for a worker execution by combining
the worker's default tier, the recipe's tier overrides, and the
execution snapshot's tier setting.
"""

from foxhound.adapters.registry import get_worker_default_tier
from foxhound.core.models import ModelTier


def resolve_effective_tier(
    worker_type: str,
    snapshot_tier: ModelTier,
    recipe_tier_overrides: dict[str, str] | None = None,
    step_name: str | None = None,
) -> ModelTier:
    """Resolve the effective model tier for a worker execution.

    Priority (highest first):
    1. Recipe tier override for the specific step
    2. Execution snapshot tier (set at queue time)
    3. Worker default tier

    Args:
        worker_type: Worker class name (e.g., 'ExecutionWorker').
        snapshot_tier: Tier from the frozen execution snapshot.
        recipe_tier_overrides: Optional tier overrides from the recipe.
        step_name: Optional step name for recipe override lookup
            (e.g., 'execution', 'review_intermediate', 'review_final').

    Returns:
        The effective ModelTier to use.
    """
    # Check recipe tier override for the specific step
    if recipe_tier_overrides and step_name:
        override = recipe_tier_overrides.get(step_name)
        if override:
            try:
                return ModelTier(override)
            except ValueError:
                pass

    # Check recipe tier override for the worker type
    if recipe_tier_overrides:
        worker_key = _worker_type_to_step(worker_type)
        override = recipe_tier_overrides.get(worker_key)
        if override:
            try:
                return ModelTier(override)
            except ValueError:
                pass

    # Use snapshot tier if explicitly set (not the default balanced)
    if snapshot_tier != get_worker_default_tier(worker_type):
        return snapshot_tier

    # Fall back to worker default
    return get_worker_default_tier(worker_type)


def _worker_type_to_step(worker_type: str) -> str:
    """Map worker type names to recipe step names.

    Args:
        worker_type: Worker class name.

    Returns:
        Corresponding recipe step name.
    """
    mapping: dict[str, str] = {
        "ExecutionWorker": "execution",
        "CodeReviewWorker": "review_final",
        "SecurityReviewWorker": "security_review",
        "DiscoveryWorker": "discovery",
        "ScoutWorker": "scout",
        "AnalyzerWorker": "analysis",
    }
    return mapping.get(worker_type, worker_type.lower().replace("worker", ""))
