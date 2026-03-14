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
def scan(
    repo_path: str = typer.Option(
        ".", "--path", "-p", help="Path to the repository to scan."
    ),
) -> None:
    """Run discovery scanners on a repository."""
    from foxhound.core.coordinator import Coordinator
    from foxhound.core.repo_registry import RepoRegistry, is_git_repo
    from foxhound.discovery.scanners import ScannerRegistry, scan_result_to_work_item
    from foxhound.storage.database import Database

    db_path = _db_path()
    if not db_path.exists():
        console.print("[red]Not initialized.[/red] Run [cyan]foxhound init[/cyan] first.")
        raise typer.Exit(code=1)

    target = Path(repo_path).resolve()
    if not target.is_dir():
        console.print(f"[red]Not a directory:[/red] {target}")
        raise typer.Exit(code=1)

    db = Database(db_path)
    registry = RepoRegistry(db)
    repos = registry.list_repos()

    # Find repo_id for this path
    repo_id = None
    for repo in repos:
        if Path(repo.path).resolve() == target:
            repo_id = repo.repo_id
            break

    if repo_id is None:
        # Auto-register if it's a git repo
        if is_git_repo(target):
            repo = registry.register(target)
            repo_id = repo.repo_id
            console.print(f"[green]Auto-registered:[/green] {repo.name}")
        else:
            console.print(
                "[red]Not a registered repo.[/red] "
                "Run [cyan]foxhound repo add[/cyan] first."
            )
            db.close()
            raise typer.Exit(code=1)

    coord = Coordinator(db)
    known_fps = coord.get_known_fingerprints(repo_id)

    # Run scanners
    scanner_reg = ScannerRegistry()
    scanner_reg.register_defaults()

    console.print(f"[cyan]Scanning[/cyan] {target} ...")
    results = scanner_reg.scan_all(target)

    # Dedup and save
    from uuid import uuid4

    new_count = 0
    skip_count = 0
    for result in results:
        if result.fingerprint in known_fps:
            skip_count += 1
            continue
        known_fps.add(result.fingerprint)
        wid = f"wi_{uuid4().hex[:12]}"
        item = scan_result_to_work_item(result, repo_id, wid)
        coord.save_work_item(item)
        new_count += 1

    # Promote discovered → suggested
    promoted = coord.promote_discovered_to_suggested(repo_id)

    db.close()

    console.print(
        f"\n[bold green]Scan complete.[/bold green] "
        f"Found {len(results)} items, {new_count} new, "
        f"{skip_count} duplicates skipped, {promoted} promoted to suggested."
    )
    if new_count > 0:
        console.print(
            "Run [cyan]foxhound log[/cyan] to see items, "
            "[cyan]foxhound approve <id>[/cyan] to review."
        )


@app.command()
def scout() -> None:
    """Run external opportunity discovery."""
    console.print("[yellow]foxhound scout — not yet implemented[/yellow]")


