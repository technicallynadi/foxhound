"""Scout Inbox view — browse and act on discovered opportunities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import DataTable, Input, Static

from foxhound.tui.widgets.detail_panel import DetailPanel

if TYPE_CHECKING:
    from foxhound.tui.data import TUIData


class ScoutInboxTable(DataTable[str]):
    """Scout inbox table with inline action keybindings."""

    BINDINGS = [
        Binding("a", "approve", "Approve", show=True),
        Binding("r", "reject", "Reject", show=True),
        Binding("delete", "delete", "Delete", show=True),
        Binding("f", "fetch", "Fetch New", show=True),
        Binding("f5", "refresh", "Refresh", show=True),
        Binding("q", "quit_app", "Quit", show=True),
    ]

    class ActionRequested(Message):
        """Emitted when user presses an action key."""

        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    def action_approve(self) -> None:
        """Forward approve to parent view."""
        self.post_message(self.ActionRequested("approve"))

    def action_reject(self) -> None:
        """Forward reject to parent view."""
        self.post_message(self.ActionRequested("reject"))

    def action_delete(self) -> None:
        """Forward delete to parent view."""
        self.post_message(self.ActionRequested("delete"))

    def action_refresh(self) -> None:
        """Forward refresh to parent view."""
        self.post_message(self.ActionRequested("refresh"))

    def action_fetch(self) -> None:
        """Forward fetch to parent view."""
        self.post_message(self.ActionRequested("fetch"))

    def action_quit_app(self) -> None:
        """Quit the application."""
        self.app.exit()

    def watch_cursor_coordinate(self, old: object, new: object) -> None:
        """Forward cursor change to parent view."""
        super().watch_cursor_coordinate(old, new)
        self.post_message(self.ActionRequested(f"cursor:{self.cursor_row}"))


class ScoutInboxView(Vertical):
    """Interactive inbox for reviewing scout opportunities."""

    def __init__(self, data: TUIData, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._data = data
        self._opportunity_ids: list[str] = []
        self._query: str = ""

    def compose(self) -> ComposeResult:
        """Build the scout inbox layout."""
        yield Input(
            placeholder="Search opportunities... (Enter to filter, Esc to clear)",
            id="scout-search",
        )
        yield ScoutInboxTable(id="scout-table")
        yield DetailPanel(
            buttons=[
                ("Approve", "approve", "success"),
                ("Reject", "reject", "error"),
                ("Delete", "delete", "warning"),
                ("Fetch New", "fetch", "primary"),
            ],
            id="scout-detail",
        )

    def on_mount(self) -> None:
        """Set up table and load data."""
        table = self.query_one("#scout-table", ScoutInboxTable)
        table.add_columns("Score", "Source", "Title", "Tags")
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.call_after_refresh(self._load_data)

    def on_show(self) -> None:
        """Refresh data when view becomes visible."""
        self.call_after_refresh(self._load_data)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Filter opportunities by search query."""
        self._query = event.value.strip()
        await self._load_data()
        # Move focus back to the table
        table = self.query_one("#scout-table", ScoutInboxTable)
        table.focus()

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Clear filter when input is emptied."""
        if not event.value.strip() and self._query:
            self._query = ""
            await self._load_data()

    async def on_detail_panel_button_pressed(
        self, message: DetailPanel.ButtonPressed
    ) -> None:
        """Handle button clicks from the detail panel."""
        actions = {
            "approve": self._do_approve,
            "reject": self._do_reject,
            "delete": self._do_delete,
            "fetch": self._do_fetch,
        }
        handler = actions.get(message.action)
        if handler:
            await handler()

    async def on_scout_inbox_table_action_requested(
        self, message: ScoutInboxTable.ActionRequested
    ) -> None:
        """Handle action key presses and cursor moves from the table."""
        if message.action.startswith("cursor:"):
            row = int(message.action.split(":")[1])
            await self._show_detail(row)
            return

        actions = {
            "approve": self._do_approve,
            "reject": self._do_reject,
            "delete": self._do_delete,
            "refresh": self._do_refresh,
            "fetch": self._do_fetch,
        }
        handler = actions.get(message.action)
        if handler:
            await handler()

    async def _do_approve(self) -> None:
        """Approve the selected opportunity."""
        opp_id = self._get_selected_id()
        if opp_id is None:
            return
        await self._data.approve_opportunity(opp_id)
        self.app.notify("Approved")
        await self._load_data()

    async def _do_reject(self) -> None:
        """Reject the selected opportunity."""
        opp_id = self._get_selected_id()
        if opp_id is None:
            return
        await self._data.reject_opportunity(opp_id)
        self.app.notify("Rejected")
        await self._load_data()

    async def _do_delete(self) -> None:
        """Delete the selected opportunity."""
        opp_id = self._get_selected_id()
        if opp_id is None:
            return
        await self._data.delete_opportunity(opp_id)
        self.app.notify("Deleted")
        await self._load_data()

    async def _do_refresh(self) -> None:
        """Reload opportunities from the database."""
        await self._load_data()
        self.app.notify("Refreshed")

    async def _do_fetch(self) -> None:
        """Fetch new opportunities from all sources, using search query if set."""
        query = self._query or None
        if query:
            self.app.notify(f"Fetching '{query}' from all sources...")
        else:
            self.app.notify("Fetching from all sources...")

        detail = self.query_one("#scout-detail", DetailPanel)
        detail.detail_text = f"Fetching{' ' + repr(query) if query else ''} from GitHub, HN, Reddit..."

        counts = await self._data.run_scout_fetch(query=query, limit=20)

        parts = []
        for source, count in counts.items():
            if count < 0:
                parts.append(f"{source}: error")
            else:
                parts.append(f"{source}: {count} new")
        summary = ", ".join(parts)

        await self._load_data()
        self.app.notify(f"Fetched: {summary}")

    async def _load_data(self) -> None:
        """Load opportunities from the database."""
        from foxhound.core.models import OpportunityState

        table = self.query_one("#scout-table", DataTable)
        table.clear()
        self._opportunity_ids.clear()

        all_items = await self._data.list_opportunities(
            state=OpportunityState.SUGGESTED, limit=200
        )

        if self._query:
            q = self._query.lower()
            items = [
                item for item in all_items
                if q in item.title.lower()
                or q in (item.description or "").lower()
                or q in item.source_type.lower()
                or any(q in tag.lower() for tag in (item.tags or []))
            ]
        else:
            items = all_items

        for item in items:
            has_llm = item.evidence.get("llm_scored", False)
            score_text = (
                f"{item.business_value_score:.0%}" if has_llm else "pending"
            )
            tags = ", ".join(item.tags[:3]) if item.tags else ""
            source = item.source_type
            if len(source) > 12:
                source = source[:11] + "…"
            title = item.title[:50]

            table.add_row(score_text, source, title, tags)
            self._opportunity_ids.append(item.opportunity_id)

        if not items:
            detail = self.query_one("#scout-detail", DetailPanel)
            detail.detail_text = (
                "No opportunities to review.\n"
                "Press [bold]f[/bold] to fetch new opportunities."
            )

    async def _show_detail(self, row_index: int) -> None:
        """Show detail for the selected row."""
        if row_index < 0 or row_index >= len(self._opportunity_ids):
            return

        opp_id = self._opportunity_ids[row_index]
        item = await self._data.get_opportunity(opp_id)
        if item is None:
            return

        detail = self.query_one("#scout-detail", DetailPanel)
        evidence = item.evidence or {}
        has_llm = evidence.get("llm_scored", False)

        if has_llm:
            scores = (
                f"Velocity: {item.credibility_score:.0%}  "
                f"Improvability: {item.novelty_score:.0%}  "
                f"Buildability: {item.actionability_score:.0%}  "
                f"Value: {item.business_value_score:.0%}"
            )
        else:
            scores = "Scores: pending (awaiting LLM evaluation)"

        url = item.source_url or ""
        desc = item.description[:200] if item.description else ""
        lang = evidence.get("language", "")
        license_t = evidence.get("license_type", "")

        meta_parts = []
        if lang:
            meta_parts.append(f"Language: {lang}")
        if license_t:
            meta_parts.append(f"License: {license_t}")
        meta = " | ".join(meta_parts) if meta_parts else ""

        lines = [
            f"[bold]{item.title}[/bold]",
            f"Source: {item.source_type}  {url}",
            scores,
        ]
        if desc:
            lines.append(desc)
        if meta:
            lines.append(f"[dim]{meta}[/dim]")

        detail.detail_text = "\n".join(lines)

    def _get_selected_id(self) -> str | None:
        """Get the opportunity ID for the currently selected row."""
        table = self.query_one("#scout-table", DataTable)
        if table.cursor_row is not None and table.cursor_row < len(
            self._opportunity_ids
        ):
            return self._opportunity_ids[table.cursor_row]
        return None

