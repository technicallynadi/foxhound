"""Security tests for Foxhound — validates all hardening fixes."""

from pathlib import Path

import pytest

from foxhound.core.models import (
    EventType,
    RunRecord,
    TrustLevel,
    WorkItem,
    WorkItemState,
)
from foxhound.execution.engine import _is_command_allowed
from foxhound.execution.workspace import validate_branch_name


class TestCommandInjectionPrevention:
    """Verify expanded metacharacter and shlex-based validation."""

    def test_quoted_argument_injection_blocked(self) -> None:
        assert not _is_command_allowed('pytest "--tb=short; rm -rf /"')

    def test_process_substitution_blocked(self) -> None:
        assert not _is_command_allowed("pytest <(echo payload)")

    def test_output_process_substitution_blocked(self) -> None:
        assert not _is_command_allowed("ruff >(cat)")

    def test_brace_expansion_blocked(self) -> None:
        assert not _is_command_allowed("pytest ${HOME}")

    def test_arithmetic_expansion_blocked(self) -> None:
        assert not _is_command_allowed("ruff $((1+1))")

    def test_newline_injection_blocked(self) -> None:
        assert not _is_command_allowed("pytest\nrm -rf /")

    def test_carriage_return_injection_blocked(self) -> None:
        assert not _is_command_allowed("pytest\rrm -rf /")

    def test_null_byte_blocked(self) -> None:
        assert not _is_command_allowed("pytest \x00evil")

    def test_pipe_stderr_blocked(self) -> None:
        assert not _is_command_allowed("pytest |& cat")

    def test_backtick_command_sub_blocked(self) -> None:
        assert not _is_command_allowed("pytest `whoami`")

    def test_dollar_paren_blocked(self) -> None:
        assert not _is_command_allowed("pytest $(whoami)")

    def test_valid_commands_still_work(self) -> None:
        assert _is_command_allowed("pytest")
        assert _is_command_allowed("pytest -v --tb=short")
        assert _is_command_allowed("ruff check .")
        assert _is_command_allowed("mypy foxhound/")

    def test_empty_command_rejected(self) -> None:
        assert not _is_command_allowed("")
        assert not _is_command_allowed("   ")

    def test_malformed_quotes_rejected(self) -> None:
        assert not _is_command_allowed("pytest 'unterminated")


class TestBranchNameValidation:
    """Verify git branch name validation prevents ref injection."""

    def test_valid_branch_names(self) -> None:
        assert validate_branch_name("foxhound/exec-abc123-def456")
        assert validate_branch_name("feature/my-branch")
        assert validate_branch_name("main")
        assert validate_branch_name("v1.0.0")

    def test_refspec_injection_rejected(self) -> None:
        assert not validate_branch_name("HEAD:refs/heads/master")

    def test_double_dot_rejected(self) -> None:
        assert not validate_branch_name("main..feature")

    def test_caret_rejected(self) -> None:
        assert not validate_branch_name("main^2")

    def test_tilde_rejected(self) -> None:
        assert not validate_branch_name("main~1")

    def test_at_brace_rejected(self) -> None:
        assert not validate_branch_name("main@{upstream}")

    def test_double_dash_rejected(self) -> None:
        assert not validate_branch_name("--option-looking")

    def test_starting_with_dash_rejected(self) -> None:
        assert not validate_branch_name("-malicious")

    def test_space_rejected(self) -> None:
        assert not validate_branch_name("branch with spaces")

    def test_control_chars_rejected(self) -> None:
        assert not validate_branch_name("branch\x00name")
        assert not validate_branch_name("branch\tname")

    def test_empty_rejected(self) -> None:
        assert not validate_branch_name("")

    def test_backslash_rejected(self) -> None:
        assert not validate_branch_name("branch\\name")

    def test_too_long_rejected(self) -> None:
        assert not validate_branch_name("a" * 256)


class TestSecurityReviewGate:
    """Verify BRANCH_READY requires security_review_passed."""

    def test_run_record_defaults_to_not_passed(self) -> None:
        run = RunRecord(
            run_id="run-001",
            job_id="job-001",
            worker_type="ExecutionWorker",
        )
        assert run.security_review_passed is False

    def test_security_review_can_be_set(self) -> None:
        run = RunRecord(
            run_id="run-001",
            job_id="job-001",
            worker_type="ExecutionWorker",
            security_review_passed=True,
        )
        assert run.security_review_passed is True


