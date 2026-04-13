# BQ-AIM-NODE-CONTRACTS — Gate 2 Spec
## Implementation: Error Normalization, CSRF/Security Middleware, Facade Base, OpenAPI

**BQ Code:** BQ-AIM-NODE-CONTRACTS
**Epic:** AIM-NODE-UI
**Phase:** 2 — Implementation
**Prerequisite:** Gate 1 approved (S431, commit 7e8ef98)
**Author:** Vulcan (S431)

---

**Revision History:**
- R1 (S432, 4c015be): Initial draft
- R2 (S433): Addressed MP R1 REVISE findings:
  - F1: Added retry-on-401 with token refresh in facade._request (Gate 1 M2)
  - F2: Resolved node_id vs node_serial — added node_id to AIMCoreConfig, clarified post-registration flow
  - F3: Replaced stderr-only session token with "issued on first localhost access" model (Gate 1 M1)
  - F4: Removed allAI endpoint from Gate 2 scope — deferred to BQ-AIM-NODE-ALLAI-COPILOT (Gate 1 compliance)
  - F5: Fixed CONFIG_INVALID status contradiction — all CONFIG_INVALID now consistently 422
  - F6: Changed /marketplace/discover from GET to POST (browser/OpenAPI compliance)
  - F7: Removed /setup/test-upstream from backend gaps (aim-node owned per Gate 1)
  - Codebase accuracy: 9 exception handlers (not 8), 6 inline errors (not ~5)


## Overview

Gate 1 defined the contracts. Gate 2 implements them. Four slices, independent delivery order. Each slice has its own done criteria and tests.

**Codebase baseline (as of Gate 2 draft):**
- `aim_node/management/app.py` — Starlette app factory, 9 ad-hoc exception handlers
- `aim_node/management/routes.py` — 17 route handlers, 6 inline `{"error": ...}` responses
- `aim_node/management/schemas.py` — `ErrorResponse(BaseModel)` exists but is `error: str` only
- `aim_node/core/auth.py` — `AuthService` with `get_auth_headers()` 
- `aim_node/core/market_client.py` — `MarketClient` wraps auth + httpx
- `aim_node/cli.py` — `serve` command defaults `--host 0.0.0.0` (security gap, M1)
- No CSRF middleware, no facade routes, no OpenAPI docs

---

## Slice A: Error Normalization (est 4h)

### A.1 New File: `aim_node/management/errors.py`

Create this file. Do not modify `schemas.py` until A.3.

```python
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
```

**Notes:**
- `ErrorCode` is a plain class with string constants (not `Enum`) — avoids `.value` boilerplate throughout callers.
- `NormalizedError` is the canonical Pydantic model. It replaces the existing `ErrorResponse` in `schemas.py` at A.3.
- `make_market_error()` is the Section 5.3 passthrough wrapper called by facade routes when `MarketClient` raises `MarketClientHTTPError`.

### A.2 Update `aim_node/management/app.py`

Replace all 9 exception handlers to use `NormalizedError`. Import from `errors.py`.

**Mapping (old exception → new error code):**

| Exception | ErrorCode | HTTP | Suggested Action |
|-----------|-----------|------|-----------------|
| `PreconditionError` | `SETUP_INCOMPLETE` | 412 | "Complete node setup first" |
| `LockedError` | `NODE_LOCKED` | 423 | "Unlock the node before proceeding" |
| `AlreadyRunningError` | `ALREADY_RUNNING` | 409 | None |
| `NotRunningError` | `NOT_RUNNING` | 409 | None |
| `FileExistsError` | `ALREADY_EXISTS` | 409 | None |
| `ConfigError` | `CONFIG_INVALID` | 422 | "Check configuration file" |
| `ValidationError` (pydantic) | `CONFIG_INVALID` | 422 | None |
| `ValueError` | `CONFIG_INVALID` | 422 | None |
| `HTTPException` (starlette) | map status code to nearest error code | passthrough | None |

**Handler pattern (same for all):**
```python
async def _precondition_handler(request: Request, exc: PreconditionError) -> JSONResponse:
    err = make_error(ErrorCode.SETUP_INCOMPLETE, str(exc) or "Precondition failed",
                     suggested_action="Complete node setup first")
    return JSONResponse(err.model_dump(exclude_none=True), status_code=412)
```

For `ValidationError`: include pydantic `exc.errors(include_url=False, include_context=False, include_input=False)` in `details={"fields": errors}`.

For `HTTPException`: use `exc.status_code`, map to nearest `ErrorCode` via a lookup table in `errors.py`:
```python
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
```

Add a catch-all `Exception` handler for unhandled errors:
```python
async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception in management API")
    err = make_error(ErrorCode.INTERNAL_ERROR, "An unexpected error occurred")
    return JSONResponse(err.model_dump(exclude_none=True), status_code=500)
```
Register as `Exception: _unhandled_handler` in `exception_handlers`.

### A.3 Migrate `aim_node/management/schemas.py`

Replace:
```python
class ErrorResponse(BaseModel):
    error: str
```
With:
```python
from aim_node.management.errors import NormalizedError
ErrorResponse = NormalizedError  # backwards-compatible alias
```

This keeps the name `ErrorResponse` available but now it resolves to the full contract model.

### A.4 Update `aim_node/management/routes.py`

Replace 6 inline `JSONResponse({"error": ...}, status_code=...)` calls with `NormalizedError`:

| Location | Current | New code | HTTP |
|----------|---------|----------|------|
| `setup_keypair` L115 | `{"error": "Keypair already exists"}` | `ALREADY_EXISTS` | 409 |
| `config_update` L263 | `{"error": "upstream_url required..."}` | `CONFIG_INVALID` | 422 |
| `session_detail` L356 | `{"error": "Session not found"}` | `NOT_FOUND` | 404 |
| `unlock` L377 | `{"error": "Invalid passphrase"}` | `AUTH_FAILED` | 401 |
| `keypair_info` L397 | `{"error": "Keystore not found"}` | `NOT_FOUND` | 404 |
| `keypair_info` L413 | `{"error": "Keystore corrupted"}` | `INTERNAL_ERROR` | 500 |

**Pattern for each:**
```python
from aim_node.management.errors import ErrorCode, make_error
# ...
err = make_error(ErrorCode.NOT_FOUND, "Session not found")
return JSONResponse(err.model_dump(exclude_none=True), status_code=404)
```

