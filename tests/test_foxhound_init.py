"""Tests for .foxhound/ directory initialization."""

from pathlib import Path

from typer.testing import CliRunner

from foxhound.cli.app import app

runner = CliRunner()


class TestInitCommand:
    """Test foxhound init creates correct directory structure."""

    def test_init_creates_all_subdirs(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0

        fh_dir = tmp_path / ".foxhound"
        assert fh_dir.is_dir()

        for subdir in ["artifacts", "recipes", "policies", "cache", "config"]:
            assert (fh_dir / subdir).is_dir(), f"Missing subdir: {subdir}"

    def test_init_creates_db(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        runner.invoke(app, ["init"])
        assert (tmp_path / ".foxhound" / "foxhound.db").exists()

    def test_init_creates_config(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        runner.invoke(app, ["init"])
        config = tmp_path / "foxhound.yaml"
        assert config.exists()
        content = config.read_text()
        assert "provider: anthropic" in content

    def test_init_creates_gitignore(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        runner.invoke(app, ["init"])
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        assert ".foxhound/" in gitignore.read_text()

    def test_init_appends_to_existing_gitignore(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/\n")
        runner.invoke(app, ["init"])
        content = gitignore.read_text()
        assert "node_modules/" in content
        assert ".foxhound/" in content

    def test_init_idempotent(self, tmp_path: Path, monkeypatch: object) -> None:
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        runner.invoke(app, ["init"])
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert "Already initialized" in result.output

    def test_init_does_not_duplicate_gitignore_entry(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
        runner.invoke(app, ["init"])
        runner.invoke(app, ["init"])
        gitignore = tmp_path / ".gitignore"
        lines = gitignore.read_text().splitlines()
        foxhound_entries = [line for line in lines if line.strip() == ".foxhound/"]
        assert len(foxhound_entries) == 1
