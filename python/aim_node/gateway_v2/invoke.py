from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Iterable

import httpx

from .contracts import CLIENT_METHODS, GatewaySurface, reject_payload_contract_fields


INVOKE_CLIENT_METHOD = CLIENT_METHODS[GatewaySurface.INVOKE]
INVOKE_HTTP_ROUTE = "/v1/gateway/invoke"
INVOKE_GRPC_UNARY_METHOD = "Invoke"
INVOKE_GRPC_STREAMING_METHOD = "InvokeStream"


class InvokeState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL_TRANSFER = "partial_transfer"
    PROVIDER_TIMEOUT = "provider_timeout"
    GRANT_REVOKED_MID_STREAM = "grant_revoked_mid_stream"
    TRUST_REVOKED_MID_STREAM = "trust_revoked_mid_stream"
    RESUME_UNSUPPORTED = "resume_unsupported"
    METERING_ACCEPTED_RECEIPT_PENDING = "metering_accepted_receipt_pending"


@dataclass(frozen=True)
class ResumeCursor:
    signed_offset: str | None = None
    resume_token: str | None = None

    def __post_init__(self) -> None:
        if not (self.signed_offset or self.resume_token):
            raise ValueError("stream resume requires a signed offset or resume token")


@dataclass(frozen=True)
class InvokeLimits:
    byte_cap: int = 5 * 1024 * 1024 * 1024
    row_cap: int = 1_000_000
    record_cap: int = 1_000_000
    wall_clock_cap_seconds: float = 3_600
    idle_timeout_seconds: float = 120
    per_grant_concurrency: int = 4
    retry_after_seconds: int = 60


@dataclass(frozen=True)
class RuntimeGrantBinding:
    access_grant_id: str
    buyer_account_id: str
    listing_id: str
    listing_version_id: str
    connector_id: str
    delivery_mode: str
    terms_hash: str
    operations: list[str]
    expires_at: str
    state: str = "active"
    seller_edge_identity_hash: str | None = None
    max_concurrency: int = 4


@dataclass(frozen=True)
class InvokeRequest:
    metadata: dict[str, Any]
    access_grant_id: str
    buyer_account_id: str
    listing_id: str
    listing_version_id: str
    connector_id: str
    delivery_mode: str
    terms_hash: str
    operation: str
    mode: str = "unary"
    seller_edge_identity_hash: str | None = None
    resume: ResumeCursor | None = None
    limits: InvokeLimits = field(default_factory=InvokeLimits)


@dataclass(frozen=True)
class MeteringSummary:
    bytes: int = 0
    rows: int = 0
    records: int = 0
    calls: int = 0
    duration_ms: int = 0
    retries: int = 0
    provider_latency_ms: int = 0
    cache_state: str = "unknown"
    connector_type: str = "unknown"
    seller_edge_route: str = "local"


@dataclass(frozen=True)
class InvokeResponse:
    invocation_id: str
    state: str
    metering: MeteringSummary
    retry_after_seconds: int | None = None
    resume_required: bool = False


