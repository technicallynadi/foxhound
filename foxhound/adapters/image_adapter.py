"""Image generation provider adapter.

Provides a protocol and implementations for image generation APIs.
Unlike text adapters, these accept prompts and return image artifact paths.
"""

import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class ImageRequest:
    """Request for image generation."""

    prompt: str
    model_id: str = ""
    size: str = "1024x1024"
    quality: str = "standard"
    output_dir: Path | None = None
    filename: str = "generated_image.png"


@dataclass
class ImageResult:
    """Result from image generation."""

    artifact_path: Path | None = None
    cost: float = 0.0
    model_id: str = ""
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Whether image generation succeeded."""
        return self.artifact_path is not None and self.error is None


@runtime_checkable
class ImageAdapter(Protocol):
    """Protocol for image generation provider adapters."""

    @property
    def provider_name(self) -> str:
        """Provider identifier."""
        ...

    def authenticate(self, api_key: str, base_url: str | None = None) -> bool:
        """Validate API credentials."""
        ...

    def generate(self, request: ImageRequest) -> ImageResult:
        """Generate an image from a text prompt.

        Args:
            request: Image generation request.

        Returns:
            ImageResult with artifact path and cost.
        """
        ...

    def estimate_cost(self, model_id: str, size: str = "1024x1024") -> float:
        """Estimate cost for a single image generation."""
        ...


def save_image_data(data: bytes, output_dir: Path, filename: str) -> Path:
    """Save raw image bytes to a file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    path.write_bytes(data)
    return path


def save_base64_image(b64_data: str, output_dir: Path, filename: str) -> Path:
    """Decode base64 image data and save to a file."""
    image_bytes = base64.b64decode(b64_data)
    return save_image_data(image_bytes, output_dir, filename)


# Per-image pricing estimates (USD)
IMAGE_PRICING: dict[str, dict[str, float]] = {
    "gpt-image-1": {
        "1024x1024": 0.04,
        "1024x1536": 0.08,
        "auto": 0.04,
    },
    "gemini-2.0-flash-preview-image-generation": {
        "1024x1024": 0.02,
        "auto": 0.02,
    },
    "dall-e-3": {
        "1024x1024": 0.04,
        "1024x1792": 0.08,
        "1792x1024": 0.08,
    },
}


class OpenAIImageAdapter:
    """Image generation adapter for OpenAI-compatible APIs.

    Supports GPT Image 1, DALL-E 3, and OpenAI-compatible local endpoints.
    """

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._base_url: str = "https://api.openai.com/v1"
        self._authenticated: bool = False

    @property
    def provider_name(self) -> str:
        return "openai"

    def authenticate(self, api_key: str, base_url: str | None = None) -> bool:
        """Store API key for later use."""
        if not api_key:
            return False
        self._api_key = api_key
        if base_url:
            self._base_url = base_url
        self._authenticated = True
        return True

    def generate(self, request: ImageRequest) -> ImageResult:
        """Generate an image using OpenAI Images API."""
        if not self._authenticated or not self._api_key:
            return ImageResult(error="Not authenticated")

        try:
            import json
            import urllib.request
            from urllib.error import HTTPError

            url = f"{self._base_url}/images/generations"
            payload = json.dumps({
                "model": request.model_id or "gpt-image-1",
                "prompt": request.prompt,
                "size": request.size,
                "n": 1,
                "response_format": "b64_json",
            }).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )

            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            b64_data = body["data"][0]["b64_json"]
            output_dir = request.output_dir or Path(".")
            artifact_path = save_base64_image(
                b64_data, output_dir, request.filename
            )

            model_id = request.model_id or "gpt-image-1"
            cost = self.estimate_cost(model_id, request.size)

            return ImageResult(
                artifact_path=artifact_path,
                cost=cost,
                model_id=model_id,
                raw=body,
            )
        except ImportError:
            return ImageResult(error="urllib not available")
        except HTTPError as e:
            return ImageResult(error=f"API error: {e.code}")
        except Exception as exc:
            logger.warning("Image generation failed: %s", exc)
            return ImageResult(error=str(exc))

    def estimate_cost(self, model_id: str, size: str = "1024x1024") -> float:
        """Estimate cost for a single image generation."""
        pricing = IMAGE_PRICING.get(model_id, {})
        return pricing.get(size, pricing.get("auto", 0.04))


class GoogleImageAdapter:
    """Image generation adapter for Google Gemini image generation."""

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._authenticated: bool = False

    @property
    def provider_name(self) -> str:
        return "google"

    def authenticate(self, api_key: str, base_url: str | None = None) -> bool:
        """Store API key for later use."""
        if not api_key:
            return False
        self._api_key = api_key
        self._authenticated = True
        return True

    def generate(self, request: ImageRequest) -> ImageResult:
        """Generate an image using Gemini image generation."""
        if not self._authenticated or not self._api_key:
            return ImageResult(error="Not authenticated")

        try:
            import json
            import urllib.request
            from urllib.error import HTTPError

            model_id = request.model_id or "gemini-2.0-flash-preview-image-generation"
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/"
                f"models/{model_id}:generateContent"
                f"?key={self._api_key}"
            )

            payload = json.dumps({
                "contents": [{"parts": [{"text": request.prompt}]}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
            }).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
            )

            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            parts = body.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            image_data = None
            for part in parts:
                if "inlineData" in part:
                    image_data = part["inlineData"].get("data")
                    break

            if not image_data:
                return ImageResult(error="No image data in response")

            output_dir = request.output_dir or Path(".")
            artifact_path = save_base64_image(
                image_data, output_dir, request.filename
            )

            cost = self.estimate_cost(model_id, request.size)

            return ImageResult(
                artifact_path=artifact_path,
                cost=cost,
                model_id=model_id,
                raw=body,
            )
        except HTTPError as e:
            return ImageResult(error=f"API error: {e.code}")
        except Exception as exc:
            logger.warning("Image generation failed: %s", exc)
            return ImageResult(error=str(exc))

    def estimate_cost(self, model_id: str, size: str = "1024x1024") -> float:
        """Estimate cost for a single image generation."""
        pricing = IMAGE_PRICING.get(model_id, {})
        return pricing.get(size, pricing.get("auto", 0.02))


# Image adapter factories by provider name
IMAGE_ADAPTER_FACTORIES: dict[str, type] = {
    "openai": OpenAIImageAdapter,
    "google": GoogleImageAdapter,
    "local": OpenAIImageAdapter,
}
