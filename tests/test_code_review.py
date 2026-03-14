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
    get_review_passes,
    get_tier_for_category,
    render_review_panel,
    run_final_review,
    run_intermediate_review,
    select_review_strategy,
    should_pause_ralph,
)
from foxhound.harness.worker_protocol import (
    Capability,
    SanitizedOutput,
    WorkerClass,
    WorkerOutput,
    validate_worker_capabilities,
)

# =========================================================================
# Test Fixtures
# =========================================================================


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
        category=category,
        severity=severity,
        file=file,
        line=line,
        description=description,
        recommendation=recommendation,
    )


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
# #46 — CodeReviewWorker Tests
# =========================================================================


class TestCodeReviewWorkerDefinition:
    """Test worker identity and capability constraints."""

    def test_worker_name(self):
        worker = CodeReviewWorker()
        assert worker.worker_name == "code_review_worker"

    def test_worker_class_is_helper(self):
        worker = CodeReviewWorker()
        assert worker.worker_class == WorkerClass.HELPER

    def test_capabilities_repo_read_only(self):
        worker = CodeReviewWorker()
        assert worker.capabilities == {Capability.REPO_READ}

    def test_cannot_write_to_repo(self):
        worker = CodeReviewWorker()
        assert Capability.REPO_WRITE not in worker.capabilities

    def test_cannot_access_network(self):
        worker = CodeReviewWorker()
        assert Capability.NETWORK not in worker.capabilities

    def test_cannot_execute_shell(self):
        worker = CodeReviewWorker()
        assert Capability.SHELL not in worker.capabilities

    def test_cannot_spawn_children(self):
        worker = CodeReviewWorker()
        assert Capability.SPAWN not in worker.capabilities
        assert worker.allowed_spawn_targets == []

    def test_default_timeout_120(self):
        worker = CodeReviewWorker()
        assert worker.default_timeout_seconds == 120

    def test_default_budget_050(self):
        worker = CodeReviewWorker()
        assert worker.default_budget == 0.50

    def test_capabilities_matrix_allows_repo_read_only(self):
        violations = validate_worker_capabilities(
            "code_review_worker", {Capability.REPO_READ}
        )
        assert violations == []

    def test_capabilities_matrix_blocks_repo_write(self):
        violations = validate_worker_capabilities(
            "code_review_worker", {Capability.REPO_READ, Capability.REPO_WRITE}
        )
        assert len(violations) == 1
        assert "repo_write" in violations[0]

    def test_capabilities_matrix_blocks_network(self):
        violations = validate_worker_capabilities(
            "code_review_worker", {Capability.REPO_READ, Capability.NETWORK}
        )
        assert len(violations) == 1

    def test_capabilities_matrix_blocks_shell(self):
        violations = validate_worker_capabilities(
            "code_review_worker", {Capability.REPO_READ, Capability.SHELL}
        )
        assert len(violations) == 1

    def test_capabilities_matrix_blocks_spawn(self):
        violations = validate_worker_capabilities(
            "code_review_worker", {Capability.REPO_READ, Capability.SPAWN}
        )
        assert len(violations) == 1


