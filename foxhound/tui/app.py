"""Foxhound operator TUI built with Textual.

Provides a dashboard for work items, runs, queue stats, and
an approval workflow. Launchable via `foxhound tui`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

if TYPE_CHECKING:
    from foxhound.storage.database import Database

DB_NAME = "foxhound.db"
FOXHOUND_DIR = ".foxhound"


def _db_path() -> Path:
    """Return the database path."""
    return Path.cwd() / FOXHOUND_DIR / DB_NAME


class StatsPanel(Static):
    """Displays queue and system statistics."""

    stats_text: reactive[str] = reactive("Loading...")

    def render(self) -> str:
        """Render stats text."""
        return self.stats_text


class WorkItemsTable(DataTable[str]):
    """Table displaying work items with state and metadata."""

    def on_mount(self) -> None:
        """Set up table columns."""
        self.add_columns("ID", "State", "Title", "Repo", "Risk")
        self.cursor_type = "row"


class RunsTable(DataTable[str]):
    """Table displaying run history."""

    def on_mount(self) -> None:
        """Set up table columns."""
        self.add_columns("Run ID", "State", "Worker", "Cost", "Duration")
        self.cursor_type = "row"


class FoxhoundApp(App[None]):
    """Foxhound operator TUI application."""

    TITLE = "Foxhound"
    SUB_TITLE = "Product Discovery Engine"
    CSS = """
    StatsPanel {
        height: 5;
        padding: 1;
        background: $surface;
        border: solid $primary;
        margin-bottom: 1;
    }
    DataTable {
        height: 1fr;
    }
    #approval-info {
        height: 8;
        padding: 1;
        background: $surface;
        border: solid $accent;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("a", "approve", "Approve"),
        Binding("x", "reject", "Reject"),
    ]

    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__()
        self._db_path = db_path or _db_path()
        self._db: Database | None = None

    def compose(self) -> ComposeResult:
        """Build the TUI layout."""
        yield Header()
        yield StatsPanel(id="stats")
        with TabbedContent():
            with TabPane("Work Items", id="tab-items"):
                yield WorkItemsTable(id="items-table")
            with TabPane("Runs", id="tab-runs"):
                yield RunsTable(id="runs-table")
            with TabPane("Approval", id="tab-approval"):
                yield Vertical(
                    Static(
                        "Select a work item and press [bold]a[/bold] to approve "
                        "or [bold]x[/bold] to reject.",
                        id="approval-info",
                    ),
                )
        yield Footer()

    def on_mount(self) -> None:
        """Load data on startup."""
        self._load_data()

    def _get_db(self) -> Database | None:
        """Get or create database connection."""
        if not self._db_path.exists():
            return None
        if self._db is None:
            from foxhound.storage.database import Database

            self._db = Database(self._db_path)
        return self._db

    def _load_data(self) -> None:
        """Load work items, runs, and stats from the database."""
        db = self._get_db()
        if db is None:
            stats = self.query_one("#stats", StatsPanel)
            stats.stats_text = "Not initialized. Run foxhound init first."
            return

        self._load_stats(db)
        self._load_work_items(db)
        self._load_runs(db)

    def _load_stats(self, db: Database) -> None:
        """Load queue and system stats."""
        from foxhound.core.models import WorkItemState
        from foxhound.storage.database import WorkItemStore

        stats_panel = self.query_one("#stats", StatsPanel)
        try:
            store = WorkItemStore(db)
            items = store.list_all()
            total = len(items)
            by_state: dict[str, int] = {}
            for item in items:
                state = item.state.value
                by_state[state] = by_state.get(state, 0) + 1

            suggested = by_state.get(WorkItemState.SUGGESTED.value, 0)
            approved = by_state.get(WorkItemState.APPROVED.value, 0)
            executing = by_state.get(WorkItemState.EXECUTING.value, 0)

            stats_panel.stats_text = (
                f"Work Items: {total} total | "
                f"{suggested} suggested | "
                f"{approved} approved | "
                f"{executing} executing"
            )
        except Exception:
            stats_panel.stats_text = "Stats unavailable"

    def _load_work_items(self, db: Database) -> None:
        """Populate the work items table."""
        from foxhound.storage.database import WorkItemStore

        table = self.query_one("#items-table", WorkItemsTable)
        table.clear()
        try:
            store = WorkItemStore(db)
            items = store.list_all()
            for item in items[:100]:
                table.add_row(
                    item.work_item_id[:12],
                    item.state.value,
                    item.title[:50],
                    item.repo_id[:12],
                    item.risk_level if hasattr(item, "risk_level") else "—",
                )
        except Exception:
            pass

    def _load_runs(self, db: Database) -> None:
        """Populate the runs table."""
        table = self.query_one("#runs-table", RunsTable)
        table.clear()
        try:
            from foxhound.storage.database import RunStore

            run_store = RunStore(db)
            runs = run_store.list_recent(limit=50)
            for run in runs:
                table.add_row(
                    run.run_id[:12],
                    run.state.value,
                    run.worker_type,
                    f"${run.total_cost:.4f}",
                    f"{0:.1f}s",
                )
        except Exception:
            pass

    def action_refresh(self) -> None:
        """Refresh all data."""
        self._load_data()

    def action_approve(self) -> None:
        """Approve selected work item."""
        table = self.query_one("#items-table", WorkItemsTable)
        if table.cursor_row is not None:
            row = table.get_row_at(table.cursor_row)
            if row:
                work_item_id = str(row[0])
                self._approve_item(work_item_id)

    def action_reject(self) -> None:
        """Reject selected work item."""
        table = self.query_one("#items-table", WorkItemsTable)
        if table.cursor_row is not None:
            row = table.get_row_at(table.cursor_row)
            if row:
                work_item_id = str(row[0])
                self._reject_item(work_item_id)

    def _approve_item(self, work_item_id_prefix: str) -> None:
        """Approve a work item by ID prefix."""
        db = self._get_db()
        if db is None:
            return
        try:
            from foxhound.core.models import WorkItemState
            from foxhound.storage.database import WorkItemStore

            store = WorkItemStore(db)
            items = store.list_all()
            for item in items:
                if item.work_item_id.startswith(work_item_id_prefix):
                    if item.state == WorkItemState.SUGGESTED:
                        store.update_state(
                            item.work_item_id, WorkItemState.APPROVED
                        )
                        self.notify(f"Approved: {item.title[:40]}")
                        self._load_data()
                    else:
                        self.notify(
                            f"Cannot approve: state is {item.state.value}",
                            severity="warning",
                        )
                    return
            self.notify(f"Item not found: {work_item_id_prefix}", severity="error")
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")

    def _reject_item(self, work_item_id_prefix: str) -> None:
        """Reject a work item by ID prefix."""
        db = self._get_db()
        if db is None:
            return
        try:
            from foxhound.core.models import WorkItemState
            from foxhound.storage.database import WorkItemStore

            store = WorkItemStore(db)
            items = store.list_all()
            for item in items:
                if item.work_item_id.startswith(work_item_id_prefix):
                    if item.state == WorkItemState.SUGGESTED:
                        store.update_state(
                            item.work_item_id, WorkItemState.REJECTED
                        )
                        self.notify(f"Rejected: {item.title[:40]}")
                        self._load_data()
                    else:
                        self.notify(
                            f"Cannot reject: state is {item.state.value}",
                            severity="warning",
                        )
                    return
            self.notify(f"Item not found: {work_item_id_prefix}", severity="error")
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")
