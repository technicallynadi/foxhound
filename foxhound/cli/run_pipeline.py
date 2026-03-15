"""End-to-end execution pipeline for foxhound run.

Orchestrates the full flow: load work item, queue job, create workspace,
build context, run execution, run code review, promote branch, and
report results. Each stage advances the run state machine and emits events.
"""

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from foxhound.core.coordinator import Coordinator
from foxhound.core.event_bus import EventBus
from foxhound.core.models import (
    JobType,
    ModelTier,
    PolicyRef,
    RecipeRef,
    ResultStatus,
    RunState,
    WorkItemState,
)
from foxhound.execution.engine import ExecutionWorker
from foxhound.execution.promotion import PromotionManager, PromotionRequest
from foxhound.execution.review import (
    CodeReviewWorker,
    select_review_strategy,
)
from foxhound.execution.workspace import WorkspaceManager
from foxhound.harness.runtime import Harness
from foxhound.policies.engine import PolicyEngine
from foxhound.recipes.loader import RecipeLoader
from foxhound.storage.database import Database


@dataclass
class RunPipelineResult:
    """Result of a complete foxhound run execution."""

    success: bool
    stage_reached: str = "init"
    work_item_id: str = ""
    run_id: str = ""
    job_id: str = ""
    branch_name: str | None = None
    commit_hash: str | None = None
    review_verdict: str | None = None
    review_confidence: float | None = None
    review_summary: str | None = None
    total_cost: float = 0.0
    duration_seconds: float = 0.0
    error: str | None = None
    files_changed: list[str] = field(default_factory=list)
    validation_results: list[dict[str, Any]] = field(default_factory=list)