class TestCodeReviewWorkerHarness:
    """Test the six-method harness contract."""

    def test_validate_input_valid(self):
        worker = CodeReviewWorker(diff_text=CLEAN_DIFF, run_id="run_001")
        task = _make_task()
        result = worker.validate_input(task)
        assert result.valid is True
        assert result.errors == []

    def test_validate_input_missing_job_id(self):
        worker = CodeReviewWorker(diff_text=CLEAN_DIFF)
        task = _make_task(job_id="")
        result = worker.validate_input(task)
        assert result.valid is False
        assert any("job_id" in e for e in result.errors)

    def test_validate_input_no_diff_or_files(self):
        worker = CodeReviewWorker()
        task = _make_task()
        result = worker.validate_input(task)
        assert result.valid is False
        assert any("diff" in e.lower() or "files" in e.lower() for e in result.errors)

    def test_validate_input_with_files_no_diff(self):
        worker = CodeReviewWorker(files_changed=["src/app.py"])
        task = _make_task()
        result = worker.validate_input(task)
        assert result.valid is True

    def test_build_context(self):
        worker = CodeReviewWorker(
            diff_text=CLEAN_DIFF,
            files_changed=["src/app.py"],
            validation_results=[{"command": "pytest", "passed": True}],
        )
        task = _make_task()
        ctx = worker.build_context(task)
        assert "diff_text" in ctx.context_pack
        assert ctx.trust_labels["diff_text"] == TrustLevel.SEMI_TRUSTED.value
        assert ctx.trust_labels["review_strategy"] == TrustLevel.TRUSTED.value
        assert "src/app.py" in ctx.files_included

    def test_execute_produces_review_result(self):
        worker = CodeReviewWorker(diff_text=CLEAN_DIFF, run_id="run_001")
        task = _make_task()
        from foxhound.harness.worker_protocol import RuntimeHandle

        runtime = RuntimeHandle(
            execution_mode=ExecutionMode.READ_ONLY,
            capabilities={Capability.REPO_READ},
            budget_remaining=1.0,
            timeout_remaining=120.0,
        )
        output = worker.execute(task, runtime)
        assert "review_id" in output.payload
        assert "overall_verdict" in output.payload
        assert "finding_count" in output.payload
        assert output.commands_run == []
        assert output.files_changed == []

    def test_execute_clean_diff_passes(self):
        worker = CodeReviewWorker(diff_text=CLEAN_DIFF, run_id="run_001")
        task = _make_task()
        from foxhound.harness.worker_protocol import RuntimeHandle

        runtime = RuntimeHandle(
            execution_mode=ExecutionMode.READ_ONLY,
            capabilities={Capability.REPO_READ},
            budget_remaining=1.0,
            timeout_remaining=120.0,
        )
        worker.execute(task, runtime)
        assert worker.review_result is not None
        assert worker.review_result.overall_verdict == ReviewVerdict.PASS

    def test_execute_secret_diff_finds_issues(self):
        worker = CodeReviewWorker(diff_text=SECRET_DIFF, run_id="run_001")
        task = _make_task()
        from foxhound.harness.worker_protocol import RuntimeHandle

        runtime = RuntimeHandle(
            execution_mode=ExecutionMode.READ_ONLY,
            capabilities={Capability.REPO_READ},
            budget_remaining=1.0,
            timeout_remaining=120.0,
        )
        worker.execute(task, runtime)
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
            commands_run=[],
            files_changed=[],
            cost=0.0,
            artifact_paths=[],
        )
        sanitized = worker.sanitize_output(output)
        assert sanitized.payload["test"] == "value"

    def test_evaluate_output_after_review(self):
        worker = CodeReviewWorker(diff_text=CLEAN_DIFF, run_id="run_001")
        task = _make_task()
        from foxhound.harness.worker_protocol import RuntimeHandle

        runtime = RuntimeHandle(
            execution_mode=ExecutionMode.READ_ONLY,
            capabilities={Capability.REPO_READ},
            budget_remaining=1.0,
            timeout_remaining=120.0,
        )
        output = worker.execute(task, runtime)
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
        task = _make_task()
        from foxhound.harness.worker_protocol import RuntimeHandle

        runtime = RuntimeHandle(
            execution_mode=ExecutionMode.READ_ONLY,
            capabilities={Capability.REPO_READ},
            budget_remaining=1.0,
            timeout_remaining=120.0,
        )
        output = worker.execute(task, runtime)
        sanitized = worker.sanitize_output(output)
        eval_result = worker.evaluate_output(sanitized)
        result = worker.finalize(eval_result)
        assert result.status == ResultStatus.SUCCESS
        assert "review_id" in result.payload
        assert "overall_verdict" in result.payload

    def test_full_harness_lifecycle(self):
        """End-to-end: validate -> build -> execute -> sanitize -> evaluate -> finalize."""
        worker = CodeReviewWorker(
            diff_text=CLEAN_DIFF,
            files_changed=["src/app.py"],
            run_id="run_001",
        )
        task = _make_task()
        from foxhound.harness.worker_protocol import RuntimeHandle

        # 1. validate
        val = worker.validate_input(task)
        assert val.valid

        # 2. build context
        ctx = worker.build_context(task)
        assert ctx.context_pack

        # 3. execute
        runtime = RuntimeHandle(
            execution_mode=ExecutionMode.READ_ONLY,
            capabilities={Capability.REPO_READ},
            budget_remaining=1.0,
            timeout_remaining=120.0,
        )
        output = worker.execute(task, runtime)
        assert output.payload

        # 4. sanitize
        sanitized = worker.sanitize_output(output)
        assert sanitized.payload

        # 5. evaluate
        eval_result = worker.evaluate_output(sanitized)
        assert eval_result.passed

        # 6. finalize
        result = worker.finalize(eval_result)
        assert result.status == ResultStatus.SUCCESS


