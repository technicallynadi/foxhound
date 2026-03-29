import logging
from pathlib import Path

from app.ml.setfit_relevance import train as train_relevance
from app.ml.lightgbm_ranker import train as train_ranker

logger = logging.getLogger(__name__)

DATASET_DIR = Path(__file__).parent.parent.parent / "data" / "datasets"


async def run_training(component: str, dataset_path: str | None = None, version: str = "v0_1") -> dict:
    """Run training for a specific ML component."""

    if component == "relevance":
        path = dataset_path or _find_rolling_dataset() or _find_latest_dataset("relevance_")
        if not path:
            return {"error": "No relevance dataset found"}
        result = train_relevance(path, output_version=version)
        return result

    elif component == "ranker":
        path = dataset_path or _find_latest_dataset("ranker_")
        if not path:
            return {"error": "No ranker dataset found"}
        result = train_ranker(path, output_version=version)
        return result

    else:
        return {"error": f"Unknown component: {component}"}


def _find_rolling_dataset() -> str | None:
    """Find the rolling training dataset if it exists and has enough data."""
    rolling = DATASET_DIR / "rolling_training_data.jsonl"
    if rolling.exists() and rolling.stat().st_size > 0:
        return str(rolling)
    return None


def _find_latest_dataset(prefix: str) -> str | None:
    """Find the latest dataset file matching the prefix."""
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    candidates = sorted(DATASET_DIR.glob(f"{prefix}*.jsonl"))
    return str(candidates[-1]) if candidates else None
