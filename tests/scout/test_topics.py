"""Tests for topic filtering and relevance scoring."""

import pytest

from foxhound.scout.topics import score_topic_relevance, score_topic_relevance_heuristic


class TestScoreTopicRelevanceHeuristic:
    """Tests for heuristic topic relevance scoring."""

    def test_exact_topic_match(self) -> None:
        score, topic = score_topic_relevance_heuristic(
            "authentication and identity management tools",
            ["authentication and identity management"],
        )
        assert score > 0.0
        assert topic == "authentication and identity management"

    def test_no_topics_returns_zero(self) -> None:
        score, topic = score_topic_relevance_heuristic("some signal", [])
        assert score == 0.0
        assert topic == ""

    def test_no_match(self) -> None:
        score, topic = score_topic_relevance_heuristic(
            "restaurant booking system",
            ["quantum computing research"],
        )
        assert score == 0.0

    def test_partial_match(self) -> None:
        score, topic = score_topic_relevance_heuristic(
            "new CLI tool for developer productivity",
            ["developer productivity CLI tools"],
        )
        assert score > 0.0
        assert "developer" in topic or "CLI" in topic or "productivity" in topic

    def test_best_topic_selected(self) -> None:
        _, topic = score_topic_relevance_heuristic(
            "developer productivity CLI tools for authentication",
            [
                "restaurant technology",
                "developer productivity CLI tools",
                "AI research",
            ],
        )
        assert topic == "developer productivity CLI tools"

    def test_empty_signal(self) -> None:
        score, topic = score_topic_relevance_heuristic("", ["some topic"])
        assert score == 0.0

    def test_score_capped_at_five(self) -> None:
        score, _ = score_topic_relevance_heuristic(
            "developer productivity CLI tools for developers",
            ["developer productivity CLI tools"],
        )
        assert score <= 5.0


class TestScoreTopicRelevance:
    """Tests for score_topic_relevance with no router (heuristic only)."""

    def test_without_router(self) -> None:
        score, topic = score_topic_relevance(
            "authentication tools for developers",
            ["authentication and identity management"],
            router=None,
        )
        assert score >= 0.0
        assert isinstance(topic, str)

    def test_empty_topics(self) -> None:
        score, topic = score_topic_relevance("some signal", [], router=None)
        assert score == 0.0
        assert topic == ""
