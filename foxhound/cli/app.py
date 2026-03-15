"""Foxhound CLI application."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from foxhound.analyzer.engine import AnalysisDiagnosis
    from foxhound.storage.database import Database

import typer
from rich.console import Console
from rich.markup import escape as rich_escape
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
            "# Set your preferred model for each capability tier.\n"
            "# See docs for supported providers and models.\n"
            "models:\n"
            "  provider: anthropic\n"
            "  api_key_env: ANTHROPIC_API_KEY\n"
            "  tiers:\n"
            "    reasoning: your-reasoning-model\n"
            "    balanced: your-balanced-model\n"
            "    fast: your-fast-model\n"
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
    import importlib
    import os
    import sys

    checks: list[tuple[str, bool, str]] = []

    # Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(("Python version", sys.version_info >= (3, 13), py_ver))

    # .foxhound directory
    fh_dir = _foxhound_dir()
    checks.append((".foxhound/ directory", fh_dir.is_dir(), str(fh_dir)))

    # Database with schema validation
    db_path = _db_path()
    db_ok = db_path.exists()
    db_instance = None
    if db_ok:
        try:
            from foxhound.storage.database import Database

            db_instance = Database(db_path)
            # Validate schema — check expected tables exist
            with db_instance.connection() as conn:
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                table_names = {row["name"] for row in tables}
            expected = {
                "repos", "work_items", "jobs", "runs", "events",
                "locks", "artifacts", "recipe_versions", "policy_versions",
                "rule_suggestions", "opportunity_items",
            }
            missing = expected - table_names
            if missing:
                checks.append(("Database schema", False, f"Missing tables: {sorted(missing)}"))
            else:
                checks.append(("Database schema", True, f"{len(table_names)} tables OK"))
        except Exception as e:
            checks.append(("Database", False, str(e)))
    else:
        checks.append(("Database", False, "Not found — run foxhound init"))

    # Config file with YAML validation
    config_path = Path.cwd() / CONFIG_NAME
    if config_path.exists():
        try:
            import yaml

            config_data = yaml.safe_load(config_path.read_text())
            if config_data and "models" in config_data:
                checks.append(("foxhound.yaml", True, "Valid config with models section"))
            else:
                checks.append(("foxhound.yaml", False, "Missing 'models' section"))
        except Exception:
            checks.append(("foxhound.yaml", True, str(config_path)))
    else:
        checks.append(("foxhound.yaml", False, "Not found"))

    # API keys (never display key content — presence check only)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    has_key = bool(anthropic_key or openai_key)
    key_detail = []
    if anthropic_key:
        key_detail.append("ANTHROPIC_API_KEY=configured")
    if openai_key:
        key_detail.append("OPENAI_API_KEY=configured")
    if not key_detail:
        key_detail.append("No API keys found")
    checks.append(("API key configured", has_key, ", ".join(key_detail)))

    # .gitignore check
    gitignore_path = Path.cwd() / ".gitignore"
    if gitignore_path.exists():
        content = gitignore_path.read_text()
        has_foxhound = ".foxhound/" in content or ".foxhound" in content
        if has_foxhound:
            checks.append((".gitignore", True, ".foxhound/ is ignored"))
        else:
            checks.append((".gitignore", False, ".foxhound/ NOT in .gitignore — add it"))
    else:
        checks.append((".gitignore", False, "No .gitignore found"))

    # Core imports
    try:
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

    # Observer and analyzer modules
    try:
        importlib.import_module("foxhound.observer.store")
        importlib.import_module("foxhound.observer.retention")
        importlib.import_module("foxhound.analyzer.engine")
        checks.append(("Observability modules", True, "observer, analyzer, retention"))
    except ImportError as e:
        checks.append(("Observability modules", False, str(e)))

    # Subdirectories
    for subdir in ["artifacts", "recipes", "policies", "cache", "config"]:
        sub = fh_dir / subdir
        checks.append((f".foxhound/{subdir}/", sub.is_dir(), str(sub)))

    # Stale lock detection
    if db_instance is not None:
        try:
            from datetime import UTC, datetime

            with db_instance.connection() as conn:
                now_iso = datetime.now(UTC).isoformat()
                stale = conn.execute(
                    "SELECT COUNT(*) as cnt FROM locks WHERE expires_at < ?",
                    (now_iso,),
                ).fetchone()
                stale_count = stale["cnt"] if stale else 0
            if stale_count > 0:
                checks.append(("Stale locks", False, f"{stale_count} expired locks found"))
            else:
                checks.append(("Stale locks", True, "No stale locks"))
        except Exception:
            pass

    # Retention status
    if db_instance is not None:
        try:
            from foxhound.observer.retention import RetentionPolicy

            policy = RetentionPolicy(db_instance)
            status = policy.get_status()
            total = status.get("total", {})
            count = total.get("count", 0)
            size = total.get("size_bytes", 0)
            size_mb = size / (1024 * 1024) if size > 0 else 0
            checks.append((
                "Artifact retention",
                True,
                f"{count} artifacts, {size_mb:.1f} MB total",
            ))
        except Exception:
            pass

    # Repo validation
    if db_instance is not None:
        try:
            from foxhound.core.repo_registry import RepoRegistry

            registry = RepoRegistry(db_instance)
            repos = registry.list_repos()
            accessible = sum(1 for r in repos if Path(r.path).is_dir())
            if repos:
                if accessible == len(repos):
                    checks.append(("Registered repos", True, f"{accessible} repos accessible"))
                else:
                    checks.append((
                        "Registered repos",
                        False,
                        f"{accessible}/{len(repos)} accessible",
                    ))
        except Exception:
            pass

    if db_instance is not None:
        db_instance.close()

    # Display results
    table = Table(title="Foxhound Doctor", show_lines=True)
    table.add_column("Check", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Details")

    all_pass = True
    for name, passed, detail in checks:
        icon = "[green]\u2713[/green]" if passed else "[red]\u2717[/red]"
        if not passed:
            all_pass = False
        table.add_row(name, icon, detail)

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
    try:
        registry = RepoRegistry(db)
        repo = registry.register(repo_path)

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
    finally:
        db.close()


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
    try:
        registry = RepoRegistry(db)
        repos = registry.list_repos()
    finally:
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
    try:
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
    finally:
        db.close()


@app.command()
def scout(
    language: str = typer.Option(
        None, "--language", "-l", help="Filter by language."
    ),
    min_stars: int = typer.Option(
        10, "--min-stars", help="Minimum star count."
    ),
    limit: int = typer.Option(
        20, "--limit", "-n", help="Max results per source."
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Force fresh fetch regardless of cache."
    ),
) -> None:
    """Run external opportunity discovery (fetch, score, review)."""
    import os

    from rich.panel import Panel

    from foxhound.scout.fetcher import ScoutFetcher
    from foxhound.scout.scoring import ScoringPipeline
    from foxhound.storage.database import Database

    db_path = _db_path()
    if not db_path.exists():
        console.print(
            "[red]Not initialized.[/red] Run [cyan]foxhound init[/cyan] first."
        )
        raise typer.Exit(code=1)

    db = Database(db_path)
    try:
        config = _load_scout_config()

        # Phase 1: Fetch from external sources
        http_client = _make_http_client()
        fetcher = ScoutFetcher(
            db=db,
            http_client=http_client,  # type: ignore[arg-type]
            config=config,  # type: ignore[arg-type]
            github_token=os.environ.get("GITHUB_TOKEN"),
            reddit_client_id=os.environ.get("REDDIT_CLIENT_ID"),
            reddit_client_secret=os.environ.get("REDDIT_CLIENT_SECRET"),
        )

        fetch_summary = fetcher.fetch_all(
            force_refresh=refresh,
            language=language,
            min_stars=min_stars,
            limit=limit,
        )

        for r in fetch_summary.results:
            if r.skipped_fresh:
                console.print(f"[dim]{r.source}: cached (still fresh)[/dim]")
            elif r.error:
                console.print(f"[yellow]{r.source}: fetch error — {r.error}[/yellow]")
            else:
                console.print(
                    f"[green]{r.source}:[/green] "
                    f"{r.new_items} new, {r.updated_items} updated"
                )

        if fetch_summary.pruned > 0:
            console.print(f"[dim]Pruned {fetch_summary.pruned} expired entries[/dim]")

        # Phase 2: Score unscored items
        pipeline = ScoringPipeline(db=db)
        score_result = pipeline.score_all()

        if score_result.processed > 0:
            console.print(
                f"\n[cyan]Scored:[/cyan] {score_result.processed} items, "
                f"{score_result.passed} passed, {score_result.filtered} filtered"
            )

        # Phase 3: Display and review suggested opportunities
        from foxhound.core.models import OpportunityState
        from foxhound.scout.opportunity import OpportunityManager

        mgr = OpportunityManager(db)
        suggested = mgr.list_by_state(OpportunityState.SUGGESTED)

        if not suggested:
            console.print(
                "\n[yellow]No opportunities to review.[/yellow]\n"
                "Try running with [cyan]--refresh[/cyan] or check API credentials."
            )
            return

        console.print(
            f"\n[cyan]Found {len(suggested)} opportunities to review[/cyan]\n"
        )

        for item in suggested:
            evidence = item.evidence or {}
            lang = evidence.get("language", "")
            license_type = evidence.get("license_type", "")

            scores = (
                f"Velocity: {item.credibility_score:.0%}  "
                f"Improvability: {item.novelty_score:.0%}  "
                f"Buildability: {item.actionability_score:.0%}  "
                f"Value: {item.business_value_score:.0%}"
            )

            source_info = f"[dim]Source: {item.source_type}[/dim]"
            if item.source_url:
                source_info += f"  [dim]{item.source_url}[/dim]"

            meta_parts = []
            if lang:
                meta_parts.append(f"Language: {lang}")
            if license_type:
                meta_parts.append(f"License: {license_type}")
            if item.tags:
                meta_parts.append(f"Tags: {', '.join(item.tags)}")
            meta_str = f"\n[dim]{' | '.join(meta_parts)}[/dim]" if meta_parts else ""

            body = (
                f"{rich_escape(item.description[:200])}\n\n"
                f"{scores}\n"
                f"{source_info}{meta_str}"
            )

            console.print(Panel(
                body,
                title=f"{rich_escape(item.title)} [{item.opportunity_id[:16]}]",
                border_style="cyan",
            ))

        # Interactive review
        from rich.prompt import Prompt

        for item in suggested:
            action = Prompt.ask(
                f"\n[bold]{rich_escape(item.title[:50])}[/bold]",
                choices=["approve", "reject", "skip"],
                default="skip",
            )

            if action == "approve":
                mgr.approve(item.opportunity_id)
                console.print("[green]Approved.[/green]")
            elif action == "reject":
                mgr.reject(item.opportunity_id)
                console.print("[red]Rejected.[/red]")
            else:
                console.print("[dim]Skipped.[/dim]")
    finally:
        db.close()


def _load_scout_config() -> object:
    """Load scout configuration from foxhound.yaml."""
    from foxhound.scout.fetcher import ScoutConfig, SourceConfig

    config_path = _foxhound_dir() / CONFIG_NAME
    if not config_path.exists():
        return ScoutConfig()

    try:
        import yaml

        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

        scout_data = data.get("scout", {})
        if not scout_data:
            return ScoutConfig()

        sources: dict[str, SourceConfig] = {}
        for name, src_data in scout_data.get("sources", {}).items():
            if isinstance(src_data, dict):
                sources[name] = SourceConfig(**{
                    k: v for k, v in src_data.items()
                    if k in SourceConfig.model_fields
                })

        return ScoutConfig(
            fetch_interval_hours=scout_data.get(
                "fetch_interval_hours", ScoutConfig.model_fields["fetch_interval_hours"].default,
            ),
            retention_days=scout_data.get("retention_days", 7),
            sources=sources if sources else ScoutConfig().sources,
        )
    except Exception:
        return ScoutConfig()


def _make_http_client() -> object:
    """Create a simple HTTP client using urllib."""
    import json as json_mod
    import urllib.request
    from urllib.error import HTTPError, URLError

    from foxhound.adapters.github_connector import HttpResponse

    class UrllibHttpClient:
        """Minimal HTTP client using urllib."""

        def get(
            self,
            url: str,
            headers: dict[str, str] | None = None,
            params: dict[str, str] | None = None,
            timeout: int = 30,
        ) -> HttpResponse:
            if params:
                from urllib.parse import urlencode
                url = f"{url}?{urlencode(params)}"

            req = urllib.request.Request(url)
            for k, v in (headers or {}).items():
                req.add_header(k, v)

            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read().decode("utf-8")
                    resp_headers = {k: v for k, v in resp.headers.items()}
                    return HttpResponse(
                        status_code=resp.status,
                        json_data=json_mod.loads(body) if body else None,
                        headers=resp_headers,
                    )
            except HTTPError as e:
                resp_headers = {k: v for k, v in e.headers.items()} if e.headers else {}
                return HttpResponse(
                    status_code=e.code,
                    json_data=None,
                    headers=resp_headers,
                )
            except (URLError, TimeoutError):
                return HttpResponse(status_code=0, json_data=None)

    return UrllibHttpClient()


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
    try:
        coord = Coordinator(db)
        item = coord.get_work_item(work_item_id)

        if item is None:
            console.print(f"[red]Work item not found:[/red] {work_item_id}")
            raise typer.Exit(code=1)

        # Display work item details
        risk_color = {"low": "green", "medium": "yellow", "high": "red"}.get(
            item.risk.value, "white"
        )

        details = (
            f"[bold]Title:[/bold] {rich_escape(item.title)}\n"
            f"[bold]State:[/bold] {item.state.value}\n"
            f"[bold]Source:[/bold] {rich_escape(item.source_type)}\n"
            f"[bold]Risk:[/bold] [{risk_color}]{item.risk.value}[/{risk_color}]\n"
            f"[bold]Confidence:[/bold] {item.confidence:.0%}\n"
            f"[bold]Recipe:[/bold] {rich_escape(item.recipe_name or 'none')}\n"
            f"[bold]Files:[/bold] {rich_escape(', '.join(item.likely_files) or 'none')}\n"
            f"[bold]Description:[/bold] {rich_escape(item.description)}"
        )

        console.print(Panel(details, title=f"Work Item: {work_item_id}", border_style="cyan"))

        # Show evidence
        if item.evidence:
            evidence_lines = []
            for key, value in item.evidence.items():
                evidence_lines.append(
                    f"  {rich_escape(str(key))}: {rich_escape(str(value))}"
                )
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
            new_title = "".join(c for c in new_title if c >= " " or c == "\n")
            if len(new_title) > 200:
                new_title = new_title[:200]
                console.print("[yellow]Title truncated to 200 characters.[/yellow]")
            if not new_title.strip():
                console.print("[red]Title cannot be empty.[/red]")
                return
            coord.advance_work_item(work_item_id, WorkItemState.EDITED)
            if new_title != item.title:
                updated_item = coord.get_work_item(work_item_id)
                if updated_item:
                    updated_item.title = new_title
                    coord.save_work_item(updated_item)
                console.print(f"[green]Edited and approved:[/green] {new_title}")
            else:
                console.print("[green]Marked as edited.[/green]")
        else:
            console.print("[dim]Skipped.[/dim]")
    finally:
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
    runs: bool = typer.Option(
        False, "--runs", help="Show run history instead of work items."
    ),
    since: str = typer.Option(
        None, "--since", help="Filter runs by date (YYYY-MM-DD)."
    ),
) -> None:
    """Show work item or run history with rich formatting."""
    from foxhound.storage.database import Database

    db_path = _db_path()
    if not db_path.exists():
        console.print("[red]Not initialized.[/red] Run [cyan]foxhound init[/cyan] first.")
        raise typer.Exit(code=1)

    db = Database(db_path)
    try:
        if runs:
            _show_run_history(db, state=state, since=since, limit=limit)
        else:
            _show_work_items(db, state=state, repo_path=repo_path, limit=limit)
    finally:
        db.close()


def _show_run_history(
    db: Database,
    state: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> None:
    """Display run history with rich formatting."""
    from foxhound.core.models import RunState

    # Query all runs via direct SQL for filtering
    query = "SELECT * FROM runs"
    params: list[str | int] = []
    conditions: list[str] = []

    if state:
        try:
            RunState(state)
        except ValueError:
            valid = ", ".join(s.value for s in RunState)
            console.print(f"[red]Invalid state:[/red] {state}. Valid: {valid}")
            raise typer.Exit(code=1)
        conditions.append("state = ?")
        params.append(state)

    if since:
        conditions.append("created_at >= ?")
        params.append(since)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    with db.connection() as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        console.print("[yellow]No runs found.[/yellow]")
        return

    table = Table(title="Run History")
    table.add_column("Run ID", style="dim", max_width=16)
    table.add_column("Worker", max_width=20)
    table.add_column("State", justify="center")
    table.add_column("Cost", justify="right")
    table.add_column("Retries", justify="center")
    table.add_column("Branch", max_width=30)
    table.add_column("Failure", max_width=30)
    table.add_column("Updated")

    state_colors = {
        "queued": "blue",
        "preparing": "cyan",
        "context_built": "cyan",
        "executing": "magenta",
        "validating": "yellow",
        "security_review": "yellow",
        "branch_ready": "green",
        "pr_draft_ready": "green",
        "completed": "bold green",
        "failed": "bold red",
        "cancelled": "dim",
    }

    for row in rows:
        sc = state_colors.get(row["state"], "white")
        cost_str = f"${row['total_cost']:.4f}" if row["total_cost"] else "$0.00"
        failure = row["failure_reason"] or ""
        if len(failure) > 30:
            failure = failure[:27] + "..."
        branch = row["branch_name"] or ""
        updated = row["updated_at"][:16] if row["updated_at"] else ""

        table.add_row(
            row["run_id"][:16],
            row["worker_type"],
            f"[{sc}]{row['state']}[/{sc}]",
            cost_str,
            str(row["retry_count"]),
            branch,
            failure,
            updated,
        )

    console.print(table)


def _show_work_items(
    db: Database,
    state: str | None = None,
    repo_path: str | None = None,
    limit: int = 50,
) -> None:
    """Display work item history."""
    from foxhound.core.coordinator import Coordinator
    from foxhound.core.models import WorkItemState
    from foxhound.core.repo_registry import RepoRegistry

    coord = Coordinator(db)

    state_filter = None
    if state:
        try:
            state_filter = WorkItemState(state)
        except ValueError:
            valid = ", ".join(s.value for s in WorkItemState)
            console.print(f"[red]Invalid state:[/red] {state}. Valid: {valid}")
            raise typer.Exit(code=1)

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
            raise typer.Exit(code=1)

    items = coord.list_work_items(repo_id=repo_id, state=state_filter)
    items = items[:limit]

    if not items:
        console.print("[yellow]No work items found.[/yellow]")
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


@app.command(name="run")
def run_item(work_item_id: str) -> None:
    """Execute approved work item end-to-end."""

    from foxhound.cli.run_pipeline import run_pipeline
    from foxhound.core.coordinator import Coordinator
    from foxhound.core.models import WorkItemState
    from foxhound.storage.database import Database

    db_path = _db_path()
    if not db_path.exists():
        console.print("[red]Not initialized.[/red] Run [cyan]foxhound init[/cyan] first.")
        raise typer.Exit(code=1)

    db = Database(db_path)
    try:
        # Quick validation before starting pipeline
        coord = Coordinator(db)
        item = coord.get_work_item(work_item_id)
        if item is None:
            console.print(f"[red]Work item not found:[/red] {work_item_id}")
            raise typer.Exit(code=1)

        if item.state not in (WorkItemState.APPROVED, WorkItemState.EDITED):
            console.print(
                f"[red]Work item must be approved or edited,[/red] "
                f"got '{item.state.value}'"
            )
            raise typer.Exit(code=1)

        # Resolve repo path
        from foxhound.core.repo_registry import RepoRegistry

        registry = RepoRegistry(db)
        repo_path = None
        for repo in registry.list_repos():
            if repo.repo_id == item.repo_id:
                repo_path = Path(repo.path)
                break

        if repo_path is None:
            console.print(f"[red]Repository not found for repo_id:[/red] {item.repo_id}")
            raise typer.Exit(code=1)

        console.print(
            f"[cyan]Running[/cyan] {rich_escape(item.title[:60])} "
            f"[dim]({work_item_id[:16]})[/dim]"
        )
        console.print(f"  Repository: {repo_path}")
        console.print()

        # Run the pipeline
        result = run_pipeline(
            work_item_id=work_item_id,
            db=db,
            repo_path=repo_path,
        )

        # Display review panel if available
        if result.review_verdict:

            # Show review results
            verdict_colors = {
                "pass": "green",
                "pass_with_warnings": "yellow",
                "needs_review": "red",
                "recommend_reject": "bold red",
            }
            v_color = verdict_colors.get(result.review_verdict, "white")
            v_display = result.review_verdict.upper().replace("_", " ")
            console.print(
                f"  Review: [{v_color}]{v_display}[/{v_color}] "
                f"({result.review_confidence:.0%} confidence)"
            )
            if result.review_summary:
                console.print(f"  {result.review_summary}")
            console.print()

        # Display final result
        if result.success:
            console.print("[bold green]Run completed successfully.[/bold green]")
            if result.branch_name:
                console.print(f"  Branch: [cyan]{result.branch_name}[/cyan]")
            if result.commit_hash:
                console.print(f"  Commit: [dim]{result.commit_hash[:12]}[/dim]")
            if result.files_changed:
                console.print(f"  Files changed: {len(result.files_changed)}")
            console.print(f"  Duration: {result.duration_seconds:.1f}s")
            console.print(f"  Cost: ${result.total_cost:.4f}")
        else:
            console.print(f"[bold red]Run failed at stage:[/bold red] {result.stage_reached}")
            if result.error:
                console.print(f"  Error: {rich_escape(result.error[:200])}")
            if result.validation_results:
                failed = [
                    r for r in result.validation_results
                    if not r.get("passed", False)
                ]
                if failed:
                    console.print(f"  Failed validations: {len(failed)}")
                    for r in failed[:3]:
                        cmd = r.get("command", "unknown")
                        err = r.get("error", "")
                        if isinstance(err, str) and len(err) > 100:
                            err = err[:100]
                        console.print(f"    {cmd}: {err}")
            console.print(f"  Duration: {result.duration_seconds:.1f}s")
            raise typer.Exit(code=1)
    finally:
        db.close()


@app.command()
def analyze(
    run_id: str = typer.Argument(
        None, help="Run ID to analyze. If omitted, analyzes recent failed runs."
    ),
    limit: int = typer.Option(5, "--limit", "-n", help="Number of recent runs to analyze."),
) -> None:
    """Summarize failures and suggestions."""

    from foxhound.analyzer.engine import AnalyzerEngine
    from foxhound.storage.database import Database

    db_path = _db_path()
    if not db_path.exists():
        console.print("[red]Not initialized.[/red] Run [cyan]foxhound init[/cyan] first.")
        raise typer.Exit(code=1)

    db = Database(db_path)
    try:
        engine = AnalyzerEngine(db)

        if run_id:
            # Analyze a specific run
            diagnosis = engine.analyze_run(run_id)
            _display_diagnosis(diagnosis)
        else:
            # Analyze recent failed runs
            with db.connection() as conn:
                rows = conn.execute(
                    "SELECT run_id FROM runs WHERE state = 'failed' "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()

            if not rows:
                console.print("[yellow]No failed runs found.[/yellow]")
                # Show pending suggestions
                suggestions = engine.get_pending_suggestions()
                if suggestions:
                    console.print(f"\n[cyan]{len(suggestions)} pending rule suggestions:[/cyan]")
                    for s in suggestions[:10]:
                        console.print(
                            f"  {s['suggestion_id'][:16]}: {s['rule_name']} "
                            f"(confidence: {s['confidence']:.0%})"
                        )
                return

            for row in rows:
                diagnosis = engine.analyze_run(row["run_id"])
                _display_diagnosis(diagnosis)
                console.print()

        # Show pending suggestions
        suggestions = engine.get_pending_suggestions()
        if suggestions:
            console.print(f"\n[cyan]{len(suggestions)} pending rule suggestions.[/cyan]")
    finally:
        db.close()


def _display_diagnosis(diagnosis: AnalysisDiagnosis) -> None:
    """Display an analysis diagnosis with rich formatting."""
    from rich.panel import Panel

    lines = [f"[bold]Run:[/bold] {diagnosis.run_id}"]

    if diagnosis.failure_class:
        fc_colors = {
            "bad_ticket": "yellow",
            "context_gap": "cyan",
            "wrong_model": "magenta",
            "validation_failure": "red",
            "timeout": "yellow",
            "budget_exceeded": "yellow",
            "security_violation": "bold red",
            "unknown": "dim",
        }
        color = fc_colors.get(diagnosis.failure_class, "white")
        lines.append(
            f"[bold]Failure class:[/bold] [{color}]{diagnosis.failure_class}[/{color}]"
        )

    lines.append(f"[bold]Confidence:[/bold] {diagnosis.confidence:.0%}")

    if diagnosis.context_gaps:
        lines.append("[bold]Context gaps:[/bold]")
        for gap in diagnosis.context_gaps:
            lines.append(f"  - {gap}")

    if diagnosis.readiness_issues:
        lines.append("[bold]Readiness issues:[/bold]")
        for issue in diagnosis.readiness_issues:
            lines.append(f"  - {issue}")

    if diagnosis.recommendations:
        lines.append("[bold]Recommendations:[/bold]")
        for rec in diagnosis.recommendations:
            lines.append(f"  - {rec}")

    console.print(Panel("\n".join(lines), title="Analysis", border_style="cyan"))


# Retention commands
retention_app = typer.Typer(
    name="retention",
    help="Manage artifact retention and storage.",
    no_args_is_help=True,
)
app.add_typer(retention_app, name="retention")


@retention_app.command("status")
def retention_status() -> None:
    """Show storage usage and retention statistics."""
    from foxhound.observer.retention import RetentionPolicy
    from foxhound.storage.database import Database

    db_path = _db_path()
    if not db_path.exists():
        console.print("[red]Not initialized.[/red] Run [cyan]foxhound init[/cyan] first.")
        raise typer.Exit(code=1)

    db = Database(db_path)
    try:
        policy = RetentionPolicy(db)
        status = policy.get_status()

        table = Table(title="Retention Status")
        table.add_column("Class", style="bold")
        table.add_column("Retention", justify="right")
        table.add_column("Artifacts", justify="right")
        table.add_column("Size", justify="right")

        for cls in ["A", "B", "C"]:
            info = status.get(cls, {})
            count = info.get("count", 0)
            size = info.get("size_bytes", 0)
            days = info.get("retention_days", 0)
            size_str = _format_size(size)
            table.add_row(f"Class {cls}", f"{days}d", str(count), size_str)

        total = status.get("total", {})
        table.add_row(
            "[bold]Total[/bold]",
            "",
            str(total.get("count", 0)),
            _format_size(total.get("size_bytes", 0)),
        )

        console.print(table)
    finally:
        db.close()


@retention_app.command("prune")
def retention_prune() -> None:
    """Remove expired artifacts."""
    from foxhound.observer.retention import RetentionPolicy
    from foxhound.storage.database import Database

    db_path = _db_path()
    if not db_path.exists():
        console.print("[red]Not initialized.[/red] Run [cyan]foxhound init[/cyan] first.")
        raise typer.Exit(code=1)

    db = Database(db_path)
    try:
        policy = RetentionPolicy(db)
        result = policy.prune()

        console.print(f"[green]Pruned:[/green] {result.artifacts_removed} artifacts")
        console.print(f"  Files deleted: {result.files_deleted}")
        console.print(f"  Space freed: {_format_size(result.bytes_freed)}")
        if result.errors:
            console.print(f"  [yellow]Errors: {len(result.errors)}[/yellow]")
            for err in result.errors[:5]:
                console.print(f"    {err}")
    finally:
        db.close()


@retention_app.command("compact")
def retention_compact(
    days: int = typer.Option(30, "--days", "-d", help="Compact events older than N days."),
) -> None:
    """Compact event streams to summaries."""
    from foxhound.observer.retention import RetentionPolicy
    from foxhound.storage.database import Database

    db_path = _db_path()
    if not db_path.exists():
        console.print("[red]Not initialized.[/red] Run [cyan]foxhound init[/cyan] first.")
        raise typer.Exit(code=1)

    db = Database(db_path)
    try:
        policy = RetentionPolicy(db)
        result = policy.compact_events(older_than_days=days)

        console.print(f"[green]Compacted:[/green] {result.events_compacted} events")
    finally:
        db.close()


def _format_size(size_bytes: int) -> str:
    """Format bytes into human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


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
    try:
        coord = Coordinator(db)
        stats = coord.get_queue_stats()
    finally:
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