# =========================================================================
# #47 — Review Model Routing Tests
# =========================================================================


class TestReviewStrategy:
    """Test review strategy selection and tier routing."""

    def test_default_strategy_is_full_reasoning(self):
        strategy = select_review_strategy()
        assert strategy == ReviewStrategy.FULL_REASONING

    def test_ralph_intermediate_strategy(self):
        strategy = select_review_strategy(is_ralph_intermediate=True)
        assert strategy == ReviewStrategy.RALPH_INTERMEDIATE

    def test_ralph_final_strategy(self):
        strategy = select_review_strategy(is_ralph_final=True)
        assert strategy == ReviewStrategy.RALPH_FINAL

    def test_budget_constrained_strategy(self):
        strategy = select_review_strategy(budget_constrained=True)
        assert strategy == ReviewStrategy.BUDGET_BALANCED

    def test_cost_optimized_strategy(self):
        strategy = select_review_strategy(cost_optimized=True)
        assert strategy == ReviewStrategy.COST_OPTIMIZED

    def test_ralph_intermediate_overrides_budget(self):
        strategy = select_review_strategy(
            is_ralph_intermediate=True, budget_constrained=True
        )
        assert strategy == ReviewStrategy.RALPH_INTERMEDIATE


class TestTierRouting:
    """Test tier assignment per strategy and category."""

    def test_full_reasoning_uses_reasoning_for_all(self):
        for cat in ReviewCategory:
            tier = get_tier_for_category(ReviewStrategy.FULL_REASONING, cat)
            assert tier == ModelTier.REASONING

    def test_budget_balanced_uses_balanced_for_all(self):
        for cat in ReviewCategory:
            tier = get_tier_for_category(ReviewStrategy.BUDGET_BALANCED, cat)
            assert tier == ModelTier.BALANCED

    def test_ralph_intermediate_uses_fast_for_all(self):
        for cat in ReviewCategory:
            tier = get_tier_for_category(ReviewStrategy.RALPH_INTERMEDIATE, cat)
            assert tier == ModelTier.FAST

    def test_ralph_final_uses_reasoning_for_all(self):
        for cat in ReviewCategory:
            tier = get_tier_for_category(ReviewStrategy.RALPH_FINAL, cat)
            assert tier == ModelTier.REASONING

    def test_cost_optimized_correctness_reasoning(self):
        tier = get_tier_for_category(
            ReviewStrategy.COST_OPTIMIZED, ReviewCategory.CORRECTNESS
        )
        assert tier == ModelTier.REASONING

    def test_cost_optimized_security_reasoning(self):
        tier = get_tier_for_category(
            ReviewStrategy.COST_OPTIMIZED, ReviewCategory.SECURITY
        )
        assert tier == ModelTier.REASONING

    def test_cost_optimized_architecture_balanced(self):
        tier = get_tier_for_category(
            ReviewStrategy.COST_OPTIMIZED, ReviewCategory.ARCHITECTURE
        )
        assert tier == ModelTier.BALANCED

    def test_cost_optimized_style_fast(self):
        tier = get_tier_for_category(
            ReviewStrategy.COST_OPTIMIZED, ReviewCategory.STYLE
        )
        assert tier == ModelTier.FAST

    def test_cost_optimized_completeness_fast(self):
        tier = get_tier_for_category(
            ReviewStrategy.COST_OPTIMIZED, ReviewCategory.COMPLETENESS
        )
        assert tier == ModelTier.FAST

    def test_no_model_names_in_strategy_map(self):
        """Ensure no hardcoded model names — only tiers."""
        from foxhound.execution.review import _STRATEGY_TIER_MAP

        for strategy, tier_map in _STRATEGY_TIER_MAP.items():
            for category, tier in tier_map.items():
                assert isinstance(tier, ModelTier), (
                    f"Strategy {strategy} category {category} has non-tier value: {tier}"
                )


