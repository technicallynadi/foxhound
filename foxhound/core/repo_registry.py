"""Repository registry for managing single and multi-repo workspaces."""

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from foxhound.storage.database import Database


class RepoInfo(BaseModel):
    """Repository metadata."""

    repo_id: str
    name: str
    path: str
    default_branch: str = "main"
    repo_hash: str | None = None
    language_meta: dict[str, Any] = Field(default_factory=dict)
    active_config_hash: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


def _generate_repo_id(path: Path) -> str:
    """Generate a deterministic repo ID from path and remote URL."""
    remote_url = _detect_remote_url(path)
    key = f"{path.resolve()}:{remote_url or 'local'}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _generate_repo_hash(path: Path) -> str:
    """Generate a fingerprint hash for the repository."""
    remote_url = _detect_remote_url(path)
    key = f"{path.resolve()}:{remote_url or 'local'}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _detect_remote_url(path: Path) -> str | None:
    """Detect the git remote URL for a repository."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _detect_default_branch(path: Path) -> str:
    """Detect the default branch of a git repository."""
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            ref = result.stdout.strip()
            return ref.split("/")[-1]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "main"


def _detect_languages(path: Path) -> dict[str, Any]:
    """Detect primary languages in a repository by file extensions."""
    extension_map = {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".go": "Go",
        ".rs": "Rust",
        ".java": "Java",
        ".rb": "Ruby",
        ".cpp": "C++",
        ".c": "C",
        ".cs": "C#",
    }
    counts: dict[str, int] = {}
    try:
        for ext, lang in extension_map.items():
            files = list(path.rglob(f"*{ext}"))
            # Skip hidden dirs and common vendor dirs
            files = [
                f for f in files
                if not any(
                    part.startswith(".") or part in ("node_modules", "vendor", "__pycache__")
                    for part in f.parts
                )
            ]
            if files:
                counts[lang] = len(files)
    except PermissionError:
        pass

    if not counts:
        return {"primary": "unknown", "files": {}}

    primary = max(counts, key=lambda k: counts[k])
    return {"primary": primary, "files": counts}


def is_git_repo(path: Path) -> bool:
    """Check if a path is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_git_root(path: Path) -> Path | None:
    """Get the root directory of the git repository containing path."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


class RepoStore:
    """Storage operations for repository records."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, repo: RepoInfo) -> None:
        """Save or update a repo record."""
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO repos (
                    repo_id, name, path, default_branch, repo_hash,
                    language_meta, active_config_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    repo.repo_id,
                    repo.name,
                    repo.path,
                    repo.default_branch,
                    repo.repo_hash,
                    json.dumps(repo.language_meta),
                    repo.active_config_hash,
                    repo.created_at.isoformat(),
                    repo.updated_at.isoformat(),
                ),
            )
            conn.commit()

    def get(self, repo_id: str) -> RepoInfo | None:
        """Get a repo by ID."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM repos WHERE repo_id = ?", (repo_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_model(row)

    def get_by_path(self, path: str) -> RepoInfo | None:
        """Get a repo by its filesystem path."""
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM repos WHERE path = ?", (path,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_model(row)

    def list_all(self) -> list[RepoInfo]:
        """List all registered repos."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM repos ORDER BY name"
            ).fetchall()
            return [self._row_to_model(row) for row in rows]

    def delete(self, repo_id: str) -> bool:
        """Remove a repo registration."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM repos WHERE repo_id = ?", (repo_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def _row_to_model(self, row: Any) -> RepoInfo:
        """Convert a database row to RepoInfo."""
        return RepoInfo(
            repo_id=row["repo_id"],
            name=row["name"],
            path=row["path"],
            default_branch=row["default_branch"] or "main",
            repo_hash=row["repo_hash"],
            language_meta=json.loads(row["language_meta"]) if row["language_meta"] else {},
            active_config_hash=row["active_config_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


class RepoRegistry:
    """Manages repository registration and active repo context.

    Supports single-repo mode (auto-detect current git repo) and
    workspace mode (multiple registered repos).
    """

    def __init__(self, db: Database) -> None:
        self._store = RepoStore(db)
        self._active_repo_id: str | None = None

    def register(self, path: Path) -> RepoInfo:
        """Register a repository by path.

        Auto-detects git metadata, languages, and generates IDs.

        Args:
            path: Path to the repository root.

        Returns:
            RepoInfo for the registered repo.

        Raises:
            ValueError: If path doesn't exist or isn't a directory.
        """
        resolved = path.resolve()
        if not resolved.is_dir():
            msg = f"Path is not a directory: {resolved}"
            raise ValueError(msg)

        # Check if already registered
        existing = self._store.get_by_path(str(resolved))
        if existing is not None:
            return existing

        repo_id = _generate_repo_id(resolved)
        repo = RepoInfo(
            repo_id=repo_id,
            name=resolved.name,
            path=str(resolved),
            default_branch=_detect_default_branch(resolved),
            repo_hash=_generate_repo_hash(resolved),
            language_meta=_detect_languages(resolved),
        )
        self._store.save(repo)
        return repo

    def auto_detect(self) -> RepoInfo | None:
        """Auto-detect and register the current git repo.

        Returns:
            RepoInfo if inside a git repo, None otherwise.
        """
        cwd = Path.cwd()
        if not is_git_repo(cwd):
            return None

        root = get_git_root(cwd)
        if root is None:
            return None

        repo = self.register(root)
        self._active_repo_id = repo.repo_id
        return repo

    def get(self, repo_id: str) -> RepoInfo | None:
        """Get a registered repo by ID."""
        return self._store.get(repo_id)

    def list_repos(self) -> list[RepoInfo]:
        """List all registered repos."""
        return self._store.list_all()

    def set_active(self, repo_id: str) -> bool:
        """Set the active repo context.

        Args:
            repo_id: ID of the repo to activate.

        Returns:
            True if the repo was found and activated.
        """
        repo = self._store.get(repo_id)
        if repo is None:
            return False
        self._active_repo_id = repo_id
        return True

    @property
    def active_repo_id(self) -> str | None:
        """Get the active repo ID."""
        return self._active_repo_id

    @property
    def active_repo(self) -> RepoInfo | None:
        """Get the active repo info."""
        if self._active_repo_id is None:
            return None
        return self._store.get(self._active_repo_id)

    def remove(self, repo_id: str) -> bool:
        """Remove a repo registration."""
        if self._active_repo_id == repo_id:
            self._active_repo_id = None
        return self._store.delete(repo_id)
