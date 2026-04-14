"""Starlette app factory for the management HTTP API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from aim_node.management.config_writer import read_config
from aim_node.management.errors import (
    ErrorCode,
    HTTP_STATUS_TO_CODE,
    make_error,
)
from aim_node.management.facade import MarketplaceFacade
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
    provider_health,
    provider_start,
    provider_stop,
    session_detail,
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
        Route("/api/mgmt/provider/health", provider_health, methods=["GET"]),
        Route("/api/mgmt/consumer/start", consumer_start, methods=["POST"]),
        Route("/api/mgmt/consumer/stop", consumer_stop, methods=["POST"]),
        Route("/api/mgmt/sessions", sessions_list, methods=["GET"]),
        Route(
            "/api/mgmt/sessions/{session_id}", session_detail, methods=["GET"]
        ),
        Route("/api/mgmt/unlock", unlock, methods=["POST"]),
        Route("/api/mgmt/keypair", keypair_info, methods=["GET"]),
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
    ]


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

    @asynccontextmanager
    async def lifespan(app: Starlette):
        state = ProcessStateStore(data_dir)
        process_mgr = ProcessManager(state, data_dir)
        app.state.store = state
        app.state.process_mgr = process_mgr
        app.state.remote_bind = remote_bind
        app.state.session_token = None
        try:
            raw_config = read_config(data_dir)
            core_cfg = _load_core_config(raw_config)
            if core_cfg is None:
                raise ValueError("invalid config")
            app.state.facade = MarketplaceFacade.create(core_cfg)
        except Exception:
            app.state.facade = None
            logger.info("MarketplaceFacade not initialized — node not yet configured")
        try:
            yield
        finally:
            try:
                await process_mgr.shutdown()
            except Exception:  # pragma: no cover
                logger.exception("Error during management shutdown")

    routes: list = list(_routes())

    # Static files placeholder (Slice 3 fills this in)
    frontend_dir = data_dir / "frontend"
    if frontend_dir.exists():
        routes.append(Mount("/static", app=StaticFiles(directory=str(frontend_dir))))

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
    app.add_middleware(CSRFMiddleware)
    return app
