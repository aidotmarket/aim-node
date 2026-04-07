from __future__ import annotations

import base64
import enum
import time
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519

from .crypto import DeviceCrypto
from .relay_crypto import TrafficKeys, derive_traffic_keys

_MAX_CLOCK_SKEW_MS = 30_000
_PROTOCOL_VERSION = "AIM/1.0"


class HandshakeState(enum.Enum):
    IDLE = "idle"
    INIT_SENT = "init_sent"
    INIT_RECEIVED = "init_received"
    ESTABLISHED = "established"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass
class HandshakeResult:
    """Result of a successful handshake."""

    traffic_keys: TrafficKeys
    peer_node_id: str
    peer_ephemeral_pubkey: bytes
    session_id: str


@dataclass
class HandshakeInitMessage:
    """HANDSHAKE_INIT (buyer -> seller, unencrypted JSON over relay WS)."""

    session_id: str
    initiator_node_id: str
    ephemeral_pubkey: str
    timestamp: int
    signature: str
    protocol_version: str = _PROTOCOL_VERSION


@dataclass
class HandshakeAcceptMessage:
    """HANDSHAKE_ACCEPT (seller -> buyer, unencrypted JSON over relay WS)."""

    session_id: str
    responder_node_id: str
    ephemeral_pubkey: str
    timestamp: int
    signature: str
    protocol_version: str = _PROTOCOL_VERSION


