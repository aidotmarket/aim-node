"""Management API log buffering and streaming."""

from __future__ import annotations

import asyncio
import collections
import logging
from datetime import datetime, timezone
from typing import Any, TypedDict
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from aim_node.management.errors import ErrorCode, make_error
from aim_node.management.middleware import _origin_is_loopback

BUFFER_SIZE = 1000
DEFAULT_TAIL_LIMIT = 100
MAX_TAIL_LIMIT = 1000
SUBSCRIBER_QUEUE_SIZE = 100

_STANDARD_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__.keys())
_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class LogEntry(TypedDict):
    timestamp: str
    level: str
    logger: str
    message: str
    extra: dict[str, Any] | None


class RingBufferHandler(logging.Handler):
    """Captures log records into a bounded deque."""

    def __init__(self, *, maxlen: int = BUFFER_SIZE) -> None:
        super().__init__()
        self.buffer: collections.deque[LogEntry] = collections.deque(maxlen=maxlen)
        self.subscribers: list[asyncio.Queue[LogEntry]] = []

    def emit(self, record: logging.LogRecord) -> None:
        entry = self._format_entry(record)
        self.buffer.append(entry)
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(entry)
            except asyncio.QueueFull:
                continue

    def _format_entry(self, record: logging.LogRecord) -> LogEntry:
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_")
        }
        return {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "extra": extra or None,
        }


def install_ring_buffer_handler() -> RingBufferHandler:
    logger = logging.getLogger("aim_node")
    for handler in list(logger.handlers):
        if isinstance(handler, RingBufferHandler):
            logger.removeHandler(handler)
    handler = RingBufferHandler()
    logger.addHandler(handler)
    return handler


def remove_ring_buffer_handler(handler: RingBufferHandler | None) -> None:
    if handler is None:
        return
    logger = logging.getLogger("aim_node")
    if handler in logger.handlers:
        logger.removeHandler(handler)


def _parse_iso8601(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_limit(raw: str | None) -> int:
    if raw in (None, ""):
        return DEFAULT_TAIL_LIMIT
    try:
        limit = int(raw)
    except ValueError as exc:
        raise ValueError("limit must be an integer") from exc
    if limit < 1 or limit > MAX_TAIL_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_TAIL_LIMIT}")
    return limit


def _parse_level(raw: str | None) -> int:
    if not raw:
        return logging.NOTSET
    level_name = raw.upper()
    if level_name not in _LEVELS:
        raise ValueError("level must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL")
    return _LEVELS[level_name]


def _tail_entries(
    handler: RingBufferHandler,
    *,
    level: int = logging.NOTSET,
    limit: int = DEFAULT_TAIL_LIMIT,
    since: datetime | None = None,
) -> list[LogEntry]:
    filtered: list[LogEntry] = []
    for entry in handler.buffer:
        if _LEVELS.get(entry["level"], logging.NOTSET) < level:
            continue
        if since is not None and _parse_iso8601(entry["timestamp"]) < since:
            continue
        filtered.append(entry)
    return filtered[-limit:]


async def logs_tail(request: Request) -> JSONResponse:
    handler: RingBufferHandler = request.app.state.log_handler
    try:
        level = _parse_level(request.query_params.get("level"))
        limit = _parse_limit(request.query_params.get("limit"))
        since_value = request.query_params.get("since")
        since = _parse_iso8601(since_value) if since_value else None
    except ValueError as exc:
        err = make_error(ErrorCode.CONFIG_INVALID, str(exc))
        return JSONResponse(err.model_dump(exclude_none=True), status_code=422)

    return JSONResponse(
        {"entries": _tail_entries(handler, level=level, limit=limit, since=since)}
    )


def _websocket_origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    parsed = urlparse(origin)
    if parsed.scheme != "http":
        return False
    return _origin_is_loopback(origin)


async def _deny_websocket(websocket: WebSocket, code: str, message: str) -> None:
    err = make_error(code, message)
    await websocket.send_denial_response(
        JSONResponse(err.model_dump(exclude_none=True), status_code=403)
    )


async def _record_ws_metric(websocket: WebSocket, *, error: bool) -> None:
    collector = getattr(websocket.app.state, "metrics", None)
    if collector is not None:
        await collector.record_call(latency_ms=0.0, error=error)


async def logs_stream_ws(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    if not _websocket_origin_allowed(origin):
        await _record_ws_metric(websocket, error=True)
        await _deny_websocket(
            websocket,
            ErrorCode.FORBIDDEN,
            "WebSocket Origin must be localhost or 127.0.0.1",
        )
        return

    if getattr(websocket.app.state, "remote_bind", False):
        expected = getattr(websocket.app.state, "session_token", None)
        provided = websocket.query_params.get("session_token")
        if not expected or provided != expected:
            await _record_ws_metric(websocket, error=True)
            await _deny_websocket(
                websocket,
                ErrorCode.FORBIDDEN,
                "Valid session_token query parameter required for remote access",
            )
            return

    handler: RingBufferHandler = websocket.app.state.log_handler
    queue: asyncio.Queue[LogEntry] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
    handler.subscribers.append(queue)

    await websocket.accept()
    await _record_ws_metric(websocket, error=False)
    try:
        while True:
            entry = await queue.get()
            await websocket.send_json(entry)
    except WebSocketDisconnect:
        return
    finally:
        if queue in handler.subscribers:
            handler.subscribers.remove(queue)
