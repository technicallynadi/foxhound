"""Doctor view — environment health checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Static

if TYPE_CHECKING:
    from foxhound.tui.data import TUIData


class DoctorView(Vertical):
    """Environment health check results with re-run button."""

    def __init__(self, data: TUIData, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._data = data
        self._initial_mount = True

    def compose(self) -> ComposeResult:
        """Build the doctor layout."""
        yield DataTable(id="doctor-table")
        yield Static("", id="doctor-summary")
        with Horizontal(id="doctor-buttons"):
            yield Button("Run Checks", id="btn-run-checks", variant="success")

    def on_mount(self) -> None:
        """Set up table and run checks."""
        table = self.query_one("#doctor-table", DataTable)
        table.add_columns("Check", "Status", "Details")
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.call_after_refresh(self._run_checks)

    def on_show(self) -> None:
        """Re-run checks when view becomes visible (skip initial mount)."""
        if self._initial_mount:
            self._initial_mount = False
            return
        self.call_after_refresh(self._run_checks)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "btn-run-checks":
            await self._run_checks()
            self.app.notify("Checks complete")

    async def _run_checks(self) -> None:
        """Run doctor checks and populate the table."""
        table = self.query_one("#doctor-table", DataTable)
        table.clear()

        checks = await self._data.run_doctor()

        all_pass = True
        for name, passed, detail in checks:
            icon = "\u2713" if passed else "\u2717"
            if not passed:
                all_pass = False
            table.add_row(name, icon, detail)

        summary = self.query_one("#doctor-summary", Static)
        if all_pass:
            summary.update("[bold green]All checks passed.[/bold green]")
        else:
            failed = sum(1 for _, p, _ in checks if not p)
            summary.update(f"[bold red]{failed} check(s) failed.[/bold red]")
