"""Tests for the code review system.

Covers:
- CodeReviewWorker (#46): harness contract, capabilities, review execution
- Review model routing (#47): strategy selection, tier mapping, multi-pass
- Review CLI output (#48): formatting, panel rendering
- Ralph review integration (#49): intermediate/final reviews, pause logic
"""


import pytest

from foxhound.core.models import (
    ExecutionMode,
    ExecutionSnapshot,
    ModelTier,
    PolicyRef,
    RecipeRef,
    ResultStatus,
    TaskEnvelope,
    TrustLevel,
)
from foxhound.execution.review import (
    CategoryResult,
    CodeReviewWorker,
    Finding,
    FindingSeverity,
    ReviewCategory,
    ReviewResult,
    ReviewStrategy,
    ReviewVerdict,
    build_review_manifest_fields,
    build_review_summary,
    compute_category_results,
    compute_confidence,
    compute_verdict,
    format_review_cli,
    get_primary_tier,
    get_tier_for_category,
    render_review_panel,
    run_final_review,
    run_intermediate_review,
    select_review_strategy,
    should_pause_ralph,
)
from foxhound.harness.worker_protocol import (
    Capability,
    RuntimeHandle,
    SanitizedOutput,
    WorkerClass,
    WorkerOutput,
    validate_worker_capabilities,
)

# =========================================================================
# Test Fixtures
# =========================================================================

_ALL_PASS_CATEGORIES = {
    "correctness": CategoryResult.PASS,
    "security": CategoryResult.PASS,
    "architecture": CategoryResult.PASS,
    "style": CategoryResult.PASS,
    "completeness": CategoryResult.PASS,
}

_RO_RUNTIME = RuntimeHandle(
    execution_mode=ExecutionMode.READ_ONLY,
    capabilities={Capability.REPO_READ},
    budget_remaining=1.0,
    timeout_remaining=120.0,
)


def _make_task(**overrides) -> TaskEnvelope:
    """Create a TaskEnvelope for testing."""
    defaults = {
        "task_id": "task_001",
        "job_id": "job_001",
        "run_id": "run_001",
        "repo_id": "repo_001",
        "execution_snapshot": ExecutionSnapshot(
            recipe_ref=RecipeRef(
                name="test_recipe", version="1.0.0", content_hash="abc123"
            ),
            policy_ref=PolicyRef(
                name="default", version="1.0.0", content_hash="def456"
            ),
            config_hash="config_hash",
        ),
        "budget": 1.0,
        "timeout_seconds": 120,
    }
    defaults.update(overrides)
    return TaskEnvelope(**defaults)


def _make_finding(
    category: ReviewCategory = ReviewCategory.CORRECTNESS,
    severity: FindingSeverity = FindingSeverity.WARNING,
    file: str = "test.py",
    line: int | None = 10,
    description: str = "Test finding",
    recommendation: str = "Fix it",
) -> Finding:
    """Create a Finding for testing."""
    return Finding(
        category=category, severity=severity, file=file,
        line=line, description=description, recommendation=recommendation,
    )


def _make_review_result(
    verdict: ReviewVerdict = ReviewVerdict.PASS,
    confidence: float = 0.95,
    strategy: ReviewStrategy = ReviewStrategy.FULL_REASONING,
    findings: list[Finding] | None = None,
    category_results: dict | None = None,
    **kwargs,
) -> ReviewResult:
    """Create a ReviewResult for testing."""
    defaults = {
        "review_id": "rev_001",
        "run_id": "run_001",
        "model_tier": "reasoning",
        "review_strategy": strategy,
        "overall_verdict": verdict,
        "confidence": confidence,
        "findings": findings or [],
        "category_results": category_results or {},
    }
    defaults.update(kwargs)
    return ReviewResult(**defaults)


CLEAN_DIFF = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,5 @@
 def hello():
