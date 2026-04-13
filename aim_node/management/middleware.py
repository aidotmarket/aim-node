from __future__ import annotations

import hmac
import secrets
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from aim_node.management.errors import ErrorCode, make_error

CSRF_TOKEN_HEADER = "X-CSRF-Token"
SESSION_TOKEN_HEADER = "X-Session-Token"
CSRF_RESPONSE_HEADER = "X-CSRF-Token"

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _origin_is_loopback(origin: Optional[str]) -> bool:
    """Return True if the Origin host is a loopback hostname/address."""
    if not origin:
        return False
    without_scheme = origin.split("://", 1)[-1]
    host = without_scheme.rsplit("@", 1)[-1]
    if host.startswith("[") and "]" in host:
        host = host[1:].split("]", 1)[0]
    else:
        host = host.split(":", 1)[0]
    return host in _LOOPBACK_HOSTS


def _origin_is_loopback_request(request: Request) -> bool:
    """Check whether the ASGI client address is loopback."""
    client_host = request.client.host if request.client else None
    return client_host in _LOOPBACK_HOSTS


class CSRFMiddleware(BaseHTTPMiddleware):
    """Enforce CSRF protections and remote-bind session token auth."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not hasattr(request.app.state, "csrf_token"):
            request.app.state.csrf_token = secrets.token_hex(32)

        token_just_issued = False

        if getattr(request.app.state, "remote_bind", False):
            expected = getattr(request.app.state, "session_token", None)
            if expected is None:
                if _origin_is_loopback_request(request):
                    request.app.state.session_token = secrets.token_hex(32)
                    request.state.session_token_issued = request.app.state.session_token
                    token_just_issued = True
                else:
                    err = make_error(
                        ErrorCode.AUTH_FAILED,
                        "Session token not yet issued - access from localhost first",
                        suggested_action="Open http://localhost:<port>/api/mgmt/health first",
                    )
                    return JSONResponse(err.model_dump(exclude_none=True), status_code=401)
            else:
                session_token = (
                    request.headers.get(SESSION_TOKEN_HEADER)
                    or request.cookies.get("aim_session")
                )
                if not hmac.compare_digest(session_token or "", expected):
                    err = make_error(
                        ErrorCode.AUTH_FAILED,
                        "Session token required for remote access",
                        suggested_action="Provide X-Session-Token header or aim_session cookie",
                    )
                    return JSONResponse(err.model_dump(exclude_none=True), status_code=401)

        if request.method not in _SAFE_METHODS:
            origin = request.headers.get("Origin")
            csrf_header = request.headers.get(CSRF_TOKEN_HEADER)
            expected_csrf = request.app.state.csrf_token

            origin_ok = _origin_is_loopback(origin)
            token_ok = csrf_header is not None and hmac.compare_digest(
                csrf_header, expected_csrf
            )

            if not origin_ok and not token_ok:
                err = make_error(
                    ErrorCode.CSRF_REJECTED,
                    "Missing or invalid CSRF token",
                    suggested_action="Include X-CSRF-Token header from GET /api/mgmt/health",
                )
                return JSONResponse(err.model_dump(exclude_none=True), status_code=403)

        response = await call_next(request)
        response.headers[CSRF_RESPONSE_HEADER] = request.app.state.csrf_token
        if token_just_issued:
            response.set_cookie(
                "aim_session",
                request.app.state.session_token,
                httponly=True,
                samesite="strict",
                path="/",
            )
        return response
