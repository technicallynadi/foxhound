"""Policy engine for enforcing deterministic constraints on worker behavior."""

import fnmatch
import hashlib
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from foxhound.core.models import PolicyRef


class PolicyViolationAction(StrEnum):
    """Action to take when a policy violation is detected."""

    BLOCK = "block"
    WARN = "warn"
    REQUIRE_APPROVAL = "require_approval"


class CommandPolicy(BaseModel):
    """Command allowlist and blocklist configuration."""

    allowed: list[str] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list)


class SensitivePathPolicy(BaseModel):
    """Sensitive file and directory blocking rules."""

    blocked_patterns: list[str] = Field(default_factory=list)
    blocked_directories: list[str] = Field(default_factory=list)


class BudgetPolicy(BaseModel):
    """Budget cap configuration."""

    max_budget_per_job: float = Field(default=5.0, ge=0.0)
    max_budget_per_run: float = Field(default=2.0, ge=0.0)
    warn_threshold: float = Field(default=0.8, ge=0.0, le=1.0)


class TimeoutPolicy(BaseModel):
    """Timeout limit configuration."""

    max_timeout_seconds: int = Field(default=1800, ge=0)
    default_timeout_seconds: int = Field(default=300, ge=0)


class ApprovalPolicy(BaseModel):
    """Approval requirements for high-risk actions."""

    require_for_install_scripts: bool = Field(default=True)
    require_for_network_access: bool = Field(default=True)
    require_for_shell_commands: bool = Field(default=True)


class PromotionPolicy(BaseModel):
    """Promotion requirements for completed work."""

    require_evaluation_pass: bool = Field(default=True)
    require_security_review: bool = Field(default=True)
    require_clean_validation: bool = Field(default=True)


class Policy(BaseModel):
    """Validated policy pack definition loaded from YAML."""

    name: str = Field(..., min_length=1)
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    description: str = Field(default="")
    commands: CommandPolicy = Field(default_factory=CommandPolicy)
    sensitive_paths: SensitivePathPolicy = Field(default_factory=SensitivePathPolicy)
    budget: BudgetPolicy = Field(default_factory=BudgetPolicy)
    timeout: TimeoutPolicy = Field(default_factory=TimeoutPolicy)
    approval: ApprovalPolicy = Field(default_factory=ApprovalPolicy)
    promotion: PromotionPolicy = Field(default_factory=PromotionPolicy)

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        """Validate semantic version format."""
        return v


class PolicyViolation(BaseModel):
    """Record of a policy violation."""

    policy_name: str
    area: str
    action: PolicyViolationAction
    description: str
    details: dict[str, Any] = Field(default_factory=dict)


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 content hash for provenance tracking."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def load_policy_from_yaml(path: Path) -> Policy:
    """Load and validate a policy from a YAML file.

    Args:
        path: Path to the YAML policy file.

    Returns:
        Validated Policy instance.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the YAML is invalid or doesn't match the schema.
    """
    if not path.exists():
        msg = f"Policy file not found: {path}"
        raise FileNotFoundError(msg)

    content = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        msg = f"Invalid YAML in policy file {path}: {e}"
        raise ValueError(msg) from e

    if not isinstance(data, dict):
        msg = f"Policy file must contain a YAML mapping, got {type(data).__name__}"
        raise ValueError(msg)

    return Policy(**data)


