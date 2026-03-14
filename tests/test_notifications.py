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
    event_type: EventType,
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


# ============================================================================
# EVENT_ROUTING constant
# ============================================================================


class TestEventRoutingPolicy:
    """Verify routing policy covers spec requirements."""

    # --- Always surface ---

    def test_approval_requested_always(self):
        assert EVENT_ROUTING[EventType.APPROVAL_REQUESTED] == NotificationPriority.ALWAYS

    def test_run_failed_always(self):
        assert EVENT_ROUTING[EventType.RUN_FAILED] == NotificationPriority.ALWAYS

    def test_security_violation_always(self):
        assert EVENT_ROUTING[EventType.SECURITY_VIOLATION_DETECTED] == NotificationPriority.ALWAYS

    def test_approval_rejected_always(self):
        assert EVENT_ROUTING[EventType.APPROVAL_REJECTED] == NotificationPriority.ALWAYS

    def test_policy_blocked_always(self):
        assert EVENT_ROUTING[EventType.POLICY_BLOCKED_ACTION] == NotificationPriority.ALWAYS

    # --- Default ---

    def test_approval_granted_default(self):
        assert EVENT_ROUTING[EventType.APPROVAL_GRANTED] == NotificationPriority.DEFAULT

    def test_run_completed_default(self):
        assert EVENT_ROUTING[EventType.RUN_COMPLETED] == NotificationPriority.DEFAULT

    def test_evaluation_passed_default(self):
        assert EVENT_ROUTING[EventType.EVALUATION_PASSED] == NotificationPriority.DEFAULT

    def test_evaluation_failed_default(self):
        assert EVENT_ROUTING[EventType.EVALUATION_FAILED] == NotificationPriority.DEFAULT

    def test_worker_spawn_failed_default(self):
        assert EVENT_ROUTING[EventType.WORKER_SPAWN_FAILED] == NotificationPriority.DEFAULT

    def test_rule_suggestion_created_default(self):
        assert EVENT_ROUTING[EventType.RULE_SUGGESTION_CREATED] == NotificationPriority.DEFAULT

    # --- Suppress ---

    def test_run_started_suppressed(self):
        assert EVENT_ROUTING[EventType.RUN_STARTED] == NotificationPriority.SUPPRESS

    def test_run_queued_suppressed(self):
        assert EVENT_ROUTING[EventType.RUN_QUEUED] == NotificationPriority.SUPPRESS

    def test_discovery_scan_completed_suppressed(self):
        assert EVENT_ROUTING[EventType.DISCOVERY_SCAN_COMPLETED] == NotificationPriority.SUPPRESS

    def test_evaluation_started_suppressed(self):
        assert EVENT_ROUTING[EventType.EVALUATION_STARTED] == NotificationPriority.SUPPRESS

    def test_security_scan_started_suppressed(self):
        assert EVENT_ROUTING[EventType.SECURITY_SCAN_STARTED] == NotificationPriority.SUPPRESS

    def test_ralph_iteration_completed_suppressed(self):
        assert EVENT_ROUTING[EventType.RALPH_ITERATION_COMPLETED] == NotificationPriority.SUPPRESS

    def test_worker_spawn_requested_suppressed(self):
        assert EVENT_ROUTING[EventType.WORKER_SPAWN_REQUESTED] == NotificationPriority.SUPPRESS

    def test_worker_spawn_approved_suppressed(self):
        assert EVENT_ROUTING[EventType.WORKER_SPAWN_APPROVED] == NotificationPriority.SUPPRESS

    def test_rule_applied_suppressed(self):
        assert EVENT_ROUTING[EventType.RULE_APPLIED] == NotificationPriority.SUPPRESS

    def test_work_item_discovered_suppressed(self):
        assert EVENT_ROUTING[EventType.WORK_ITEM_DISCOVERED] == NotificationPriority.SUPPRESS

    # --- Coverage ---

    def test_all_event_types_have_routing(self):
        for event_type in EventType:
            assert event_type in EVENT_ROUTING, (
                f"{event_type.value} missing from EVENT_ROUTING"
            )

    def test_always_count(self):
        always = [
            k for k, v in EVENT_ROUTING.items()
            if v == NotificationPriority.ALWAYS
        ]
        assert len(always) == 5

    def test_suppress_count(self):
        suppressed = [
            k for k, v in EVENT_ROUTING.items()
            if v == NotificationPriority.SUPPRESS
        ]
        assert len(suppressed) == 10


