"""Colored state label widget."""

from __future__ import annotations

STATE_COLORS = {
    "discovered": "blue",
    "suggested": "cyan",
    "approved": "green",
    "edited": "green",
    "rejected": "red",
    "blocked": "yellow",
    "executing": "magenta",
    "validating": "yellow",
    "security_review": "yellow",
    "completed": "bright_green",
    "failed": "bright_red",
    "cancelled": "dim",
    "observed": "blue",
    "sanitized": "cyan",
    "evaluated": "cyan",
    "converted_to_project": "green",
}


def state_color(state: str) -> str:
    """Return the Rich color name for a given state value."""
    return STATE_COLORS.get(state.lower(), "white")


def state_markup(state: str) -> str:
    """Return a Rich-markup-styled state string."""
    color = state_color(state)
    return f"[{color}]{state}[/{color}]"
