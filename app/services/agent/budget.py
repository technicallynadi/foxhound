"""Budget tracking for agent requests.

Tracks token usage, cost, and iteration count per request.
Enforces caps to prevent runaway agent loops.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Haiku pricing (per million tokens)
HAIKU_INPUT_COST_PER_M = 0.80
HAIKU_OUTPUT_COST_PER_M = 4.00

MAX_ITERATIONS = 10
MAX_TOKENS_PER_REQUEST = 50_000
MAX_COST_PER_REQUEST = 0.10  # $0.10


@dataclass
class RequestBudget:
    """Tracks resource usage for a single agent request."""

    max_iterations: int = MAX_ITERATIONS
    max_tokens: int = MAX_TOKENS_PER_REQUEST
    max_cost: float = MAX_COST_PER_REQUEST

    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    tool_calls: list[dict] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def estimated_cost(self) -> float:
        return (
            self.input_tokens / 1_000_000 * HAIKU_INPUT_COST_PER_M
            + self.output_tokens / 1_000_000 * HAIKU_OUTPUT_COST_PER_M
        )

    def record_api_call(self, input_tokens: int, output_tokens: int) -> None:
        """Record an API call's token usage."""
        self.iterations += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def record_tool_call(self, tool_name: str, duration_ms: int = 0) -> None:
        """Record a tool execution."""
        self.tool_calls.append({
            "tool": tool_name,
            "duration_ms": duration_ms,
        })

    def can_continue(self) -> bool:
        """Check if the budget allows another iteration."""
        if self.iterations >= self.max_iterations:
            logger.warning("Budget exhausted: max iterations (%d)", self.max_iterations)
            return False
        if self.total_tokens >= self.max_tokens:
            logger.warning("Budget exhausted: max tokens (%d)", self.max_tokens)
            return False
        if self.estimated_cost >= self.max_cost:
            logger.warning("Budget exhausted: max cost ($%.4f)", self.max_cost)
            return False
        return True

    def summary(self) -> dict:
        """Return a summary for logging."""
        return {
            "iterations": self.iterations,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost": round(self.estimated_cost, 6),
            "tool_calls": len(self.tool_calls),
        }
