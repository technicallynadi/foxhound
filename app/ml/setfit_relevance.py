import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent.parent.parent / "data" / "models"
_model = None
_is_loaded = False


def is_available() -> bool:
    """Check if a trained relevance model is available."""
    return _is_loaded


def load_model(version: str = "latest") -> bool:
    """Load the trained relevance model."""
    global _model, _is_loaded

    model_path = MODEL_DIR / f"relevance_model_{version}.pkl"
    if not model_path.exists():
        # Try latest
        candidates = sorted(MODEL_DIR.glob("relevance_model_*.pkl"))
        if not candidates:
            logger.info("No relevance model found — using rule-based fallback")
            return False
        model_path = candidates[-1]

    try:
        import pickle
        with open(model_path, "rb") as f:
            _model = pickle.load(f)
        _is_loaded = True
        logger.info("Loaded relevance model from %s", model_path)
        return True
    except Exception as e:
        logger.warning("Failed to load relevance model: %s", e)
        return False


def predict(query: str, text: str) -> dict:
    """Predict relevance labels for a (query, text) pair."""
    if not _is_loaded or _model is None:
        return None

    try:
        combined = f"{query} [SEP] {text[:500]}"
        vectorizer = _model.get("vectorizer")
        classifiers = _model.get("classifiers", {})

        if not vectorizer or not classifiers:
            return None

        features = vectorizer.transform([combined])

        result = {}
        for label_name, clf in classifiers.items():
            pred = clf.predict(features)[0]
            proba = clf.predict_proba(features)[0]
            result[label_name] = int(pred)
            result[f"{label_name}_confidence"] = round(float(max(proba)), 3)

        return result
    except Exception as e:
        logger.warning("Relevance prediction failed: %s", e)
        return None


def train(dataset_path: str, output_version: str = "v0_1") -> dict:
    """Train a relevance model from a JSONL dataset."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import f1_score
    import pickle

    # Load dataset
    rows = []
    with open(dataset_path) as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    if len(rows) < 20:
        return {"error": "Need at least 20 labeled examples", "count": len(rows)}

    # Prepare features
    texts = [f"{r['query']} [SEP] {r['text'][:500]}" for r in rows]
    vectorizer = TfidfVectorizer(max_features=5000, ngram_range=(1, 2))
    X = vectorizer.fit_transform(texts)

    labels = ["domain_relevant", "workflow_relevant", "opportunity_relevant"]
    classifiers = {}
    metrics = {}

    for label in labels:
        y = [r.get(label, 0) for r in rows]
        if len(set(y)) < 2:
            continue

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        clf = LogisticRegression(max_iter=1000, class_weight="balanced")
        clf.fit(X_train, y_train)

        y_pred = clf.predict(X_test)
        f1 = f1_score(y_test, y_pred, zero_division=0)

        classifiers[label] = clf
        metrics[label] = {"f1": round(f1, 4), "train_size": len(y_train), "test_size": len(y_test)}

    # Save model
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_data = {"vectorizer": vectorizer, "classifiers": classifiers}
    model_path = MODEL_DIR / f"relevance_model_{output_version}.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(model_data, f)

    logger.info("Trained relevance model: %s", metrics)
    return {"status": "trained", "path": str(model_path), "metrics": metrics}
