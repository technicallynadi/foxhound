"""Google Gemini provider adapter.

Wraps the Google Generative AI API for model tier routing.
Uses the Gemini API content format with parts-based responses.
"""

from foxhound.adapters.provider import (
    ModelRequest,
    ModelResponse,
    TokenUsage,
)

# Per-million-token pricing (USD) as of March 2026
GOOGLE_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.0-flash": (0.10, 0.40),
}


class GoogleAdapter:
    """Adapter for the Google Gemini API."""

    def __init__(self) -> None:
        self._api_key: str = ""
        self._authenticated: bool = False

    @property
    def provider_name(self) -> str:
        """Unique provider identifier."""
        return "google"

    def authenticate(self, api_key: str, base_url: str | None = None) -> bool:
        """Store API key for later use.

        Args:
            api_key: Google API key.
            base_url: Ignored for Google (uses standard endpoint).

        Returns:
            True if key is non-empty.
        """
        if not api_key:
            return False
        self._api_key = api_key
        self._authenticated = True
        return True

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Send a request to the Gemini generateContent endpoint.

        Args:
            request: Model request with messages and optional system prompt.

        Returns:
            Structured model response.

        Raises:
            RuntimeError: If not authenticated or request fails.
        """
        if not self._authenticated:
            raise RuntimeError("Google adapter not authenticated")

        import json
        import urllib.request
        from urllib.error import HTTPError

        model_id = request.model_id or "gemini-2.5-flash"
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{model_id}:generateContent"
            f"?key={self._api_key}"
        )

        contents = []
        for msg in request.messages:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg.get("content", "")}],
            })

        payload: dict[str, object] = {"contents": contents}
        if request.system:
            payload["systemInstruction"] = {
                "parts": [{"text": request.system}],
            }

        generation_config: dict[str, object] = {
            "maxOutputTokens": request.max_tokens,
        }
        if request.temperature > 0:
            generation_config["temperature"] = request.temperature
        if request.stop_sequences:
            generation_config["stopSequences"] = request.stop_sequences
        payload["generationConfig"] = generation_config

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            raise RuntimeError(f"Google API error: {e.code}") from e
        except Exception as e:
            raise RuntimeError(f"Google API error: {e}") from e

        candidates = data.get("candidates", [])
        content = ""
        stop_reason = None
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                if "text" in part:
                    content += part["text"]
            stop_reason = candidates[0].get("finishReason")

        usage_meta = data.get("usageMetadata", {})
        usage = TokenUsage(
            input_tokens=usage_meta.get("promptTokenCount", 0),
            output_tokens=usage_meta.get("candidatesTokenCount", 0),
        )

        return ModelResponse(
            content=content,
            role="assistant",
            usage=usage,
            model_id=model_id,
            stop_reason=stop_reason,
            raw=data,
        )

    def check_model(self, model_id: str) -> bool:
        """Check if a model is accessible by sending a minimal request.

        Args:
            model_id: Google model identifier.

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
        """Estimate cost based on Google's per-token pricing.

        Args:
            usage: Token consumption.
            model_id: Google model identifier.

        Returns:
            Estimated cost in USD.
        """
        pricing = GOOGLE_PRICING.get(model_id)
        if not pricing:
            return 0.0
        input_rate, output_rate = pricing
        input_cost = (usage.input_tokens / 1_000_000) * input_rate
        output_cost = (usage.output_tokens / 1_000_000) * output_rate
        return input_cost + output_cost