@app.command()
def approve(work_item_id: str) -> None:
    """Approve, edit, or reject a work item."""
    from rich.panel import Panel
    from rich.prompt import Prompt

    from foxhound.core.coordinator import Coordinator
    from foxhound.core.models import WorkItemState
    from foxhound.storage.database import Database

    db_path = _db_path()
    if not db_path.exists():
        console.print("[red]Not initialized.[/red] Run [cyan]foxhound init[/cyan] first.")
        raise typer.Exit(code=1)

    db = Database(db_path)
    coord = Coordinator(db)
    item = coord.get_work_item(work_item_id)

    if item is None:
        console.print(f"[red]Work item not found:[/red] {work_item_id}")
        db.close()
        raise typer.Exit(code=1)

    # Display work item details
    risk_color = {"low": "green", "medium": "yellow", "high": "red"}.get(
        item.risk.value, "white"
    )

    details = (
        f"[bold]Title:[/bold] {item.title}\n"
        f"[bold]State:[/bold] {item.state.value}\n"
        f"[bold]Source:[/bold] {item.source_type}\n"
        f"[bold]Risk:[/bold] [{risk_color}]{item.risk.value}[/{risk_color}]\n"
        f"[bold]Confidence:[/bold] {item.confidence:.0%}\n"
        f"[bold]Recipe:[/bold] {item.recipe_name or 'none'}\n"
        f"[bold]Files:[/bold] {', '.join(item.likely_files) or 'none'}\n"
        f"[bold]Description:[/bold] {item.description}"
    )

    console.print(Panel(details, title=f"Work Item: {work_item_id}", border_style="cyan"))

    # Show evidence
    if item.evidence:
        evidence_lines = []
        for key, value in item.evidence.items():
            evidence_lines.append(f"  {key}: {value}")
        console.print(Panel(
            "\n".join(evidence_lines),
            title="Evidence",
            border_style="dim",
        ))

    # Check if item is in a reviewable state
    if item.state not in (WorkItemState.SUGGESTED, WorkItemState.BLOCKED):
        console.print(
            f"[yellow]Item is in state '{item.state.value}' — "
            f"only 'suggested' or 'blocked' items can be reviewed.[/yellow]"
        )
        db.close()
        return

    # Prompt for action
    action = Prompt.ask(
        "\nAction",
        choices=["approve", "reject", "edit", "skip"],
        default="skip",
    )

    if action == "approve":
        coord.advance_work_item(work_item_id, WorkItemState.APPROVED)
        console.print("[green]Approved.[/green]")
    elif action == "reject":
        coord.advance_work_item(work_item_id, WorkItemState.REJECTED)
        console.print("[red]Rejected.[/red]")
    elif action == "edit":
        new_title = Prompt.ask("New title", default=item.title)
        if new_title != item.title:
            from foxhound.core.models import WorkItem

            item_dict = item.model_dump()
            item_dict["title"] = new_title
            item_dict["state"] = WorkItemState.EDITED
            updated = WorkItem(**item_dict)
            coord.save_work_item(updated)
            console.print(f"[green]Edited and approved:[/green] {new_title}")
        else:
            coord.advance_work_item(work_item_id, WorkItemState.EDITED)
            console.print("[green]Marked as edited.[/green]")
    else:
        console.print("[dim]Skipped.[/dim]")

    db.close()


@app.command()
def log(
    state: str = typer.Option(
        None, "--state", "-s", help="Filter by state (e.g., suggested, approved)."
    ),
    repo_path: str = typer.Option(
        None, "--repo", "-r", help="Filter by repo path."
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="Max items to show."),
) -> None:
    """Show work item history with state transitions."""
    from foxhound.core.coordinator import Coordinator
    from foxhound.core.models import WorkItemState
    from foxhound.core.repo_registry import RepoRegistry
    from foxhound.storage.database import Database

    db_path = _db_path()
    if not db_path.exists():
        console.print("[red]Not initialized.[/red] Run [cyan]foxhound init[/cyan] first.")
        raise typer.Exit(code=1)

    db = Database(db_path)
    coord = Coordinator(db)

    # Resolve state filter
    state_filter = None
    if state:
        try:
            state_filter = WorkItemState(state)
        except ValueError:
            valid = ", ".join(s.value for s in WorkItemState)
            console.print(f"[red]Invalid state:[/red] {state}. Valid: {valid}")
            db.close()
            raise typer.Exit(code=1)

    # Resolve repo filter
    repo_id = None
    if repo_path:
        registry = RepoRegistry(db)
        target = Path(repo_path).resolve()
        for repo in registry.list_repos():
            if Path(repo.path).resolve() == target:
                repo_id = repo.repo_id
                break
        if repo_id is None:
            console.print(f"[red]Repo not found:[/red] {repo_path}")
            db.close()
            raise typer.Exit(code=1)

    items = coord.list_work_items(repo_id=repo_id, state=state_filter)
    items = items[:limit]

    if not items:
        console.print("[yellow]No work items found.[/yellow]")
        db.close()
        return

    table = Table(title="Work Items")
    table.add_column("ID", style="dim", max_width=16)
    table.add_column("State", justify="center")
    table.add_column("Risk", justify="center")
    table.add_column("Conf", justify="right")
    table.add_column("Source", max_width=18)
    table.add_column("Title", max_width=50)
    table.add_column("Updated")

    state_colors = {
        "discovered": "blue",
        "suggested": "cyan",
        "approved": "green",
        "edited": "green",
        "rejected": "red",
        "blocked": "yellow",
        "executing": "magenta",
        "completed": "bold green",
        "failed": "bold red",
    }
    risk_colors = {"low": "green", "medium": "yellow", "high": "red"}

    for item in items:
        sc = state_colors.get(item.state.value, "white")
        rc = risk_colors.get(item.risk.value, "white")
        table.add_row(
            item.work_item_id[:16],
            f"[{sc}]{item.state.value}[/{sc}]",
            f"[{rc}]{item.risk.value}[/{rc}]",
            f"{item.confidence:.0%}",
            item.source_type,
            item.title[:50],
            item.updated_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)
    db.close()


@app.command(name="run")
def run_item(work_item_id: str) -> None:
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
