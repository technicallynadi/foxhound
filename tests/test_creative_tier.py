"""Tests for Creative Tier & Visual Assets (Milestone 7).

Covers: #70 creative tier enum/config, #71 image adapters,
#72 mockup-to-code pipeline, #73 visual asset generation.
"""

import base64
import tempfile
from pathlib import Path

import pytest

from foxhound.adapters.image_adapter import (
    IMAGE_ADAPTER_FACTORIES,
    IMAGE_PRICING,
    GoogleImageAdapter,
    ImageRequest,
    ImageResult,
    OpenAIImageAdapter,
    save_base64_image,
    save_image_data,
)
from foxhound.adapters.registry import (
    PROVIDER_TIER_SUGGESTIONS,
    apply_auto_defaults,
    generate_config_yaml,
)
from foxhound.adapters.router import ModelRouter
from foxhound.core.config import FoxhoundConfig, ModelsConfig
from foxhound.core.models import ModelTier
from foxhound.execution.creative import (
    ASSET_TYPES,
    CreativeStepResult,
    ImageStepConfig,
    VisualAssetConfig,
    VisualAssetResults,
    build_asset_references,
    generate_visual_assets,
    is_creative_available,
    run_image_step,
    run_mockup_to_code,
)
from foxhound.recipes.loader import Recipe

# ============================================================================
# #70: Creative Tier in Model Tier System
# ============================================================================


class TestModelTierEnum:
    def test_creative_tier_exists(self) -> None:
        assert ModelTier.CREATIVE == "creative"

    def test_four_tiers(self) -> None:
        assert len(ModelTier) == 4

    def test_all_tier_values(self) -> None:
        values = {t.value for t in ModelTier}
        assert values == {"reasoning", "balanced", "fast", "creative"}

    def test_creative_tier_from_string(self) -> None:
        tier = ModelTier("creative")
        assert tier == ModelTier.CREATIVE


class TestCreativeTierConfig:
    def test_config_with_creative_tier(self) -> None:
        config = ModelsConfig(
            provider="openai",
            api_key_env="OPENAI_API_KEY",
            tiers={
                "reasoning": "gpt-4.1",
                "balanced": "gpt-4.1-mini",
                "fast": "gpt-4.1-nano",
                "creative": "gpt-image-1",
            },
        )
        provider, model = config.resolve_tier(ModelTier.CREATIVE)
        assert provider == "openai"
        assert model == "gpt-image-1"

    def test_config_without_creative_tier(self) -> None:
        config = ModelsConfig(
            provider="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
            tiers={
                "reasoning": "claude-opus-4.6",
                "balanced": "claude-sonnet-4.6",
                "fast": "claude-haiku-4.5",
            },
        )
        with pytest.raises(ValueError, match="No model configured for tier 'creative'"):
            config.resolve_tier(ModelTier.CREATIVE)

    def test_creative_tier_with_provider_prefix(self) -> None:
        from foxhound.core.config import ProviderConfig

        config = ModelsConfig(
            providers={
                "openai": ProviderConfig(api_key_env="OPENAI_API_KEY"),
                "google": ProviderConfig(api_key_env="GOOGLE_API_KEY"),
            },
            tiers={
                "reasoning": "openai/gpt-4.1",
                "balanced": "openai/gpt-4.1-mini",
                "fast": "openai/gpt-4.1-nano",
                "creative": "google/gemini-2.0-flash-preview-image-generation",
            },
        )
        provider, model = config.resolve_tier(ModelTier.CREATIVE)
        assert provider == "google"
        assert model == "gemini-2.0-flash-preview-image-generation"


