"""Reusable detail panel widget with action buttons."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Static


class DetailPanel(Vertical):
    """A panel that displays detail text and action buttons."""

    detail_text: reactive[str] = reactive("Select an item to view details.")

    class ButtonPressed(Message):
        """Emitted when an action button is clicked."""

        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    def __init__(self, buttons: list[tuple[str, str, str]] | None = None, **kwargs: object) -> None:
        """Initialize with optional button definitions.

        Args:
            buttons: List of (label, action_id, variant) tuples.
                     variant is one of: default, primary, success, warning, error.
        """
        super().__init__(**kwargs)
        self._button_defs = buttons or []
        self.add_class("detail-panel")

    def compose(self) -> ComposeResult:
        """Build detail panel with text and buttons."""
        yield Static("Select an item to view details.", id="detail-text")
        if self._button_defs:
            with Horizontal(id="detail-buttons"):
                for label, action_id, variant in self._button_defs:
                    yield Button(label, id=f"btn-{action_id}", variant=variant)

    def watch_detail_text(self, new_value: str) -> None:
        """Update the text widget when detail_text changes."""
        try:
            text_widget = self.query_one("#detail-text", Static)
            text_widget.update(new_value)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Forward button press as a DetailPanel.ButtonPressed message."""
        button_id = event.button.id or ""
        action = button_id.removeprefix("btn-")
        self.post_message(self.ButtonPressed(action))

    def clear(self) -> None:
        """Clear the detail panel."""
        self.detail_text = "Select an item to view details."
