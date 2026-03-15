"""Deepseek provider adapter.

Wraps the Deepseek API for model tier routing.
Uses an OpenAI-compatible Chat Completions format with Deepseek-specific pricing.
"""

import json
import urllib.request
from urllib.error import HTTPError

from foxhound.adapters.provider import (
    ModelRequest,
    ModelResponse,
    TokenUsage,
)

# Per-million-token pricing (USD) as of March 2026
DEEPSEEK_PRICING: dict[str, tuple[float, float]] = {
    "deepseek-r1": (0.55, 2.19),
    "deepseek-v3": (0.27, 1.10),
    "deepseek-chat": (0.27, 1.10),
}

DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"


class DeepseekAdapter:
    """Adapter for the Deepseek API (OpenAI-compatible format)."""

    def __init__(self) -> None:
        self._api_key: str = ""
        self._base_url: str = DEEPSEEK_API_BASE
        self._authenticated: bool = False

    @property
    def provider_name(self) -> str:
        """Unique provider identifier."""
        return "deepseek"

    def authenticate(self, api_key: str, base_url: str | None = None) -> bool:
        """Store API key for later use.

        Args:
            api_key: Deepseek API key.
            base_url: Optional custom base URL.

        Returns:
            True if key is non-empty.
        """
        if not api_key:
            return False
        self._api_key = api_key
        if base_url:
            self._base_url = base_url
        self._authenticated = True
        return True

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Send a chat completion request to Deepseek.

        Args:
            request: Model request with messages and optional system prompt.

        Returns:
            Structured model response.

        Raises:
            RuntimeError: If not authenticated or request fails.
        """
        if not self._authenticated:
            raise RuntimeError("Deepseek adapter not authenticated")

        model_id = request.model_id or "deepseek-chat"
        url = f"{self._base_url}/chat/completions"

        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.extend(request.messages)

        payload: dict[str, object] = {
            "model": model_id,
            "max_tokens": request.max_tokens,
            "messages": messages,
        }
        if request.temperature > 0:
            payload["temperature"] = request.temperature
        if request.stop_sequences:
            payload["stop"] = request.stop_sequences

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            raise RuntimeError(f"Deepseek API error: {e.code}") from e
        except Exception as e:
            raise RuntimeError(f"Deepseek API error: {e}") from e

        choices = data.get("choices", [])
        content = ""
        stop_reason = None
        if choices:
            content = choices[0].get("message", {}).get("content", "")
            stop_reason = choices[0].get("finish_reason")

        usage_data = data.get("usage", {})
        usage = TokenUsage(
            input_tokens=usage_data.get("prompt_tokens", 0),
            output_tokens=usage_data.get("completion_tokens", 0),
        )

        return ModelResponse(
            content=content,
            role="assistant",
            usage=usage,
            model_id=data.get("model", model_id),
            stop_reason=stop_reason,
            raw=data,
        )

    def check_model(self, model_id: str) -> bool:
        """Check if a model is accessible by sending a minimal request.

        Args:
            model_id: Deepseek model identifier.

        Returns:
            True if the model responds.
        """
        if not self._authenticated:
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
        """Estimate cost based on Deepseek's per-token pricing.

        Args:
            usage: Token consumption.
            model_id: Deepseek model identifier.

        Returns:
            Estimated cost in USD.
        """
        pricing = DEEPSEEK_PRICING.get(model_id)
        if not pricing:
            return 0.0
        input_rate, output_rate = pricing
        input_cost = (usage.input_tokens / 1_000_000) * input_rate
        output_cost = (usage.output_tokens / 1_000_000) * output_rate
        return input_cost + output_cost
