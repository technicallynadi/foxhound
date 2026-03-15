"""Tests for notification dispatch system."""

import pytest

from foxhound.core.models import (
    EventEnvelope,
    EventSeverity,
    EventType,
)
from foxhound.observer.notifications import (
    EVENT_ROUTING,
    CliNotificationSink,
    NotificationDispatcher,
    NotificationPriority,
    _format_event_message,
)


def _make_event(
    event_type: EventType = EventType.RUN_COMPLETED,
    payload: dict | None = None,
    severity: EventSeverity = EventSeverity.INFO,
    event_id: str = "evt_001",
) -> EventEnvelope:
    """Create a test event."""
    return EventEnvelope(
        event_id=event_id,
        event_type=event_type,
        source_module="test",
        severity=severity,
        payload=payload or {},
    )


# -- Event routing data for parametrized tests --
_ALWAYS_EVENTS = [
    EventType.APPROVAL_REQUESTED,
    EventType.RUN_FAILED,
    EventType.SECURITY_VIOLATION_DETECTED,
    EventType.APPROVAL_REJECTED,
    EventType.POLICY_BLOCKED_ACTION,
    EventType.PROMOTION_FAILED,
]

_DEFAULT_EVENTS = [
    EventType.APPROVAL_GRANTED,
    EventType.RUN_COMPLETED,
    EventType.EVALUATION_PASSED,
    EventType.EVALUATION_FAILED,
    EventType.WORKER_SPAWN_FAILED,
    EventType.RULE_SUGGESTION_CREATED,
    EventType.PROMOTION_SUCCEEDED,
]

_SUPPRESS_EVENTS = [
    EventType.RUN_STARTED,
    EventType.RUN_QUEUED,
    EventType.DISCOVERY_SCAN_COMPLETED,
    EventType.EVALUATION_STARTED,
    EventType.SECURITY_SCAN_STARTED,
    EventType.RALPH_ITERATION_COMPLETED,
    EventType.WORKER_SPAWN_REQUESTED,
    EventType.WORKER_SPAWN_APPROVED,
    EventType.RULE_APPLIED,
    EventType.WORK_ITEM_DISCOVERED,
    EventType.PROMOTION_STARTED,
]

_ROUTING_PARAMS = (
    [(et, NotificationPriority.ALWAYS) for et in _ALWAYS_EVENTS]
    + [(et, NotificationPriority.DEFAULT) for et in _DEFAULT_EVENTS]
    + [(et, NotificationPriority.SUPPRESS) for et in _SUPPRESS_EVENTS]
)


class TestEventRoutingPolicy:
    """Verify routing policy covers spec requirements."""

    @pytest.mark.parametrize(
        ("event_type", "expected_priority"),
        _ROUTING_PARAMS,
        ids=[et.value for et, _ in _ROUTING_PARAMS],
    )
    def test_event_routing(self, event_type: EventType, expected_priority: NotificationPriority):
        assert EVENT_ROUTING[event_type] == expected_priority

    def test_all_event_types_have_routing(self):
        for event_type in EventType:
            assert event_type in EVENT_ROUTING, (
                f"{event_type.value} missing from EVENT_ROUTING"
            )

    def test_always_count(self):
        always = [k for k, v in EVENT_ROUTING.items() if v == NotificationPriority.ALWAYS]
        assert len(always) == 6

    def test_suppress_count(self):
        suppressed = [k for k, v in EVENT_ROUTING.items() if v == NotificationPriority.SUPPRESS]
        assert len(suppressed) == 11