class TestCreativeTierRegistry:
    def test_openai_has_creative_suggestion(self) -> None:
        suggestions = PROVIDER_TIER_SUGGESTIONS["openai"]
        assert ModelTier.CREATIVE in suggestions
        assert suggestions[ModelTier.CREATIVE] == "gpt-image-1"

    def test_google_has_creative_suggestion(self) -> None:
        suggestions = PROVIDER_TIER_SUGGESTIONS["google"]
        assert ModelTier.CREATIVE in suggestions

    def test_anthropic_no_creative_suggestion(self) -> None:
        suggestions = PROVIDER_TIER_SUGGESTIONS["anthropic"]
        assert ModelTier.CREATIVE not in suggestions

    def test_auto_defaults_skips_creative_for_anthropic(self) -> None:
        result = apply_auto_defaults("anthropic", {})
        assert "reasoning" in result
        assert "balanced" in result
        assert "fast" in result
        assert "creative" not in result

    def test_auto_defaults_includes_creative_for_openai(self) -> None:
        result = apply_auto_defaults("openai", {})
        assert "creative" in result
        assert result["creative"] == "gpt-image-1"

    def test_generate_config_skips_creative_for_anthropic(self) -> None:
        yaml_str = generate_config_yaml("anthropic")
        assert "creative:" not in yaml_str

    def test_generate_config_includes_creative_for_openai(self) -> None:
        yaml_str = generate_config_yaml("openai")
        assert "creative:" in yaml_str


class TestCreativeTierRecipe:
    def test_recipe_with_creative_tier_override(self) -> None:
        recipe = Recipe(
            name="test", version="1.0.0",
            tier_overrides={"image_generation": "creative"},
        )
        assert recipe.tier_overrides["image_generation"] == "creative"

    def test_creative_tier_invalid_step_rejected(self) -> None:
        with pytest.raises(ValueError, match="tier override"):
            Recipe(
                name="test", version="1.0.0",
                tier_overrides={"image_generation": "invalid_tier"},
            )


class TestCreativeTierRouter:
    def test_is_tier_configured_creative(self) -> None:
        config = FoxhoundConfig(models=ModelsConfig(
            provider="openai",
            api_key_env="OPENAI_API_KEY",
            tiers={
                "reasoning": "gpt-4.1",
                "balanced": "gpt-4.1-mini",
                "fast": "gpt-4.1-nano",
                "creative": "gpt-image-1",
            },
        ))
        router = ModelRouter(config)
        assert router.is_tier_configured(ModelTier.CREATIVE) is True

    def test_is_tier_not_configured_creative(self) -> None:
        config = FoxhoundConfig(models=ModelsConfig(
            provider="anthropic",
            api_key_env="ANTHROPIC_API_KEY",
            tiers={
                "reasoning": "claude-opus-4.6",
                "balanced": "claude-sonnet-4.6",
                "fast": "claude-haiku-4.5",
            },
        ))
        router = ModelRouter(config)
        assert router.is_tier_configured(ModelTier.CREATIVE) is False


class TestCreativeTierManifest:
    def test_manifest_records_creative_tier(self) -> None:
        from foxhound.core.models import (
            ExecutionStrategy,
            Manifest,
            PolicyRef,
            RecipeRef,
        )

        manifest = Manifest(
            manifest_id="m1",
            run_id="r1",
            repo_id="repo1",
            work_item_id="wi1",
            recipe_ref=RecipeRef(name="r", version="1.0.0", content_hash="h"),
            policy_ref=PolicyRef(name="p", version="1.0.0", content_hash="h"),
            context_pack_hash="ctx",
            execution_environment_fingerprint="env",
            execution_strategy=ExecutionStrategy.ONE_SHOT,
            model_provider="openai",
            model_tier=ModelTier.CREATIVE,
            model_resolved="openai/gpt-image-1",
            workspace_id="ws1",
        )
        assert manifest.model_tier == ModelTier.CREATIVE
        assert manifest.model_resolved == "openai/gpt-image-1"