class TestPrimaryTier:
    """Test primary tier extraction for manifest recording."""

    def test_full_reasoning_primary_is_reasoning(self):
        assert get_primary_tier(ReviewStrategy.FULL_REASONING) == ModelTier.REASONING

    def test_budget_balanced_primary_is_balanced(self):
        assert get_primary_tier(ReviewStrategy.BUDGET_BALANCED) == ModelTier.BALANCED

    def test_ralph_intermediate_primary_is_fast(self):
        assert get_primary_tier(ReviewStrategy.RALPH_INTERMEDIATE) == ModelTier.FAST

    def test_cost_optimized_primary_is_reasoning(self):
        assert get_primary_tier(ReviewStrategy.COST_OPTIMIZED) == ModelTier.REASONING


class TestReviewPasses:
    """Test multi-pass review configuration."""

    def test_full_reasoning_single_pass(self):
        passes = get_review_passes(ReviewStrategy.FULL_REASONING)
        assert len(passes) == 1
        tier, categories = passes[0]
        assert tier == ModelTier.REASONING
        assert len(categories) == 5

    def test_cost_optimized_three_passes(self):
        passes = get_review_passes(ReviewStrategy.COST_OPTIMIZED)
        assert len(passes) == 3
        # Fast pass
        assert passes[0][0] == ModelTier.FAST
        assert ReviewCategory.STYLE in passes[0][1]
        assert ReviewCategory.COMPLETENESS in passes[0][1]
        # Balanced pass
        assert passes[1][0] == ModelTier.BALANCED
        assert ReviewCategory.ARCHITECTURE in passes[1][1]
        # Reasoning pass
        assert passes[2][0] == ModelTier.REASONING
        assert ReviewCategory.CORRECTNESS in passes[2][1]
        assert ReviewCategory.SECURITY in passes[2][1]

    def test_budget_balanced_single_pass(self):
        passes = get_review_passes(ReviewStrategy.BUDGET_BALANCED)
        assert len(passes) == 1
        assert passes[0][0] == ModelTier.BALANCED


class TestReviewStrategyInManifest:
    """Test that review strategy is recorded correctly in manifest."""

    def test_strategy_recorded(self):
        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="reasoning",
            review_strategy=ReviewStrategy.FULL_REASONING,
            overall_verdict=ReviewVerdict.PASS,
            confidence=0.95,
            category_results={},
        )
        manifest = build_review_manifest_fields(result)
        assert manifest["review_strategy"] == "full_reasoning"

    def test_cost_optimized_recorded(self):
        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="reasoning",
            review_strategy=ReviewStrategy.COST_OPTIMIZED,
            overall_verdict=ReviewVerdict.PASS,
            confidence=0.90,
            category_results={},
        )
        manifest = build_review_manifest_fields(result)
        assert manifest["review_strategy"] == "cost_optimized"


# =========================================================================
# #46 — Review Evaluation Logic Tests
# =========================================================================


class TestComputeVerdict:
    """Test verdict computation from findings."""

    def test_no_findings_is_pass(self):
        assert compute_verdict([]) == ReviewVerdict.PASS

    def test_suggestions_only_is_pass(self):
        findings = [_make_finding(severity=FindingSeverity.SUGGESTION)]
        assert compute_verdict(findings) == ReviewVerdict.PASS

    def test_warnings_is_pass_with_warnings(self):
        findings = [_make_finding(severity=FindingSeverity.WARNING)]
        assert compute_verdict(findings) == ReviewVerdict.PASS_WITH_WARNINGS

    def test_one_critical_is_needs_review(self):
        findings = [_make_finding(severity=FindingSeverity.CRITICAL)]
        assert compute_verdict(findings) == ReviewVerdict.NEEDS_REVIEW

    def test_three_critical_is_recommend_reject(self):
        findings = [
            _make_finding(severity=FindingSeverity.CRITICAL)
            for _ in range(3)
        ]
        assert compute_verdict(findings) == ReviewVerdict.RECOMMEND_REJECT

    def test_mixed_severities(self):
        findings = [
            _make_finding(severity=FindingSeverity.CRITICAL),
            _make_finding(severity=FindingSeverity.WARNING),
            _make_finding(severity=FindingSeverity.SUGGESTION),
        ]
        assert compute_verdict(findings) == ReviewVerdict.NEEDS_REVIEW


