"""LightGBM LambdaRank ranker for opportunity ranking.

Replaces hand-tuned heuristic once enough labeled feedback data exists.
Uses LambdaRank objective (pairwise learning-to-rank) with NDCG evaluation.
"""

import json
import logging
import math
from pathlib import Path

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent.parent.parent / "data" / "models"
_model = None
_is_loaded = False

MIN_TRAINING_SAMPLES = 500
MIN_TRAINING_GROUPS = 50

RANKING_FEATURES = [
    "evidence_count", "breakpoint_count", "workaround_count",
    "incumbent_failure_count", "source_count", "tool_count",
    "has_grounded_persona", "has_breakpoint", "has_workaround",
    "has_incumbent_failure", "pain_type_count", "base_opportunity_score",
    "frequency_score", "pain_intensity_score", "workaround_score_base",
    "cross_source_score", "buyer_quality_score", "buildability_score",
    "freshness_score", "execution_ready_score", "avg_signal_quality",
    "source_diversity_count",
]


def is_available() -> bool:
    return _is_loaded


def load_model(version: str = "latest") -> bool:
    global _model, _is_loaded

    model_path = MODEL_DIR / f"ranker_model_{version}.txt"
    if not model_path.exists():
        candidates = sorted(MODEL_DIR.glob("ranker_model_*.txt"))
        if not candidates:
            logger.info("No ranker model found — using rule-based fallback")
            return False
        model_path = candidates[-1]

    try:
        import lightgbm as lgb
        _model = lgb.Booster(model_file=str(model_path))
        _is_loaded = True
        logger.info("Loaded ranker model from %s", model_path)
        return True
    except Exception as e:
        logger.warning("Failed to load ranker model: %s", e)
        return False


def predict(features: dict) -> float | None:
    """Predict rank score from features."""
    if not _is_loaded or _model is None or not _HAS_NUMPY:
        return None

    try:
        feature_values = [float(features.get(f, 0)) for f in RANKING_FEATURES]
        X = np.array([feature_values])
        score = _model.predict(X)[0]
        return round(float(score), 4)
    except Exception as e:
        logger.warning("Ranker prediction failed: %s", e)
        return None


def should_graduate_to_ml(dataset_path: str) -> bool:
    """Check if we have enough labeled data to train a model."""
    try:
        rows = []
        with open(dataset_path) as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))

        if len(rows) < MIN_TRAINING_SAMPLES:
            return False

        groups = set(r.get("query_group", "") for r in rows)
        return len(groups) >= MIN_TRAINING_GROUPS
    except Exception:
        return False


def train(dataset_path: str, output_version: str = "v0_1") -> dict:
    """Train a LightGBM LambdaRank ranker from a JSONL dataset.

    Each row must have:
      - features: dict of feature name -> value
      - relevance_label: int 0-4
      - query_group: str (groups rows into ranking lists)
    """
    import lightgbm as lgb

    rows = []
    with open(dataset_path) as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    if len(rows) < MIN_TRAINING_SAMPLES:
        return {
            "error": f"Need at least {MIN_TRAINING_SAMPLES} labeled examples",
            "count": len(rows),
        }

    # Sort by query_group so LightGBM can read group boundaries
    rows.sort(key=lambda r: r.get("query_group", ""))

    X = np.array([
        [float(r.get("features", {}).get(f, 0)) for f in RANKING_FEATURES]
        for r in rows
    ])
    y = np.array([int(r.get("relevance_label", 0)) for r in rows])

    # Build group sizes
    groups = []
    current_group = None
    current_count = 0
    for r in rows:
        g = r.get("query_group", "default")
        if g != current_group:
            if current_group is not None:
                groups.append(current_count)
            current_group = g
            current_count = 1
        else:
            current_count += 1
    if current_count > 0:
        groups.append(current_count)

    if len(groups) < MIN_TRAINING_GROUPS:
        return {
            "error": f"Need at least {MIN_TRAINING_GROUPS} query groups",
            "group_count": len(groups),
        }

    # Split by groups (not individual rows)
    split_idx = int(len(groups) * 0.8)
    train_end = sum(groups[:split_idx])

    X_train, X_val = X[:train_end], X[train_end:]
    y_train, y_val = y[:train_end], y[train_end:]
    groups_train = groups[:split_idx]
    groups_val = groups[split_idx:]

    train_data = lgb.Dataset(X_train, label=y_train, group=groups_train)
    val_data = lgb.Dataset(X_val, label=y_val, group=groups_val, reference=train_data)

    params = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "eval_at": [5, 10],
        "num_leaves": 31,
        "learning_rate": 0.05,
        "min_data_in_leaf": 10,
        "min_data_per_group": 1,
        "max_depth": 6,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "lambdarank_truncation_level": 10,
        "verbose": -1,
    }

    callbacks = [
        lgb.early_stopping(stopping_rounds=20),
        lgb.log_evaluation(period=10),
    ]

    model = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[val_data],
        valid_names=["val"],
        callbacks=callbacks,
    )

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR / f"ranker_model_{output_version}.txt"
    model.save_model(str(model_path))

    # Evaluate
    y_pred = model.predict(X_val)
    ndcg5 = _ndcg_at_k(y_val, y_pred, groups_val, k=5)
    ndcg10 = _ndcg_at_k(y_val, y_pred, groups_val, k=10)

    importance = dict(zip(RANKING_FEATURES, model.feature_importance("gain").tolist()))

    logger.info("Trained LambdaRank: NDCG@5=%.4f NDCG@10=%.4f", ndcg5, ndcg10)
    return {
        "status": "trained",
        "path": str(model_path),
        "sample_count": len(rows),
        "group_count": len(groups),
        "metrics": {
            "ndcg_at_5": round(ndcg5, 4),
            "ndcg_at_10": round(ndcg10, 4),
        },
        "feature_importance": importance,
    }


def _ndcg_at_k(y_true: np.ndarray, y_pred: np.ndarray, groups: list[int], k: int) -> float:
    """Compute mean NDCG@k across all groups."""
    ndcgs = []
    offset = 0
    for size in groups:
        true_slice = y_true[offset:offset + size]
        pred_slice = y_pred[offset:offset + size]
        offset += size

        # Sort by predicted score descending
        order = np.argsort(-pred_slice)
        sorted_true = true_slice[order]

        dcg = sum(
            (2 ** rel - 1) / math.log2(i + 2)
            for i, rel in enumerate(sorted_true[:k])
        )
        ideal = np.sort(true_slice)[::-1]
        idcg = sum(
            (2 ** rel - 1) / math.log2(i + 2)
            for i, rel in enumerate(ideal[:k])
        )
        ndcgs.append(dcg / idcg if idcg > 0 else 0.0)

    return sum(ndcgs) / len(ndcgs) if ndcgs else 0.0
