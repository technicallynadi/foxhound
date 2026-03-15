"""Shared path resolution for foxhound CLI and TUI."""

from pathlib import Path

FOXHOUND_DIR = ".foxhound"
DB_NAME = "foxhound.db"
CONFIG_NAME = "foxhound.yaml"


def foxhound_dir(root: Path | None = None) -> Path:
    """Return the .foxhound directory path."""
    return (root or Path.cwd()) / FOXHOUND_DIR


def db_path(root: Path | None = None) -> Path:
    """Return the database path."""
    return foxhound_dir(root) / DB_NAME


def config_path(root: Path | None = None) -> Path:
    """Return the foxhound.yaml config path."""
    return (root or Path.cwd()) / CONFIG_NAME