class TestComputeCategoryResults:
    """Test per-category result computation."""

    def test_all_pass_no_findings(self):
        results = compute_category_results([])
        for cat in ReviewCategory:
            assert results[cat.value] == CategoryResult.PASS

    def test_critical_finding_in_category(self):
        findings = [
            _make_finding(
                category=ReviewCategory.SECURITY,
                severity=FindingSeverity.CRITICAL,
            )
        ]
        results = compute_category_results(findings)
        assert results["security"] == CategoryResult.CRITICAL
        assert results["correctness"] == CategoryResult.PASS

    def test_warning_finding_in_category(self):
        findings = [
            _make_finding(
                category=ReviewCategory.STYLE,
                severity=FindingSeverity.WARNING,
            )
        ]
        results = compute_category_results(findings)
        assert results["style"] == CategoryResult.WARNING

    def test_suggestion_finding_in_category(self):
        findings = [
            _make_finding(
                category=ReviewCategory.COMPLETENESS,
                severity=FindingSeverity.SUGGESTION,
            )
        ]
        results = compute_category_results(findings)
        assert results["completeness"] == CategoryResult.SUGGESTION


class TestComputeConfidence:
    """Test confidence score computation."""

    def test_full_reasoning_base_confidence(self):
        conf = compute_confidence([], ReviewStrategy.FULL_REASONING)
        assert conf == 0.95

    def test_ralph_intermediate_lower_base(self):
        conf = compute_confidence([], ReviewStrategy.RALPH_INTERMEDIATE)
        assert conf == 0.70

    def test_critical_reduces_confidence(self):
        findings = [_make_finding(severity=FindingSeverity.CRITICAL)]
        conf = compute_confidence(findings, ReviewStrategy.FULL_REASONING)
        assert conf < 0.95

    def test_multiple_criticals_reduce_more(self):
        findings = [
            _make_finding(severity=FindingSeverity.CRITICAL)
            for _ in range(5)
        ]
        conf = compute_confidence(findings, ReviewStrategy.FULL_REASONING)
        assert conf < 0.50

    def test_confidence_never_below_zero(self):
        findings = [
            _make_finding(severity=FindingSeverity.CRITICAL)
            for _ in range(20)
        ]
        conf = compute_confidence(findings, ReviewStrategy.FULL_REASONING)
        assert conf == 0.0

    def test_confidence_between_0_and_1(self):
        for strategy in ReviewStrategy:
            conf = compute_confidence([], strategy)
            assert 0.0 <= conf <= 1.0


class TestBuildReviewSummary:
    """Test summary generation."""

    def test_no_findings_summary(self):
        summary = build_review_summary([], ReviewVerdict.PASS)
        assert "No issues" in summary

    def test_critical_summary(self):
        findings = [_make_finding(severity=FindingSeverity.CRITICAL)]
        summary = build_review_summary(findings, ReviewVerdict.NEEDS_REVIEW)
        assert "critical" in summary.lower()

    def test_warnings_summary(self):
        findings = [_make_finding(severity=FindingSeverity.WARNING)]
        summary = build_review_summary(findings, ReviewVerdict.PASS_WITH_WARNINGS)
        assert "warning" in summary.lower()


# =========================================================================
# #48 — CLI Output Tests
# =========================================================================


