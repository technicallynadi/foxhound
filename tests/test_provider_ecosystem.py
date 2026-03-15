"""Tests for Provider Ecosystem & Developer Experience (Milestone 8).

Covers: #77 Google/Deepseek adapters, #78 capability benchmark,
#79 interactive tier suggestion in foxhound init.
"""

from unittest.mock import MagicMock, patch

import pytest

from foxhound.adapters.benchmark import (
    BENCHMARK_PROMPT,
    REASONING_THRESHOLD,
    BenchmarkResult,
    BenchmarkSummary,
    format_benchmark_output,
    run_benchmark_for_tier,
    run_full_benchmark,
    score_response,
)
from foxhound.adapters.deepseek_adapter import (
    DEEPSEEK_PRICING,
    DeepseekAdapter,
)
from foxhound.adapters.google_adapter import (
    GOOGLE_PRICING,
    GoogleAdapter,
)
from foxhound.adapters.provider import ProviderAdapter, TokenUsage
from foxhound.adapters.router import ADAPTER_FACTORIES
from foxhound.cli.init_flow import (
    build_config_yaml,
    detect_providers,
    get_tier_suggestions,
    select_provider_non_interactive,
)
from foxhound.core.models import ModelTier

# ============================================================================
# #77: Google and Deepseek Provider Adapters
# ============================================================================


class TestGoogleAdapter:
    def test_provider_name(self) -> None:
        adapter = GoogleAdapter()
        assert adapter.provider_name == "google"

    def test_implements_protocol(self) -> None:
        adapter = GoogleAdapter()
        assert isinstance(adapter, ProviderAdapter)

    def test_authenticate_success(self) -> None:
        adapter = GoogleAdapter()
        assert adapter.authenticate("test-key") is True

    def test_authenticate_empty_key(self) -> None:
        adapter = GoogleAdapter()
        assert adapter.authenticate("") is False

    def test_complete_unauthenticated(self) -> None:
        adapter = GoogleAdapter()
        with pytest.raises(RuntimeError, match="not authenticated"):
            from foxhound.adapters.provider import ModelRequest
            adapter.complete(ModelRequest(
                messages=[{"role": "user", "content": "hi"}],
                model_id="gemini-2.5-flash",
            ))

    def test_check_model_unauthenticated(self) -> None:
        adapter = GoogleAdapter()
        assert adapter.check_model("gemini-2.5-flash") is False

    def test_estimate_cost_gemini_pro(self) -> None:
        adapter = GoogleAdapter()
        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        cost = adapter.estimate_cost(usage, "gemini-2.5-pro")
        expected = (1000 / 1_000_000) * 1.25 + (500 / 1_000_000) * 10.0
        assert abs(cost - expected) < 1e-10

    def test_estimate_cost_gemini_flash(self) -> None:
        adapter = GoogleAdapter()
        usage = TokenUsage(input_tokens=10000, output_tokens=5000)
        cost = adapter.estimate_cost(usage, "gemini-2.5-flash")
        expected = (10000 / 1_000_000) * 0.15 + (5000 / 1_000_000) * 0.60
        assert abs(cost - expected) < 1e-10

    def test_estimate_cost_unknown_model(self) -> None:
        adapter = GoogleAdapter()
        usage = TokenUsage(input_tokens=100)
        assert adapter.estimate_cost(usage, "unknown-model") == 0.0

    def test_pricing_table(self) -> None:
        assert "gemini-2.5-pro" in GOOGLE_PRICING
        assert "gemini-2.5-flash" in GOOGLE_PRICING
        for model, (inp, out) in GOOGLE_PRICING.items():
            assert inp > 0
            assert out > 0