Do NOT create a helper wrapper function — keep it explicit per the 3-lines-not-abstraction rule.

### A.5 Tests

**File:** `tests/test_errors.py` (new)

Unit tests for `errors.py`:
- `test_make_error_sets_request_id` — `request_id` is non-empty string starting with `req_`
- `test_make_error_retryable_true` — retryable codes have `retryable=True`
- `test_make_error_retryable_false` — non-retryable codes have `retryable=False`
- `test_make_market_error_shape` — output matches Section 5.3 exactly
- `test_error_http_status_complete` — every `ErrorCode` constant has an entry in `ERROR_HTTP_STATUS`

**File:** `tests/test_management_api.py` (extend existing)

Integration tests (Starlette `TestClient`):
- `test_locked_error_returns_normalized` — trigger `LockedError`, assert `code == "node_locked"`, `status == 423`
- `test_precondition_error_returns_normalized` — `code == "setup_incomplete"`, `status == 412`
- `test_not_found_session_returns_normalized` — GET nonexistent session, `code == "not_found"`, `status == 404`
- `test_invalid_passphrase_returns_normalized` — POST /unlock wrong passphrase, `code == "auth_failed"`, `status == 401`
- `test_duplicate_keypair_returns_normalized` — POST /setup/keypair twice, `code == "already_exists"`, `status == 409`

### A.6 Done Criteria

- All responses from the management API follow the Section 5.1 format
- No `{"error": "..."}` string-only responses remain in `app.py` or `routes.py`
- Every error code in Section 5.2 maps to an HTTP status in `ERROR_HTTP_STATUS`
- `request_id` is present and unique on every error response
- `retryable` is set correctly for connectivity error codes
- `make_market_error()` produces the exact shape from Section 5.3
- All A.5 tests pass

---

## Slice B: CSRF/Security Middleware (est 3h)

### B.1 New File: `aim_node/management/middleware.py`

```python
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
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
    """Return True if Origin header is http://localhost:* or http://127.0.0.1:*."""
    if not origin:
        return False
    # origin format: "http://host" or "http://host:port"
    # strip scheme
    without_scheme = origin.split("://", 1)[-1]
    host = without_scheme.split(":")[0]
    return host in _LOOPBACK_HOSTS


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    Implements Contract M1 CSRF/origin protection.

    - Issues a per-session CSRF token stored in `app.state.csrf_token`
      (generated at first middleware init, survives app lifetime).
    - On safe methods (GET/HEAD/OPTIONS): passes through, injects token header.
    - On mutating methods (POST/PUT/DELETE/PATCH):
        - Allow if Origin is loopback, OR
        - Allow if X-CSRF-Token matches app.state.csrf_token
        - Reject with 403 + ErrorCode.CSRF_REJECTED otherwise.
    - On remote-bind mode (app.state.remote_bind == True):
        - All requests (including safe) MUST include X-Session-Token matching
          app.state.session_token.
        - Missing/wrong session token → 401 + ErrorCode.AUTH_FAILED.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        # Lazily generate CSRF token once per app lifecycle
        if not hasattr(request.app.state, "csrf_token"):
            request.app.state.csrf_token = secrets.token_hex(32)

        # Remote-bind session token check (applied before CSRF)
        if getattr(request.app.state, "remote_bind", False):
            session_token = request.headers.get(SESSION_TOKEN_HEADER)
            expected = getattr(request.app.state, "session_token", None)
            if not expected or not hmac.compare_digest(session_token or "", expected):
                err = make_error(ErrorCode.AUTH_FAILED,
                                 "Session token required for remote access",
                                 suggested_action="Provide X-Session-Token header")
                return JSONResponse(err.model_dump(exclude_none=True), status_code=401)

        # CSRF check on mutating methods only
        if request.method not in _SAFE_METHODS:
            origin = request.headers.get("Origin")
            csrf_header = request.headers.get(CSRF_TOKEN_HEADER)
            expected_csrf = request.app.state.csrf_token

            origin_ok = _origin_is_loopback(origin)
            token_ok = csrf_header is not None and hmac.compare_digest(csrf_header, expected_csrf)

            if not origin_ok and not token_ok:
                err = make_error(
                    ErrorCode.CSRF_REJECTED,
                    "Missing or invalid CSRF token",
                    suggested_action="Include X-CSRF-Token header from GET /api/mgmt/health",
                )
                return JSONResponse(err.model_dump(exclude_none=True), status_code=403)

        response = await call_next(request)

        # Always inject CSRF token in response header (safe for browser to read)
        response.headers[CSRF_RESPONSE_HEADER] = request.app.state.csrf_token
        return response
```

**Notes:**
- `app.state.csrf_token` is initialized lazily on first request to avoid needing lifespan changes.
- `app.state.remote_bind` and `app.state.session_token` are set by the app factory when `--host 0.0.0.0` is used.
- `hmac.compare_digest` prevents timing attacks.
- `_origin_is_loopback` handles `localhost`, `127.0.0.1`, `::1` without regex.

### B.2 Update `aim_node/management/app.py`

Add `CSRFMiddleware` to the middleware stack:

```python
from aim_node.management.middleware import CSRFMiddleware

# In create_management_app(), after app = Starlette(...):
app.add_middleware(CSRFMiddleware)
```

Middleware is applied after routing, so exception handlers fire before CSRF errors — this is correct behavior (Starlette exception handlers wrap middleware).

**Add `remote_bind` and `session_token` to factory signature:**

```python
def create_management_app(
    data_dir: Path,
    *,
    remote_bind: bool = False,
) -> Starlette:
```

In `lifespan`:
```python
app.state.remote_bind = remote_bind
app.state.session_token = None  # Issued on first loopback request (Gate 1 M1)
```

### B.3 Update `aim_node/management/routes.py` — health endpoint

Add CSRF token to `GET /api/mgmt/health` response header. The middleware already injects it, but the health handler should also expose it in the JSON body for non-browser clients:

```python
async def health(request: Request) -> JSONResponse:
    state = request.app.state.store
    status = state.get_status()
    csrf_token = getattr(request.app.state, "csrf_token", None)
    response = JSONResponse(
        HealthResponse(
            healthy=True,
            setup_complete=status["setup_complete"],
            locked=status["locked"],
            csrf_token=csrf_token,   # add field to HealthResponse schema
        ).model_dump()
    )
    if csrf_token:
        response.headers["X-CSRF-Token"] = csrf_token
    return response
```