class TestEventSourceVerification:
    """Verify event bus rejects unauthorized emitters."""

    def test_approval_from_unauthorized_source_rejected(self) -> None:
        from foxhound.core.event_bus import EventBus

        bus = EventBus(source_module="malicious_worker")
        with pytest.raises(PermissionError, match="not authorized"):
            bus.emit(event_type=EventType.APPROVAL_GRANTED)

    def test_approval_from_coordinator_allowed(self) -> None:
        from foxhound.core.event_bus import EventBus

        bus = EventBus(source_module="coordinator")
        event = bus.emit(event_type=EventType.APPROVAL_GRANTED)
        assert event.event_type == EventType.APPROVAL_GRANTED

    def test_approval_from_cli_allowed(self) -> None:
        from foxhound.core.event_bus import EventBus

        bus = EventBus(source_module="cli")
        event = bus.emit(event_type=EventType.APPROVAL_GRANTED)
        assert event.source_module == "cli"

    def test_security_violation_from_unauthorized_rejected(self) -> None:
        from foxhound.core.event_bus import EventBus

        bus = EventBus(source_module="some_random_module")
        with pytest.raises(PermissionError):
            bus.emit(event_type=EventType.SECURITY_VIOLATION_DETECTED)

    def test_unrestricted_event_from_any_source_allowed(self) -> None:
        from foxhound.core.event_bus import EventBus

        bus = EventBus(source_module="any_module")
        event = bus.emit(event_type=EventType.RUN_STARTED)
        assert event.event_type == EventType.RUN_STARTED

    def test_promotion_event_from_unauthorized_rejected(self) -> None:
        from foxhound.core.event_bus import EventBus

        bus = EventBus(source_module="evil_worker")
        with pytest.raises(PermissionError):
            bus.emit(event_type=EventType.PROMOTION_SUCCEEDED)

    def test_promotion_event_from_promotion_manager_allowed(self) -> None:
        from foxhound.core.event_bus import EventBus

        bus = EventBus(source_module="promotion_manager")
        event = bus.emit(event_type=EventType.PROMOTION_STARTED)
        assert event.event_type == EventType.PROMOTION_STARTED


class TestEvidenceTrustLabeling:
    """Verify evidence and work items get correct trust labels."""

    def test_evidence_from_github_issue_semi_trusted(self, tmp_path: Path) -> None:
        from foxhound.execution.context import ContextAssembler

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("print('hello')\n")

        wi = WorkItem(
            work_item_id="wi-001",
            repo_id="repo-001",
            title="Fix bug",
            source_type="github_issue",
            source_fingerprint="fp1",
            state=WorkItemState.APPROVED,
            likely_files=["main.py"],
            evidence={"issue": 42},
        )

        assembler = ContextAssembler(repo)
        pack = assembler.assemble(wi)
        assert pack.trust_labels["evidence"] == TrustLevel.SEMI_TRUSTED.value
        assert pack.trust_labels["work_item"] == TrustLevel.SEMI_TRUSTED.value

    def test_evidence_from_reddit_untrusted(self, tmp_path: Path) -> None:
        from foxhound.execution.context import ContextAssembler

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("print('hello')\n")

        wi = WorkItem(
            work_item_id="wi-002",
            repo_id="repo-001",
            title="Fix bug",
            source_type="reddit",
            source_fingerprint="fp2",
            state=WorkItemState.APPROVED,
            likely_files=["main.py"],
        )

        assembler = ContextAssembler(repo)
        pack = assembler.assemble(wi)
        assert pack.trust_labels["evidence"] == TrustLevel.UNTRUSTED.value

    def test_recipe_always_trusted(self, tmp_path: Path) -> None:
        from foxhound.execution.context import ContextAssembler

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("print('hello')\n")

        wi = WorkItem(
            work_item_id="wi-003",
            repo_id="repo-001",
            title="Fix bug",
            source_type="ci_failure",
            source_fingerprint="fp3",
            state=WorkItemState.APPROVED,
        )

        assembler = ContextAssembler(repo)
        pack = assembler.assemble(wi)
        assert pack.trust_labels["recipe"] == TrustLevel.TRUSTED.value
        assert pack.trust_labels["policy"] == TrustLevel.TRUSTED.value


