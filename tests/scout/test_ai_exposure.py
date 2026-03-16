"""Tests for AI exposure analysis module."""

import pytest

from foxhound.core.models import AIExposureAngle
from foxhound.scout.ai_exposure import score_ai_exposure, score_ai_exposure_heuristic


class TestScoreAIExposureHeuristic:
    """Tests for heuristic AI exposure scoring."""

    @pytest.mark.parametrize(
        "text,expected_angle",
        [
            ("software developer tools for coding", AIExposureAngle.DISRUPTION),
            ("data entry automation platform", AIExposureAngle.DISRUPTION),
            ("copywriting and content writing tool", AIExposureAngle.DISRUPTION),
            ("plumber scheduling and invoicing app", AIExposureAngle.GREENFIELD),
            ("restaurant booking system", AIExposureAngle.GREENFIELD),
            ("salon appointment management", AIExposureAngle.GREENFIELD),
            ("landscaping business management", AIExposureAngle.GREENFIELD),
        ],
    )
    def test_angle_classification(self, text: str, expected_angle: AIExposureAngle) -> None:
        _, angle = score_ai_exposure_heuristic(text)
        assert angle == expected_angle

    def test_high_exposure_score_range(self) -> None:
        score, _ = score_ai_exposure_heuristic("software developer analytics")
        assert score >= 7.0

    def test_low_exposure_score_range(self) -> None:
        score, _ = score_ai_exposure_heuristic("plumber invoicing tool")
        assert score <= 3.0

    def test_neutral_text_moderate_score(self) -> None:
        score, _ = score_ai_exposure_heuristic("generic business tool")
        assert 0.0 <= score <= 10.0


class TestScoreAIExposure:
    """Tests for score_ai_exposure with no router (heuristic only)."""

    def test_without_router(self) -> None:
        score, angle = score_ai_exposure("restaurant management software", router=None)
        assert 0.0 <= score <= 10.0
        assert angle in (AIExposureAngle.DISRUPTION, AIExposureAngle.GREENFIELD)

    def test_returns_tuple(self) -> None:
        result = score_ai_exposure("developer tools", router=None)
        assert isinstance(result, tuple)
        assert len(result) == 2