class TestFormatEventMessage:
    def test_approval_requested(self):
        event = _make_event(EventType.APPROVAL_REQUESTED, {
            "title": "Fix auth bug",
            "risk": "high",
            "work_item_id": "wi_001",
        })
        msg = _format_event_message(event)
        assert "Fix auth bug" in msg
        assert "high" in msg
        assert "wi_001" in msg
        assert "Approval required" in msg

    def test_approval_requested_defaults(self):
        msg = _format_event_message(_make_event(EventType.APPROVAL_REQUESTED, {}))
        assert "unknown" in msg

    def test_run_failed(self):
        msg = _format_event_message(_make_event(EventType.RUN_FAILED, {"reason": "timeout"}))
        assert "Run failed" in msg
        assert "timeout" in msg

    def test_run_failed_default_reason(self):
        msg = _format_event_message(_make_event(EventType.RUN_FAILED, {}))
        assert "unknown" in msg

    def test_security_violation(self):
        msg = _format_event_message(
            _make_event(EventType.SECURITY_VIOLATION_DETECTED, {"details": "secret in output"})
        )
        assert "Security violation" in msg
        assert "secret in output" in msg

    def test_security_violation_default(self):
        msg = _format_event_message(_make_event(EventType.SECURITY_VIOLATION_DETECTED, {}))
        assert "check logs" in msg

    def test_policy_blocked(self):
        msg = _format_event_message(
            _make_event(EventType.POLICY_BLOCKED_ACTION, {"rule": "no_env_files"})
        )
        assert "Policy blocked" in msg
        assert "no_env_files" in msg

    def test_policy_blocked_default(self):
        msg = _format_event_message(_make_event(EventType.POLICY_BLOCKED_ACTION, {}))
        assert "unknown rule" in msg

    def test_approval_granted(self):
        msg = _format_event_message(
            _make_event(EventType.APPROVAL_GRANTED, {"work_item_id": "wi_abc"})
        )
        assert "Approved" in msg
        assert "wi_abc" in msg

    def test_approval_rejected(self):
        msg = _format_event_message(
            _make_event(EventType.APPROVAL_REJECTED, {"work_item_id": "wi_xyz"})
        )
        assert "Rejected" in msg
        assert "wi_xyz" in msg

    def test_run_completed(self):
        msg = _format_event_message(
            _make_event(EventType.RUN_COMPLETED, {"worker": "execution_worker", "duration_seconds": 12.5})
        )
        assert "execution_worker" in msg
        assert "12.5" in msg
        assert "Run completed" in msg

    def test_run_completed_defaults(self):
        msg = _format_event_message(_make_event(EventType.RUN_COMPLETED, {}))
        assert "unknown" in msg

    def test_evaluation_failed(self):
        msg = _format_event_message(
            _make_event(EventType.EVALUATION_FAILED, {"reason": "low confidence"})
        )
        assert "Evaluation failed" in msg
        assert "low confidence" in msg

    def test_evaluation_failed_default(self):
        msg = _format_event_message(_make_event(EventType.EVALUATION_FAILED, {}))
        assert "check results" in msg

    def test_default_format_fallback(self):
        msg = _format_event_message(_make_event(EventType.RULE_APPLIED, {"rule": "test_rule"}))
        assert "RuleApplied" in msg
        assert "test_rule" in msg

    def test_default_format_empty_payload(self):
        msg = _format_event_message(_make_event(EventType.RUN_QUEUED, {}))
        assert "RunQueued" in msg


class TestCliNotificationSink:
    def test_send_returns_true(self):
        sink = CliNotificationSink()
        assert sink.send("msg", NotificationPriority.ALWAYS, _make_event(EventType.RUN_FAILED)) is True

    def test_send_stores_message_with_priority_and_event(self):
        sink = CliNotificationSink()
        event = _make_event(EventType.APPROVAL_REQUESTED)
        sink.send("test message", NotificationPriority.ALWAYS, event)
        assert len(sink.messages) == 1
        assert sink.messages[0][0] == "test message"
        assert sink.messages[0][1] == NotificationPriority.ALWAYS
        assert sink.messages[0][2] == event

    def test_send_multiple(self):
        sink = CliNotificationSink()
        event = _make_event(EventType.RUN_FAILED)
        sink.send("msg1", NotificationPriority.ALWAYS, event)
        sink.send("msg2", NotificationPriority.DEFAULT, event)
        sink.send("msg3", NotificationPriority.ALWAYS, event)
        assert len(sink.messages) == 3

    def test_messages_returns_copy(self):
        sink = CliNotificationSink()
        sink.send("msg", NotificationPriority.ALWAYS, _make_event(EventType.RUN_FAILED))
        msgs = sink.messages
        msgs.clear()
        assert len(sink.messages) == 1

    def test_sink_name(self):
        assert CliNotificationSink().sink_name == "cli"

    def test_empty_messages_initially(self):
        assert CliNotificationSink().messages == []


