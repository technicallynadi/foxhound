"""Navigation sidebar widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static


class NavItem(Static):
    """A single navigation item in the sidebar."""

    class Selected(Message):
        """Emitted when a nav item is selected."""

        def __init__(self, view_id: str) -> None:
            super().__init__()
            self.view_id = view_id

    def __init__(self, label: str, key: str, view_id: str, **kwargs: object) -> None:
        super().__init__(f" [{key}] {label}", **kwargs)
        self.view_id = view_id
        self.add_class("nav-item")

    def on_click(self) -> None:
        """Handle click on nav item."""
        self.post_message(self.Selected(self.view_id))


NAV_ITEMS = [
    ("Dashboard", "F1", "dashboard"),
    ("Scout Inbox", "F2", "scout-inbox"),
    ("Work Items", "F3", "work-items"),
    ("Runs", "F4", "runs"),
    ("Doctor", "F5", "doctor"),
    ("Analyze", "F6", "analyze"),
    ("Repos", "F7", "repos"),
    ("Retention", "F8", "retention"),
]


class Sidebar(Static):
    """Navigation sidebar with view switching."""

    active_view: reactive[str] = reactive("dashboard")

    def compose(self) -> ComposeResult:
        """Build sidebar navigation items."""
        yield Static(" Foxhound", classes="nav-header")
        yield Static("")
        for label, key, view_id in NAV_ITEMS:
            yield NavItem(label, key, view_id, id=f"nav-{view_id}")

    def watch_active_view(self, old: str, new: str) -> None:
        """Update styling when active view changes."""
        for item in self.query(NavItem):
            if item.view_id == new:
                item.add_class("--active")
            else:
                item.remove_class("--active")