class TestDeepseekAdapter:
    def test_provider_name(self) -> None:
        adapter = DeepseekAdapter()
        assert adapter.provider_name == "deepseek"

    def test_implements_protocol(self) -> None:
        adapter = DeepseekAdapter()
        assert isinstance(adapter, ProviderAdapter)

    def test_authenticate_success(self) -> None:
        adapter = DeepseekAdapter()
        assert adapter.authenticate("test-key") is True

    def test_authenticate_empty_key(self) -> None:
        adapter = DeepseekAdapter()
        assert adapter.authenticate("") is False

    def test_authenticate_custom_base_url(self) -> None:
        adapter = DeepseekAdapter()
        adapter.authenticate("key", base_url="http://custom:8080/v1")
        assert adapter._base_url == "http://custom:8080/v1"

    def test_complete_unauthenticated(self) -> None:
        adapter = DeepseekAdapter()
        with pytest.raises(RuntimeError, match="not authenticated"):
            from foxhound.adapters.provider import ModelRequest
            adapter.complete(ModelRequest(
                messages=[{"role": "user", "content": "hi"}],
                model_id="deepseek-chat",
            ))

    def test_check_model_unauthenticated(self) -> None:
        adapter = DeepseekAdapter()
        assert adapter.check_model("deepseek-chat") is False

    def test_estimate_cost_r1(self) -> None:
        adapter = DeepseekAdapter()
        usage = TokenUsage(input_tokens=1000, output_tokens=500)
        cost = adapter.estimate_cost(usage, "deepseek-r1")
        expected = (1000 / 1_000_000) * 0.55 + (500 / 1_000_000) * 2.19
        assert abs(cost - expected) < 1e-10

    def test_estimate_cost_v3(self) -> None:
        adapter = DeepseekAdapter()
        usage = TokenUsage(input_tokens=10000, output_tokens=5000)
        cost = adapter.estimate_cost(usage, "deepseek-v3")
        expected = (10000 / 1_000_000) * 0.27 + (5000 / 1_000_000) * 1.10
        assert abs(cost - expected) < 1e-10

    def test_estimate_cost_unknown_model(self) -> None:
        adapter = DeepseekAdapter()
        usage = TokenUsage(input_tokens=100)
        assert adapter.estimate_cost(usage, "unknown-model") == 0.0

    def test_pricing_table(self) -> None:
        assert "deepseek-r1" in DEEPSEEK_PRICING
        assert "deepseek-v3" in DEEPSEEK_PRICING
        assert "deepseek-chat" in DEEPSEEK_PRICING


class TestAdapterFactories:
    def test_google_registered(self) -> None:
        assert "google" in ADAPTER_FACTORIES
        adapter = ADAPTER_FACTORIES["google"]()
        assert adapter.provider_name == "google"

    def test_deepseek_registered(self) -> None:
        assert "deepseek" in ADAPTER_FACTORIES
        adapter = ADAPTER_FACTORIES["deepseek"]()
        assert adapter.provider_name == "deepseek"

    def test_all_known_providers_have_factories(self) -> None:
        from foxhound.adapters.registry import KNOWN_PROVIDERS
        for provider in KNOWN_PROVIDERS:
            assert provider in ADAPTER_FACTORIES, f"Missing factory for {provider}"


# ============================================================================
# #78: Capability Benchmark
# ============================================================================


class TestScoreResponse:
    def test_empty_response(self) -> None:
        assert score_response("") == 0
        assert score_response("   ") == 0

    def test_no_keywords(self) -> None:
        assert score_response("This function looks fine.") == 25

    def test_one_keyword(self) -> None:
        assert score_response("Could fail with zero input.") == 50

    def test_all_keywords(self) -> None:
        score = score_response(
            "The function has a division by zero bug when divisor is zero."
        )
        assert score == 100

    def test_partial_keywords(self) -> None:
        score = score_response("Division error when zero is passed.")
        assert 50 <= score <= 100

    def test_case_insensitive(self) -> None:
        score = score_response("DIVISION BY ZERO when DIVISOR is 0")
        assert score == 100


class TestRunBenchmarkForTier:
    def test_no_router_returns_error(self) -> None:
        result = run_benchmark_for_tier(ModelTier.BALANCED)
        assert result.error == "No model router available"
        assert result.score == 0

    def test_successful_benchmark(self) -> None:
        mock_response = MagicMock()
        mock_response.content = "Division by zero when divisor is 0"
        mock_response.model_id = "test-model"

        result = run_benchmark_for_tier(
            ModelTier.BALANCED,
            complete_fn=lambda tier, msgs: mock_response,
        )
        assert result.score == 100
        assert result.model_id == "test-model"
        assert result.error is None

    def test_reasoning_below_threshold(self) -> None:
        mock_response = MagicMock()
        mock_response.content = "Looks fine to me."
        mock_response.model_id = "weak-model"

        result = run_benchmark_for_tier(
            ModelTier.REASONING,
            complete_fn=lambda tier, msgs: mock_response,
        )
        assert result.below_threshold is True
        assert result.score < REASONING_THRESHOLD

    def test_exception_handling(self) -> None:
        def failing_fn(tier, msgs):
            raise ConnectionError("Network down")

        result = run_benchmark_for_tier(
            ModelTier.FAST,
            complete_fn=failing_fn,
        )
        assert result.error is not None
        assert "Network down" in result.error


class TestRunFullBenchmark:
    def test_all_tiers(self) -> None:
        mock_response = MagicMock()
        mock_response.content = "Division by zero when divisor is zero"
        mock_response.model_id = "test"

        summary = run_full_benchmark(
            [ModelTier.REASONING, ModelTier.BALANCED, ModelTier.FAST],
            complete_fn=lambda tier, msgs: mock_response,
        )
        assert len(summary.results) == 3
        assert all(r.score == 100 for r in summary.results)
        assert len(summary.warnings) == 0

    def test_reasoning_warning(self) -> None:
        mock_response = MagicMock()
        mock_response.content = "No issues."
        mock_response.model_id = "bad-model"

        summary = run_full_benchmark(
            [ModelTier.REASONING],
            complete_fn=lambda tier, msgs: mock_response,
        )
        assert len(summary.warnings) == 1
        assert "below threshold" in summary.warnings[0]

    def test_empty_tiers(self) -> None:
        summary = run_full_benchmark([])
        assert len(summary.results) == 0


