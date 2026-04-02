"""Tests for the event bus."""

import asyncio
import pytest

from app.services.events.bus import FoxhoundEvent, emit, on_event, _handlers


@pytest.fixture(autouse=True)
def clear_handlers():
    """Clear any registered handlers before each test."""
    _handlers.clear()
    yield
    _handlers.clear()


def test_on_event_registers_handler():
    @on_event("test.event")
    async def handler(event):
        pass

    assert "test.event" in _handlers
    assert len(_handlers["test.event"]) == 1


def test_multiple_handlers_same_event():
    @on_event("test.multi")
    async def handler_a(event):
        pass

    @on_event("test.multi")
    async def handler_b(event):
        pass

    assert len(_handlers["test.multi"]) == 2


@pytest.mark.asyncio
async def test_emit_calls_handlers():
    received = []

    @on_event("test.emit")
    async def handler(event):
        received.append(event.data["value"])

    await emit(FoxhoundEvent(name="test.emit", data={"value": 42}))
    await asyncio.sleep(0.05)  # Let the task run

    assert received == [42]


@pytest.mark.asyncio
async def test_emit_no_handlers_is_silent():
    # Should not raise
    await emit(FoxhoundEvent(name="nonexistent.event", data={}))


@pytest.mark.asyncio
async def test_handler_error_does_not_crash_emitter():
    called = []

    @on_event("test.error")
    async def bad_handler(event):
        raise RuntimeError("boom")

    @on_event("test.error")
    async def good_handler(event):
        called.append(True)

    await emit(FoxhoundEvent(name="test.error", data={}))
    await asyncio.sleep(0.05)

    # Good handler still ran despite bad handler crashing
    assert called == [True]


def test_foxhound_event_has_timestamp():
    event = FoxhoundEvent(name="test", data={"x": 1})
    assert event.timestamp is not None
    assert event.name == "test"
    assert event.data == {"x": 1}
