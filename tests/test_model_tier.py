"""Tests for the model tier system."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from foxhound.core.models import ModelTier

# =============================================================================
# Model Tier Enum and Config
# =============================================================================


class TestModelTierEnum:
    """Tests for the ModelTier enum."""

    def test_tier_values(self) -> None:
        assert ModelTier.REASONING == "reasoning"
        assert ModelTier.BALANCED == "balanced"
        assert ModelTier.FAST == "fast"

    def test_tier_from_string(self) -> None:
        assert ModelTier("reasoning") == ModelTier.REASONING
        assert ModelTier("balanced") == ModelTier.BALANCED
        assert ModelTier("fast") == ModelTier.FAST

    def test_tier_invalid(self) -> None:
        with pytest.raises(ValueError):
            ModelTier("invalid")

    def test_all_tiers(self) -> None:
        assert len(ModelTier) == 4

    def test_tier_is_string(self) -> None:
        assert isinstance(ModelTier.BALANCED, str)
        assert ModelTier.BALANCED == "balanced"


class TestExecutionSnapshotTier:
    """Tests for ModelTier in ExecutionSnapshot."""

    def test_default_tier(self) -> None:
        from foxhound.core.models import ExecutionSnapshot, PolicyRef, RecipeRef

        snapshot = ExecutionSnapshot(
            recipe_ref=RecipeRef(name="test", version="1.0.0", content_hash="abc"),
            policy_ref=PolicyRef(name="test", version="1.0.0", content_hash="abc"),
            config_hash="test",
        )
        assert snapshot.model_tier == ModelTier.BALANCED

    def test_set_tier(self) -> None:
        from foxhound.core.models import ExecutionSnapshot, PolicyRef, RecipeRef

        snapshot = ExecutionSnapshot(
            recipe_ref=RecipeRef(name="test", version="1.0.0", content_hash="abc"),
            policy_ref=PolicyRef(name="test", version="1.0.0", content_hash="abc"),
            config_hash="test",
            model_tier=ModelTier.REASONING,
        )
        assert snapshot.model_tier == ModelTier.REASONING

    def test_tier_from_string_in_snapshot(self) -> None:
        from foxhound.core.models import ExecutionSnapshot, PolicyRef, RecipeRef

        snapshot = ExecutionSnapshot(
            recipe_ref=RecipeRef(name="test", version="1.0.0", content_hash="abc"),
            policy_ref=PolicyRef(name="test", version="1.0.0", content_hash="abc"),
            config_hash="test",
            model_tier="fast",  # type: ignore[arg-type]
        )
        assert snapshot.model_tier == ModelTier.FAST


class TestManifestTier:
    """Tests for ModelTier in Manifest."""

    def test_manifest_model_resolved(self) -> None:
        from foxhound.core.models import (
            ExecutionStrategy,
            Manifest,
            PolicyRef,
            RecipeRef,
        )

        manifest = Manifest(
            manifest_id="m1",
            run_id="r1",
            work_item_id="wi1",
            repo_id="repo1",
            recipe_ref=RecipeRef(name="test", version="1.0.0", content_hash="abc"),
            policy_ref=PolicyRef(name="test", version="1.0.0", content_hash="abc"),
            context_pack_hash="hash",
            execution_environment_fingerprint="fp",
            execution_strategy=ExecutionStrategy.ONE_SHOT,
            model_provider="anthropic",
            model_tier=ModelTier.BALANCED,
            model_resolved="anthropic/claude-sonnet-4.6",
            workspace_id="ws1",
        )
        assert manifest.model_tier == ModelTier.BALANCED
        assert manifest.model_resolved == "anthropic/claude-sonnet-4.6"


class TestFoxhoundConfig:
    """Tests for config loading and validation."""

    def test_load_single_provider(self, tmp_path: Path) -> None:
        from foxhound.core.config import load_config

        config_path = tmp_path / "foxhound.yaml"
        config_path.write_text(
            "models:\n"
            "  provider: anthropic\n"
            "  api_key_env: ANTHROPIC_API_KEY\n"
            "  tiers:\n"
            "    reasoning: claude-opus-4.6\n"
            "    balanced: claude-sonnet-4.6\n"
            "    fast: claude-haiku-4.5\n"
        )
        config = load_config(config_path)
        assert config.models.provider == "anthropic"
        assert "anthropic" in config.models.providers
        assert config.models.tiers["reasoning"] == "claude-opus-4.6"

    def test_load_multi_provider(self, tmp_path: Path) -> None:
        from foxhound.core.config import load_config

        config_path = tmp_path / "foxhound.yaml"
        config_path.write_text(
            "models:\n"
            "  providers:\n"
            "    anthropic:\n"
            "      api_key_env: ANTHROPIC_API_KEY\n"
            "    openai:\n"
            "      api_key_env: OPENAI_API_KEY\n"
            "  tiers:\n"
            "    reasoning: anthropic/claude-opus-4.6\n"
            "    balanced: openai/gpt-4.1-mini\n"
            "    fast: openai/gpt-4.1-nano\n"
        )
        config = load_config(config_path)
        assert "anthropic" in config.models.providers
        assert "openai" in config.models.providers

    def test_resolve_tier_single_provider(self, tmp_path: Path) -> None:
        from foxhound.core.config import load_config

        config_path = tmp_path / "foxhound.yaml"
        config_path.write_text(
            "models:\n"
            "  provider: anthropic\n"
            "  api_key_env: ANTHROPIC_API_KEY\n"
            "  tiers:\n"
            "    reasoning: claude-opus-4.6\n"
            "    balanced: claude-sonnet-4.6\n"
            "    fast: claude-haiku-4.5\n"
        )
        config = load_config(config_path)
        provider, model = config.models.resolve_tier(ModelTier.REASONING)
        assert provider == "anthropic"
        assert model == "claude-opus-4.6"

    def test_resolve_tier_multi_provider(self, tmp_path: Path) -> None:
        from foxhound.core.config import load_config

        config_path = tmp_path / "foxhound.yaml"
        config_path.write_text(
            "models:\n"
            "  providers:\n"
            "    anthropic:\n"
            "      api_key_env: ANTHROPIC_API_KEY\n"
            "    openai:\n"
            "      api_key_env: OPENAI_API_KEY\n"
            "  tiers:\n"
            "    reasoning: anthropic/claude-opus-4.6\n"
            "    balanced: openai/gpt-4.1-mini\n"
            "    fast: openai/gpt-4.1-nano\n"
        )
        config = load_config(config_path)
        provider, model = config.models.resolve_tier(ModelTier.REASONING)
        assert provider == "anthropic"
        assert model == "claude-opus-4.6"
        provider, model = config.models.resolve_tier(ModelTier.BALANCED)
        assert provider == "openai"
        assert model == "gpt-4.1-mini"

    def test_resolve_tier_missing(self, tmp_path: Path) -> None:
        from foxhound.core.config import load_config

        config_path = tmp_path / "foxhound.yaml"
        config_path.write_text(
            "models:\n"
            "  provider: anthropic\n"
            "  api_key_env: ANTHROPIC_API_KEY\n"
            "  tiers:\n"
            "    balanced: claude-sonnet-4.6\n"
        )
        config = load_config(config_path)
        with pytest.raises(ValueError, match="No model configured"):
            config.models.resolve_tier(ModelTier.REASONING)

    def test_resolve_tier_unknown_provider(self, tmp_path: Path) -> None:
        from foxhound.core.config import load_config

        config_path = tmp_path / "foxhound.yaml"
        config_path.write_text(
            "models:\n"
            "  providers:\n"
            "    anthropic:\n"
            "      api_key_env: ANTHROPIC_API_KEY\n"
            "  tiers:\n"
            "    reasoning: unknown/some-model\n"
        )
        config = load_config(config_path)
        with pytest.raises(ValueError, match="not in the providers"):
            config.models.resolve_tier(ModelTier.REASONING)

    def test_load_missing_file(self, tmp_path: Path) -> None:
        from foxhound.core.config import load_config

        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_load_invalid_yaml(self, tmp_path: Path) -> None:
        from foxhound.core.config import load_config

        config_path = tmp_path / "foxhound.yaml"
        config_path.write_text("  bad: yaml\n  : invalid")
        with pytest.raises(ValueError, match="Invalid YAML"):
            load_config(config_path)

    def test_load_non_mapping(self, tmp_path: Path) -> None:
        from foxhound.core.config import load_config

        config_path = tmp_path / "foxhound.yaml"
        config_path.write_text("- list item\n- not a mapping")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_config(config_path)

    def test_provider_config_base_url(self, tmp_path: Path) -> None:
        from foxhound.core.config import load_config

        config_path = tmp_path / "foxhound.yaml"
        config_path.write_text(
            "models:\n"
            "  providers:\n"
            "    local:\n"
            "      api_key_env: LOCAL_API_KEY\n"
            "      base_url: http://localhost:11434/v1\n"
            "  tiers:\n"
            "    reasoning: qwen3-32b\n"
            "    balanced: qwen3-8b\n"
            "    fast: qwen3-4b\n"
        )
        config = load_config(config_path)
        local_config = config.models.get_provider_config("local")
        assert local_config is not None
        assert local_config.base_url == "http://localhost:11434/v1"

    def test_empty_config(self, tmp_path: Path) -> None:
        from foxhound.core.config import load_config

        config_path = tmp_path / "foxhound.yaml"
        config_path.write_text("{}")
        config = load_config(config_path)
        assert config.models.tiers == {}

    def test_resolve_ambiguous_multi_provider(self, tmp_path: Path) -> None:
        from foxhound.core.config import load_config

        config_path = tmp_path / "foxhound.yaml"
        config_path.write_text(
            "models:\n"
            "  providers:\n"
            "    anthropic:\n"
            "      api_key_env: ANTHROPIC_API_KEY\n"
            "    openai:\n"
            "      api_key_env: OPENAI_API_KEY\n"
            "  tiers:\n"
            "    reasoning: some-model\n"
        )
        config = load_config(config_path)
        with pytest.raises(ValueError, match="no provider prefix"):
            config.models.resolve_tier(ModelTier.REASONING)


# =============================================================================
# Provider Adapter Protocol
# =============================================================================


class TestProviderProtocol:
    """Tests for the ProviderAdapter protocol."""

    def test_protocol_check(self) -> None:
        from foxhound.adapters.provider import ProviderAdapter

        adapter = MagicMock(spec=ProviderAdapter)
        assert isinstance(adapter, ProviderAdapter)

    def test_token_usage(self) -> None:
        from foxhound.adapters.provider import TokenUsage

        usage = TokenUsage(input_tokens=100, output_tokens=50)
        assert usage.total_tokens == 150
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50

    def test_token_usage_defaults(self) -> None:
        from foxhound.adapters.provider import TokenUsage

        usage = TokenUsage()
        assert usage.total_tokens == 0

    def test_token_usage_with_cache(self) -> None:
        from foxhound.adapters.provider import TokenUsage

        usage = TokenUsage(
            input_tokens=100,
            output_tokens=50,
            cache_read_tokens=20,
            cache_write_tokens=10,
        )
        assert usage.total_tokens == 150

    def test_model_response(self) -> None:
        from foxhound.adapters.provider import ModelResponse, TokenUsage

        response = ModelResponse(
            content="Hello",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            model_id="test-model",
            stop_reason="end_turn",
        )
        assert response.content == "Hello"
        assert response.usage.total_tokens == 15

    def test_model_request(self) -> None:
        from foxhound.adapters.provider import ModelRequest

        request = ModelRequest(
            messages=[{"role": "user", "content": "test"}],
            model_id="test-model",
            max_tokens=100,
        )
        assert len(request.messages) == 1
        assert request.model_id == "test-model"


class TestAnthropicAdapter:
    """Tests for the Anthropic adapter."""

    def test_provider_name(self) -> None:
        from foxhound.adapters.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter()
        assert adapter.provider_name == "anthropic"

    def test_authenticate_no_package(self) -> None:
        from foxhound.adapters.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter()
        with patch.dict("sys.modules", {"anthropic": None}):
            result = adapter.authenticate("test-key")
            assert result is False

    def test_complete_not_authenticated(self) -> None:
        from foxhound.adapters.anthropic_adapter import AnthropicAdapter
        from foxhound.adapters.provider import ModelRequest

        adapter = AnthropicAdapter()
        with pytest.raises(RuntimeError, match="not authenticated"):
            adapter.complete(ModelRequest(
                messages=[{"role": "user", "content": "test"}],
                model_id="test",
            ))

    def test_check_model_not_authenticated(self) -> None:
        from foxhound.adapters.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter()
        assert adapter.check_model("test") is False

    def test_estimate_cost_known_model(self) -> None:
        from foxhound.adapters.anthropic_adapter import AnthropicAdapter
        from foxhound.adapters.provider import TokenUsage

        adapter = AnthropicAdapter()
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = adapter.estimate_cost(usage, "claude-sonnet-4.6")
        assert cost == pytest.approx(18.0)  # 3.0 + 15.0

    def test_estimate_cost_unknown_model(self) -> None:
        from foxhound.adapters.anthropic_adapter import AnthropicAdapter
        from foxhound.adapters.provider import TokenUsage

        adapter = AnthropicAdapter()
        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        cost = adapter.estimate_cost(usage, "unknown-model")
        assert cost == 0.0

    def test_estimate_cost_opus(self) -> None:
        from foxhound.adapters.anthropic_adapter import AnthropicAdapter
        from foxhound.adapters.provider import TokenUsage

        adapter = AnthropicAdapter()
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = adapter.estimate_cost(usage, "claude-opus-4.6")
        assert cost == pytest.approx(90.0)  # 15.0 + 75.0

    def test_estimate_cost_haiku(self) -> None:
        from foxhound.adapters.anthropic_adapter import AnthropicAdapter
        from foxhound.adapters.provider import TokenUsage

        adapter = AnthropicAdapter()
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = adapter.estimate_cost(usage, "claude-haiku-4.5")
        assert cost == pytest.approx(4.8)  # 0.80 + 4.0


class TestOpenAIAdapter:
    """Tests for the OpenAI adapter."""

    def test_provider_name(self) -> None:
        from foxhound.adapters.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter()
        assert adapter.provider_name == "openai"

    def test_authenticate_no_package(self) -> None:
        from foxhound.adapters.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter()
        with patch.dict("sys.modules", {"openai": None}):
            result = adapter.authenticate("test-key")
            assert result is False

    def test_complete_not_authenticated(self) -> None:
        from foxhound.adapters.openai_adapter import OpenAIAdapter
        from foxhound.adapters.provider import ModelRequest

        adapter = OpenAIAdapter()
        with pytest.raises(RuntimeError, match="not authenticated"):
            adapter.complete(ModelRequest(
                messages=[{"role": "user", "content": "test"}],
                model_id="test",
            ))

    def test_check_model_not_authenticated(self) -> None:
        from foxhound.adapters.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter()
        assert adapter.check_model("test") is False

    def test_estimate_cost_known_model(self) -> None:
        from foxhound.adapters.openai_adapter import OpenAIAdapter
        from foxhound.adapters.provider import TokenUsage

        adapter = OpenAIAdapter()
        usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = adapter.estimate_cost(usage, "gpt-4.1")
        assert cost == pytest.approx(10.0)  # 2.0 + 8.0

    def test_estimate_cost_unknown_model(self) -> None:
        from foxhound.adapters.openai_adapter import OpenAIAdapter
        from foxhound.adapters.provider import TokenUsage

        adapter = OpenAIAdapter()
        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        cost = adapter.estimate_cost(usage, "unknown-model")
        assert cost == 0.0


# =============================================================================
# Provider Registry and Auto-Defaults
# =============================================================================


class TestProviderRegistry:
    """Tests for the provider registry."""

    def test_known_providers(self) -> None:
        from foxhound.adapters.registry import KNOWN_PROVIDERS

        assert "anthropic" in KNOWN_PROVIDERS
        assert "openai" in KNOWN_PROVIDERS
        assert "google" in KNOWN_PROVIDERS
        assert "deepseek" in KNOWN_PROVIDERS
        assert "local" in KNOWN_PROVIDERS

    def test_get_suggested_tiers_anthropic(self) -> None:
        from foxhound.adapters.registry import get_suggested_tiers

        tiers = get_suggested_tiers("anthropic")
        assert tiers is not None
        assert "reasoning" in tiers
        assert "balanced" in tiers
        assert "fast" in tiers
        assert "claude-opus" in tiers["reasoning"]

    def test_get_suggested_tiers_openai(self) -> None:
        from foxhound.adapters.registry import get_suggested_tiers

        tiers = get_suggested_tiers("openai")
        assert tiers is not None
        assert "gpt-4.1" in tiers["reasoning"]

    def test_get_suggested_tiers_unknown(self) -> None:
        from foxhound.adapters.registry import get_suggested_tiers

        assert get_suggested_tiers("nonexistent") is None

    def test_get_default_api_key_env(self) -> None:
        from foxhound.adapters.registry import get_default_api_key_env

        assert get_default_api_key_env("anthropic") == "ANTHROPIC_API_KEY"
        assert get_default_api_key_env("openai") == "OPENAI_API_KEY"
        assert get_default_api_key_env("custom") == "CUSTOM_API_KEY"

    def test_apply_auto_defaults_empty(self) -> None:
        from foxhound.adapters.registry import apply_auto_defaults

        result = apply_auto_defaults("anthropic", {})
        assert "reasoning" in result
        assert "balanced" in result
        assert "fast" in result
        assert "claude-opus" in result["reasoning"]

    def test_apply_auto_defaults_partial(self) -> None:
        from foxhound.adapters.registry import apply_auto_defaults

        result = apply_auto_defaults("anthropic", {"balanced": "my-custom-model"})
        assert result["balanced"] == "my-custom-model"
        assert "claude-opus" in result["reasoning"]
        assert "claude-haiku" in result["fast"]

    def test_apply_auto_defaults_unknown_provider(self) -> None:
        from foxhound.adapters.registry import apply_auto_defaults

        result = apply_auto_defaults("unknown", {"balanced": "my-model"})
        assert result["balanced"] == "my-model"
        # Missing tiers fall back to balanced model
        assert result["reasoning"] == "my-model"
        assert result["fast"] == "my-model"

    def test_generate_config_yaml(self) -> None:
        from foxhound.adapters.registry import generate_config_yaml

        yaml_str = generate_config_yaml("anthropic")
        assert "provider: anthropic" in yaml_str
        assert "api_key_env: ANTHROPIC_API_KEY" in yaml_str
        assert "reasoning:" in yaml_str
        assert "balanced:" in yaml_str
        assert "fast:" in yaml_str
        assert "claude-opus" in yaml_str

    def test_generate_config_yaml_custom_key(self) -> None:
        from foxhound.adapters.registry import generate_config_yaml

        yaml_str = generate_config_yaml("openai", api_key_env="MY_KEY")
        assert "api_key_env: MY_KEY" in yaml_str

    def test_worker_default_tiers(self) -> None:
        from foxhound.adapters.registry import get_worker_default_tier

        assert get_worker_default_tier("ScoutWorker") == ModelTier.FAST
        assert get_worker_default_tier("DiscoveryWorker") == ModelTier.BALANCED
        assert get_worker_default_tier("ExecutionWorker") == ModelTier.BALANCED
        assert get_worker_default_tier("CodeReviewWorker") == ModelTier.REASONING
        assert get_worker_default_tier("UnknownWorker") == ModelTier.BALANCED


# =============================================================================
# Model Router
# =============================================================================


class TestModelRouter:
    """Tests for the ModelRouter."""

    def _make_config(self, tmp_path: Path) -> object:
        from foxhound.core.config import load_config

        config_path = tmp_path / "foxhound.yaml"
        config_path.write_text(
            "models:\n"
            "  provider: anthropic\n"
            "  api_key_env: ANTHROPIC_API_KEY\n"
            "  tiers:\n"
            "    reasoning: claude-opus-4.6\n"
            "    balanced: claude-sonnet-4.6\n"
            "    fast: claude-haiku-4.5\n"
        )
        return load_config(config_path)

    def test_initialize_no_api_key(self, tmp_path: Path) -> None:
        from foxhound.adapters.router import ModelRouter

        config = self._make_config(tmp_path)
        router = ModelRouter(config)
        with patch.dict(os.environ, {}, clear=True):
            errors = router.initialize()
        assert len(errors) == 1
        assert "not set" in errors[0]

    def test_initialize_with_mock_adapter(self, tmp_path: Path) -> None:
        from foxhound.adapters.router import ModelRouter

        config = self._make_config(tmp_path)
        router = ModelRouter(config)

        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = True
        mock_adapter.provider_name = "anthropic"

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.dict(
                "foxhound.adapters.router.ADAPTER_FACTORIES",
                {"anthropic": lambda: mock_adapter},
            ):
                errors = router.initialize()

        assert errors == []
        assert router.is_ready()
        assert "anthropic" in router.authenticated_providers

    def test_resolve_tier(self, tmp_path: Path) -> None:
        from foxhound.adapters.router import ModelRouter

        config = self._make_config(tmp_path)
        router = ModelRouter(config)

        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = True
        router._adapters["anthropic"] = mock_adapter
        router._authenticated.add("anthropic")

        provider, model_id, adapter = router.resolve(ModelTier.REASONING)
        assert provider == "anthropic"
        assert model_id == "claude-opus-4.6"
        assert adapter is mock_adapter

    def test_resolve_unauthenticated(self, tmp_path: Path) -> None:
        from foxhound.adapters.router import ModelRouter

        config = self._make_config(tmp_path)
        router = ModelRouter(config)

        with pytest.raises(RuntimeError, match="not authenticated"):
            router.resolve(ModelTier.REASONING)

    def test_complete_routes_to_adapter(self, tmp_path: Path) -> None:
        from foxhound.adapters.provider import ModelResponse, TokenUsage
        from foxhound.adapters.router import ModelRouter

        config = self._make_config(tmp_path)
        router = ModelRouter(config)

        mock_adapter = MagicMock()
        mock_adapter.authenticate.return_value = True
        mock_adapter.complete.return_value = ModelResponse(
            content="Hello!",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            model_id="claude-sonnet-4.6",
        )
        mock_adapter.estimate_cost.return_value = 0.001
        router._adapters["anthropic"] = mock_adapter
        router._authenticated.add("anthropic")

        response = router.complete(
            ModelTier.BALANCED,
            messages=[{"role": "user", "content": "test"}],
        )
        assert response.content == "Hello!"
        mock_adapter.complete.assert_called_once()
        assert router.total_cost == pytest.approx(0.001)

    def test_check_model(self, tmp_path: Path) -> None:
        from foxhound.adapters.router import ModelRouter

        config = self._make_config(tmp_path)
        router = ModelRouter(config)

        mock_adapter = MagicMock()
        mock_adapter.check_model.return_value = True
        router._adapters["anthropic"] = mock_adapter
        router._authenticated.add("anthropic")

        assert router.check_model(ModelTier.BALANCED) is True
        mock_adapter.check_model.assert_called_with("claude-sonnet-4.6")

    def test_check_model_not_ready(self, tmp_path: Path) -> None:
        from foxhound.adapters.router import ModelRouter

        config = self._make_config(tmp_path)
        router = ModelRouter(config)
        assert router.check_model(ModelTier.BALANCED) is False

    def test_estimate_cost(self, tmp_path: Path) -> None:
        from foxhound.adapters.provider import TokenUsage
        from foxhound.adapters.router import ModelRouter

        config = self._make_config(tmp_path)
        router = ModelRouter(config)

        mock_adapter = MagicMock()
        mock_adapter.estimate_cost.return_value = 0.05
        router._adapters["anthropic"] = mock_adapter
        router._authenticated.add("anthropic")

        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        cost = router.estimate_cost(ModelTier.BALANCED, usage)
        assert cost == pytest.approx(0.05)

    def test_total_cost_accumulates(self, tmp_path: Path) -> None:
        from foxhound.adapters.provider import ModelResponse, TokenUsage
        from foxhound.adapters.router import ModelRouter

        config = self._make_config(tmp_path)
        router = ModelRouter(config)

        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = ModelResponse(
            content="ok",
            usage=TokenUsage(input_tokens=10, output_tokens=5),
        )
        mock_adapter.estimate_cost.return_value = 0.01
        router._adapters["anthropic"] = mock_adapter
        router._authenticated.add("anthropic")

        router.complete(ModelTier.BALANCED, messages=[{"role": "user", "content": "1"}])
        router.complete(ModelTier.BALANCED, messages=[{"role": "user", "content": "2"}])
        assert router.total_cost == pytest.approx(0.02)

    def test_unknown_provider_error(self, tmp_path: Path) -> None:
        from foxhound.adapters.router import ModelRouter
        from foxhound.core.config import load_config

        config_path = tmp_path / "foxhound.yaml"
        config_path.write_text(
            "models:\n"
            "  providers:\n"
            "    fakecloud:\n"
            "      api_key_env: FAKE_KEY\n"
            "  tiers:\n"
            "    balanced: some-model\n"
        )
        config = load_config(config_path)
        router = ModelRouter(config)
        with patch.dict(os.environ, {"FAKE_KEY": "val"}):
            errors = router.initialize()
        assert any("Unknown provider" in e for e in errors)


# =============================================================================
# Tier Resolver (recipe overrides + execution wiring)
# =============================================================================


class TestTierResolver:
    """Tests for tier resolution with recipe overrides."""

    def test_default_tier_for_worker(self) -> None:
        from foxhound.adapters.tier_resolver import resolve_effective_tier

        tier = resolve_effective_tier(
            worker_type="ExecutionWorker",
            snapshot_tier=ModelTier.BALANCED,
        )
        assert tier == ModelTier.BALANCED

    def test_recipe_override_by_step(self) -> None:
        from foxhound.adapters.tier_resolver import resolve_effective_tier

        tier = resolve_effective_tier(
            worker_type="ExecutionWorker",
            snapshot_tier=ModelTier.BALANCED,
            recipe_tier_overrides={"execution": "reasoning"},
            step_name="execution",
        )
        assert tier == ModelTier.REASONING

    def test_recipe_override_by_worker_type(self) -> None:
        from foxhound.adapters.tier_resolver import resolve_effective_tier

        tier = resolve_effective_tier(
            worker_type="ExecutionWorker",
            snapshot_tier=ModelTier.BALANCED,
            recipe_tier_overrides={"execution": "fast"},
        )
        assert tier == ModelTier.FAST

    def test_snapshot_tier_overrides_default(self) -> None:
        from foxhound.adapters.tier_resolver import resolve_effective_tier

        tier = resolve_effective_tier(
            worker_type="ExecutionWorker",
            snapshot_tier=ModelTier.REASONING,
        )
        assert tier == ModelTier.REASONING

    def test_recipe_override_takes_priority(self) -> None:
        from foxhound.adapters.tier_resolver import resolve_effective_tier

        tier = resolve_effective_tier(
            worker_type="ExecutionWorker",
            snapshot_tier=ModelTier.REASONING,
            recipe_tier_overrides={"execution": "fast"},
            step_name="execution",
        )
        assert tier == ModelTier.FAST

    def test_invalid_recipe_override_ignored(self) -> None:
        from foxhound.adapters.tier_resolver import resolve_effective_tier

        tier = resolve_effective_tier(
            worker_type="ExecutionWorker",
            snapshot_tier=ModelTier.BALANCED,
            recipe_tier_overrides={"execution": "invalid_tier"},
            step_name="execution",
        )
        assert tier == ModelTier.BALANCED

    def test_code_review_worker_default(self) -> None:
        from foxhound.adapters.tier_resolver import resolve_effective_tier

        tier = resolve_effective_tier(
            worker_type="CodeReviewWorker",
            snapshot_tier=ModelTier.REASONING,
        )
        assert tier == ModelTier.REASONING

    def test_scout_worker_default(self) -> None:
        from foxhound.adapters.tier_resolver import resolve_effective_tier

        tier = resolve_effective_tier(
            worker_type="ScoutWorker",
            snapshot_tier=ModelTier.FAST,
        )
        assert tier == ModelTier.FAST

    def test_review_intermediate_override(self) -> None:
        from foxhound.adapters.tier_resolver import resolve_effective_tier

        tier = resolve_effective_tier(
            worker_type="CodeReviewWorker",
            snapshot_tier=ModelTier.REASONING,
            recipe_tier_overrides={
                "review_intermediate": "fast",
                "review_final": "reasoning",
            },
            step_name="review_intermediate",
        )
        assert tier == ModelTier.FAST

    def test_no_overrides_unknown_worker(self) -> None:
        from foxhound.adapters.tier_resolver import resolve_effective_tier

        tier = resolve_effective_tier(
            worker_type="CustomWorker",
            snapshot_tier=ModelTier.BALANCED,
        )
        assert tier == ModelTier.BALANCED


# =============================================================================
# Recipe tier override validation
# =============================================================================


class TestRecipeTierOverrides:
    """Tests for recipe tier override validation."""

    def test_valid_tier_overrides(self) -> None:
        from foxhound.recipes.loader import Recipe

        recipe = Recipe(
            name="test",
            version="1.0.0",
            tier_overrides={"execution": "reasoning", "review_final": "fast"},
        )
        assert recipe.tier_overrides["execution"] == "reasoning"

    def test_invalid_tier_override_rejected(self) -> None:
        from foxhound.recipes.loader import Recipe

        with pytest.raises(ValueError, match="tier override"):
            Recipe(
                name="test",
                version="1.0.0",
                tier_overrides={"execution": "invalid_tier"},
            )

    def test_empty_tier_overrides(self) -> None:
        from foxhound.recipes.loader import Recipe

        recipe = Recipe(name="test", version="1.0.0")
        assert recipe.tier_overrides == {}


# =============================================================================
# Queue with ModelTier
# =============================================================================


class TestQueueModelTier:
    """Tests for ModelTier in the job queue."""

    def test_enqueue_with_tier(self, tmp_path: Path) -> None:
        from foxhound.core.models import (
            ExecutionStrategy,
            JobType,
            PolicyRef,
            RecipeRef,
        )
        from foxhound.core.queue import JobQueue
        from foxhound.storage.database import Database

        db = Database(tmp_path / "test.db")
        queue = JobQueue(db)
        job = queue.enqueue(
            work_item_id="wi1",
            repo_id="r1",
            job_type=JobType.EXECUTION,
            recipe_ref=RecipeRef(name="test", version="1.0.0", content_hash="abc"),
            policy_ref=PolicyRef(name="default", version="1.0.0", content_hash="def"),
            config_hash="hash",
            execution_strategy=ExecutionStrategy.ONE_SHOT,
            model_tier=ModelTier.REASONING,
        )
        assert job.execution_snapshot.model_tier == ModelTier.REASONING
        db.close()

    def test_enqueue_default_tier(self, tmp_path: Path) -> None:
        from foxhound.core.models import (
            JobType,
            PolicyRef,
            RecipeRef,
        )
        from foxhound.core.queue import JobQueue
        from foxhound.storage.database import Database

        db = Database(tmp_path / "test.db")
        queue = JobQueue(db)
        job = queue.enqueue(
            work_item_id="wi1",
            repo_id="r1",
            job_type=JobType.EXECUTION,
            recipe_ref=RecipeRef(name="test", version="1.0.0", content_hash="abc"),
            policy_ref=PolicyRef(name="default", version="1.0.0", content_hash="def"),
            config_hash="hash",
        )
        assert job.execution_snapshot.model_tier == ModelTier.BALANCED
        db.close()
