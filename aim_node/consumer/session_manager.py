from __future__ import annotations

import asyncio
import base64
import os
import re
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519

from aim_node.core.config import AIMCoreConfig
from aim_node.core.crypto import DeviceCrypto
from aim_node.core.handshake import HandshakeManager
from aim_node.core.market_client import MarketClient
from aim_node.relay.protocol import RequestPayload
from aim_node.relay.transport import RelayTransport

KEEPALIVE_INTERVAL_S = 240
DEFAULT_INVOKE_TIMEOUT_S = 30.0
DEFAULT_INVOKE_TIMEOUT_MS = 30_000
_ERROR_CODE_RE = re.compile(r"^\s*(\d+):\s*(.*)$")


class SessionInvokeError(Exception):
    """Invocation failure with AIM protocol error code semantics."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class SessionState:
    session_id: str
    connection_mode: str
    endpoint_url: str | None
    session_token: str | None
    transport: RelayTransport | None
    expires_at: str
    created_at: float
    request_count: int = 0


class SessionManager:
    """
    Manages buyer-side sessions: direct and relay.
    """

    def __init__(self, config: AIMCoreConfig, market_client: MarketClient):
        self.config = config
        self._market_client = market_client
        self._sessions: dict[str, SessionState] = {}
        self._keepalive_tasks: dict[str, asyncio.Task[Any]] = {}

    async def connect(self, listing_id: str, max_spend_cents: int) -> dict[str, Any]:
        payload = await self._market_client.negotiate_session(
            listing_id=listing_id,
            buyer_node_id=self.config.node_serial,
            spend_cap_cents=max_spend_cents,
            session_type="consumer",
        )

        session_id = self._require_str(payload, "session_id")
        connection_mode = self._require_str(payload, "connection_mode")
        expires_at = self._require_str(payload, "expires_at")
        endpoint_url = self._optional_str(payload, "endpoint_url")
        session_token = self._optional_str(payload, "session_token")
        transport: RelayTransport | None = None

        if connection_mode == "relay":
            relay_url = self._require_str(payload, "relay_url")
            provider_node_id = self._require_str(payload, "provider_node_id")
            provider_pubkey_b64 = self._require_str(payload, "provider_ed25519_pubkey")
            provider_pubkey = ed25519.Ed25519PublicKey.from_public_bytes(
                base64.b64decode(provider_pubkey_b64.encode("ascii"), validate=True)
            )
            transport = RelayTransport(self.config, self._build_handshake_manager())
            await transport.connect(
                relay_url=relay_url,
                session_id=session_id,
                peer_node_id=provider_node_id,
                peer_ed25519_pubkey=provider_pubkey,
                is_initiator=True,
            )
        elif connection_mode != "direct":
            raise ValueError(f"unsupported connection_mode: {connection_mode}")

        state = SessionState(
            session_id=session_id,
            connection_mode=connection_mode,
            endpoint_url=endpoint_url,
            session_token=session_token,
            transport=transport,
            expires_at=expires_at,
            created_at=time.time(),
        )
        self._sessions[session_id] = state
        self._keepalive_tasks[session_id] = asyncio.create_task(self._keepalive_loop(session_id))
        return self._session_to_dict(state)

    async def invoke(self, session_id: str, body: bytes) -> tuple[bytes, dict[str, str]]:
        state = self._sessions.get(session_id)
        if state is None:
            raise SessionInvokeError(1004, "session expired")

        state.request_count += 1
        trace_id = str(uuid.uuid4())
        sequence = state.request_count

        if state.connection_mode == "direct":
            return await self._invoke_direct(state, body, trace_id, sequence)
        if state.connection_mode == "relay" and state.transport is not None:
            return await self._invoke_relay(state, body, trace_id, sequence)
        raise SessionInvokeError(1010, "session closing")

    async def close_session(self, session_id: str) -> None:
        state = self._sessions.pop(session_id, None)
        task = self._keepalive_tasks.pop(session_id, None)
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        try:
            await self._market_client.close_session(session_id)
        finally:
            if state is not None and state.transport is not None:
                with suppress(Exception):
                    await state.transport.close(reason="buyer_requested")

    async def list_sessions(self) -> list[dict[str, Any]]:
        return [self._session_to_dict(state) for state in self._sessions.values()]

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        state = self._sessions.get(session_id)
        if state is None:
            return None
        return self._session_to_dict(state)

    async def _keepalive_loop(self, session_id: str) -> None:
        try:
            while session_id in self._sessions:
                await asyncio.sleep(KEEPALIVE_INTERVAL_S)
                if session_id not in self._sessions:
                    break
                await self._market_client.keepalive_session(session_id)
        except asyncio.CancelledError:
            raise

    async def _invoke_direct(
        self,
        state: SessionState,
        body: bytes,
        trace_id: str,
        sequence: int,
    ) -> tuple[bytes, dict[str, str]]:
        if state.endpoint_url is None:
            raise SessionInvokeError(1010, "session closing")

        headers = {"Content-Type": "application/json"}
        if state.session_token:
            headers["Authorization"] = f"Bearer {state.session_token}"

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_INVOKE_TIMEOUT_S) as client:
                response = await client.post(state.endpoint_url, content=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise SessionInvokeError(1007, "adapter timeout") from exc
        except httpx.HTTPError as exc:
            raise SessionInvokeError(1006, f"adapter error: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code == 429:
            raise SessionInvokeError(1005, "rate limited")
        if response.status_code == 413:
            raise SessionInvokeError(1008, "request too large")
        if response.status_code == 499:
            raise SessionInvokeError(1009, "cancelled")
        if response.status_code >= 500:
            raise SessionInvokeError(1006, f"adapter HTTP {response.status_code}")

        response_headers = {
            "X-AIM-Trace-Id": response.headers.get("X-AIM-Trace-Id", trace_id),
            "X-AIM-Latency-Ms": response.headers.get("X-AIM-Latency-Ms", str(latency_ms)),
            "X-AIM-Sequence": response.headers.get("X-AIM-Sequence", str(sequence)),
        }
        return response.content, response_headers

    async def _invoke_relay(
        self,
        state: SessionState,
        body: bytes,
        trace_id: str,
        sequence: int,
    ) -> tuple[bytes, dict[str, str]]:
        assert state.transport is not None
        try:
            response = await state.transport.send_request(
                RequestPayload(
                    trace_id=trace_id,
                    sequence=sequence,
                    content_type="application/json",
                    body=body,
                    timeout_ms=DEFAULT_INVOKE_TIMEOUT_MS,
                )
            )
        except RuntimeError as exc:
            match = _ERROR_CODE_RE.match(str(exc))
            if match:
                raise SessionInvokeError(int(match.group(1)), match.group(2) or "session invoke failed") from exc
            raise SessionInvokeError(1006, str(exc) or "session invoke failed") from exc

        headers = {
            "X-AIM-Trace-Id": response.trace_id,
            "X-AIM-Latency-Ms": str(response.latency_ms),
            "X-AIM-Sequence": str(response.sequence),
        }
        return response.body, headers

    def _build_handshake_manager(self) -> HandshakeManager:
        passphrase = os.environ.get("AIM_KEYSTORE_PASSPHRASE", "")
        crypto = DeviceCrypto(self.config, passphrase=passphrase)
        ed_priv, ed_pub, _, _ = crypto.get_or_create_keypairs()
        return HandshakeManager(self.config.node_serial, ed_priv, ed_pub)

    @staticmethod
    def _session_to_dict(state: SessionState) -> dict[str, Any]:
        return {
            "session_id": state.session_id,
            "connection_mode": state.connection_mode,
            "endpoint_url": state.endpoint_url,
            "session_token": state.session_token,
            "expires_at": state.expires_at,
            "created_at": state.created_at,
            "request_count": state.request_count,
        }

    @staticmethod
    def _require_str(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"missing required field: {key}")
        return value

    @staticmethod
    def _optional_str(payload: dict[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"invalid field: {key}")
        return value