class TestIsCreativeAvailable:
    def test_available(self) -> None:
        config = {"tiers": {"reasoning": "x", "creative": "y"}}
        assert is_creative_available(config) is True

    def test_not_available(self) -> None:
        config = {"tiers": {"reasoning": "x", "balanced": "y"}}
        assert is_creative_available(config) is False

    def test_none_config(self) -> None:
        assert is_creative_available(None) is False

    def test_empty_config(self) -> None:
        assert is_creative_available({}) is False


# ============================================================================
# #71: Image Generation Provider Adapters
# ============================================================================


class TestImageAdapterProtocol:
    def test_openai_adapter_is_image_adapter(self) -> None:
        from foxhound.adapters.image_adapter import ImageAdapter

        adapter = OpenAIImageAdapter()
        assert isinstance(adapter, ImageAdapter)

    def test_google_adapter_is_image_adapter(self) -> None:
        from foxhound.adapters.image_adapter import ImageAdapter

        adapter = GoogleImageAdapter()
        assert isinstance(adapter, ImageAdapter)


class TestOpenAIImageAdapter:
    def test_provider_name(self) -> None:
        adapter = OpenAIImageAdapter()
        assert adapter.provider_name == "openai"

    def test_authenticate_success(self) -> None:
        adapter = OpenAIImageAdapter()
        assert adapter.authenticate("sk-test-key") is True

    def test_authenticate_empty_key(self) -> None:
        adapter = OpenAIImageAdapter()
        assert adapter.authenticate("") is False

    def test_generate_unauthenticated(self) -> None:
        adapter = OpenAIImageAdapter()
        result = adapter.generate(ImageRequest(prompt="test"))
        assert not result.success
        assert result.error == "Not authenticated"

    def test_estimate_cost_gpt_image(self) -> None:
        adapter = OpenAIImageAdapter()
        cost = adapter.estimate_cost("gpt-image-1", "1024x1024")
        assert cost == 0.04

    def test_estimate_cost_unknown_model(self) -> None:
        adapter = OpenAIImageAdapter()
        cost = adapter.estimate_cost("unknown-model")
        assert cost == 0.04  # default fallback

    def test_custom_base_url(self) -> None:
        adapter = OpenAIImageAdapter()
        adapter.authenticate("key", base_url="http://localhost:8080/v1")
        assert adapter._base_url == "http://localhost:8080/v1"


class TestGoogleImageAdapter:
    def test_provider_name(self) -> None:
        adapter = GoogleImageAdapter()
        assert adapter.provider_name == "google"

    def test_authenticate_success(self) -> None:
        adapter = GoogleImageAdapter()
        assert adapter.authenticate("google-test-key") is True

    def test_authenticate_empty_key(self) -> None:
        adapter = GoogleImageAdapter()
        assert adapter.authenticate("") is False

    def test_generate_unauthenticated(self) -> None:
        adapter = GoogleImageAdapter()
        result = adapter.generate(ImageRequest(prompt="test"))
        assert not result.success
        assert result.error == "Not authenticated"

    def test_estimate_cost(self) -> None:
        adapter = GoogleImageAdapter()
        cost = adapter.estimate_cost(
            "gemini-2.0-flash-preview-image-generation"
        )
        assert cost == 0.02


class TestImageRequest:
    def test_defaults(self) -> None:
        req = ImageRequest(prompt="A blue sky")
        assert req.size == "1024x1024"
        assert req.quality == "standard"

    def test_custom_size(self) -> None:
        req = ImageRequest(prompt="test", size="1024x1536")
        assert req.size == "1024x1536"


class TestImageResult:
    def test_success(self) -> None:
        result = ImageResult(artifact_path=Path("/tmp/img.png"), cost=0.04)
        assert result.success is True

    def test_failure(self) -> None:
        result = ImageResult(error="API error")
        assert result.success is False

    def test_no_path_no_error(self) -> None:
        result = ImageResult()
        assert result.success is False


