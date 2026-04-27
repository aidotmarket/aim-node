from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import httpx

from .contracts import CLIENT_METHODS, GatewaySurface


DISCOVER_CLIENT_METHOD = CLIENT_METHODS[GatewaySurface.DISCOVER]


@dataclass(frozen=True)
class DiscoverRequest:
    metadata: dict[str, Any]
    query: str | None = None
    categories: list[str] | None = None
    tags: list[str] | None = None
    seller_ids: list[str] | None = None
    provider_ids: list[str] | None = None
    capabilities: list[str] | None = None
    limit: int | None = None
    cursor: str | None = None


@dataclass(frozen=True)
class DiscoverListing:
    listing_id: str
    listing_version_id: str
    seller_id: str
    provider_id: str | None = None
    title: str = ""
    description: str | None = None
    categories: list[str] | None = None
    tags: list[str] | None = None
    capabilities: list[str] | None = None
    quote_required: bool | None = None
    pricing_summary: dict[str, Any] | None = None


@dataclass(frozen=True)
class DiscoverResponse:
    listings: list[DiscoverListing]
    next_cursor: str | None = None
    request_id: str | None = None


class GatewayDiscoverClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or httpx.Client()

    def discover(self, request: DiscoverRequest) -> DiscoverResponse:
        headers = {
            "content-type": "application/json",
            "x-request-id": str(_pick(request.metadata, "requestId", "request_id")),
        }
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"

        response = self.client.post(
            f"{self.base_url}/v1/gateway/discover",
            json=_drop_none(asdict(request)),
            headers=headers,
        )
        response.raise_for_status()
        return _parse_discover_response(response.json())


def _parse_discover_response(data: dict[str, Any]) -> DiscoverResponse:
    return DiscoverResponse(
        listings=[_parse_discover_listing(listing) for listing in data.get("listings", [])],
        next_cursor=_pick(data, "next_cursor", "nextCursor"),
        request_id=_pick(data, "request_id", "requestId"),
    )


def _parse_discover_listing(data: dict[str, Any]) -> DiscoverListing:
    return DiscoverListing(
        listing_id=data["listing_id"] if "listing_id" in data else data["listingId"],
        listing_version_id=(
            data["listing_version_id"]
            if "listing_version_id" in data
            else data["listingVersionId"]
        ),
        seller_id=data["seller_id"] if "seller_id" in data else data["sellerId"],
        provider_id=_pick(data, "provider_id", "providerId"),
        title=data.get("title", ""),
        description=data.get("description"),
        categories=data.get("categories"),
        tags=data.get("tags"),
        capabilities=data.get("capabilities"),
        quote_required=_pick(data, "quote_required", "quoteRequired"),
        pricing_summary=_pick(data, "pricing_summary", "pricingSummary"),
    )


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}
