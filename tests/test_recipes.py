"""Tests for recipe loader and schema validation."""

import textwrap
from pathlib import Path

import pytest

from foxhound.recipes.loader import (
    ContextConfig,
    Recipe,
    RecipeLoader,
    RetryConfig,
    compute_content_hash,
    load_recipe_from_dict,
    load_recipe_from_yaml,
)


class TestRecipeSchema:
    """Test recipe Pydantic model validation."""

    def test_minimal_recipe(self) -> None:
        recipe = Recipe(name="test", version="1.0.0")
        assert recipe.name == "test"
        assert recipe.version == "1.0.0"
        assert recipe.execution_strategy == "one_shot"

    def test_full_recipe(self) -> None:
        recipe = Recipe(
            name="test_recipe",
            version="2.1.0",
            description="A test recipe",
            execution_strategy="bounded_retry",
            tier_overrides={"execution": "balanced", "review_final": "reasoning"},
        )
        assert recipe.name == "test_recipe"
        assert recipe.version == "2.1.0"
        assert recipe.tier_overrides["execution"] == "balanced"

    def test_invalid_version_format(self) -> None:
        with pytest.raises(ValueError):
            Recipe(name="test", version="not-a-version")

    def test_invalid_tier_override(self) -> None:
        with pytest.raises(ValueError, match="tier override"):
            Recipe(
                name="test",
                version="1.0.0",
                tier_overrides={"execution": "ultra_mega"},
            )

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            Recipe(name="", version="1.0.0")

    def test_context_config_defaults(self) -> None:
        ctx = ContextConfig()
        assert ctx.max_files == 50
        assert ctx.max_total_size_kb == 500
        assert ctx.include_patterns == []

    def test_retry_config_validation(self) -> None:
        with pytest.raises(ValueError, match="backoff_strategy"):
            RetryConfig(backoff_strategy="invalid")

    def test_retry_config_valid_strategies(self) -> None:
        for strategy in ("fixed", "exponential", "none"):
            config = RetryConfig(backoff_strategy=strategy)
            assert config.backoff_strategy == strategy

    def test_recipe_json_roundtrip(self) -> None:
        recipe = Recipe(
            name="roundtrip",
            version="1.0.0",
            description="Test roundtrip",
            execution_strategy="ralph_loop",
        )
        data = recipe.model_dump()
        restored = Recipe(**data)
        assert restored.name == recipe.name
        assert restored.version == recipe.version
        assert restored.execution_strategy == recipe.execution_strategy


class TestContentHash:
    """Test content hashing for provenance."""

    def test_deterministic(self) -> None:
        content = "name: test\nversion: '1.0.0'\n"
        h1 = compute_content_hash(content)
        h2 = compute_content_hash(content)
        assert h1 == h2

    def test_different_content_different_hash(self) -> None:
        h1 = compute_content_hash("version: 1.0.0")
        h2 = compute_content_hash("version: 2.0.0")
        assert h1 != h2

    def test_hash_length(self) -> None:
        h = compute_content_hash("test")
        assert len(h) == 12


class TestLoadRecipeFromYaml:
    """Test loading recipes from YAML files."""

    def test_load_valid_yaml(self, tmp_path: Path) -> None:
        yaml_content = textwrap.dedent("""\
            name: test_recipe
            version: "1.0.0"
            description: A test recipe
            execution_strategy: one_shot
            context:
              include_patterns:
                - "src/**/*.py"
              max_files: 30
            validation:
              commands:
                - "pytest"
        """)
        path = tmp_path / "test.yaml"
        path.write_text(yaml_content)
        recipe = load_recipe_from_yaml(path)
        assert recipe.name == "test_recipe"
        assert recipe.version == "1.0.0"
        assert recipe.context.max_files == 30
        assert "pytest" in recipe.validation.commands

    def test_load_nonexistent_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_recipe_from_yaml(tmp_path / "nope.yaml")

    def test_load_invalid_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("{{invalid yaml}}")
        with pytest.raises(ValueError, match="Invalid YAML"):
            load_recipe_from_yaml(path)

    def test_load_non_mapping_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_recipe_from_yaml(path)


class TestLoadRecipeFromDict:
    """Test loading recipes from dictionaries."""

    def test_load_from_dict(self) -> None:
        data = {"name": "dict_recipe", "version": "1.0.0"}
        recipe = load_recipe_from_dict(data)
        assert recipe.name == "dict_recipe"


class TestRecipeLoader:
    """Test RecipeLoader with precedence resolution."""

    def test_load_builtins(self) -> None:
        loader = RecipeLoader()
        recipes = loader.load_all()
        assert "approved_ticket" in recipes
        assert "dependency_security_update" in recipes
        assert "ci_failure_repair" in recipes

    def test_builtin_recipe_versions(self) -> None:
        loader = RecipeLoader()
        recipes = loader.load_all()
        for recipe in recipes.values():
            assert recipe.version == "1.0.0"

    def test_load_by_name(self) -> None:
        loader = RecipeLoader()
        recipe = loader.load_by_name("approved_ticket")
        assert recipe is not None
        assert recipe.name == "approved_ticket"

    def test_load_by_name_not_found(self) -> None:
        loader = RecipeLoader()
        assert loader.load_by_name("nonexistent") is None

    def test_get_recipe_ref(self) -> None:
        loader = RecipeLoader()
        ref = loader.get_recipe_ref("approved_ticket")
        assert ref is not None
        assert ref.name == "approved_ticket"
        assert ref.version == "1.0.0"
        assert ref.source_scope == "builtin"
        assert len(ref.content_hash) == 12

    def test_repo_local_overrides_builtin(self, tmp_path: Path) -> None:
        recipes_dir = tmp_path / ".foxhound" / "recipes"
        recipes_dir.mkdir(parents=True)
        yaml_content = textwrap.dedent("""\
            name: approved_ticket
            version: "2.0.0"
            description: Custom override
            execution_strategy: one_shot
        """)
        (recipes_dir / "approved_ticket.yaml").write_text(yaml_content)

        loader = RecipeLoader(repo_dir=tmp_path)
        recipe = loader.load_by_name("approved_ticket")
        assert recipe is not None
        assert recipe.version == "2.0.0"
        assert recipe.description == "Custom override"

    def test_repo_local_ref_scope(self, tmp_path: Path) -> None:
        recipes_dir = tmp_path / ".foxhound" / "recipes"
        recipes_dir.mkdir(parents=True)
        yaml_content = textwrap.dedent("""\
            name: custom_recipe
            version: "1.0.0"
            description: Repo-local only
        """)
        (recipes_dir / "custom.yaml").write_text(yaml_content)

        loader = RecipeLoader(repo_dir=tmp_path)
        ref = loader.get_recipe_ref("custom_recipe")
        assert ref is not None
        assert ref.source_scope == "repo"

    def test_list_available(self) -> None:
        loader = RecipeLoader()
        available = loader.list_available()
        names = [r["name"] for r in available]
        assert "approved_ticket" in names
        assert all("version" in r and "scope" in r for r in available)

    def test_ci_failure_repair_uses_bounded_retry(self) -> None:
        loader = RecipeLoader()
        recipe = loader.load_by_name("ci_failure_repair")
        assert recipe is not None
        assert recipe.execution_strategy == "bounded_retry"
        assert recipe.retry.max_retries == 3
