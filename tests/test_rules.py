"""Tests for the deterministic rules engine."""

import pytest

from foxhound.policies.rules import (
    Rule,
    RuleCheckpoint,
    RuleOutcome,
    RulesEngine,
    RuleSuggestion,
    RuleSuggestionState,
    RuleType,
)


class TestRuleModel:
    """Test Rule Pydantic model."""

    def test_create_hard_rule(self) -> None:
        rule = Rule(
            rule_id="test_1",
            name="test_rule",
            rule_type=RuleType.HARD,
            checkpoint=RuleCheckpoint.PRE_EXECUTION,
            condition="Some condition",
            action="Block execution",
        )
        assert rule.rule_type == RuleType.HARD
        assert rule.enabled is True
        assert rule.priority == 100

    def test_rule_json_roundtrip(self) -> None:
        rule = Rule(
            rule_id="test_2",
            name="roundtrip",
            rule_type=RuleType.SOFT,
            checkpoint=RuleCheckpoint.DISCOVERY,
            condition="Condition",
            action="Action",
        )
        data = rule.model_dump()
        restored = Rule(**data)
        assert restored.rule_id == rule.rule_id
        assert restored.rule_type == rule.rule_type


class TestRuleTypes:
    """Test rule type enum values."""

    def test_rule_types(self) -> None:
        assert RuleType.HARD.value == "hard"
        assert RuleType.SOFT.value == "soft"
        assert RuleType.ADVISORY.value == "advisory"

    def test_checkpoints(self) -> None:
        assert RuleCheckpoint.DISCOVERY.value == "discovery"
        assert RuleCheckpoint.PRE_EXECUTION.value == "pre_execution"
        assert RuleCheckpoint.PRE_PROMOTION.value == "pre_promotion"

    def test_outcomes(self) -> None:
        assert RuleOutcome.BLOCK.value == "block"
        assert RuleOutcome.REROUTE.value == "reroute"
        assert RuleOutcome.REQUIRE_APPROVAL.value == "require_approval"
        assert RuleOutcome.ADVISORY.value == "advisory"


