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

logger = logging.getLogger(__name__)


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
    ]


async def _precondition_handler(request: Request, exc: PreconditionError) -> JSONResponse:
    return JSONResponse({"error": str(exc) or "Precondition failed"}, status_code=412)


async def _locked_handler(request: Request, exc: LockedError) -> JSONResponse:
    return JSONResponse({"error": str(exc) or "Node locked"}, status_code=423)


async def _already_running_handler(request: Request, exc: AlreadyRunningError) -> JSONResponse:
    return JSONResponse({"error": str(exc) or "Already running"}, status_code=409)


async def _not_running_handler(request: Request, exc: NotRunningError) -> JSONResponse:
    return JSONResponse({"error": str(exc) or "Not running"}, status_code=409)


async def _file_exists_handler(request: Request, exc: FileExistsError) -> JSONResponse:
    return JSONResponse({"error": str(exc) or "Already exists"}, status_code=409)


async def _validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    errors = exc.errors(include_url=False, include_context=False, include_input=False)
    return JSONResponse({"error": errors}, status_code=422)


async def _config_error_handler(request: Request, exc: ConfigError) -> JSONResponse:
    return JSONResponse({"error": str(exc) or "Config error"}, status_code=500)


async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    # Catch-all for stray ValueError from route logic. Should be rare after
    # ConfigError introduction; pydantic ValidationError is handled separately (422).
    return JSONResponse({"error": str(exc)}, status_code=400)


async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


def create_management_app(data_dir: Path) -> Starlette:
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
    }

    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        exception_handlers=exception_handlers,
    )
    return app
