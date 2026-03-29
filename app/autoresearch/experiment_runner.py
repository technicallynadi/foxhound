import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.autoresearch.registry import register_version
from app.autoresearch.evaluator import evaluate_pipeline_run

logger = logging.getLogger(__name__)

EXPERIMENTS_DIR = Path(__file__).parent.parent.parent / "data" / "experiments"


async def run_pipeline_experiment(
    query: str,
    sources: list[str],
    variant_id: str,
    config_overrides: dict | None = None,
) -> dict:
    """Run a single pipeline experiment and evaluate it."""
    from app.services.pipeline import run_pipeline

    result = await run_pipeline(
        topic=query,
        sources=sources,
        debug=True,
        limit=10,
    )

    debug_data = result.get("debug", {})
    metrics = evaluate_pipeline_run(debug_data)
    metrics["num_results"] = len(result.get("results", []))
    metrics["top_score"] = max(
        (r.get("opportunity_score", 0) for r in result.get("results", [])),
        default=0,
    )

    experiment = {
        "variant_id": variant_id,
        "query": query,
        "sources": sources,
        "config_overrides": config_overrides or {},
        "metrics": metrics,
        "num_results": len(result.get("results", [])),
        "result_titles": [r.get("title", "")[:80] for r in result.get("results", [])],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    _save_experiment(experiment)
    return experiment


def compare_experiments(experiments: list[dict], metric_key: str = "num_results") -> dict:
    """Compare multiple experiment results and pick the best."""
    if not experiments:
        return {"winner": None}

    def _get_metric(exp: dict) -> float:
        metrics = exp.get("metrics", {})
        if metric_key in metrics:
            return metrics[metric_key]
        return exp.get(metric_key, 0)

    sorted_exps = sorted(experiments, key=_get_metric, reverse=True)
    winner = sorted_exps[0]

    return {
        "winner": winner["variant_id"],
        "winner_score": _get_metric(winner),
        "all_scores": {
            e["variant_id"]: _get_metric(e)
            for e in sorted_exps
        },
    }


def should_promote(
    candidate_metrics: dict,
    baseline_metrics: dict,
    improvement_threshold: float = 0.05,
) -> dict:
    """Determine if a candidate should be promoted over baseline."""
    improvements = {}
    regressions = {}

    for key in candidate_metrics:
        if key not in baseline_metrics:
            continue
        c_val = candidate_metrics[key]
        b_val = baseline_metrics[key]
        if not isinstance(c_val, (int, float)) or not isinstance(b_val, (int, float)):
            continue

        diff = c_val - b_val
        if diff > 0:
            improvements[key] = round(diff, 4)
        elif diff < 0:
            regressions[key] = round(diff, 4)

    net_improvement = sum(improvements.values()) - abs(sum(regressions.values()))
    promote = (
        net_improvement > improvement_threshold
        and len(regressions) <= 1  # allow at most 1 minor regression
    )

    return {
        "promote": promote,
        "improvements": improvements,
        "regressions": regressions,
        "net_improvement": round(net_improvement, 4),
    }


def _save_experiment(experiment: dict) -> None:
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    variant = experiment.get("variant_id", "unknown")
    filepath = EXPERIMENTS_DIR / f"exp_{variant}_{timestamp}.json"
    with open(filepath, "w") as f:
        json.dump(experiment, f, indent=2)
    logger.info("Saved experiment: %s", filepath.name)


def load_experiments(component: str | None = None) -> list[dict]:
    """Load all saved experiments, optionally filtered by component."""
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    experiments = []
    for filepath in sorted(EXPERIMENTS_DIR.glob("exp_*.json")):
        with open(filepath) as f:
            exp = json.load(f)
        if component is None or component in exp.get("variant_id", ""):
            experiments.append(exp)
    return experiments
