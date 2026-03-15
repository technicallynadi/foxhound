"""Foxhound TUI — unified interactive dashboard.

Sidebar navigation with ContentSwitcher for instant view switching.
All views preserve state when navigating between them.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import ContentSwitcher, Footer, Header, Static

from foxhound.tui.data import TUIData
from foxhound.tui.styles import APP_CSS
from foxhound.tui.widgets.sidebar import NAV_ITEMS, NavItem, Sidebar


class FoxhoundApp(App[None]):
    """Foxhound unified TUI application."""

    TITLE = "Foxhound"
    SUB_TITLE = "Product Discovery Engine"
    CSS = APP_CSS

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("f1", "switch('dashboard')", "Dashboard", show=True),
        Binding("f2", "switch('scout-inbox')", "Scout", show=True),
        Binding("f3", "switch('work-items')", "Work Items", show=True),
        Binding("f4", "switch('runs')", "Runs", show=True),
        Binding("f5", "switch('doctor')", "Doctor", show=False),
        Binding("f6", "switch('analyze')", "Analyze", show=False),
        Binding("f7", "switch('repos')", "Repos", show=False),
        Binding("f8", "switch('retention')", "Retention", show=False),
    ]

    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__()
        root = db_path.parent.parent if db_path else None
        self.data = TUIData(root=root)

    def compose(self) -> ComposeResult:
        """Build the TUI layout."""
        yield Header()
        with Horizontal():
            yield Sidebar(id="sidebar")
            with ContentSwitcher(id="main-content", initial="dashboard"):
                yield self._make_view("dashboard", "Dashboard")
                yield self._make_view("scout-inbox", "Scout Inbox")
                yield self._make_view("work-items", "Work Items")
                yield self._make_view("runs", "Runs")
                yield self._make_view("doctor", "Doctor")
                yield self._make_view("analyze", "Analyze")
                yield self._make_view("repos", "Repos")
                yield self._make_view("retention", "Retention")
        yield Footer()

    def _make_view(self, view_id: str, title: str) -> Vertical:
        """Create a placeholder view container. Real views mount into these."""
        return Vertical(
            Static(f" {title}", classes="view-title"),
            Static("Loading...", classes="empty-state", id=f"{view_id}-content"),
            id=view_id,
        )

    async def on_mount(self) -> None:
        """Load views after mount."""
        if not self.data.is_initialized():
            self.notify(
                "Not initialized. Run foxhound init first.", severity="error"
            )
            return
        await self._load_views()

    async def _load_views(self) -> None:
        """Replace placeholder content with real view widgets."""
        from foxhound.tui.views.dashboard import DashboardView
        from foxhound.tui.views.scout_inbox import ScoutInboxView
        from foxhound.tui.views.work_items import WorkItemsView
        from foxhound.tui.views.runs import RunsView
        from foxhound.tui.views.doctor import DoctorView
        from foxhound.tui.views.analyze import AnalyzeView
        from foxhound.tui.views.repos import ReposView
        from foxhound.tui.views.retention import RetentionView

        view_map: dict[str, type] = {
            "dashboard": DashboardView,
            "scout-inbox": ScoutInboxView,
            "work-items": WorkItemsView,
            "runs": RunsView,
            "doctor": DoctorView,
            "analyze": AnalyzeView,
            "repos": ReposView,
            "retention": RetentionView,
        }

        for view_id, view_cls in view_map.items():
            container = self.query_one(f"#{view_id}", Vertical)
            placeholder = container.query_one(f"#{view_id}-content")
            await placeholder.remove()
            await container.mount(view_cls(data=self.data, id=f"{view_id}-view"))

    def action_switch(self, view_id: str) -> None:
        """Switch to a different view."""
        switcher = self.query_one("#main-content", ContentSwitcher)
        switcher.current = view_id
        sidebar = self.query_one("#sidebar", Sidebar)
        sidebar.active_view = view_id

    def on_nav_item_selected(self, message: NavItem.Selected) -> None:
        """Handle sidebar navigation clicks."""
        self.action_switch(message.view_id)