class TestFormatBenchmarkOutput:
    def test_format_success(self) -> None:
        summary = BenchmarkSummary(results=[
            BenchmarkResult(tier="reasoning", model_id="m1", score=95),
            BenchmarkResult(tier="balanced", model_id="m2", score=80),
        ])
        output = format_benchmark_output(summary)
        assert "95/100" in output
        assert "80/100" in output

    def test_format_error(self) -> None:
        summary = BenchmarkSummary(results=[
            BenchmarkResult(tier="fast", error="timeout"),
        ])
        output = format_benchmark_output(summary)
        assert "error" in output
        assert "timeout" in output

    def test_format_warning(self) -> None:
        summary = BenchmarkSummary(
            results=[
                BenchmarkResult(
                    tier="reasoning", model_id="weak",
                    score=40, below_threshold=True,
                ),
            ],
            warnings=["Reasoning tier scored below threshold"],
        )
        output = format_benchmark_output(summary)
        assert "Warning" in output

    def test_benchmark_prompt_exists(self) -> None:
        assert len(BENCHMARK_PROMPT) > 50
        assert "divide_list" in BENCHMARK_PROMPT


# ============================================================================
# #79: Interactive Tier Suggestion in foxhound init
# ============================================================================


class TestDetectProviders:
    def test_no_keys_set(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            detected = detect_providers()
            assert detected == []

    def test_anthropic_detected(self) -> None:
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            detected = detect_providers()
            providers = [p for p, _ in detected]
            assert "anthropic" in providers

    def test_multiple_detected(self) -> None:
        with patch.dict("os.environ", {
            "ANTHROPIC_API_KEY": "sk-ant",
            "OPENAI_API_KEY": "sk-oai",
        }):
            detected = detect_providers()
            providers = [p for p, _ in detected]
            assert "anthropic" in providers
            assert "openai" in providers


class TestSelectProviderNonInteractive:
    def test_empty_detected(self) -> None:
        assert select_provider_non_interactive([]) is None

    def test_anthropic_preferred(self) -> None:
        detected = [
            ("openai", "OPENAI_API_KEY"),
            ("anthropic", "ANTHROPIC_API_KEY"),
        ]
        result = select_provider_non_interactive(detected)
        assert result is not None
        assert result[0] == "anthropic"

    def test_openai_second_priority(self) -> None:
        detected = [
            ("google", "GOOGLE_API_KEY"),
            ("openai", "OPENAI_API_KEY"),
        ]
        result = select_provider_non_interactive(detected)
        assert result is not None
        assert result[0] == "openai"

    def test_unknown_provider_fallback(self) -> None:
        detected = [("custom_provider", "CUSTOM_KEY")]
        result = select_provider_non_interactive(detected)
        assert result is not None
        assert result[0] == "custom_provider"


class TestGetTierSuggestions:
    def test_anthropic_suggestions(self) -> None:
        tiers = get_tier_suggestions("anthropic")
        assert "reasoning" in tiers
        assert "balanced" in tiers
        assert "fast" in tiers
        assert "claude-opus" in tiers["reasoning"]

    def test_openai_suggestions(self) -> None:
        tiers = get_tier_suggestions("openai")
        assert "reasoning" in tiers
        assert "gpt-4.1" in tiers["reasoning"]

    def test_unknown_provider(self) -> None:
        tiers = get_tier_suggestions("unknown_provider")
        assert tiers == {}


class TestBuildConfigYaml:
    def test_builds_valid_yaml(self) -> None:
        yaml = build_config_yaml(
            "anthropic",
            {"reasoning": "claude-opus-4.6", "balanced": "claude-sonnet-4.6",
             "fast": "claude-haiku-4.5"},
        )
        assert "provider: anthropic" in yaml
        assert "api_key_env: ANTHROPIC_API_KEY" in yaml
        assert "reasoning: claude-opus-4.6" in yaml
        assert "balanced: claude-sonnet-4.6" in yaml

    def test_custom_api_key_env(self) -> None:
        yaml = build_config_yaml(
            "openai", {"reasoning": "gpt-4.1"},
            api_key_env="MY_OPENAI_KEY",
        )
        assert "api_key_env: MY_OPENAI_KEY" in yaml

    def test_output_is_valid_yaml(self) -> None:
        import yaml as yaml_lib
        content = build_config_yaml(
            "anthropic",
            {"reasoning": "r", "balanced": "b", "fast": "f"},
        )
        data = yaml_lib.safe_load(content)
        assert data["models"]["provider"] == "anthropic"
        assert data["models"]["tiers"]["reasoning"] == "r"