Update `HealthResponse` in `schemas.py`:
```python
class HealthResponse(BaseModel):
    healthy: bool = True
    setup_complete: bool
    locked: bool
    csrf_token: Optional[str] = None
```

### B.4 Fix `aim_node/cli.py` — default host

Change `serve` command default from `0.0.0.0` to `127.0.0.1` (Contract M1):

```python
# Before:
@click.option("--host", default="0.0.0.0")

# After:
@click.option("--host", default="127.0.0.1",
              help="Bind host. Use 0.0.0.0 only with explicit intent — requires session token.")
```

When `--host 0.0.0.0` is used, enable remote-bind mode (no pre-generated token):

```python
def serve(data_dir: str, host: str, port: int) -> None:
    """Start the AIM Node management HTTP server."""
    import uvicorn
    from aim_node.management.app import create_management_app

    remote_bind = host not in ("127.0.0.1", "localhost", "::1")
    if remote_bind:
        click.echo(
            f"WARNING: Binding to {host}. Remote access enabled.\n"
            f"Session token will be issued on first localhost access.",
            err=True,
        )

    app = create_management_app(Path(data_dir), remote_bind=remote_bind)
    uvicorn.run(app, host=host, port=port)
```

**Session token lifecycle (Gate 1 M1 compliance):**

1. App starts with `remote_bind=True`, `app.state.session_token = None`.
2. First request from a loopback address (127.0.0.1, localhost, ::1) triggers token generation:
   - `app.state.session_token = secrets.token_hex(32)`
   - Token returned in response body (`session_token` field) AND `Set-Cookie: aim_session=<token>; HttpOnly; SameSite=Strict; Path=/`
3. Subsequent requests from any origin must include the token via `X-Session-Token` header or `aim_session` cookie.
4. Token is ephemeral — lost on process restart.

This matches Gate 1 M1: "issued on first localhost access, stored in browser, validated on every request."

Update `CSRFMiddleware.dispatch()` in `middleware.py` to handle this:
```python
# In remote-bind session token check:
if getattr(request.app.state, "remote_bind", False):
    # Token issuance on first loopback request
    if request.app.state.session_token is None:
        if _origin_is_loopback_request(request):
            import secrets, sys
            token = secrets.token_hex(32)
            request.app.state.session_token = token
            # Token delivered via Set-Cookie + response body on this request
        else:
            # Non-loopback request before any loopback has issued a token
            err = make_error(ErrorCode.AUTH_FAILED,
                             "Session token not yet issued — access from localhost first",
                             suggested_action="Open http://localhost:<port>/api/mgmt/health first")
            return JSONResponse(err.model_dump(exclude_none=True), status_code=401)
    else:
        # Token exists — validate
        session_token = (
            request.headers.get(SESSION_TOKEN_HEADER)
            or request.cookies.get("aim_session")
        )
        if not hmac.compare_digest(session_token or "", request.app.state.session_token):
            err = make_error(ErrorCode.AUTH_FAILED,
                             "Session token required for remote access",
                             suggested_action="Provide X-Session-Token header or aim_session cookie")
            return JSONResponse(err.model_dump(exclude_none=True), status_code=401)

# ... after call_next:
# If token was just issued this request, inject Set-Cookie
if getattr(request.app.state, "_token_just_issued", False):
    response.set_cookie("aim_session", request.app.state.session_token,
                        httponly=True, samesite="strict", path="/")
    request.app.state._token_just_issued = False
```

Add helper:
```python
def _origin_is_loopback_request(request: Request) -> bool:
    """Check if the request originates from a loopback address."""
    client_host = request.client.host if request.client else None
    return client_host in _LOOPBACK_HOSTS
```

### B.5 Tests

**File:** `tests/test_middleware.py` (new)

Unit/integration tests using `TestClient`:
- `test_csrf_safe_method_passes_without_token` — GET /api/mgmt/health returns 200
- `test_csrf_mutating_loopback_origin_passes` — POST with `Origin: http://localhost:3000` returns non-403
- `test_csrf_mutating_valid_token_passes` — POST with correct `X-CSRF-Token` returns non-403
- `test_csrf_mutating_missing_both_rejected` — POST with no Origin and no token returns 403 + `code == "csrf_rejected"`
- `test_csrf_mutating_wrong_token_rejected` — POST with wrong token returns 403
- `test_csrf_token_in_response_header` — GET /health response has `X-CSRF-Token` header
- `test_remote_bind_valid_session_token_passes` — app with `remote_bind=True`, correct `X-Session-Token` passes
- `test_remote_bind_missing_session_token_rejected` — app with `remote_bind=True`, no token → 401
- `test_remote_bind_first_loopback_issues_token` — first request from 127.0.0.1 returns session_token in body + Set-Cookie
- `test_remote_bind_non_loopback_before_issue_rejected` — non-loopback request before any loopback → 401 "not yet issued"
- `test_remote_bind_cookie_auth_accepted` — request with aim_session cookie passes validation
- `test_health_includes_csrf_token_in_body` — `GET /health` JSON body has `csrf_token` field

**File:** `tests/test_cli.py` (extend existing)

- `test_serve_default_host_is_loopback` — invoke CLI `serve --help` or mock uvicorn, assert default host is `127.0.0.1`

### B.6 Done Criteria

- `GET /api/mgmt/health` response includes `X-CSRF-Token` header and `csrf_token` in body
- POST/PUT/DELETE without valid Origin or CSRF token → 403 + `code: "csrf_rejected"`
- POST with `Origin: http://localhost:3000` passes without CSRF token
- POST with correct `X-CSRF-Token` passes regardless of Origin
- `aim-node serve` defaults to `--host 127.0.0.1`
- `--host 0.0.0.0` issues session token on first localhost access and enforces `X-Session-Token`/cookie validation
- All B.5 tests pass

---

## Slice C: Facade Base & Auth Helpers (est 4h)

### C.1 New File: `aim_node/management/facade.py`

The facade base class wraps `MarketClient` to provide: auth injection, retry-on-401, error normalization, and TTL caching.