# ============================================================================
# _format_event_message
# ============================================================================


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
        event = _make_event(EventType.APPROVAL_REQUESTED, {})
        msg = _format_event_message(event)
        assert "unknown" in msg

    def test_run_failed(self):
        event = _make_event(EventType.RUN_FAILED, {"reason": "timeout"})
        msg = _format_event_message(event)
        assert "Run failed" in msg
        assert "timeout" in msg

    def test_run_failed_default_reason(self):
        event = _make_event(EventType.RUN_FAILED, {})
        msg = _format_event_message(event)
        assert "unknown" in msg

    def test_security_violation(self):
        event = _make_event(EventType.SECURITY_VIOLATION_DETECTED, {
            "details": "secret in output",
        })
        msg = _format_event_message(event)
        assert "Security violation" in msg
        assert "secret in output" in msg

    def test_security_violation_default(self):
        event = _make_event(EventType.SECURITY_VIOLATION_DETECTED, {})
        msg = _format_event_message(event)
        assert "check logs" in msg

    def test_policy_blocked(self):
        event = _make_event(EventType.POLICY_BLOCKED_ACTION, {
            "rule": "no_env_files",
        })
        msg = _format_event_message(event)
        assert "Policy blocked" in msg
        assert "no_env_files" in msg

    def test_policy_blocked_default(self):
        event = _make_event(EventType.POLICY_BLOCKED_ACTION, {})
        msg = _format_event_message(event)
        assert "unknown rule" in msg

    def test_approval_granted(self):
        event = _make_event(EventType.APPROVAL_GRANTED, {
            "work_item_id": "wi_abc",
        })
        msg = _format_event_message(event)
        assert "Approved" in msg
        assert "wi_abc" in msg

    def test_approval_rejected(self):
        event = _make_event(EventType.APPROVAL_REJECTED, {
            "work_item_id": "wi_xyz",
        })
        msg = _format_event_message(event)
        assert "Rejected" in msg
        assert "wi_xyz" in msg

    def test_run_completed(self):
        event = _make_event(EventType.RUN_COMPLETED, {
            "worker": "execution_worker",
            "duration_seconds": 12.5,
        })
        msg = _format_event_message(event)
        assert "execution_worker" in msg
        assert "12.5" in msg
        assert "Run completed" in msg

    def test_run_completed_defaults(self):
        event = _make_event(EventType.RUN_COMPLETED, {})
        msg = _format_event_message(event)
        assert "unknown" in msg

    def test_evaluation_failed(self):
        event = _make_event(EventType.EVALUATION_FAILED, {
            "reason": "low confidence",
        })
        msg = _format_event_message(event)
        assert "Evaluation failed" in msg
        assert "low confidence" in msg

    def test_evaluation_failed_default(self):
        event = _make_event(EventType.EVALUATION_FAILED, {})
        msg = _format_event_message(event)
        assert "check results" in msg

    def test_default_format_fallback(self):
        event = _make_event(EventType.RULE_APPLIED, {"rule": "test_rule"})
        msg = _format_event_message(event)
        assert "RuleApplied" in msg
        assert "test_rule" in msg

    def test_default_format_empty_payload(self):
        event = _make_event(EventType.RUN_QUEUED, {})
        msg = _format_event_message(event)
        assert "RunQueued" in msg


# ============================================================================
# CliNotificationSink
# ============================================================================


class TestCliNotificationSink:
    def test_send_returns_true(self):
        sink = CliNotificationSink()
        event = _make_event(EventType.RUN_FAILED)
        assert sink.send("msg", NotificationPriority.ALWAYS, event) is True

    def test_send_stores_message(self):
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
        event = _make_event(EventType.RUN_FAILED)
        sink.send("msg", NotificationPriority.ALWAYS, event)
        msgs = sink.messages
        msgs.clear()
        assert len(sink.messages) == 1

    def test_stores_priority(self):
        sink = CliNotificationSink()
        event = _make_event(EventType.RUN_COMPLETED)
        sink.send("msg", NotificationPriority.DEFAULT, event)
        assert sink.messages[0][1] == NotificationPriority.DEFAULT

    def test_sink_name(self):
        assert CliNotificationSink().sink_name == "cli"

    def test_empty_messages_initially(self):
        assert CliNotificationSink().messages == []


# ============================================================================
# NotificationDispatcher
# ============================================================================