class TestSaveImage:
    def test_save_image_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data = b"\x89PNG\r\n\x1a\nfake_image_data"
            path = save_image_data(data, Path(tmpdir), "test.png")
            assert path.exists()
            assert path.read_bytes() == data

    def test_save_base64_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data = b"fake_image_bytes"
            b64 = base64.b64encode(data).decode()
            path = save_base64_image(b64, Path(tmpdir), "test.png")
            assert path.exists()
            assert path.read_bytes() == data

    def test_save_creates_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = Path(tmpdir) / "a" / "b" / "c"
            path = save_image_data(b"data", nested, "img.png")
            assert path.exists()


class TestImagePricing:
    def test_gpt_image_pricing(self) -> None:
        assert "gpt-image-1" in IMAGE_PRICING
        assert IMAGE_PRICING["gpt-image-1"]["1024x1024"] == 0.04

    def test_gemini_pricing(self) -> None:
        assert "gemini-2.0-flash-preview-image-generation" in IMAGE_PRICING

    def test_dalle3_pricing(self) -> None:
        assert "dall-e-3" in IMAGE_PRICING


class TestImageAdapterFactories:
    def test_openai_factory(self) -> None:
        assert "openai" in IMAGE_ADAPTER_FACTORIES
        adapter = IMAGE_ADAPTER_FACTORIES["openai"]()
        assert adapter.provider_name == "openai"

    def test_google_factory(self) -> None:
        assert "google" in IMAGE_ADAPTER_FACTORIES
        adapter = IMAGE_ADAPTER_FACTORIES["google"]()
        assert adapter.provider_name == "google"


# ============================================================================
# #72: Mockup-to-Code Pipeline
# ============================================================================


class TestImageStepConfig:
    def test_defaults(self) -> None:
        config = ImageStepConfig(name="generate_mockup")
        assert config.tier == "creative"
        assert config.step_type == "image_generation"
        assert config.size == "1024x1024"

    def test_custom_prompt(self) -> None:
        config = ImageStepConfig(
            name="custom",
            prompt_template="Create a {task_description} logo",
        )
        assert "{task_description}" in config.prompt_template


class TestRunImageStep:
    def test_skip_when_creative_unavailable(self) -> None:
        step = ImageStepConfig(name="test_step")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_image_step(
                step, "Build a dashboard", Path(tmpdir),
                creative_available=False,
            )
            assert result.skipped is True
            assert "not configured" in result.skip_reason

    def test_produces_artifact_when_available(self) -> None:
        step = ImageStepConfig(name="test_step", output="mockup")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_image_step(
                step, "Build a dashboard", Path(tmpdir),
                creative_available=True,
            )
            assert result.success is True
            assert result.artifact_path is not None
            assert "mockup" in str(result.artifact_path)

    def test_step_name_preserved(self) -> None:
        step = ImageStepConfig(name="my_step")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_image_step(
                step, "test", Path(tmpdir), creative_available=False,
            )
            assert result.step_name == "my_step"


class TestMockupToCode:
    def test_fallback_when_creative_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_mockup_to_code(
                "Build a todo app", Path(tmpdir),
                creative_available=False,
            )
            assert result.fallback_used is True
            assert result.mockup_result is not None
            assert result.mockup_result.skipped is True
            assert result.code_result is not None
            assert result.code_result.step_name == "build_frontend_from_description"

    def test_full_pipeline_when_creative_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_mockup_to_code(
                "Build a todo app", Path(tmpdir),
                creative_available=True,
            )
            assert result.fallback_used is False
            assert result.mockup_result is not None
            assert result.mockup_result.success is True
            assert result.code_result is not None
            assert result.code_result.step_name == "build_frontend_from_mockup"

    def test_cost_tracking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_mockup_to_code(
                "test", Path(tmpdir), creative_available=True,
            )
            assert isinstance(result.total_cost, float)


# ============================================================================
# #73: Visual Asset Generation
# ============================================================================


