"""Tests for the evaluation engine."""

import pytest

from foxhound.core.models import RiskLevel, TrustLevel
from foxhound.evaluation.engine import (
    Classification,
    EvaluationEngine,
    ReadinessState,
    assess_readiness,
    assess_risk,
    check_grounding,
    check_policy_compliance,
    check_scope,
    check_trust_compliance,
    classify_result,
)
from foxhound.harness.worker_protocol import SanitizedOutput


class TestCheckGrounding:
    """Test grounding evaluation criterion."""

    def test_grounded_with_evidence(self) -> None:
        result = check_grounding(
            {"evidence": {"ci_log": "..."}, "source_files": ["main.py"]},
            {"main.py": TrustLevel.SEMI_TRUSTED.value},
        )
        assert result.passed
        assert result.score > 0.5

    def test_grounded_no_trusted_sources(self) -> None:
        result = check_grounding(
            {"evidence": {"log": "..."}},
            {},
        )
        assert result.passed
        assert result.score == 0.5

    def test_no_evidence(self) -> None:
        result = check_grounding(
            {"description": "Just a guess"},
            {},
        )
        assert not result.passed
        assert result.score < 0.5


class TestCheckScope:
    """Test scope evaluation criterion."""

    def test_reasonable_scope(self) -> None:
        result = check_scope(
            {"title": "Fix login bug"},
            ["src/auth.py", "tests/test_auth.py"],
        )
        assert result.passed
        assert result.score > 0.5

    def test_too_many_files(self) -> None:
        files = [f"src/file_{i}.py" for i in range(25)]
        result = check_scope({"title": "Big change"}, files)
        assert not result.passed
        assert "too broad" in result.details.lower()

    def test_vague_description(self) -> None:
        result = check_scope(
            {"description": "Refactor all the things in the entire codebase"},
            ["src/main.py"],
        )
        assert not result.passed
        assert "too broad" in result.details.lower()

    def test_empty_files(self) -> None:
        result = check_scope({"title": "Discovery item"}, [])
        assert result.passed


class TestCheckTrustCompliance:
    """Test trust compliance evaluation criterion."""

    def test_all_trusted(self) -> None:
        result = check_trust_compliance(
            {"file.py": TrustLevel.TRUSTED.value},
            [],
        )
        assert result.passed
        assert result.score == 1.0

    def test_with_redactions(self) -> None:
        result = check_trust_compliance(
            {"file.py": TrustLevel.SEMI_TRUSTED.value},
            ["Stripped pattern: eval(...)"],
        )
        assert result.passed
        assert result.score == 0.9

    def test_untrusted_no_redaction(self) -> None:
        result = check_trust_compliance(
            {"reddit_post.txt": TrustLevel.UNTRUSTED.value},
            [],
        )
        assert not result.passed

    def test_empty_labels(self) -> None:
        result = check_trust_compliance({}, [])
        assert result.passed


class TestCheckPolicyCompliance:
    """Test policy compliance evaluation criterion."""

    def test_no_violations(self) -> None:
        result = check_policy_compliance([], [])
        assert result.passed
        assert result.score == 1.0

    def test_with_critical_flags(self) -> None:
        result = check_policy_compliance(
            ["BLOCK: command not allowed"],
            [],
        )
        assert not result.passed

    def test_stripped_patterns_ok(self) -> None:
        result = check_policy_compliance(
            [],
            ["Stripped pattern: eval(x)"],
        )
        assert result.passed
        assert result.score == 0.7


