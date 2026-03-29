import logging
from collections import Counter

logger = logging.getLogger(__name__)


def evaluate_relevance(predictions: list[dict], labels: list[dict]) -> dict:
    """Evaluate relevance model predictions against labeled data."""
    metrics = {}

    for field in ["domain_relevant", "workflow_relevant", "opportunity_relevant"]:
        tp = fp = fn = tn = 0
        for pred, label in zip(predictions, labels):
            p = pred.get(field, 0)
            l = label.get(field, 0)
            if p == 1 and l == 1:
                tp += 1
            elif p == 1 and l == 0:
                fp += 1
            elif p == 0 and l == 1:
                fn += 1
            else:
                tn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        metrics[field] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        }

    # Hard negative precision
    hard_neg_correct = sum(
        1 for p, l in zip(predictions, labels)
        if l.get("is_hard_negative") and p.get("opportunity_relevant", 0) == 0
    )
    hard_neg_total = sum(1 for l in labels if l.get("is_hard_negative"))
    metrics["hard_negative_precision"] = round(
        hard_neg_correct / hard_neg_total if hard_neg_total > 0 else 0.0, 4
    )

    return metrics


def evaluate_workflow_builder(results: list[dict]) -> dict:
    """Evaluate workflow builder outputs."""
    total = len(results)
    if total == 0:
        return {"total": 0}

    valid = sum(1 for r in results if r.get("workflow_detected"))
    has_breakpoint = sum(1 for r in results if r.get("broken_step"))

    # Check for hallucination indicators
    topic_only = sum(
        1 for r in results
        if r.get("workflow_detected") and r.get("specificity") == "low"
    )

    return {
        "total": total,
        "valid_workflow_rate": round(valid / total, 4),
        "breakpoint_rate": round(has_breakpoint / total, 4),
        "hallucination_rate": round(topic_only / max(valid, 1), 4),
    }


def evaluate_tinyfish(results: list[dict]) -> dict:
    """Evaluate TinyFish extraction quality."""
    total = len(results)
    if total == 0:
        return {"total": 0}

    success = sum(1 for r in results if r.get("status") == "completed")
    failed = sum(1 for r in results if r.get("status") in ("failed", "error"))

    # Count items extracted
    total_items = sum(len(r.get("items", [])) for r in results if r.get("items"))

    return {
        "total_runs": total,
        "success_rate": round(success / total, 4),
        "failure_rate": round(failed / total, 4),
        "total_items_extracted": total_items,
        "avg_items_per_run": round(total_items / max(success, 1), 2),
    }


def evaluate_ranking(predictions: list[dict], human_scores: list[float]) -> dict:
    """Evaluate ranking quality against human-rated scores."""
    if not predictions or not human_scores:
        return {"total": 0}

    n = min(len(predictions), len(human_scores))

    # Precision@k
    results = {}
    for k in [1, 3, 5]:
        if k > n:
            continue
        top_k_pred = sorted(predictions[:n], key=lambda x: x.get("rank_score", 0), reverse=True)[:k]
        top_k_human = sorted(range(n), key=lambda i: human_scores[i], reverse=True)[:k]

        pred_ids = {p.get("cluster_id") for p in top_k_pred}
        human_ids = {predictions[i].get("cluster_id") for i in top_k_human}

        overlap = len(pred_ids & human_ids)
        results[f"precision_at_{k}"] = round(overlap / k, 4)

    return results


def evaluate_pipeline_run(debug_data: dict) -> dict:
    """Evaluate a full pipeline run from debug output.

    Current pipeline stages:
    1. Ingest → 2. Normalize → 3. Relevance gate → 4. spaCy NLP →
    5. Signal extraction → 6. Cluster → 7. NLP enrich → 8. Quality assess →
    9. Eligibility → 10. LLM workflow builder → 11. Validity gate →
    12. Score → 13. Rank → 14. LLM report synthesis
    """
    total = debug_data.get("total_ingested", 0)
    if total == 0:
        return {"total_ingested": 0}

    relevant = debug_data.get("after_relevance_gate", 0)
    candidates = debug_data.get("total_candidates", 0)
    clusters = debug_data.get("total_clusters", 0)
    eligible = debug_data.get("after_eligibility_gate", 0)
    valid = debug_data.get("after_validity_gate", 0)

    # TinyFish metrics
    tf_runs = debug_data.get("tinyfish_runs", {})
    tf_total = tf_runs.get("total", 0)
    tf_completed = tf_runs.get("completed", 0)

    # LLM workflow metrics
    llm_workflows = debug_data.get("llm_workflows", [])
    llm_detected = sum(1 for w in llm_workflows if w.get("workflow", {}).get("workflow_detected"))

    return {
        "total_ingested": total,
        "relevance_pass_rate": round(relevant / total, 4) if total else 0,
        "candidate_rate": round(candidates / max(relevant, 1), 4),
        "cluster_count": clusters,
        "eligibility_rate": round(eligible / max(clusters, 1), 4),
        "llm_workflow_detection_rate": round(llm_detected / max(eligible, 1), 4),
        "validity_rate": round(valid / max(eligible, 1), 4),
        "tinyfish_runs": tf_total,
        "tinyfish_success_rate": round(tf_completed / max(tf_total, 1), 4),
        "overall_conversion": round(valid / max(total, 1), 4),
    }
