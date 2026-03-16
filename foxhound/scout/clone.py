"""Safe repository cloning for approved scout opportunities.

Handles cloning external repositories discovered by scout connectors.
All cloned repos are treated as UNTRUSTED content — they are evidence
for analysis, never execution control. Users must review before any
code execution occurs.
"""

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)

# Git URL patterns we accept (HTTPS and SSH only, no local paths)
_HTTPS_PATTERN = re.compile(
    r"^https://(?:github\.com|gitlab\.com|bitbucket\.org)/[\w.\-]+/[\w.\-]+(?:\.git)?$"
)
_SSH_PATTERN = re.compile(
    r"^git@(?:github\.com|gitlab\.com|bitbucket\.org):[\w.\-]+/[\w.\-]+(?:\.git)?$"
)

# Maximum clone size (shallow clone, but still guard against abuse)
MAX_CLONE_TIMEOUT_SECONDS = 120

# Dangerous paths that should never exist in a cloned repo
DANGEROUS_PATHS = {
    ".github/workflows",
    ".gitlab-ci.yml",
    "Makefile",
    "setup.py",
    "setup.cfg",
    "pyproject.toml",
}


class CloneStatus(StrEnum):
    """Status of a clone operation."""

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    CLONED = "cloned"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass
class CloneRequest:
    """A request to clone an external repository."""

    opportunity_id: str
    source_url: str
    repo_name: str
    status: CloneStatus = CloneStatus.PENDING_REVIEW
    clone_path: Path | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class CloneConfig:
    """Configuration for the clone manager."""

    clone_dir: Path = Path(".foxhound/cloned")
    shallow_clone: bool = True
    auto_add_to_targets: bool = False
    max_repo_size_mb: int = 500
    allowed_hosts: list[str] = field(
        default_factory=lambda: ["github.com", "gitlab.com", "bitbucket.org"]
    )


# Safety disclaimers shown to the user before cloning
SAFETY_DISCLAIMERS = [
    "This repository is UNTRUSTED external code discovered by scout.",
    "Cloning downloads code to your machine but does NOT execute it.",
    "Do NOT run any scripts, install commands, or build steps from "
    "this repo without manual review.",
    "Foxhound will scan the cloned repo for analysis only. No code "
    "from this repo will be executed automatically.",
    "You are responsible for reviewing the code before any manual execution.",
]

# Risk warnings for specific dangerous patterns found in the repo
RISK_WARNINGS = {
    ".github/workflows": (
        "Contains GitHub Actions workflows — these could run "
        "arbitrary code if triggered."
    ),
    ".gitlab-ci.yml": (
        "Contains GitLab CI config — do not push this repo to "
        "a GitLab instance without review."
    ),
    "Makefile": (
        "Contains a Makefile — do not run 'make' without "
        "reviewing the targets."
    ),
    "setup.py": (
        "Contains setup.py — running 'pip install' on this repo "
        "can execute arbitrary code."
    ),
    "setup.cfg": (
        "Contains setup.cfg — may define install hooks that "
        "execute code."
    ),
    "pyproject.toml": (
        "Contains pyproject.toml — build backends can execute "
        "arbitrary code during install."
    ),
}


def validate_clone_url(url: str, config: CloneConfig) -> tuple[bool, str]:
    """Validate that a URL is safe to clone.

    Returns:
        Tuple of (is_valid, reason).
    """
    if not url:
        return False, "Empty URL"

    if _HTTPS_PATTERN.match(url):
        host = url.split("/")[2]
        if host not in config.allowed_hosts:
            return False, f"Host '{host}' not in allowed hosts"
        return True, "Valid HTTPS URL"

    if _SSH_PATTERN.match(url):
        host = url.split("@")[1].split(":")[0]
        if host not in config.allowed_hosts:
            return False, f"Host '{host}' not in allowed hosts"
        return True, "Valid SSH URL"

    return False, f"URL does not match allowed patterns (HTTPS or SSH to {config.allowed_hosts})"


def extract_repo_name(url: str) -> str:
    """Extract repository name from a git URL.

    Raises:
        ValueError: If the extracted name is a path traversal component.
    """
    name = url.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    if not name or name in (".", "..") or "/" in name:
        raise ValueError(f"Invalid repository name extracted from URL: {name!r}")
    return name


def scan_for_risks(clone_path: Path) -> list[str]:
    """Scan a cloned repo for dangerous patterns and return warnings."""
    warnings: list[str] = []

    for dangerous_path, warning in RISK_WARNINGS.items():
        check = clone_path / dangerous_path
        if check.exists():
            warnings.append(warning)

    hook_dir = clone_path / ".git" / "hooks"
    if hook_dir.exists():
        active_hooks = [
            h for h in hook_dir.iterdir()
            if h.is_file() and not h.name.endswith(".sample")
        ]
        if active_hooks:
            hook_names = ", ".join(h.name for h in active_hooks)
            warnings.append(
                f"Contains active git hooks ({hook_names}) — these "
                f"could execute code on git operations."
            )

    return warnings