class TestClassifyResult:
    """Test classification logic."""

    def test_all_pass_high_score(self) -> None:
        from foxhound.evaluation.engine import EvaluationCriteria

        criteria = [
            EvaluationCriteria(name="grounding", passed=True, score=0.9),
            EvaluationCriteria(name="scope", passed=True, score=0.8),
            EvaluationCriteria(name="trust_compliance", passed=True, score=1.0),
            EvaluationCriteria(name="policy_compliance", passed=True, score=1.0),
        ]
        assert classify_result(criteria) == Classification.ACCEPTED

    def test_all_pass_low_score(self) -> None:
        from foxhound.evaluation.engine import EvaluationCriteria

        criteria = [
            EvaluationCriteria(name="grounding", passed=True, score=0.5),
            EvaluationCriteria(name="scope", passed=True, score=0.5),
            EvaluationCriteria(name="trust_compliance", passed=True, score=0.5),
            EvaluationCriteria(name="policy_compliance", passed=True, score=0.5),
        ]
        assert classify_result(criteria) == Classification.REVIEW

    def test_trust_failure_quarantines(self) -> None:
        from foxhound.evaluation.engine import EvaluationCriteria

        criteria = [
            EvaluationCriteria(name="grounding", passed=True, score=0.9),
            EvaluationCriteria(name="scope", passed=True, score=0.8),
            EvaluationCriteria(name="trust_compliance", passed=False, score=0.3),
            EvaluationCriteria(name="policy_compliance", passed=True, score=1.0),
        ]
        assert classify_result(criteria) == Classification.QUARANTINE

    def test_scope_failure_reviews(self) -> None:
        from foxhound.evaluation.engine import EvaluationCriteria

        criteria = [
            EvaluationCriteria(name="grounding", passed=True, score=0.9),
            EvaluationCriteria(name="scope", passed=False, score=0.2),
            EvaluationCriteria(name="trust_compliance", passed=True, score=1.0),
            EvaluationCriteria(name="policy_compliance", passed=True, score=1.0),
        ]
        assert classify_result(criteria) == Classification.REVIEW


class TestAssessReadiness:
    """Test readiness assessment."""

    def test_accepted_is_ready(self) -> None:
        assert assess_readiness(Classification.ACCEPTED, []) == ReadinessState.READY

    def test_quarantine_is_blocked(self) -> None:
        assert assess_readiness(Classification.QUARANTINE, []) == ReadinessState.BLOCKED

    def test_scope_too_broad(self) -> None:
        from foxhound.evaluation.engine import EvaluationCriteria

        criteria = [
            EvaluationCriteria(
                name="scope", passed=False, score=0.2,
                details="Too broad: 25 files changed",
            ),
        ]
        assert assess_readiness(Classification.REVIEW, criteria) == ReadinessState.TOO_BROAD

    def test_review_needs_edit(self) -> None:
        assert assess_readiness(Classification.REVIEW, []) == ReadinessState.NEEDS_EDIT


class TestAssessRisk:
    """Test risk assessment."""

    def test_low_risk(self) -> None:
        from foxhound.evaluation.engine import EvaluationCriteria

        criteria = [EvaluationCriteria(name="test", passed=True, score=0.9)]
        assert assess_risk(criteria, ["file.py"]) == RiskLevel.LOW

    def test_high_risk_many_files(self) -> None:
        from foxhound.evaluation.engine import EvaluationCriteria

        criteria = [EvaluationCriteria(name="test", passed=True, score=0.9)]
        files = [f"file_{i}.py" for i in range(15)]
        assert assess_risk(criteria, files) == RiskLevel.HIGH

    def test_high_risk_low_score(self) -> None:
        from foxhound.evaluation.engine import EvaluationCriteria

        criteria = [EvaluationCriteria(name="test", passed=False, score=0.3)]
        assert assess_risk(criteria, ["file.py"]) == RiskLevel.HIGH

    def test_medium_risk(self) -> None:
        from foxhound.evaluation.engine import EvaluationCriteria

        criteria = [EvaluationCriteria(name="test", passed=True, score=0.6)]
        assert assess_risk(criteria, ["file.py"]) == RiskLevel.MEDIUM


