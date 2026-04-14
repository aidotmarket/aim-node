from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient, WebSocketDenialResponse

from aim_node.management.app import create_management_app
from aim_node.management.process import ProcessManager
from aim_node.management.state import ProcessStateStore


@pytest.fixture(autouse=True)
def _reset_state():
    ProcessStateStore.reset()
    os.environ.pop("AIM_KEYSTORE_PASSPHRASE", None)
    yield
    ProcessStateStore.reset()
    os.environ.pop("AIM_KEYSTORE_PASSPHRASE", None)


def _build_app(data_dir: Path, *, remote_bind: bool = False):
    app = create_management_app(data_dir, remote_bind=remote_bind)
    state = ProcessStateStore(data_dir)
    process_mgr = ProcessManager(state, data_dir)
    app.state.store = state
    app.state.process_mgr = process_mgr
    app.state.remote_bind = remote_bind
    app.state.log_handler.buffer.clear()
    app.state.log_handler.subscribers.clear()
    logging.getLogger("aim_node").setLevel(logging.DEBUG)
    return app


def _make_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://localhost"},
    )


def _append_log(app, *, level: str, message: str, timestamp: str | None = None) -> None:
    app.state.log_handler.buffer.append(
        {
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "level": level,
            "logger": "aim_node.management.test",
            "message": message,
            "extra": None,
        }
    )


async def test_logs_tail_empty_returns_empty_list(tmp_path: Path):
    app = _build_app(tmp_path)
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/logs")
    assert response.status_code == 200
    assert response.json() == {"entries": []}


async def test_logs_tail_returns_recent_entries_with_default_limit(tmp_path: Path):
    app = _build_app(tmp_path)
    for index in range(120):
        _append_log(app, level="INFO", message=f"msg-{index}")
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/logs")
    body = response.json()
    assert response.status_code == 200
    assert len(body["entries"]) == 100
    assert body["entries"][0]["message"] == "msg-20"
    assert body["entries"][-1]["message"] == "msg-119"


async def test_logs_tail_limit_query_applies(tmp_path: Path):
    app = _build_app(tmp_path)
    for index in range(5):
        _append_log(app, level="INFO", message=f"entry-{index}")
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/logs?limit=2")
    assert [item["message"] for item in response.json()["entries"]] == [
        "entry-3",
        "entry-4",
    ]


async def test_logs_tail_filters_by_min_level(tmp_path: Path):
    app = _build_app(tmp_path)
    _append_log(app, level="INFO", message="info")
    _append_log(app, level="WARNING", message="warn")
    _append_log(app, level="ERROR", message="error")
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/logs?level=warning")
    assert [item["message"] for item in response.json()["entries"]] == ["warn", "error"]


async def test_logs_tail_filters_by_since(tmp_path: Path):
    app = _build_app(tmp_path)
    now = datetime.now(timezone.utc)
    _append_log(
        app,
        level="INFO",
        message="old",
        timestamp=(now - timedelta(minutes=10)).isoformat(),
    )
    _append_log(
        app,
        level="INFO",
        message="new",
        timestamp=(now - timedelta(seconds=10)).isoformat(),
    )
    async with _make_client(app) as client:
        response = await client.get(
            "/api/mgmt/logs",
            params={"since": (now - timedelta(minutes=1)).isoformat()},
        )
    assert [item["message"] for item in response.json()["entries"]] == ["new"]


async def test_logs_tail_invalid_limit_returns_422(tmp_path: Path):
    app = _build_app(tmp_path)
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/logs?limit=2000")
    assert response.status_code == 422
    assert response.json()["code"] == "config_invalid"


async def test_logs_tail_invalid_since_returns_422(tmp_path: Path):
    app = _build_app(tmp_path)
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/logs?since=not-a-date")
    assert response.status_code == 422
    assert response.json()["code"] == "config_invalid"


def test_ring_buffer_caps_at_1000_entries(tmp_path: Path):
    app = _build_app(tmp_path)
    for index in range(1005):
        _append_log(app, level="INFO", message=f"entry-{index}")
    assert len(app.state.log_handler.buffer) == 1000
    assert app.state.log_handler.buffer[0]["message"] == "entry-5"


def test_logs_websocket_streams_new_entries(tmp_path: Path):
    app = _build_app(tmp_path)
    logger = logging.getLogger("aim_node.management.websocket")
    logger.setLevel(logging.INFO)

    with TestClient(app) as client:
        app.state.log_handler.buffer.clear()
        with client.websocket_connect(
            "/api/mgmt/logs/stream",
            headers={"origin": "http://localhost:3000"},
        ) as websocket:
            logger.info("stream-event", extra={"source": "ws-test"})
            payload = websocket.receive_json()

    assert payload["message"] == "stream-event"
    assert payload["level"] == "INFO"
    assert payload["extra"]["source"] == "ws-test"


def test_logs_websocket_disconnect_removes_subscriber(tmp_path: Path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        app.state.log_handler.buffer.clear()
        with client.websocket_connect(
            "/api/mgmt/logs/stream",
            headers={"origin": "http://localhost:3000"},
        ):
            assert len(app.state.log_handler.subscribers) == 1
        assert app.state.log_handler.subscribers == []


def test_logs_websocket_rejects_non_loopback_origin(tmp_path: Path):
    app = _build_app(tmp_path)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDenialResponse) as exc_info:
            with client.websocket_connect(
                "/api/mgmt/logs/stream",
                headers={"origin": "http://evil.example"},
            ):
                pass
    assert exc_info.value.status_code == 403
    assert exc_info.value.json()["code"] == "forbidden"


def test_logs_websocket_rejects_remote_bind_without_token(tmp_path: Path):
    app = _build_app(tmp_path, remote_bind=True)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDenialResponse) as exc_info:
            with client.websocket_connect(
                "/api/mgmt/logs/stream",
                headers={"origin": "http://localhost:3000"},
            ):
                pass
    assert exc_info.value.status_code == 403
    assert exc_info.value.json()["code"] == "forbidden"


def test_logs_websocket_accepts_remote_bind_with_valid_token(tmp_path: Path):
    app = _build_app(tmp_path, remote_bind=True)
    logger = logging.getLogger("aim_node.management.websocket.auth")
    logger.setLevel(logging.INFO)

    with TestClient(app) as client:
        app.state.session_token = "session-123"
        app.state.log_handler.buffer.clear()
        with client.websocket_connect(
            "/api/mgmt/logs/stream?session_token=session-123",
            headers={"origin": "http://127.0.0.1:4312"},
        ) as websocket:
            logger.info("authorized")
            payload = websocket.receive_json()

    assert payload["message"] == "authorized"


def test_logs_websocket_counts_denied_upgrade_as_metric_error(tmp_path: Path):
    app = _build_app(tmp_path, remote_bind=True)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDenialResponse):
            with client.websocket_connect(
                "/api/mgmt/logs/stream",
                headers={"origin": "http://localhost:3000"},
            ):
                pass
    assert app.state.metrics.total_errors >= 1
    assert app.state.metrics.total_calls >= 1
