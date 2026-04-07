from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)

APP_VERSION = os.environ.get("AIM_NODE_VERSION", "dev")
SERVICE_NAME = "aim-node"

_startup_time: float = time.time()


def get_uptime_s() -> float:
    return time.time() - _startup_time


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
            "service": SERVICE_NAME,
            "version": APP_VERSION,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        request_id = request_id_var.get()
        correlation_id = correlation_id_var.get()
        session_id = session_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        if correlation_id:
            payload["correlation_id"] = correlation_id
        if session_id:
            payload["session_id"] = session_id

        return json.dumps(payload, ensure_ascii=True)


def setup_logging(
    log_dir: str | os.PathLike[str] = "logs",
    log_file: str = "aim-node.jsonl",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    log_level: int = logging.INFO,
) -> None:
    os.makedirs(log_dir, exist_ok=True)
    log_path = Path(log_dir) / log_file
    formatter = JsonFormatter()

    try:
        file_handler: logging.Handler | None = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
    except OSError:
        file_handler = None

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(log_level)
    root.addHandler(console_handler)
    if file_handler:
        root.addHandler(file_handler)

    for noisy in ("httpcore", "httpx", "urllib3", "asyncio", "watchfiles", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
