"""Starlette app factory for the management HTTP API."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from aim_node.management.allai import allai_chat, allai_confirm
from aim_node.management.config_writer import read_config
from aim_node.management.errors import (
    ErrorCode,
    HTTP_STATUS_TO_CODE,
    make_error,
)
from aim_node.management.facade import MarketplaceFacade
from aim_node.management.logs import (
    install_ring_buffer_handler,
    logs_stream_ws,
    logs_tail,
    remove_ring_buffer_handler,
)
from aim_node.management.marketplace import (
    discover,
    earnings_history,
    listings,
    marketplace_earnings,
    marketplace_node,
    marketplace_trust,
    sessions,
    settlements,
    tool_delete,
    tool_update,
    tools_list,
    tools_publish,
    traces,
    trust_events,
)
from aim_node.management.metrics import (
    MetricsCollector,
    MetricsMiddleware,
    metrics_summary,
    metrics_timeseries,
)
from aim_node.management.middleware import CSRFMiddleware
from aim_node.management.process import (
    AlreadyRunningError,
    ConfigError,
    LockedError,
    NotRunningError,
    PreconditionError,
    ProcessManager,
)
from aim_node.management.routes import (
    config_read,
    config_update,
    consumer_start,
    consumer_stop,
    dashboard,
    health,
    keypair_info,
    keypair_rotate,
    lock_node,
    provider_health,
    provider_reload,
    provider_restart,
    provider_start,
    provider_stop,
    session_detail,
    session_kill,
    sessions_list,
    setup_finalize,
    setup_keypair,
    setup_status,
    setup_test_connection,
    unlock,
)
from aim_node.management.state import ProcessStateStore
from aim_node.management.tools import (
    setup_test_upstream,
    tools_detail,
    tools_discover,
    tools_list_local,
    tools_validate,
)

logger = logging.getLogger(__name__)


def _load_core_config(raw: dict) -> "AIMCoreConfig | None":
    from aim_node.config_loader import load_config
    from aim_node.core.config import AIMCoreConfig

    try:
        return load_config(raw)
    except Exception:
        return None


def _routes() -> list[Route]:
    return [
        Route("/api/mgmt/health", health, methods=["GET"]),
        Route("/api/mgmt/setup/status", setup_status, methods=["GET"]),
        Route("/api/mgmt/setup/keypair", setup_keypair, methods=["POST"]),
        Route(
            "/api/mgmt/setup/test-connection",
            setup_test_connection,
            methods=["POST"],
        ),
        Route(
            "/api/mgmt/setup/test-upstream",
            setup_test_upstream,
            methods=["POST"],
        ),
        Route("/api/mgmt/setup/finalize", setup_finalize, methods=["POST"]),
        Route("/api/mgmt/status", dashboard, methods=["GET"]),
        Route("/api/mgmt/config", config_read, methods=["GET"]),
        Route("/api/mgmt/config", config_update, methods=["PUT"]),
        Route("/api/mgmt/provider/start", provider_start, methods=["POST"]),
        Route("/api/mgmt/provider/stop", provider_stop, methods=["POST"]),
        Route("/api/mgmt/provider/restart", provider_restart, methods=["POST"]),
        Route("/api/mgmt/provider/reload", provider_reload, methods=["POST"]),
        Route("/api/mgmt/provider/health", provider_health, methods=["GET"]),
        Route("/api/mgmt/consumer/start", consumer_start, methods=["POST"]),
        Route("/api/mgmt/consumer/stop", consumer_stop, methods=["POST"]),
        Route("/api/mgmt/lock", lock_node, methods=["POST"]),
        Route("/api/mgmt/sessions", sessions_list, methods=["GET"]),
        Route(
            "/api/mgmt/sessions/{session_id}", session_detail, methods=["GET"]
        ),
        Route(
            "/api/mgmt/sessions/{session_id}", session_kill, methods=["DELETE"]
        ),
        Route("/api/mgmt/unlock", unlock, methods=["POST"]),
        Route("/api/mgmt/keypair", keypair_info, methods=["GET"]),
        Route("/api/mgmt/keypair/rotate", keypair_rotate, methods=["POST"]),
        Route("/api/mgmt/logs", logs_tail, methods=["GET"]),
        WebSocketRoute("/api/mgmt/logs/stream", logs_stream_ws),
        Route("/api/mgmt/metrics/summary", metrics_summary, methods=["GET"]),
        Route("/api/mgmt/metrics/timeseries", metrics_timeseries, methods=["GET"]),
        Route("/api/mgmt/tools", tools_list_local, methods=["GET"]),
        Route("/api/mgmt/tools/discover", tools_discover, methods=["POST"]),
        Route("/api/mgmt/tools/{tool_id}", tools_detail, methods=["GET"]),
        Route(
            "/api/mgmt/tools/{tool_id}/validate",
            tools_validate,
            methods=["POST"],
        ),
        Route("/api/mgmt/marketplace/node", marketplace_node, methods=["GET"]),
        Route("/api/mgmt/marketplace/tools", tools_list, methods=["GET"]),
        Route(
            "/api/mgmt/marketplace/tools/publish",
            tools_publish,
            methods=["POST"],
        ),
        Route(
            "/api/mgmt/marketplace/tools/{tool_id}",
            tool_update,
            methods=["PUT"],
        ),
        Route(
            "/api/mgmt/marketplace/tools/{tool_id}",
            tool_delete,
            methods=["DELETE"],
        ),
        Route(
            "/api/mgmt/marketplace/earnings",
            marketplace_earnings,
            methods=["GET"],
        ),
        Route(
            "/api/mgmt/marketplace/earnings/history",
            earnings_history,
            methods=["GET"],
        ),
        Route("/api/mgmt/marketplace/sessions", sessions, methods=["GET"]),
        Route(
            "/api/mgmt/marketplace/settlements",
            settlements,
            methods=["GET"],
        ),
        Route("/api/mgmt/marketplace/trust", marketplace_trust, methods=["GET"]),
        Route(
            "/api/mgmt/marketplace/trust/events",
            trust_events,
            methods=["GET"],
        ),
        Route("/api/mgmt/marketplace/traces", traces, methods=["GET"]),
        Route("/api/mgmt/marketplace/listings", listings, methods=["GET"]),
        Route("/api/mgmt/marketplace/discover", discover, methods=["POST"]),
        Route("/allai/chat", allai_chat, methods=["POST"]),
        Route("/allai/confirm", allai_confirm, methods=["POST"]),
    ]


class StaticCacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/assets/") and response.status_code < 400:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def _spa_fallback_handler(data_dir: Path):
    frontend_dir = Path(data_dir) / "frontend" / "dist"
    index_path = frontend_dir / "index.html"

    async def spa_fallback(request: Request) -> Response:
        path = request.url.path
        if path.startswith("/api/") or path.startswith("/assets/"):
            raise HTTPException(404, "Not found")
        if not index_path.exists():
            raise HTTPException(404, "UI not built")
        return HTMLResponse(
            index_path.read_text(),
            headers={"Cache-Control": "no-cache"},
        )

    return spa_fallback


async def _precondition_handler(request: Request, exc: PreconditionError) -> JSONResponse:
    err = make_error(
        ErrorCode.SETUP_INCOMPLETE,
        str(exc) or "Precondition failed",
        suggested_action="Complete node setup first",
    )
    return JSONResponse(err.model_dump(exclude_none=True), status_code=412)


async def _locked_handler(request: Request, exc: LockedError) -> JSONResponse:
    err = make_error(
        ErrorCode.NODE_LOCKED,
        str(exc) or "Node locked",
        suggested_action="Unlock the node before proceeding",
    )
    return JSONResponse(err.model_dump(exclude_none=True), status_code=423)


async def _already_running_handler(request: Request, exc: AlreadyRunningError) -> JSONResponse:
    err = make_error(ErrorCode.ALREADY_RUNNING, str(exc) or "Already running")
    return JSONResponse(err.model_dump(exclude_none=True), status_code=409)


async def _not_running_handler(request: Request, exc: NotRunningError) -> JSONResponse:
    err = make_error(ErrorCode.NOT_RUNNING, str(exc) or "Not running")
    return JSONResponse(err.model_dump(exclude_none=True), status_code=409)


async def _file_exists_handler(request: Request, exc: FileExistsError) -> JSONResponse:
    err = make_error(ErrorCode.ALREADY_EXISTS, str(exc) or "Already exists")
    return JSONResponse(err.model_dump(exclude_none=True), status_code=409)


async def _validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    errors = exc.errors(include_url=False, include_context=False, include_input=False)
    err = make_error(
        ErrorCode.CONFIG_INVALID,
        "Validation failed",
        details={"fields": errors},
    )
    return JSONResponse(err.model_dump(exclude_none=True), status_code=422)


async def _config_error_handler(request: Request, exc: ConfigError) -> JSONResponse:
    err = make_error(
        ErrorCode.CONFIG_INVALID,
        str(exc) or "Config error",
        suggested_action="Check configuration file",
    )
    return JSONResponse(err.model_dump(exclude_none=True), status_code=422)


async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    # Catch-all for stray ValueError from route logic. Should be rare after
    # ConfigError introduction; pydantic ValidationError is handled separately (422).
    err = make_error(ErrorCode.CONFIG_INVALID, str(exc) or "Invalid configuration")
    return JSONResponse(err.model_dump(exclude_none=True), status_code=422)


async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = HTTP_STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
    err = make_error(code, str(exc.detail) if exc.detail else "Request failed")
    return JSONResponse(err.model_dump(exclude_none=True), status_code=exc.status_code)


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception in management API")
    err = make_error(ErrorCode.INTERNAL_ERROR, "An unexpected error occurred")
    return JSONResponse(err.model_dump(exclude_none=True), status_code=500)


def create_management_app(
    data_dir: Path,
    *,
    remote_bind: bool = False,
) -> Starlette:
    """Create the management Starlette application.

    Lifespan creates a fresh ProcessStateStore and ProcessManager bound to the
    supplied data_dir. Caller is responsible for resetting the singleton
    (ProcessStateStore.reset()) in tests.
    """

    data_dir = Path(data_dir)
    log_handler = install_ring_buffer_handler()
    metrics = MetricsCollector(data_dir)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        state = ProcessStateStore(data_dir)
        process_mgr = ProcessManager(state, data_dir)
        app.state.store = state
        app.state.process_mgr = process_mgr
        app.state.remote_bind = remote_bind
        app.state.session_token = None
        app.state.allai_action_cache = {}
        app.state.log_handler = log_handler
        app.state.metrics = metrics
        try:
            raw_config = read_config(data_dir)
            core_cfg = _load_core_config(raw_config)
            if core_cfg is None:
                raise ValueError("invalid config")
            app.state.facade = MarketplaceFacade.create(core_cfg)
        except Exception:
            app.state.facade = None
            logger.info("MarketplaceFacade not initialized — node not yet configured")
        flush_task = asyncio.create_task(metrics.flush_loop())
        try:
            yield
        finally:
            metrics.sync_active_sessions(len(state.get_sessions()))
            flush_task.cancel()
            try:
                await flush_task
            except asyncio.CancelledError:
                pass
            await metrics.flush()
            remove_ring_buffer_handler(log_handler)
            try:
                await process_mgr.shutdown()
            except Exception:  # pragma: no cover
                logger.exception("Error during management shutdown")

    routes: list = list(_routes())

    frontend_dir = data_dir / "frontend" / "dist"
    if frontend_dir.exists():
        routes.append(
            Mount("/assets", app=StaticFiles(directory=str(frontend_dir / "assets")))
        )
    routes.append(Route("/{path:path}", _spa_fallback_handler(data_dir), methods=["GET"]))

    exception_handlers = {
        PreconditionError: _precondition_handler,
        LockedError: _locked_handler,
        AlreadyRunningError: _already_running_handler,
        NotRunningError: _not_running_handler,
        FileExistsError: _file_exists_handler,
        ConfigError: _config_error_handler,
        ValidationError: _validation_error_handler,
        ValueError: _value_error_handler,
        HTTPException: _http_exception_handler,
        Exception: _unhandled_handler,
    }

    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        exception_handlers=exception_handlers,
    )
    app.state.remote_bind = remote_bind
    app.state.session_token = None
    app.state.facade = None
    app.state.allai_action_cache = {}
    app.state.log_handler = log_handler
    app.state.metrics = metrics
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(StaticCacheControlMiddleware)
    return app