```python
from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from aim_node.core.auth import AuthService, AuthError
from aim_node.core.market_client import MarketClient, MarketClientError, MarketClientHTTPError
from aim_node.management.errors import (
    ErrorCode, NormalizedError, make_error, make_market_error,
)


class FacadeError(Exception):
    """Raised by facade methods. Always carries a NormalizedError."""
    def __init__(self, normalized: NormalizedError, http_status: int) -> None:
        self.normalized = normalized
        self.http_status = http_status
        super().__init__(normalized.message)


class MarketplaceFacade:
    """
    Base class for all marketplace facade route handlers.

    Lifecycle: one instance per app (stored in app.state.facade).
    Caller creates via MarketplaceFacade.create(config, data_dir).

    Subclassing: not needed. Facade routes call methods directly.
    """

    # Cache storage: { cache_key: (expires_at_monotonic, payload) }
    _cache: dict[str, tuple[float, Any]]

    def __init__(self, client: MarketClient, node_id: str) -> None:
        self.client = client
        self.node_id = node_id
        self._cache = {}

    @classmethod
    def create(cls, config: "AIMCoreConfig") -> "MarketplaceFacade":
        """Factory. Reads node_id from config (set after registration).

        Gate 1 defines a two-field model:
        - node_serial: local identifier, set at first config creation
        - node_id: backend-assigned UUID, returned by POST /aim/nodes/register
          and stored in config after successful registration

        The facade uses node_id for all backend API paths. If node_id is not
        yet set (pre-registration), facade creation should be deferred.
        """
        from aim_node.core.auth import AuthService
        auth = AuthService(config)
        client = MarketClient(config, auth_service=auth)
        node_id = config.node_id
        if not node_id:
            raise ValueError(
                "node_id not set in config — complete node registration first. "
                "node_serial is a local identifier; node_id is the backend-assigned UUID."
            )
        return cls(client, node_id=node_id)

    async def get(
        self,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        cache_ttl_s: Optional[float] = None,
    ) -> dict[str, Any]:
        """GET request with optional TTL cache. Raises FacadeError on failure."""
        if cache_ttl_s is not None:
            cache_key = f"GET:{path}:{params}"
            cached = self._get_cache(cache_key)
            if cached is not None:
                return cached

        result = await self._request("GET", path, params=params)

        if cache_ttl_s is not None:
            self._set_cache(cache_key, result, cache_ttl_s)
        return result

    async def post(
        self,
        path: str,
        *,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """POST request. Never cached."""
        return await self._request("POST", path, json_body=json_body)

    async def put(
        self,
        path: str,
        *,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return await self._request("PUT", path, json_body=json_body)

    async def delete(self, path: str) -> dict[str, Any]:
        return await self._request("DELETE", path)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        _is_retry: bool = False,
    ) -> dict[str, Any]:
        """Execute request with retry-on-401, normalize errors to FacadeError.

        Gate 1 M2 compliance: On 401, refresh the bearer token via AuthService
        and retry the request exactly once. If the retry also fails, raise FacadeError.
        """
        try:
            return await self.client._request(
                method, path, params=params, json_body=json_body
            )
        except MarketClientHTTPError as exc:
            # Retry-on-401: refresh token and retry once (Gate 1 M2)
            if exc.status_code == 401 and not _is_retry and self.client.auth_service:
                try:
                    await self.client.auth_service.refresh()
                except Exception:
                    pass  # Refresh failed — fall through to original 401 handling
                else:
                    return await self._request(
                        method, path, params=params, json_body=json_body, _is_retry=True
                    )
            # Non-2xx backend response → Section 5.3 passthrough
            normalized = make_market_error(exc.status_code, str(exc), path)
            raise FacadeError(normalized, 502) from exc
        except MarketClientError as exc:
            # Network/connectivity failure
            err_str = str(exc)
            if "timeout" in err_str.lower():
                normalized = make_error(
                    ErrorCode.MARKET_TIMEOUT,
                    f"Marketplace request timed out: {path}",
                )
                raise FacadeError(normalized, 504) from exc
            else:
                normalized = make_error(
                    ErrorCode.MARKET_UNREACHABLE,
                    f"Cannot reach marketplace: {path}",
                    suggested_action="Check your internet connection and API URL in Settings",
                )
                raise FacadeError(normalized, 502) from exc
        except AuthError as exc:
            normalized = make_error(
                ErrorCode.AUTH_FAILED,
                f"Marketplace authentication failed: {exc}",
                suggested_action="Re-enter your API key in Settings",
            )
            raise FacadeError(normalized, 401) from exc

    def _get_cache(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if time.monotonic() > expires_at:
            del self._cache[key]
            return None
        return payload

    def _set_cache(self, key: str, payload: Any, ttl_s: float) -> None:
        self._cache[key] = (time.monotonic() + ttl_s, payload)

    def invalidate_cache(self, prefix: str = "") -> None:
        """Remove all cache entries matching key prefix. Empty prefix clears all."""
        if not prefix:
            self._cache.clear()
        else:
            for key in list(self._cache.keys()):
                if key.startswith(prefix):
                    del self._cache[key]
```



**Required config change (Slice C prerequisite):**

Add `node_id` to `AIMCoreConfig` in `aim_node/core/config.py`:

```python
@dataclass
class AIMCoreConfig:
    keystore_path: Path
    node_serial: str
    market_api_url: str = "https://api.ai.market"
    market_ws_url: str = "wss://api.ai.market/ws"
    data_dir: Path = field(default_factory=lambda: Path.home() / ".aim-node")
    reconnect_delay_s: float = 5.0
    reconnect_max_delay_s: float = 60.0
    reconnect_jitter: float = 0.3
    api_key: str | None = None
    node_id: str | None = None  # Backend-assigned UUID, set after registration
```

`node_id` is populated by the registration flow (BQ-AIM-NODE-SETUP-WIZARD) which calls `POST /aim/nodes/register` and receives `{node_id, node_serial}`. The config writer stores `node_id` at that point. Until registration, `node_id` is `None` and the facade cannot be created.

**Notes:**
- `MarketClient._request` is currently a private method. Facade calls it directly — acceptable since both live in aim-node and MarketClient owns the auth retry logic. If `MarketClient` is refactored, update facade.
- Cache key includes `params` stringified — not collision-proof for complex params, but sufficient for the simple query dicts in these routes.
- `node_id` is stored on the facade for auto-injection into backend paths (`/aim/nodes/{self.node_id}/...`).

### C.2 New File: `aim_node/management/marketplace.py`

Concrete route handlers for all 14 facade endpoints from Section 4.1. Each handler follows the same pattern:

