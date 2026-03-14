"""Context pack assembly for execution workers.

Builds structured task briefs for LLM execution by assembling approved
work items, relevant files, tests, constraints, and trust labels into
a context pack. Sensitive files are excluded and all content is labeled
with its trust tier.
"""

import fnmatch
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from foxhound.core.models import TrustLevel, WorkItem
from foxhound.recipes.loader import Recipe

SENSITIVE_PATTERNS: list[str] = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_ed25519",
    "id_dsa",
    "*.keystore",
    "credentials.json",
    "service_account.json",
    "secrets.yaml",
    "secrets.yml",
    "secrets.json",
    ".secrets",
    ".htpasswd",
    "token.json",
]

SENSITIVE_DIRS: list[str] = [
    "secrets",
    ".secrets",
    ".ssh",
    ".gnupg",
    "private",
]

DEFAULT_EXCLUDE_PATTERNS: list[str] = [
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/.git/**",
    "**/.venv/**",
    "**/venv/**",
    "**/.tox/**",
    "**/dist/**",
    "**/build/**",
    "**/*.egg-info/**",
]

MAX_FILE_SIZE_BYTES = 100_000
MAX_CONTEXT_FILES = 100
MAX_CONTEXT_SIZE_KB = 1000


class ContextPackFile(BaseModel):
    """A file included in a context pack with trust metadata."""

    path: str = Field(..., description="Relative file path")
    content: str = Field(..., description="File content")
    trust_level: TrustLevel = Field(
        default=TrustLevel.SEMI_TRUSTED, description="Trust classification"
    )
    size_bytes: int = Field(default=0, description="File size in bytes")


class ContextPack(BaseModel):
    """Structured task brief for a single execution run."""

    work_item_id: str = Field(..., description="Approved work item ID")
    work_item_title: str = Field(..., description="Work item title")
    work_item_description: str = Field(default="", description="Work item description")
    evidence: dict[str, Any] = Field(
        default_factory=dict, description="Evidence from work item"
    )
    recipe_name: str = Field(default="", description="Recipe governing execution")
    recipe_instructions: dict[str, Any] = Field(
        default_factory=dict, description="Recipe configuration snapshot"
    )
    policy_constraints: dict[str, Any] = Field(
        default_factory=dict, description="Policy constraints for execution"
    )
    files: list[ContextPackFile] = Field(
        default_factory=list, description="Included files with trust labels"
    )
    trust_labels: dict[str, str] = Field(
        default_factory=dict, description="Trust level for each content source"
    )
    context_hash: str = Field(default="", description="Hash of assembled context")
    total_size_kb: float = Field(default=0.0, description="Total context size in KB")
    warnings: list[str] = Field(
        default_factory=list, description="Warnings generated during assembly"
    )


def _is_sensitive_file(rel_path: str) -> bool:
    """Check if a relative file path matches sensitive patterns or dirs."""
    path = Path(rel_path)
    name = path.name
    for pattern in SENSITIVE_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True

    for part in path.parts:
        if part.lower() in SENSITIVE_DIRS:
            return True

    return False


def _matches_patterns(path_str: str, patterns: list[str]) -> bool:
    """Check if a path matches any of the given glob patterns."""
    from pathlib import PurePosixPath

    path = PurePosixPath(path_str)
    for pattern in patterns:
        if path.full_match(pattern):
            return True
    return False


def _compute_context_hash(pack: ContextPack) -> str:
    """Compute a SHA-256 hash of the context pack for provenance."""
    hasher = hashlib.sha256()
    hasher.update(pack.work_item_id.encode())
    hasher.update(pack.recipe_name.encode())
    for f in pack.files:
        hasher.update(f.path.encode())
        hasher.update(f.content.encode())
    return hasher.hexdigest()[:16]


class ContextAssembler:
    """Assembles context packs for execution from work items and repo files.

    Uses deterministic heuristics to select relevant files based on recipe
    include/exclude patterns and the work item's likely affected files.
    Excludes sensitive files and labels all content with trust tiers.
    """

    def __init__(self, repo_path: Path) -> None:
        self._repo_path = repo_path

    def assemble(
        self,
        work_item: WorkItem,
        recipe: Recipe | None = None,
        policy_constraints: dict[str, Any] | None = None,
    ) -> ContextPack:
        """Assemble a context pack for a work item.

        Args:
            work_item: The approved work item to build context for.
            recipe: Optional recipe governing execution.
            policy_constraints: Optional policy constraints.

        Returns:
            A ContextPack with files, trust labels, and metadata.
        """
        include_patterns = recipe.context.include_patterns if recipe else ["**/*.py"]
        exclude_patterns = (
            recipe.context.exclude_patterns if recipe else []
        ) + DEFAULT_EXCLUDE_PATTERNS
        max_files = recipe.context.max_files if recipe else MAX_CONTEXT_FILES
        max_size_kb = recipe.context.max_total_size_kb if recipe else MAX_CONTEXT_SIZE_KB

        files = self._select_files(
            work_item=work_item,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            max_files=max_files,
            max_size_kb=max_size_kb,
        )

        trust_labels: dict[str, str] = {
            "work_item": TrustLevel.TRUSTED.value,
            "recipe": TrustLevel.TRUSTED.value,
            "policy": TrustLevel.TRUSTED.value,
        }
        for f in files:
            trust_labels[f"file:{f.path}"] = f.trust_level.value

        recipe_instructions: dict[str, Any] = {}
        if recipe:
            recipe_instructions = {
                "execution_strategy": recipe.execution_strategy.value,
                "validation_commands": recipe.validation.commands,
                "require_all_pass": recipe.validation.require_all_pass,
                "max_retries": recipe.retry.max_retries,
                "tier_overrides": recipe.tier_overrides,
            }

        total_size = sum(f.size_bytes for f in files)

        warnings: list[str] = []
        if total_size > max_size_kb * 1024:
            warnings.append(
                f"Context size ({total_size // 1024}KB) exceeds limit ({max_size_kb}KB)"
            )
        if len(files) >= max_files:
            warnings.append(
                f"File count ({len(files)}) reached limit ({max_files})"
            )

        pack = ContextPack(
            work_item_id=work_item.work_item_id,
            work_item_title=work_item.title,
            work_item_description=work_item.description,
            evidence=work_item.evidence,
            recipe_name=recipe.name if recipe else "",
            recipe_instructions=recipe_instructions,
            policy_constraints=policy_constraints or {},
            files=files,
            trust_labels=trust_labels,
            total_size_kb=round(total_size / 1024, 2),
            warnings=warnings,
        )
        pack.context_hash = _compute_context_hash(pack)
        return pack

    def _select_files(
        self,
        work_item: WorkItem,
        include_patterns: list[str],
        exclude_patterns: list[str],
        max_files: int,
        max_size_kb: int,
    ) -> list[ContextPackFile]:
        """Select relevant files using deterministic heuristics.

        Priority order:
        1. Files named in work_item.likely_files
        2. Files matching recipe include patterns
        """
        selected: dict[str, ContextPackFile] = {}
        total_bytes = 0
        max_bytes = max_size_kb * 1024

        for rel_path in work_item.likely_files:
            if len(selected) >= max_files or total_bytes >= max_bytes:
                break
            full_path = self._repo_path / rel_path
            cpf = self._try_read_file(full_path, rel_path, exclude_patterns)
            if cpf and total_bytes + cpf.size_bytes <= max_bytes:
                selected[rel_path] = cpf
                total_bytes += cpf.size_bytes

        for pattern in include_patterns:
            if len(selected) >= max_files or total_bytes >= max_bytes:
                break
            for full_path in sorted(self._repo_path.glob(pattern)):
                if len(selected) >= max_files or total_bytes >= max_bytes:
                    break
                if not full_path.is_file():
                    continue
                rel_path = str(full_path.relative_to(self._repo_path))
                if rel_path in selected:
                    continue
                cpf = self._try_read_file(full_path, rel_path, exclude_patterns)
                if cpf and total_bytes + cpf.size_bytes <= max_bytes:
                    selected[rel_path] = cpf
                    total_bytes += cpf.size_bytes

        return list(selected.values())

    def _try_read_file(
        self,
        full_path: Path,
        rel_path: str,
        exclude_patterns: list[str],
    ) -> ContextPackFile | None:
        """Try to read a file, applying exclusion and sensitivity checks."""
        if not full_path.exists() or not full_path.is_file():
            return None

        if _is_sensitive_file(rel_path):
            return None

        if _matches_patterns(rel_path, exclude_patterns):
            return None

        try:
            stat = full_path.stat()
        except OSError:
            return None

        if stat.st_size > MAX_FILE_SIZE_BYTES:
            return None
        if stat.st_size == 0:
            return None

        try:
            content = full_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return None

        return ContextPackFile(
            path=rel_path,
            content=content,
            trust_level=TrustLevel.SEMI_TRUSTED,
            size_bytes=len(content.encode("utf-8")),
        )


def save_context_pack(pack: ContextPack, artifacts_dir: Path) -> Path:
    """Save a context pack to the artifacts directory as JSON.

    Args:
        pack: The context pack to save.
        artifacts_dir: Path to .foxhound/artifacts/.

    Returns:
        Path to the saved context pack file.
    """
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    filename = f"context_pack_{pack.work_item_id}_{pack.context_hash}.json"
    filepath = artifacts_dir / filename

    pack_dict = pack.model_dump()
    for f in pack_dict.get("files", []):
        f.pop("content", None)

    filepath.write_text(
        json.dumps(pack_dict, indent=2, default=str),
        encoding="utf-8",
    )
    return filepath
