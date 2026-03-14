"""Anthropic provider adapter.

Wraps the Anthropic API client for model tier routing.
Falls back gracefully when the anthropic package is not installed.
"""

from foxhound.adapters.provider import (
    ModelRequest,
    ModelResponse,
    TokenUsage,
)

# Per-million-token pricing (USD) as of March 2026
ANTHROPIC_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4.6": (15.0, 75.0),
    "claude-opus-4-6": (15.0, 75.0),
    "claude-sonnet-4.6": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4.5": (0.80, 4.0),
    "claude-haiku-4-5": (0.80, 4.0),
}


class AnthropicAdapter:
    """Adapter for the Anthropic Messages API."""

    def __init__(self) -> None:
        self._client: object | None = None
        self._api_key: str = ""

    @property
    def provider_name(self) -> str:
        """Unique provider identifier."""
        return "anthropic"

    def authenticate(self, api_key: str, base_url: str | None = None) -> bool:
        """Validate API key by constructing a client.

        Args:
            api_key: Anthropic API key.
            base_url: Optional custom base URL.

        Returns:
            True if the client was created successfully.
        """
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError:
            return False

        self._api_key = api_key
        kwargs: dict[str, str] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        try:
            self._client = anthropic.Anthropic(**kwargs)
            return True
        except Exception:
            return False

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Send a completion request to Anthropic.

        Args:
            request: Model request with messages, system prompt, etc.

        Returns:
            Structured model response.

        Raises:
            RuntimeError: If not authenticated or request fails.
        """
        if self._client is None:
            raise RuntimeError("Anthropic adapter not authenticated")

        import anthropic

        client: anthropic.Anthropic = self._client
        kwargs: dict[str, object] = {
            "model": request.model_id,
            "max_tokens": request.max_tokens,
            "messages": request.messages,
        }
        if request.system:
            kwargs["system"] = request.system
        if request.temperature > 0:
            kwargs["temperature"] = request.temperature
        if request.stop_sequences:
            kwargs["stop_sequences"] = request.stop_sequences

        try:
            response = client.messages.create(**kwargs)
        except Exception as e:
            raise RuntimeError(f"Anthropic API error: {e}") from e

        content = ""
        for block in response.content:
            if hasattr(block, "text"):
                content += block.text

        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        )

        return ModelResponse(
            content=content,
            role="assistant",
            usage=usage,
            model_id=response.model,
            stop_reason=response.stop_reason,
            raw={"id": response.id, "type": response.type},
        )

    def check_model(self, model_id: str) -> bool:
        """Check if a model is accessible by sending a minimal request.

        Args:
            model_id: Anthropic model identifier.

        Returns:
            True if the model responds.
        """
        if self._client is None:
            return False
        try:
            self.complete(ModelRequest(
                messages=[{"role": "user", "content": "ping"}],
                model_id=model_id,
                max_tokens=1,
            ))
            return True
        except Exception:
            return False

    def estimate_cost(self, usage: TokenUsage, model_id: str) -> float:
        """Estimate cost based on Anthropic's per-token pricing.

        Args:
            usage: Token consumption.
            model_id: Anthropic model identifier.

        Returns:
            Estimated cost in USD.
        """
        pricing = ANTHROPIC_PRICING.get(model_id)
        if not pricing:
            return 0.0
        input_rate, output_rate = pricing
        input_cost = (usage.input_tokens / 1_000_000) * input_rate
        output_cost = (usage.output_tokens / 1_000_000) * output_rate
        return input_cost + output_cost