class TestFormatReviewCli:
    """Test CLI formatting of review results."""

    def test_format_pass_verdict(self):
        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="reasoning",
            review_strategy=ReviewStrategy.FULL_REASONING,
            overall_verdict=ReviewVerdict.PASS,
            confidence=0.95,
            findings=[],
            category_results={
                "correctness": CategoryResult.PASS,
                "security": CategoryResult.PASS,
                "architecture": CategoryResult.PASS,
                "style": CategoryResult.PASS,
                "completeness": CategoryResult.PASS,
            },
        )
        output = format_review_cli(result)
        assert "PASS" in output
        assert "Verdict" in output
        assert "Correctness" in output
        assert "Security" in output

    def test_format_with_findings(self):
        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="reasoning",
            review_strategy=ReviewStrategy.FULL_REASONING,
            overall_verdict=ReviewVerdict.PASS_WITH_WARNINGS,
            confidence=0.85,
            findings=[
                _make_finding(
                    category=ReviewCategory.STYLE,
                    severity=FindingSeverity.WARNING,
                    description="Mixed async patterns",
                    recommendation="Standardize on async/await",
                ),
            ],
            category_results={
                "correctness": CategoryResult.PASS,
                "security": CategoryResult.PASS,
                "architecture": CategoryResult.PASS,
                "style": CategoryResult.WARNING,
                "completeness": CategoryResult.PASS,
            },
        )
        output = format_review_cli(result)
        assert "PASS WITH WARNINGS" in output
        assert "Mixed async patterns" in output
        assert "Standardize on async/await" in output
        assert "1 warning" in output

    def test_format_shows_confidence(self):
        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="reasoning",
            review_strategy=ReviewStrategy.FULL_REASONING,
            overall_verdict=ReviewVerdict.PASS,
            confidence=0.95,
            findings=[],
            category_results={},
        )
        output = format_review_cli(result)
        assert "95%" in output

    def test_format_critical_findings(self):
        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="reasoning",
            review_strategy=ReviewStrategy.FULL_REASONING,
            overall_verdict=ReviewVerdict.NEEDS_REVIEW,
            confidence=0.60,
            findings=[
                _make_finding(severity=FindingSeverity.CRITICAL),
            ],
            category_results={
                "correctness": CategoryResult.CRITICAL,
                "security": CategoryResult.PASS,
                "architecture": CategoryResult.PASS,
                "style": CategoryResult.PASS,
                "completeness": CategoryResult.PASS,
            },
        )
        output = format_review_cli(result)
        assert "NEEDS REVIEW" in output
        assert "1 critical" in output

    def test_format_all_five_categories_displayed(self):
        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="reasoning",
            review_strategy=ReviewStrategy.FULL_REASONING,
            overall_verdict=ReviewVerdict.PASS,
            confidence=0.95,
            findings=[],
            category_results={
                "correctness": CategoryResult.PASS,
                "security": CategoryResult.PASS,
                "architecture": CategoryResult.PASS,
                "style": CategoryResult.PASS,
                "completeness": CategoryResult.PASS,
            },
        )
        output = format_review_cli(result)
        assert "Correctness" in output
        assert "Security" in output
        assert "Architecture" in output
        assert "Style" in output
        assert "Complete" in output


class TestRenderReviewPanel:
    """Test rich Panel rendering."""

    def test_panel_created(self):
        from rich.panel import Panel

        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="reasoning",
            review_strategy=ReviewStrategy.FULL_REASONING,
            overall_verdict=ReviewVerdict.PASS,
            confidence=0.95,
            findings=[],
            category_results={},
        )
        panel = render_review_panel(result, title="test-app")
        assert isinstance(panel, Panel)

    def test_panel_with_custom_title(self):
        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="reasoning",
            review_strategy=ReviewStrategy.FULL_REASONING,
            overall_verdict=ReviewVerdict.PASS,
            confidence=0.95,
            findings=[],
            category_results={},
        )
        panel = render_review_panel(result, title="my-project")
        assert "my-project" in str(panel.title)


# =========================================================================
# #49 — Ralph Integration Tests
# =========================================================================


class TestIntermediateReview:
    """Test Ralph intermediate review per iteration."""

    def test_clean_iteration_passes(self):
        result = run_intermediate_review(
            diff_text=CLEAN_DIFF,
            validation_results=[{"command": "pytest", "passed": True}],
            run_id="run_001",
            iteration=1,
        )
        assert result.overall_verdict == ReviewVerdict.PASS
        assert result.review_strategy == ReviewStrategy.RALPH_INTERMEDIATE
        assert result.model_tier == ModelTier.FAST.value

    def test_failed_validation_produces_warning(self):
        result = run_intermediate_review(
            diff_text=CLEAN_DIFF,
            validation_results=[
                {"command": "pytest", "passed": False, "error": "tests failed"},
            ],
            run_id="run_001",
            iteration=2,
        )
        assert len(result.findings) > 0
        assert result.findings[0].severity == FindingSeverity.WARNING
        assert result.findings[0].category == ReviewCategory.CORRECTNESS

    def test_security_pattern_in_diff(self):
        result = run_intermediate_review(
            diff_text=SECRET_DIFF,
            validation_results=[],
            run_id="run_001",
            iteration=1,
        )
        security = [
            f for f in result.findings if f.category == ReviewCategory.SECURITY
        ]
        assert len(security) > 0

    def test_uses_fast_tier(self):
        result = run_intermediate_review(
            diff_text=CLEAN_DIFF,
            validation_results=[],
            run_id="run_001",
            iteration=1,
        )
        assert result.model_tier == ModelTier.FAST.value

    def test_ralph_intermediate_strategy(self):
        result = run_intermediate_review(
            diff_text=CLEAN_DIFF,
            validation_results=[],
            run_id="run_001",
            iteration=1,
        )
        assert result.review_strategy == ReviewStrategy.RALPH_INTERMEDIATE

    def test_intermediate_cost_tracked(self):
        result = run_intermediate_review(
            diff_text=CLEAN_DIFF,
            validation_results=[],
            run_id="run_001",
            iteration=1,
        )
        assert result.cost >= 0.0
        assert result.duration_seconds >= 0.0


