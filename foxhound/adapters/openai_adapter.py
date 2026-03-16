"""OpenAI provider adapter.

Wraps the OpenAI API client for model tier routing.
Also works with OpenAI-compatible APIs (Ollama, local servers).
Falls back gracefully when the openai package is not installed.
"""

from foxhound.adapters.provider import (
    ModelRequest,
    ModelResponse,
    TokenUsage,
)

# Per-million-token pricing (USD) as of March 2026
OPENAI_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "o3": (10.0, 40.0),
    "o4-mini": (1.10, 4.40),
}


class OpenAIAdapter:
    """Adapter for the OpenAI Chat Completions API."""

    def __init__(self) -> None:
        self._client: object | None = None
        self._api_key: str = ""

    @property
    def provider_name(self) -> str:
        """Unique provider identifier."""
        return "openai"

    def authenticate(self, api_key: str, base_url: str | None = None) -> bool:
        """Validate API key by constructing a client.

        Args:
            api_key: OpenAI API key.
            base_url: Optional custom base URL (for compatible APIs).

        Returns:
            True if the client was created successfully.
        """
        try:
            import openai  # type: ignore[import-not-found]
        except ImportError:
            return False

        self._api_key = api_key
        kwargs: dict[str, str] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        try:
            self._client = openai.OpenAI(**kwargs)
            return True
        except Exception:
            return False

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Send a chat completion request to OpenAI.

        Args:
            request: Model request with messages, system prompt, etc.

        Returns:
            Structured model response.

        Raises:
            RuntimeError: If not authenticated or request fails.
        """
        if self._client is None:
            raise RuntimeError("OpenAI adapter not authenticated")

        import openai

        client: openai.OpenAI = self._client

        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.extend(request.messages)

        kwargs: dict[str, object] = {
            "model": request.model_id,
            "max_tokens": request.max_tokens,
            "messages": messages,
        }
        if request.temperature > 0:
            kwargs["temperature"] = request.temperature
        if request.stop_sequences:
            kwargs["stop"] = request.stop_sequences

        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as e:
            raise RuntimeError(f"OpenAI API error: {e}") from e

        choice = response.choices[0] if response.choices else None
        content = choice.message.content or "" if choice else ""

        # Some models (e.g. Qwen3 via Ollama) put chain-of-thought in a
        # "reasoning" field and leave content empty until thinking is done.
        # Fall back to reasoning content when content is empty.
        if not content and choice:
            raw_msg = choice.message.model_extra or {}
            reasoning = raw_msg.get("reasoning", "")
            if reasoning:
                content = reasoning

        stop_reason = choice.finish_reason if choice else None

        usage_data = response.usage
        usage = TokenUsage(
            input_tokens=usage_data.prompt_tokens if usage_data else 0,
            output_tokens=usage_data.completion_tokens if usage_data else 0,
        )

        return ModelResponse(
            content=content,
            role="assistant",
            usage=usage,
            model_id=response.model or request.model_id,
            stop_reason=stop_reason,
            raw={"id": response.id},
        )

    def check_model(self, model_id: str) -> bool:
        """Check if a model is accessible by sending a minimal request.

        Args:
            model_id: OpenAI model identifier.

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
        """Estimate cost based on OpenAI's per-token pricing.

        Args:
            usage: Token consumption.
            model_id: OpenAI model identifier.

        Returns:
            Estimated cost in USD.
        """
        pricing = OPENAI_PRICING.get(model_id)
        if not pricing:
            return 0.0
        input_rate, output_rate = pricing
        input_cost = (usage.input_tokens / 1_000_000) * input_rate
        output_cost = (usage.output_tokens / 1_000_000) * output_rate
        return input_cost + output_cost