class TestNotificationDispatcher:
    @pytest.fixture()
    def dispatcher_with_sink(self):
        d = NotificationDispatcher()
        s = CliNotificationSink()
        d.add_sink(s)
        return d, s

    def test_dispatch_always_event_delivered(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        event = _make_event(EventType.APPROVAL_REQUESTED, {
            "title": "test", "risk": "low", "work_item_id": "wi_1",
        })
        assert d.dispatch(event) is True
        assert len(s.messages) == 1

    def test_dispatch_default_event_delivered(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        event = _make_event(EventType.RUN_COMPLETED, {
            "worker": "test", "duration_seconds": 1.0,
        })
        assert d.dispatch(event) is True
        assert len(s.messages) == 1

    def test_dispatch_suppressed_event_not_delivered(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        assert d.dispatch(_make_event(EventType.RUN_STARTED)) is False
        assert len(s.messages) == 0

    def test_no_sinks_always_returns_false(self):
        dispatcher = NotificationDispatcher()
        event = _make_event(EventType.APPROVAL_REQUESTED, {
            "title": "t", "risk": "l", "work_item_id": "w",
        })
        assert dispatcher.dispatch(event) is False

    def test_no_sinks_suppressed_still_counts(self):
        dispatcher = NotificationDispatcher()
        dispatcher.dispatch(_make_event(EventType.RUN_STARTED))
        assert dispatcher.stats["suppressed"] == 1

    def test_override_suppress_to_always(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        d.override_priority(EventType.RUN_STARTED, NotificationPriority.ALWAYS)
        assert d.dispatch(_make_event(EventType.RUN_STARTED)) is True
        assert len(s.messages) == 1

    def test_override_always_to_suppress(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        d.override_priority(EventType.RUN_FAILED, NotificationPriority.SUPPRESS)
        assert d.dispatch(_make_event(EventType.RUN_FAILED, {"reason": "err"})) is False
        assert len(s.messages) == 0

    def test_override_persists(self):
        dispatcher = NotificationDispatcher()
        dispatcher.override_priority(EventType.RUN_STARTED, NotificationPriority.ALWAYS)
        assert dispatcher.get_priority(EventType.RUN_STARTED) == NotificationPriority.ALWAYS

    def test_get_priority_known_event(self):
        assert NotificationDispatcher().get_priority(EventType.RUN_FAILED) == NotificationPriority.ALWAYS

    def test_get_priority_suppressed_event(self):
        assert NotificationDispatcher().get_priority(EventType.RUN_STARTED) == NotificationPriority.SUPPRESS

    def test_stats_initial(self):
        assert NotificationDispatcher().stats == {"delivered": 0, "suppressed": 0}

    def test_stats_after_delivery(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        d.dispatch(_make_event(EventType.RUN_FAILED, {"reason": "x"}))
        assert d.stats == {"delivered": 1, "suppressed": 0}

    def test_stats_after_suppression(self, dispatcher_with_sink):
        d, _ = dispatcher_with_sink
        d.dispatch(_make_event(EventType.RUN_STARTED))
        assert d.stats == {"delivered": 0, "suppressed": 1}

    def test_stats_mixed(self, dispatcher_with_sink):
        d, _ = dispatcher_with_sink
        d.dispatch(_make_event(EventType.RUN_FAILED, {"reason": "x"}))
        d.dispatch(_make_event(EventType.RUN_STARTED))
        d.dispatch(_make_event(EventType.RUN_FAILED, {"reason": "y"}))
        d.dispatch(_make_event(EventType.RUN_QUEUED))
        assert d.stats == {"delivered": 2, "suppressed": 2}

    # --- Multiple sinks ---

    def test_multiple_sinks_all_receive_same_message(self):
        dispatcher = NotificationDispatcher()
        sink1 = CliNotificationSink()
        sink2 = CliNotificationSink()
        dispatcher.add_sink(sink1)
        dispatcher.add_sink(sink2)
        dispatcher.dispatch(_make_event(EventType.RUN_FAILED, {"reason": "err"}))
        assert len(sink1.messages) == 1
        assert len(sink2.messages) == 1
        assert sink1.messages[0][0] == sink2.messages[0][0]

    def test_sinks_property_returns_copy(self):
        dispatcher = NotificationDispatcher()
        dispatcher.add_sink(CliNotificationSink())
        assert len(dispatcher.sinks) == 1
        assert dispatcher.sinks[0].sink_name == "cli"
        dispatcher.sinks.clear()
        assert len(dispatcher.sinks) == 1

    def test_dispatch_batch(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        events = [
            _make_event(EventType.APPROVAL_REQUESTED, {
                "title": "t", "risk": "l", "work_item_id": "w",
            }),
            _make_event(EventType.RUN_STARTED),
            _make_event(EventType.RUN_FAILED, {"reason": "err"}),
            _make_event(EventType.RUN_QUEUED),
        ]
        assert d.dispatch_batch(events) == 2
        assert len(s.messages) == 2

    def test_dispatch_batch_empty(self, dispatcher_with_sink):
        d, _ = dispatcher_with_sink
        assert d.dispatch_batch([]) == 0

    def test_dispatch_batch_all_suppressed(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        events = [_make_event(EventType.RUN_STARTED), _make_event(EventType.RUN_QUEUED)]
        assert d.dispatch_batch(events) == 0
        assert len(s.messages) == 0
        assert d.stats["suppressed"] == 2

    def test_dispatch_batch_all_delivered(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        events = [
            _make_event(EventType.RUN_FAILED, {"reason": "a"}),
            _make_event(EventType.RUN_FAILED, {"reason": "b"}),
        ]
        assert d.dispatch_batch(events) == 2
        assert len(s.messages) == 2

    def test_dispatched_message_is_formatted(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        d.dispatch(_make_event(EventType.RUN_FAILED, {"reason": "oom"}))
        msg = s.messages[0][0]
        assert "Run failed" in msg
        assert "oom" in msg

    def test_dispatched_priority_matches_routing(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        d.dispatch(_make_event(EventType.APPROVAL_REQUESTED, {
            "title": "t", "risk": "l", "work_item_id": "w",
        }))
        assert s.messages[0][1] == NotificationPriority.ALWAYS

    def test_dispatched_event_object_passed_through(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        d.dispatch(_make_event(EventType.RUN_FAILED, {"reason": "err"}, event_id="evt_unique"))
        assert s.messages[0][2].event_id == "evt_unique"


# Minimal payloads so _format_event_message doesn't error on key lookups.
_ALWAYS_PAYLOADS: dict[EventType, dict] = {
    EventType.APPROVAL_REQUESTED: {"title": "t", "risk": "l", "work_item_id": "w"},
    EventType.RUN_FAILED: {"reason": "x"},
    EventType.SECURITY_VIOLATION_DETECTED: {"details": "x"},
    EventType.APPROVAL_REJECTED: {"work_item_id": "w"},
    EventType.POLICY_BLOCKED_ACTION: {"rule": "r"},
    EventType.PROMOTION_FAILED: {},
}


class TestAlwaysEventsIntegration:
    """Verify every ALWAYS-routed event actually dispatches end-to-end."""

    @pytest.fixture()
    def dispatcher_with_sink(self):
        d = NotificationDispatcher()
        s = CliNotificationSink()
        d.add_sink(s)
        return d, s

    @pytest.mark.parametrize("event_type", _ALWAYS_EVENTS, ids=[e.value for e in _ALWAYS_EVENTS])
    def test_always_event_dispatches(self, dispatcher_with_sink, event_type):
        d, s = dispatcher_with_sink
        d.dispatch(_make_event(event_type, _ALWAYS_PAYLOADS.get(event_type, {})))
        assert len(s.messages) == 1


class TestSuppressEventsIntegration:
    """Verify every SUPPRESS-routed event is actually suppressed."""

    @pytest.fixture()
    def dispatcher_with_sink(self):
        d = NotificationDispatcher()
        s = CliNotificationSink()
        d.add_sink(s)
        return d, s

    @pytest.mark.parametrize("event_type", _SUPPRESS_EVENTS, ids=[e.value for e in _SUPPRESS_EVENTS])
    def test_suppressed_event(self, dispatcher_with_sink, event_type):
        d, s = dispatcher_with_sink
        assert d.dispatch(_make_event(event_type)) is False
        assert len(s.messages) == 0
