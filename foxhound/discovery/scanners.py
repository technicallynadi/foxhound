"""Discovery scanners for repo-native work discovery.

Scanners inspect repository files to find actionable work items like
TODO comments, dependency vulnerabilities, and other improvement
opportunities. All scanner output is semi-trusted.
"""

import hashlib
import re
from pathlib import Path
from typing import Any, Protocol

from foxhound.core.models import RiskLevel, TrustLevel, WorkItem, WorkItemKind, WorkItemState


class ScanResult:
    """Raw result from a single scanner finding."""

    def __init__(
        self,
        *,
        source_type: str,
        title: str,
        description: str,
        file_path: str,
        line_number: int | None = None,
        evidence: dict[str, Any],
        confidence: float = 0.5,
        risk: RiskLevel = RiskLevel.LOW,
        recipe_name: str | None = None,
    ) -> None:
        self.source_type = source_type
        self.title = title
        self.description = description
        self.file_path = file_path
        self.line_number = line_number
        self.evidence = evidence
        self.confidence = confidence
        self.risk = risk
        self.recipe_name = recipe_name

    @property
    def fingerprint(self) -> str:
        """Deterministic hash for dedup based on source type, file, and content."""
        content = f"{self.source_type}:{self.file_path}:{self.title}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class Scanner(Protocol):
    """Protocol for discovery scanners."""

    scanner_name: str

    def scan(self, repo_path: Path) -> list[ScanResult]:
        """Scan a repository and return findings."""
        ...


# Default file patterns to scan
SOURCE_PATTERNS = [
    "**/*.py", "**/*.js", "**/*.ts", "**/*.tsx", "**/*.jsx",
    "**/*.rs", "**/*.go", "**/*.java", "**/*.rb", "**/*.c",
    "**/*.cpp", "**/*.h", "**/*.hpp", "**/*.cs", "**/*.swift",
    "**/*.kt", "**/*.sh", "**/*.yaml", "**/*.yml",
]

# Directories to skip
SKIP_DIRS = {
    ".git", ".foxhound", "node_modules", "__pycache__", ".venv",
    "venv", ".tox", ".mypy_cache", ".pytest_cache", "dist",
    "build", ".eggs", "*.egg-info",
}

# TODO pattern: matches TODO, FIXME, HACK, XXX in # or // comments
TODO_PATTERN = re.compile(
    r"(?:#|//)\s*(TODO|FIXME|HACK|XXX)\b[:\s]*(.*)",
    re.IGNORECASE,
)

# Priority mapping for tag types
TAG_RISK: dict[str, RiskLevel] = {
    "fixme": RiskLevel.MEDIUM,
    "hack": RiskLevel.MEDIUM,
    "xxx": RiskLevel.HIGH,
    "todo": RiskLevel.LOW,
}

TAG_CONFIDENCE: dict[str, float] = {
    "fixme": 0.7,
    "hack": 0.6,
    "xxx": 0.8,
    "todo": 0.5,
}


def _should_skip(path: Path) -> bool:
    """Check if a path should be skipped during scanning."""
    for part in path.parts:
        if part in SKIP_DIRS or part.endswith(".egg-info"):
            return True
    return False


class TodoScanner:
    """Scans source files for TODO, FIXME, HACK, and XXX comments."""

    scanner_name = "todo_scanner"

    def scan(self, repo_path: Path) -> list[ScanResult]:
        """Scan repository for TODO-style comments."""
        results: list[ScanResult] = []

        for pattern in SOURCE_PATTERNS:
            for file_path in repo_path.glob(pattern):
                if _should_skip(file_path.relative_to(repo_path)):
                    continue
                if not file_path.is_file():
                    continue
                results.extend(self._scan_file(file_path, repo_path))

        return results

    def _scan_file(self, file_path: Path, repo_path: Path) -> list[ScanResult]:
        """Scan a single file for TODO-style comments."""
        results: list[ScanResult] = []
        relative = str(file_path.relative_to(repo_path))

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            return results

        for line_num, line in enumerate(content.splitlines(), start=1):
            match = TODO_PATTERN.search(line)
            if match:
                tag = match.group(1).lower()
                message = match.group(2).strip()
                if not message:
                    message = f"{tag.upper()} found"

                results.append(ScanResult(
                    source_type=f"todo_{tag}",
                    title=f"[{tag.upper()}] {message[:80]}",
                    description=f"{tag.upper()} comment in {relative}:{line_num}: {message}",
                    file_path=relative,
                    line_number=line_num,
                    evidence={
                        "tag": tag,
                        "message": message,
                        "line": line.strip(),
                        "file": relative,
                        "line_number": line_num,
                    },
                    confidence=TAG_CONFIDENCE.get(tag, 0.5),
                    risk=TAG_RISK.get(tag, RiskLevel.LOW),
                ))

        return results


