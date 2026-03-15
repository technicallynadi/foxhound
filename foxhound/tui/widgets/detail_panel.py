"""Reusable detail panel widget with action buttons."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Static

ButtonRow = list[tuple[str, str, str]]

_STANDARD_VARIANTS = {"default", "primary", "success", "warning", "error"}


class DetailPanel(Vertical):
    """A panel that displays detail text and action buttons.

    Buttons are organized in rows. Pass a list of rows where each row
    is a list of (label, action_id, variant) tuples.
    """

    detail_text: reactive[str] = reactive("Select an item to view details.")

    class ButtonPressed(Message):
        """Emitted when an action button is clicked."""

        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    def __init__(
        self,
        buttons: ButtonRow | None = None,
        button_rows: list[ButtonRow] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        if button_rows:
            self._button_rows = button_rows
        elif buttons:
            self._button_rows = [buttons]
        else:
            self._button_rows = []
        self.add_class("detail-panel")

    def compose(self) -> ComposeResult:
        yield Static("Select an item to view details.", id="detail-text")
        with Vertical(id="detail-buttons-container"):
            for row in self._button_rows:
                with Horizontal(classes="detail-button-row"):
                    for label, action_id, variant in row:
                        btn = self._make_button(label, action_id, variant)
                        yield btn

    def watch_detail_text(self, new_value: str) -> None:
        try:
            text_widget = self.query_one("#detail-text", Static)
            text_widget.update(new_value)
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        action = button_id.removeprefix("btn-")
        self.post_message(self.ButtonPressed(action))

    async def set_buttons(self, buttons: ButtonRow) -> None:
        """Replace buttons with a single row."""
        await self.set_button_rows([buttons])

    @staticmethod
    def _make_button(label: str, action_id: str, variant: str) -> Button:
        """Create a button, using CSS class for non-standard variants."""
        if variant in _STANDARD_VARIANTS:
            return Button(label, id=f"btn-{action_id}", variant=variant)
        btn = Button(label, id=f"btn-{action_id}", variant="default")
        btn.add_class(variant)
        return btn

    async def set_button_rows(self, rows: list[ButtonRow]) -> None:
        """Replace all button rows."""
        try:
            container = self.query_one("#detail-buttons-container", Vertical)
            await container.remove_children()
            for row in rows:
                h = Horizontal(classes="detail-button-row")
                await container.mount(h)
                for label, action_id, variant in row:
                    btn = self._make_button(label, action_id, variant)
                    await h.mount(btn)
        except Exception:
            pass

    def clear(self) -> None:
        self.detail_text = "Select an item to view details."