class HandshakeManager:
    """Manages the handshake lifecycle for one relay session."""

    def __init__(
        self,
        node_id: str,
        ed25519_private_key: ed25519.Ed25519PrivateKey,
        ed25519_public_key: ed25519.Ed25519PublicKey,
    ) -> None:
        self.node_id = node_id
        self._ed25519_priv = ed25519_private_key
        self._ed25519_pub = ed25519_public_key
        self.state = HandshakeState.IDLE
        self._eph_private: x25519.X25519PrivateKey | None = None
        self._eph_public: x25519.X25519PublicKey | None = None
        self._peer_eph_public: x25519.X25519PublicKey | None = None
        self._session_id: str | None = None

    def create_init(self, session_id: str) -> HandshakeInitMessage:
        """
        Buyer creates HANDSHAKE_INIT.
        """
        if self.state is not HandshakeState.IDLE:
            raise RuntimeError(f"cannot create init from state {self.state.value}")

        self._eph_private = x25519.X25519PrivateKey.generate()
        self._eph_public = self._eph_private.public_key()
        self._session_id = session_id
        eph_pubkey_b64 = base64.b64encode(self._public_key_bytes(self._eph_public)).decode("ascii")
        timestamp = self._now_ms()
        signature = base64.b64encode(
            DeviceCrypto.sign(
                self._ed25519_priv,
                self._build_init_payload(session_id, self.node_id, eph_pubkey_b64, timestamp),
            )
        ).decode("ascii")
        self.state = HandshakeState.INIT_SENT
        return HandshakeInitMessage(
            session_id=session_id,
            initiator_node_id=self.node_id,
            ephemeral_pubkey=eph_pubkey_b64,
            timestamp=timestamp,
            signature=signature,
        )

    def verify_init(
        self,
        msg: HandshakeInitMessage,
        expected_session_id: str,
        expected_buyer_node_id: str,
        buyer_ed25519_pubkey: ed25519.Ed25519PublicKey,
    ) -> None:
        """
        Seller verifies HANDSHAKE_INIT.
        """
        if self.state is not HandshakeState.IDLE:
            raise RuntimeError(f"cannot verify init from state {self.state.value}")

        try:
            if msg.session_id != expected_session_id:
                raise ValueError("session_id mismatch")
            if msg.initiator_node_id != expected_buyer_node_id:
                raise ValueError("initiator_node_id mismatch")
            self._validate_timestamp(msg.timestamp)
            self._verify_signature(
                buyer_ed25519_pubkey,
                self._build_init_payload(
                    msg.session_id,
                    msg.initiator_node_id,
                    msg.ephemeral_pubkey,
                    msg.timestamp,
                ),
                msg.signature,
            )
            self._peer_eph_public = x25519.X25519PublicKey.from_public_bytes(
                base64.b64decode(msg.ephemeral_pubkey, validate=True)
            )
            self._session_id = msg.session_id
        except Exception:
            self.state = HandshakeState.FAILED
            raise

        self.state = HandshakeState.INIT_RECEIVED

    def create_accept(self, session_id: str, buyer_eph_pubkey_b64: str) -> HandshakeAcceptMessage:
        """
        Seller creates HANDSHAKE_ACCEPT.
        """
        if self.state is not HandshakeState.INIT_RECEIVED:
            raise RuntimeError(f"cannot create accept from state {self.state.value}")
        if self._session_id != session_id:
            raise ValueError("session_id mismatch")

        buyer_eph_public_bytes = base64.b64decode(buyer_eph_pubkey_b64, validate=True)
        if self._peer_eph_public is None:
            self._peer_eph_public = x25519.X25519PublicKey.from_public_bytes(buyer_eph_public_bytes)
        elif self._public_key_bytes(self._peer_eph_public) != buyer_eph_public_bytes:
            self.state = HandshakeState.FAILED
            raise ValueError("buyer ephemeral pubkey mismatch")

        self._eph_private = x25519.X25519PrivateKey.generate()
        self._eph_public = self._eph_private.public_key()
        eph_pubkey_b64 = base64.b64encode(self._public_key_bytes(self._eph_public)).decode("ascii")
        timestamp = self._now_ms()
        signature = base64.b64encode(
            DeviceCrypto.sign(
                self._ed25519_priv,
                self._build_accept_payload(
                    session_id,
                    self.node_id,
                    eph_pubkey_b64,
                    buyer_eph_pubkey_b64,
                    timestamp,
                ),
            )
        ).decode("ascii")

        self._compute_shared_secret_and_keys(buyer_eph_public_bytes, session_id)
        self.state = HandshakeState.ESTABLISHED
        return HandshakeAcceptMessage(
            session_id=session_id,
            responder_node_id=self.node_id,
            ephemeral_pubkey=eph_pubkey_b64,
            timestamp=timestamp,
            signature=signature,
        )

    def verify_accept(
        self,
        msg: HandshakeAcceptMessage,
        seller_ed25519_pubkey: ed25519.Ed25519PublicKey,
    ) -> HandshakeResult:
        """
        Buyer verifies HANDSHAKE_ACCEPT.
        """
        if self.state is not HandshakeState.INIT_SENT:
            raise RuntimeError(f"cannot verify accept from state {self.state.value}")
        if self._eph_public is None or self._session_id is None:
            self.state = HandshakeState.FAILED
            raise ValueError("initiator ephemeral key not initialized")

        buyer_eph_pubkey_b64 = base64.b64encode(self._public_key_bytes(self._eph_public)).decode("ascii")

        try:
            if msg.session_id != self._session_id:
                raise ValueError("session_id mismatch")
            self._validate_timestamp(msg.timestamp)
            self._verify_signature(
                seller_ed25519_pubkey,
                self._build_accept_payload(
                    msg.session_id,
                    msg.responder_node_id,
                    msg.ephemeral_pubkey,
                    buyer_eph_pubkey_b64,
                    msg.timestamp,
                ),
                msg.signature,
            )
            peer_public_bytes = base64.b64decode(msg.ephemeral_pubkey, validate=True)
            self._peer_eph_public = x25519.X25519PublicKey.from_public_bytes(peer_public_bytes)
            traffic_keys = self._compute_shared_secret_and_keys(peer_public_bytes, msg.session_id)
        except Exception:
            self.state = HandshakeState.FAILED
            raise

        self.state = HandshakeState.ESTABLISHED
        return HandshakeResult(
            traffic_keys=traffic_keys,
            peer_node_id=msg.responder_node_id,
            peer_ephemeral_pubkey=peer_public_bytes,
            session_id=msg.session_id,
        )

    def _compute_shared_secret_and_keys(self, peer_eph_public_bytes: bytes, session_id: str) -> TrafficKeys:
        """X25519 DH + derive_traffic_keys()."""
        if self._eph_private is None:
            raise ValueError("local ephemeral key not initialized")
        peer_public = x25519.X25519PublicKey.from_public_bytes(peer_eph_public_bytes)
        shared_secret = self._eph_private.exchange(peer_public)
        return derive_traffic_keys(shared_secret, session_id)

    @staticmethod
    def _build_init_payload(session_id: str, node_id: str, eph_pubkey_b64: str, timestamp: int) -> bytes:
        return "".join(
            [
                "AIM-HANDSHAKE-INIT",
                session_id,
                node_id,
                eph_pubkey_b64,
                str(timestamp),
            ]
        ).encode("utf-8")

    @staticmethod
    def _build_accept_payload(
        session_id: str,
        node_id: str,
        eph_pubkey_b64: str,
        buyer_eph_pubkey_b64: str,
        timestamp: int,
    ) -> bytes:
        return "".join(
            [
                "AIM-HANDSHAKE-ACCEPT",
                session_id,
                node_id,
                eph_pubkey_b64,
                buyer_eph_pubkey_b64,
                str(timestamp),
            ]
        ).encode("utf-8")

    @staticmethod
    def _public_key_bytes(public_key: x25519.X25519PublicKey) -> bytes:
        return public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _validate_timestamp(timestamp: int) -> None:
        if abs(HandshakeManager._now_ms() - timestamp) > _MAX_CLOCK_SKEW_MS:
            raise ValueError("timestamp outside allowed window")

    @staticmethod
    def _verify_signature(
        public_key: ed25519.Ed25519PublicKey,
        payload: bytes,
        signature_b64: str,
    ) -> None:
        try:
            signature = base64.b64decode(signature_b64, validate=True)
            DeviceCrypto.verify(public_key, payload, signature)
        except (InvalidSignature, ValueError) as exc:
            raise ValueError("invalid handshake signature") from exc
