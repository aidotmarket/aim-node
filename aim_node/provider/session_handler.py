from __future__ import annotations

import asyncio
import base64
import logging
import os
from contextlib import suppress
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ed25519

from aim_node.core.config import AIMCoreConfig
from aim_node.core.crypto import DeviceCrypto
from aim_node.core.handshake import HandshakeManager
from aim_node.core.trust_channel import TrustChannelClient
from aim_node.relay.protocol import (
    FRAME_CANCEL,
    FRAME_CANCEL_ACK,
    FRAME_ERROR,
    FRAME_REQUEST,
    CancelPayload,
    CancelAckPayload,
    ErrorPayload,
    RequestPayload,
    ResponsePayload,
    deserialize_payload,
    serialize_payload,
)
from aim_node.relay.transport import RelayTransport

from .adapter import AdapterError, HttpJsonAdapter

logger = logging.getLogger(__name__)


class ProviderSessionHandler:
    def __init__(
        self,
        config: AIMCoreConfig,
        adapter: HttpJsonAdapter,
        trust_channel: TrustChannelClient,
    ):
        self.config = config
        self.adapter = adapter
        self._trust_channel = trust_channel
        self._active_sessions: dict[str, RelayTransport] = {}
        self._health_task: asyncio.Task | None = None
        self._session_tasks: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """Start adapter, register SESSION_NEGOTIATE handler on trust channel, start health loop."""
        await self.adapter.start()
        self._trust_channel.register_handler("SESSION_NEGOTIATE", self.on_session_negotiate)
        self._health_task = asyncio.create_task(self._health_loop())

    async def stop(self) -> None:
        """Close all sessions, stop adapter, stop health loop."""
        health_task = self._health_task
        self._health_task = None
        if health_task is not None:
            health_task.cancel()
            with suppress(asyncio.CancelledError):
                await health_task

        session_tasks = list(self._session_tasks.values())
        for task in session_tasks:
            task.cancel()
        for task in session_tasks:
            with suppress(asyncio.CancelledError):
                await task

        sessions = list(self._active_sessions.items())
        self._active_sessions.clear()
        for _, transport in sessions:
            with suppress(Exception):
                await transport.close(reason="provider_shutdown")

        await self.adapter.stop()

    async def on_session_negotiate(self, event: dict) -> None:
        """
        Handle SESSION_NEGOTIATE from trust channel.
        """
        payload = event.get("payload")
        source = payload if isinstance(payload, dict) else event

        self._trust_channel.buyer_node_id = source.get("buyer_node_id")
        self._trust_channel.buyer_ed25519_pubkey = source.get("buyer_ed25519_pubkey")

        if not self.adapter._healthy:
            logger.warning("Rejecting session negotiate while adapter is unhealthy")
            return

        connection_mode = source.get("connection_mode")
        if connection_mode == "direct":
            return
        if connection_mode != "relay":
            logger.warning("Ignoring unsupported connection mode: %s", connection_mode)
            return

        session_id = source.get("session_id")
        relay_url = source.get("relay_url")
        buyer_node_id = source.get("buyer_node_id")
        buyer_pubkey_b64 = source.get("buyer_ed25519_pubkey")
        if not all(isinstance(value, str) and value for value in (session_id, relay_url, buyer_node_id, buyer_pubkey_b64)):
            logger.warning("SESSION_NEGOTIATE missing required relay fields")
            return

        if session_id in self._active_sessions:
            logger.info("Session already active: %s", session_id)
            return

        handshake = self._build_handshake_manager()
        buyer_pubkey = ed25519.Ed25519PublicKey.from_public_bytes(
            base64.b64decode(buyer_pubkey_b64.encode("ascii"), validate=True)
        )
        transport = RelayTransport(self.config, handshake)
        await transport.connect(
            relay_url=relay_url,
            session_id=session_id,
            peer_node_id=buyer_node_id,
            peer_ed25519_pubkey=buyer_pubkey,
            is_initiator=False,
        )
        self._active_sessions[session_id] = transport
        self._session_tasks[session_id] = asyncio.create_task(
            self._process_session(session_id, transport)
        )

    async def _process_session(self, session_id: str, transport: RelayTransport) -> None:
        """
        Receive REQUEST frames, forward to adapter, send RESPONSE/ERROR back.
        """
        try:
            while True:
                frame_type, plaintext = await transport.recv_frame()
                if frame_type == FRAME_REQUEST:
                    payload: RequestPayload | None = None
                    try:
                        payload = deserialize_payload(frame_type, plaintext)
                        if not isinstance(payload, RequestPayload):
                            raise ValueError("request payload decode failed")
                        response_body, latency_ms = await self.adapter.forward_request(payload.body)
                        response = ResponsePayload(
                            trace_id=payload.trace_id,
                            sequence=payload.sequence,
                            content_type="application/json",
                            body=response_body,
                            latency_ms=latency_ms,
                        )
                        await transport.send_response(response)
                    except AdapterError as exc:
                        await transport.send_frame(
                            FRAME_ERROR,
                            serialize_payload(
                                ErrorPayload(
                                    trace_id=getattr(payload, "trace_id", None),
                                    code=exc.code,
                                    message=exc.message,
                                )
                            ),
                        )
                    except Exception as exc:
                        await transport.send_frame(
                            FRAME_ERROR,
                            serialize_payload(
                                ErrorPayload(
                                    trace_id=getattr(payload, "trace_id", None),
                                    code=1001,
                                    message=f"provider: invalid request ({exc})",
                                )
                            ),
                        )
                elif frame_type == FRAME_CANCEL:
                    cancel = deserialize_payload(frame_type, plaintext)
                    cancelled = isinstance(cancel, CancelPayload)
                    trace_id = cancel.trace_id if isinstance(cancel, CancelPayload) else ""
                    await transport.send_frame(
                        FRAME_CANCEL_ACK,
                        serialize_payload(CancelAckPayload(trace_id=trace_id, cancelled=cancelled)),
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("Provider session closed for %s: %s", session_id, exc)
        finally:
            self._session_tasks.pop(session_id, None)
            active = self._active_sessions.pop(session_id, None)
            if active is not None:
                with suppress(Exception):
                    await active.close(reason="connection_drop")

    async def _health_loop(self) -> None:
        """Every 60s: run adapter.health_check()."""
        try:
            while True:
                await self.adapter.health_check()
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise

    def _build_handshake_manager(self) -> HandshakeManager:
        passphrase = os.environ.get("AIM_KEYSTORE_PASSPHRASE", "")
        crypto = DeviceCrypto(self.config, passphrase=passphrase)
        ed_priv, ed_pub, _, _ = crypto.get_or_create_keypairs()
        return HandshakeManager(self.config.node_serial, ed_priv, ed_pub)
