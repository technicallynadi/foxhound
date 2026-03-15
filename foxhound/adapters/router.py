"""Model router for tier-aware request routing.

Resolves model tiers to provider adapters and model identifiers,
then routes requests to the appropriate provider.
"""

import os

from foxhound.adapters.anthropic_adapter import AnthropicAdapter
from foxhound.adapters.deepseek_adapter import DeepseekAdapter
from foxhound.adapters.google_adapter import GoogleAdapter
from foxhound.adapters.openai_adapter import OpenAIAdapter
from foxhound.adapters.provider import (
    ModelRequest,
    ModelResponse,
    ProviderAdapter,
    TokenUsage,
)
from foxhound.core.config import FoxhoundConfig, ModelsConfig
from foxhound.core.models import ModelTier

# Default adapter factories by provider name
ADAPTER_FACTORIES: dict[str, type] = {
    "anthropic": AnthropicAdapter,
    "openai": OpenAIAdapter,
    "google": GoogleAdapter,
    "deepseek": DeepseekAdapter,
    "local": OpenAIAdapter,
    "ollama": OpenAIAdapter,
}


class ModelRouter:
    """Routes model requests by tier through configured providers.

    Loads provider adapters, authenticates them, and routes
    completion requests to the correct provider for each tier.
    """

    def __init__(self, config: FoxhoundConfig) -> None:
        self._config = config
        self._models_config: ModelsConfig = config.models
        self._adapters: dict[str, ProviderAdapter] = {}
        self._authenticated: set[str] = set()
        self._total_cost: float = 0.0

    def initialize(self) -> list[str]:
        """Initialize and authenticate all configured providers.

        Returns:
            List of error messages for any providers that failed to authenticate.
            Empty list means all providers authenticated successfully.
        """
        errors: list[str] = []

        for provider_name, provider_config in self._models_config.providers.items():
            factory = ADAPTER_FACTORIES.get(provider_name)
            if factory is None:
                errors.append(
                    f"Unknown provider '{provider_name}' — "
                    f"supported: {', '.join(sorted(ADAPTER_FACTORIES))}"
                )
                continue

            adapter: ProviderAdapter = factory()
            api_key = os.environ.get(provider_config.api_key_env, "")
            if not api_key:
                errors.append(
                    f"Provider '{provider_name}': environment variable "
                    f"'{provider_config.api_key_env}' is not set"
                )
                continue

            if adapter.authenticate(api_key, provider_config.base_url):
                self._adapters[provider_name] = adapter
                self._authenticated.add(provider_name)
            else:
                errors.append(
                    f"Provider '{provider_name}': authentication failed"
                )

        return errors

    def is_ready(self) -> bool:
        """Check if at least one provider is authenticated."""
        return len(self._authenticated) > 0

    def resolve(self, tier: ModelTier) -> tuple[str, str, ProviderAdapter]:
        """Resolve a tier to its provider and model.

        Args:
            tier: The model tier to resolve.

        Returns:
            Tuple of (provider_name, model_id, adapter).

        Raises:
            ValueError: If the tier cannot be resolved.
            RuntimeError: If the provider is not authenticated.
        """
        provider_name, model_id = self._models_config.resolve_tier(tier)

        adapter = self._adapters.get(provider_name)
        if adapter is None:
            raise RuntimeError(
                f"Provider '{provider_name}' for tier '{tier.value}' is not authenticated"
            )

        return provider_name, model_id, adapter

    def complete(
        self,
        tier: ModelTier,
        messages: list[dict[str, str]],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> ModelResponse:
        """Route a completion request through the appropriate provider.

        Args:
            tier: Model tier to use.
            messages: Conversation messages.
            system: Optional system prompt.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.

        Returns:
            Model response from the resolved provider.
        """
        provider_name, model_id, adapter = self.resolve(tier)

        request = ModelRequest(
            messages=messages,
            system=system,
            model_id=model_id,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        response = adapter.complete(request)
        cost = adapter.estimate_cost(response.usage, model_id)
        self._total_cost += cost

        return response

    def check_model(self, tier: ModelTier) -> bool:
        """Check if the model for a tier is accessible.

        Args:
            tier: Model tier to check.

        Returns:
            True if the model responds.
        """
        try:
            _provider_name, model_id, adapter = self.resolve(tier)
            return adapter.check_model(model_id)
        except (ValueError, RuntimeError):
            return False

    def estimate_cost(self, tier: ModelTier, usage: TokenUsage) -> float:
        """Estimate cost for a usage at a given tier.

        Args:
            tier: Model tier.
            usage: Token usage to estimate.

        Returns:
            Estimated cost in USD.
        """
        try:
            _provider_name, model_id, adapter = self.resolve(tier)
            return adapter.estimate_cost(usage, model_id)
        except (ValueError, RuntimeError):
            return 0.0

    @property
    def total_cost(self) -> float:
        """Total accumulated cost across all requests."""
        return self._total_cost

    def is_tier_configured(self, tier: ModelTier) -> bool:
        """Check if a tier has a configured model mapping."""
        return tier.value in self._models_config.tiers

    @property
    def authenticated_providers(self) -> set[str]:
        """Set of successfully authenticated provider names."""
        return self._authenticated.copy()
