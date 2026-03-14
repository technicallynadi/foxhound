"""Foxhound CLI application."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="foxhound",
    help="Sniff out ideas worth building. Ship them fast.",
    no_args_is_help=True,
)

console = Console()

FOXHOUND_DIR = ".foxhound"
DB_NAME = "foxhound.db"
CONFIG_NAME = "foxhound.yaml"


def _foxhound_dir() -> Path:
    """Return the .foxhound directory path."""
    return Path.cwd() / FOXHOUND_DIR


def _db_path() -> Path:
    """Return the database path."""
    return _foxhound_dir() / DB_NAME


@app.command()
def init() -> None:
    """Initialize .foxhound config and local DB."""
    fh_dir = _foxhound_dir()

    if fh_dir.exists():
        console.print(f"[yellow]Already initialized:[/yellow] {fh_dir}")
    else:
        fh_dir.mkdir(parents=True)
        console.print(f"[green]Created:[/green] {fh_dir}/")

    # Create subdirectories
    for subdir in ["artifacts", "recipes", "policies", "cache", "config"]:
        sub = fh_dir / subdir
        if not sub.exists():
            sub.mkdir()
            console.print(f"[green]Created:[/green] {sub}/")

    # Initialize database
    db_path = _db_path()
    from foxhound.storage.database import Database

    db = Database(db_path)
    db.close()
    console.print(f"[green]Database ready:[/green] {db_path}")

    # Create default config if missing
    config_path = Path.cwd() / CONFIG_NAME
    if not config_path.exists():
        config_path.write_text(
            "# Foxhound configuration\n"
            "models:\n"
            "  provider: anthropic\n"
            "  api_key_env: ANTHROPIC_API_KEY\n"
            "  tiers:\n"
            "    reasoning: claude-sonnet-4-6\n"
            "    balanced: claude-sonnet-4-6\n"
            "    fast: claude-haiku-4-5\n"
        )
        console.print(f"[green]Created:[/green] {config_path}")
    else:
        console.print(f"[yellow]Config exists:[/yellow] {config_path}")

    # Add .foxhound/ to .gitignore if not already there
    gitignore_path = Path.cwd() / ".gitignore"
    entry = ".foxhound/"
    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if entry not in content.splitlines():
            gitignore_path.write_text(content.rstrip() + f"\n{entry}\n")
            console.print(f"[green]Updated:[/green] .gitignore (added {entry})")
    else:
        gitignore_path.write_text(f"{entry}\n")
        console.print(f"[green]Created:[/green] .gitignore (added {entry})")

    console.print(
        "\n[bold green]Foxhound initialized.[/bold green] "
        "Run [cyan]foxhound doctor[/cyan] to validate."
    )


@app.command()
def doctor() -> None:
    """Validate environment and configuration."""
    import os
    import sys

    checks: list[tuple[str, bool, str]] = []

    # Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(("Python version", sys.version_info >= (3, 13), py_ver))

    # .foxhound directory
    fh_dir = _foxhound_dir()
    checks.append((".foxhound/ directory", fh_dir.is_dir(), str(fh_dir)))

    # Database
    db_path = _db_path()
    db_ok = db_path.exists()
    if db_ok:
        try:
            from foxhound.storage.database import Database

            db = Database(db_path)
            db.close()
            checks.append(("Database", True, str(db_path)))
        except Exception as e:
            checks.append(("Database", False, str(e)))
    else:
        checks.append(("Database", False, "Not found — run foxhound init"))

    # Config file
    config_path = Path.cwd() / CONFIG_NAME
    checks.append(("foxhound.yaml", config_path.exists(), str(config_path)))

    # API keys
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    has_key = bool(anthropic_key or openai_key)
    key_detail = []
    if anthropic_key:
        key_detail.append(f"ANTHROPIC_API_KEY={anthropic_key[:8]}...")
    if openai_key:
        key_detail.append(f"OPENAI_API_KEY={openai_key[:8]}...")
    if not key_detail:
        key_detail.append("No API keys found")
    checks.append(("API key configured", has_key, ", ".join(key_detail)))

    # Core imports
    try:
        import importlib

        for mod in [
            "foxhound.core.coordinator",
            "foxhound.core.event_bus",
            "foxhound.core.lock_manager",
            "foxhound.core.queue",
        ]:
            importlib.import_module(mod)
        checks.append(("Core modules", True, "coordinator, queue, locks, event_bus"))
    except ImportError as e:
        checks.append(("Core modules", False, str(e)))

    # Harness imports
    try:
        importlib.import_module("foxhound.harness.runtime")
        importlib.import_module("foxhound.harness.worker_protocol")
        checks.append(("Harness modules", True, "harness, worker_protocol"))
    except ImportError as e:
        checks.append(("Harness modules", False, str(e)))

    # Secrets imports
    try:
        importlib.import_module("foxhound.secrets.provider")
        checks.append(("Secrets modules", True, "provider, redaction"))
    except ImportError as e:
        checks.append(("Secrets modules", False, str(e)))

    # Recipe and policy modules
    try:
        importlib.import_module("foxhound.recipes.loader")
        importlib.import_module("foxhound.policies.engine")
        importlib.import_module("foxhound.policies.rules")
        checks.append(("Recipe/Policy modules", True, "recipes, policies, rules"))
    except ImportError as e:
        checks.append(("Recipe/Policy modules", False, str(e)))

    # Sanitization and evaluation modules
    try:
        importlib.import_module("foxhound.sanitization.pipeline")
        importlib.import_module("foxhound.evaluation.engine")
        checks.append(("Output processing", True, "sanitization, evaluation"))
    except ImportError as e:
        checks.append(("Output processing", False, str(e)))

    # Subdirectories
    for subdir in ["artifacts", "recipes", "policies", "cache", "config"]:
        sub = fh_dir / subdir
        checks.append((f".foxhound/{subdir}/", sub.is_dir(), str(sub)))

    # Display results
    table = Table(title="Foxhound Doctor", show_lines=True)
    table.add_column("Check", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Details")

    all_pass = True
    for name, passed, detail in checks:
        status = "[green]✓[/green]" if passed else "[red]✗[/red]"
        if not passed:
            all_pass = False
        table.add_row(name, status, detail)

    console.print(table)

    if all_pass:
        console.print("\n[bold green]All checks passed.[/bold green]")
    else:
        console.print("\n[bold red]Some checks failed.[/bold red] Fix the issues above.")
        raise typer.Exit(code=1)


repo_app = typer.Typer(
    name="repo",
    help="Manage registered repositories.",
    no_args_is_help=True,
)
app.add_typer(repo_app, name="repo")


@repo_app.command("add")
def repo_add(
    path: str = typer.Argument(
        ".", help="Path to the repository to register."
    ),
) -> None:
    """Register a new repository."""
    from foxhound.core.repo_registry import RepoRegistry, is_git_repo
    from foxhound.storage.database import Database

    repo_path = Path(path).resolve()
    if not repo_path.is_dir():
        console.print(f"[red]Not a directory:[/red] {repo_path}")
        raise typer.Exit(code=1)

    if not is_git_repo(repo_path):
        console.print(f"[red]Not a git repository:[/red] {repo_path}")
        raise typer.Exit(code=1)

    db_path = _db_path()
    if not db_path.exists():
        console.print("[red]Not initialized.[/red] Run [cyan]foxhound init[/cyan] first.")
        raise typer.Exit(code=1)

    db = Database(db_path)
    registry = RepoRegistry(db)
    repo = registry.register(repo_path)
    db.close()

    lang = repo.language_meta.get("primary", "unknown")
    console.print(f"[green]Registered:[/green] {repo.name} ({lang})")
    console.print(f"  ID: {repo.repo_id}")
    console.print(f"  Path: {repo.path}")
    console.print(f"  Branch: {repo.default_branch}")

    # Ensure .foxhound/ exists in the target repo
    fh_dir = repo_path / ".foxhound"
    if not fh_dir.exists():
        fh_dir.mkdir(parents=True)
        for subdir in ["artifacts", "recipes", "policies", "cache", "config"]:
            (fh_dir / subdir).mkdir(exist_ok=True)
        console.print(f"[green]Created:[/green] {fh_dir}/")


@repo_app.command("list")
def repo_list() -> None:
    """Show all registered repositories."""
    from foxhound.core.repo_registry import RepoRegistry
    from foxhound.storage.database import Database

    db_path = _db_path()
    if not db_path.exists():
        console.print("[red]Not initialized.[/red] Run [cyan]foxhound init[/cyan] first.")
        raise typer.Exit(code=1)

    db = Database(db_path)
    registry = RepoRegistry(db)
    repos = registry.list_repos()
    db.close()

    if not repos:
        console.print("[yellow]No repositories registered.[/yellow]")
        console.print("Run [cyan]foxhound repo add <path>[/cyan] to register one.")
        return

    table = Table(title="Registered Repositories")
    table.add_column("Name", style="bold")
    table.add_column("Language")
    table.add_column("Branch")
    table.add_column("Path")
    table.add_column("ID", style="dim")

    for repo in repos:
        lang = repo.language_meta.get("primary", "unknown")
        table.add_row(
            repo.name,
            lang,
            repo.default_branch,
            repo.path,
            repo.repo_id[:12],
        )

    console.print(table)


@repo_app.command("use")
def repo_use(repo_id: str) -> None:
    """Switch active repository context."""
    console.print(
        f"[yellow]foxhound repo use {repo_id} — "
        "active repo switching will be wired in a future milestone[/yellow]"
    )


@app.command()
def scan() -> None:
    """Run discovery scanners."""
    console.print("[yellow]foxhound scan — not yet implemented[/yellow]")


@app.command()
def scout() -> None:
    """Run external opportunity discovery."""
    console.print("[yellow]foxhound scout — not yet implemented[/yellow]")


@app.command()
def approve(work_item_id: str) -> None:
    """Approve/edit/reject a work item."""
    console.print(f"[yellow]foxhound approve {work_item_id} — not yet implemented[/yellow]")


@app.command()
def run(work_item_id: str) -> None:
    """Execute approved item."""
    console.print(f"[yellow]foxhound run {work_item_id} — not yet implemented[/yellow]")


@app.command()
def analyze() -> None:
    """Summarize failures and suggestions."""
    console.print("[yellow]foxhound analyze — not yet implemented[/yellow]")


@app.command()
def status() -> None:
    """Show queue and job status."""
    db_path = _db_path()
    if not db_path.exists():
        console.print("[red]Not initialized.[/red] Run [cyan]foxhound init[/cyan] first.")
        raise typer.Exit(code=1)

    from foxhound.core.coordinator import Coordinator
    from foxhound.storage.database import Database

    db = Database(db_path)
    coord = Coordinator(db)
    stats = coord.get_queue_stats()
    db.close()

    table = Table(title="Job Queue Status")
    table.add_column("Status", style="bold")
    table.add_column("Count", justify="right")

    for s, count in stats.items():
        style = "green" if s == "completed" else "red" if s == "failed" else "cyan"
        table.add_row(s, f"[{style}]{count}[/{style}]")

    console.print(table)


if __name__ == "__main__":
    app()
