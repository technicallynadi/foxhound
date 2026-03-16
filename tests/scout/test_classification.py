"""Tests for signal classification module."""

import pytest

from foxhound.core.models import SignalTier
from foxhound.scout.classification import classify_signal, classify_signal_heuristic


class TestClassifySignalHeuristic:
    """Tests for heuristic signal classification."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("I hate using this tool, it wastes so much time", SignalTier.PAIN),
            ("This process is so manual and frustrating", SignalTier.PAIN),
            ("Why doesn't this exist? I spent hours doing this", SignalTier.PAIN),
            ("We wrote a script to handle the CSV export", SignalTier.WORKAROUND),
            ("Our team built an internal tool for deployment", SignalTier.WORKAROUND),
            ("We hacked together a quick fix for auth", SignalTier.WORKAROUND),
            ("Is there a tool for automating database migrations?", SignalTier.REPEATED_QUESTION),
            ("How do people solve config management at scale?", SignalTier.REPEATED_QUESTION),
            ("Does anything automate API documentation?", SignalTier.REPEATED_QUESTION),
            ("This tool would be perfect if it supported YAML", SignalTier.FEATURE_GAP),
            ("Feature request: add dark mode support", SignalTier.FEATURE_GAP),
            ("Someone should build an AI for everything", SignalTier.TREND),
            ("The future of DevOps is exciting", SignalTier.TREND),
            ("Random text with no indicators", SignalTier.TREND),
        ],
    )
    def test_classification(self, text: str, expected: SignalTier) -> None:
        assert classify_signal_heuristic(text) == expected

    def test_case_insensitive(self) -> None:
        assert classify_signal_heuristic("I HATE THIS TOOL") == SignalTier.PAIN

    def test_pain_takes_priority_over_workaround(self) -> None:
        text = "I hate this so I wrote a script to workaround it"
        assert classify_signal_heuristic(text) == SignalTier.PAIN


class TestClassifySignal:
    """Tests for classify_signal with no router (heuristic only)."""

    def test_without_router(self) -> None:
        result = classify_signal("This process is frustrating", router=None)
        assert result == SignalTier.PAIN

    def test_trend_fallback(self) -> None:
        result = classify_signal("Neutral discussion about technology", router=None)
        assert result == SignalTier.TREND
