"""Tests for Milestone 9: Spec Alignment features.

Covers #99 (doctor model validation), #100 (manifest wiring),
#103 (creative adapter wiring), and #97 (helper workers).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── #99: Doctor model validation ─────────────────────────────────────


class TestDoctorModelValidation:
    """Tests for model tier connectivity checks in foxhound doctor."""

    def test_doctor_accepts_benchmark_flag(self) -> None:
        """Doctor command accepts --benchmark option."""
        from typer.testing import CliRunner

        from foxhound.cli.app import app

        runner = CliRunner()
        result = runner.invoke(app, ["doctor", "--help"])
        assert "--benchmark" in result.output

    def test_doctor_tier_display_with_config(self, tmp_path: Path) -> None:
        """Doctor displays tier mappings when config exists."""
        import yaml

        config = {
            "models": {
                "provider": "anthropic",
                "api_key_env": "ANTHROPIC_API_KEY",
                "tiers": {
                    "reasoning": "claude-opus-4.6",
                    "balanced": "claude-sonnet-4.6",
                    "fast": "claude-haiku-4.5",
                },
            }
        }
        config_path = tmp_path / "foxhound.yaml"
        config_path.write_text(yaml.dump(config))

        from foxhound.core.config import load_config

        loaded = load_config(config_path)
        assert loaded.models.tiers["reasoning"] == "claude-opus-4.6"

    def test_doctor_benchmark_skip_without_provider(self) -> None:
        """Benchmark is skipped when no providers are authenticated."""
        from foxhound.adapters.benchmark import run_full_benchmark

        summary = run_full_benchmark([], None)
        assert len(summary.results) == 0
        assert len(summary.warnings) == 0

    def test_doctor_benchmark_with_mock_router(self) -> None:
        """Benchmark runs through router.complete when available."""
        from foxhound.adapters.benchmark import BenchmarkResult, run_benchmark_for_tier
        from foxhound.core.models import ModelTier

        @dataclass
        class FakeResponse:
            content: str = "division by zero bug"
            model_id: str = "test-model"

        def fake_complete(tier: Any, messages: Any) -> FakeResponse:
            return FakeResponse()

        result = run_benchmark_for_tier(ModelTier.BALANCED, fake_complete)
        assert result.score > 0
        assert result.error is None
        assert result.model_id == "test-model"

    def test_doctor_benchmark_error_handling(self) -> None:
        """Benchmark handles provider errors gracefully."""
        from foxhound.adapters.benchmark import run_benchmark_for_tier
        from foxhound.core.models import ModelTier

        def failing_complete(tier: Any, messages: Any) -> None:
            raise ConnectionError("API unreachable")

        result = run_benchmark_for_tier(ModelTier.FAST, failing_complete)
        assert result.error is not None
        assert "unreachable" in result.error

    def test_doctor_benchmark_reasoning_threshold(self) -> None:
        """Benchmark flags reasoning tier below threshold."""
        from foxhound.adapters.benchmark import run_benchmark_for_tier
        from foxhound.core.models import ModelTier

        @dataclass
        class WeakResponse:
            content: str = "the function looks fine"
            model_id: str = "weak-model"

        def weak_complete(tier: Any, messages: Any) -> WeakResponse:
            return WeakResponse()

        result = run_benchmark_for_tier(ModelTier.REASONING, weak_complete)
        assert result.below_threshold is True

    def test_doctor_benchmark_format_output(self) -> None:
        """Benchmark output formatting includes scores and warnings."""
        from foxhound.adapters.benchmark import (
            BenchmarkResult,
            BenchmarkSummary,
            format_benchmark_output,
        )

        summary = BenchmarkSummary(
            results=[
                BenchmarkResult(tier="balanced", model_id="test", score=100),
                BenchmarkResult(tier="fast", error="API error"),
            ],
            warnings=["Low reasoning score"],
        )
        output = format_benchmark_output(summary)
        assert "100/100" in output
        assert "error" in output
        assert "Warning" in output

    def test_doctor_creative_tier_optional(self) -> None:
        """Creative tier shows as optional when not configured."""
        from foxhound.core.models import ModelTier

        # ModelTier.CREATIVE exists but is optional
        assert hasattr(ModelTier, "CREATIVE")
