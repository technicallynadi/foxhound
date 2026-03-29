import copy
import random
import logging

logger = logging.getLogger(__name__)


def mutate_thresholds(base_config: dict, n_variants: int = 5) -> list[dict]:
    """Generate threshold variations."""
    variants = []
    for i in range(n_variants):
        variant = copy.deepcopy(base_config)
        for key, value in variant.items():
            if isinstance(value, float) and 0.0 <= value <= 1.0:
                delta = random.uniform(-0.15, 0.15)
                variant[key] = round(max(0.0, min(1.0, value + delta)), 3)
        variant["_variant_id"] = f"threshold_v{i}"
        variants.append(variant)
    return variants


def mutate_prompt(base_prompt: str, mutations: list[str]) -> list[dict]:
    """Generate prompt variations from a list of mutation descriptions."""
    variants = []
    for i, mutation in enumerate(mutations):
        variants.append({
            "_variant_id": f"prompt_v{i}",
            "base_prompt": base_prompt[:100] + "...",
            "mutation": mutation,
            "prompt": f"{base_prompt}\n\nAdditional instruction: {mutation}",
        })
    return variants


def mutate_feature_set(base_features: list[str], n_variants: int = 3) -> list[dict]:
    """Generate feature set variations by dropping/adding features."""
    variants = []
    for i in range(n_variants):
        features = list(base_features)
        # Randomly drop 1-2 features
        if len(features) > 3:
            n_drop = random.randint(1, min(2, len(features) - 2))
            for _ in range(n_drop):
                features.pop(random.randint(0, len(features) - 1))
        variants.append({
            "_variant_id": f"features_v{i}",
            "features": features,
            "dropped": list(set(base_features) - set(features)),
        })
    return variants


def generate_tinyfish_variants(base_goal: str) -> list[dict]:
    """Generate TinyFish goal prompt variations."""
    mutations = [
        "Be more aggressive about extracting negative signals and complaints",
        "Focus specifically on workaround language and manual processes",
        "Prioritize missing feature mentions and gap descriptions",
        "Extract persona and role information when visible",
        "Stop after 10 items instead of 20 for faster extraction",
    ]
    return mutate_prompt(base_goal, mutations)
