from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.application_guidance import (
    build_application_context,
    build_recommended_next_action,
    parse_serialized_recommended_next_action,
    serialize_recommended_next_action,
)


def _sample_app(**overrides):
    now = datetime.now(timezone.utc)
    base = {
        "id": "app_123",
        "job_id": "job_123",
        "status": "submitted",
        "posting_status": "active",
        "submitted_at": now - timedelta(days=8),
        "created_at": now - timedelta(days=10),
        "followup_day3_sent": True,
        "followup_day7_sent": False,
        "followup_day14_sent": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _sample_job(**overrides):
    base = {
        "id": "job_123",
        "company": "Acme",
        "title": "Staff Engineer",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_build_application_context_contract_shape():
    context = build_application_context(
        _sample_app(),
        _sample_job(),
        brief_ready=True,
        brief_status="ready",
    )

    assert context["application_id"] == "app_123"
    assert context["job_id"] == "job_123"
    assert context["company"] == "Acme"
    assert context["role"] == "Staff Engineer"
    assert context["status"] == "submitted"
    assert context["posting_status"] == "active"
    assert isinstance(context["days_since_applied"], int)
    assert context["followup_day3_sent"] is True
    assert context["followup_day7_sent"] is False
    assert context["brief_ready"] is True
    assert context["brief_status"] == "ready"


def test_build_recommended_next_action_uses_followup_window():
    context = build_application_context(_sample_app(), _sample_job())
    action = build_recommended_next_action(context, module="status")

    assert action["label"] == "Send the day-7 follow-up"
    assert action["priority"] == "high"
    assert action["href"] == "/brief/app_123"
    assert action["href_label"] == "Open Brief"


def test_parse_serialized_recommended_next_action_supports_legacy_string():
    action = parse_serialized_recommended_next_action("Follow up in 7 days")
    assert action["label"] == "Recommended next action"
    assert action["detail"] == "Follow up in 7 days"
    assert action["priority"] == "normal"


def test_round_trip_recommended_next_action_json():
    initial = build_recommended_next_action(None, module="brief")
    payload = serialize_recommended_next_action(initial)
    parsed = parse_serialized_recommended_next_action(payload)

    assert json.loads(payload)["label"] == initial["label"]
    assert parsed == initial
