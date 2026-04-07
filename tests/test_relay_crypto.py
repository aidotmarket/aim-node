from __future__ import annotations

import pytest

from aim_node.core.relay_crypto import (
    SequenceTracker,
    build_nonce,
    decrypt_frame,
    derive_traffic_keys,
    encrypt_frame,
)


def test_derive_traffic_keys_produces_different_per_direction_keys() -> None:
    keys = derive_traffic_keys(b"\x01" * 32, "session-1")

    assert len(keys.buyer_to_seller_key) == 32
    assert len(keys.seller_to_buyer_key) == 32
    assert len(keys.buyer_to_seller_nonce_prefix) == 4
    assert len(keys.seller_to_buyer_nonce_prefix) == 4
    assert keys.buyer_to_seller_key != keys.seller_to_buyer_key
    assert keys.buyer_to_seller_nonce_prefix != keys.seller_to_buyer_nonce_prefix


def test_derive_traffic_keys_deterministic() -> None:
    first = derive_traffic_keys(b"\x02" * 32, "session-2")
    second = derive_traffic_keys(b"\x02" * 32, "session-2")

    assert first == second


def test_derive_traffic_keys_different_sessions_different_keys() -> None:
    first = derive_traffic_keys(b"\x03" * 32, "session-a")
    second = derive_traffic_keys(b"\x03" * 32, "session-b")

    assert first != second


def test_build_nonce_length_12_bytes() -> None:
    nonce = build_nonce(b"ABCD", 7)

    assert len(nonce) == 12
    assert nonce == b"ABCD" + (7).to_bytes(8, "big")


def test_encrypt_decrypt_roundtrip() -> None:
    keys = derive_traffic_keys(b"\x04" * 32, "session-4")
    plaintext = b"relay payload"

    frame = encrypt_frame(
        keys.buyer_to_seller_key,
        keys.buyer_to_seller_nonce_prefix,
        0,
        3,
        plaintext,
    )

    frame_type, sequence_number, decrypted = decrypt_frame(
        keys.buyer_to_seller_key,
        keys.buyer_to_seller_nonce_prefix,
        frame,
    )

    assert frame_type == 3
    assert sequence_number == 0
    assert decrypted == plaintext


def test_decrypt_tampered_ciphertext_fails() -> None:
    keys = derive_traffic_keys(b"\x05" * 32, "session-5")
    frame = encrypt_frame(
        keys.buyer_to_seller_key,
        keys.buyer_to_seller_nonce_prefix,
        1,
        9,
        b"tamper test",
    )
    tampered = frame[:-1] + bytes([frame[-1] ^ 0x01])

    with pytest.raises(ValueError, match="authentication failed"):
        decrypt_frame(
            keys.buyer_to_seller_key,
            keys.buyer_to_seller_nonce_prefix,
            tampered,
        )


def test_decrypt_wrong_key_fails() -> None:
    correct = derive_traffic_keys(b"\x06" * 32, "session-6")
    wrong = derive_traffic_keys(b"\x07" * 32, "session-6")
    frame = encrypt_frame(
        correct.buyer_to_seller_key,
        correct.buyer_to_seller_nonce_prefix,
        2,
        1,
        b"wrong key test",
    )

    with pytest.raises(ValueError, match="authentication failed"):
        decrypt_frame(
            wrong.buyer_to_seller_key,
            correct.buyer_to_seller_nonce_prefix,
            frame,
        )


def test_sequence_tracker_strict_monotonic() -> None:
    tracker = SequenceTracker()

    assert tracker.next_sequence == 0
    tracker.validate_and_advance(0)
    assert tracker.next_sequence == 1
    tracker.validate_and_advance(1)
    tracker.validate_and_advance(2)
    assert tracker.next_sequence == 3

    with pytest.raises(ValueError, match="got 0, expected 3"):
        tracker.validate_and_advance(0)

    with pytest.raises(ValueError, match="got 5, expected 3"):
        tracker.validate_and_advance(5)
