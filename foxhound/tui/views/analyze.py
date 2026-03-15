"""Analyze view — failure analysis with interactive run selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Button, DataTable, Static

from foxhound.tui.widgets.detail_panel import DetailPanel

if TYPE_CHECKING:
    from foxhound.tui.data import TUIData


class AnalyzeView(Vertical):
    """Displays failed runs and lets you analyze them inline."""

    def __init__(self, data: TUIData, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._data = data
        self._run_ids: list[str] = []

    def compose(self) -> ComposeResult:
        """Build the analyze layout."""
        yield DataTable(id="failed-runs-table")
        yield DetailPanel(
            buttons=[
                ("Analyze Selected", "analyze", "success"),
                ("Refresh", "refresh", "primary"),
            ],
            id="analyze-detail",
        )

    def on_mount(self) -> None:
        """Set up table and load data."""
        table = self.query_one("#failed-runs-table", DataTable)
        table.add_columns("Run ID", "Worker", "State", "Cost", "Failure")
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.call_after_refresh(self._load_data)

    def on_show(self) -> None:
        """Refresh when view becomes visible."""
        self.call_after_refresh(self._load_data)

    async def _load_data(self) -> None:
        """Load failed runs."""
        table = self.query_one("#failed-runs-table", DataTable)
        table.clear()
        self._run_ids.clear()

        try:
            runs = await self._data.list_failed_runs(limit=20)
        except Exception:
            detail = self.query_one("#analyze-detail", DetailPanel)
            detail.detail_text = "No failed runs to analyze."
            return

        for run in runs:
            failure = getattr(run, "failure_class", "") or "—"
            table.add_row(
                run.run_id[:12],
                run.worker_type,
                run.state.value,
                f"${run.total_cost:.4f}",
                str(failure)[:30],
            )
            self._run_ids.append(run.run_id)

        if not runs:
            detail = self.query_one("#analyze-detail", DetailPanel)
            detail.detail_text = "No failed runs to analyze."

    async def on_detail_panel_button_pressed(
        self, message: DetailPanel.ButtonPressed
    ) -> None:
        """Handle button clicks."""
        if message.action == "analyze":
            await self._do_analyze()
        elif message.action == "refresh":
            await self._load_data()
            self.app.notify("Refreshed")

    async def _do_analyze(self) -> None:
        """Analyze the selected failed run."""
        table = self.query_one("#failed-runs-table", DataTable)
        if table.cursor_row is None or table.cursor_row >= len(self._run_ids):
            self.app.notify("Select a failed run first", severity="warning")
            return

        run_id = self._run_ids[table.cursor_row]
        detail = self.query_one("#analyze-detail", DetailPanel)
        detail.detail_text = f"Analyzing run {run_id[:12]}..."

        try:
            diagnosis = await self._data.analyze_run(run_id)

            lines = [
                f"[bold]Analysis: {run_id[:12]}[/bold]\n",
                f"Failure class: {diagnosis.failure_class}",
            ]
            if diagnosis.context_gaps:
                lines.append(f"\nContext gaps:")
                for gap in diagnosis.context_gaps:
                    lines.append(f"  - {gap}")
            if diagnosis.readiness_issues:
                lines.append(f"\nReadiness issues:")
                for issue in diagnosis.readiness_issues:
                    lines.append(f"  - {issue}")
            if diagnosis.recommendations:
                lines.append(f"\nRecommendations:")
                for rec in diagnosis.recommendations:
                    lines.append(f"  - {rec}")

            detail.detail_text = "\n".join(lines)
        except Exception as e:
            detail.detail_text = f"Analysis failed: {e}"