```python
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from aim_node.management.errors import ERROR_HTTP_STATUS
from aim_node.management.facade import FacadeError


def _facade(request: Request):
    """Retrieve the shared MarketplaceFacade from app state."""
    return request.app.state.facade


async def marketplace_node(request: Request) -> JSONResponse:
    """GET /api/mgmt/marketplace/node — proxies GET /aim/nodes/mine"""
    facade = _facade(request)
    try:
        data = await facade.get("/aim/nodes/mine", cache_ttl_s=30.0)
    except FacadeError as exc:
        return JSONResponse(
            exc.normalized.model_dump(exclude_none=True), status_code=exc.http_status
        )
    return JSONResponse(data)


async def marketplace_tools_list(request: Request) -> JSONResponse:
    """GET /api/mgmt/marketplace/tools — proxies GET /aim/nodes/{id}/tools"""
    facade = _facade(request)
    try:
        data = await facade.get(
            f"/aim/nodes/{facade.node_id}/tools", cache_ttl_s=30.0
        )
    except FacadeError as exc:
        return JSONResponse(
            exc.normalized.model_dump(exclude_none=True), status_code=exc.http_status
        )
    return JSONResponse(data)


async def marketplace_tools_publish(request: Request) -> JSONResponse:
    """POST /api/mgmt/marketplace/tools/publish — proxies POST /aim/nodes/{id}/tools/publish"""
    facade = _facade(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        data = await facade.post(
            f"/aim/nodes/{facade.node_id}/tools/publish", json_body=body
        )
    except FacadeError as exc:
        return JSONResponse(
            exc.normalized.model_dump(exclude_none=True), status_code=exc.http_status
        )
    facade.invalidate_cache(f"GET:/aim/nodes/{facade.node_id}/tools")
    return JSONResponse(data)


async def marketplace_tool_update(request: Request) -> JSONResponse:
    """PUT /api/mgmt/marketplace/tools/{tool_id} — proxies PUT /aim/nodes/{id}/tools/{tool_id}"""
    tool_id = request.path_params["tool_id"]
    facade = _facade(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        data = await facade.put(
            f"/aim/nodes/{facade.node_id}/tools/{tool_id}", json_body=body
        )
    except FacadeError as exc:
        return JSONResponse(
            exc.normalized.model_dump(exclude_none=True), status_code=exc.http_status
        )
    facade.invalidate_cache(f"GET:/aim/nodes/{facade.node_id}/tools")
    return JSONResponse(data)


async def marketplace_tool_delete(request: Request) -> JSONResponse:
    """DELETE /api/mgmt/marketplace/tools/{tool_id} — proxies DELETE /aim/nodes/{id}/tools/{tool_id}"""
    tool_id = request.path_params["tool_id"]
    facade = _facade(request)
    try:
        data = await facade.delete(
            f"/aim/nodes/{facade.node_id}/tools/{tool_id}"
        )
    except FacadeError as exc:
        return JSONResponse(
            exc.normalized.model_dump(exclude_none=True), status_code=exc.http_status
        )
    facade.invalidate_cache(f"GET:/aim/nodes/{facade.node_id}/tools")
    return JSONResponse(data)


async def marketplace_earnings(request: Request) -> JSONResponse:
    """GET /api/mgmt/marketplace/earnings — proxies GET /aim/payouts/summary"""
    facade = _facade(request)
    range_param = request.query_params.get("range", "7d")
    try:
        data = await facade.get(
            "/aim/payouts/summary",
            params={"node_id": facade.node_id, "range": range_param},
            cache_ttl_s=60.0,
        )
    except FacadeError as exc:
        return JSONResponse(
            exc.normalized.model_dump(exclude_none=True), status_code=exc.http_status
        )
    return JSONResponse(data)


async def marketplace_earnings_history(request: Request) -> JSONResponse:
    """GET /api/mgmt/marketplace/earnings/history — proxies GET /aim/payouts/history"""
    facade = _facade(request)
    try:
        data = await facade.get("/aim/payouts/history", cache_ttl_s=60.0)
    except FacadeError as exc:
        return JSONResponse(
            exc.normalized.model_dump(exclude_none=True), status_code=exc.http_status
        )
    return JSONResponse(data)


async def marketplace_sessions(request: Request) -> JSONResponse:
    """GET /api/mgmt/marketplace/sessions — proxies GET /aim/sessions (no cache)"""
    facade = _facade(request)
    range_param = request.query_params.get("range", "7d")
    try:
        data = await facade.get(
            "/aim/sessions",
            params={"node_id": facade.node_id, "range": range_param},
        )
    except FacadeError as exc:
        return JSONResponse(
            exc.normalized.model_dump(exclude_none=True), status_code=exc.http_status
        )
    return JSONResponse(data)


async def marketplace_settlements(request: Request) -> JSONResponse:
    """GET /api/mgmt/marketplace/settlements — proxies GET /aim/settlements"""
    facade = _facade(request)
    range_param = request.query_params.get("range", "30d")
    try:
        data = await facade.get(
            "/aim/settlements",
            params={"node_id": facade.node_id, "range": range_param},
            cache_ttl_s=60.0,
        )
    except FacadeError as exc:
        return JSONResponse(
            exc.normalized.model_dump(exclude_none=True), status_code=exc.http_status
        )
    return JSONResponse(data)


async def marketplace_trust(request: Request) -> JSONResponse:
    """GET /api/mgmt/marketplace/trust — proxies GET /aim/nodes/{id}/trust (cache 5m)"""
    facade = _facade(request)
    try:
        data = await facade.get(
            f"/aim/nodes/{facade.node_id}/trust", cache_ttl_s=300.0
        )
    except FacadeError as exc:
        return JSONResponse(
            exc.normalized.model_dump(exclude_none=True), status_code=exc.http_status
        )
    return JSONResponse(data)


async def marketplace_trust_events(request: Request) -> JSONResponse:
    """GET /api/mgmt/marketplace/trust/events — proxies GET /aim/nodes/{id}/trust/events"""
    facade = _facade(request)
    try:
        data = await facade.get(
            f"/aim/nodes/{facade.node_id}/trust/events", cache_ttl_s=300.0
        )
    except FacadeError as exc:
        return JSONResponse(
            exc.normalized.model_dump(exclude_none=True), status_code=exc.http_status
        )
    return JSONResponse(data)


async def marketplace_traces(request: Request) -> JSONResponse:
    """GET /api/mgmt/marketplace/traces — proxies GET /aim/observability/traces"""
    facade = _facade(request)
    limit = request.query_params.get("limit", "50")
    try:
        data = await facade.get(
            "/aim/observability/traces",
            params={"node_id": facade.node_id, "limit": limit},
        )
    except FacadeError as exc:
        return JSONResponse(
            exc.normalized.model_dump(exclude_none=True), status_code=exc.http_status
        )
    return JSONResponse(data)


async def marketplace_listings(request: Request) -> JSONResponse:
    """GET /api/mgmt/marketplace/listings — proxies GET /listings"""
    facade = _facade(request)
    try:
        data = await facade.get(
            "/listings",
            params={"node_id": facade.node_id},
            cache_ttl_s=30.0,
        )
    except FacadeError as exc:
        return JSONResponse(
            exc.normalized.model_dump(exclude_none=True), status_code=exc.http_status
        )
    return JSONResponse(data)


async def marketplace_discover(request: Request) -> JSONResponse:
    """POST /api/mgmt/marketplace/discover — proxies POST /aim/discover/search"""
    facade = _facade(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        data = await facade.post("/aim/discover/search", json_body=body)
    except FacadeError as exc:
        return JSONResponse(
            exc.normalized.model_dump(exclude_none=True), status_code=exc.http_status
        )
    return JSONResponse(data)


# NOTE: allAI endpoint (/marketplace/allai) is NOT included in Gate 2.
# Gate 1 requires redaction before forwarding and context injection (Section 6).
# A raw passthrough stub would violate Gate 1 M3. This endpoint is deferred to
# BQ-AIM-NODE-ALLAI-COPILOT which owns the full redaction/injection logic.
```

