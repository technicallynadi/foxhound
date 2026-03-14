"""Recipe loader and schema validation for Foxhound."""

import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from foxhound.core.models import ExecutionStrategy, ModelTier, RecipeRef


class ScanConfig(BaseModel):
    """Recipe scan configuration."""

    source_types: list[str] = Field(default_factory=list)
    auto_approve: bool = Field(default=False)


class ReadinessConfig(BaseModel):
    """Recipe readiness requirements."""

    require_approval: bool = Field(default=True)
    require_recipe_match: bool = Field(default=True)


class ContextConfig(BaseModel):
    """Recipe context pack preferences."""

    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    max_files: int = Field(default=50, ge=1)
    max_total_size_kb: int = Field(default=500, ge=1)


class ValidationConfig(BaseModel):
    """Recipe validation commands."""

    commands: list[str] = Field(default_factory=list)
    require_all_pass: bool = Field(default=True)


class RetryConfig(BaseModel):
    """Recipe retry settings."""

    max_retries: int = Field(default=2, ge=0)
    backoff_strategy: str = Field(default="fixed")

    @field_validator("backoff_strategy")
    @classmethod
    def validate_backoff_strategy(cls, v: str) -> str:
        """Validate backoff strategy is a known value."""
        allowed = {"fixed", "exponential", "none"}
        if v not in allowed:
            msg = f"backoff_strategy must be one of {allowed}, got '{v}'"
            raise ValueError(msg)
        return v


class PromotionConfig(BaseModel):
    """Recipe promotion requirements."""

    require_evaluation_pass: bool = Field(default=True)
    require_security_review: bool = Field(default=True)
    auto_branch: bool = Field(default=True)
    auto_pr_draft: bool = Field(default=False)


class Recipe(BaseModel):
    """Validated recipe definition loaded from YAML."""

    name: str = Field(..., min_length=1)
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    description: str = Field(default="")
    execution_strategy: ExecutionStrategy = Field(default=ExecutionStrategy.ONE_SHOT)
    tier_overrides: dict[str, str] = Field(default_factory=dict)
    scan: ScanConfig = Field(default_factory=ScanConfig)
    readiness: ReadinessConfig = Field(default_factory=ReadinessConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    promotion: PromotionConfig = Field(default_factory=PromotionConfig)

    @field_validator("tier_overrides")
    @classmethod
    def validate_tier_overrides(cls, v: dict[str, str]) -> dict[str, str]:
        """Validate tier overrides reference valid tier names."""
        valid_tiers = {t.value for t in ModelTier}
        for step, tier in v.items():
            if tier not in valid_tiers:
                msg = f"tier override for '{step}' must be one of {valid_tiers}, got '{tier}'"
                raise ValueError(msg)
        return v


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 content hash for provenance tracking."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def load_recipe_from_yaml(path: Path) -> Recipe:
    """Load and validate a recipe from a YAML file.

    Args:
        path: Path to the YAML recipe file.

    Returns:
        Validated Recipe instance.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the YAML is invalid or doesn't match the schema.
    """
    if not path.exists():
        msg = f"Recipe file not found: {path}"
        raise FileNotFoundError(msg)

    content = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        msg = f"Invalid YAML in recipe file {path}: {e}"
        raise ValueError(msg) from e

    if not isinstance(data, dict):
        msg = f"Recipe file must contain a YAML mapping, got {type(data).__name__}"
        raise ValueError(msg)

    return Recipe(**data)


def load_recipe_from_dict(data: dict[str, Any]) -> Recipe:
    """Load and validate a recipe from a dictionary.

    Args:
        data: Dictionary with recipe fields.

    Returns:
        Validated Recipe instance.
    """
    return Recipe(**data)


class RecipeLoader:
    """Loads recipes from built-in, global, and repo-local directories.

    Precedence: repo-local > global > built-in.
    """

    BUILTINS_DIR = Path(__file__).parent / "builtins"
    GLOBAL_DIR = Path.home() / ".config" / "foxhound" / "recipes"

    def __init__(self, repo_dir: Path | None = None) -> None:
        """Initialize the recipe loader.

        Args:
            repo_dir: Path to the repository root. If provided, repo-local
                recipes from .foxhound/recipes/ will be included.
        """
        self._repo_dir = repo_dir
        self._cache: dict[str, tuple[Recipe, str, str]] = {}

    @property
    def _repo_recipes_dir(self) -> Path | None:
        """Path to repo-local recipes directory."""
        if self._repo_dir is None:
            return None
        return self._repo_dir / ".foxhound" / "recipes"

    def _search_dirs(self) -> list[tuple[Path, str]]:
        """Return search directories in precedence order (lowest first).

        Returns list of (directory, scope) tuples. Later entries override
        earlier ones when recipes share the same name.
        """
        dirs: list[tuple[Path, str]] = [(self.BUILTINS_DIR, "builtin")]
        if self.GLOBAL_DIR.exists():
            dirs.append((self.GLOBAL_DIR, "global"))
        repo_dir = self._repo_recipes_dir
        if repo_dir is not None and repo_dir.exists():
            dirs.append((repo_dir, "repo"))
        return dirs

    def load_all(self) -> dict[str, Recipe]:
        """Load all available recipes with precedence resolution.

        Returns:
            Dictionary mapping recipe names to Recipe instances.
            Repo-local recipes override global, which override built-in.
        """
        recipes: dict[str, Recipe] = {}
        self._cache.clear()

        for search_dir, scope in self._search_dirs():
            for yaml_path in sorted(search_dir.glob("*.yaml")):
                try:
                    recipe = load_recipe_from_yaml(yaml_path)
                    content = yaml_path.read_text(encoding="utf-8")
                    content_hash = compute_content_hash(content)
                    recipes[recipe.name] = recipe
                    self._cache[recipe.name] = (recipe, content_hash, scope)
                except (ValueError, FileNotFoundError):
                    continue

        return recipes

    def load_by_name(self, name: str) -> Recipe | None:
        """Load a single recipe by name with precedence resolution.

        Searches repo-local first, then global, then built-in.

        Args:
            name: Recipe name to search for.

        Returns:
            Recipe if found, None otherwise.
        """
        if not self._cache:
            self.load_all()
        entry = self._cache.get(name)
        return entry[0] if entry else None

    def get_recipe_ref(self, name: str) -> RecipeRef | None:
        """Get a RecipeRef for a loaded recipe.

        Args:
            name: Recipe name.

        Returns:
            RecipeRef with version and content hash, or None if not found.
        """
        if not self._cache:
            self.load_all()
        entry = self._cache.get(name)
        if entry is None:
            return None
        recipe, content_hash, scope = entry
        return RecipeRef(
            name=recipe.name,
            version=recipe.version,
            content_hash=content_hash,
            source_scope=scope,
        )

    def list_available(self) -> list[dict[str, str]]:
        """List all available recipes with metadata.

        Returns:
            List of dicts with name, version, scope, and description.
        """
        if not self._cache:
            self.load_all()
        result = []
        for name, (recipe, _content_hash, scope) in sorted(self._cache.items()):
            result.append({
                "name": name,
                "version": recipe.version,
                "scope": scope,
                "description": recipe.description,
            })
        return result
