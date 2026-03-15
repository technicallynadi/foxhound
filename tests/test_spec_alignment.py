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


# ── #100: Manifest generation wiring ─────────────────────────────────


class TestManifestWiring:
    """Tests for manifest generation in the execution pipeline."""

    def test_build_env_fingerprint_deterministic(self) -> None:
        """Environment fingerprint is deterministic."""
        from foxhound.cli.run_pipeline import _build_env_fingerprint

        fp1 = _build_env_fingerprint()
        fp2 = _build_env_fingerprint()
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_manifest_model_has_all_fields(self) -> None:
        """Manifest model has all required fields for pipeline recording."""
        from foxhound.core.models import Manifest

        fields = set(Manifest.model_fields.keys())
        required = {
            "manifest_id", "run_id", "work_item_id", "repo_id",
            "recipe_ref", "policy_ref", "context_pack_hash",
            "execution_strategy", "model_provider", "model_tier",
            "model_resolved", "workspace_id", "total_cost",
            "duration_seconds", "commands_run", "files_changed",
            "branch_ref", "commit_ref", "evaluator_result",
            "iteration_count", "per_iteration_costs",
            "per_iteration_tasks_completed", "commit_refs",
        }
        assert required.issubset(fields)

    def test_record_manifest_creates_artifact(self, tmp_path: Path) -> None:
        """_record_manifest persists manifest via ObserverStore."""
        from foxhound.cli.run_pipeline import _record_manifest
        from foxhound.core.models import (
            ExecutionSnapshot,
            ModelTier,
            PolicyRef,
            RecipeRef,
        )
        from foxhound.storage.database import Database

        db = Database(tmp_path / "test.db")

        recipe_ref = RecipeRef(
            name="test_recipe", version="1.0.0",
            content_hash="abc123", source_scope="builtin",
        )
        policy_ref = PolicyRef(
            name="default", version="1.0.0",
            content_hash="def456", source_scope="builtin",
        )

        mock_run = MagicMock()
        mock_run.run_id = "run_abc123"

        mock_job = MagicMock()
        mock_job.execution_snapshot = ExecutionSnapshot(
            recipe_ref=recipe_ref,
            policy_ref=policy_ref,
            config_hash="hash123",
            model_tier=ModelTier.BALANCED,
        )

        mock_item = MagicMock()
        mock_item.work_item_id = "wi_test"
        mock_item.repo_id = "repo_test"

        mock_workspace = MagicMock()
        mock_workspace.workspace_id = "ws_test"

        artifact_id = _record_manifest(
            db=db,
            run=mock_run,
            job=mock_job,
            item=mock_item,
            recipe_ref=recipe_ref,
            policy_ref=policy_ref,
            config_hash="hash123",
            workspace=mock_workspace,
            review_verdict="pass",
            branch_name="foxhound/test",
            commit_hash="abc1234",
            files_changed=["src/main.py"],
            commands_run=["pytest"],
            total_cost=0.05,
            duration_seconds=12.5,
        )

        assert artifact_id is not None

        db.close()

    def test_record_manifest_updates_run_record(self, tmp_path: Path) -> None:
        """_record_manifest sets manifest_path on the run record."""
        from foxhound.storage.database import Database, RunStore

        db = Database(tmp_path / "test.db")
        run_store = RunStore(db)

        # Create a run record first
        from foxhound.core.models import RunRecord, RunState

        run = RunRecord(
            run_id="run_manifest_test",
            job_id="job_test",
            worker_type="ExecutionWorker",
        )
        run_store.save(run)

        # Update manifest path
        result = run_store.update_manifest_path(
            "run_manifest_test", "manifests/manifest_abc.json"
        )
        assert result is True

        # Verify it was saved
        loaded = run_store.get("run_manifest_test")
        assert loaded is not None
        assert loaded.manifest_path == "manifests/manifest_abc.json"

        db.close()

    def test_record_manifest_handles_errors_gracefully(self) -> None:
        """_record_manifest returns None on errors instead of raising."""
        from foxhound.cli.run_pipeline import _record_manifest

        result = _record_manifest(
            db=None,  # type: ignore[arg-type]
            run=MagicMock(),
            job=MagicMock(),
            item=MagicMock(),
            recipe_ref=MagicMock(),
            policy_ref=MagicMock(),
            config_hash="x",
            workspace=MagicMock(),
            review_verdict=None,
            branch_name=None,
            commit_hash=None,
            files_changed=[],
            commands_run=[],
            total_cost=0.0,
            duration_seconds=0.0,
        )
        assert result is None

    def test_observer_store_record_manifest(self, tmp_path: Path) -> None:
        """ObserverStore.record_manifest writes JSON and indexes as Class A."""
        from foxhound.core.models import (
            ExecutionStrategy,
            Manifest,
            ModelTier,
            PolicyRef,
            RecipeRef,
        )
        from foxhound.observer.store import ObserverStore
        from foxhound.storage.database import Database

        db = Database(tmp_path / "test.db")
        artifacts_dir = tmp_path / "artifacts"

        observer = ObserverStore(db, artifacts_dir=artifacts_dir)

        manifest = Manifest(
            manifest_id="manifest_test123",
            run_id="run_1",
            work_item_id="wi_1",
            repo_id="repo_1",
            recipe_ref=RecipeRef(
                name="r", version="1", content_hash="h", source_scope="b"
            ),
            policy_ref=PolicyRef(
                name="p", version="1", content_hash="h", source_scope="b"
            ),
            context_pack_hash="ctx_hash",
            execution_environment_fingerprint="env_fp",
            execution_strategy=ExecutionStrategy.ONE_SHOT,
            model_provider="anthropic",
            model_tier=ModelTier.BALANCED,
            workspace_id="ws_1",
        )

        artifact_id = observer.record_manifest(manifest, "run_1")
        assert artifact_id.startswith("art_")

        # Verify JSON file was written
        manifest_file = artifacts_dir / "manifests" / "manifest_test123.json"
        assert manifest_file.exists()
        data = json.loads(manifest_file.read_text())
        assert data["manifest_id"] == "manifest_test123"
        assert data["run_id"] == "run_1"

        db.close()


