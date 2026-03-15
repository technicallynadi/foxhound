"""Dashboard view — stats and queue overview."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

if TYPE_CHECKING:
    from foxhound.tui.data import TUIData


class DashboardView(Vertical):
    """System overview with queue stats and recent activity."""

    def __init__(self, data: TUIData, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._data = data

    def compose(self) -> ComposeResult:
        """Build the dashboard layout."""
        yield Static("Loading...", id="dash-stats")
        with Horizontal(id="dash-buttons"):
            yield Button("Scan Repo", id="btn-scan", variant="success")
            yield Button("Refresh", id="btn-dash-refresh", variant="primary")

    def on_mount(self) -> None:
        """Load stats on mount."""
        self.call_after_refresh(self._load_stats)

    def on_show(self) -> None:
        """Refresh stats when view becomes visible."""
        self.call_after_refresh(self._load_stats)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "btn-scan":
            await self._run_scan()
        elif event.button.id == "btn-dash-refresh":
            await self._load_stats()
            self.app.notify("Refreshed")

    async def _run_scan(self) -> None:
        """Run discovery scanners on the current repo."""
        self.app.notify("Scanning repository...")
        widget = self.query_one("#dash-stats", Static)
        widget.update("[bold]Scanning...[/bold]\n\nLooking for TODOs, bugs, dead code, and issues...")

        result = await self._data.run_scan()

        if result.get("error"):
            self.app.notify("Scan failed — not a valid repo directory", severity="error")
        else:
            self.app.notify(
                f"Scan complete: {result['new']} new, "
                f"{result['skipped']} skipped, {result['promoted']} promoted"
            )

        await self._load_stats()

    async def _load_stats(self) -> None:
        """Load and display queue statistics."""
        stats = await self._data.get_stats()

        total = stats.get("total", 0)
        suggested = stats.get("suggested", 0)
        approved = stats.get("approved", 0)
        executing = stats.get("executing", 0)
        completed = stats.get("completed", 0)
        failed = stats.get("failed", 0)

        opp_suggested = stats.get("opp_suggested", 0)
        opp_approved = stats.get("opp_approved", 0)
        opp_rejected = stats.get("opp_rejected", 0)

        text = (
            f"[bold]Scout Opportunities[/bold]\n\n"
            f"  [cyan]Pending review:[/cyan]    {opp_suggested}\n"
            f"  [green]Approved:[/green]          {opp_approved}\n"
            f"  [red]Rejected:[/red]          {opp_rejected}\n"
            f"\n"
            f"[bold]Work Items[/bold]\n\n"
            f"  Total:             {total}\n"
            f"  [cyan]Suggested:[/cyan]         {suggested}\n"
            f"  [green]Approved:[/green]          {approved}\n"
            f"  [magenta]Executing:[/magenta]         {executing}\n"
            f"  [bright_green]Completed:[/bright_green]         {completed}\n"
            f"  [bright_red]Failed:[/bright_red]            {failed}"
        )

        widget = self.query_one("#dash-stats", Static)
        widget.update(text)
