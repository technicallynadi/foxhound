"""Tests for form scanner: field classification and analysis."""

import pytest
from app.services.apply.form_scanner import (
    FormField, ScanResult, classify_field, match_field_to_profile, analyze_scan,
)


# ---------------------------------------------------------------------------
# Field classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,expected", [
    ("First Name", "auto_fill"),
    ("Last Name", "auto_fill"),
    ("Email", "auto_fill"),
    ("Phone number", "auto_fill"),
    ("LinkedIn URL", "auto_fill"),
    ("Location", "auto_fill"),
    ("Current company", "auto_fill"),
    ("Years of experience", "auto_fill"),
])
def test_classify_auto_fill(label, expected):
    assert classify_field(label) == expected


@pytest.mark.parametrize("label,expected", [
    ("Why do you want to work here?", "narrative"),
    ("Tell us about yourself", "narrative"),
    ("Describe your experience with distributed systems", "narrative"),
    ("Cover letter", "narrative"),
    ("What interests you about this role?", "narrative"),
])
def test_classify_narrative(label, expected):
    assert classify_field(label) == expected


@pytest.mark.parametrize("label,expected", [
    ("Salary expectations", "sensitive"),
    ("Desired compensation", "sensitive"),
    ("Criminal background", "sensitive"),
    ("Disability status", "sensitive"),
    ("Gender", "sensitive"),
    ("Start date", "sensitive"),
])
def test_classify_sensitive(label, expected):
    assert classify_field(label) == expected


def test_classify_unknown():
    assert classify_field("Favorite programming language") == "unknown"


# ---------------------------------------------------------------------------
# Profile field matching
# ---------------------------------------------------------------------------

def test_match_field_to_profile():
    assert match_field_to_profile("First Name") == "first_name"
    assert match_field_to_profile("Email address") == "email"
    assert match_field_to_profile("LinkedIn") == "linkedin"
    assert match_field_to_profile("Favorite color") is None


# ---------------------------------------------------------------------------
# Scan analysis
# ---------------------------------------------------------------------------

def test_analyze_scan_basic():
    scan = ScanResult(
        status="scannable",
        fields=[
            FormField(label="First Name", field_type="text", required=True),
            FormField(label="Email", field_type="email", required=True),
            FormField(label="Why this company?", field_type="textarea"),
            FormField(label="Salary expectations", field_type="text"),
            FormField(label="Resume", field_type="file"),
        ],
    )
    result = analyze_scan(scan)
    assert len(result["auto_fill"]) == 2
    assert len(result["narrative"]) == 1
    assert len(result["sensitive"]) == 1
    assert result["has_resume_upload"] is False  # file fields are skipped
    assert result["needs_user_input"] is True
    assert result["total_fields"] == 5  # includes file


def test_analyze_scan_all_auto():
    scan = ScanResult(
        status="scannable",
        fields=[
            FormField(label="First Name", field_type="text"),
            FormField(label="Last Name", field_type="text"),
            FormField(label="Email", field_type="email"),
        ],
    )
    result = analyze_scan(scan)
    assert result["needs_user_input"] is False
    assert result["auto_fillable_count"] == 3


def test_analyze_scan_empty():
    scan = ScanResult(status="scannable", fields=[])
    result = analyze_scan(scan)
    assert result["total_fields"] == 0
    assert result["needs_user_input"] is False
