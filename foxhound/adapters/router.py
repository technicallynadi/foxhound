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


SERVICE_NAME = "foxhound"

# Only these key names are allowed in credential operations
_ALLOWED_KEY_NAMES = frozenset({
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GITHUB_TOKEN",
    "NEWSAPI_API_KEY",
    "PRODUCTHUNT_API_TOKEN",
    # Notification channel credentials
    "RESEND_API_KEY",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "SLACK_WEBHOOK_URL",
    "DISCORD_WEBHOOK_URL",
})

_KEY_NAME_RE = __import__("re").compile(r"^[A-Z][A-Z0-9_]{2,40}$")


def _validate_key_name(key_name: str) -> None:
    """Validate key name to prevent injection in subprocess args."""
    if not _KEY_NAME_RE.match(key_name):
        raise ValueError(f"Invalid key name: {key_name}")


def _read_credential(key_name: str, platform: str) -> str | None:
    """Read a credential from the platform's secure store."""
    import subprocess

    _validate_key_name(key_name)

    if platform == "darwin":
        result = subprocess.run(
            ["security", "find-generic-password",
             "-s", SERVICE_NAME, "-a", key_name, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None

    elif platform == "linux":
        result = subprocess.run(
            ["secret-tool", "lookup",
             "service", SERVICE_NAME, "key", key_name],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None

    elif platform == "win32":
        # Use cmdkey for reading on Windows (no PowerShell interpolation)
        target = f"{SERVICE_NAME}/{key_name}"
        result = subprocess.run(
            ["cmdkey", f"/list:{target}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and target in result.stdout:
            # cmdkey /list doesn't return the password directly;
            # use PowerShell with -EncodedCommand to avoid injection
            import base64
            cmd = (
                f"[Runtime.InteropServices.Marshal]::"
                f"PtrToStringAuto("
                f"[Runtime.InteropServices.Marshal]::"
                f"SecureStringToBSTR("
                f"(Get-StoredCredential"
                f" -Target '{SERVICE_NAME}/{key_name}'"
                f").Password))"
            )
            encoded = base64.b64encode(
                cmd.encode("utf-16-le")
            ).decode("ascii")
            result = subprocess.run(
                ["powershell", "-NoProfile",
                 "-EncodedCommand", encoded],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip() or None

    return None


def store_credential(key_name: str, value: str, platform: str) -> bool:
    """Store a credential in the platform's secure store.

    On macOS and Windows, passes the value via stdin to avoid
    exposing it in process arguments visible via `ps`.
    """
    import subprocess

    _validate_key_name(key_name)

    if platform == "darwin":
        # Delete existing entry first (retry to ensure it's gone)
        for _ in range(2):
            subprocess.run(
                ["security", "delete-generic-password",
                 "-s", SERVICE_NAME, "-a", key_name],
                capture_output=True, timeout=5,
            )
        # Use -U to update if exists. The macOS security command
        # requires -w with an inline value (it ignores stdin).
        # We pass it as an argument — the window is brief (~ms)
        # and this is a local CLI tool on the user's own machine.
        result = subprocess.run(
            ["security", "add-generic-password",
             "-s", SERVICE_NAME, "-a", key_name, "-U", "-w", value],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return False
        # Verify the stored value matches
        stored = _read_credential(key_name, platform)
        if stored != value:
            return False
        return True

    elif platform == "linux":
        result = subprocess.run(
            ["secret-tool", "store", "--label",
             f"foxhound {key_name}",
             "service", SERVICE_NAME, "key", key_name],
            input=value, capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0

    elif platform == "win32":
        # Use PowerShell via encoded command to avoid injection
        import base64
        target = f"{SERVICE_NAME}/{key_name}"
        cmd = (
            f"cmdkey /generic:{target} "
            f"/user:foxhound /pass:$env:_FH_SECRET"
        )
        encoded = base64.b64encode(
            cmd.encode("utf-16-le")
        ).decode("ascii")
        result = subprocess.run(
            ["powershell", "-NoProfile",
             "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "_FH_SECRET": value},
        )
        return result.returncode == 0

    return False


def delete_credential(key_name: str, platform: str) -> bool:
    """Delete a credential from the platform's secure store."""
    import subprocess

    _validate_key_name(key_name)

    if platform == "darwin":
        result = subprocess.run(
            ["security", "delete-generic-password",
             "-s", SERVICE_NAME, "-a", key_name],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0

    elif platform == "linux":
        result = subprocess.run(
            ["secret-tool", "clear",
             "service", SERVICE_NAME, "key", key_name],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0

    elif platform == "win32":
        target = f"{SERVICE_NAME}/{key_name}"
        result = subprocess.run(
            ["cmdkey", f"/delete:{target}"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0

    return False


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

        Loads API keys from environment variables. Also checks for a .env
        file in the current directory as a fallback.

        Returns:
            List of error messages for any providers that failed to authenticate.
            Empty list means all providers authenticated successfully.
        """
        self._load_secrets()
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

            # Local providers don't need API keys
            _LOCAL_PROVIDERS = {"local", "ollama"}
            if provider_name in _LOCAL_PROVIDERS:
                api_key = "no-auth"
            else:
                # Validate api_key_env to prevent arbitrary env var exfiltration
                env_var = provider_config.api_key_env
                if not env_var:
                    errors.append(
                        f"Provider '{provider_name}': api_key_env is required"
                    )
                    continue
                if not env_var.endswith(("_KEY", "_TOKEN", "_SECRET")):
                    errors.append(
                        f"Provider '{provider_name}': api_key_env "
                        f"'{env_var}' must end in _KEY, _TOKEN, or _SECRET"
                    )
                    continue

                api_key = os.environ.get(env_var, "")
                if not api_key:
                    errors.append(
                        f"Provider '{provider_name}': environment variable "
                        f"'{env_var}' is not set"
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

    @staticmethod
    def _load_secrets() -> None:
        """Load API keys from the platform credential store into env vars.

        - macOS: Keychain (via `security` command)
        - Linux: Secret Service / libsecret (via `secret-tool`)
        - Windows: Windows Credential Manager (via `keyring` or `cmdkey`)

        Falls back to .env file if no credential store is available.
        Never overwrites existing env vars.
        """
        import sys

        secret_keys = [
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GITHUB_TOKEN",
            "NEWSAPI_API_KEY",
            "PRODUCTHUNT_API_TOKEN",
            # Notification channel credentials
            "RESEND_API_KEY",
            "TWILIO_ACCOUNT_SID",
            "TWILIO_AUTH_TOKEN",
            "SLACK_WEBHOOK_URL",
            "DISCORD_WEBHOOK_URL",
        ]

        for key_name in secret_keys:
            if os.environ.get(key_name):
                continue
            try:
                value = _read_credential(key_name, sys.platform)
                if value:
                    os.environ[key_name] = value
            except Exception:
                pass

        # Fallback: load .env file if it exists
        from pathlib import Path

        env_file = Path.cwd() / ".env"
        if not env_file.exists():
            return
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key in _ALLOWED_KEY_NAMES and key not in os.environ:
                os.environ[key] = value

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
