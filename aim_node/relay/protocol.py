from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from typing import Any

FRAME_REQUEST = 0x10
FRAME_RESPONSE = 0x11
FRAME_ERROR = 0x12
FRAME_HEARTBEAT = 0x20
FRAME_HEARTBEAT_ACK = 0x21
FRAME_CANCEL = 0x30
FRAME_CANCEL_ACK = 0x31
FRAME_CLOSE = 0x40
FRAME_CLOSE_ACK = 0x41

_MAX_TIMEOUT_MS = 300_000
_MAX_MESSAGE_LEN = 500


@dataclass
class RequestPayload:
    trace_id: str
    sequence: int
    content_type: str
    body: bytes
    timeout_ms: int


@dataclass
class ResponsePayload:
    trace_id: str
    sequence: int
    content_type: str
    body: bytes
    latency_ms: int


@dataclass
class ErrorPayload:
    trace_id: str | None
    code: int
    message: str


@dataclass
class CancelPayload:
    trace_id: str


@dataclass
class CancelAckPayload:
    trace_id: str
    cancelled: bool


@dataclass
class ClosePayload:
    reason: str
    message: str = ""


def serialize_payload(payload: Any) -> bytes:
    """Serialize a payload dataclass to JSON bytes. Body fields are base64-encoded."""
    if not hasattr(payload, "__dataclass_fields__"):
        raise TypeError("payload must be a dataclass instance")

    _validate_payload(payload)
    raw = asdict(payload)
    if "body" in raw:
        raw["body"] = base64.b64encode(raw["body"]).decode("ascii")
    return json.dumps(raw, separators=(",", ":"), sort_keys=True).encode("utf-8")


def deserialize_payload(frame_type: int, data: bytes) -> Any:
    """Deserialize JSON bytes to the appropriate payload dataclass based on frame_type."""
    if frame_type in {FRAME_HEARTBEAT, FRAME_HEARTBEAT_ACK, FRAME_CLOSE_ACK}:
        if data not in (b"", b"{}", b"null"):
            raise ValueError("control frames must not include a payload")
        return None

    decoded = json.loads(data.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("payload JSON must decode to an object")

    if frame_type == FRAME_REQUEST:
        payload = RequestPayload(
            trace_id=decoded["trace_id"],
            sequence=decoded["sequence"],
            content_type=decoded["content_type"],
            body=_decode_body(decoded["body"]),
            timeout_ms=decoded["timeout_ms"],
        )
    elif frame_type == FRAME_RESPONSE:
        payload = ResponsePayload(
            trace_id=decoded["trace_id"],
            sequence=decoded["sequence"],
            content_type=decoded["content_type"],
            body=_decode_body(decoded["body"]),
            latency_ms=decoded["latency_ms"],
        )
    elif frame_type == FRAME_ERROR:
        payload = ErrorPayload(
            trace_id=decoded.get("trace_id"),
            code=decoded["code"],
            message=decoded["message"],
        )
    elif frame_type == FRAME_CANCEL:
        payload = CancelPayload(trace_id=decoded["trace_id"])
    elif frame_type == FRAME_CANCEL_ACK:
        payload = CancelAckPayload(
            trace_id=decoded["trace_id"],
            cancelled=decoded["cancelled"],
        )
    elif frame_type == FRAME_CLOSE:
        payload = ClosePayload(
            reason=decoded["reason"],
            message=decoded.get("message", ""),
        )
    else:
        raise ValueError(f"unsupported frame type: {frame_type}")

    _validate_payload(payload)
    return payload


def _decode_body(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def _validate_payload(payload: Any) -> None:
    if isinstance(payload, RequestPayload):
        if payload.timeout_ms < 0 or payload.timeout_ms > _MAX_TIMEOUT_MS:
            raise ValueError("timeout_ms must be between 0 and 300000")
    elif isinstance(payload, ErrorPayload):
        if len(payload.message) > _MAX_MESSAGE_LEN:
            raise ValueError("message exceeds 500 characters")
    elif isinstance(payload, ClosePayload):
        if len(payload.message) > _MAX_MESSAGE_LEN:
            raise ValueError("message exceeds 500 characters")