class CloneManager:
    """Manages safe cloning of external repositories.

    All cloned repos are untrusted. The manager enforces URL validation,
    shallow cloning, risk scanning, and user review before any repo
    is available for further processing.
    """

    def __init__(self, config: CloneConfig | None = None) -> None:
        self._config = config or CloneConfig()

    @property
    def config(self) -> CloneConfig:
        """Get the clone configuration."""
        return self._config

    def prepare_clone(
        self,
        opportunity_id: str,
        source_url: str,
    ) -> CloneRequest:
        """Validate a URL and prepare a clone request for user review.

        Does NOT clone yet — returns a CloneRequest in PENDING_REVIEW
        state with safety disclaimers and any pre-clone warnings.
        """
        try:
            repo_name = extract_repo_name(source_url)
        except ValueError as exc:
            return CloneRequest(
                opportunity_id=opportunity_id,
                source_url=source_url,
                repo_name="",
                status=CloneStatus.FAILED,
                error=str(exc),
            )

        request = CloneRequest(
            opportunity_id=opportunity_id,
            source_url=source_url,
            repo_name=repo_name,
        )

        valid, reason = validate_clone_url(source_url, self._config)
        if not valid:
            request.status = CloneStatus.FAILED
            request.error = f"URL validation failed: {reason}"
            return request

        target_path = (self._config.clone_dir / repo_name).resolve()
        clone_dir_resolved = self._config.clone_dir.resolve()

        if not str(target_path).startswith(str(clone_dir_resolved) + "/"):
            request.status = CloneStatus.FAILED
            request.error = "Path traversal detected in repository name"
            return request

        if target_path.exists():
            request.status = CloneStatus.FAILED
            request.error = (
                f"Directory already exists: {target_path}. "
                f"Remove it first or use a different clone_dir."
            )
            return request

        request.clone_path = target_path
        request.status = CloneStatus.PENDING_REVIEW
        return request

    def get_review_summary(self, request: CloneRequest) -> dict[str, object]:
        """Build a review summary for the user to approve/reject.

        Returns a dict suitable for rendering in the TUI.
        """
        return {
            "opportunity_id": request.opportunity_id,
            "source_url": request.source_url,
            "repo_name": request.repo_name,
            "clone_path": str(request.clone_path) if request.clone_path else None,
            "status": request.status.value,
            "disclaimers": SAFETY_DISCLAIMERS,
            "shallow_clone": self._config.shallow_clone,
            "warnings": request.warnings,
            "error": request.error,
        }

    def execute_clone(self, request: CloneRequest) -> CloneRequest:
        """Execute the clone after user approval.

        The request must be in APPROVED state. Performs a shallow clone,
        scans for risks, and updates the request with warnings.

        Raises:
            ValueError: If the request is not in APPROVED state.
        """
        if request.status != CloneStatus.APPROVED:
            raise ValueError(
                f"Cannot clone: request is '{request.status.value}', "
                f"must be 'approved'. User must review and approve first."
            )

        if request.clone_path is None:
            request.status = CloneStatus.FAILED
            request.error = "No clone path set"
            return request

        request.clone_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = ["git", "clone"]
        if self._config.shallow_clone:
            cmd.extend(["--depth", "1"])
        cmd.extend([request.source_url, str(request.clone_path)])

        try:
            logger.info(
                "Cloning %s into %s", request.source_url, request.clone_path
            )
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=MAX_CLONE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            request.status = CloneStatus.FAILED
            request.error = (
                f"Clone timed out after {MAX_CLONE_TIMEOUT_SECONDS}s — "
                f"repo may be too large"
            )
            return request
        except subprocess.CalledProcessError as exc:
            request.status = CloneStatus.FAILED
            request.error = f"Git clone failed: {exc.stderr.strip()}"
            return request

        # Post-clone risk scan
        request.warnings = scan_for_risks(request.clone_path)
        request.status = CloneStatus.CLONED

        if request.warnings:
            logger.warning(
                "Risk warnings for %s: %s",
                request.repo_name,
                "; ".join(request.warnings),
            )

        return request

    def remove_clone(self, clone_path: Path) -> bool:
        """Remove a cloned repository."""
        if not clone_path.exists():
            return False

        resolved = clone_path.resolve()
        clone_dir_resolved = self._config.clone_dir.resolve()
        if not str(resolved).startswith(str(clone_dir_resolved) + "/"):
            raise ValueError(
                f"Refusing to remove {clone_path} — resolves outside "
                f"managed clone directory {self._config.clone_dir}"
            )

        shutil.rmtree(clone_path)
        logger.info("Removed cloned repo: %s", clone_path)
        return True
