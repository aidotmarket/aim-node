from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Callable

import httpx

from .contracts import CLIENT_METHODS, GatewaySurface, reject_payload_contract_fields


METER_RECORD_CLIENT_METHOD = CLIENT_METHODS[GatewaySurface.METER_RECORD]
METER_LIST_CLIENT_METHOD = CLIENT_METHODS[GatewaySurface.METER_LIST]
METER_RECORD_HTTP_ROUTE = "/v1/gateway/meter"
METER_LIST_HTTP_ROUTE = "/v1/gateway/meter"
METER_RECORD_GRPC_METHOD = "RecordMetering"
METER_LIST_GRPC_METHOD = "ListMetering"


class MeterEventType(StrEnum):
    ACCESS_GRANT = "access_grant"
    INVOCATION = "invocation"
    DELIVERY_FACT = "delivery_fact"
    RECONCILIATION = "reconciliation"


@dataclass(frozen=True)
class MeterMeasures:
    bytes: int = 0
    rows: int = 0
    records: int = 0
    calls: int = 0
    duration_ms: int = 0
    retries: int = 0


@dataclass(frozen=True)
class MeterRecordRequest:
    metadata: dict[str, Any]
    access_grant_id: str
    invocation_id: str
    buyer_account_id: str
    seller_account_id: str
    listing_id: str
    listing_version_id: str
    connector_id: str
    event_type: str
    measures: MeterMeasures
    artifact_hash: str
    occurred_at: str
    seller_edge_identity_hash: str | None = None
    signed_reference: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        reject_payload_contract_fields(list(asdict(self).keys()))
        reject_payload_contract_fields(list(asdict(self.measures).keys()))
        if not self.metadata.get("signed_envelope") and not (
            self.metadata.get("request_timestamp") and self.metadata.get("nonce")
        ):
            raise ValueError("meter events require a signed envelope or timestamp/nonce")
        if self.measures.bytes + self.measures.rows + self.measures.records + self.measures.calls <= 0:
            raise ValueError("METERING_REJECTED: meter event must include evidence measures")


@dataclass(frozen=True)
class MeterEvent:
    meter_event_id: str
    access_grant_id: str
    invocation_id: str
    buyer_account_id: str
    seller_account_id: str
    listing_id: str
    listing_version_id: str
    connector_id: str
    event_type: str
    measures: MeterMeasures
    artifact_hash: str
    occurred_at: str
    accepted_at: str
    state: str = "accepted"
    seller_edge_identity_hash: str | None = None


@dataclass(frozen=True)
class MeterListRequest:
    metadata: dict[str, Any]
    account_id: str
    access_grant_id: str | None = None
    invocation_id: str | None = None
    artifact_hash: str | None = None


class GatewayMeterClient:
    def __init__(self, base_url: str, api_key: str | None = None, client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or httpx.Client()

    def record(self, request: MeterRecordRequest) -> MeterEvent:
        response = self.client.post(
            f"{self.base_url}{METER_RECORD_HTTP_ROUTE}",
            json=_drop_none(asdict(request)),
            headers=self._headers(request.metadata, idempotent=True),
        )
        response.raise_for_status()
        return parse_meter_event(response.json())

    def list(self, request: MeterListRequest) -> list[MeterEvent]:
        reject_payload_contract_fields(list(asdict(request).keys()))
        params = _drop_none(
            {
                "account_id": request.account_id,
                "access_grant_id": request.access_grant_id,
                "invocation_id": request.invocation_id,
                "artifact_hash": request.artifact_hash,
            }
        )
        response = self.client.get(
            f"{self.base_url}{METER_LIST_HTTP_ROUTE}",
            params=params,
            headers=self._headers(request.metadata, idempotent=False),
        )
        response.raise_for_status()
        return [parse_meter_event(item) for item in response.json()]

    def _headers(self, metadata: dict[str, Any], *, idempotent: bool) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "x-request-id": str(_pick(metadata, "request_id", "requestId")),
        }
        idempotency_key = _pick(metadata, "idempotency_key", "idempotencyKey")
        if idempotent and idempotency_key:
            headers["idempotency-key"] = str(idempotency_key)
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return headers


@dataclass(frozen=True)
class MeterBufferPolicy:
    threshold_events: int = 100
    max_events: int = 10_000
    drain_deadline_seconds: int = 300
    fail_closed_policy: str = "fail_closed"


class MeterBufferError(RuntimeError):
    def __init__(self, message: str, state: str) -> None:
        super().__init__(message)
        self.code = "METERING_REJECTED"
        self.state = state


