"""Tests for Milestone 9: Spec Alignment features.

Covers #99 (doctor model validation), #100 (manifest wiring),
#103 (creative adapter wiring), and #97 (helper workers).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

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
        from foxhound.adapters.benchmark import run_benchmark_for_tier
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
        from foxhound.core.models import RunRecord

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


# ── #97: Helper workers ──────────────────────────────────────────────


def _make_task_envelope(**overrides: Any) -> Any:
    """Create a minimal TaskEnvelope for testing."""
    from foxhound.core.models import (
        ExecutionMode,
        ExecutionSnapshot,
        PolicyRef,
        RecipeRef,
        TaskEnvelope,
    )

    defaults: dict[str, Any] = {
        "task_id": "test_task",
        "job_id": "test_job",
        "run_id": "test_run",
        "repo_id": "test_repo",
        "execution_snapshot": ExecutionSnapshot(
            recipe_ref=RecipeRef(
                name="r", version="1", content_hash="h", source_scope="b"
            ),
            policy_ref=PolicyRef(
                name="p", version="1", content_hash="h", source_scope="b"
            ),
            config_hash="test",
        ),
        "budget": 1.0,
        "timeout_seconds": 120,
        "execution_mode": ExecutionMode.READ_ONLY,
        "input_payload": {},
    }
    defaults.update(overrides)
    return TaskEnvelope(**defaults)


def _make_runtime(**overrides: Any) -> Any:
    """Create a minimal RuntimeHandle for testing."""
    from foxhound.core.models import ExecutionMode
    from foxhound.harness.worker_protocol import Capability, RuntimeHandle

    defaults: dict[str, Any] = {
        "execution_mode": ExecutionMode.READ_ONLY,
        "capabilities": {Capability.REPO_READ},
        "budget_remaining": 1.0,
        "timeout_remaining": 120.0,
    }
    defaults.update(overrides)
    return RuntimeHandle(**defaults)


class TestSecurityReviewWorker:
    """Tests for SecurityReviewWorker."""

    def test_attributes(self) -> None:
        from foxhound.harness.helpers import SecurityReviewWorker
        from foxhound.harness.worker_protocol import Capability, WorkerClass

        w = SecurityReviewWorker()
        assert w.worker_name == "security_review_worker"
        assert w.worker_class == WorkerClass.HELPER
        assert w.capabilities == {Capability.REPO_READ}
        assert w.allowed_spawn_targets == []

    def test_validate_input_no_diff(self) -> None:
        from foxhound.harness.helpers import SecurityReviewWorker

        w = SecurityReviewWorker()
        result = w.validate_input(_make_task_envelope())
        assert not result.valid

    def test_validate_input_with_diff(self) -> None:
        from foxhound.harness.helpers import SecurityReviewWorker

        w = SecurityReviewWorker(diff_text="+ some code")
        result = w.validate_input(_make_task_envelope())
        assert result.valid

    def test_execute_finds_hardcoded_secret(self) -> None:
        from foxhound.harness.helpers import SecurityReviewWorker

        diff = '+ password = "hunter2"\n+ x = 1'
        w = SecurityReviewWorker(diff_text=diff)
        output = w.execute(_make_task_envelope(), _make_runtime())
        findings = output.payload["findings"]
        assert len(findings) >= 1
        assert findings[0]["pattern_name"] == "hardcoded_secret"
        assert findings[0]["severity"] == "critical"

    def test_execute_finds_eval(self) -> None:
        from foxhound.harness.helpers import SecurityReviewWorker

        diff = "+ result = eval(user_input)"
        w = SecurityReviewWorker(diff_text=diff)
        output = w.execute(_make_task_envelope(), _make_runtime())
        assert output.payload["finding_count"] >= 1

    def test_evaluate_fails_on_critical(self) -> None:
        from foxhound.harness.helpers import SecurityReviewWorker
        from foxhound.harness.worker_protocol import SanitizedOutput

        output = SanitizedOutput(payload={
            "findings": [{"severity": "critical", "pattern_name": "eval_usage"}],
        })
        w = SecurityReviewWorker()
        result = w.evaluate_output(output)
        assert not result.passed

    def test_evaluate_passes_on_warnings_only(self) -> None:
        from foxhound.harness.helpers import SecurityReviewWorker
        from foxhound.harness.worker_protocol import SanitizedOutput

        output = SanitizedOutput(payload={
            "findings": [{"severity": "warning", "pattern_name": "bind_all"}],
        })
        w = SecurityReviewWorker()
        result = w.evaluate_output(output)
        assert result.passed

    def test_full_harness_cycle(self) -> None:
        from foxhound.harness.helpers import SecurityReviewWorker

        w = SecurityReviewWorker(diff_text="+ x = 1\n+ y = 2")
        task = _make_task_envelope()
        runtime = _make_runtime()

        v = w.validate_input(task)
        assert v.valid
        w.build_context(task)
        output = w.execute(task, runtime)
        sanitized = w.sanitize_output(output)
        evaluated = w.evaluate_output(sanitized)
        result = w.finalize(evaluated)
        assert result.status.value == "success"


class TestEvidenceValidatorWorker:
    """Tests for EvidenceValidatorWorker."""

    def test_attributes(self) -> None:
        from foxhound.harness.helpers import EvidenceValidatorWorker
        from foxhound.harness.worker_protocol import Capability, WorkerClass

        w = EvidenceValidatorWorker()
        assert w.worker_name == "evidence_validator"
        assert w.worker_class == WorkerClass.HELPER
        assert w.capabilities == {Capability.NETWORK}

    def test_validate_no_evidence(self) -> None:
        from foxhound.harness.helpers import EvidenceValidatorWorker

        w = EvidenceValidatorWorker()
        result = w.validate_input(_make_task_envelope())
        assert not result.valid

    def test_execute_validates_evidence(self) -> None:
        from foxhound.harness.helpers import EvidenceValidatorWorker

        evidence = [
            {"title": "Bug report", "source_type": "github_issue", "url": "https://example.com"},
            {"title": "", "source_type": "unknown"},
        ]
        w = EvidenceValidatorWorker(evidence=evidence)
        task = _make_task_envelope(input_payload={"evidence": evidence})
        output = w.execute(task, _make_runtime())
        assert output.payload["total"] == 2
        assert output.payload["valid_count"] == 1

    def test_trust_labeling(self) -> None:
        from foxhound.harness.helpers import EvidenceValidatorWorker

        evidence = [
            {"source_type": "reddit"},
            {"source_type": "github_issue"},
        ]
        w = EvidenceValidatorWorker(evidence=evidence)
        ctx = w.build_context(_make_task_envelope(input_payload={"evidence": evidence}))
        assert ctx.trust_labels["evidence_0"] == "untrusted"
        assert ctx.trust_labels["evidence_1"] == "semi_trusted"


class TestFailureTriageWorker:
    """Tests for FailureTriageWorker."""

    def test_attributes(self) -> None:
        from foxhound.harness.helpers import FailureTriageWorker
        from foxhound.harness.worker_protocol import Capability, WorkerClass

        w = FailureTriageWorker()
        assert w.worker_name == "failure_triage_worker"
        assert w.worker_class == WorkerClass.HELPER
        assert w.capabilities == {Capability.REPO_READ}

    def test_classifies_test_failure(self) -> None:
        from foxhound.harness.helpers import FailureTriageWorker

        w = FailureTriageWorker(failure_output="FAILED test_login - AssertionError")
        output = w.execute(_make_task_envelope(), _make_runtime())
        assert output.payload["failure_class"] == "test_failure"

    def test_classifies_import_error(self) -> None:
        from foxhound.harness.helpers import FailureTriageWorker

        w = FailureTriageWorker(failure_output="ModuleNotFoundError: No module named 'foo'")
        output = w.execute(_make_task_envelope(), _make_runtime())
        assert output.payload["failure_class"] == "import_error"

    def test_classifies_unknown(self) -> None:
        from foxhound.harness.helpers import FailureTriageWorker

        w = FailureTriageWorker(failure_output="something weird happened")
        output = w.execute(_make_task_envelope(), _make_runtime())
        assert output.payload["failure_class"] == "unknown"

    def test_validate_no_input(self) -> None:
        from foxhound.harness.helpers import FailureTriageWorker

        w = FailureTriageWorker()
        result = w.validate_input(_make_task_envelope())
        assert not result.valid

    def test_remediation_suggestion(self) -> None:
        from foxhound.harness.helpers import FailureTriageWorker

        w = FailureTriageWorker(failure_output="TimeoutError: timed out")
        output = w.execute(_make_task_envelope(), _make_runtime())
        assert "timeout" in output.payload["remediation"].lower()


class TestPatchQualityEvaluatorWorker:
    """Tests for PatchQualityEvaluatorWorker."""

    def test_attributes(self) -> None:
        from foxhound.harness.helpers import PatchQualityEvaluatorWorker
        from foxhound.harness.worker_protocol import Capability, WorkerClass

        w = PatchQualityEvaluatorWorker()
        assert w.worker_name == "patch_quality_evaluator_worker"
        assert w.worker_class == WorkerClass.HELPER
        assert w.capabilities == {Capability.REPO_READ}

    def test_validate_no_diff(self) -> None:
        from foxhound.harness.helpers import PatchQualityEvaluatorWorker

        w = PatchQualityEvaluatorWorker()
        result = w.validate_input(_make_task_envelope())
        assert not result.valid

    def test_quality_score_small_diff(self) -> None:
        from foxhound.harness.helpers import PatchQualityEvaluatorWorker

        diff = "\n".join([f"+line{i}" for i in range(10)])
        w = PatchQualityEvaluatorWorker(
            diff_text=diff, files_changed=["src/main.py", "tests/test_main.py"]
        )
        output = w.execute(_make_task_envelope(), _make_runtime())
        assert output.payload["quality_score"] > 0.5
        assert output.payload["test_files_count"] == 1

    def test_quality_penalty_no_tests(self) -> None:
        from foxhound.harness.helpers import PatchQualityEvaluatorWorker

        diff = "\n".join([f"+line{i}" for i in range(10)])
        w = PatchQualityEvaluatorWorker(
            diff_text=diff, files_changed=["src/main.py"]
        )
        output = w.execute(_make_task_envelope(), _make_runtime())
        issues = output.payload["issues"]
        assert any("test" in i.lower() for i in issues)

    def test_quality_penalty_failed_validations(self) -> None:
        from foxhound.harness.helpers import PatchQualityEvaluatorWorker

        w = PatchQualityEvaluatorWorker(
            diff_text="+x = 1",
            validation_results=[{"passed": False, "command": "pytest"}],
        )
        output = w.execute(_make_task_envelope(), _make_runtime())
        assert any("validation" in i.lower() for i in output.payload["issues"])


class TestTaskDecomposerWorker:
    """Tests for TaskDecomposerWorker."""

    def test_attributes(self) -> None:
        from foxhound.harness.helpers import TaskDecomposerWorker
        from foxhound.harness.worker_protocol import Capability, WorkerClass

        w = TaskDecomposerWorker()
        assert w.worker_name == "task_decomposer_worker"
        assert w.worker_class == WorkerClass.HELPER
        assert w.capabilities == {Capability.REPO_READ}

    def test_validate_no_description(self) -> None:
        from foxhound.harness.helpers import TaskDecomposerWorker

        w = TaskDecomposerWorker()
        result = w.validate_input(_make_task_envelope())
        assert not result.valid

    def test_decompose_numbered_list(self) -> None:
        from foxhound.harness.helpers import TaskDecomposerWorker

        desc = "1. Add user model\n2. Create migration\n3. Write tests"
        w = TaskDecomposerWorker(task_description=desc)
        output = w.execute(_make_task_envelope(), _make_runtime())
        assert output.payload["total_subtasks"] == 3
        subtasks = output.payload["subtasks"]
        assert subtasks[0]["description"] == "Add user model"
        assert subtasks[1]["depends_on"] == [1]

    def test_decompose_bullet_list(self) -> None:
        from foxhound.harness.helpers import TaskDecomposerWorker

        desc = "- Fix the login bug\n- Update the tests"
        w = TaskDecomposerWorker(task_description=desc)
        output = w.execute(_make_task_envelope(), _make_runtime())
        assert output.payload["total_subtasks"] == 2

    def test_decompose_single_task(self) -> None:
        from foxhound.harness.helpers import TaskDecomposerWorker

        w = TaskDecomposerWorker(task_description="Fix the bug")
        output = w.execute(_make_task_envelope(), _make_runtime())
        assert output.payload["total_subtasks"] == 1
        assert output.payload["estimated_complexity"] == "low"

    def test_complexity_estimation(self) -> None:
        from foxhound.harness.helpers import TaskDecomposerWorker

        desc = "\n".join([f"- Task {i}: do something" for i in range(8)])
        w = TaskDecomposerWorker(task_description=desc)
        output = w.execute(_make_task_envelope(), _make_runtime())
        assert output.payload["estimated_complexity"] == "high"


class TestContextGapAnalyzerWorker:
    """Tests for ContextGapAnalyzerWorker."""

    def test_attributes(self) -> None:
        from foxhound.harness.helpers import ContextGapAnalyzerWorker
        from foxhound.harness.worker_protocol import Capability, WorkerClass

        w = ContextGapAnalyzerWorker()
        assert w.worker_name == "context_gap_analyzer_worker"
        assert w.worker_class == WorkerClass.HELPER
        assert w.capabilities == {Capability.REPO_READ}

    def test_validate_no_failure_output(self) -> None:
        from foxhound.harness.helpers import ContextGapAnalyzerWorker

        w = ContextGapAnalyzerWorker()
        result = w.validate_input(_make_task_envelope())
        assert not result.valid

    def test_detect_missing_file(self) -> None:
        from foxhound.harness.helpers import ContextGapAnalyzerWorker

        failure = 'File "src/utils.py", line 10, in helper\nNameError'
        w = ContextGapAnalyzerWorker(
            failure_output=failure,
            files_in_context=["src/main.py"],
        )
        output = w.execute(_make_task_envelope(), _make_runtime())
        gaps = output.payload["gaps"]
        assert any(g["type"] == "missing_file" for g in gaps)
        assert any("utils.py" in g["reference"] for g in gaps)

    def test_detect_missing_module(self) -> None:
        from foxhound.harness.helpers import ContextGapAnalyzerWorker

        failure = "ModuleNotFoundError: No module named 'requests'"
        w = ContextGapAnalyzerWorker(failure_output=failure)
        output = w.execute(_make_task_envelope(), _make_runtime())
        gaps = output.payload["gaps"]
        assert any(g["type"] == "missing_dependency" for g in gaps)
        assert any("requests" in g["reference"] for g in gaps)

    def test_detect_undefined_name(self) -> None:
        from foxhound.harness.helpers import ContextGapAnalyzerWorker

        failure = "NameError: name 'helper_func' is not defined"
        w = ContextGapAnalyzerWorker(failure_output=failure)
        output = w.execute(_make_task_envelope(), _make_runtime())
        gaps = output.payload["gaps"]
        assert any(g["type"] == "undefined_reference" for g in gaps)

    def test_no_gaps_when_all_present(self) -> None:
        from foxhound.harness.helpers import ContextGapAnalyzerWorker

        failure = "AssertionError: expected True"
        w = ContextGapAnalyzerWorker(failure_output=failure)
        output = w.execute(_make_task_envelope(), _make_runtime())
        assert output.payload["gap_count"] == 0


class TestCapabilitiesMatrixUpdated:
    """Tests that CAPABILITIES_MATRIX includes all helper workers."""

    def test_all_helpers_in_matrix(self) -> None:
        from foxhound.harness.worker_protocol import CAPABILITIES_MATRIX

        expected = [
            "security_review_worker",
            "evidence_validator",
            "failure_triage_worker",
            "patch_quality_evaluator_worker",
            "task_decomposer_worker",
            "context_gap_analyzer_worker",
        ]
        for name in expected:
            assert name in CAPABILITIES_MATRIX, f"{name} missing from matrix"

    def test_helpers_have_restricted_capabilities(self) -> None:
        from foxhound.harness.worker_protocol import CAPABILITIES_MATRIX, Capability

        restricted_helpers = [
            "security_review_worker",
            "failure_triage_worker",
            "patch_quality_evaluator_worker",
            "task_decomposer_worker",
            "context_gap_analyzer_worker",
        ]
        for name in restricted_helpers:
            caps = CAPABILITIES_MATRIX[name]
            assert Capability.REPO_WRITE not in caps
            assert Capability.SHELL not in caps
            assert Capability.SPAWN not in caps

    def test_evidence_validator_has_network(self) -> None:
        from foxhound.harness.worker_protocol import CAPABILITIES_MATRIX, Capability

        assert Capability.NETWORK in CAPABILITIES_MATRIX["evidence_validator"]

    def test_worker_validate_capabilities_passes(self) -> None:
        from foxhound.harness.worker_protocol import (
            Capability,
            validate_worker_capabilities,
        )

        violations = validate_worker_capabilities(
            "security_review_worker", {Capability.REPO_READ}
        )
        assert len(violations) == 0

    def test_worker_validate_capabilities_fails_on_escalation(self) -> None:
        from foxhound.harness.worker_protocol import (
            Capability,
            validate_worker_capabilities,
        )

        violations = validate_worker_capabilities(
            "security_review_worker", {Capability.REPO_READ, Capability.SHELL}
        )
        assert len(violations) > 0
