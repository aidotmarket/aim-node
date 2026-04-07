from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand


@dataclass(frozen=True)
class TrafficKeys:
    """Holds derived per-direction traffic keys after handshake."""

    buyer_to_seller_key: bytes
    seller_to_buyer_key: bytes
    buyer_to_seller_nonce_prefix: bytes
    seller_to_buyer_nonce_prefix: bytes


def derive_traffic_keys(shared_secret: bytes, session_id: str) -> TrafficKeys:
    """
    Derive per-direction traffic keys from an X25519 shared secret.
    """
    session_id_bytes = session_id.encode("utf-8")
    prk = hmac.new(session_id_bytes, shared_secret, hashlib.sha256).digest()

    def expand(info: bytes, length: int) -> bytes:
        return HKDFExpand(
            algorithm=SHA256(),
            length=length,
            info=info,
        ).derive(prk)

    return TrafficKeys(
        buyer_to_seller_key=expand(b"AIM/1.0 buyer-to-seller key", 32),
        seller_to_buyer_key=expand(b"AIM/1.0 seller-to-buyer key", 32),
        buyer_to_seller_nonce_prefix=expand(b"AIM/1.0 buyer-to-seller nonce", 4),
        seller_to_buyer_nonce_prefix=expand(b"AIM/1.0 seller-to-buyer nonce", 4),
    )


def build_nonce(direction_prefix: bytes, sequence_number: int) -> bytes:
    """Build a 12-byte nonce: 4-byte prefix + 8-byte sequence number."""
    if len(direction_prefix) != 4:
        raise ValueError("nonce prefix must be exactly 4 bytes")
    if sequence_number < 0 or sequence_number > 0xFFFFFFFFFFFFFFFF:
        raise ValueError("sequence number must fit in uint64")
    return direction_prefix + sequence_number.to_bytes(8, "big")


def encrypt_frame(
    key: bytes,
    nonce_prefix: bytes,
    sequence_number: int,
    frame_type: int,
    plaintext: bytes,
) -> bytes:
    """
    Encrypt and encode a relay frame.
    """
    if len(key) != 32:
        raise ValueError("key must be exactly 32 bytes")
    if frame_type < 0 or frame_type > 0xFF:
        raise ValueError("frame_type must fit in uint8")
    if len(plaintext) > 0xFFFF:
        raise ValueError("plaintext too large for uint16 length field")

    header = (
        len(plaintext).to_bytes(2, "big")
        + frame_type.to_bytes(1, "big")
        + sequence_number.to_bytes(8, "big")
    )
    nonce = build_nonce(nonce_prefix, sequence_number)
    ciphertext = ChaCha20Poly1305(key).encrypt(nonce, plaintext, header)
    return header + ciphertext


def decrypt_frame(
    key: bytes,
    nonce_prefix: bytes,
    raw_frame: bytes,
) -> tuple[int, int, bytes]:
    """
    Parse and decrypt a relay frame.
    """
    if len(key) != 32:
        raise ValueError("key must be exactly 32 bytes")
    if len(raw_frame) < 27:
        raise ValueError("frame too short")

    header = raw_frame[:11]
    plaintext_length = int.from_bytes(header[:2], "big")
    frame_type = header[2]
    sequence_number = int.from_bytes(header[3:11], "big")
    ciphertext = raw_frame[11:]

    if len(ciphertext) < 16:
        raise ValueError("frame missing authentication tag")

    nonce = build_nonce(nonce_prefix, sequence_number)
    try:
        plaintext = ChaCha20Poly1305(key).decrypt(nonce, ciphertext, header)
    except InvalidTag as exc:
        raise ValueError("frame authentication failed") from exc

    if len(plaintext) != plaintext_length:
        raise ValueError("plaintext length mismatch")

    return frame_type, sequence_number, plaintext


class SequenceTracker:
    """Strict monotonic sequence enforcement per spec S2.6."""

    def __init__(self) -> None:
        self._next_expected = 0

    def validate_and_advance(self, sequence_number: int) -> None:
        """Raise ValueError if the sequence is not the next expected value."""
        if sequence_number != self._next_expected:
            raise ValueError(
                f"unexpected sequence number: got {sequence_number}, expected {self._next_expected}"
            )
        self._next_expected += 1

    @property
    def next_sequence(self) -> int:
        """Return the next sequence number to use for sending."""
        return self._next_expected