class TestShouldPauseRalph:
    """Test Ralph pause logic based on review results."""

    def test_no_findings_no_pause(self):
        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="fast",
            review_strategy=ReviewStrategy.RALPH_INTERMEDIATE,
            overall_verdict=ReviewVerdict.PASS,
            confidence=0.70,
            findings=[],
            category_results={},
        )
        assert should_pause_ralph(result) is False

    def test_critical_finding_pauses(self):
        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="fast",
            review_strategy=ReviewStrategy.RALPH_INTERMEDIATE,
            overall_verdict=ReviewVerdict.NEEDS_REVIEW,
            confidence=0.50,
            findings=[_make_finding(severity=FindingSeverity.CRITICAL)],
            category_results={},
        )
        assert should_pause_ralph(result) is True

    def test_three_warnings_pauses(self):
        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="fast",
            review_strategy=ReviewStrategy.RALPH_INTERMEDIATE,
            overall_verdict=ReviewVerdict.PASS_WITH_WARNINGS,
            confidence=0.60,
            findings=[
                _make_finding(severity=FindingSeverity.WARNING)
                for _ in range(3)
            ],
            category_results={},
        )
        assert should_pause_ralph(result) is True

    def test_two_warnings_no_pause(self):
        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="fast",
            review_strategy=ReviewStrategy.RALPH_INTERMEDIATE,
            overall_verdict=ReviewVerdict.PASS_WITH_WARNINGS,
            confidence=0.65,
            findings=[
                _make_finding(severity=FindingSeverity.WARNING)
                for _ in range(2)
            ],
            category_results={},
        )
        assert should_pause_ralph(result) is False

    def test_suggestions_only_no_pause(self):
        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="fast",
            review_strategy=ReviewStrategy.RALPH_INTERMEDIATE,
            overall_verdict=ReviewVerdict.PASS,
            confidence=0.70,
            findings=[
                _make_finding(severity=FindingSeverity.SUGGESTION)
                for _ in range(10)
            ],
            category_results={},
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
        assert result.overall_verdict in (
            ReviewVerdict.PASS,
            ReviewVerdict.PASS_WITH_WARNINGS,
        )
        assert result.review_strategy == ReviewStrategy.RALPH_FINAL
        assert result.model_tier == ModelTier.REASONING.value

    def test_failed_validation_is_critical(self):
        result = run_final_review(
            diff_text=CLEAN_DIFF,
            files_changed=["src/app.py"],
            validation_results=[
                {"command": "pytest", "passed": False, "error": "3 tests failed"},
            ],
            run_id="run_001",
        )
        critical = [
            f for f in result.findings if f.severity == FindingSeverity.CRITICAL
        ]
        assert len(critical) > 0

    def test_uses_reasoning_tier(self):
        result = run_final_review(
            diff_text=CLEAN_DIFF,
            files_changed=[],
            validation_results=[],
            run_id="run_001",
        )
        assert result.model_tier == ModelTier.REASONING.value

    def test_missing_tests_flagged(self):
        result = run_final_review(
            diff_text=CLEAN_DIFF,
            files_changed=["src/new_module.py"],
            validation_results=[],
            run_id="run_001",
        )
        completeness = [
            f for f in result.findings
            if f.category == ReviewCategory.COMPLETENESS
        ]
        assert len(completeness) > 0

    def test_security_issues_in_diff(self):
        result = run_final_review(
            diff_text=SECRET_DIFF,
            files_changed=["src/config.py"],
            validation_results=[],
            run_id="run_001",
        )
        security = [
            f for f in result.findings if f.category == ReviewCategory.SECURITY
        ]
        assert len(security) > 0

    def test_ralph_final_strategy(self):
        result = run_final_review(
            diff_text=CLEAN_DIFF,
            files_changed=[],
            validation_results=[],
            run_id="run_001",
        )
        assert result.review_strategy == ReviewStrategy.RALPH_FINAL


