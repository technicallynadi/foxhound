"""Structured error responses for agent-friendliness.

Agents need machine-parseable errors with codes, context, and retry hints
to diagnose issues without human intervention.
"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse


class FoxhoundError(HTTPException):
    """Structured error with code, context, and retry guidance."""

    def __init__(
        self,
        status_code: int = 400,
        error_code: str = "UNKNOWN_ERROR",
        detail: str = "An error occurred",
        debug_context: dict | None = None,
        retry_after_seconds: int | None = None,
        retryable: bool = False,
    ):
        self.error_code = error_code
        self.debug_context = debug_context or {}
        self.retry_after_seconds = retry_after_seconds
        self.retryable = retryable
        super().__init__(status_code=status_code, detail=detail)


def foxhound_error_handler(request, exc: FoxhoundError) -> JSONResponse:
    """FastAPI exception handler for FoxhoundError."""
    body = {
        "error": exc.detail,
        "error_code": exc.error_code,
        "retryable": exc.retryable,
    }
    if exc.debug_context:
        body["debug_context"] = exc.debug_context
    if exc.retry_after_seconds is not None:
        body["retry_after_seconds"] = exc.retry_after_seconds
    return JSONResponse(status_code=exc.status_code, content=body)


# Common error factories

def not_found(resource: str, resource_id: str) -> FoxhoundError:
    return FoxhoundError(
        status_code=404,
        error_code=f"{resource.upper()}_NOT_FOUND",
        detail=f"{resource} not found: {resource_id}",
        debug_context={"resource": resource, "id": resource_id},
    )


def artifact_not_found(opportunity_id: str) -> FoxhoundError:
    return FoxhoundError(
        status_code=404,
        error_code="ARTIFACT_NOT_FOUND",
        detail="No execution artifact found. Generate one first.",
        debug_context={"opportunity_id": opportunity_id},
    )


def llm_timeout(model: str, timeout_seconds: float) -> FoxhoundError:
    return FoxhoundError(
        status_code=504,
        error_code="LLM_TIMEOUT",
        detail=f"LLM request timed out after {timeout_seconds}s",
        debug_context={"model": model, "timeout_seconds": timeout_seconds},
        retry_after_seconds=10,
        retryable=True,
    )


def llm_error(model: str, error: str) -> FoxhoundError:
    return FoxhoundError(
        status_code=502,
        error_code="LLM_ERROR",
        detail=f"LLM request failed: {error[:200]}",
        debug_context={"model": model},
        retry_after_seconds=5,
        retryable=True,
    )


def build_failed(project_id: str, error: str) -> FoxhoundError:
    return FoxhoundError(
        status_code=500,
        error_code="BUILD_FAILED",
        detail=f"Build failed: {error[:200]}",
        debug_context={"project_id": project_id},
        retryable=True,
        retry_after_seconds=5,
    )


def deploy_failed(app_name: str, error: str) -> FoxhoundError:
    return FoxhoundError(
        status_code=502,
        error_code="DEPLOY_FAILED",
        detail=f"Preview deployment failed: {error[:200]}",
        debug_context={"fly_app_name": app_name},
        retryable=True,
        retry_after_seconds=10,
    )


def auth_required() -> FoxhoundError:
    return FoxhoundError(
        status_code=401,
        error_code="AUTH_REQUIRED",
        detail="Authentication required",
    )


def insufficient_tier(required: str, current: str) -> FoxhoundError:
    return FoxhoundError(
        status_code=403,
        error_code="INSUFFICIENT_TIER",
        detail=f"This feature requires {required} tier (current: {current})",
        debug_context={"required_tier": required, "current_tier": current},
    )