-    return "old"
+    return "new"
+    # added line
"""

SECRET_DIFF = """\
diff --git a/src/config.py b/src/config.py
+api_key = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
+password = "supersecretpassword123"
"""

EVAL_DIFF = """\
diff --git a/src/dangerous.py b/src/dangerous.py
+result = eval(user_input)
+data = exec(code_string)
"""


# =========================================================================
# #46 -- CodeReviewWorker Tests
# =========================================================================


class TestCodeReviewWorkerDefinition:
    """Test worker identity and capability constraints."""

    def test_worker_identity(self):
        worker = CodeReviewWorker()
        assert worker.worker_name == "code_review_worker"
        assert worker.worker_class == WorkerClass.HELPER
        assert worker.default_timeout_seconds == 120
        assert worker.default_budget == 0.50

    def test_capabilities_repo_read_only(self):
        worker = CodeReviewWorker()
        assert worker.capabilities == {Capability.REPO_READ}
        for excluded in (Capability.REPO_WRITE, Capability.NETWORK, Capability.SHELL, Capability.SPAWN):
            assert excluded not in worker.capabilities
        assert worker.allowed_spawn_targets == []

    @pytest.mark.parametrize("extra_cap,expect_violation", [
        (set(), False),
        ({Capability.REPO_WRITE}, True),
        ({Capability.NETWORK}, True),
        ({Capability.SHELL}, True),
        ({Capability.SPAWN}, True),
    ])
    def test_capabilities_matrix(self, extra_cap, expect_violation):
        caps = {Capability.REPO_READ} | extra_cap
        violations = validate_worker_capabilities("code_review_worker", caps)
        if expect_violation:
            assert len(violations) == 1
        else:
            assert violations == []


class TestCodeReviewWorkerHarness:
    """Test the six-method harness contract."""

    def test_validate_input_valid(self):
        worker = CodeReviewWorker(diff_text=CLEAN_DIFF, run_id="run_001")
        result = worker.validate_input(_make_task())
        assert result.valid is True
        assert result.errors == []

    def test_validate_input_missing_job_id(self):
        worker = CodeReviewWorker(diff_text=CLEAN_DIFF)
        result = worker.validate_input(_make_task(job_id=""))
        assert result.valid is False
        assert any("job_id" in e for e in result.errors)

    def test_validate_input_no_diff_or_files(self):
        worker = CodeReviewWorker()
        result = worker.validate_input(_make_task())
        assert result.valid is False
        assert any("diff" in e.lower() or "files" in e.lower() for e in result.errors)

    def test_validate_input_with_files_no_diff(self):
        worker = CodeReviewWorker(files_changed=["src/app.py"])
        result = worker.validate_input(_make_task())
        assert result.valid is True

    def test_build_context(self):
        worker = CodeReviewWorker(
            diff_text=CLEAN_DIFF, files_changed=["src/app.py"],
            validation_results=[{"command": "pytest", "passed": True}],
        )
        ctx = worker.build_context(_make_task())
        assert "diff_text" in ctx.context_pack
        assert ctx.trust_labels["diff_text"] == TrustLevel.SEMI_TRUSTED.value
        assert ctx.trust_labels["review_strategy"] == TrustLevel.TRUSTED.value
        assert "src/app.py" in ctx.files_included

    def test_execute_produces_review_result(self):
        worker = CodeReviewWorker(diff_text=CLEAN_DIFF, run_id="run_001")
        output = worker.execute(_make_task(), _RO_RUNTIME)
        assert "review_id" in output.payload
        assert "overall_verdict" in output.payload
        assert "finding_count" in output.payload
        assert output.commands_run == []
        assert output.files_changed == []

    def test_execute_clean_diff_passes(self):
        worker = CodeReviewWorker(diff_text=CLEAN_DIFF, run_id="run_001")
        worker.execute(_make_task(), _RO_RUNTIME)
        assert worker.review_result is not None
        assert worker.review_result.overall_verdict == ReviewVerdict.PASS

    def test_execute_secret_diff_finds_issues(self):
        worker = CodeReviewWorker(diff_text=SECRET_DIFF, run_id="run_001")
        worker.execute(_make_task(), _RO_RUNTIME)
        assert worker.review_result is not None
        assert len(worker.review_result.findings) > 0
        security_findings = [
            f for f in worker.review_result.findings
            if f.category == ReviewCategory.SECURITY
        ]
        assert len(security_findings) > 0

    def test_sanitize_output(self):
        worker = CodeReviewWorker(diff_text=CLEAN_DIFF)
        output = WorkerOutput(
            payload={"test": "value", "review_id": "rev_abc"},
            commands_run=[], files_changed=[], cost=0.0, artifact_paths=[],
        )
        sanitized = worker.sanitize_output(output)
        assert sanitized.payload["test"] == "value"

    def test_evaluate_output_after_review(self):
        worker = CodeReviewWorker(diff_text=CLEAN_DIFF, run_id="run_001")
        output = worker.execute(_make_task(), _RO_RUNTIME)
        sanitized = worker.sanitize_output(output)
        eval_result = worker.evaluate_output(sanitized)
        assert eval_result.passed is True
        assert eval_result.recommended_next_action == "present_review"

    def test_evaluate_output_without_review(self):
        worker = CodeReviewWorker(diff_text=CLEAN_DIFF)
        sanitized = SanitizedOutput(
            payload={}, commands_run=[], files_changed=[],
            cost=0.0, artifact_paths=[], redactions_applied=[],
        )
        eval_result = worker.evaluate_output(sanitized)
        assert eval_result.passed is False

    def test_finalize_produces_result_envelope(self):
        worker = CodeReviewWorker(diff_text=CLEAN_DIFF, run_id="run_001")
        output = worker.execute(_make_task(), _RO_RUNTIME)
        sanitized = worker.sanitize_output(output)
        eval_result = worker.evaluate_output(sanitized)
        result = worker.finalize(eval_result)
        assert result.status == ResultStatus.SUCCESS
        assert "review_id" in result.payload
        assert "overall_verdict" in result.payload

    def test_full_harness_lifecycle(self):
        """End-to-end: validate -> build -> execute -> sanitize -> evaluate -> finalize."""
        worker = CodeReviewWorker(
            diff_text=CLEAN_DIFF, files_changed=["src/app.py"], run_id="run_001",
        )
        task = _make_task()

        val = worker.validate_input(task)
        assert val.valid

        ctx = worker.build_context(task)
        assert ctx.context_pack

        output = worker.execute(task, _RO_RUNTIME)
        assert output.payload

        sanitized = worker.sanitize_output(output)
        assert sanitized.payload

        eval_result = worker.evaluate_output(sanitized)
        assert eval_result.passed

        result = worker.finalize(eval_result)
        assert result.status == ResultStatus.SUCCESS


# =========================================================================
# #47 -- Review Model Routing Tests
# =========================================================================


class TestReviewStrategy:
    """Test review strategy selection."""

    def test_default_strategy_is_full_reasoning(self):
        assert select_review_strategy() == ReviewStrategy.FULL_REASONING

    @pytest.mark.parametrize("kwargs,expected", [
        ({"is_ralph_intermediate": True}, ReviewStrategy.RALPH_INTERMEDIATE),
        ({"is_ralph_final": True}, ReviewStrategy.RALPH_FINAL),
        ({"budget_constrained": True}, ReviewStrategy.BUDGET_BALANCED),
        ({"cost_optimized": True}, ReviewStrategy.COST_OPTIMIZED),
    ])
    def test_strategy_selection(self, kwargs, expected):
        assert select_review_strategy(**kwargs) == expected

    def test_ralph_intermediate_overrides_budget(self):
        strategy = select_review_strategy(
            is_ralph_intermediate=True, budget_constrained=True
        )
        assert strategy == ReviewStrategy.RALPH_INTERMEDIATE


@pytest.mark.parametrize("strategy,expected_tier", [
    (ReviewStrategy.FULL_REASONING, ModelTier.REASONING),
    (ReviewStrategy.BUDGET_BALANCED, ModelTier.BALANCED),
    (ReviewStrategy.RALPH_INTERMEDIATE, ModelTier.FAST),
    (ReviewStrategy.COST_OPTIMIZED, ModelTier.REASONING),
])
def test_primary_tier(strategy, expected_tier):
    assert get_primary_tier(strategy) == expected_tier


@pytest.mark.parametrize("strategy,expected", [
    (ReviewStrategy.FULL_REASONING, "full_reasoning"),
    (ReviewStrategy.COST_OPTIMIZED, "cost_optimized"),
])
def test_strategy_recorded_in_manifest(strategy, expected):
    result = _make_review_result(strategy=strategy)
    assert build_review_manifest_fields(result)["review_strategy"] == expected


def test_no_model_names_in_strategy_map():
    """Ensure no hardcoded model names -- only tiers."""
    from foxhound.execution.review import _STRATEGY_TIER_MAP

    for strategy, tier_map in _STRATEGY_TIER_MAP.items():
        for category, tier in tier_map.items():
            assert isinstance(tier, ModelTier), (
                f"Strategy {strategy} category {category} has non-tier value: {tier}"
            )


# =========================================================================
# #46 -- Review Evaluation Logic Tests
# =========================================================================


class TestComputeVerdict:
    """Test verdict computation from findings."""

    @pytest.mark.parametrize("severities,expected", [
        ([], ReviewVerdict.PASS),
        ([FindingSeverity.SUGGESTION], ReviewVerdict.PASS),
        ([FindingSeverity.WARNING], ReviewVerdict.PASS_WITH_WARNINGS),
        ([FindingSeverity.CRITICAL], ReviewVerdict.NEEDS_REVIEW),
        ([FindingSeverity.CRITICAL] * 3, ReviewVerdict.RECOMMEND_REJECT),
        (
            [FindingSeverity.CRITICAL, FindingSeverity.WARNING, FindingSeverity.SUGGESTION],
            ReviewVerdict.NEEDS_REVIEW,
        ),
    ])
    def test_verdict(self, severities, expected):
        findings = [_make_finding(severity=s) for s in severities]
        assert compute_verdict(findings) == expected


class TestComputeCategoryResults:
    """Test per-category result computation."""

    def test_all_pass_no_findings(self):
        results = compute_category_results([])
        for cat in ReviewCategory:
            assert results[cat.value] == CategoryResult.PASS

    @pytest.mark.parametrize("category,severity,expected_result", [
        (ReviewCategory.SECURITY, FindingSeverity.CRITICAL, CategoryResult.CRITICAL),
        (ReviewCategory.STYLE, FindingSeverity.WARNING, CategoryResult.WARNING),
        (ReviewCategory.COMPLETENESS, FindingSeverity.SUGGESTION, CategoryResult.SUGGESTION),
    ])
    def test_category_result(self, category, severity, expected_result):
        findings = [_make_finding(category=category, severity=severity)]
        results = compute_category_results(findings)
        assert results[category.value] == expected_result

    def test_unaffected_categories_still_pass(self):
        findings = [_make_finding(category=ReviewCategory.SECURITY, severity=FindingSeverity.CRITICAL)]
        results = compute_category_results(findings)
        assert results["correctness"] == CategoryResult.PASS


class TestComputeConfidence:
    """Test confidence score computation."""

    @pytest.mark.parametrize("strategy,expected_base", [
        (ReviewStrategy.FULL_REASONING, 0.95),
        (ReviewStrategy.RALPH_INTERMEDIATE, 0.70),
    ])
    def test_base_confidence(self, strategy, expected_base):
        assert compute_confidence([], strategy) == expected_base

    def test_critical_reduces_confidence(self):
        findings = [_make_finding(severity=FindingSeverity.CRITICAL)]
        assert compute_confidence(findings, ReviewStrategy.FULL_REASONING) < 0.95

    def test_multiple_criticals_reduce_more(self):
        findings = [_make_finding(severity=FindingSeverity.CRITICAL) for _ in range(5)]
        assert compute_confidence(findings, ReviewStrategy.FULL_REASONING) < 0.50

    def test_confidence_never_below_zero(self):
        findings = [_make_finding(severity=FindingSeverity.CRITICAL) for _ in range(20)]
        assert compute_confidence(findings, ReviewStrategy.FULL_REASONING) == 0.0

    def test_confidence_between_0_and_1(self):
        for strategy in ReviewStrategy:
            conf = compute_confidence([], strategy)
            assert 0.0 <= conf <= 1.0


class TestBuildReviewSummary:
    """Test summary generation."""

    @pytest.mark.parametrize("severity,verdict,expected_substr", [
        (None, ReviewVerdict.PASS, "No issues"),
        (FindingSeverity.CRITICAL, ReviewVerdict.NEEDS_REVIEW, "critical"),
        (FindingSeverity.WARNING, ReviewVerdict.PASS_WITH_WARNINGS, "warning"),
    ])
    def test_summary_content(self, severity, verdict, expected_substr):
        findings = [_make_finding(severity=severity)] if severity else []
        summary = build_review_summary(findings, verdict)
        assert expected_substr.lower() in summary.lower()


# =========================================================================
# #48 -- CLI Output Tests
# =========================================================================


class TestFormatReviewCli:
    """Test CLI formatting of review results."""

    def test_format_pass_verdict(self):
        result = _make_review_result(category_results=_ALL_PASS_CATEGORIES)
        output = format_review_cli(result)
        assert "PASS" in output
        assert "Verdict" in output
        assert "Correctness" in output
        assert "Security" in output

    def test_format_with_findings(self):
        result = _make_review_result(
            verdict=ReviewVerdict.PASS_WITH_WARNINGS,
            confidence=0.85,
            findings=[_make_finding(
                category=ReviewCategory.STYLE, severity=FindingSeverity.WARNING,
                description="Mixed async patterns",
                recommendation="Standardize on async/await",
            )],
            category_results={**_ALL_PASS_CATEGORIES, "style": CategoryResult.WARNING},
        )
        output = format_review_cli(result)
        assert "PASS WITH WARNINGS" in output
        assert "Mixed async patterns" in output
        assert "Standardize on async/await" in output
        assert "1 warning" in output

    def test_format_shows_confidence(self):
        output = format_review_cli(_make_review_result(confidence=0.95))
        assert "95%" in output

    def test_format_critical_findings(self):
        result = _make_review_result(
            verdict=ReviewVerdict.NEEDS_REVIEW, confidence=0.60,
            findings=[_make_finding(severity=FindingSeverity.CRITICAL)],
            category_results={**_ALL_PASS_CATEGORIES, "correctness": CategoryResult.CRITICAL},
        )
        output = format_review_cli(result)
        assert "NEEDS REVIEW" in output
        assert "1 critical" in output

    def test_format_all_five_categories_displayed(self):
        result = _make_review_result(category_results=_ALL_PASS_CATEGORIES)
        output = format_review_cli(result)
        for name in ("Correctness", "Security", "Architecture", "Style", "Complete"):
            assert name in output


class TestRenderReviewPanel:
    """Test rich Panel rendering."""

    def test_panel_created_with_title(self):
        from rich.panel import Panel

        result = _make_review_result()
        panel = render_review_panel(result, title="test-app")
        assert isinstance(panel, Panel)

        panel2 = render_review_panel(result, title="my-project")
        assert "my-project" in str(panel2.title)


# =========================================================================
# #49 -- Ralph Integration Tests
# =========================================================================


class TestIntermediateReview:
    """Test Ralph intermediate review per iteration."""

    def test_clean_iteration_passes(self):
        result = run_intermediate_review(
            diff_text=CLEAN_DIFF,
            validation_results=[{"command": "pytest", "passed": True}],
            run_id="run_001", iteration=1,
        )
        assert result.overall_verdict == ReviewVerdict.PASS
        assert result.review_strategy == ReviewStrategy.RALPH_INTERMEDIATE
        assert result.model_tier == ModelTier.FAST.value
        assert result.cost >= 0.0
        assert result.duration_seconds >= 0.0

    def test_failed_validation_produces_warning(self):
        result = run_intermediate_review(
            diff_text=CLEAN_DIFF,
            validation_results=[{"command": "pytest", "passed": False, "error": "tests failed"}],
            run_id="run_001", iteration=2,
        )
        assert len(result.findings) > 0
        assert result.findings[0].severity == FindingSeverity.WARNING
        assert result.findings[0].category == ReviewCategory.CORRECTNESS

    def test_security_pattern_in_diff(self):
        result = run_intermediate_review(
            diff_text=SECRET_DIFF, validation_results=[],
            run_id="run_001", iteration=1,
        )
        security = [f for f in result.findings if f.category == ReviewCategory.SECURITY]
        assert len(security) > 0


class TestShouldPauseRalph:
    """Test Ralph pause logic based on review results."""

    def _ralph_result(self, verdict, confidence, findings):
        return _make_review_result(
            verdict=verdict, confidence=confidence, findings=findings,
            strategy=ReviewStrategy.RALPH_INTERMEDIATE, model_tier="fast",
        )

    @pytest.mark.parametrize("verdict,confidence,findings,expected", [
        (ReviewVerdict.PASS, 0.70, [], False),
        (ReviewVerdict.PASS, 0.70, [_make_finding(severity=FindingSeverity.SUGGESTION)] * 10, False),
    ])
    def test_no_pause(self, verdict, confidence, findings, expected):
        assert should_pause_ralph(self._ralph_result(verdict, confidence, findings)) is expected

    def test_critical_finding_pauses(self):
        result = self._ralph_result(
            ReviewVerdict.NEEDS_REVIEW, 0.50,
            [_make_finding(severity=FindingSeverity.CRITICAL)],
        )
        assert should_pause_ralph(result) is True

    def test_three_warnings_pauses(self):
        result = self._ralph_result(
            ReviewVerdict.PASS_WITH_WARNINGS, 0.60,
            [_make_finding(severity=FindingSeverity.WARNING) for _ in range(3)],
        )
        assert should_pause_ralph(result) is True

    def test_two_warnings_no_pause(self):
        result = self._ralph_result(
            ReviewVerdict.PASS_WITH_WARNINGS, 0.65,
            [_make_finding(severity=FindingSeverity.WARNING) for _ in range(2)],
        )
        assert should_pause_ralph(result) is False


class TestFinalReview:
    """Test Ralph final review of complete output."""

    def test_clean_output_passes(self):
        result = run_final_review(
            diff_text=CLEAN_DIFF,
            files_changed=["src/app.py", "tests/test_app.py"],
            validation_results=[{"command": "pytest", "passed": True}],
            run_id="run_001",
        )
        assert result.overall_verdict in (ReviewVerdict.PASS, ReviewVerdict.PASS_WITH_WARNINGS)
        assert result.review_strategy == ReviewStrategy.RALPH_FINAL
        assert result.model_tier == ModelTier.REASONING.value

    def test_failed_validation_is_critical(self):
        result = run_final_review(
            diff_text=CLEAN_DIFF, files_changed=["src/app.py"],
            validation_results=[{"command": "pytest", "passed": False, "error": "3 tests failed"}],
            run_id="run_001",
        )
        critical = [f for f in result.findings if f.severity == FindingSeverity.CRITICAL]
        assert len(critical) > 0

    def test_missing_tests_flagged(self):
        result = run_final_review(
            diff_text=CLEAN_DIFF, files_changed=["src/new_module.py"],
            validation_results=[], run_id="run_001",
        )
        completeness = [f for f in result.findings if f.category == ReviewCategory.COMPLETENESS]
        assert len(completeness) > 0

    def test_security_issues_in_diff(self):
        result = run_final_review(
            diff_text=SECRET_DIFF, files_changed=["src/config.py"],
            validation_results=[], run_id="run_001",
        )
        security = [f for f in result.findings if f.category == ReviewCategory.SECURITY]
        assert len(security) > 0


class TestCodeReviewWorkerRalphStrategies:
    """Test that CodeReviewWorker correctly routes to Ralph review modes."""

    @pytest.mark.parametrize("strategy,kwargs", [
        (ReviewStrategy.RALPH_INTERMEDIATE, {"input_payload": {"iteration": 3}}),
        (ReviewStrategy.RALPH_FINAL, {}),
    ])
    def test_worker_ralph_strategy(self, strategy, kwargs):
        worker = CodeReviewWorker(
            diff_text=CLEAN_DIFF, run_id="run_001",
            review_strategy=strategy,
            files_changed=["src/app.py"] if strategy == ReviewStrategy.RALPH_FINAL else None,
        )
        worker.execute(_make_task(**kwargs), _RO_RUNTIME)
        assert worker.review_result is not None
        assert worker.review_result.review_strategy == strategy


# =========================================================================
# Manifest Fields Tests
# =========================================================================


class TestBuildReviewManifestFields:
    """Test manifest field extraction from review results."""

    def test_all_fields_present(self):
        result = _make_review_result(
            verdict=ReviewVerdict.PASS_WITH_WARNINGS, confidence=0.85,
            findings=[
                _make_finding(severity=FindingSeverity.WARNING),
                _make_finding(severity=FindingSeverity.SUGGESTION),
            ],
            category_results={**_ALL_PASS_CATEGORIES, "style": CategoryResult.WARNING},
            duration_seconds=2.5, cost=0.25,
        )
        fields = build_review_manifest_fields(result)

        assert fields["review_id"] == "rev_001"
        assert fields["review_model"] == "reasoning"
        assert fields["review_strategy"] == "full_reasoning"
        assert fields["review_cost"] == 0.25
        assert fields["review_duration"] == 2.5
        assert fields["overall_verdict"] == "pass_with_warnings"
        assert fields["confidence_score"] == 0.85
        assert fields["finding_count_by_severity"]["warning"] == 1
        assert fields["finding_count_by_severity"]["suggestion"] == 1
        assert fields["finding_count_by_severity"]["critical"] == 0
        assert fields["category_results"]["style"] == CategoryResult.WARNING


# =========================================================================
# Finding Model Tests
# =========================================================================


class TestFindingModel:
    """Test the Finding Pydantic model."""

    def test_finding_required_fields(self):
        f = Finding(
            category=ReviewCategory.CORRECTNESS, severity=FindingSeverity.CRITICAL,
            file="src/app.py", description="Null check missing", recommendation="Add null guard",
        )
        assert f.category == ReviewCategory.CORRECTNESS
        assert f.severity == FindingSeverity.CRITICAL
        assert f.file == "src/app.py"
        assert f.line is None

    def test_finding_with_line(self):
        f = Finding(
            category=ReviewCategory.SECURITY, severity=FindingSeverity.WARNING,
            file="src/api.py", line=47,
            description="SQL injection risk", recommendation="Use parameterized queries",
        )
        assert f.line == 47


class TestReviewResultModel:
    """Test the ReviewResult Pydantic model."""

    def test_verdict_values(self):
        for v in ReviewVerdict:
            assert v.value in ("pass", "pass_with_warnings", "needs_review", "recommend_reject")

    def test_confidence_bounds(self):
        result = _make_review_result(confidence=0.5)
        assert 0.0 <= result.confidence <= 1.0

    @pytest.mark.parametrize("invalid_confidence", [-0.1, 1.1])
    def test_confidence_out_of_bounds_rejected(self, invalid_confidence):
        with pytest.raises(Exception):
            _make_review_result(confidence=invalid_confidence)