class TestCodeReviewWorkerRalphStrategies:
    """Test that CodeReviewWorker correctly routes to Ralph review modes."""

    def test_worker_intermediate_strategy(self):
        worker = CodeReviewWorker(
            diff_text=CLEAN_DIFF,
            run_id="run_001",
            review_strategy=ReviewStrategy.RALPH_INTERMEDIATE,
        )
        task = _make_task(input_payload={"iteration": 3})
        from foxhound.harness.worker_protocol import RuntimeHandle

        runtime = RuntimeHandle(
            execution_mode=ExecutionMode.READ_ONLY,
            capabilities={Capability.REPO_READ},
            budget_remaining=1.0,
            timeout_remaining=120.0,
        )
        worker.execute(task, runtime)
        assert worker.review_result is not None
        assert worker.review_result.review_strategy == ReviewStrategy.RALPH_INTERMEDIATE

    def test_worker_final_strategy(self):
        worker = CodeReviewWorker(
            diff_text=CLEAN_DIFF,
            files_changed=["src/app.py"],
            run_id="run_001",
            review_strategy=ReviewStrategy.RALPH_FINAL,
        )
        task = _make_task()
        from foxhound.harness.worker_protocol import RuntimeHandle

        runtime = RuntimeHandle(
            execution_mode=ExecutionMode.READ_ONLY,
            capabilities={Capability.REPO_READ},
            budget_remaining=1.0,
            timeout_remaining=120.0,
        )
        worker.execute(task, runtime)
        assert worker.review_result is not None
        assert worker.review_result.review_strategy == ReviewStrategy.RALPH_FINAL


# =========================================================================
# Manifest Fields Tests
# =========================================================================


class TestBuildReviewManifestFields:
    """Test manifest field extraction from review results."""

    def test_all_fields_present(self):
        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="reasoning",
            review_strategy=ReviewStrategy.FULL_REASONING,
            duration_seconds=2.5,
            cost=0.25,
            overall_verdict=ReviewVerdict.PASS_WITH_WARNINGS,
            confidence=0.85,
            findings=[
                _make_finding(severity=FindingSeverity.WARNING),
                _make_finding(severity=FindingSeverity.SUGGESTION),
            ],
            category_results={
                "correctness": CategoryResult.PASS,
                "security": CategoryResult.PASS,
                "architecture": CategoryResult.PASS,
                "style": CategoryResult.WARNING,
                "completeness": CategoryResult.PASS,
            },
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
            category=ReviewCategory.CORRECTNESS,
            severity=FindingSeverity.CRITICAL,
            file="src/app.py",
            description="Null check missing",
            recommendation="Add null guard",
        )
        assert f.category == ReviewCategory.CORRECTNESS
        assert f.severity == FindingSeverity.CRITICAL
        assert f.file == "src/app.py"
        assert f.line is None

    def test_finding_with_line(self):
        f = Finding(
            category=ReviewCategory.SECURITY,
            severity=FindingSeverity.WARNING,
            file="src/api.py",
            line=47,
            description="SQL injection risk",
            recommendation="Use parameterized queries",
        )
        assert f.line == 47


class TestReviewResultModel:
    """Test the ReviewResult Pydantic model."""

    def test_verdict_values(self):
        for v in ReviewVerdict:
            assert v.value in ("pass", "pass_with_warnings", "needs_review", "recommend_reject")

    def test_confidence_bounds(self):
        result = ReviewResult(
            review_id="rev_001",
            run_id="run_001",
            model_tier="reasoning",
            review_strategy=ReviewStrategy.FULL_REASONING,
            overall_verdict=ReviewVerdict.PASS,
            confidence=0.5,
            category_results={},
        )
        assert 0.0 <= result.confidence <= 1.0

    def test_confidence_lower_bound(self):
        with pytest.raises(Exception):
            ReviewResult(
                review_id="rev_001",
                run_id="run_001",
                model_tier="reasoning",
                review_strategy=ReviewStrategy.FULL_REASONING,
                overall_verdict=ReviewVerdict.PASS,
                confidence=-0.1,
                category_results={},
            )

    def test_confidence_upper_bound(self):
        with pytest.raises(Exception):
            ReviewResult(
                review_id="rev_001",
                run_id="run_001",
                model_tier="reasoning",
                review_strategy=ReviewStrategy.FULL_REASONING,
                overall_verdict=ReviewVerdict.PASS,
                confidence=1.1,
                category_results={},
            )