class TestSymlinkSafety:
    """Verify symlinks are rejected by safe file reading."""

    def test_symlink_file_excluded(self, tmp_path: Path) -> None:
        from foxhound.execution.context import _safe_read_file

        real_file = tmp_path / "real.txt"
        real_file.write_text("real content")
        symlink = tmp_path / "link.txt"
        symlink.symlink_to(real_file)

        result = _safe_read_file(symlink, tmp_path)
        assert result is None

    def test_regular_file_readable(self, tmp_path: Path) -> None:
        from foxhound.execution.context import _safe_read_file

        real_file = tmp_path / "real.txt"
        real_file.write_text("real content")

        result = _safe_read_file(real_file, tmp_path)
        assert result == "real content"

    def test_file_outside_repo_rejected(self, tmp_path: Path) -> None:
        from foxhound.execution.context import _safe_read_file

        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("secret")

        repo = tmp_path / "repo"
        repo.mkdir()

        result = _safe_read_file(secret, repo)
        assert result is None

class TestSessionSecretScoping:
    """Verify secrets are isolated between jobs."""

    def test_secrets_isolated_between_jobs(self) -> None:
        from foxhound.secrets.provider import SessionOverrideProvider

        provider = SessionOverrideProvider()
        provider.set_secret("API_KEY", "key-for-job-1", job_id="job-1")
        provider.set_secret("API_KEY", "key-for-job-2", job_id="job-2")

        assert provider.get_secret("API_KEY", job_id="job-1") == "key-for-job-1"
        assert provider.get_secret("API_KEY", job_id="job-2") == "key-for-job-2"

    def test_clear_job_removes_all_secrets(self) -> None:
        from foxhound.secrets.provider import SessionOverrideProvider

        provider = SessionOverrideProvider()
        provider.set_secret("KEY1", "val1", job_id="job-1")
        provider.set_secret("KEY2", "val2", job_id="job-1")
        provider.clear_job("job-1")

        assert provider.get_secret("KEY1", job_id="job-1") is None
        assert provider.get_secret("KEY2", job_id="job-1") is None

    def test_global_scope_fallback(self) -> None:
        from foxhound.secrets.provider import SessionOverrideProvider

        provider = SessionOverrideProvider()
        provider.set_secret("GLOBAL_KEY", "global-value")

        assert provider.get_secret("GLOBAL_KEY") == "global-value"
        assert provider.get_secret("GLOBAL_KEY", job_id="any-job") == "global-value"

    def test_job_scope_overrides_global(self) -> None:
        from foxhound.secrets.provider import SessionOverrideProvider

        provider = SessionOverrideProvider()
        provider.set_secret("KEY", "global")
        provider.set_secret("KEY", "job-specific", job_id="job-1")

        assert provider.get_secret("KEY", job_id="job-1") == "job-specific"
        assert provider.get_secret("KEY") == "global"


class TestPromotionIntegrity:
    """Verify workspace integrity is checked before promotion."""

    def test_hash_workspace_files(self, tmp_path: Path) -> None:
        from foxhound.execution.promotion import PromotionManager

        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "file.py").write_text("print('hello')\n")

        hash1 = PromotionManager.hash_workspace_files(ws, ["file.py"])
        hash2 = PromotionManager.hash_workspace_files(ws, ["file.py"])
        assert hash1 == hash2

    def test_hash_changes_when_file_modified(self, tmp_path: Path) -> None:
        from foxhound.execution.promotion import PromotionManager

        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "file.py").write_text("print('hello')\n")

        hash1 = PromotionManager.hash_workspace_files(ws, ["file.py"])

        (ws / "file.py").write_text("print('modified')\n")
        hash2 = PromotionManager.hash_workspace_files(ws, ["file.py"])

        assert hash1 != hash2
