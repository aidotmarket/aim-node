from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import httpx

from .contracts import CLIENT_METHODS, GatewaySurface


QUOTE_CREATE_CLIENT_METHOD = CLIENT_METHODS[GatewaySurface.QUOTE_CREATE]


@dataclass(frozen=True)
class QuoteRequest:
    metadata: dict[str, Any]
    listing_id: str
    listing_version_id: str | None = None
    seller_id: str | None = None
    provider_id: str | None = None
    quantity: int | None = None
    units: str | None = None
    usage_estimate: dict[str, Any] | None = None
    buyer_context: dict[str, Any] | None = None
    expires_after_seconds: int | None = None


@dataclass(frozen=True)
class QuoteLineItem:
    code: str
    amount: int
    currency: str
    description: str | None = None
    quantity: int | None = None
    unit_amount: int | None = None


@dataclass(frozen=True)
class QuoteResponse:
    quote_id: str
    listing_id: str
    amount: int
    currency: str
    status: str
    listing_version_id: str | None = None
    seller_id: str | None = None
    provider_id: str | None = None
    line_items: list[QuoteLineItem] | None = None
    expires_at: str | None = None
    request_id: str | None = None


class GatewayQuoteClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or httpx.Client()

    def quote(self, request: QuoteRequest) -> QuoteResponse:
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
            f"{self.base_url}/v1/gateway/quotes",
            json=_drop_none(asdict(request)),
            headers=headers,
        )
        response.raise_for_status()
        return _parse_quote_response(response.json())


def _parse_quote_response(data: dict[str, Any]) -> QuoteResponse:
    line_items = data.get("line_items") or data.get("lineItems")
    return QuoteResponse(
        quote_id=data["quote_id"] if "quote_id" in data else data["quoteId"],
        listing_id=data["listing_id"] if "listing_id" in data else data["listingId"],
        listing_version_id=_pick(data, "listing_version_id", "listingVersionId"),
        seller_id=_pick(data, "seller_id", "sellerId"),
        provider_id=_pick(data, "provider_id", "providerId"),
        amount=data["amount"],
        currency=data["currency"],
        status=data["status"],
        line_items=[_parse_quote_line_item(item) for item in line_items] if line_items else None,
        expires_at=_pick(data, "expires_at", "expiresAt"),
        request_id=_pick(data, "request_id", "requestId"),
    )


def _parse_quote_line_item(data: dict[str, Any]) -> QuoteLineItem:
    return QuoteLineItem(
        code=data["code"],
        description=data.get("description"),
        quantity=data.get("quantity"),
        unit_amount=_pick(data, "unit_amount", "unitAmount"),
        amount=data["amount"],
        currency=data["currency"],
    )


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}
