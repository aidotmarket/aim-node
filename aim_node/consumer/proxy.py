from __future__ import annotations

import json
import os
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
import uvicorn

from aim_node.consumer.session_manager import SessionInvokeError, SessionManager
from aim_node.core.config import AIMCoreConfig

MAX_BODY_BYTES = 32 * 1024
DEFAULT_HOST = "127.0.0.1"


class LocalProxy:
    """
    Local HTTP server on 127.0.0.1:8400 that proxies buyer requests to AIM sessions.
    """

    def __init__(self, config: AIMCoreConfig, session_manager: SessionManager, host: str = DEFAULT_HOST):
        self.config = config
        self._session_manager = session_manager
        self._host = host
        self._port = int(os.environ.get("AIM_NODE_PORT", "8400"))
        self._app: Starlette | None = self._build_app()
        self._server: uvicorn.Server | None = None
        self._server_task = None

    async def start(self) -> None:
        """Build ASGI app with routes, start uvicorn."""
        if self._server is not None:
            return
        app = self._app or self._build_app()
        self._app = app
        server_config = uvicorn.Config(
            app,
            host=self._host,
            port=self._port,
            log_level="warning",
            loop="asyncio",
        )
        self._server = uvicorn.Server(server_config)
        import asyncio

        self._server_task = asyncio.create_task(self._server.serve())

    async def stop(self) -> None:
        """Shutdown server."""
        if self._server is None:
            return
        self._server.should_exit = True
        if self._server_task is not None:
            await self._server_task
        self._server = None
        self._server_task = None

    def _build_app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/aim/invoke/{session_id}", self._invoke, methods=["POST"]),
                Route("/aim/sessions/connect", self._connect, methods=["POST"]),
                Route("/aim/sessions", self._list_sessions, methods=["GET"]),
                Route("/aim/sessions/{session_id}", self._session_detail, methods=["GET", "DELETE"]),
                Route("/aim/marketplace/search", self._market_search, methods=["GET"]),
                Route("/aim/marketplace/listings/{listing_id}", self._market_listing, methods=["GET"]),
            ]
        )

    async def _invoke(self, request: Request) -> Response:
        content_type = request.headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            return JSONResponse({"error": "unsupported media type"}, status_code=415)

        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return JSONResponse({"error": "request body too large"}, status_code=413)

        try:
            json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        session_id = request.path_params["session_id"]
        try:
            response_body, headers = await self._session_manager.invoke(session_id, body)
        except SessionInvokeError as exc:
            return JSONResponse({"error": exc.message, "code": exc.code}, status_code=self._map_status(exc.code))

        return Response(response_body, media_type="application/json", headers=headers, status_code=200)

    async def _connect(self, request: Request) -> Response:
        payload = await request.json()
        session = await self._session_manager.connect(
            listing_id=str(payload["listing_id"]),
            max_spend_cents=int(payload["max_spend_cents"]),
        )
        return JSONResponse(
            {
                "session_id": session["session_id"],
                "connection_mode": session["connection_mode"],
                "endpoint_url": session["endpoint_url"],
                "expires_at": session["expires_at"],
            },
            status_code=200,
        )

    async def _list_sessions(self, request: Request) -> Response:
        return JSONResponse(await self._session_manager.list_sessions(), status_code=200)

    async def _session_detail(self, request: Request) -> Response:
        session_id = request.path_params["session_id"]
        if request.method == "GET":
            session = await self._session_manager.get_session(session_id)
            if session is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            return JSONResponse(session, status_code=200)
        await self._session_manager.close_session(session_id)
        return Response(status_code=204)

    async def _market_search(self, request: Request) -> Response:
        query = request.query_params.get("q", "")
        results = await self._session_manager._market_client.search_listings(query)
        return JSONResponse(results, status_code=200)

    async def _market_listing(self, request: Request) -> Response:
        listing_id = request.path_params["listing_id"]
        listing = await self._session_manager._market_client.get_listing(listing_id)
        return JSONResponse(listing, status_code=200)

    @staticmethod
    def _map_status(code: int) -> int:
        if code == 1000:
            return 502
        if code == 1001:
            return 502
        if code == 1002:
            return 502
        if code == 1003:
            return 401
        if code == 1004:
            return 410
        if code == 1005:
            return 429
        if code == 1006:
            return 502
        if code == 1007:
            return 504
        if code == 1008:
            return 413
        if code == 1009:
            return 499
        if code == 1010:
            return 503
        return 502