### C.3 Update `aim_node/management/app.py` — Register Facade Routes & Lifecycle

**Add marketplace routes to `_routes()`:**

```python
from aim_node.management.marketplace import (
    marketplace_node,
    marketplace_tools_list,
    marketplace_tools_publish,
    marketplace_tool_update,
    marketplace_tool_delete,
    marketplace_earnings,
    marketplace_earnings_history,
    marketplace_sessions,
    marketplace_settlements,
    marketplace_trust,
    marketplace_trust_events,
    marketplace_traces,
    marketplace_listings,
    marketplace_discover,
)

# Append to _routes() return value:
Route("/api/mgmt/marketplace/node", marketplace_node, methods=["GET"]),
Route("/api/mgmt/marketplace/tools", marketplace_tools_list, methods=["GET"]),
Route("/api/mgmt/marketplace/tools/publish", marketplace_tools_publish, methods=["POST"]),
Route("/api/mgmt/marketplace/tools/{tool_id}", marketplace_tool_update, methods=["PUT"]),
Route("/api/mgmt/marketplace/tools/{tool_id}", marketplace_tool_delete, methods=["DELETE"]),
Route("/api/mgmt/marketplace/earnings", marketplace_earnings, methods=["GET"]),
Route("/api/mgmt/marketplace/earnings/history", marketplace_earnings_history, methods=["GET"]),
Route("/api/mgmt/marketplace/sessions", marketplace_sessions, methods=["GET"]),
Route("/api/mgmt/marketplace/settlements", marketplace_settlements, methods=["GET"]),
Route("/api/mgmt/marketplace/trust", marketplace_trust, methods=["GET"]),
Route("/api/mgmt/marketplace/trust/events", marketplace_trust_events, methods=["GET"]),
Route("/api/mgmt/marketplace/traces", marketplace_traces, methods=["GET"]),
Route("/api/mgmt/marketplace/listings", marketplace_listings, methods=["GET"]),
Route("/api/mgmt/marketplace/discover", marketplace_discover, methods=["POST"]),
```

**Note on route ordering:** Starlette matches routes in registration order. `/marketplace/tools/publish` MUST be registered before `/marketplace/tools/{tool_id}` to prevent `publish` from being captured as a `tool_id`.

**Add facade lifecycle to lifespan:**

```python
from aim_node.management.facade import MarketplaceFacade
from aim_node.core.config import AIMCoreConfig

# In lifespan, after store and process_mgr:
try:
    raw_config = read_config(data_dir)
    core_cfg = _load_core_config(raw_config)  # new helper, see below
    app.state.facade = MarketplaceFacade.create(core_cfg)
except Exception:
    # Config may not exist yet during setup wizard — facade unavailable
    app.state.facade = None
    logger.info("MarketplaceFacade not initialized — node not yet configured")
```

Add private helper in `app.py`:
```python
def _load_core_config(raw: dict) -> Optional["AIMCoreConfig"]:
    """Return AIMCoreConfig if config is valid, else None."""
    from aim_node.config_loader import load_config
    try:
        return load_config(raw)
    except Exception:
        return None
```

Facade routes must guard against `app.state.facade is None`:
```python
# Add to each handler in marketplace.py before facade.get():
if (facade := _facade(request)) is None:
    from aim_node.management.errors import make_error, ErrorCode
    err = make_error(ErrorCode.SETUP_INCOMPLETE, "Node not yet configured")
    return JSONResponse(err.model_dump(exclude_none=True), status_code=412)
```

### C.4 Cache TTL Summary

| Endpoint | TTL | Rationale |
|----------|-----|-----------|
| `/marketplace/node` | 30s | Registration state changes infrequently |
| `/marketplace/tools` | 30s | Published tools change on explicit action |
| `/marketplace/earnings` | 60s | Rollup lag > 1min acceptable |
| `/marketplace/earnings/history` | 60s | Historical, stable |
| `/marketplace/sessions` | none | Real-time |
| `/marketplace/settlements` | 60s | Historical, stable |
| `/marketplace/trust` | 300s | Trust score is slow-changing |
| `/marketplace/trust/events` | 300s | Same |
| `/marketplace/traces` | none | Real-time |
| `/marketplace/listings` | 30s | Changes on publish/archive |
| `/marketplace/discover` | none | Search results vary by query |

### C.5 New Packages Required

None. `httpx` is already a dependency. TTL cache uses `time.monotonic()` from stdlib.

### C.6 Tests

**File:** `tests/test_facade.py` (new)

