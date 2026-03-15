"""Tests for observability CLI commands."""

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from foxhound.cli.app import app
from foxhound.storage.database import Database, RunStore

runner = CliRunner()


def _fh_dir(base: Path) -> Path:
    return base / ".foxhound"


def _fh_db(base: Path) -> Path:
    return base / ".foxhound" / "foxhound.db"


@pytest.fixture
def initialized_dir(tmp_path: Path) -> Path:
    """Create a minimal initialized foxhound directory."""
    fh_dir = tmp_path / ".foxhound"
    fh_dir.mkdir()
    for subdir in ["artifacts", "recipes", "policies", "cache", "config"]:
        (fh_dir / subdir).mkdir()

    db = Database(fh_dir / "foxhound.db")
    db.close()

    config = tmp_path / "foxhound.yaml"
    config.write_text(
        "models:\n"
        "  provider: anthropic\n"
        "  api_key_env: ANTHROPIC_API_KEY\n"
        "  tiers:\n"
        "    reasoning: test-model\n"
        "    balanced: test-model\n"
        "    fast: test-model\n"
    )

    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(".foxhound/\n")

    return tmp_path


def _patched(d: Path):  # noqa: ANN201
    """Context manager patching _foxhound_dir and _db_path."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():  # noqa: ANN202
        with (
            patch("foxhound.cli.app._foxhound_dir", return_value=_fh_dir(d)),
            patch("foxhound.cli.app._db_path", return_value=_fh_db(d)),
        ):
            yield

    return _ctx()


class TestLogRunsCommand:
    def test_log_runs_empty(self, initialized_dir: Path) -> None:
        with _patched(initialized_dir):
            result = runner.invoke(app, ["log", "--runs"])
            assert result.exit_code == 0
            assert "No runs found" in result.output

    def test_log_runs_with_data(self, initialized_dir: Path) -> None:
        db_path = _fh_db(initialized_dir)
        db = Database(db_path)
        from foxhound.core.models import RunRecord, RunState

        run_store = RunStore(db)
        run_store.save(RunRecord(
            run_id="run_test_001",
            job_id="job_001",
            worker_type="ExecutionWorker",
            state=RunState.COMPLETED,
            total_cost=0.05,
            branch_name="foxhound/test-branch",
        ))
        db.close()

        with _patched(initialized_dir):
            result = runner.invoke(app, ["log", "--runs"])
            assert result.exit_code == 0
            assert "Run History" in result.output
            assert "run_te" in result.output

    def test_log_runs_filter_state(self, initialized_dir: Path) -> None:
        db_path = _fh_db(initialized_dir)
        db = Database(db_path)
        from foxhound.core.models import RunRecord, RunState

        run_store = RunStore(db)
        run_store.save(RunRecord(
            run_id="run_pass",
            job_id="job_001",
            worker_type="ExecutionWorker",
            state=RunState.COMPLETED,
        ))
        run_store.save(RunRecord(
            run_id="run_fail",
            job_id="job_002",
            worker_type="ExecutionWorker",
            state=RunState.FAILED,
            failure_reason="test error",
        ))
        db.close()

        with _patched(initialized_dir):
            result = runner.invoke(
                app, ["log", "--runs", "--state", "failed"]
            )
            assert result.exit_code == 0
            assert "run_fail" in result.output

    def test_log_runs_invalid_state(self, initialized_dir: Path) -> None:
        with _patched(initialized_dir):
            result = runner.invoke(
                app, ["log", "--runs", "--state", "bogus"]
            )
            assert result.exit_code == 1
            assert "Invalid state" in result.output


class TestAnalyzeCommand:
    def test_analyze_no_failed_runs(self, initialized_dir: Path) -> None:
        with _patched(initialized_dir):
            result = runner.invoke(app, ["analyze"])
            assert result.exit_code == 0
            assert "No failed runs" in result.output

    def test_analyze_specific_run(self, initialized_dir: Path) -> None:
        db_path = _fh_db(initialized_dir)
        db = Database(db_path)
        from foxhound.core.models import RunRecord, RunState

        RunStore(db).save(RunRecord(
            run_id="run_analyze",
            job_id="job_001",
            worker_type="ExecutionWorker",
            state=RunState.FAILED,
            failure_reason="lint check failed",
        ))
        db.close()

        with _patched(initialized_dir):
            result = runner.invoke(app, ["analyze", "run_analyze"])
            assert result.exit_code == 0
            assert "Analysis" in result.output
            assert "validation_failure" in result.output

    def test_analyze_recent_failed(self, initialized_dir: Path) -> None:
        db_path = _fh_db(initialized_dir)
        db = Database(db_path)
        from foxhound.core.models import RunRecord, RunState

        RunStore(db).save(RunRecord(
            run_id="run_f1",
            job_id="job_001",
            worker_type="ExecutionWorker",
            state=RunState.FAILED,
            failure_reason="timed out",
        ))
        db.close()

        with _patched(initialized_dir):
            result = runner.invoke(app, ["analyze"])
            assert result.exit_code == 0
            assert "Analysis" in result.output


class TestRetentionCommands:
    def test_retention_status(self, initialized_dir: Path) -> None:
        with _patched(initialized_dir):
            result = runner.invoke(app, ["retention", "status"])
            assert result.exit_code == 0
            assert "Retention Status" in result.output

    def test_retention_prune_empty(self, initialized_dir: Path) -> None:
        with _patched(initialized_dir):
            result = runner.invoke(app, ["retention", "prune"])
            assert result.exit_code == 0
            assert "Pruned" in result.output
            assert "0 artifacts" in result.output

    def test_retention_compact(self, initialized_dir: Path) -> None:
        with _patched(initialized_dir):
            result = runner.invoke(app, ["retention", "compact"])
            assert result.exit_code == 0
            assert "Compacted" in result.output


class TestDoctorEnhancements:
    def test_format_size(self) -> None:
        from foxhound.cli.app import _format_size

        assert _format_size(0) == "0 B"
        assert _format_size(512) == "512 B"
        assert _format_size(1024) == "1.0 KB"
        assert _format_size(1024 * 1024) == "1.0 MB"
        assert _format_size(1024 * 1024 * 1024) == "1.0 GB"
        assert _format_size(1536) == "1.5 KB"