class InvokeRuntimeError(RuntimeError):
    def __init__(self, state: InvokeState, message: str, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.state = state
        self.retry_after_seconds = retry_after_seconds


class GatewayInvokeClient:
    def __init__(self, base_url: str, api_key: str | None = None, client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or httpx.Client()

    def invoke(self, request: InvokeRequest) -> InvokeResponse:
        reject_payload_contract_fields(list(asdict(request).keys()))
        headers = {
            "content-type": "application/json",
            "x-request-id": str(_pick(request.metadata, "requestId", "request_id")),
        }
        idempotency_key = _pick(request.metadata, "idempotencyKey", "idempotency_key")
        if idempotency_key:
            headers["idempotency-key"] = str(idempotency_key)
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"

        response = self.client.post(f"{self.base_url}{INVOKE_HTTP_ROUTE}", json=_drop_none(asdict(request)), headers=headers)
        response.raise_for_status()
        return parse_invoke_response(response.json())


class ConnectorRuntime:
    def __init__(self) -> None:
        self.active_per_grant: dict[str, int] = {}

    def invoke(
        self,
        request: InvokeRequest,
        grant: RuntimeGrantBinding,
        chunks: Iterable[bytes],
        *,
        resume_supported: bool = True,
        trust_revoked: bool = False,
        grant_revoked: bool = False,
        now: datetime | None = None,
    ) -> InvokeResponse:
        self._validate_grant_binding(request, grant, now or datetime(2026, 4, 28, tzinfo=UTC))
        if trust_revoked:
            raise InvokeRuntimeError(InvokeState.TRUST_REVOKED_MID_STREAM, "trust revoked mid stream")
        if grant_revoked:
            raise InvokeRuntimeError(InvokeState.GRANT_REVOKED_MID_STREAM, "grant revoked mid stream")
        if request.resume and not resume_supported:
            raise InvokeRuntimeError(InvokeState.RESUME_UNSUPPORTED, "connector does not support resume")

        active = self.active_per_grant.get(request.access_grant_id, 0)
        if active >= request.limits.per_grant_concurrency:
            raise InvokeRuntimeError(InvokeState.FAILED, "per_grant concurrency exceeded", request.limits.retry_after_seconds)

        self.active_per_grant[request.access_grant_id] = active + 1
        started = time.monotonic()
        bytes_seen = 0
        records = 0
        try:
            for chunk in chunks:
                elapsed = time.monotonic() - started
                if elapsed > request.limits.wall_clock_cap_seconds:
                    raise InvokeRuntimeError(InvokeState.PROVIDER_TIMEOUT, "wall-clock cap exceeded")
                bytes_seen += len(chunk)
                records += 1
                if bytes_seen > request.limits.byte_cap or records > request.limits.record_cap:
                    raise InvokeRuntimeError(InvokeState.PARTIAL_TRANSFER, "byte or record cap exceeded")
            duration_ms = int((time.monotonic() - started) * 1000)
            return InvokeResponse(
                invocation_id=f"inv_{request.access_grant_id}_{request.operation}".replace("-", "_"),
                state=InvokeState.COMPLETED,
                metering=MeteringSummary(
                    bytes=bytes_seen,
                    records=records,
                    calls=1,
                    duration_ms=duration_ms,
                    retries=1 if request.resume else 0,
                    provider_latency_ms=duration_ms,
                    connector_type=request.connector_id,
                    seller_edge_route=request.seller_edge_identity_hash or "local",
                ),
                resume_required=request.mode == "stream",
            )
        finally:
            self.active_per_grant[request.access_grant_id] = active

    def _validate_grant_binding(self, request: InvokeRequest, grant: RuntimeGrantBinding, now: datetime) -> None:
        expires_at = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00"))
        if grant.state != "active" or expires_at <= now:
            raise InvokeRuntimeError(InvokeState.FAILED, "active unexpired grant required")
        checks = {
            "access_grant_id": request.access_grant_id == grant.access_grant_id,
            "buyer_account_id": request.buyer_account_id == grant.buyer_account_id,
            "listing_id": request.listing_id == grant.listing_id,
            "listing_version_id": request.listing_version_id == grant.listing_version_id,
            "connector_id": request.connector_id == grant.connector_id,
            "delivery_mode": request.delivery_mode == grant.delivery_mode,
            "terms_hash": request.terms_hash == grant.terms_hash,
            "operation": request.operation in grant.operations,
            "seller_edge_identity_hash": (
                grant.seller_edge_identity_hash is None
                or request.seller_edge_identity_hash == grant.seller_edge_identity_hash
            ),
        }
        failed = [field for field, ok in checks.items() if not ok]
        if failed:
            raise InvokeRuntimeError(InvokeState.FAILED, f"grant binding mismatch: {failed[0]}")


def parse_invoke_response(data: dict[str, Any]) -> InvokeResponse:
    metering = _pick(data, "metering") or {}
    return InvokeResponse(
        invocation_id=_pick(data, "invocation_id", "invocationId"),
        state=_pick(data, "state"),
        metering=MeteringSummary(
            bytes=_pick(metering, "bytes") or 0,
            rows=_pick(metering, "rows") or 0,
            records=_pick(metering, "records") or 0,
            calls=_pick(metering, "calls") or 0,
            duration_ms=_pick(metering, "duration_ms", "durationMs") or 0,
            retries=_pick(metering, "retries") or 0,
            provider_latency_ms=_pick(metering, "provider_latency_ms", "providerLatencyMs") or 0,
            cache_state=_pick(metering, "cache_state", "cacheState") or "unknown",
            connector_type=_pick(metering, "connector_type", "connectorType") or "unknown",
            seller_edge_route=_pick(metering, "seller_edge_route", "sellerEdgeRoute") or "local",
        ),
        retry_after_seconds=_pick(data, "retry_after_seconds", "retryAfterSeconds"),
        resume_required=bool(_pick(data, "resume_required", "resumeRequired")),
    )


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}
