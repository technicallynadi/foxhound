"""Capability benchmark for model tier validation.

Runs standardized prompts against configured models, scores responses
against known-good baselines, and warns if quality is below threshold.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from foxhound.core.models import ModelTier

logger = logging.getLogger(__name__)

# Benchmark prompt: a small code review task with a known correct answer
BENCHMARK_PROMPT = (
    "Review this Python function for bugs. Return only the bug description "
    "in one sentence.\n\n"
    "```python\n"
    "def divide_list(numbers, divisor):\n"
    "    results = []\n"
    "    for n in numbers:\n"
    "        results.append(n / divisor)\n"
    "    return results\n"
    "```"
)

# Keywords that a correct response should contain
EXPECTED_KEYWORDS = ["zero", "division", "divisor"]

# Minimum benchmark score (0-100) for the reasoning tier
REASONING_THRESHOLD = 60

# Score weights
KEYWORD_SCORE_EACH = 25
RESPONSE_PRESENT_SCORE = 25


@dataclass
class BenchmarkResult:
    """Result from benchmarking a single tier."""

    tier: str
    model_id: str = ""
    score: int = 0
    response: str = ""
    error: str | None = None
    below_threshold: bool = False


@dataclass
class BenchmarkSummary:
    """Summary of all tier benchmarks."""

    results: list[BenchmarkResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def score_response(response_text: str) -> int:
    """Score a benchmark response against the known-good baseline.

    Checks for presence of expected keywords indicating the model
    identified the division-by-zero bug.

    Args:
        response_text: The model's response text.

    Returns:
        Score from 0-100.
    """
    if not response_text.strip():
        return 0

    score = RESPONSE_PRESENT_SCORE
    lower = response_text.lower()

    for keyword in EXPECTED_KEYWORDS:
        if keyword in lower:
            score += KEYWORD_SCORE_EACH

    return min(score, 100)


def run_benchmark_for_tier(
    tier: ModelTier,
    complete_fn: Callable[..., Any] | None = None,
) -> BenchmarkResult:
    """Run the benchmark prompt against a single tier.

    Args:
        tier: Model tier to benchmark.
        complete_fn: Optional callable (tier, messages) -> ModelResponse.
            If None, returns a dry-run result.

    Returns:
        BenchmarkResult with score and response.
    """
    result = BenchmarkResult(tier=tier.value)

    if complete_fn is None:
        result.error = "No model router available"
        return result

    try:
        response = complete_fn(
            tier,
            [{"role": "user", "content": BENCHMARK_PROMPT}],
        )
        result.response = response.content if hasattr(response, "content") else str(response)
        result.model_id = response.model_id if hasattr(response, "model_id") else ""
        result.score = score_response(result.response)

        if tier == ModelTier.REASONING and result.score < REASONING_THRESHOLD:
            result.below_threshold = True
    except Exception as exc:
        result.error = str(exc)

    return result


def run_full_benchmark(
    configured_tiers: list[ModelTier],
    complete_fn: Callable[..., Any] | None = None,
) -> BenchmarkSummary:
    """Run benchmarks against all configured tiers.

    Args:
        configured_tiers: List of tiers to benchmark.
        complete_fn: Callable (tier, messages) -> ModelResponse.

    Returns:
        BenchmarkSummary with per-tier results and warnings.
    """
    summary = BenchmarkSummary()

    for tier in configured_tiers:
        result = run_benchmark_for_tier(tier, complete_fn)
        summary.results.append(result)

        if result.error:
            logger.warning(
                "Benchmark failed for %s: %s", tier.value, result.error,
            )
        elif result.below_threshold:
            warning = (
                f"Reasoning tier ({result.model_id}) scored {result.score}/100, "
                f"below threshold {REASONING_THRESHOLD}. "
                f"Code review accuracy may be reduced."
            )
            summary.warnings.append(warning)
            logger.warning(warning)

    return summary


def format_benchmark_output(summary: BenchmarkSummary) -> str:
    """Format benchmark results for CLI display.

    Args:
        summary: Benchmark results.

    Returns:
        Formatted string for console output.
    """
    lines: list[str] = ["[bold]Model Benchmark Results[/bold]\n"]

    for result in summary.results:
        if result.error:
            lines.append(
                f"  {result.tier}: [red]error[/red] — {result.error}"
            )
        elif result.below_threshold:
            lines.append(
                f"  {result.tier}: [yellow]{result.score}/100[/yellow] "
                f"⚠ below threshold ({result.model_id})"
            )
        else:
            lines.append(
                f"  {result.tier}: [green]{result.score}/100[/green] "
                f"({result.model_id})"
            )

    if summary.warnings:
        lines.append("")
        for warning in summary.warnings:
            lines.append(f"[yellow]Warning:[/yellow] {warning}")

    return "\n".join(lines)
