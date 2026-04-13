from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel


class ErrorCode:
    SETUP_INCOMPLETE = "setup_incomplete"
    NODE_LOCKED = "node_locked"
    AUTH_FAILED = "auth_failed"
    CSRF_REJECTED = "csrf_rejected"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    ALREADY_RUNNING = "already_running"
    NOT_RUNNING = "not_running"
    CONFIG_INVALID = "config_invalid"
    TOOL_VALIDATION_FAILED = "tool_validation_failed"
    UPSTREAM_UNREACHABLE = "upstream_unreachable"
    MARKET_UNREACHABLE = "market_unreachable"
    MARKET_ERROR = "market_error"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    MARKET_TIMEOUT = "market_timeout"
    SERVICE_UNAVAILABLE = "service_unavailable"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"


# HTTP status codes for each error code
ERROR_HTTP_STATUS: dict[str, int] = {
    ErrorCode.SETUP_INCOMPLETE: 412,
    ErrorCode.NODE_LOCKED: 423,
    ErrorCode.AUTH_FAILED: 401,
    ErrorCode.CSRF_REJECTED: 403,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.ALREADY_EXISTS: 409,
    ErrorCode.ALREADY_RUNNING: 409,
    ErrorCode.NOT_RUNNING: 409,
    ErrorCode.CONFIG_INVALID: 422,
    ErrorCode.TOOL_VALIDATION_FAILED: 422,
    ErrorCode.UPSTREAM_UNREACHABLE: 502,
    ErrorCode.MARKET_UNREACHABLE: 502,
    ErrorCode.MARKET_ERROR: 502,
    ErrorCode.UPSTREAM_TIMEOUT: 504,
    ErrorCode.MARKET_TIMEOUT: 504,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.INTERNAL_ERROR: 500,
}

RETRYABLE_CODES: set[str] = {
    ErrorCode.UPSTREAM_UNREACHABLE,
    ErrorCode.MARKET_UNREACHABLE,
    ErrorCode.UPSTREAM_TIMEOUT,
    ErrorCode.MARKET_TIMEOUT,
    ErrorCode.RATE_LIMITED,
    ErrorCode.SERVICE_UNAVAILABLE,
}


class NormalizedError(BaseModel):
    """Section 5.1 error response format."""

    code: str
    message: str
    details: Optional[dict[str, Any]] = None
    retryable: Optional[bool] = None
    request_id: Optional[str] = None
    suggested_action: Optional[str] = None


def make_error(
    code: str,
    message: str,
    *,
    details: Optional[dict[str, Any]] = None,
    suggested_action: Optional[str] = None,
    request_id: Optional[str] = None,
) -> NormalizedError:
    """Construct a NormalizedError with auto-populated retryable flag and request_id."""
    return NormalizedError(
        code=code,
        message=message,
        details=details,
        retryable=(code in RETRYABLE_CODES),
        request_id=request_id or f"req_{uuid.uuid4().hex[:12]}",
        suggested_action=suggested_action,
    )


def make_market_error(
    backend_status: int,
    backend_body: str,
    endpoint: str,
    *,
    request_id: Optional[str] = None,
) -> NormalizedError:
    """Section 5.3 — wrap a non-2xx backend response as market_error."""
    return make_error(
        ErrorCode.MARKET_ERROR,
        "Marketplace returned an error",
        details={
            "status": backend_status,
            "backend_error": backend_body,
            "endpoint": endpoint,
        },
        suggested_action="Check your API key in Settings",
        request_id=request_id,
    )


HTTP_STATUS_TO_CODE: dict[int, str] = {
    400: ErrorCode.CONFIG_INVALID,
    401: ErrorCode.AUTH_FAILED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.ALREADY_EXISTS,
    412: ErrorCode.SETUP_INCOMPLETE,
    422: ErrorCode.CONFIG_INVALID,
    423: ErrorCode.NODE_LOCKED,
    429: ErrorCode.RATE_LIMITED,
    500: ErrorCode.INTERNAL_ERROR,
    502: ErrorCode.MARKET_ERROR,
    503: ErrorCode.SERVICE_UNAVAILABLE,
    504: ErrorCode.MARKET_TIMEOUT,
}
