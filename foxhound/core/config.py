"""Foxhound configuration loading and validation.

Loads foxhound.yaml, parses model tier mappings, and provides
the resolved configuration to the rest of the system.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from foxhound.core.models import ModelTier


class ProviderConfig(BaseModel):
    """Configuration for a single model provider."""

    api_key_env: str | None = Field(default=None, description="Environment variable holding the API key")
    base_url: str | None = Field(default=None, description="Custom API base URL")


class ModelsConfig(BaseModel):
    """Model tier configuration from foxhound.yaml."""

    provider: str | None = Field(
        default=None, description="Single provider name (shorthand)"
    )
    api_key_env: str | None = Field(
        default=None, description="API key env var (single-provider shorthand)"
    )
    providers: dict[str, ProviderConfig] = Field(
        default_factory=dict, description="Multi-provider configurations"
    )
    tiers: dict[str, str] = Field(
        default_factory=dict, description="Tier-to-model mappings"
    )

    @model_validator(mode="after")
    def normalize_providers(self) -> "ModelsConfig":
        """Normalize single-provider shorthand into providers dict."""
        if self.provider and not self.providers:
            self.providers[self.provider] = ProviderConfig(
                api_key_env=self.api_key_env or f"{self.provider.upper()}_API_KEY"
            )
        return self

    def resolve_tier(self, tier: ModelTier) -> tuple[str, str]:
        """Resolve a tier to (provider_name, model_identifier).

        Args:
            tier: The model tier to resolve.

        Returns:
            Tuple of (provider_name, model_id).

        Raises:
            ValueError: If the tier is not configured.
        """
        model_spec = self.tiers.get(tier.value)
        if not model_spec:
            raise ValueError(f"No model configured for tier '{tier.value}'")

        if "/" in model_spec:
            provider_name, model_id = model_spec.split("/", 1)
        elif self.provider:
            provider_name = self.provider
            model_id = model_spec
        elif len(self.providers) == 1:
            provider_name = next(iter(self.providers))
            model_id = model_spec
        else:
            raise ValueError(
                f"Model '{model_spec}' for tier '{tier.value}' has no provider prefix "
                "and multiple providers are configured"
            )

        if provider_name not in self.providers:
            raise ValueError(
                f"Provider '{provider_name}' for tier '{tier.value}' "
                "is not in the providers configuration"
            )

        return provider_name, model_id

    def get_provider_config(self, provider_name: str) -> ProviderConfig | None:
        """Get configuration for a specific provider."""
        return self.providers.get(provider_name)


class NotificationSinkConfig(BaseModel):
    """Configuration for a single notification sink."""

    type: str = Field(..., description="Sink type: slack, discord, webhook")
    url: str = Field(..., description="Webhook or endpoint URL")
    channel: str | None = Field(default=None, description="Channel (Slack only)")
    headers: dict[str, str] = Field(
        default_factory=dict, description="Extra headers (webhook only)"
    )


class NotificationsConfig(BaseModel):
    """Notification configuration from foxhound.yaml."""

    enabled: bool = Field(default=True, description="Enable notifications")
    sinks: list[NotificationSinkConfig] = Field(
        default_factory=list, description="Configured notification sinks"
    )


class ScoutCloneConfig(BaseModel):
    """Configuration for cloning repos discovered by scout."""

    clone_dir: str = Field(
        default=".foxhound/cloned",
        description="Directory for cloned repos (relative to workspace root)",
    )
    shallow_clone: bool = Field(
        default=True, description="Use --depth 1 for clones"
    )
    auto_add_to_targets: bool = Field(
        default=False,
        description="Automatically register cloned repos as scan targets",
    )
    max_repo_size_mb: int = Field(
        default=500, description="Max allowed repo size in MB"
    )
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["github.com", "gitlab.com", "bitbucket.org"],
        description="Git hosts allowed for cloning",
    )


class ScoutConfig(BaseModel):
    """Scout configuration from foxhound.yaml."""

    clone: ScoutCloneConfig = Field(default_factory=ScoutCloneConfig)


class FoxhoundConfig(BaseModel):
    """Top-level foxhound.yaml configuration."""

    models: ModelsConfig = Field(default_factory=ModelsConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    scout: ScoutConfig = Field(default_factory=ScoutConfig)


def load_config(config_path: Path) -> FoxhoundConfig:
    """Load and validate foxhound.yaml.

    Args:
        config_path: Path to foxhound.yaml.

    Returns:
        Validated FoxhoundConfig.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValueError: If config is invalid.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    content = config_path.read_text(encoding="utf-8")
    try:
        data: Any = yaml.safe_load(content)
    except yaml.YAMLError as e:
        msg = f"Invalid YAML in {config_path}: {e}"
        raise ValueError(msg) from e

    if not isinstance(data, dict):
        msg = f"Config must be a YAML mapping, got {type(data).__name__}"
        raise ValueError(msg)

    return FoxhoundConfig(**data)


def load_config_from_cwd() -> FoxhoundConfig:
    """Load foxhound.yaml from the current working directory.

    Returns:
        Validated FoxhoundConfig.

    Raises:
        FileNotFoundError: If foxhound.yaml doesn't exist.
        ValueError: If config is invalid.
    """
    return load_config(Path.cwd() / "foxhound.yaml")