class TestRulesEngine:
    """Test rules engine evaluation."""

    @pytest.fixture()
    def engine(self) -> RulesEngine:
        return RulesEngine()

    def test_default_rules_loaded(self, engine: RulesEngine) -> None:
        rules = engine.rules
        assert len(rules) > 0
        types = {r.rule_type for r in rules}
        assert RuleType.HARD in types
        assert RuleType.SOFT in types
        assert RuleType.ADVISORY in types

    def test_get_rules_for_checkpoint(self, engine: RulesEngine) -> None:
        pre_exec = engine.get_rules_for_checkpoint(RuleCheckpoint.PRE_EXECUTION)
        assert len(pre_exec) > 0
        assert all(r.checkpoint == RuleCheckpoint.PRE_EXECUTION for r in pre_exec)

    def test_rules_sorted_by_priority(self, engine: RulesEngine) -> None:
        rules = engine.get_rules_for_checkpoint(RuleCheckpoint.PRE_EXECUTION)
        priorities = [r.priority for r in rules]
        assert priorities == sorted(priorities)

    def test_block_env_files(self, engine: RulesEngine) -> None:
        result = engine.evaluate(
            RuleCheckpoint.PRE_EXECUTION,
            {"paths": [".env", "src/main.py"]},
        )
        assert result.blocked is True
        matched = [r for r in result.results if r.matched and r.outcome == RuleOutcome.BLOCK]
        assert len(matched) >= 1

    def test_block_install_commands(self, engine: RulesEngine) -> None:
        result = engine.evaluate(
            RuleCheckpoint.PRE_EXECUTION,
            {"command": "pip install requests"},
        )
        assert result.blocked is True

    def test_block_npm_install(self, engine: RulesEngine) -> None:
        result = engine.evaluate(
            RuleCheckpoint.PRE_EXECUTION,
            {"command": "npm install lodash"},
        )
        assert result.blocked is True

    def test_max_retries_exceeded(self, engine: RulesEngine) -> None:
        result = engine.evaluate(
            RuleCheckpoint.PRE_EXECUTION,
            {"retry_count": 5, "max_retries": 3},
        )
        assert result.blocked is True

    def test_max_retries_within_limit(self, engine: RulesEngine) -> None:
        result = engine.evaluate(
            RuleCheckpoint.PRE_EXECUTION,
            {"retry_count": 1, "max_retries": 3},
        )
        hard_blocks = [
            r for r in result.results
            if r.rule.rule_id == "hard_max_retries" and r.matched
        ]
        assert len(hard_blocks) == 0

    def test_secret_leak_blocked(self, engine: RulesEngine) -> None:
        result = engine.evaluate(
            RuleCheckpoint.PRE_PROMOTION,
            {"has_secret_patterns": True},
        )
        assert result.blocked is True

    def test_escalate_on_retriable_failure(self, engine: RulesEngine) -> None:
        result = engine.evaluate(
            RuleCheckpoint.PRE_EXECUTION,
            {"previous_attempt_failed": True, "retriable_error": True},
        )
        assert result.rerouted is True

    def test_high_risk_requires_approval(self, engine: RulesEngine) -> None:
        result = engine.evaluate(
            RuleCheckpoint.PRE_EXECUTION,
            {"risk_level": "high"},
        )
        assert result.requires_approval is True

    def test_advisory_missing_tests(self, engine: RulesEngine) -> None:
        result = engine.evaluate(
            RuleCheckpoint.PRE_PROMOTION,
            {"has_tests": False},
        )
        assert len(result.advisory_notes) >= 1
        assert not result.blocked

    def test_advisory_large_diff(self, engine: RulesEngine) -> None:
        result = engine.evaluate(
            RuleCheckpoint.PRE_PROMOTION,
            {"diff_lines": 1000},
        )
        assert len(result.advisory_notes) >= 1
        assert not result.blocked

    def test_clean_context_passes(self, engine: RulesEngine) -> None:
        result = engine.evaluate(
            RuleCheckpoint.PRE_EXECUTION,
            {"paths": ["src/main.py"], "command": "", "retry_count": 0},
        )
        assert not result.blocked
        assert not result.requires_approval
        assert not result.rerouted

    def test_add_custom_rule(self, engine: RulesEngine) -> None:
        custom = Rule(
            rule_id="custom_1",
            name="custom_rule",
            rule_type=RuleType.HARD,
            checkpoint=RuleCheckpoint.DISCOVERY,
            condition="Custom condition",
            action="Custom action",
        )
        engine.add_rule(custom)
        rules = engine.get_rules_for_checkpoint(RuleCheckpoint.DISCOVERY)
        assert any(r.rule_id == "custom_1" for r in rules)

    def test_remove_rule(self, engine: RulesEngine) -> None:
        initial_count = len(engine.rules)
        assert engine.remove_rule("hard_no_env_files")
        assert len(engine.rules) == initial_count - 1

    def test_remove_nonexistent_rule(self, engine: RulesEngine) -> None:
        assert not engine.remove_rule("nonexistent")


class TestRuleSuggestion:
    """Test rule suggestion model and creation."""

    def test_create_suggestion(self) -> None:
        engine = RulesEngine()
        suggestion = engine.create_suggestion(
            rule_name="new_rule",
            rule_type=RuleType.SOFT,
            condition="Some pattern detected",
            action="Require approval",
            evidence="Seen in 5 runs",
            confidence=0.85,
            repo_id="repo_123",
        )
        assert suggestion.state == RuleSuggestionState.PENDING_REVIEW
        assert suggestion.rule_name == "new_rule"
        assert suggestion.confidence == 0.85
        assert suggestion.suggestion_id.startswith("rs_")

    def test_suggestion_state_values(self) -> None:
        assert RuleSuggestionState.PENDING_REVIEW.value == "pending_review"
        assert RuleSuggestionState.APPROVED.value == "approved"
        assert RuleSuggestionState.REJECTED.value == "rejected"
        assert RuleSuggestionState.ACTIVATED.value == "activated"

    def test_suggestion_defaults(self) -> None:
        suggestion = RuleSuggestion(
            rule_name="test",
            rule_type=RuleType.ADVISORY,
            condition="c",
            action="a",
        )
        assert suggestion.suggested_by == "analyzer"
        assert suggestion.confidence == 0.0
        assert suggestion.repo_id is None
