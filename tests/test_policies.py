"""Tests for policy engine and enforcement."""

import textwrap
from pathlib import Path

import pytest

from foxhound.policies.engine import (
    Policy,
    PolicyEngine,
    PolicyViolationAction,
    load_policy_from_yaml,
)


class TestPolicySchema:
    """Test policy Pydantic model validation."""

    def test_minimal_policy(self) -> None:
        policy = Policy(name="test", version="1.0.0")
        assert policy.name == "test"
        assert policy.version == "1.0.0"

    def test_full_policy(self) -> None:
        policy = Policy(
            name="strict",
            version="1.0.0",
            description="Strict policy",
            commands={"allowed": ["pytest"], "blocked": ["rm -rf"]},
            budget={"max_budget_per_job": 10.0, "max_budget_per_run": 3.0},
        )
        assert policy.commands.allowed == ["pytest"]
        assert policy.commands.blocked == ["rm -rf"]
        assert policy.budget.max_budget_per_job == 10.0

    def test_invalid_version(self) -> None:
        with pytest.raises(ValueError):
            Policy(name="test", version="bad")

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            Policy(name="", version="1.0.0")

    def test_policy_json_roundtrip(self) -> None:
        policy = Policy(
            name="roundtrip",
            version="1.0.0",
            description="Test roundtrip",
        )
        data = policy.model_dump()
        restored = Policy(**data)
        assert restored.name == policy.name
        assert restored.version == policy.version


class TestLoadPolicyFromYaml:
    """Test loading policies from YAML files."""

    def test_load_valid_yaml(self, tmp_path: Path) -> None:
        yaml_content = textwrap.dedent("""\
            name: test_policy
            version: "1.0.0"
            description: A test policy
            commands:
              allowed:
                - "pytest"
              blocked:
                - "rm -rf"
            sensitive_paths:
              blocked_patterns:
                - ".env"
        """)
        path = tmp_path / "test.yaml"
        path.write_text(yaml_content)
        policy = load_policy_from_yaml(path)
        assert policy.name == "test_policy"
        assert "pytest" in policy.commands.allowed
        assert ".env" in policy.sensitive_paths.blocked_patterns

    def test_load_nonexistent_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_policy_from_yaml(tmp_path / "nope.yaml")


class TestPolicyEngine:
    """Test PolicyEngine loading and enforcement."""

    def test_load_default_policy(self) -> None:
        engine = PolicyEngine()
        policies = engine.load_all()
        assert "default_policy" in policies

    def test_set_active_policy(self) -> None:
        engine = PolicyEngine()
        assert engine.set_active_policy("default_policy")
        assert engine.active_policy is not None
        assert engine.active_policy.name == "default_policy"

    def test_set_nonexistent_policy(self) -> None:
        engine = PolicyEngine()
        assert not engine.set_active_policy("nonexistent")

    def test_get_policy_ref(self) -> None:
        engine = PolicyEngine()
        ref = engine.get_policy_ref("default_policy")
        assert ref is not None
        assert ref.name == "default_policy"
        assert ref.version == "1.0.0"
        assert ref.source_scope == "builtin"
        assert len(ref.content_hash) == 12

    def test_list_available(self) -> None:
        engine = PolicyEngine()
        available = engine.list_available()
        names = [p["name"] for p in available]
        assert "default_policy" in names

    def test_repo_local_overrides_builtin(self, tmp_path: Path) -> None:
        policies_dir = tmp_path / ".foxhound" / "policies"
        policies_dir.mkdir(parents=True)
        yaml_content = textwrap.dedent("""\
            name: default_policy
            version: "2.0.0"
            description: Custom override
        """)
        (policies_dir / "default_policy.yaml").write_text(yaml_content)

        engine = PolicyEngine(repo_dir=tmp_path)
        policy = engine.load_by_name("default_policy")
        assert policy is not None
        assert policy.version == "2.0.0"