class TestNotificationDispatcher:
    # --- Basic dispatch ---

    def test_dispatch_always_event_delivered(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)

        event = _make_event(EventType.APPROVAL_REQUESTED, {
            "title": "test", "risk": "low", "work_item_id": "wi_1",
        })
        assert dispatcher.dispatch(event) is True
        assert len(sink.messages) == 1

    def test_dispatch_default_event_delivered(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)

        event = _make_event(EventType.RUN_COMPLETED, {
            "worker": "test", "duration_seconds": 1.0,
        })
        assert dispatcher.dispatch(event) is True
        assert len(sink.messages) == 1

    def test_dispatch_suppressed_event_not_delivered(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)

        event = _make_event(EventType.RUN_STARTED)
        assert dispatcher.dispatch(event) is False
        assert len(sink.messages) == 0

    # --- No sinks ---

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

    # --- Override priority ---

    def test_override_suppress_to_always(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)

        dispatcher.override_priority(
            EventType.RUN_STARTED, NotificationPriority.ALWAYS
        )
        event = _make_event(EventType.RUN_STARTED)
        assert dispatcher.dispatch(event) is True
        assert len(sink.messages) == 1

    def test_override_always_to_suppress(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)

        dispatcher.override_priority(
            EventType.RUN_FAILED, NotificationPriority.SUPPRESS
        )
        event = _make_event(EventType.RUN_FAILED, {"reason": "err"})
        assert dispatcher.dispatch(event) is False
        assert len(sink.messages) == 0

    def test_override_persists(self):
        dispatcher = NotificationDispatcher()
        dispatcher.override_priority(
            EventType.RUN_STARTED, NotificationPriority.ALWAYS
        )
        assert dispatcher.get_priority(EventType.RUN_STARTED) == NotificationPriority.ALWAYS

    # --- get_priority ---

    def test_get_priority_known_event(self):
        dispatcher = NotificationDispatcher()
        assert dispatcher.get_priority(EventType.RUN_FAILED) == NotificationPriority.ALWAYS

    def test_get_priority_suppressed_event(self):
        dispatcher = NotificationDispatcher()
        assert dispatcher.get_priority(EventType.RUN_STARTED) == NotificationPriority.SUPPRESS

    # --- Stats ---

    def test_stats_initial(self):
        dispatcher = NotificationDispatcher()
        assert dispatcher.stats == {"delivered": 0, "suppressed": 0}

    def test_stats_after_delivery(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)

        dispatcher.dispatch(_make_event(EventType.RUN_FAILED, {"reason": "x"}))
        assert dispatcher.stats == {"delivered": 1, "suppressed": 0}

    def test_stats_after_suppression(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)

        dispatcher.dispatch(_make_event(EventType.RUN_STARTED))
        assert dispatcher.stats == {"delivered": 0, "suppressed": 1}

    def test_stats_mixed(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)

        dispatcher.dispatch(_make_event(EventType.RUN_FAILED, {"reason": "x"}))
        dispatcher.dispatch(_make_event(EventType.RUN_STARTED))
        dispatcher.dispatch(_make_event(EventType.RUN_FAILED, {"reason": "y"}))
        dispatcher.dispatch(_make_event(EventType.RUN_QUEUED))

        assert dispatcher.stats == {"delivered": 2, "suppressed": 2}

    # --- Multiple sinks ---

    def test_multiple_sinks_all_receive(self):
        dispatcher = NotificationDispatcher()
        sink1 = CliNotificationSink()
        sink2 = CliNotificationSink()
        dispatcher.add_sink(sink1)
        dispatcher.add_sink(sink2)

        event = _make_event(EventType.RUN_FAILED, {"reason": "err"})
        dispatcher.dispatch(event)

        assert len(sink1.messages) == 1
        assert len(sink2.messages) == 1

    def test_multiple_sinks_same_message(self):
        dispatcher = NotificationDispatcher()
        sink1 = CliNotificationSink()
        sink2 = CliNotificationSink()
        dispatcher.add_sink(sink1)
        dispatcher.add_sink(sink2)

        event = _make_event(EventType.RUN_FAILED, {"reason": "err"})
        dispatcher.dispatch(event)

        assert sink1.messages[0][0] == sink2.messages[0][0]

    def test_sinks_property(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)
        assert len(dispatcher.sinks) == 1
        assert dispatcher.sinks[0].sink_name == "cli"

    def test_sinks_property_returns_copy(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)
        sinks = dispatcher.sinks
        sinks.clear()
        assert len(dispatcher.sinks) == 1

    # --- Batch dispatch ---

    def test_dispatch_batch(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)

        events = [
            _make_event(EventType.APPROVAL_REQUESTED, {
                "title": "t", "risk": "l", "work_item_id": "w",
            }),
            _make_event(EventType.RUN_STARTED),   # suppressed
            _make_event(EventType.RUN_FAILED, {"reason": "err"}),
            _make_event(EventType.RUN_QUEUED),     # suppressed
        ]
        count = dispatcher.dispatch_batch(events)
        assert count == 2
        assert len(sink.messages) == 2

    def test_dispatch_batch_empty(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)
        assert dispatcher.dispatch_batch([]) == 0

    def test_dispatch_batch_all_suppressed(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)

        events = [
            _make_event(EventType.RUN_STARTED),
            _make_event(EventType.RUN_QUEUED),
        ]
        assert dispatcher.dispatch_batch(events) == 0
        assert len(sink.messages) == 0
        assert dispatcher.stats["suppressed"] == 2

    def test_dispatch_batch_all_delivered(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)

        events = [
            _make_event(EventType.RUN_FAILED, {"reason": "a"}),
            _make_event(EventType.RUN_FAILED, {"reason": "b"}),
        ]
        assert dispatcher.dispatch_batch(events) == 2
        assert len(sink.messages) == 2

    # --- Message content verification ---

    def test_dispatched_message_is_formatted(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)

        event = _make_event(EventType.RUN_FAILED, {"reason": "oom"})
        dispatcher.dispatch(event)
        msg = sink.messages[0][0]
        assert "Run failed" in msg
        assert "oom" in msg

    def test_dispatched_priority_matches_routing(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)

        event = _make_event(EventType.APPROVAL_REQUESTED, {
            "title": "t", "risk": "l", "work_item_id": "w",
        })
        dispatcher.dispatch(event)
        assert sink.messages[0][1] == NotificationPriority.ALWAYS

    def test_dispatched_event_object_passed_through(self):
        dispatcher = NotificationDispatcher()
        sink = CliNotificationSink()
        dispatcher.add_sink(sink)

        event = _make_event(
            EventType.RUN_FAILED,
            {"reason": "err"},
            event_id="evt_unique",
        )
        dispatcher.dispatch(event)
        assert sink.messages[0][2].event_id == "evt_unique"


