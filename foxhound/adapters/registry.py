"""Provider registry with suggested tier mappings and auto-defaults.

Maintains the canonical list of known providers, their suggested
tier-to-model mappings, and auto-default logic for minimal configs.
"""

from foxhound.core.models import ModelTier

# Suggested tier mappings per provider.
# Users can override any mapping in foxhound.yaml.
PROVIDER_TIER_SUGGESTIONS: dict[str, dict[str, str]] = {
    "anthropic": {
        ModelTier.REASONING: "claude-opus-4.6",
        ModelTier.BALANCED: "claude-sonnet-4.6",
        ModelTier.FAST: "claude-haiku-4.5",
    },
    "openai": {
        ModelTier.REASONING: "gpt-4.1",
        ModelTier.BALANCED: "gpt-4.1-mini",
        ModelTier.FAST: "gpt-4.1-nano",
    },
    "google": {
        ModelTier.REASONING: "gemini-2.5-pro",
        ModelTier.BALANCED: "gemini-2.5-flash",
        ModelTier.FAST: "gemini-2.5-flash",
    },
    "deepseek": {
        ModelTier.REASONING: "deepseek-r1",
        ModelTier.BALANCED: "deepseek-v3",
        ModelTier.FAST: "deepseek-v3",
    },
    "local": {
        ModelTier.REASONING: "qwen3-32b",
        ModelTier.BALANCED: "qwen3-8b",
        ModelTier.FAST: "qwen3-4b",
    },
    "ollama": {
        ModelTier.REASONING: "qwen3-32b",
        ModelTier.BALANCED: "qwen3-8b",
        ModelTier.FAST: "qwen3-4b",
    },
}

# Default API key environment variables per provider
PROVIDER_API_KEY_DEFAULTS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "local": "LOCAL_API_KEY",
    "ollama": "OLLAMA_API_KEY",
}

# Known providers
KNOWN_PROVIDERS = set(PROVIDER_TIER_SUGGESTIONS.keys())


def get_suggested_tiers(provider: str) -> dict[str, str] | None:
    """Get suggested tier-to-model mappings for a provider.

    Args:
        provider: Provider name.

    Returns:
        Dict mapping tier names to model identifiers, or None if unknown.
    """
    return PROVIDER_TIER_SUGGESTIONS.get(provider)


def get_default_api_key_env(provider: str) -> str:
    """Get the default API key environment variable for a provider.

    Args:
        provider: Provider name.

    Returns:
        Environment variable name.
    """
    return PROVIDER_API_KEY_DEFAULTS.get(provider, f"{provider.upper()}_API_KEY")


def apply_auto_defaults(provider: str, tiers: dict[str, str]) -> dict[str, str]:
    """Fill in missing tier mappings with provider defaults.

    If the user configured a provider but left some tiers unmapped,
    this fills them in with the suggested defaults. If no suggestions
    exist, the balanced tier's model is used for all missing tiers.

    Args:
        provider: Provider name.
        tiers: User-specified tier mappings (may be partial or empty).

    Returns:
        Complete tier mappings with all three tiers filled in.
    """
    suggestions = PROVIDER_TIER_SUGGESTIONS.get(provider, {})
    result = dict(tiers)

    for tier in ModelTier:
        if tier.value not in result:
            if tier.value in suggestions:
                result[tier.value] = suggestions[tier.value]
            elif ModelTier.BALANCED.value in result:
                # Fallback: use balanced model for missing tiers
                result[tier.value] = result[ModelTier.BALANCED.value]
            elif suggestions:
                # Use balanced suggestion as ultimate fallback
                result[tier.value] = suggestions.get(
                    ModelTier.BALANCED, next(iter(suggestions.values()))
                )

    return result


def generate_config_yaml(provider: str, api_key_env: str | None = None) -> str:
    """Generate a foxhound.yaml models section for a provider.

    Args:
        provider: Provider name.
        api_key_env: Override for the API key env var.

    Returns:
        YAML string for the models section.
    """
    key_env = api_key_env or get_default_api_key_env(provider)
    suggestions = PROVIDER_TIER_SUGGESTIONS.get(provider, {})

    lines = [
        "models:",
        f"  provider: {provider}",
        f"  api_key_env: {key_env}",
        "  tiers:",
    ]

    for tier in ModelTier:
        model = suggestions.get(tier.value, f"your-{tier.value}-model")
        lines.append(f"    {tier.value}: {model}")

    return "\n".join(lines) + "\n"


# Default worker tier assignments (spec §5)
WORKER_DEFAULT_TIERS: dict[str, ModelTier] = {
    "ScoutWorker": ModelTier.FAST,
    "DiscoveryWorker": ModelTier.BALANCED,
    "ExecutionWorker": ModelTier.BALANCED,
    "AnalyzerWorker": ModelTier.BALANCED,
    "CodeReviewWorker": ModelTier.REASONING,
    "SecurityReviewWorker": ModelTier.REASONING,
    "EvidenceValidatorWorker": ModelTier.FAST,
    "FailureTriageWorker": ModelTier.BALANCED,
    "PatchQualityEvaluatorWorker": ModelTier.BALANCED,
    "TaskDecomposerWorker": ModelTier.REASONING,
}


def get_worker_default_tier(worker_type: str) -> ModelTier:
    """Get the default model tier for a worker type.

    Args:
        worker_type: Worker class name.

    Returns:
        Default model tier (falls back to balanced).
    """
    return WORKER_DEFAULT_TIERS.get(worker_type, ModelTier.BALANCED)