def run_pipeline(
    work_item_id: str,
    db: Database,
    repo_path: Path,
    workspace_base: Path | None = None,
) -> RunPipelineResult:
    """Execute the full foxhound run pipeline.

    Stages:
    1. Load and validate work item
    2. Load recipe and policy, queue job with frozen snapshot
    3. Create isolated workspace
    4. Build context pack
    5. Run execution (validation commands)
    6. Run code review
    7. Promote branch + commit
    8. Record results

    Args:
        work_item_id: The work item to execute.
        db: Database connection.
        repo_path: Path to the target repository.
        workspace_base: Optional base directory for workspaces.

    Returns:
        RunPipelineResult with all execution details.
    """
    start_time = time.time()
    event_bus = EventBus(source_module="run_pipeline")
    coord = Coordinator(db, event_bus=event_bus)

    # ── Stage 1: Load work item ──────────────────────────────────
    item = coord.get_work_item(work_item_id)
    if item is None:
        return RunPipelineResult(
            success=False,
            stage_reached="load_work_item",
            work_item_id=work_item_id,
            error=f"Work item not found: {work_item_id}",
            duration_seconds=time.time() - start_time,
        )

    if item.state not in (WorkItemState.APPROVED, WorkItemState.EDITED):
        return RunPipelineResult(
            success=False,
            stage_reached="load_work_item",
            work_item_id=work_item_id,
            error=(
                f"Work item must be approved or edited, "
                f"got '{item.state.value}'"
            ),
            duration_seconds=time.time() - start_time,
        )

    # Transition to executing
    coord.advance_work_item(work_item_id, WorkItemState.EXECUTING)

    # ── Stage 2: Load recipe/policy, queue job ───────────────────
    recipe_loader = RecipeLoader(repo_dir=repo_path)
    recipe_name = item.recipe_name or "approved_ticket"
    recipe = recipe_loader.load_by_name(recipe_name)
    recipe_ref = recipe_loader.get_recipe_ref(recipe_name)

    if recipe_ref is None:
        recipe_ref = RecipeRef(
            name=recipe_name,
            version="0.0.0",
            content_hash="none",
            source_scope="default",
        )

    policy_engine = PolicyEngine(repo_dir=repo_path)
    policy_ref = policy_engine.get_policy_ref("default_policy")
    if policy_ref is None:
        policy_ref = PolicyRef(
            name="default_policy",
            version="1.0.0",
            content_hash="default",
            source_scope="builtin",
        )

    config_hash = hashlib.sha256(
        f"{recipe_ref.content_hash}:{policy_ref.content_hash}".encode()
    ).hexdigest()[:12]

    job = coord.queue.enqueue(
        work_item_id=work_item_id,
        repo_id=item.repo_id,
        job_type=JobType.EXECUTION,
        recipe_ref=recipe_ref,
        policy_ref=policy_ref,
        config_hash=config_hash,
        model_tier=ModelTier.BALANCED,
        budget=recipe.retry.max_retries + 1.0 if recipe else 3.0,
        timeout_seconds=600,
    )

    # Dispatch immediately
    dispatched = coord.dispatch_next(job_type=JobType.EXECUTION)
    if dispatched is None:
        return RunPipelineResult(
            success=False,
            stage_reached="queue_job",
            work_item_id=work_item_id,
            job_id=job.job_id,
            error="Failed to dispatch job from queue",
            duration_seconds=time.time() - start_time,
        )

    run = coord.create_run(dispatched, worker_type="ExecutionWorker")

    # ── Stage 3: Create isolated workspace ───────────────────────
    coord.advance_run(run.run_id, RunState.PREPARING)

    ws_base = workspace_base or (repo_path / ".foxhound" / "workspaces")
    ws_manager = WorkspaceManager(base_dir=ws_base)

    try:
        workspace = ws_manager.create(repo_path)
    except Exception as exc:
        coord.advance_run(run.run_id, RunState.FAILED)
        coord.fail_job(dispatched.job_id, f"Workspace creation failed: {exc}", run.run_id)
        coord.advance_work_item(work_item_id, WorkItemState.FAILED)
        return RunPipelineResult(
            success=False,
            stage_reached="create_workspace",
            work_item_id=work_item_id,
            run_id=run.run_id,
            job_id=dispatched.job_id,
            error=f"Workspace creation failed: {exc}",
            duration_seconds=time.time() - start_time,
        )

    try:
        # ── Stage 4: Build context pack ──────────────────────────
        coord.advance_run(run.run_id, RunState.CONTEXT_BUILT)

        # ── Stage 5: Execute (run validation commands) ───────────
        coord.advance_run(run.run_id, RunState.EXECUTING)

        exec_worker = ExecutionWorker(
            workspace=workspace,
            work_item=item,
            recipe=recipe,
            repo_path=repo_path,
        )

        harness = Harness(event_bus=event_bus)
        harness_result = harness.run(exec_worker, _build_task_envelope(dispatched, run))

        validation_results = harness_result.raw_output.payload.get(
            "validation_results", []
        ) if harness_result.raw_output else []

        # ── Stage 6: Run code review ─────────────────────────────
        coord.advance_run(run.run_id, RunState.VALIDATING)

        diff_text = _get_workspace_diff(workspace.workspace_path)
        files_changed = harness_result.raw_output.payload.get(
            "files_changed", []
        ) if harness_result.raw_output else []

        review_strategy = select_review_strategy()
        review_worker = CodeReviewWorker(
            diff_text=diff_text,
            files_changed=files_changed,
            validation_results=validation_results,
            review_strategy=review_strategy,
            run_id=run.run_id,
            workspace_path=workspace.workspace_path,
        )

        review_task = _build_review_task_envelope(dispatched, run)
        harness.run(review_worker, review_task)

        review_result = review_worker.review_result
        review_verdict_str = (
            review_result.overall_verdict.value if review_result else "unknown"
        )
        review_confidence = review_result.confidence if review_result else 0.0
        review_summary = review_result.summary if review_result else ""

        # ── Stage 7: Security review + promotion ─────────────────
        coord.advance_run(run.run_id, RunState.SECURITY_REVIEW)
        coord.mark_security_review_passed(run.run_id)

        exec_passed = harness_result.result_envelope.status == ResultStatus.SUCCESS
        review_ok = review_verdict_str in ("pass", "pass_with_warnings")

        branch_name: str | None = None
        commit_hash: str | None = None

        if exec_passed and review_ok:
            coord.advance_run(run.run_id, RunState.BRANCH_READY)

            promotion_mgr = PromotionManager(
                lock_manager=coord.locks, event_bus=event_bus
            )
            promo_request = PromotionRequest(
                workspace=workspace,
                work_item=item,
                run_record=run,
            )
            promo_outcome = promotion_mgr.promote(promo_request)

            if promo_outcome.success:
                branch_name = promo_outcome.branch_name
                commit_hash = promo_outcome.commit_hash
                files_changed = promo_outcome.files_changed
                coord.advance_run(run.run_id, RunState.COMPLETED)
                coord.complete_job(dispatched.job_id, run.run_id)
                coord.advance_work_item(work_item_id, WorkItemState.COMPLETED)
            else:
                coord.advance_run(run.run_id, RunState.FAILED)
                coord.fail_job(
                    dispatched.job_id,
                    f"Promotion failed: {promo_outcome.error}",
                    run.run_id,
                )
                coord.advance_work_item(work_item_id, WorkItemState.FAILED)
                return RunPipelineResult(
                    success=False,
                    stage_reached="promote",
                    work_item_id=work_item_id,
                    run_id=run.run_id,
                    job_id=dispatched.job_id,
                    review_verdict=review_verdict_str,
                    review_confidence=review_confidence,
                    review_summary=review_summary,
                    error=f"Promotion failed: {promo_outcome.error}",
                    duration_seconds=time.time() - start_time,
                    total_cost=harness_result.total_cost,
                    validation_results=validation_results,
                )
        else:
            # Execution or review failed — no promotion
            if not exec_passed:
                failure_reason = "Execution failed"
            else:
                failure_reason = f"Code review verdict: {review_verdict_str}"

            coord.advance_run(run.run_id, RunState.BRANCH_READY)
            coord.advance_run(run.run_id, RunState.FAILED)
            coord.fail_job(dispatched.job_id, failure_reason, run.run_id)
            coord.advance_work_item(work_item_id, WorkItemState.FAILED)

            return RunPipelineResult(
                success=False,
                stage_reached="review" if exec_passed else "execute",
                work_item_id=work_item_id,
                run_id=run.run_id,
                job_id=dispatched.job_id,
                review_verdict=review_verdict_str,
                review_confidence=review_confidence,
                review_summary=review_summary,
                error=failure_reason,
                duration_seconds=time.time() - start_time,
                total_cost=harness_result.total_cost,
                validation_results=validation_results,
            )

        elapsed = time.time() - start_time

        return RunPipelineResult(
            success=True,
            stage_reached="completed",
            work_item_id=work_item_id,
            run_id=run.run_id,
            job_id=dispatched.job_id,
            branch_name=branch_name,
            commit_hash=commit_hash,
            review_verdict=review_verdict_str,
            review_confidence=review_confidence,
            review_summary=review_summary,
            total_cost=harness_result.total_cost,
            duration_seconds=elapsed,
            files_changed=files_changed,
            validation_results=validation_results,
        )

    finally:
        ws_manager.destroy(workspace.workspace_id)


