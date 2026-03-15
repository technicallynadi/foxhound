"""Retention view — storage stats and artifact management."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Static

if TYPE_CHECKING:
    from foxhound.tui.data import TUIData


def _format_size(size_bytes: int) -> str:
    """Convert bytes to human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


class RetentionView(Vertical):
    """Storage usage with prune and compact actions."""

    def __init__(self, data: TUIData, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._data = data

    def compose(self) -> ComposeResult:
        """Build the retention layout."""
        yield Static("Loading...", id="retention-stats")
        with Horizontal(id="retention-buttons"):
            yield Button("Prune Expired", id="btn-prune", variant="warning")
            yield Button("Compact Events", id="btn-compact", variant="primary")
            yield Button("Refresh", id="btn-refresh", variant="default")

    def on_mount(self) -> None:
        """Load stats on mount."""
        self.call_after_refresh(self._load_stats)

    def on_show(self) -> None:
        """Refresh when view becomes visible."""
        self.call_after_refresh(self._load_stats)

    async def _load_stats(self) -> None:
        """Load and display retention stats."""
        try:
            status = await self._data.get_retention_status()
        except Exception:
            widget = self.query_one("#retention-stats", Static)
            widget.update(
                "[bold]Storage & Retention[/bold]\n\n"
                "  No artifacts stored yet.\n\n"
                "  Artifacts are created when you run work items.\n"
                "  Use [bold]Prune Expired[/bold] to clean up old artifacts\n"
                "  and [bold]Compact Events[/bold] to compress event history."
            )
            return

        classes = status.get("classes", {})
        total_artifacts = status.get("total_artifacts", 0)
        total_size = status.get("total_size_bytes", 0)

        lines = [
            "[bold]Storage & Retention[/bold]\n",
        ]

        if classes:
            lines.append(f"  {'Class':<12} {'Retention':<14} {'Artifacts':<12} {'Size':<10}")
            lines.append(f"  {'─' * 48}")
            for cls_name, cls_info in classes.items():
                days = cls_info.get("retention_days", "—")
                count = cls_info.get("artifact_count", 0)
                size = _format_size(cls_info.get("size_bytes", 0))
                lines.append(f"  {cls_name:<12} {days} days{'':<8} {count:<12} {size}")
            lines.append(f"  {'─' * 48}")

        lines.append(f"\n  Total artifacts: {total_artifacts}")
        lines.append(f"  Total size: {_format_size(total_size)}")

        widget = self.query_one("#retention-stats", Static)
        widget.update("\n".join(lines))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "btn-prune":
            self.app.notify("Pruning expired artifacts...")
            try:
                result = await self._data.run_prune()
                self.app.notify(
                    f"Pruned: {result['artifacts_removed']} artifacts, "
                    f"{result['files_deleted']} files, "
                    f"{_format_size(result['space_freed'])} freed"
                )
            except Exception as e:
                self.app.notify(f"Prune failed: {e}", severity="error")
            await self._load_stats()

        elif event.button.id == "btn-compact":
            self.app.notify("Compacting event streams...")
            try:
                count = await self._data.run_compact(days=30)
                self.app.notify(f"Compacted {count} events")
            except Exception as e:
                self.app.notify(f"Compact failed: {e}", severity="error")
            await self._load_stats()

        elif event.button.id == "btn-refresh":
            await self._load_stats()
            self.app.notify("Refreshed")
