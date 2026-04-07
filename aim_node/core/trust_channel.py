from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Awaitable, Callable

import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

try:
    from websockets.exceptions import InvalidStatus
except ImportError:  # pragma: no cover
    InvalidStatus = ConnectionClosedError  # type: ignore[assignment]

from .config import AIMCoreConfig

logger = logging.getLogger(__name__)

ActionHandler = Callable[[dict[str, Any]], Awaitable[None]]
SESSION_NEGOTIATE_ACTION = "SESSION_NEGOTIATE"


class TrustChannelError(Exception):
    """Raised for trust-channel failures."""


class TrustChannelClient:
    """Persistent websocket client for ai.market trust-channel events."""

    def __init__(self, config: AIMCoreConfig) -> None:
        self.config = config
        self._handlers: dict[str, ActionHandler] = {}
        self._waiters: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._receive_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._send_lock = asyncio.Lock()
        self._ws: Any | None = None
        self._running = False
        self._reconnect_delay_s = config.reconnect_delay_s
        self._reconnect_max_delay_s = config.reconnect_max_delay_s
        self._reconnect_jitter = config.reconnect_jitter
        self._ws_url = config.market_ws_url.rstrip("/")
        self.buyer_node_id: str | None = None
        self.buyer_ed25519_pubkey: str | None = None

        self.register_handler(SESSION_NEGOTIATE_ACTION, self._handle_session_negotiate)

    @property
    def ws_url(self) -> str:
        return self._ws_url

    @property
    def reconnect_delay_s(self) -> float:
        return self._reconnect_delay_s

    @property
    def reconnect_max_delay_s(self) -> float:
        return self._reconnect_max_delay_s

    @property
    def reconnect_jitter(self) -> float:
        return self._reconnect_jitter

    def register_handler(self, action: str, handler: ActionHandler) -> None:
        self._handlers[action] = handler

    async def send(self, message: dict[str, Any]) -> None:
        if self._ws is None:
            raise TrustChannelError("trust channel not connected")

        async with self._send_lock:
            await self._ws.send(json.dumps(message))

    async def receive(self, timeout: float | None = None) -> dict[str, Any]:
        if timeout is None:
            return await self._receive_queue.get()
        return await asyncio.wait_for(self._receive_queue.get(), timeout=timeout)

    async def wait_for_action(
        self, action: str, transfer_id: str, timeout: float = 30.0
    ) -> dict[str, Any]:
        waiter_key = f"{action}:{transfer_id}"
        future = asyncio.get_running_loop().create_future()
        self._waiters[waiter_key] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"Timed out waiting for {action} (transfer_id={transfer_id})"
            ) from exc
        finally:
            self._waiters.pop(waiter_key, None)

    async def run(self) -> None:
        self._running = True
        backoff = self._reconnect_delay_s

        while self._running:
            try:
                await self._connect_and_listen()
                backoff = self._reconnect_delay_s
            except (ConnectionClosed, ConnectionClosedError, OSError) as exc:
                logger.warning("Trust channel disconnected: %s", exc)
            except InvalidStatus as exc:
                status_code = getattr(exc, "status_code", None)
                logger.error("Trust channel rejected connection: %s", status_code)
            except Exception as exc:  # pragma: no cover
                logger.exception("Trust channel unexpected error: %s", exc)

            if not self._running:
                break

            sleep_for = min(backoff, self._reconnect_max_delay_s)
            if self._reconnect_jitter > 0:
                sleep_for += random.uniform(0.0, self._reconnect_jitter)
            await asyncio.sleep(sleep_for)
            backoff = min(backoff * 2, self._reconnect_max_delay_s)

    async def stop(self) -> None:
        self._running = False
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

        for future in self._waiters.values():
            if not future.done():
                future.cancel()

    async def _connect_and_listen(self) -> None:
        headers = {"X-Node-Serial": self.config.node_serial}
        if self.config.api_key:
            headers["X-API-Key"] = self.config.api_key

        async with websockets.connect(
            self._ws_url,
            additional_headers=headers,
            ping_interval=30,
            ping_timeout=10,
            max_size=2 * 1024 * 1024,
        ) as ws:
            self._ws = ws
            async for raw_message in ws:
                message = self._parse_message(raw_message)
                if message is None:
                    continue
                await self._dispatch_message(message)

        self._ws = None

    def _parse_message(self, raw_message: Any) -> dict[str, Any] | None:
        try:
            if isinstance(raw_message, bytes):
                raw_message = raw_message.decode("utf-8")
            return json.loads(raw_message)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            logger.warning("Discarding malformed trust-channel message")
            return None

    async def _dispatch_message(self, message: dict[str, Any]) -> None:
        action = str(message.get("action", ""))
        transfer_id = str(message.get("transfer_id", ""))
        waiter_key = f"{action}:{transfer_id}"
        waiter = self._waiters.get(waiter_key)
        if waiter is not None and not waiter.done():
            waiter.set_result(message)
            return

        handler = self._handlers.get(action)
        if handler is not None:
            asyncio.create_task(self._safe_handle(action, handler, message))

        await self._receive_queue.put(message)

    async def _safe_handle(
        self, action: str, handler: ActionHandler, message: dict[str, Any]
    ) -> None:
        try:
            await handler(message)
        except Exception as exc:  # pragma: no cover
            logger.exception("Trust-channel handler failed for %s: %s", action, exc)

    async def _handle_session_negotiate(self, message: dict[str, Any]) -> None:
        payload = message.get("payload")
        if isinstance(payload, dict):
            source = payload
        else:
            source = message

        self.buyer_node_id = source.get("buyer_node_id")
        self.buyer_ed25519_pubkey = source.get("buyer_ed25519_pubkey")