Unit tests (mock `MarketClient._request`):
- `test_facade_get_injects_bearer_auth` — assert auth headers are present in mocked call
- `test_facade_cache_hit_skips_request` — second call within TTL returns cached, no new HTTP call
- `test_facade_cache_miss_after_ttl` — after TTL expires, new HTTP call is made
- `test_facade_market_error_wraps_to_facade_error` — `MarketClientHTTPError(403, ...)` → `FacadeError` with `code == "market_error"`
- `test_facade_network_error_wraps_to_market_unreachable` — `MarketClientError` (no "timeout") → `code == "market_unreachable"`
- `test_facade_timeout_wraps_to_market_timeout` — `MarketClientError("...timeout...")` → `code == "market_timeout"`
- `test_make_market_error_passthrough_shape`
- `test_facade_retry_on_401_refreshes_and_succeeds` — first call returns 401, mock refresh succeeds, retry returns 200
- `test_facade_retry_on_401_refresh_fails_raises` — first call returns 401, refresh raises, FacadeError with auth_failed
- `test_facade_no_double_retry_on_401` — second 401 after refresh does not retry again — `details.status`, `details.backend_error`, `details.endpoint` all present
- `test_facade_invalidate_cache_clears_prefix` — publish call invalidates tools cache entry

**File:** `tests/test_marketplace_routes.py` (new)

Integration tests (Starlette `TestClient`, mock `app.state.facade`):
- `test_marketplace_node_returns_backend_response` — mock facade.get returns dict, handler returns 200
- `test_marketplace_node_facade_error_normalized` — mock raises FacadeError, handler returns correct status + normalized body
- `test_marketplace_tools_publish_invalidates_cache` — publish calls `invalidate_cache`
- `test_marketplace_facade_none_returns_412` — `app.state.facade = None` → 412 + `setup_incomplete`
- `test_marketplace_discover_uses_post_to_backend` — verify discover calls `facade.post` not `facade.get`
- `test_marketplace_trust_cache_ttl_300` — verify cache_ttl_s=300.0 is passed for trust endpoint

### C.7 Done Criteria

- All 14 facade routes registered and routable
- `MarketplaceFacade.create()` wired in app lifespan
- Each route returns backend response on success, `FacadeError` shape on failure
- Cache TTLs match Section 4.2 table exactly
- `publish` route before `{tool_id}` route to avoid path collision
- Bearer token injected automatically via `AuthService` — no token exposure to UI
- Backend URL never appears in facade responses to UI
- `app.state.facade is None` handled with 412 on all marketplace routes
- All C.6 tests pass

---

## Slice D: OpenAPI & Documentation (est 2h)

### D.1 New File: `docs/openapi-facade.yaml`

OpenAPI 3.1 fragment for all 14 aim-node facade endpoints (Section 4.1). Full spec — not just stubs.

**Structure:**

```yaml
openapi: "3.1.0"
info:
  title: AIM Node Facade API
  version: "0.1.0"
  description: >
    aim-node management API facade endpoints. UI calls these; node proxies to ai-market-backend.
    All endpoints under /api/mgmt/marketplace/*.

components:
  securitySchemes:
    csrf:
      type: apiKey
      in: header
      name: X-CSRF-Token
      description: Issued via GET /api/mgmt/health response header.
  schemas:
    ErrorResponse:
      type: object
      required: [code, message]
      properties:
        code: { type: string, enum: [setup_incomplete, node_locked, auth_failed, ...] }
        message: { type: string }
        details: { type: object, nullable: true }
        retryable: { type: boolean, nullable: true }
        request_id: { type: string, nullable: true }
        suggested_action: { type: string, nullable: true }

paths:
  /api/mgmt/marketplace/node:
    get:
      summary: Get seller's registered node details
      description: Proxies GET /aim/nodes/mine on ai-market-backend.
      security: [{ csrf: [] }]
      responses:
        "200": { description: Node details, content: { application/json: { schema: { type: object } } } }
        "412": { $ref: '#/components/responses/SetupIncomplete' }
        "502": { $ref: '#/components/responses/MarketError' }

  /api/mgmt/marketplace/tools:
    get:
      summary: List published tools
      description: Proxies GET /aim/nodes/{id}/tools. Cached 30s.
      # ... responses

  /api/mgmt/marketplace/tools/publish:
    post:
      summary: Publish a tool to the marketplace
      # requestBody with tool schema
      # responses: 200, 412, 502

  /api/mgmt/marketplace/tools/{tool_id}:
    put:
      summary: Update tool metadata
      parameters: [{name: tool_id, in: path, required: true, schema: {type: string}}]
      # ...
    delete:
      summary: Archive a tool (soft delete)
      # ...

  # ... all 15 endpoints
```

**Reusable responses to define:**
- `SetupIncomplete` — 412, `code: setup_incomplete`
- `MarketError` — 502, `code: market_error`, with `details.status`, `details.backend_error`
- `MarketUnreachable` — 502, `code: market_unreachable`
- `MarketTimeout` — 504, `code: market_timeout`
- `CsrfRejected` — 403, `code: csrf_rejected`

All 14 path entries must be present. Use `$ref` for error responses.

### D.2 New File: `docs/openapi-backend-gaps.yaml`

OpenAPI 3.1 fragment for the 9 new endpoints needed on ai-market-backend (Section 2.1 "Gaps" column). This is a spec for the backend team, not for aim-node.

**Endpoints to document:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/aim/nodes/mine` | GET | Authenticated seller's nodes |
| `/aim/nodes/{id}/tools` | GET | List published tools |
| `/aim/nodes/{id}/tools/{tool_id}` | PUT | Update tool metadata |
| `/aim/nodes/{id}/tools/{tool_id}` | DELETE | Archive tool |
| `/aim/sessions` | GET | Session history with `?node_id=&range=` filter |
| `/aim/settlements` | GET | Settlement records with `?node_id=&range=` filter |
| `/aim/payouts/summary` | GET | Rollup with `?node_id=&group_by=day` |
| `/aim/observability/traces` | GET | Trace feed with `?node_id=&limit=` filter |
| `/listings` | GET | Listings with `?node_id=` filter |


Each entry must include: parameters, request body (if any), response schema (200 + error cases), auth requirement (`Bearer` or `X-API-Key`).

**Format:**
```yaml
openapi: "3.1.0"
info:
  title: ai-market-backend — AIM Node UI Gaps
  version: "0.1.0"
  description: >
    New endpoints required on ai-market-backend to support aim-node UI.
    All require Bearer token auth unless noted.

