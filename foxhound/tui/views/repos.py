"""Repos view — registered repositories."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable

if TYPE_CHECKING:
    from foxhound.tui.data import TUIData


class ReposView(Vertical):
    """Table of registered repositories."""

    BINDINGS = [
        Binding("f5", "refresh", "Refresh", show=True),
    ]

    def __init__(self, data: TUIData, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._data = data

    def compose(self) -> ComposeResult:
        """Build the repos layout."""
        yield DataTable(id="repos-table")

    def on_mount(self) -> None:
        """Set up table and load data."""
        table = self.query_one("#repos-table", DataTable)
        table.add_columns("Name", "Language", "Branch", "Path", "ID")
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.call_after_refresh(self._load_data)

    async def _load_data(self) -> None:
        """Load repos from the database."""
        table = self.query_one("#repos-table", DataTable)
        table.clear()

        try:
            repos = await self._data.list_repos()
            for repo in repos:
                table.add_row(
                    repo.name,
                    repo.language or "—",
                    repo.default_branch or "—",
                    str(repo.path)[:40],
                    repo.repo_id[:12],
                )
        except Exception:
            pass

    async def action_refresh(self) -> None:
        """Reload repos."""
        await self._load_data()
        self.app.notify("Refreshed")
