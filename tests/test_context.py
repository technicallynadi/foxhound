"""Tests for context pack assembly."""

from pathlib import Path

import pytest

from foxhound.core.models import TrustLevel, WorkItem, WorkItemState
from foxhound.execution.context import (
    ContextAssembler,
    ContextPack,
    _is_sensitive_file,
    _matches_patterns,
    save_context_pack,
)
from foxhound.recipes.loader import Recipe


def _make_work_item(**overrides: object) -> WorkItem:
    """Create a test work item with defaults."""
    defaults = {
        "work_item_id": "wi-test-001",
        "repo_id": "repo-001",
        "title": "Fix authentication bug",
        "description": "Users are unable to log in with email",
        "source_type": "github_issue",
        "source_fingerprint": "abc123",
        "state": WorkItemState.APPROVED,
        "likely_files": [],
        "evidence": {"issue_number": 42},
    }
    defaults.update(overrides)
    return WorkItem(**defaults)


def _make_recipe(**overrides: object) -> Recipe:
    """Create a test recipe with defaults."""
    defaults = {
        "name": "test_recipe",
        "version": "1.0.0",
        "description": "Test recipe",
    }
    defaults.update(overrides)
    return Recipe(**defaults)


@pytest.fixture
def repo_dir(tmp_path: Path) -> Path:
    """Create a mock repository with test files."""
    repo = tmp_path / "repo"
    repo.mkdir()

    (repo / "src").mkdir()
    (repo / "src" / "auth.py").write_text("def login(): pass\n")
    (repo / "src" / "utils.py").write_text("def helper(): pass\n")

    (repo / "tests").mkdir()
    (repo / "tests" / "test_auth.py").write_text("def test_login(): pass\n")

    (repo / "README.md").write_text("# Test Project\n")
    (repo / "pyproject.toml").write_text("[project]\nname='test'\n")

    return repo


class TestSensitiveFileDetection:
    """Tests for sensitive file detection."""

    def test_env_file(self) -> None:
        assert _is_sensitive_file(".env")

    def test_env_local(self) -> None:
        assert _is_sensitive_file(".env.local")

    def test_pem_file(self) -> None:
        assert _is_sensitive_file("server.pem")

    def test_key_file(self) -> None:
        assert _is_sensitive_file("private.key")

    def test_ssh_dir(self) -> None:
        assert _is_sensitive_file(".ssh/authorized_keys")

    def test_secrets_dir(self) -> None:
        assert _is_sensitive_file("secrets/api_keys.json")

    def test_normal_python_file(self) -> None:
        assert not _is_sensitive_file("src/main.py")

    def test_credentials_json(self) -> None:
        assert _is_sensitive_file("credentials.json")

    def test_normal_json(self) -> None:
        assert not _is_sensitive_file("config.json")


class TestPatternMatching:
    """Tests for pattern matching utility."""

    def test_match_simple_glob(self) -> None:
        assert _matches_patterns("test.py", ["*.py"])
        assert not _matches_patterns("src/test.py", ["*.py"])

    def test_match_double_star_pattern(self) -> None:
        assert _matches_patterns("deep/nested/test.py", ["**/*.py"])

    def test_no_match(self) -> None:
        assert not _matches_patterns("lib/test.rs", ["*.py"])

    def test_node_modules(self) -> None:
        assert _matches_patterns(
            "node_modules/pkg/index.js", ["**/node_modules/**"]
        )

    def test_pycache(self) -> None:
        assert _matches_patterns(
            "src/__pycache__/mod.pyc", ["**/__pycache__/**"]
        )


