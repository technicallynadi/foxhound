"""Tests for the secret provider chain."""

import os
import tempfile

import pytest

from foxhound.secrets.provider import (
    CompositeSecretProvider,
    DotenvSecretProvider,
    EnvSecretProvider,
    RedactionGuard,
    ScopedSecretAccessor,
    SessionOverrideProvider,
)


class TestEnvSecretProvider:
    def test_reads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FOXHOUND_TEST_KEY", "test_value")
        provider = EnvSecretProvider()
        assert provider.get_secret("FOXHOUND_TEST_KEY") == "test_value"

    def test_returns_none_for_missing(self) -> None:
        provider = EnvSecretProvider()
        assert provider.get_secret("FOXHOUND_NONEXISTENT_KEY_12345") is None


class TestDotenvSecretProvider:
    def test_reads_dotenv_file(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("API_KEY=secret123\n")
            f.write("DB_URL=postgres://localhost\n")
            f.flush()

            try:
                provider = DotenvSecretProvider(f.name)
                assert provider.get_secret("API_KEY") == "secret123"
                assert provider.get_secret("DB_URL") == "postgres://localhost"
                assert provider.get_secret("MISSING") is None
            finally:
                os.unlink(f.name)

    def test_handles_quoted_values(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write('DOUBLE="double_quoted"\n')
            f.write("SINGLE='single_quoted'\n")
            f.flush()

            try:
                provider = DotenvSecretProvider(f.name)
                assert provider.get_secret("DOUBLE") == "double_quoted"
                assert provider.get_secret("SINGLE") == "single_quoted"
            finally:
                os.unlink(f.name)

    def test_ignores_comments_and_blanks(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# This is a comment\n")
            f.write("\n")
            f.write("VALID=value\n")
            f.flush()

            try:
                provider = DotenvSecretProvider(f.name)
                assert provider.get_secret("VALID") == "value"
            finally:
                os.unlink(f.name)

    def test_missing_file_no_error(self) -> None:
        provider = DotenvSecretProvider("/nonexistent/path/.env")
        assert provider.get_secret("ANY") is None


class TestSessionOverrideProvider:
    def test_set_and_get(self) -> None:
        provider = SessionOverrideProvider()
        provider.set_secret("KEY", "value")
        assert provider.get_secret("KEY") == "value"

    def test_clear(self) -> None:
        provider = SessionOverrideProvider()
        provider.set_secret("KEY", "value")
        provider.clear_secret("KEY")
        assert provider.get_secret("KEY") is None

    def test_returns_none_for_unset(self) -> None:
        provider = SessionOverrideProvider()
        assert provider.get_secret("UNSET") is None


class TestCompositeSecretProvider:
    def test_session_override_takes_precedence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SHARED_KEY", "from_env")
        provider = CompositeSecretProvider()
        provider.session.set_secret("SHARED_KEY", "from_session")

        assert provider.get_secret("SHARED_KEY") == "from_session"

    def test_falls_through_to_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENV_ONLY_KEY", "env_value")
        provider = CompositeSecretProvider()
        assert provider.get_secret("ENV_ONLY_KEY") == "env_value"

    def test_returns_none_when_not_found(self) -> None:
        provider = CompositeSecretProvider()
        assert provider.get_secret("TRULY_MISSING_KEY_99999") is None

    def test_require_secret_raises(self) -> None:
        provider = CompositeSecretProvider()
        with pytest.raises(ValueError, match="not found"):
            provider.require_secret("TRULY_MISSING_KEY_99999")

    def test_require_secret_returns_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REQUIRED_KEY", "found")
        provider = CompositeSecretProvider()
        assert provider.require_secret("REQUIRED_KEY") == "found"

    def test_custom_provider_list(self) -> None:
        session = SessionOverrideProvider()
        session.set_secret("MY_KEY", "custom")
        provider = CompositeSecretProvider(providers=[session])
        assert provider.get_secret("MY_KEY") == "custom"


class TestScopedSecretAccessor:
    def test_allows_authorized_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_abc123")
        composite = CompositeSecretProvider()
        scoped = ScopedSecretAccessor(composite, {"GITHUB_TOKEN"})

        assert scoped.get_secret("GITHUB_TOKEN") == "ghp_abc123"

    def test_rejects_unauthorized_keys(self) -> None:
        composite = CompositeSecretProvider()
        scoped = ScopedSecretAccessor(composite, {"GITHUB_TOKEN"})

        with pytest.raises(PermissionError, match="not authorized"):
            scoped.get_secret("ANTHROPIC_API_KEY")

    def test_allowed_keys_property(self) -> None:
        composite = CompositeSecretProvider()
        scoped = ScopedSecretAccessor(composite, {"KEY_A", "KEY_B"})
        assert scoped.allowed_keys == frozenset({"KEY_A", "KEY_B"})


class TestRedactionGuard:
    def test_redact_single_secret(self) -> None:
        guard = RedactionGuard()
        guard.register_secret("API_KEY", "sk-secret123")

        text = "Using key sk-secret123 for auth"
        assert guard.redact(text) == "Using key [REDACTED:API_KEY] for auth"

    def test_redact_multiple_secrets(self) -> None:
        guard = RedactionGuard()
        guard.register_secret("KEY_A", "aaa")
        guard.register_secret("KEY_B", "bbb")

        text = "Keys: aaa and bbb"
        redacted = guard.redact(text)
        assert "aaa" not in redacted
        assert "bbb" not in redacted

    def test_redact_dict(self) -> None:
        guard = RedactionGuard()
        guard.register_secret("TOKEN", "secret_token")

        data = {
            "auth": "Bearer secret_token",
            "nested": {"key": "secret_token"},
            "list": ["secret_token", "safe"],
            "number": 42,
        }
        result = guard.redact_dict(data)

        assert result["auth"] == "Bearer [REDACTED:TOKEN]"
        assert result["nested"]["key"] == "[REDACTED:TOKEN]"
        assert result["list"][0] == "[REDACTED:TOKEN]"
        assert result["list"][1] == "safe"
        assert result["number"] == 42

    def test_no_secrets_registered(self) -> None:
        guard = RedactionGuard()
        assert guard.redact("plain text") == "plain text"
        assert guard.secret_count == 0

    def test_empty_value_not_registered(self) -> None:
        guard = RedactionGuard()
        guard.register_secret("EMPTY", "")
        assert guard.secret_count == 0
