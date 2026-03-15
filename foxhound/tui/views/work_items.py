"""Work Items view — browse and approve/reject work items."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable

from foxhound.tui.widgets.detail_panel import DetailPanel
from foxhound.tui.widgets.state_badge import state_markup

if TYPE_CHECKING:
    from foxhound.tui.data import TUIData


class WorkItemsView(Vertical):
    """Interactive list for reviewing work items."""

    BINDINGS = [
        Binding("a", "approve", "Approve", show=True),
        Binding("x", "reject", "Reject", show=True),
        Binding("f5", "refresh", "Refresh", show=True),
    ]

    def __init__(self, data: TUIData, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._data = data
        self._item_ids: list[str] = []

    def compose(self) -> ComposeResult:
        """Build the work items layout."""
        yield DataTable(id="work-items-table")
        yield DetailPanel(
            buttons=[
                ("Approve", "approve", "success"),
                ("Reject", "reject", "error"),
            ],
            id="work-items-detail",
        )

    def on_mount(self) -> None:
        """Set up table and load data."""
        table = self.query_one("#work-items-table", DataTable)
        table.add_columns("ID", "State", "Risk", "Title", "Source")
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.call_after_refresh(self._load_data)

    def on_show(self) -> None:
        """Refresh data when view becomes visible."""
        self.call_after_refresh(self._load_data)

    async def _load_data(self) -> None:
        """Load work items from the database."""
        table = self.query_one("#work-items-table", DataTable)
        table.clear()
        self._item_ids.clear()

        items = await self._data.list_work_items(limit=100)

        for item in items:
            risk = getattr(item, "risk_level", "—")
            table.add_row(
                item.work_item_id[:12],
                item.state.value,
                risk,
                item.title[:50],
                item.source_type if hasattr(item, "source_type") else "—",
            )
            self._item_ids.append(item.work_item_id)

        if not items:
            detail = self.query_one("#work-items-detail", DetailPanel)
            detail.detail_text = (
                "No work items found.\n"
                "Run [bold]foxhound scan[/bold] to discover work items."
            )

    def on_data_table_cursor_moved(self, event: DataTable.CursorMoved) -> None:
        """Update detail panel."""
        if event.cursor_row < len(self._item_ids):
            table = self.query_one("#work-items-table", DataTable)
            row = table.get_row_at(event.cursor_row)
            detail = self.query_one("#work-items-detail", DetailPanel)
            detail.detail_text = (
                f"[bold]{row[3]}[/bold]\n"
                f"ID: {row[0]}  State: {row[1]}  Risk: {row[2]}\n\n"
                f"[dim][a] Approve  [x] Reject  [F5] Refresh[/dim]"
            )

    async def on_detail_panel_button_pressed(
        self, message: DetailPanel.ButtonPressed
    ) -> None:
        """Handle button clicks from the detail panel."""
        if message.action == "approve":
            await self.action_approve()
        elif message.action == "reject":
            await self.action_reject()

    def _get_selected_id(self) -> str | None:
        """Get the work item ID for the currently selected row."""
        table = self.query_one("#work-items-table", DataTable)
        if table.cursor_row is not None and table.cursor_row < len(self._item_ids):
            return self._item_ids[table.cursor_row]
        return None

    async def action_approve(self) -> None:
        """Approve the selected work item."""
        item_id = self._get_selected_id()
        if item_id is None:
            return
        await self._data.approve_work_item(item_id)
        self.app.notify("Approved")
        await self._load_data()

    async def action_reject(self) -> None:
        """Reject the selected work item."""
        item_id = self._get_selected_id()
        if item_id is None:
            return
        await self._data.reject_work_item(item_id)
        self.app.notify("Rejected")
        await self._load_data()

    async def action_refresh(self) -> None:
        """Reload work items."""
        await self._load_data()
        self.app.notify("Refreshed")
