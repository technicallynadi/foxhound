"""Provider adapter protocol and base types.

Defines the interface that all model provider adapters must implement,
plus common types for token usage, model responses, and cost tracking.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class TokenUsage:
    """Token consumption from a single model call."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed."""
        return self.input_tokens + self.output_tokens


@dataclass
class ModelResponse:
    """Structured response from a model provider."""

    content: str = ""
    role: str = "assistant"
    usage: TokenUsage = field(default_factory=TokenUsage)
    model_id: str = ""
    stop_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelRequest:
    """Structured request to a model provider."""

    messages: list[dict[str, str]] = field(default_factory=list)
    system: str | None = None
    model_id: str = ""
    max_tokens: int = 4096
    temperature: float = 0.0
    stop_sequences: list[str] | None = None


@runtime_checkable
class ProviderAdapter(Protocol):
    """Protocol that all model provider adapters must implement."""

    @property
    def provider_name(self) -> str:
        """Unique provider identifier (e.g., 'anthropic', 'openai')."""
        ...

    def authenticate(self, api_key: str, base_url: str | None = None) -> bool:
        """Validate API key and establish connection.

        Args:
            api_key: The API key to authenticate with.
            base_url: Optional custom API base URL.

        Returns:
            True if authentication succeeded.
        """
        ...

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Send a completion request to the provider.

        Args:
            request: Structured model request.

        Returns:
            Structured model response.

        Raises:
            ConnectionError: If the provider is unreachable.
            ValueError: If the model_id is invalid.
            RuntimeError: If the request fails.
        """
        ...

    def check_model(self, model_id: str) -> bool:
        """Check if a model identifier is valid and accessible.

        Args:
            model_id: Model identifier to check.

        Returns:
            True if the model is accessible.
        """
        ...

    def estimate_cost(self, usage: TokenUsage, model_id: str) -> float:
        """Estimate cost in USD for a given token usage.

        Args:
            usage: Token consumption.
            model_id: Model that produced the usage.

        Returns:
            Estimated cost in USD.
        """
        ...
