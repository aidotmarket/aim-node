from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import httpx

from .contracts import CLIENT_METHODS, GatewaySurface, reject_payload_contract_fields


CONNECT_CLIENT_METHOD = CLIENT_METHODS[GatewaySurface.CONNECT]
LOCAL_SECRET_REF_PREFIX = "local://aim-node/secrets/"


@dataclass(frozen=True)
class ConnectorPreferences:
    preferred_connector_ids: list[str] | None = None
    preferred_seller_edge_id: str | None = None
    connection_types: list[str] | None = None
    region: str | None = None


@dataclass(frozen=True)
class ConnectRequest:
    metadata: dict[str, Any]
    quote_id: str
    billing_session_id: str
    delivery_mode: str
    accepted_terms_hash: str
    connector_preferences: ConnectorPreferences | None = None
    seller_edge_id: str | None = None


@dataclass(frozen=True)
class SellerEdgeBinding:
    seller_edge_id: str
    seller_id: str
    connector_id: str
    listing_id: str
    identity_hash: str


@dataclass(frozen=True)
class GrantConnection:
    type: str
    local_secret_ref: str
    seller_edge: SellerEdgeBinding | None = None


@dataclass(frozen=True)
class AllowedScope:
    listing_id: str
    quote_id: str
    billing_session_id: str
    delivery_mode: str
    operations: list[str]
    max_concurrency: int


@dataclass(frozen=True)
class ConnectResponse:
    access_grant_id: str
    connector_id: str
    state: str
    expires_at: str
    connection: GrantConnection
    allowed_scope: AllowedScope
    terms_hash: str


class GatewayConnectClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or httpx.Client()

    def connect(self, request: ConnectRequest) -> ConnectResponse:
        reject_payload_contract_fields(list(asdict(request).keys()))
        _reject_raw_seller_secret_fields(asdict(request))
        headers = {
            "content-type": "application/json",
            "x-request-id": str(_pick(request.metadata, "requestId", "request_id")),
        }
        idempotency_key = _pick(request.metadata, "idempotencyKey", "idempotency_key")
        if idempotency_key:
            headers["idempotency-key"] = str(idempotency_key)
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"

        response = self.client.post(
            f"{self.base_url}/v1/gateway/connect",
            json=_drop_none(asdict(request)),
            headers=headers,
        )
        response.raise_for_status()
        return parse_connect_response(response.json())


def local_grant_secret_ref(access_grant_id: str) -> str:
    if not access_grant_id:
        raise ValueError("access_grant_id is required")
    return f"{LOCAL_SECRET_REF_PREFIX}grants/{access_grant_id}"


def parse_connect_response(data: dict[str, Any]) -> ConnectResponse:
    connection = _pick(data, "connection")
    allowed_scope = _pick(data, "allowed_scope", "allowedScope")
    secret_ref = _pick(connection, "local_secret_ref", "localSecretRef")
    _assert_local_secret_ref(secret_ref)
    return ConnectResponse(
        access_grant_id=_pick(data, "access_grant_id", "accessGrantId"),
        connector_id=_pick(data, "connector_id", "connectorId"),
        state=data["state"],
        expires_at=_pick(data, "expires_at", "expiresAt"),
        connection=GrantConnection(
            type=connection["type"],
            local_secret_ref=secret_ref,
            seller_edge=_parse_seller_edge(_pick(connection, "seller_edge", "sellerEdge")),
        ),
        allowed_scope=AllowedScope(
            listing_id=_pick(allowed_scope, "listing_id", "listingId"),
            quote_id=_pick(allowed_scope, "quote_id", "quoteId"),
            billing_session_id=_pick(allowed_scope, "billing_session_id", "billingSessionId"),
            delivery_mode=_pick(allowed_scope, "delivery_mode", "deliveryMode"),
            operations=list(allowed_scope["operations"]),
            max_concurrency=_pick(allowed_scope, "max_concurrency", "maxConcurrency"),
        ),
        terms_hash=_pick(data, "terms_hash", "termsHash"),
    )


def _parse_seller_edge(data: dict[str, Any] | None) -> SellerEdgeBinding | None:
    if not data:
        return None
    return SellerEdgeBinding(
        seller_edge_id=_pick(data, "seller_edge_id", "sellerEdgeId"),
        seller_id=_pick(data, "seller_id", "sellerId"),
        connector_id=_pick(data, "connector_id", "connectorId"),
        listing_id=_pick(data, "listing_id", "listingId"),
        identity_hash=_pick(data, "identity_hash", "identityHash"),
    )


def _assert_local_secret_ref(secret_ref: str) -> None:
    if not isinstance(secret_ref, str) or not secret_ref.startswith(LOCAL_SECRET_REF_PREFIX):
        raise ValueError("secret_ref must point to the local aim-node secret store")


def _reject_raw_seller_secret_fields(data: dict[str, Any]) -> None:
    for field_name in data:
        lowered = field_name.lower()
        if "raw_secret" in lowered or "seller_secret" in lowered:
            raise ValueError("raw seller secrets are forbidden in gateway.connect")


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}