class TestCommandEnforcement:
    """Test command allowlist/blocklist enforcement."""

    @pytest.fixture()
    def engine(self) -> PolicyEngine:
        engine = PolicyEngine()
        engine.set_active_policy("default_policy")
        return engine

    def test_allowed_command(self, engine: PolicyEngine) -> None:
        assert engine.check_command("pytest tests/") is None

    def test_blocked_command(self, engine: PolicyEngine) -> None:
        v = engine.check_command("rm -rf /")
        assert v is not None
        assert v.action == PolicyViolationAction.BLOCK
        assert v.area == "commands"

    def test_unlisted_command_blocked(self, engine: PolicyEngine) -> None:
        v = engine.check_command("dangerous_script.sh")
        assert v is not None
        assert v.action == PolicyViolationAction.BLOCK

    def test_no_policy_allows_all(self) -> None:
        engine = PolicyEngine()
        assert engine.check_command("anything") is None


class TestPathEnforcement:
    """Test sensitive path blocking."""

    @pytest.fixture()
    def engine(self) -> PolicyEngine:
        engine = PolicyEngine()
        engine.set_active_policy("default_policy")
        return engine

    def test_env_file_blocked(self, engine: PolicyEngine) -> None:
        v = engine.check_path(".env")
        assert v is not None
        assert v.action == PolicyViolationAction.BLOCK

    def test_env_variant_blocked(self, engine: PolicyEngine) -> None:
        v = engine.check_path(".env.production")
        assert v is not None

    def test_pem_file_blocked(self, engine: PolicyEngine) -> None:
        v = engine.check_path("certs/server.pem")
        assert v is not None

    def test_ssh_directory_blocked(self, engine: PolicyEngine) -> None:
        v = engine.check_path(".ssh/id_rsa")
        assert v is not None

    def test_normal_file_allowed(self, engine: PolicyEngine) -> None:
        assert engine.check_path("src/main.py") is None

    def test_secrets_directory_blocked(self, engine: PolicyEngine) -> None:
        v = engine.check_path("secrets/api_key.txt")
        assert v is not None


class TestBudgetEnforcement:
    """Test budget cap enforcement."""

    @pytest.fixture()
    def engine(self) -> PolicyEngine:
        engine = PolicyEngine()
        engine.set_active_policy("default_policy")
        return engine

    def test_within_budget(self, engine: PolicyEngine) -> None:
        assert engine.check_budget(1.0, "run") is None

    def test_exceed_run_budget(self, engine: PolicyEngine) -> None:
        v = engine.check_budget(10.0, "run")
        assert v is not None
        assert v.area == "budget"

    def test_exceed_job_budget(self, engine: PolicyEngine) -> None:
        v = engine.check_budget(10.0, "job")
        assert v is not None


class TestTimeoutEnforcement:
    """Test timeout limit enforcement."""

    @pytest.fixture()
    def engine(self) -> PolicyEngine:
        engine = PolicyEngine()
        engine.set_active_policy("default_policy")
        return engine

    def test_within_timeout(self, engine: PolicyEngine) -> None:
        assert engine.check_timeout(300) is None

    def test_exceed_timeout(self, engine: PolicyEngine) -> None:
        v = engine.check_timeout(3600)
        assert v is not None
        assert v.area == "timeout"


class TestCheckAll:
    """Test combined policy checks."""

    def test_multiple_violations(self) -> None:
        engine = PolicyEngine()
        engine.set_active_policy("default_policy")
        violations = engine.check_all(
            command="rm -rf /",
            paths=[".env", "src/main.py"],
            budget=100.0,
            timeout=9999,
        )
        assert len(violations) >= 3  # command + path + budget + timeout
        areas = {v.area for v in violations}
        assert "commands" in areas
        assert "sensitive_paths" in areas
        assert "budget" in areas

    def test_no_violations(self) -> None:
        engine = PolicyEngine()
        engine.set_active_policy("default_policy")
        violations = engine.check_all(
            command="pytest tests/",
            paths=["src/main.py"],
            budget=1.0,
            timeout=300,
        )
        assert len(violations) == 0