class TestVisualAssetConfig:
    def test_defaults(self) -> None:
        config = VisualAssetConfig()
        assert config.enabled is True
        assert "hero" in config.asset_types
        assert "og_image" in config.asset_types
        assert "favicon" in config.asset_types
        assert "readme_banner" in config.asset_types
        assert config.output_dir == "public/assets"

    def test_disabled(self) -> None:
        config = VisualAssetConfig(enabled=False)
        assert config.enabled is False

    def test_custom_asset_types(self) -> None:
        config = VisualAssetConfig(asset_types=["hero", "favicon"])
        assert len(config.asset_types) == 2


class TestAssetTypes:
    def test_all_types_defined(self) -> None:
        assert "hero" in ASSET_TYPES
        assert "og_image" in ASSET_TYPES
        assert "favicon" in ASSET_TYPES
        assert "readme_banner" in ASSET_TYPES

    def test_each_type_has_required_fields(self) -> None:
        for name, asset_def in ASSET_TYPES.items():
            assert "prompt_suffix" in asset_def, f"{name} missing prompt_suffix"
            assert "filename" in asset_def, f"{name} missing filename"
            assert "size" in asset_def, f"{name} missing size"


class TestGenerateVisualAssets:
    def test_skip_when_creative_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results = generate_visual_assets(
                "A CLI tool for developers", Path(tmpdir),
                creative_available=False,
            )
            assert results.generated == 0
            assert results.skipped == 4
            for r in results.results:
                assert r.skipped is True

    def test_generate_when_creative_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results = generate_visual_assets(
                "A CLI tool for developers", Path(tmpdir),
                creative_available=True,
            )
            assert results.generated == 4
            assert results.skipped == 0

    def test_custom_asset_types(self) -> None:
        config = VisualAssetConfig(asset_types=["hero", "favicon"])
        with tempfile.TemporaryDirectory() as tmpdir:
            results = generate_visual_assets(
                "test", Path(tmpdir), asset_config=config,
                creative_available=True,
            )
            assert len(results.results) == 2

    def test_disabled_config(self) -> None:
        config = VisualAssetConfig(enabled=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            results = generate_visual_assets(
                "test", Path(tmpdir), asset_config=config,
                creative_available=True,
            )
            assert len(results.results) == 0

    def test_cost_tracking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results = generate_visual_assets(
                "test", Path(tmpdir), creative_available=True,
            )
            assert isinstance(results.total_cost, float)

    def test_unknown_asset_type_skipped(self) -> None:
        config = VisualAssetConfig(asset_types=["hero", "nonexistent_type"])
        with tempfile.TemporaryDirectory() as tmpdir:
            results = generate_visual_assets(
                "test", Path(tmpdir), asset_config=config,
                creative_available=True,
            )
            assert len(results.results) == 1


class TestBuildAssetReferences:
    def test_builds_refs_from_results(self) -> None:
        results = VisualAssetResults(results=[
            CreativeStepResult(
                step_name="generate_hero",
                artifact_path=Path("public/assets/hero.png"),
            ),
            CreativeStepResult(
                step_name="generate_og_image",
                artifact_path=Path("public/assets/og-image.png"),
            ),
        ])
        refs = build_asset_references(results)
        assert refs["hero"] == "public/assets/hero.png"
        assert refs["og_image"] == "public/assets/og-image.png"

    def test_skips_failed_assets(self) -> None:
        results = VisualAssetResults(results=[
            CreativeStepResult(
                step_name="generate_hero",
                artifact_path=Path("public/assets/hero.png"),
            ),
            CreativeStepResult(
                step_name="generate_favicon",
                skipped=True,
                skip_reason="Creative tier not configured",
            ),
        ])
        refs = build_asset_references(results)
        assert "hero" in refs
        assert "favicon" not in refs

    def test_empty_results(self) -> None:
        results = VisualAssetResults()
        refs = build_asset_references(results)
        assert refs == {}