# Patterns for known vulnerable dependency indicators in requirements files
VULN_PATTERN = re.compile(
    r"^(\S+)==(\S+)\s*#\s*(?:CVE|vuln|security)", re.IGNORECASE
)

# Requirements file names actually scanned
REQUIREMENTS_FILE_NAMES = {
    "requirements.txt", "requirements-dev.txt", "requirements-lock.txt",
}


class DependencyAlertScanner:
    """Scans dependency files for pinned versions and lockfile staleness."""

    scanner_name = "dependency_alert_scanner"

    def scan(self, repo_path: Path) -> list[ScanResult]:
        """Scan requirements files for flagged dependencies."""
        results: list[ScanResult] = []

        for filename in REQUIREMENTS_FILE_NAMES:
            req_file = repo_path / filename
            if req_file.is_file():
                results.extend(self._check_requirements(req_file, repo_path))

        return results

    def _check_requirements(self, req_file: Path, repo_path: Path) -> list[ScanResult]:
        """Check a requirements file for CVE/vulnerability annotations."""
        results: list[ScanResult] = []
        relative = str(req_file.relative_to(repo_path))

        try:
            content = req_file.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            return results

        for line_num, line in enumerate(content.splitlines(), start=1):
            match = VULN_PATTERN.match(line)
            if match:
                pkg = match.group(1)
                ver = match.group(2)
                results.append(ScanResult(
                    source_type="dependency_alert",
                    title=f"Flagged dependency: {pkg}=={ver}",
                    description=(
                        f"Dependency {pkg}=={ver} has a security "
                        f"annotation in {relative}"
                    ),
                    file_path=relative,
                    line_number=line_num,
                    evidence={
                        "package": pkg,
                        "version": ver,
                        "file": relative,
                        "line": line.strip(),
                    },
                    confidence=0.8,
                    risk=RiskLevel.HIGH,
                    recipe_name="dependency_update",
                ))

        return results


class ScannerRegistry:
    """Registry of available discovery scanners."""

    def __init__(self) -> None:
        self._scanners: list[Scanner] = []

    def register(self, scanner: Scanner) -> None:
        """Register a scanner."""
        self._scanners.append(scanner)

    def register_defaults(self) -> None:
        """Register the built-in default scanners."""
        self._scanners = [
            TodoScanner(),
            DependencyAlertScanner(),
        ]

    @property
    def scanners(self) -> list[Scanner]:
        """Get all registered scanners."""
        return list(self._scanners)

    def scan_all(self, repo_path: Path) -> list[ScanResult]:
        """Run all registered scanners and return combined results."""
        results: list[ScanResult] = []
        for scanner in self._scanners:
            results.extend(scanner.scan(repo_path))
        return results


def scan_result_to_work_item(
    result: ScanResult,
    repo_id: str,
    work_item_id: str,
) -> WorkItem:
    """Convert a ScanResult into a WorkItem."""
    return WorkItem(
        work_item_id=work_item_id,
        repo_id=repo_id,
        kind=WorkItemKind.EXECUTION,
        title=result.title,
        description=result.description,
        source_type=result.source_type,
        source_fingerprint=result.fingerprint,
        trust_level=TrustLevel.SEMI_TRUSTED,
        state=WorkItemState.DISCOVERED,
        confidence=result.confidence,
        risk=result.risk,
        recipe_name=result.recipe_name,
        evidence=result.evidence,
        likely_files=[result.file_path],
    )
