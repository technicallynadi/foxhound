"""Interactive tier suggestion flow for foxhound init.

Detects available provider API keys, presents tier suggestions,
and generates foxhound.yaml with user-confirmed configuration.
"""

import os

NOTIFICATIONS_YAML = (
    "\n"
    "# Notification channels — set enabled: true and configure env vars to activate.\n"
    "notifications:\n"
    "  enabled: true\n"
    "  channels:\n"
    "    desktop:\n"
    "      enabled: true\n"
    "    email:\n"
    "      enabled: false\n"
    "      api_key_env: RESEND_API_KEY\n"
    "      to_address_env: USER_EMAIL\n"
    "      # from_address: foxhound@notifications.foxhound.dev\n"
    "    sms:\n"
    "      enabled: false\n"
    "      account_sid_env: TWILIO_ACCOUNT_SID\n"
    "      auth_token_env: TWILIO_AUTH_TOKEN\n"
    "      from_number_env: TWILIO_FROM_NUMBER\n"
    "      to_number_env: USER_PHONE_NUMBER\n"
    "    slack:\n"
    "      enabled: false\n"
    "      webhook_env: SLACK_WEBHOOK_URL\n"
    "      # channel: '#foxhound'\n"
    "    discord:\n"
    "      enabled: false\n"
    "      webhook_env: DISCORD_WEBHOOK_URL\n"
    "    web_push:\n"
    "      enabled: true\n"
)

from foxhound.adapters.registry import (
    PROVIDER_API_KEY_DEFAULTS,
    apply_auto_defaults,
    get_default_api_key_env,
)


def detect_providers() -> list[tuple[str, str]]:
    """Detect which providers have API keys set in the environment.

    Returns:
        List of (provider_name, env_var_name) tuples for detected providers.
    """
    detected: list[tuple[str, str]] = []
    for provider, env_var in PROVIDER_API_KEY_DEFAULTS.items():
        if os.environ.get(env_var):
            detected.append((provider, env_var))
    return detected


def get_tier_suggestions(provider: str) -> dict[str, str]:
    """Get complete tier suggestions for a provider.

    Args:
        provider: Provider name.

    Returns:
        Dict mapping tier names to suggested model identifiers.
    """
    return apply_auto_defaults(provider, {})


def build_config_yaml(
    provider: str,
    tiers: dict[str, str],
    api_key_env: str | None = None,
) -> str:
    """Build foxhound.yaml content from provider and tier selections.

    Args:
        provider: Provider name.
        tiers: Tier-to-model mappings.
        api_key_env: Optional API key env var override.

    Returns:
        Complete foxhound.yaml content string.
    """
    key_env = api_key_env or get_default_api_key_env(provider)

    lines = [
        "# Foxhound configuration",
        "# Model tier mappings for your provider.",
        "models:",
        f"  provider: {provider}",
        f"  api_key_env: {key_env}",
        "  tiers:",
    ]
    for tier_name, model_id in sorted(tiers.items()):
        lines.append(f"    {tier_name}: {model_id}")

    return "\n".join(lines) + "\n" + NOTIFICATIONS_YAML


def select_provider_non_interactive(
    detected: list[tuple[str, str]],
) -> tuple[str, str] | None:
    """Select a provider non-interactively for CI/headless environments.

    Priority: anthropic > openai > google > deepseek > first detected.

    Args:
        detected: List of (provider, env_var) tuples.

    Returns:
        Selected (provider, env_var) or None if nothing detected.
    """
    if not detected:
        return None

    priority = ["anthropic", "openai", "google", "deepseek"]
    provider_map = {p: e for p, e in detected}

    for preferred in priority:
        if preferred in provider_map:
            return preferred, provider_map[preferred]

    return detected[0]
