from __future__ import annotations

import base64

import pytest

from aim_node.core.crypto import DeviceCrypto
from aim_node.core.handshake import (
    HandshakeManager,
    HandshakeState,
)


def _new_manager(node_id: str) -> tuple[HandshakeManager, object, object]:
    priv, pub = DeviceCrypto.generate_ed25519_keypair()
    return HandshakeManager(node_id, priv, pub), priv, pub


def test_create_init_generates_ephemeral_key() -> None:
    buyer, _, _ = _new_manager("buyer-1")

    init = buyer.create_init("session-1")

    assert buyer._eph_private is not None
    assert buyer._eph_public is not None
    assert len(base64.b64decode(init.ephemeral_pubkey, validate=True)) == 32


def test_create_init_transitions_to_init_sent() -> None:
    buyer, _, _ = _new_manager("buyer-1")

    buyer.create_init("session-1")

    assert buyer.state is HandshakeState.INIT_SENT


def test_verify_init_valid_signature() -> None:
    buyer, _, buyer_pub = _new_manager("buyer-1")
    seller, _, _ = _new_manager("seller-1")
    init = buyer.create_init("session-1")

    seller.verify_init(init, "session-1", "buyer-1", buyer_pub)

    assert seller.state is HandshakeState.INIT_RECEIVED
    assert seller._peer_eph_public is not None


def test_verify_init_wrong_session_id_fails() -> None:
    buyer, _, buyer_pub = _new_manager("buyer-1")
    seller, _, _ = _new_manager("seller-1")
    init = buyer.create_init("session-1")

    with pytest.raises(ValueError, match="session_id mismatch"):
        seller.verify_init(init, "other-session", "buyer-1", buyer_pub)

    assert seller.state is HandshakeState.FAILED


def test_verify_init_expired_timestamp_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    buyer, _, buyer_pub = _new_manager("buyer-1")
    seller, _, _ = _new_manager("seller-1")
    now_ms = 1_700_000_100_000

    monkeypatch.setattr(HandshakeManager, "_now_ms", staticmethod(lambda: now_ms - 31_000))
    init = buyer.create_init("session-1")
    monkeypatch.setattr(HandshakeManager, "_now_ms", staticmethod(lambda: now_ms))

    with pytest.raises(ValueError, match="timestamp outside allowed window"):
        seller.verify_init(init, "session-1", "buyer-1", buyer_pub)

    assert seller.state is HandshakeState.FAILED


def test_verify_init_wrong_node_id_fails() -> None:
    buyer, _, buyer_pub = _new_manager("buyer-1")
    seller, _, _ = _new_manager("seller-1")
    init = buyer.create_init("session-1")

    with pytest.raises(ValueError, match="initiator_node_id mismatch"):
        seller.verify_init(init, "session-1", "buyer-2", buyer_pub)

    assert seller.state is HandshakeState.FAILED


def test_create_accept_transcript_binding() -> None:
    buyer, _, buyer_pub = _new_manager("buyer-1")
    seller, _, seller_pub = _new_manager("seller-1")
    init = buyer.create_init("session-1")
    seller.verify_init(init, "session-1", "buyer-1", buyer_pub)
    accept = seller.create_accept("session-1", init.ephemeral_pubkey)
    tampered_buyer, _, _ = _new_manager("buyer-2")
    tampered_buyer.create_init("session-1")

    with pytest.raises(ValueError, match="invalid handshake signature"):
        tampered_buyer.verify_accept(accept, seller_pub)

    assert tampered_buyer.state is HandshakeState.FAILED


def test_full_handshake_buyer_seller_roundtrip() -> None:
    buyer, _, buyer_pub = _new_manager("buyer-1")
    seller, _, seller_pub = _new_manager("seller-1")

    init = buyer.create_init("session-1")
    seller.verify_init(init, "session-1", "buyer-1", buyer_pub)
    accept = seller.create_accept("session-1", init.ephemeral_pubkey)
    buyer_result = buyer.verify_accept(accept, seller_pub)
    seller_keys = seller._compute_shared_secret_and_keys(
        base64.b64decode(init.ephemeral_pubkey, validate=True),
        "session-1",
    )

    assert buyer.state is HandshakeState.ESTABLISHED
    assert seller.state is HandshakeState.ESTABLISHED
    assert buyer_result.peer_node_id == "seller-1"
    assert buyer_result.session_id == "session-1"
    assert buyer_result.traffic_keys == seller_keys


def test_full_handshake_different_sessions_different_keys() -> None:
    buyer_one, _, buyer_one_pub = _new_manager("buyer-1")
    seller_one, _, seller_one_pub = _new_manager("seller-1")
    init_one = buyer_one.create_init("session-1")
    seller_one.verify_init(init_one, "session-1", "buyer-1", buyer_one_pub)
    accept_one = seller_one.create_accept("session-1", init_one.ephemeral_pubkey)
    result_one = buyer_one.verify_accept(accept_one, seller_one_pub)

    buyer_two, _, buyer_two_pub = _new_manager("buyer-1")
    seller_two, _, seller_two_pub = _new_manager("seller-1")
    init_two = buyer_two.create_init("session-2")
    seller_two.verify_init(init_two, "session-2", "buyer-1", buyer_two_pub)
    accept_two = seller_two.create_accept("session-2", init_two.ephemeral_pubkey)
    result_two = buyer_two.verify_accept(accept_two, seller_two_pub)

    assert result_one.traffic_keys != result_two.traffic_keys


def test_handshake_state_transitions() -> None:
    buyer, _, buyer_pub = _new_manager("buyer-1")
    seller, _, seller_pub = _new_manager("seller-1")

    assert buyer.state is HandshakeState.IDLE
    assert seller.state is HandshakeState.IDLE

    init = buyer.create_init("session-1")
    assert buyer.state is HandshakeState.INIT_SENT

    seller.verify_init(init, "session-1", "buyer-1", buyer_pub)
    assert seller.state is HandshakeState.INIT_RECEIVED

    accept = seller.create_accept("session-1", init.ephemeral_pubkey)
    assert seller.state is HandshakeState.ESTABLISHED

    buyer.verify_accept(accept, seller_pub)
    assert buyer.state is HandshakeState.ESTABLISHED
