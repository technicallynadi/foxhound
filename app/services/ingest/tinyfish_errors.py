"""Structured error typing for TinyFish extraction runs."""

from enum import StrEnum


class TinyFishErrorType(StrEnum):
    rate_limit = "rate_limit"
    blocked = "blocked"
    timeout = "timeout"
    parse_failure = "parse_failure"
    captcha = "captcha"
    login_wall = "login_wall"
    network = "network"
    api_error = "api_error"
    unknown = "unknown"


RETRYABLE = {TinyFishErrorType.rate_limit, TinyFishErrorType.timeout, TinyFishErrorType.network}


def is_retryable(error_type: str | TinyFishErrorType) -> bool:
    return TinyFishErrorType(error_type) in RETRYABLE


def classify_error(
    exception: Exception | None = None,
    response: object | None = None,
) -> TinyFishErrorType:
    """Classify a TinyFish failure into a structured error type."""
    # Check response status/error first
    if response is not None:
        error_msg = ""
        if hasattr(response, "error") and response.error:
            error_msg = getattr(response.error, "message", str(response.error)).lower()
        status = getattr(response, "status", "")

        if status in ("CANCELLED",):
            return TinyFishErrorType.blocked

        if error_msg:
            return _classify_message(error_msg)

    # Classify by exception type and message
    if exception is not None:
        if isinstance(exception, TimeoutError):
            return TinyFishErrorType.timeout
        if isinstance(exception, ConnectionError | OSError):
            return TinyFishErrorType.network
        if isinstance(exception, ValueError | KeyError):
            return TinyFishErrorType.parse_failure

        msg = str(exception).lower()
        return _classify_message(msg)

    return TinyFishErrorType.unknown


def _classify_message(msg: str) -> TinyFishErrorType:
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return TinyFishErrorType.rate_limit
    if "captcha" in msg:
        return TinyFishErrorType.captcha
    if "login" in msg or "sign in" in msg or "log in" in msg or "authentication" in msg:
        return TinyFishErrorType.login_wall
    if "timeout" in msg or "timed out" in msg:
        return TinyFishErrorType.timeout
    if "blocked" in msg or "forbidden" in msg or "403" in msg or "access denied" in msg:
        return TinyFishErrorType.blocked
    if "connection" in msg or "dns" in msg or "network" in msg:
        return TinyFishErrorType.network
    if "json" in msg or "parse" in msg or "decode" in msg or "key" in msg:
        return TinyFishErrorType.parse_failure
    return TinyFishErrorType.api_error
