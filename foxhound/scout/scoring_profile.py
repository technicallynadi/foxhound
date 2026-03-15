"""Scoring profile loader and model.

Scoring profiles define user-configurable criteria that the LLM uses
when evaluating scout opportunities. Profiles live in .foxhound/scoring/
and are loaded by name.
"""

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

BUILTIN_PROFILES_DIR = Path(__file__).parent / "profiles"
DEFAULT_PROFILE_NAME = "default"


class CriteriaBlock(BaseModel):
    """Scoring criteria for a single metric."""

    rules: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class ScoringProfile(BaseModel):
    """User-configurable scoring profile for LLM-based opportunity evaluation."""

    name: str = Field(..., description="Profile identifier")
    description: str = Field(default="", description="What this profile optimizes for")

    criteria: dict[str, CriteriaBlock] = Field(
        default_factory=lambda: {
            "velocity": CriteriaBlock(),
            "improvability": CriteriaBlock(),
            "buildability": CriteriaBlock(),
            "value": CriteriaBlock(),
        },
        description="Per-metric scoring criteria for the LLM",
    )

    filters: dict[str, Any] = Field(
        default_factory=dict,
        description="Hard filters applied before LLM scoring",
    )

    model_config = {"extra": "forbid"}

    def to_prompt_block(self) -> str:
        """Render this profile as an instruction block for the LLM scoring prompt."""
        lines = [f"Scoring Profile: {self.name}"]
        if self.description:
            lines.append(f"Focus: {self.description}")
        lines.append("")

        for metric, block in self.criteria.items():
            if not block.rules:
                continue
            lines.append(f"## {metric.title()}")
            for rule in block.rules:
                lines.append(f"- {rule}")
            lines.append("")

        if self.filters:
            lines.append("## Filters")
            for key, val in self.filters.items():
                lines.append(f"- {key}: {val}")

        return "\n".join(lines)


def _default_profile() -> ScoringProfile:
    """Return the built-in default scoring profile."""
    return ScoringProfile(
        name="default",
        description="General-purpose opportunity scoring",
        criteria={
            "velocity": CriteriaBlock(rules=[
                "High if the project is trending in the last 48 hours",
                "Boost if growth is accelerating, not just high absolute numbers",
                "Consider comment/discussion volume as a signal of interest",
            ]),
            "improvability": CriteriaBlock(rules=[
                "High if documentation is thin or missing",
                "High if there are open issues labeled good-first-issue or help-wanted",
                "Low if the project already has many active contributors",
            ]),
            "buildability": CriteriaBlock(rules=[
                "High if the project has a permissive license (MIT, Apache-2.0, BSD)",
                "Boost if the project uses a well-known language and framework",
                "Low if the project has complex build requirements or dependencies",
            ]),
            "value": CriteriaBlock(rules=[
                "High if the project solves a real developer pain point",
                "Boost if the project is in an underserved niche",
                "Low if the space is already crowded with similar tools",
            ]),
        },
    )


def load_profile(
    name: str = DEFAULT_PROFILE_NAME,
    foxhound_dir: Path | None = None,
) -> ScoringProfile:
    """Load a scoring profile by name.

    Search order:
    1. .foxhound/scoring/{name}.yaml (repo-local)
    2. Built-in profiles directory
    3. Fall back to default profile
    """
    if foxhound_dir:
        repo_path = foxhound_dir / "scoring" / f"{name}.yaml"
        if repo_path.exists():
            return _load_from_file(repo_path)

    builtin_path = BUILTIN_PROFILES_DIR / f"{name}.yaml"
    if builtin_path.exists():
        return _load_from_file(builtin_path)

    if name != DEFAULT_PROFILE_NAME:
        logger.warning("Profile '%s' not found, falling back to default", name)

    return _default_profile()


def list_profiles(foxhound_dir: Path | None = None) -> list[str]:
    """List available scoring profile names."""
    names: set[str] = {"default"}

    if foxhound_dir:
        scoring_dir = foxhound_dir / "scoring"
        if scoring_dir.exists():
            for f in scoring_dir.glob("*.yaml"):
                names.add(f.stem)

    if BUILTIN_PROFILES_DIR.exists():
        for f in BUILTIN_PROFILES_DIR.glob("*.yaml"):
            names.add(f.stem)

    return sorted(names)


def _load_from_file(path: Path) -> ScoringProfile:
    """Parse a scoring profile YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    criteria = {}
    for metric, rules_data in data.get("criteria", {}).items():
        if isinstance(rules_data, list):
            criteria[metric] = CriteriaBlock(rules=rules_data)
        elif isinstance(rules_data, dict):
            criteria[metric] = CriteriaBlock(rules=rules_data.get("rules", []))

    return ScoringProfile(
        name=data.get("name", path.stem),
        description=data.get("description", ""),
        criteria=criteria,
        filters=data.get("filters", {}),
    )
