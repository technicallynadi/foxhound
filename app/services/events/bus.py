"""In-process async event bus.

Single-worker, in-process only. Handlers run as fire-and-forget
asyncio tasks. A failing handler never blocks the emitter.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


@dataclass
class FoxhoundEvent:
    name: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_handlers: dict[str, list[Callable[[FoxhoundEvent], Coroutine]]] = {}


def on_event(event_name: str):
    """Decorator to register an async handler for an event."""
    def decorator(fn: Callable[[FoxhoundEvent], Coroutine]):
        _handlers.setdefault(event_name, []).append(fn)
        return fn
    return decorator


async def emit(event: FoxhoundEvent) -> None:
    """Fire event to all registered handlers. Non-blocking."""
    handlers = _handlers.get(event.name, [])
    if not handlers:
        return
    logger.info("Event %s -> %d handlers", event.name, len(handlers))
    for handler in handlers:
        asyncio.create_task(_safe_handle(handler, event))


async def _safe_handle(handler: Callable, event: FoxhoundEvent) -> None:
    try:
        await handler(event)
    except Exception:
        logger.exception("Event handler %s failed for %s", handler.__name__, event.name)