class TestEvaluationEngine:
    """Test full evaluation engine."""

    @pytest.fixture()
    def engine(self) -> EvaluationEngine:
        return EvaluationEngine()

    def test_clean_grounded_output(self, engine: EvaluationEngine) -> None:
        output = SanitizedOutput(
            payload={"evidence": {"ci_log": "failure"}, "title": "Fix CI"},
            files_changed=["src/main.py"],
            redactions_applied=[],
        )
        result = engine.evaluate(
            output,
            trust_labels={"src/main.py": TrustLevel.SEMI_TRUSTED.value},
        )
        assert result.classification == Classification.ACCEPTED
        assert result.readiness == ReadinessState.READY
        assert result.confidence > 0.5

    def test_ungrounded_output(self, engine: EvaluationEngine) -> None:
        output = SanitizedOutput(
            payload={"description": "Maybe we should try this"},
            files_changed=[],
            redactions_applied=[],
        )
        result = engine.evaluate(output)
        assert result.classification in (Classification.REVIEW, Classification.REJECT)

    def test_untrusted_unsanitized_quarantines(self, engine: EvaluationEngine) -> None:
        output = SanitizedOutput(
            payload={"evidence": {"reddit": "..."}},
            files_changed=["data.txt"],
            redactions_applied=[],
        )
        result = engine.evaluate(
            output,
            trust_labels={"data.txt": TrustLevel.UNTRUSTED.value},
        )
        assert result.classification == Classification.QUARANTINE
        assert result.readiness == ReadinessState.BLOCKED

    def test_policy_violation_quarantines(self, engine: EvaluationEngine) -> None:
        output = SanitizedOutput(
            payload={"evidence": {"log": "..."}},
            files_changed=["src/main.py"],
            redactions_applied=[],
        )
        result = engine.evaluate(
            output,
            trust_labels={"src/main.py": TrustLevel.SEMI_TRUSTED.value},
            safety_flags=["BLOCK: forbidden command"],
        )
        assert result.classification == Classification.QUARANTINE

    def test_too_broad_scope(self, engine: EvaluationEngine) -> None:
        files = [f"src/file_{i}.py" for i in range(25)]
        output = SanitizedOutput(
            payload={"evidence": {"log": "..."}, "title": "Mass refactor"},
            files_changed=files,
            redactions_applied=[],
        )
        labels = {f: TrustLevel.SEMI_TRUSTED.value for f in files}
        result = engine.evaluate(output, trust_labels=labels)
        assert result.readiness == ReadinessState.TOO_BROAD
        assert result.risk_level == RiskLevel.HIGH

    def test_harness_result_conversion(self, engine: EvaluationEngine) -> None:
        output = SanitizedOutput(
            payload={"evidence": {"log": "fail"}, "title": "Fix"},
            files_changed=["src/main.py"],
            redactions_applied=[],
        )
        result = engine.evaluate(
            output,
            trust_labels={"src/main.py": TrustLevel.SEMI_TRUSTED.value},
        )
        harness_result = result.to_harness_result()
        assert harness_result.passed == (
            result.classification in (Classification.ACCEPTED, Classification.REVIEW)
        )
        assert harness_result.confidence == result.confidence

    def test_recommended_action_quarantine(self, engine: EvaluationEngine) -> None:
        output = SanitizedOutput(
            payload={"evidence": {"log": "..."}},
            files_changed=["data.txt"],
            redactions_applied=[],
        )
        result = engine.evaluate(
            output,
            trust_labels={"data.txt": TrustLevel.UNTRUSTED.value},
        )
        assert result.recommended_next_action == "quarantine_review"

    def test_evaluator_notes_on_failure(self, engine: EvaluationEngine) -> None:
        output = SanitizedOutput(
            payload={"description": "vague"},
            files_changed=[],
            redactions_applied=[],
        )
        result = engine.evaluate(output)
        assert len(result.evaluator_notes) > 0

    def test_criteria_count(self, engine: EvaluationEngine) -> None:
        output = SanitizedOutput(
            payload={"title": "test"},
            files_changed=[],
            redactions_applied=[],
        )
        result = engine.evaluate(output)
        assert len(result.criteria_results) == 4
        names = {c.name for c in result.criteria_results}
        assert names == {"grounding", "scope", "trust_compliance", "policy_compliance"}
