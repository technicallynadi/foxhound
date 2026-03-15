"""Async-safe data access layer for the TUI.

Wraps synchronous store operations so they can be called from
Textual's async event loop without blocking the UI thread.
"""

from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path
from typing import Any

from foxhound.core.models import (
    OpportunityDiscoveryItem,
    OpportunityState,
    WorkItem,
    WorkItemState,
)
from foxhound.core.paths import db_path
from foxhound.storage.database import Database


class TUIData:
    """Data access for the TUI, backed by the foxhound database."""

    def __init__(self, root: Path | None = None) -> None:
        self._db_path = db_path(root)
        self._db: Database | None = None

    @property
    def db(self) -> Database:
        """Lazy database connection."""
        if self._db is None:
            self._db = Database(self._db_path)
        return self._db

    def is_initialized(self) -> bool:
        """Check if the database exists."""
        return self._db_path.exists()

    def close(self) -> None:
        """Close the database connection."""
        if self._db:
            self._db.close()
            self._db = None

    async def _run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a sync function in a thread to avoid blocking the TUI."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(fn, *args, **kwargs))

    # -- Scan --

    async def run_scan(self, repo_path: str | None = None) -> dict[str, int]:
        """Run discovery scanners on a repo. Returns {new, skipped, promoted}."""
        return await self._run(self._do_scan, repo_path)

    def _do_scan(self, repo_path: str | None = None) -> dict[str, int]:
        """Synchronous scan logic."""
        from pathlib import Path
        from uuid import uuid4

        from foxhound.core.coordinator import Coordinator
        from foxhound.core.repo_registry import RepoRegistry, is_git_repo
        from foxhound.discovery.scanners import ScannerRegistry, scan_result_to_work_item

        registry = RepoRegistry(self.db)
        target = Path(repo_path or ".").resolve()

        if not target.is_dir():
            return {"error": 1, "new": 0, "skipped": 0, "promoted": 0}

        # Find or auto-register
        repo_id = None
        for repo in registry.list_repos():
            if Path(repo.path).resolve() == target:
                repo_id = repo.repo_id
                break

        if repo_id is None:
            if is_git_repo(target):
                repo = registry.register(target)
                repo_id = repo.repo_id
            else:
                return {"error": 1, "new": 0, "skipped": 0, "promoted": 0}

        coord = Coordinator(self.db)
        scanner_reg = ScannerRegistry()
        scanner_reg.register_defaults()

        known_fps = coord.get_known_fingerprints(repo_id)
        results = scanner_reg.scan_all(target)

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

        promoted = coord.promote_discovered_to_suggested(repo_id)

        return {
            "new": new_count,
            "skipped": skip_count,
            "promoted": promoted,
            "total_found": len(results),
        }

    # -- Doctor Checks --

    async def run_doctor(self) -> list[tuple[str, bool, str]]:
        """Run all environment health checks. Returns list of (name, passed, detail)."""
        return await self._run(self._doctor_checks)

    def _doctor_checks(self) -> list[tuple[str, bool, str]]:
        """Synchronous doctor checks — user-facing only."""
        import os
        import sys
        from pathlib import Path

        from foxhound.core.paths import CONFIG_NAME, foxhound_dir, db_path

        checks: list[tuple[str, bool, str]] = []

        # Python version
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        checks.append(("Python version", sys.version_info >= (3, 13), py_ver))

        # .foxhound directory
        fh_dir = foxhound_dir()
        checks.append(("Project initialized", fh_dir.is_dir(), "Ready" if fh_dir.is_dir() else "Run foxhound init"))

        # Database
        db = db_path()
        if db.exists():
            try:
                from foxhound.storage.database import Database
                db_instance = Database(db)
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
                    checks.append(("Database", False, f"Missing tables: {', '.join(sorted(missing))}"))
                else:
                    checks.append(("Database", True, f"{len(table_names)} tables"))
                db_instance.close()
            except Exception as e:
                checks.append(("Database", False, str(e)))
        else:
            checks.append(("Database", False, "Not found — run foxhound init"))

        # Config
        config_path = Path.cwd() / CONFIG_NAME
        if config_path.exists():
            try:
                import yaml
                config_data = yaml.safe_load(config_path.read_text())
                if config_data and "models" in config_data:
                    provider = config_data["models"].get("provider", "unknown")
                    checks.append(("Config", True, f"Provider: {provider}"))
                else:
                    checks.append(("Config", False, "Missing 'models' section"))
            except Exception:
                checks.append(("Config", False, "Invalid YAML"))
        else:
            checks.append(("Config", False, "foxhound.yaml not found"))

        # API keys
        key_names = {
            "ANTHROPIC_API_KEY": "Anthropic",
            "OPENAI_API_KEY": "OpenAI",
            "GITHUB_TOKEN": "GitHub",
        }
        found_keys = []
        for env_var, display_name in key_names.items():
            if os.environ.get(env_var):
                found_keys.append(display_name)
        if found_keys:
            checks.append(("API keys", True, ", ".join(found_keys)))
        else:
            checks.append(("API keys", False, "No API keys configured"))

        # Model tiers
        try:
            from foxhound.core.config import load_config
            from foxhound.core.models import ModelTier

            if config_path.exists():
                config = load_config(config_path)
                from foxhound.adapters.router import ModelRouter
                router = ModelRouter(config)
                init_errors = router.initialize()
                if init_errors:
                    for err in init_errors:
                        checks.append(("Model provider", False, err))
                else:
                    for tier in [ModelTier.REASONING, ModelTier.BALANCED, ModelTier.FAST]:
                        if router.is_tier_configured(tier):
                            try:
                                provider_name, model_id, _ = router.resolve(tier)
                                authenticated = provider_name in router.authenticated_providers
                                status = f"{model_id}" if authenticated else f"{model_id} (no auth)"
                                checks.append((f"Tier: {tier.value}", authenticated, status))
                            except Exception as exc:
                                checks.append((f"Tier: {tier.value}", False, str(exc)))
                        else:
                            checks.append((f"Tier: {tier.value}", False, "Not configured"))
        except Exception:
            pass

        # .gitignore
        gitignore_path = Path.cwd() / ".gitignore"
        if gitignore_path.exists():
            content = gitignore_path.read_text()
            has_foxhound = ".foxhound" in content
            if has_foxhound:
                checks.append((".gitignore", True, ".foxhound/ is ignored"))
            else:
                checks.append((".gitignore", False, ".foxhound/ not in .gitignore"))
        else:
            checks.append((".gitignore", False, "No .gitignore found"))

        return checks

    # -- Scout Fetch --

    async def run_scout_fetch(
        self,
        query: str | None = None,
        language: str | None = None,
        limit: int = 20,
    ) -> dict[str, int]:
        """Run the full scout fetch + score pipeline. Returns source counts."""
        import os

        def _do_fetch() -> dict[str, int]:
            from foxhound.scout.fetcher import ScoutFetcher, ScoutConfig
            from foxhound.scout.scoring import ScoringPipeline
            from foxhound.adapters.github_connector import HttpClient

            # Build a minimal HTTP client
            import json as json_mod
            import urllib.request
            from urllib.error import HTTPError, URLError
            from foxhound.adapters.github_connector import HttpResponse

            class _UrllibClient:
                def get(self, url, headers=None, params=None, timeout=30):
                    if params:
                        from urllib.parse import urlencode
                        url = f"{url}?{urlencode(params)}"
                    req = urllib.request.Request(url, headers=headers or {})
                    try:
                        with urllib.request.urlopen(req, timeout=timeout) as resp:
                            body = resp.read().decode()
                            try:
                                data = json_mod.loads(body)
                            except Exception:
                                data = None
                            return HttpResponse(
                                status_code=resp.status,
                                headers=dict(resp.headers),
                                json_data=data,
                            )
                    except HTTPError as e:
                        return HttpResponse(
                            status_code=e.code,
                            headers=dict(e.headers) if e.headers else {},
                            json_data=None,
                        )
                    except (URLError, TimeoutError):
                        return HttpResponse(
                            status_code=0, headers={}, json_data=None
                        )

            fetcher = ScoutFetcher(
                db=self.db,
                http_client=_UrllibClient(),
                github_token=os.environ.get("GITHUB_TOKEN"),
                reddit_client_id=os.environ.get("REDDIT_CLIENT_ID"),
                reddit_client_secret=os.environ.get("REDDIT_CLIENT_SECRET"),
            )
            summary = fetcher.fetch_all(
                force_refresh=True,
                language=language,
                limit=limit,
                query=query,
            )

            pipeline = ScoringPipeline(db=self.db)
            pipeline.score_all()

            counts: dict[str, int] = {}
            for r in summary.results:
                if r.error:
                    counts[r.source] = -1
                else:
                    counts[r.source] = r.new_items
            return counts

        return await self._run(_do_fetch)

    # -- Opportunities --

    async def list_opportunities(
        self, state: OpportunityState | None = None, limit: int = 100
    ) -> list[OpportunityDiscoveryItem]:
        """List opportunities, optionally filtered by state."""
        from foxhound.scout.opportunity import OpportunityManager

        mgr = OpportunityManager(self.db)
        if state:
            return await self._run(mgr.list_by_state, state, limit)
        return await self._run(mgr.list_by_state, OpportunityState.SUGGESTED, limit)

    async def approve_opportunity(self, opportunity_id: str) -> None:
        """Approve an opportunity."""
        from foxhound.scout.opportunity import OpportunityManager

        mgr = OpportunityManager(self.db)
        await self._run(mgr.approve, opportunity_id)

    async def reject_opportunity(self, opportunity_id: str) -> None:
        """Reject an opportunity."""
        from foxhound.scout.opportunity import OpportunityManager

        mgr = OpportunityManager(self.db)
        await self._run(mgr.reject, opportunity_id)

    async def delete_opportunity(self, opportunity_id: str) -> None:
        """Delete an opportunity."""
        from foxhound.scout.opportunity import OpportunityManager

        mgr = OpportunityManager(self.db)
        await self._run(mgr.delete, opportunity_id)

    async def get_opportunity(
        self, opportunity_id: str
    ) -> OpportunityDiscoveryItem | None:
        """Get a single opportunity by ID."""
        from foxhound.scout.opportunity import OpportunityManager

        mgr = OpportunityManager(self.db)
        return await self._run(mgr.get, opportunity_id)

    # -- Work Items --

    async def list_work_items(
        self, state: WorkItemState | None = None, limit: int = 100
    ) -> list[WorkItem]:
        """List work items, optionally filtered by state."""
        from foxhound.storage.database import WorkItemStore

        store = WorkItemStore(self.db)
        if state:
            return await self._run(store.list_by_state, state, limit)
        return await self._run(store.list_all)

    async def approve_work_item(self, work_item_id: str) -> None:
        """Approve a work item."""
        from foxhound.storage.database import WorkItemStore

        store = WorkItemStore(self.db)
        await self._run(store.update_state, work_item_id, WorkItemState.APPROVED)

    async def reject_work_item(self, work_item_id: str) -> None:
        """Reject a work item."""
        from foxhound.storage.database import WorkItemStore

        store = WorkItemStore(self.db)
        await self._run(store.update_state, work_item_id, WorkItemState.REJECTED)

    # -- Runs --

    async def list_runs(self, limit: int = 50) -> list[Any]:
        """List recent runs."""
        from foxhound.storage.database import RunStore

        store = RunStore(self.db)
        return await self._run(store.list_recent, limit=limit)

    # -- Stats --

    async def get_stats(self) -> dict[str, int]:
        """Get queue and system stats including opportunities."""
        from foxhound.core.models import OpportunityState
        from foxhound.storage.database import WorkItemStore

        store = WorkItemStore(self.db)
        items = await self._run(store.list_all)
        by_state: dict[str, int] = {}
        for item in items:
            state = item.state.value
            by_state[state] = by_state.get(state, 0) + 1
        by_state["total"] = len(items)

        # Opportunity counts
        from foxhound.scout.opportunity import OpportunityManager
        mgr = OpportunityManager(self.db)
        for opp_state in [OpportunityState.SUGGESTED, OpportunityState.APPROVED, OpportunityState.REJECTED]:
            opps = await self._run(mgr.list_by_state, opp_state, 1000)
            by_state[f"opp_{opp_state.value}"] = len(opps)

        return by_state

    # -- Retention --

    async def get_retention_status(self) -> dict[str, Any]:
        """Get retention/storage status."""
        from foxhound.observer.retention import RetentionPolicy

        policy = RetentionPolicy(self.db)
        return await self._run(policy.get_status)

    async def run_prune(self) -> dict[str, int]:
        """Prune expired artifacts."""
        from foxhound.observer.retention import RetentionPolicy

        policy = RetentionPolicy(self.db)
        result = await self._run(policy.prune)
        return {
            "artifacts_removed": result.artifacts_removed,
            "files_deleted": result.files_deleted,
            "space_freed": result.space_freed_bytes,
            "errors": len(result.errors),
        }

    async def run_compact(self, days: int = 30) -> int:
        """Compact event streams. Returns events compacted."""
        from foxhound.observer.retention import RetentionPolicy

        policy = RetentionPolicy(self.db)
        result = await self._run(policy.compact_events, days)
        return result.events_compacted

    # -- Analyze --

    async def list_failed_runs(self, limit: int = 10) -> list[Any]:
        """List recent failed runs."""
        from foxhound.storage.database import RunStore
        from foxhound.core.models import RunState

        store = RunStore(self.db)
        all_runs = await self._run(store.list_recent, limit=100)
        failed = [r for r in all_runs if r.state == RunState.FAILED]
        return failed[:limit]

    async def analyze_run(self, run_id: str) -> Any:
        """Analyze a failed run."""
        from foxhound.analyzer.engine import AnalyzerEngine

        engine = AnalyzerEngine(self.db)
        return await self._run(engine.analyze_run, run_id)

    # -- Repos --

    async def list_repos(self) -> list[Any]:
        """List registered repositories."""
        from foxhound.core.repo_registry import RepoRegistry

        registry = RepoRegistry(self.db)
        return await self._run(registry.list_all)