@dataclass
class MeterBufferObservability:
    spans: list[dict[str, object]] = field(default_factory=list)
    metrics: list[dict[str, object]] = field(default_factory=list)


class LocalMeterBuffer:
    def __init__(
        self,
        policy: MeterBufferPolicy | None = None,
        observability: MeterBufferObservability | None = None,
    ) -> None:
        self.policy = policy or MeterBufferPolicy()
        self.observability = observability or MeterBufferObservability()
        self._queue: list[MeterRecordRequest] = []
        self._state = "open"
        self._deadline_started_at: float | None = None
        self._dropped_events = 0

    @property
    def state(self) -> str:
        return self._state

    @property
    def depth(self) -> int:
        return len(self._queue)

    @property
    def dropped_events(self) -> int:
        return self._dropped_events

    def enqueue(self, request: MeterRecordRequest, *, now_seconds: float) -> None:
        if self._state in {"degraded", "fail_closed"}:
            self._rejected("degraded")
            raise MeterBufferError("METERING_REJECTED: local meter buffer is degraded", self._state)
        if (
            self._deadline_started_at is not None
            and now_seconds - self._deadline_started_at > self.policy.drain_deadline_seconds
        ):
            self._state = "fail_closed"
            self._rejected("drain_deadline_missed")
            raise MeterBufferError("METERING_REJECTED: meter_buffer drain deadline missed", self._state)
        if len(self._queue) >= self.policy.max_events:
            self._state = "fail_closed"
            self._dropped_events += 1
            self._rejected("max_depth")
            raise MeterBufferError("METERING_REJECTED: meter_buffer max depth reached", self._state)

        self._queue.append(request)
        if len(self._queue) >= self.policy.threshold_events:
            self._state = "buffering"
            if self._deadline_started_at is None:
                self._deadline_started_at = now_seconds
        self._depth_metric()

    def drain(self, send: Callable[[MeterRecordRequest], MeterEvent]) -> list[MeterEvent]:
        if self._state in {"degraded", "fail_closed"}:
            self._rejected("drain_blocked")
            raise MeterBufferError("METERING_REJECTED: meter_buffer cannot drain while fail-closed", self._state)
        accepted: list[MeterEvent] = []
        while self._queue:
            accepted.append(send(self._queue.pop(0)))
            self._depth_metric()
        self._state = "open"
        self._deadline_started_at = None
        return accepted

    def mark_degraded(self, reason: str) -> None:
        self._state = "degraded"
        self.observability.spans.append(
            {"name": "gateway.meter_buffer.degraded", "attributes": {"reason": reason, "redacted_fields": ("payload",)}}
        )

    def _depth_metric(self) -> None:
        self.observability.metrics.append(
            {
                "name": "gateway.meter_buffer.depth",
                "value": len(self._queue),
                "attributes": {"state": self._state, "redacted_fields": ("payload",)},
            }
        )

    def _rejected(self, reason: str) -> None:
        attrs = {
            "reason": reason,
            "state": self._state,
            "dropped_events": self._dropped_events,
            "redacted_fields": ("payload",),
        }
        self.observability.spans.append({"name": "gateway.meter_buffer.rejected", "attributes": attrs})
        self.observability.metrics.append({"name": "gateway.meter_buffer.rejected.count", "value": 1, "attributes": attrs})


def parse_meter_event(data: dict[str, Any]) -> MeterEvent:
    return MeterEvent(
        meter_event_id=str(_pick(data, "meter_event_id", "meterEventId")),
        access_grant_id=str(_pick(data, "access_grant_id", "accessGrantId")),
        invocation_id=str(_pick(data, "invocation_id", "invocationId")),
        buyer_account_id=str(_pick(data, "buyer_account_id", "buyerAccountId")),
        seller_account_id=str(_pick(data, "seller_account_id", "sellerAccountId")),
        listing_id=str(_pick(data, "listing_id", "listingId")),
        listing_version_id=str(_pick(data, "listing_version_id", "listingVersionId")),
        connector_id=str(_pick(data, "connector_id", "connectorId")),
        event_type=str(_pick(data, "event_type", "eventType")),
        measures=MeterMeasures(**_pick(data, "measures")),
        artifact_hash=str(_pick(data, "artifact_hash", "artifactHash")),
        occurred_at=str(_pick(data, "occurred_at", "occurredAt")),
        accepted_at=str(_pick(data, "accepted_at", "acceptedAt")),
        state=str(_pick(data, "state")),
        seller_edge_identity_hash=_pick(data, "seller_edge_identity_hash", "sellerEdgeIdentityHash"),
    )


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    raise KeyError(keys[0])


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}