class TestContextAssembler:
    """Tests for ContextAssembler."""

    def test_basic_assembly(self, repo_dir: Path) -> None:
        """Test basic context pack assembly."""
        work_item = _make_work_item()
        assembler = ContextAssembler(repo_dir)
        pack = assembler.assemble(work_item)

        assert pack.work_item_id == "wi-test-001"
        assert pack.work_item_title == "Fix authentication bug"
        assert pack.context_hash
        assert len(pack.files) > 0

    def test_assembly_with_likely_files(self, repo_dir: Path) -> None:
        """Test that likely_files are prioritized."""
        work_item = _make_work_item(likely_files=["src/auth.py"])
        assembler = ContextAssembler(repo_dir)
        pack = assembler.assemble(work_item)

        paths = [f.path for f in pack.files]
        assert "src/auth.py" in paths

    def test_assembly_excludes_sensitive_files(self, repo_dir: Path) -> None:
        """Test that sensitive files are excluded."""
        (repo_dir / ".env").write_text("SECRET=abc123\n")
        (repo_dir / "private.key").write_text("-----BEGIN PRIVATE KEY-----\n")

        work_item = _make_work_item(
            likely_files=[".env", "private.key", "src/auth.py"]
        )
        assembler = ContextAssembler(repo_dir)
        pack = assembler.assemble(work_item)

        paths = [f.path for f in pack.files]
        assert ".env" not in paths
        assert "private.key" not in paths
        assert "src/auth.py" in paths

    def test_assembly_with_recipe(self, repo_dir: Path) -> None:
        """Test assembly respects recipe context preferences."""
        recipe = _make_recipe()
        recipe.context.include_patterns = ["src/**/*.py"]
        recipe.context.exclude_patterns = ["**/test_*.py"]

        work_item = _make_work_item()
        assembler = ContextAssembler(repo_dir)
        pack = assembler.assemble(work_item, recipe=recipe)

        paths = [f.path for f in pack.files]
        assert any("src/" in p for p in paths)

    def test_assembly_trust_labels(self, repo_dir: Path) -> None:
        """Test that trust labels are applied correctly."""
        work_item = _make_work_item(likely_files=["src/auth.py"])
        assembler = ContextAssembler(repo_dir)
        pack = assembler.assemble(work_item)

        assert pack.trust_labels["work_item"] == TrustLevel.TRUSTED.value
        assert pack.trust_labels["recipe"] == TrustLevel.TRUSTED.value
        assert pack.trust_labels.get("file:src/auth.py") == TrustLevel.SEMI_TRUSTED.value

    def test_assembly_max_files_limit(self, repo_dir: Path) -> None:
        """Test that max files limit is enforced."""
        for i in range(20):
            (repo_dir / "src" / f"module_{i}.py").write_text(f"# module {i}\n")

        recipe = _make_recipe()
        recipe.context.include_patterns = ["src/**/*.py"]
        recipe.context.max_files = 5

        work_item = _make_work_item()
        assembler = ContextAssembler(repo_dir)
        pack = assembler.assemble(work_item, recipe=recipe)

        assert len(pack.files) <= 5

    def test_assembly_skips_binary_files(self, repo_dir: Path) -> None:
        """Test that binary files are skipped."""
        (repo_dir / "src" / "image.png").write_bytes(b"\x89PNG\r\n" + b"\x00" * 100)

        work_item = _make_work_item(likely_files=["src/image.png"])
        assembler = ContextAssembler(repo_dir)
        pack = assembler.assemble(work_item)

        paths = [f.path for f in pack.files]
        assert "src/image.png" not in paths

    def test_assembly_skips_empty_files(self, repo_dir: Path) -> None:
        """Test that empty files are skipped."""
        (repo_dir / "src" / "empty.py").write_text("")

        work_item = _make_work_item(likely_files=["src/empty.py"])
        assembler = ContextAssembler(repo_dir)
        pack = assembler.assemble(work_item)

        paths = [f.path for f in pack.files]
        assert "src/empty.py" not in paths

    def test_assembly_with_policy_constraints(self, repo_dir: Path) -> None:
        """Test that policy constraints are included in pack."""
        work_item = _make_work_item()
        assembler = ContextAssembler(repo_dir)
        constraints = {"max_budget": 1.0, "allowed_commands": ["pytest"]}
        pack = assembler.assemble(
            work_item, policy_constraints=constraints
        )

        assert pack.policy_constraints == constraints

    def test_context_hash_changes_with_content(self, repo_dir: Path) -> None:
        """Test that context hash changes when content changes."""
        work_item = _make_work_item()
        assembler = ContextAssembler(repo_dir)

        pack1 = assembler.assemble(work_item)

        (repo_dir / "src" / "auth.py").write_text("def login(): return True\n")
        pack2 = assembler.assemble(work_item)

        assert pack1.context_hash != pack2.context_hash

    def test_recipe_instructions_in_pack(self, repo_dir: Path) -> None:
        """Test that recipe instructions are included."""
        recipe = _make_recipe()
        recipe.validation.commands = ["pytest", "ruff check ."]

        work_item = _make_work_item()
        assembler = ContextAssembler(repo_dir)
        pack = assembler.assemble(work_item, recipe=recipe)

        assert "validation_commands" in pack.recipe_instructions
        assert pack.recipe_instructions["validation_commands"] == ["pytest", "ruff check ."]


class TestSaveContextPack:
    """Tests for saving context packs."""

    def test_save_creates_file(self, tmp_path: Path) -> None:
        """Test that save creates a JSON file."""
        pack = ContextPack(
            work_item_id="wi-001",
            work_item_title="Test",
            context_hash="abc123",
        )
        artifacts_dir = tmp_path / "artifacts"
        path = save_context_pack(pack, artifacts_dir)

        assert path.exists()
        assert path.suffix == ".json"
        assert artifacts_dir.exists()

    def test_save_excludes_file_content(self, tmp_path: Path) -> None:
        """Test that saved pack excludes file content (for size)."""
        from foxhound.execution.context import ContextPackFile

        pack = ContextPack(
            work_item_id="wi-001",
            work_item_title="Test",
            context_hash="abc123",
            files=[
                ContextPackFile(
                    path="src/main.py",
                    content="print('hello')",
                    size_bytes=14,
                )
            ],
        )
        artifacts_dir = tmp_path / "artifacts"
        path = save_context_pack(pack, artifacts_dir)

        import json
        data = json.loads(path.read_text())
        for f in data.get("files", []):
            assert "content" not in f
