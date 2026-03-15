"""Integration wiring tests for spec alignment features.

Covers cross-module wiring that no single-feature test file owns:
doctor CLI flags, manifest pipeline, creative adapter fallback, TUI imports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


# ── Doctor CLI wiring ────────────────────────────────────────────────


class TestDoctorCLI:
    """Doctor command integration: benchmark flag and config display."""

    def test_doctor_accepts_benchmark_flag(self) -> None:
        from typer.testing import CliRunner

        from foxhound.cli.app import app

        runner = CliRunner()
        result = runner.invoke(app, ["doctor", "--help"])
        assert "--benchmark" in result.output

    def test_doctor_tier_display_with_config(self, tmp_path: Path) -> None:
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
        assert loaded.models.tiers["balanced"] == "claude-sonnet-4.6"
        assert loaded.models.tiers["fast"] == "claude-haiku-4.5"


# ── Manifest wiring ─────────────────────────────────────────────────


class TestManifestWiring:
    """Manifest generation and recording in the execution pipeline."""

    def test_build_env_fingerprint_deterministic(self) -> None:
        from foxhound.cli.run_pipeline import _build_env_fingerprint

        fp1 = _build_env_fingerprint()
        fp2 = _build_env_fingerprint()
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_record_manifest_creates_artifact(self, tmp_path: Path) -> None:
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

    def test_record_manifest_handles_errors_gracefully(self) -> None:
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

    def test_record_manifest_updates_run_record(self, tmp_path: Path) -> None:
        from foxhound.core.models import RunRecord
        from foxhound.storage.database import Database, RunStore

        db = Database(tmp_path / "test.db")
        run_store = RunStore(db)

        run = RunRecord(
            run_id="run_manifest_test",
            job_id="job_test",
            worker_type="ExecutionWorker",
        )
        run_store.save(run)

        result = run_store.update_manifest_path(
            "run_manifest_test", "manifests/manifest_abc.json"
        )
        assert result is True

        loaded = run_store.get("run_manifest_test")
        assert loaded is not None
        assert loaded.manifest_path == "manifests/manifest_abc.json"
        db.close()

    def test_observer_store_record_manifest(self, tmp_path: Path) -> None:
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

        manifest_file = artifacts_dir / "manifests" / "manifest_test123.json"
        assert manifest_file.exists()
        data = json.loads(manifest_file.read_text())
        assert data["manifest_id"] == "manifest_test123"
        assert data["run_id"] == "run_1"
        db.close()


# ── Creative adapter wiring ──────────────────────────────────────────


class TestCreativeAdapterWiring:
    """Creative tier adapter: graceful skip and error paths."""

    def test_run_image_step_skips_without_creative(self, tmp_path: Path) -> None:
        from foxhound.execution.creative import ImageStepConfig, run_image_step

        step = ImageStepConfig(name="test_step", output="test_out")
        result = run_image_step(step, "test", tmp_path, creative_available=False)
        assert result.skipped is True
        assert result.skip_reason == "Creative tier not configured"

    def test_run_image_step_placeholder_without_adapter(
        self, tmp_path: Path,
    ) -> None:
        from foxhound.execution.creative import ImageStepConfig, run_image_step

        step = ImageStepConfig(name="test", output="test_img")
        result = run_image_step(
            step, "test", tmp_path,
            creative_available=True, image_adapter=None,
        )
        assert result.artifact_path is not None
        assert result.model_id == "creative"

    @pytest.mark.parametrize("config_input,reason", [
        ({"tiers": {"balanced": "claude-sonnet-4.6"}}, "no creative tier"),
        (
            {
                "provider": "openai",
                "api_key_env": "NONEXISTENT_KEY_12345",
                "tiers": {"creative": "gpt-image-1"},
            },
            "missing API key",
        ),
        (
            {"provider": "unknown_provider", "tiers": {"creative": "some-model"}},
            "unknown provider",
        ),
    ], ids=["no-creative", "no-api-key", "unknown-provider"])
    def test_get_image_adapter_returns_none(
        self, config_input: dict[str, Any], reason: str,
    ) -> None:
        from foxhound.execution.creative import get_image_adapter_from_config

        assert get_image_adapter_from_config(config_input) is None

    def test_run_image_step_adapter_exception(self, tmp_path: Path) -> None:
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


# ── TUI module importability ─────────────────────────────────────────


class TestTuiImport:
    """Basic TUI module import check."""

    def test_foxhound_app_importable(self) -> None:
        from foxhound.tui.app import FoxhoundApp

        assert FoxhoundApp is not None