# ============================================================================
# Integration: all ALWAYS events actually dispatch
# ============================================================================


class TestAlwaysEventsIntegration:
    """Verify every ALWAYS-routed event actually dispatches end-to-end."""

    @pytest.fixture()
    def dispatcher_with_sink(self):
        d = NotificationDispatcher()
        s = CliNotificationSink()
        d.add_sink(s)
        return d, s

    def test_approval_requested_dispatches(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        d.dispatch(_make_event(EventType.APPROVAL_REQUESTED, {
            "title": "t", "risk": "l", "work_item_id": "w",
        }))
        assert len(s.messages) == 1

    def test_run_failed_dispatches(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        d.dispatch(_make_event(EventType.RUN_FAILED, {"reason": "x"}))
        assert len(s.messages) == 1

    def test_security_violation_dispatches(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        d.dispatch(_make_event(
            EventType.SECURITY_VIOLATION_DETECTED, {"details": "x"}
        ))
        assert len(s.messages) == 1

    def test_approval_rejected_dispatches(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        d.dispatch(_make_event(
            EventType.APPROVAL_REJECTED, {"work_item_id": "w"}
        ))
        assert len(s.messages) == 1

    def test_policy_blocked_dispatches(self, dispatcher_with_sink):
        d, s = dispatcher_with_sink
        d.dispatch(_make_event(
            EventType.POLICY_BLOCKED_ACTION, {"rule": "r"}
        ))
        assert len(s.messages) == 1


# ============================================================================
# Integration: all SUPPRESS events actually suppressed
# ============================================================================


class TestSuppressEventsIntegration:
    """Verify every SUPPRESS-routed event is actually suppressed."""

    @pytest.fixture()
    def dispatcher_with_sink(self):
        d = NotificationDispatcher()
        s = CliNotificationSink()
        d.add_sink(s)
        return d, s

    @pytest.mark.parametrize("event_type", [
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
    ])
    def test_suppressed_event(self, dispatcher_with_sink, event_type):
        d, s = dispatcher_with_sink
        result = d.dispatch(_make_event(event_type))
        assert result is False
        assert len(s.messages) == 0