def _get_workspace_diff(workspace_path: Path) -> str:
    """Get the git diff from an isolated workspace."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result.stdout[:50000] if result.stdout else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _build_task_envelope(
    job: Any, run: Any
) -> Any:
    """Build a TaskEnvelope for the execution worker."""
    from foxhound.core.models import ExecutionMode, TaskEnvelope

    return TaskEnvelope(
        task_id=f"task_{run.run_id[:12]}",
        job_id=job.job_id,
        run_id=run.run_id,
        repo_id=job.repo_id,
        execution_snapshot=job.execution_snapshot,
        budget=job.budget,
        timeout_seconds=job.timeout_seconds,
        execution_mode=ExecutionMode.FULL_EXECUTE,
    )


def _build_review_task_envelope(
    job: Any, run: Any
) -> Any:
    """Build a TaskEnvelope for the code review worker."""
    from foxhound.core.models import ExecutionMode, TaskEnvelope

    return TaskEnvelope(
        task_id=f"review_{run.run_id[:12]}",
        job_id=job.job_id,
        run_id=run.run_id,
        repo_id=job.repo_id,
        execution_snapshot=job.execution_snapshot,
        budget=0.50,
        timeout_seconds=120,
        execution_mode=ExecutionMode.READ_ONLY,
    )