paths:
  /aim/nodes/mine:
    get:
      summary: Get authenticated seller's node registrations
      security: [{bearerAuth: []}]
      responses:
        "200":
          content:
            application/json:
              schema:
                type: object
                properties:
                  nodes:
                    type: array
                    items:
                      type: object
                      required: [node_id, public_key, endpoint_url, status]
                      properties:
                        node_id: {type: string}
                        public_key: {type: string}
                        endpoint_url: {type: string}
                        status: {type: string, enum: [active, inactive]}
  # ... all 10
```

### D.3 Update `README.md` — Auth Chain Section

Add a new section "## Auth Chain" to the existing `README.md` (find and insert after the existing "## Setup" section or near the top-level architecture description).

**Content to add:**

```markdown
## Auth Chain

### UI → Node (Management Plane)

The UI exclusively talks to the aim-node management API (`/api/mgmt/*`). It never calls
ai-market-backend directly.

**CSRF protection** (loopback access):
- Fetch `GET /api/mgmt/health` → read `X-CSRF-Token` response header
- Include `X-CSRF-Token: <token>` on all POST/PUT/DELETE requests
- Alternatively, requests from `Origin: http://localhost:*` pass without CSRF token

**Remote access** (`--host 0.0.0.0`):
- Session token issued on first request from localhost (Gate 1 M1)
- Token delivered via `Set-Cookie: aim_session` and in response body
- Subsequent requests from any origin must include `X-Session-Token` header or `aim_session` cookie

### Node → Backend (Marketplace Plane)

aim-node authenticates to ai-market-backend with a two-step flow:

1. **API Key Exchange**: `POST /auth/token` with `X-API-Key: {key}` → receives `access_token` + `refresh_token`
2. **Bearer Token**: All subsequent calls use `Authorization: Bearer {access_token}`
3. **Refresh**: On 401, node calls `POST /auth/refresh` with `Authorization: Bearer {refresh_token}`
4. **Token storage**: `{data_dir}/auth_token.json` (never exposed to UI or browser)

The UI never sees the API key, bearer token, or private key. The node facade injects
auth headers transparently.

### Auth per Endpoint Family

| Endpoint Family | Method | Notes |
|----------------|--------|-------|
| `/auth/token` | X-API-Key | Initial exchange only |
| `/auth/refresh` | Bearer (refresh token) | On access token expiry |
| `/aim/nodes/register/*` | X-API-Key + Ed25519 signature | Challenge-response |
| `/aim/nodes/{id}/tools/*` | Bearer | node_id claim required |
| `/aim/sessions/*` | Bearer | node_id + session_id |
| `/aim/metering/events` | Bearer + Ed25519 signed payload | Integrity guarantee |
| `/aim/payouts/*`, `/aim/settlements/*` | Bearer | seller_id claim |
| `/aim/discover/*` | Bearer (buyer) or public | search is unauthenticated |
| `/aim/nodes/{id}/trust*` | Bearer | |
| `/aim/observability/*` | Bearer | |
| `/allie/chat/agentic` | Bearer (via API key) | allAI proxy |
```

### D.4 Done Criteria

- `docs/openapi-facade.yaml` — all 14 facade paths present, ErrorResponse schema referenced, CSRF security scheme defined
- `docs/openapi-backend-gaps.yaml` — all 9 backend gap endpoints present with parameters, response schemas, and auth requirements
- `README.md` — "Auth Chain" section present with loopback/remote-bind flows and per-family auth table
- YAML files are valid OpenAPI 3.1 (run `python3 -c "import yaml; yaml.safe_load(open('docs/openapi-facade.yaml'))"` to spot-check syntax)
- No prose padding — every entry has actionable schema detail

---

## Cross-Slice Dependencies

```
Slice A (errors.py)  ─────────────────────────────► Slice B (middleware.py imports errors)
Slice A (errors.py)  ─────────────────────────────► Slice C (facade.py imports errors)
Slice B (app.py changes) + Slice C (app.py changes) ─► must be merged without conflict
Slice D has no code dependencies — can be done in parallel with A/B/C
```

**Recommended delivery order:** A → B → C → D (or A+D in parallel with B+C).

**Merge conflict risk:** Both B and C modify `app.py`. Assign to same builder or coordinate via a shared PR.

---

## Files Created / Modified Summary

| File | Action | Slice |
|------|--------|-------|
| `aim_node/management/errors.py` | **Create** | A |
| `aim_node/management/schemas.py` | **Modify** (ErrorResponse alias) | A |
| `aim_node/management/app.py` | **Modify** (handlers, middleware, facade lifecycle) | A+B+C |
| `aim_node/management/routes.py` | **Modify** (inline errors + health CSRF header) | A+B |
| `aim_node/management/middleware.py` | **Create** | B |
| `aim_node/management/facade.py` | **Create** | C |
| `aim_node/management/marketplace.py` | **Create** | C |
| `aim_node/cli.py` | **Modify** (default host, session token) | B |
| `docs/openapi-facade.yaml` | **Create** | D |
| `docs/openapi-backend-gaps.yaml` | **Create** | D |
| `README.md` | **Modify** (auth chain section) | D |
| `tests/test_errors.py` | **Create** | A |
| `tests/test_middleware.py` | **Create** | B |
| `tests/test_facade.py` | **Create** | C |
| `tests/test_marketplace_routes.py` | **Create** | C |
| `tests/test_management_api.py` | **Extend** | A |
| `tests/test_cli.py` | **Extend** | B |

**New packages required:** None.

---

## Gate 2 Done Criteria (All Slices)

1. All management API errors conform to Section 5.1 format — `code`, `message`, optional fields
2. Every error code from Section 5.2 present in `ERROR_HTTP_STATUS` dict
3. `GET /api/mgmt/health` returns `X-CSRF-Token` header and `csrf_token` in body
4. POST/PUT/DELETE without valid origin or CSRF token returns 403 + `code: csrf_rejected`
5. `aim-node serve` defaults to `--host 127.0.0.1`; `--host 0.0.0.0` enforces session token
6. All 15 marketplace facade routes registered and returning normalized responses
7. Facade caching matches Section 4.2 TTL values exactly
8. Backend errors wrapped as `market_error` per Section 5.3
9. `app.state.facade is None` when not yet configured — returns 412 not 500
10. `docs/openapi-facade.yaml` and `docs/openapi-backend-gaps.yaml` exist and are valid YAML
11. Auth chain documented in README
12. All new test files pass (`python3 -m pytest tests/test_errors.py tests/test_middleware.py tests/test_facade.py tests/test_marketplace_routes.py -v`)
