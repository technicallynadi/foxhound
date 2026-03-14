"""Composite secret provider with scoped injection and redaction.

Loads secrets from multiple sources in precedence order:
session override (highest) -> environment -> keychain -> dotenv (lowest).
Secrets are scoped per connector and never appear in logs, manifests,
or context packs.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class SecretProvider(Protocol):
    """Base protocol for secret retrieval."""

    def get_secret(self, key: str) -> str | None:
        """Retrieve a secret by key.

        Args:
            key: The secret key (e.g., 'ANTHROPIC_API_KEY').

        Returns:
            The secret value, or None if not found.
        """
        ...


class EnvSecretProvider:
    """Read secrets from environment variables."""

    def get_secret(self, key: str) -> str | None:
        """Retrieve a secret from environment variables."""
        return os.environ.get(key)


class DotenvSecretProvider:
    """Read secrets from a .env file (development only).

    Parses KEY=VALUE lines, ignoring comments and blank lines.
    Does NOT inject into os.environ.
    """

    def __init__(self, dotenv_path: str | Path = ".env") -> None:
        self._secrets: dict[str, str] = {}
        path = Path(dotenv_path)
        if path.exists():
            logger.warning(
                "Loading secrets from %s — use environment variables in production",
                path,
            )
            self._load(path)

    def _load(self, path: Path) -> None:
        """Parse the .env file."""
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            self._secrets[key] = value

    def get_secret(self, key: str) -> str | None:
        """Retrieve a secret from the parsed .env file."""
        return self._secrets.get(key)


class KeychainSecretProvider:
    """Read secrets from OS keychain via the keyring library.

    Falls back gracefully if keyring is not installed or not available.
    """

    SERVICE_NAME = "foxhound"

    def __init__(self) -> None:
        self._available = False
        try:
            import keyring  # type: ignore[import-not-found]  # noqa: F401

            self._available = True
        except ImportError:
            logger.debug("keyring library not installed — keychain provider disabled")

    def get_secret(self, key: str) -> str | None:
        """Retrieve a secret from the OS keychain."""
        if not self._available:
            return None
        try:
            import keyring  # noqa: F811

            value: str | None = keyring.get_password(self.SERVICE_NAME, key)
            return value
        except Exception:
            logger.debug("Keychain lookup failed for %s", key, exc_info=True)
            return None


class SessionOverrideProvider:
    """In-memory secret overrides for the current session."""

    def __init__(self) -> None:
        self._overrides: dict[str, str] = {}

    def set_secret(self, key: str, value: str) -> None:
        """Set a session-level secret override."""
        self._overrides[key] = value

    def clear_secret(self, key: str) -> None:
        """Remove a session-level override."""
        self._overrides.pop(key, None)

    def get_secret(self, key: str) -> str | None:
        """Retrieve a session override."""
        return self._overrides.get(key)


class CompositeSecretProvider:
    """Tries multiple providers in precedence order.

    Default order: session override -> env -> keychain -> dotenv.
    """

    def __init__(
        self,
        providers: list[SecretProvider] | None = None,
    ) -> None:
        self._session: SessionOverrideProvider | None = None
        self._providers: list[SecretProvider]
        if providers is not None:
            self._providers = providers
        else:
            self._session = SessionOverrideProvider()
            self._providers = [
                self._session,
                EnvSecretProvider(),
                KeychainSecretProvider(),
                DotenvSecretProvider(),
            ]

    @property
    def session(self) -> SessionOverrideProvider:
        """Access the session override provider."""
        if self._session is None:
            raise AttributeError(
                "Session provider not available when using custom provider list"
            )
        return self._session

    def get_secret(self, key: str) -> str | None:
        """Retrieve a secret by trying providers in order."""
        for provider in self._providers:
            value = provider.get_secret(key)
            if value is not None:
                return value
        return None

    def require_secret(self, key: str) -> str:
        """Retrieve a secret, raising if not found.

        Args:
            key: The secret key.

        Returns:
            The secret value.

        Raises:
            ValueError: If the secret is not found in any provider.
        """
        value = self.get_secret(key)
        if value is None:
            raise ValueError(
                f"Required secret '{key}' not found in any provider"
            )
        return value


class ScopedSecretAccessor:
    """Provides scoped access to secrets for a specific connector.

    Workers receive a ScopedSecretAccessor that only allows access
    to the keys their connector is authorized to use.
    """

    def __init__(
        self,
        provider: CompositeSecretProvider,
        allowed_keys: set[str],
    ) -> None:
        self._provider = provider
        self._allowed_keys = frozenset(allowed_keys)

    def get_secret(self, key: str) -> str | None:
        """Retrieve a secret if the key is in the allowed set.

        Args:
            key: The secret key.

        Returns:
            The secret value, or None if not found or not allowed.

        Raises:
            PermissionError: If the key is not in the allowed set.
        """
        if key not in self._allowed_keys:
            raise PermissionError(
                f"Secret '{key}' is not authorized for this connector. "
                f"Allowed keys: {sorted(self._allowed_keys)}"
            )
        return self._provider.get_secret(key)

    @property
    def allowed_keys(self) -> frozenset[str]:
        """Return the set of authorized secret keys."""
        return self._allowed_keys


class RedactionGuard:
    """Strips secrets from strings to prevent leaks in logs and artifacts."""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def register_secret(self, key: str, value: str) -> None:
        """Register a secret value for redaction."""
        if value:
            self._secrets[key] = value

    def redact(self, text: str) -> str:
        """Replace all registered secret values with [REDACTED:key].

        Args:
            text: The text to redact.

        Returns:
            Text with all secret values replaced.
        """
        for key, value in self._secrets.items():
            text = text.replace(value, f"[REDACTED:{key}]")
        return text

    def redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Recursively redact all string values in a dict.

        Args:
            data: The dictionary to redact.

        Returns:
            New dictionary with secret values replaced.
        """
        result: dict[str, Any] = {}
        for k, v in data.items():
            if isinstance(v, str):
                result[k] = self.redact(v)
            elif isinstance(v, dict):
                result[k] = self.redact_dict(v)
            elif isinstance(v, list):
                result[k] = [
                    self.redact(item) if isinstance(item, str) else item
                    for item in v
                ]
            else:
                result[k] = v
        return result

    @property
    def secret_count(self) -> int:
        """Number of registered secrets."""
        return len(self._secrets)