class PolicyEngine:
    """Loads and enforces policy packs.

    Precedence: repo-local > global > built-in.
    """

    BUILTINS_DIR = Path(__file__).parent / "builtins"
    GLOBAL_DIR = Path.home() / ".config" / "foxhound" / "policies"

    def __init__(self, repo_dir: Path | None = None) -> None:
        """Initialize the policy engine.

        Args:
            repo_dir: Path to the repository root. If provided, repo-local
                policies from .foxhound/policies/ will be included.
        """
        self._repo_dir = repo_dir
        self._cache: dict[str, tuple[Policy, str, str]] = {}
        self._active_policy: Policy | None = None

    @property
    def _repo_policies_dir(self) -> Path | None:
        """Path to repo-local policies directory."""
        if self._repo_dir is None:
            return None
        return self._repo_dir / ".foxhound" / "policies"

    def _search_dirs(self) -> list[tuple[Path, str]]:
        """Return search directories in precedence order (lowest first)."""
        dirs: list[tuple[Path, str]] = [(self.BUILTINS_DIR, "builtin")]
        if self.GLOBAL_DIR.exists():
            dirs.append((self.GLOBAL_DIR, "global"))
        repo_dir = self._repo_policies_dir
        if repo_dir is not None and repo_dir.exists():
            dirs.append((repo_dir, "repo"))
        return dirs

    def load_all(self) -> dict[str, Policy]:
        """Load all available policies with precedence resolution.

        Returns:
            Dictionary mapping policy names to Policy instances.
        """
        policies: dict[str, Policy] = {}
        self._cache.clear()

        for search_dir, scope in self._search_dirs():
            for yaml_path in sorted(search_dir.glob("*.yaml")):
                try:
                    policy = load_policy_from_yaml(yaml_path)
                    content = yaml_path.read_text(encoding="utf-8")
                    content_hash = compute_content_hash(content)
                    policies[policy.name] = policy
                    self._cache[policy.name] = (policy, content_hash, scope)
                except (ValueError, FileNotFoundError):
                    continue

        return policies

    def load_by_name(self, name: str) -> Policy | None:
        """Load a single policy by name with precedence resolution."""
        if not self._cache:
            self.load_all()
        entry = self._cache.get(name)
        return entry[0] if entry else None

    def get_policy_ref(self, name: str) -> PolicyRef | None:
        """Get a PolicyRef for a loaded policy."""
        if not self._cache:
            self.load_all()
        entry = self._cache.get(name)
        if entry is None:
            return None
        policy, content_hash, scope = entry
        return PolicyRef(
            name=policy.name,
            version=policy.version,
            content_hash=content_hash,
            source_scope=scope,
        )

    def set_active_policy(self, name: str) -> bool:
        """Set the active policy for enforcement.

        Args:
            name: Policy name to activate.

        Returns:
            True if the policy was found and activated.
        """
        policy = self.load_by_name(name)
        if policy is None:
            return False
        self._active_policy = policy
        return True

    @property
    def active_policy(self) -> Policy | None:
        """Get the currently active policy."""
        return self._active_policy

    def check_command(self, command: str) -> PolicyViolation | None:
        """Check if a command is allowed by the active policy.

        Args:
            command: Command string to check.

        Returns:
            PolicyViolation if blocked, None if allowed.
        """
        if self._active_policy is None:
            return None

        cmd_policy = self._active_policy.commands

        for blocked in cmd_policy.blocked:
            if command.startswith(blocked) or command == blocked:
                return PolicyViolation(
                    policy_name=self._active_policy.name,
                    area="commands",
                    action=PolicyViolationAction.BLOCK,
                    description=f"Command blocked by policy: '{command}'",
                    details={"command": command, "matched_rule": blocked},
                )

        if cmd_policy.allowed:
            is_allowed = any(
                command.startswith(allowed) or command == allowed
                for allowed in cmd_policy.allowed
            )
            if not is_allowed:
                return PolicyViolation(
                    policy_name=self._active_policy.name,
                    area="commands",
                    action=PolicyViolationAction.BLOCK,
                    description=f"Command not in allowlist: '{command}'",
                    details={"command": command},
                )

        return None

    def check_path(self, path: str) -> PolicyViolation | None:
        """Check if a file path is blocked by sensitive path rules.

        Args:
            path: File path to check.

        Returns:
            PolicyViolation if blocked, None if allowed.
        """
        if self._active_policy is None:
            return None

        path_policy = self._active_policy.sensitive_paths
        filename = Path(path).name

        for pattern in path_policy.blocked_patterns:
            if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(path, pattern):
                return PolicyViolation(
                    policy_name=self._active_policy.name,
                    area="sensitive_paths",
                    action=PolicyViolationAction.BLOCK,
                    description=f"Path blocked by sensitive path rule: '{path}'",
                    details={"path": path, "matched_pattern": pattern},
                )

        for blocked_dir in path_policy.blocked_directories:
            normalized_dir = blocked_dir.rstrip("/")
            if f"/{normalized_dir}/" in f"/{path}/" or path.startswith(normalized_dir):
                return PolicyViolation(
                    policy_name=self._active_policy.name,
                    area="sensitive_paths",
                    action=PolicyViolationAction.BLOCK,
                    description=f"Path in blocked directory: '{path}'",
                    details={"path": path, "matched_directory": blocked_dir},
                )

        return None

    def check_budget(self, requested: float, budget_type: str = "run") -> PolicyViolation | None:
        """Check if a budget request exceeds policy caps.

        Args:
            requested: Requested budget amount.
            budget_type: Either 'job' or 'run'.

        Returns:
            PolicyViolation if exceeded, None if within limits.
        """
        if self._active_policy is None:
            return None

        budget_policy = self._active_policy.budget
        if budget_type == "job":
            cap = budget_policy.max_budget_per_job
        else:
            cap = budget_policy.max_budget_per_run

        if requested > cap:
            return PolicyViolation(
                policy_name=self._active_policy.name,
                area="budget",
                action=PolicyViolationAction.BLOCK,
                description=f"Budget {requested} exceeds {budget_type} cap of {cap}",
                details={"requested": requested, "cap": cap, "budget_type": budget_type},
            )

        return None

    def check_timeout(self, requested: int) -> PolicyViolation | None:
        """Check if a timeout request exceeds policy limits.

        Args:
            requested: Requested timeout in seconds.

        Returns:
            PolicyViolation if exceeded, None if within limits.
        """
        if self._active_policy is None:
            return None

        max_timeout = self._active_policy.timeout.max_timeout_seconds
        if requested > max_timeout:
            return PolicyViolation(
                policy_name=self._active_policy.name,
                area="timeout",
                action=PolicyViolationAction.BLOCK,
                description=f"Timeout {requested}s exceeds max of {max_timeout}s",
                details={"requested": requested, "max": max_timeout},
            )

        return None

    def check_all(
        self,
        command: str | None = None,
        paths: list[str] | None = None,
        budget: float | None = None,
        budget_type: str = "run",
        timeout: int | None = None,
    ) -> list[PolicyViolation]:
        """Run all applicable policy checks.

        Args:
            command: Command to check.
            paths: List of file paths to check.
            budget: Budget amount to check.
            budget_type: Budget type ('job' or 'run').
            timeout: Timeout in seconds to check.

        Returns:
            List of policy violations found.
        """
        violations: list[PolicyViolation] = []

        if command is not None:
            v = self.check_command(command)
            if v:
                violations.append(v)

        if paths is not None:
            for path in paths:
                v = self.check_path(path)
                if v:
                    violations.append(v)

        if budget is not None:
            v = self.check_budget(budget, budget_type)
            if v:
                violations.append(v)

        if timeout is not None:
            v = self.check_timeout(timeout)
            if v:
                violations.append(v)

        return violations

    def list_available(self) -> list[dict[str, str]]:
        """List all available policies with metadata."""
        if not self._cache:
            self.load_all()
        result = []
        for name, (policy, _hash, scope) in sorted(self._cache.items()):
            result.append({
                "name": name,
                "version": policy.version,
                "scope": scope,
                "description": policy.description,
            })
        return result
