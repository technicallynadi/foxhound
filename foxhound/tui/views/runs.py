"""Runs view — browse execution history."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable

from foxhound.tui.widgets.detail_panel import DetailPanel

if TYPE_CHECKING:
    from foxhound.tui.data import TUIData


class RunsView(Vertical):
    """Run history table with detail panel."""

    BINDINGS = [
        Binding("f5", "refresh", "Refresh", show=True),
    ]

    def __init__(self, data: TUIData, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._data = data

    def compose(self) -> ComposeResult:
        """Build the runs layout."""
        yield DataTable(id="runs-table")
        yield DetailPanel(id="runs-detail")

    def on_mount(self) -> None:
        """Set up table and load data."""
        table = self.query_one("#runs-table", DataTable)
        table.add_columns("Run ID", "State", "Worker", "Cost", "Duration")
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.call_after_refresh(self._load_data)

    def on_show(self) -> None:
        """Refresh data when view becomes visible."""
        self.call_after_refresh(self._load_data)

    async def _load_data(self) -> None:
        """Load runs from the database."""
        table = self.query_one("#runs-table", DataTable)
        table.clear()

        runs = await self._data.list_runs(limit=50)

        for run in runs:
            table.add_row(
                run.run_id[:12],
                run.state.value,
                run.worker_type,
                f"${run.total_cost:.4f}",
                f"{0:.1f}s",
            )

        if not runs:
            detail = self.query_one("#runs-detail", DetailPanel)
            detail.detail_text = (
                "No runs found.\n"
                "Approve a work item and run [bold]foxhound run <id>[/bold]."
            )

    async def action_refresh(self) -> None:
        """Reload runs."""
        await self._load_data()
        self.app.notify("Refreshed")
