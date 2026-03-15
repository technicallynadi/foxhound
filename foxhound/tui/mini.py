"""Mini TUI — single-view focused apps for individual CLI commands.

Each function launches a full-screen Textual app with just one view,
no sidebar. Used by CLI commands to provide interactive experiences.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from foxhound.tui.data import TUIData
from foxhound.tui.styles import APP_CSS


class MiniApp(App[None]):
    """Base mini TUI app — single view, no sidebar."""

    TITLE = "Foxhound"
    CSS = APP_CSS

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, view_cls: type, subtitle: str, db_path: Path) -> None:
        super().__init__()
        self.sub_title = subtitle
        self._view_cls = view_cls
        root = db_path.parent.parent if db_path else None
        self.data = TUIData(root=root)

    def compose(self) -> ComposeResult:
        yield Header()
        yield self._view_cls(data=self.data, id="main-view")
        yield Footer()


def run_scout_inbox(db_path: Path) -> None:
    """Launch the scout inbox as a focused mini TUI."""
    from foxhound.tui.views.scout_inbox import ScoutInboxView

    app = MiniApp(ScoutInboxView, "Scout Inbox", db_path)
    app.run()


def run_work_items(db_path: Path) -> None:
    """Launch work items view as a focused mini TUI."""
    from foxhound.tui.views.work_items import WorkItemsView

    app = MiniApp(WorkItemsView, "Work Items", db_path)
    app.run()


def run_runs(db_path: Path) -> None:
    """Launch runs view as a focused mini TUI."""
    from foxhound.tui.views.runs import RunsView

    app = MiniApp(RunsView, "Runs", db_path)
    app.run()


def run_dashboard(db_path: Path) -> None:
    """Launch dashboard as a focused mini TUI."""
    from foxhound.tui.views.dashboard import DashboardView

    app = MiniApp(DashboardView, "Dashboard", db_path)
    app.run()


def run_doctor(db_path: Path) -> None:
    """Launch doctor view as a focused mini TUI."""
    from foxhound.tui.views.doctor import DoctorView

    app = MiniApp(DoctorView, "Doctor", db_path)
    app.run()


def run_repos(db_path: Path) -> None:
    """Launch repos view as a focused mini TUI."""
    from foxhound.tui.views.repos import ReposView

    app = MiniApp(ReposView, "Repositories", db_path)
    app.run()
