from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GatewaySurface(StrEnum):
    DISCOVER = "discover"
    QUOTE_CREATE = "quote.create"
    QUOTE_GET = "quote.get"
    CONNECT = "connect"
    INVOKE = "invoke"
    METER_RECORD = "meter.record"
    METER_LIST = "meter.list"
    RECEIPT_GET = "receipt.get"
    RECEIPT_LOOKUP = "receipt.lookup"
    PUBLISH = "publish"
    VERIFY_PROVIDER = "verify_provider"
    REQUEST_ACCESS = "request_access"
    ESTIMATE_COST = "estimate_cost"
    CREATE_BILLING_SESSION = "create_billing_session"


COMMON_ID_FIELDS: tuple[str, ...] = (
    "listing_id",
    "listing_version_id",
    "seller_id",
    "provider_id",
    "quote_id",
    "access_grant_id",
    "connector_id",
    "invocation_id",
    "meter_event_id",
    "receipt_id",
    "billing_session_id",
    "trust_profile_id",
    "attestation_id",
)


@dataclass(frozen=True)
class GatewayClientMethod:
    surface: GatewaySurface
    sdk_method: str
    idempotency_required: bool
    source_of_truth: str


CLIENT_METHODS: dict[GatewaySurface, GatewayClientMethod] = {
    GatewaySurface.DISCOVER: GatewayClientMethod(
        GatewaySurface.DISCOVER, "gateway.discover", False, "ai-market-backend"
    ),
    GatewaySurface.QUOTE_CREATE: GatewayClientMethod(
        GatewaySurface.QUOTE_CREATE, "gateway.quote.create", True, "ai-market-backend"
    ),
    GatewaySurface.QUOTE_GET: GatewayClientMethod(
        GatewaySurface.QUOTE_GET, "gateway.quote.get", False, "ai-market-backend"
    ),
    GatewaySurface.CONNECT: GatewayClientMethod(
        GatewaySurface.CONNECT, "gateway.connect", True, "ai-market-backend"
    ),
    GatewaySurface.INVOKE: GatewayClientMethod(
        GatewaySurface.INVOKE, "gateway.invoke", True, "local-or-seller-edge-runtime"
    ),
    GatewaySurface.METER_RECORD: GatewayClientMethod(
        GatewaySurface.METER_RECORD, "gateway.meter.record", True, "ai-market-backend"
    ),
    GatewaySurface.METER_LIST: GatewayClientMethod(
        GatewaySurface.METER_LIST, "gateway.meter.list", False, "ai-market-backend"
    ),
    GatewaySurface.RECEIPT_GET: GatewayClientMethod(
        GatewaySurface.RECEIPT_GET, "gateway.receipt.get", False, "ai-market-backend"
    ),
    GatewaySurface.RECEIPT_LOOKUP: GatewayClientMethod(
        GatewaySurface.RECEIPT_LOOKUP, "gateway.receipt.lookup", False, "ai-market-backend"
    ),
    GatewaySurface.PUBLISH: GatewayClientMethod(
        GatewaySurface.PUBLISH, "gateway.publish", True, "ai-market-backend"
    ),
    GatewaySurface.VERIFY_PROVIDER: GatewayClientMethod(
        GatewaySurface.VERIFY_PROVIDER, "gateway.verify_provider", False, "ai-market-backend"
    ),
    GatewaySurface.REQUEST_ACCESS: GatewayClientMethod(
        GatewaySurface.REQUEST_ACCESS, "gateway.request_access", True, "ai-market-backend"
    ),
    GatewaySurface.ESTIMATE_COST: GatewayClientMethod(
        GatewaySurface.ESTIMATE_COST, "gateway.estimate_cost", False, "ai-market-backend"
    ),
    GatewaySurface.CREATE_BILLING_SESSION: GatewayClientMethod(
        GatewaySurface.CREATE_BILLING_SESSION,
        "gateway.create_billing_session",
        True,
        "ai-market-backend",
    ),
}

AIM_NODE_LOCAL_RUNTIME_MODELS: tuple[str, ...] = (
    "local_credentials",
    "connector_configuration",
    "cached_discover_result_with_freshness",
    "gateway_invocation_runtime",
    "local_meter_buffer",
    "retry_idempotency_coordination",
    "developer_console_health",
)

AIM_NODE_FORBIDDEN_SOURCE_OF_TRUTH_MODELS: tuple[str, ...] = (
    "canonical_listing",
    "canonical_quote",
    "canonical_billing_session",
    "accepted_meter_event",
    "canonical_receipt",
    "balance_ledger",
    "trust_state",
)

FORBIDDEN_PAYLOAD_FIELD_TOKENS: tuple[str, ...] = (
    "payload",
    "payload_bytes",
    "dataset_bytes",
    "raw_bytes",
    "file_bytes",
    "content_bytes",
    "sample_bytes",
    "sample_payload",
    "raw_secret",
    "seller_secret",
)


def reject_payload_contract_fields(field_names: list[str]) -> None:
    forbidden = [
        field
        for field in field_names
        if any(token in field.lower() for token in FORBIDDEN_PAYLOAD_FIELD_TOKENS)
    ]
    if forbidden:
        raise ValueError(f"payload-bearing fields are forbidden: {forbidden}")