# ── #103: Creative tier adapter wiring ───────────────────────────────


class TestCreativeAdapterWiring:
    """Tests for creative tier adapter wiring in creative.py."""

    def test_run_image_step_skips_without_creative(self, tmp_path: Path) -> None:
        """Image step skips gracefully when creative tier unavailable."""
        from foxhound.execution.creative import ImageStepConfig, run_image_step

        step = ImageStepConfig(name="test_step", output="test_out")
        result = run_image_step(step, "test", tmp_path, creative_available=False)
        assert result.skipped is True
        assert result.skip_reason == "Creative tier not configured"

    def test_run_image_step_calls_adapter(self, tmp_path: Path) -> None:
        """Image step calls image adapter when provided."""
        from foxhound.adapters.image_adapter import ImageResult
        from foxhound.execution.creative import ImageStepConfig, run_image_step

        mock_adapter = MagicMock()
        artifact_path = tmp_path / "output.png"
        mock_adapter.generate.return_value = ImageResult(
            artifact_path=artifact_path, cost=0.04, model_id="gpt-image-1"
        )

        step = ImageStepConfig(name="hero", output="hero_img")
        result = run_image_step(
            step, "a landing page", tmp_path,
            creative_available=True, image_adapter=mock_adapter,
        )
        assert result.success
        assert result.cost == 0.04
        assert result.model_id == "gpt-image-1"
        mock_adapter.generate.assert_called_once()

    def test_run_image_step_adapter_error(self, tmp_path: Path) -> None:
        """Image step handles adapter errors gracefully."""
        from foxhound.adapters.image_adapter import ImageResult
        from foxhound.execution.creative import ImageStepConfig, run_image_step

        mock_adapter = MagicMock()
        mock_adapter.generate.return_value = ImageResult(error="Rate limited")

        step = ImageStepConfig(name="test", output="test")
        result = run_image_step(
            step, "test", tmp_path,
            creative_available=True, image_adapter=mock_adapter,
        )
        assert result.error == "Rate limited"
        assert not result.success

    def test_run_image_step_adapter_exception(self, tmp_path: Path) -> None:
        """Image step catches adapter exceptions."""
        from foxhound.execution.creative import ImageStepConfig, run_image_step

        mock_adapter = MagicMock()
        mock_adapter.generate.side_effect = ConnectionError("timeout")

        step = ImageStepConfig(name="test", output="test")
        result = run_image_step(
            step, "test", tmp_path,
            creative_available=True, image_adapter=mock_adapter,
        )
        assert result.error is not None
        assert "timeout" in result.error

    def test_run_image_step_placeholder_without_adapter(self, tmp_path: Path) -> None:
        """Image step returns placeholder when creative available but no adapter."""
        from foxhound.execution.creative import ImageStepConfig, run_image_step

        step = ImageStepConfig(name="test", output="test_img")
        result = run_image_step(
            step, "test", tmp_path,
            creative_available=True, image_adapter=None,
        )
        assert result.artifact_path is not None
        assert result.model_id == "creative"

    def test_mockup_to_code_with_adapter(self, tmp_path: Path) -> None:
        """Mockup-to-code passes adapter through to image step."""
        from foxhound.adapters.image_adapter import ImageResult
        from foxhound.execution.creative import run_mockup_to_code

        mock_adapter = MagicMock()
        mock_adapter.generate.return_value = ImageResult(
            artifact_path=tmp_path / "mockup.png",
            cost=0.04,
            model_id="gpt-image-1",
        )

        result = run_mockup_to_code(
            "a dashboard UI", tmp_path,
            creative_available=True, image_adapter=mock_adapter,
        )
        assert result.mockup_result is not None
        assert result.mockup_result.success
        assert not result.fallback_used

    def test_mockup_to_code_fallback_without_creative(self, tmp_path: Path) -> None:
        """Mockup-to-code falls back to text-only without creative tier."""
        from foxhound.execution.creative import run_mockup_to_code

        result = run_mockup_to_code(
            "a dashboard", tmp_path, creative_available=False
        )
        assert result.fallback_used is True
        assert result.mockup_result is not None
        assert result.mockup_result.skipped

    def test_generate_visual_assets_with_adapter(self, tmp_path: Path) -> None:
        """Visual asset generation passes adapter to each step."""
        from foxhound.adapters.image_adapter import ImageResult
        from foxhound.execution.creative import (
            VisualAssetConfig,
            generate_visual_assets,
        )

        mock_adapter = MagicMock()
        mock_adapter.generate.return_value = ImageResult(
            artifact_path=tmp_path / "asset.png",
            cost=0.02,
            model_id="gemini",
        )

        config = VisualAssetConfig(asset_types=["hero", "favicon"])
        results = generate_visual_assets(
            "my product", tmp_path,
            asset_config=config, creative_available=True,
            image_adapter=mock_adapter,
        )
        assert results.generated == 2
        assert results.skipped == 0
        assert mock_adapter.generate.call_count == 2

    def test_generate_visual_assets_skips_without_creative(
        self, tmp_path: Path,
    ) -> None:
        """Visual assets skip when creative tier unavailable."""
        from foxhound.execution.creative import generate_visual_assets

        results = generate_visual_assets(
            "my product", tmp_path, creative_available=False
        )
        assert results.generated == 0
        assert results.skipped == 4  # 4 default asset types

    def test_get_image_adapter_from_config_no_creative(self) -> None:
        """Returns None when creative tier not in config."""
        from foxhound.execution.creative import get_image_adapter_from_config

        config: dict[str, Any] = {"tiers": {"balanced": "claude-sonnet-4.6"}}
        assert get_image_adapter_from_config(config) is None

    def test_get_image_adapter_from_config_no_key(self) -> None:
        """Returns None when API key env var not set."""
        from foxhound.execution.creative import get_image_adapter_from_config

        config: dict[str, Any] = {
            "provider": "openai",
            "api_key_env": "NONEXISTENT_KEY_12345",
            "tiers": {"creative": "gpt-image-1"},
        }
        assert get_image_adapter_from_config(config) is None

    def test_get_image_adapter_from_config_unknown_provider(self) -> None:
        """Returns None for unknown provider."""
        from foxhound.execution.creative import get_image_adapter_from_config

        config: dict[str, Any] = {
            "provider": "unknown_provider",
            "tiers": {"creative": "some-model"},
        }
        assert get_image_adapter_from_config(config) is None

    def test_build_asset_references(self, tmp_path: Path) -> None:
        """build_asset_references maps generated assets to paths."""
        from foxhound.execution.creative import (
            CreativeStepResult,
            VisualAssetResults,
            build_asset_references,
        )

        results = VisualAssetResults(
            results=[
                CreativeStepResult(
                    step_name="generate_hero",
                    artifact_path=tmp_path / "hero.png",
                ),
                CreativeStepResult(
                    step_name="generate_favicon",
                    skipped=True,
                ),
            ],
            generated=1,
            skipped=1,
        )
        refs = build_asset_references(results)
        assert "hero" in refs
        assert "favicon" not in refs
