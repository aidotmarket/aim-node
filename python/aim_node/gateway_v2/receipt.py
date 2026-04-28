from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

import httpx

from .contracts import CLIENT_METHODS, GatewaySurface, reject_payload_contract_fields
from .meter import MeterMeasures


RECEIPT_GET_CLIENT_METHOD = CLIENT_METHODS[GatewaySurface.RECEIPT_GET]
RECEIPT_LOOKUP_CLIENT_METHOD = CLIENT_METHODS[GatewaySurface.RECEIPT_LOOKUP]
RECEIPT_GET_HTTP_ROUTE = "/v1/gateway/receipts"
RECEIPT_LOOKUP_HTTP_ROUTE = "/v1/gateway/receipts"
RECEIPT_GET_GRPC_METHOD = "GetReceipt"
RECEIPT_LOOKUP_GRPC_METHOD = "LookupReceipt"
receiptSourceOfTruth = "ai-market-backend"


class PaymentState(StrEnum):
    AUTHORIZED = "authorized"
    SETTLED = "settled"
    FAILED = "failed"
    REFUNDED = "refunded"


@dataclass(frozen=True)
class ReceiptViewPrincipal:
    principal_type: str
    principal_id: str
    account_id: str | None = None
    delegated_account_id: str | None = None
    audit_reason: str | None = None

    def __post_init__(self) -> None:
        if self.principal_type == "support_governance" and not self.audit_reason:
            raise ValueError("support/governance receipt access requires an audit reason")


@dataclass(frozen=True)
class MeteringReceiptSummary:
    meter_event_ids: list[str]
    measures: MeterMeasures
    artifact_hashes: list[str]
    connector_ids: list[str]


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    quote_id: str
    access_grant_id: str
    buyer_account_id: str
    seller_account_id: str
    listing_id: str
    listing_version_id: str
    terms_hash: str
    trust_artifact_references: dict[str, Any]
    metering_summary: MeteringReceiptSummary
    payment_state: str
    issued_at: str


@dataclass(frozen=True)
class ReceiptGetRequest:
    metadata: dict[str, Any]
    receipt_id: str
    principal: ReceiptViewPrincipal


@dataclass(frozen=True)
class ReceiptLookupRequest:
    metadata: dict[str, Any]
    principal: ReceiptViewPrincipal
    quote_id: str | None = None
    access_grant_id: str | None = None
    invocation_id: str | None = None


class GatewayReceiptClient:
    def __init__(self, base_url: str, api_key: str | None = None, client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or httpx.Client()

    def get(self, request: ReceiptGetRequest) -> Receipt:
        reject_payload_contract_fields(list(asdict(request).keys()))
        response = self.client.get(
            f"{self.base_url}{RECEIPT_GET_HTTP_ROUTE}/{request.receipt_id}",
            headers=self._headers(request.metadata),
        )
        response.raise_for_status()
        return parse_receipt(response.json())

    def lookup(self, request: ReceiptLookupRequest) -> list[Receipt]:
        reject_payload_contract_fields(list(asdict(request).keys()))
        params = _drop_none(
            {
                "quote_id": request.quote_id,
                "access_grant_id": request.access_grant_id,
                "invocation_id": request.invocation_id,
            }
        )
        response = self.client.get(
            f"{self.base_url}{RECEIPT_LOOKUP_HTTP_ROUTE}",
            params=params,
            headers=self._headers(request.metadata),
        )
        response.raise_for_status()
        return [parse_receipt(item) for item in response.json()]

    def _headers(self, metadata: dict[str, Any]) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "x-request-id": str(_pick(metadata, "request_id", "requestId")),
        }
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return headers


def parse_receipt(data: dict[str, Any]) -> Receipt:
    summary = _pick(data, "metering_summary", "meteringSummary")
    return Receipt(
        receipt_id=str(_pick(data, "receipt_id", "receiptId")),
        quote_id=str(_pick(data, "quote_id", "quoteId")),
        access_grant_id=str(_pick(data, "access_grant_id", "accessGrantId")),
        buyer_account_id=str(_pick(data, "buyer_account_id", "buyerAccountId")),
        seller_account_id=str(_pick(data, "seller_account_id", "sellerAccountId")),
        listing_id=str(_pick(data, "listing_id", "listingId")),
        listing_version_id=str(_pick(data, "listing_version_id", "listingVersionId")),
        terms_hash=str(_pick(data, "terms_hash", "termsHash")),
        trust_artifact_references=_pick(data, "trust", "trustArtifactReferences"),
        metering_summary=MeteringReceiptSummary(
            meter_event_ids=list(_pick(summary, "meter_event_ids", "meterEventIds")),
            measures=MeterMeasures(**_pick(summary, "measures")),
            artifact_hashes=list(_pick(summary, "artifact_hashes", "artifactHashes")),
            connector_ids=list(_pick(summary, "connector_ids", "connectorIds")),
        ),
        payment_state=str(_pick(data, "payment_state", "paymentState")),
        issued_at=str(_pick(data, "issued_at", "issuedAt")),
    )


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    raise KeyError(keys[0])


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}
