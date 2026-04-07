from __future__ import annotations

from typing import Any

import httpx

from .auth import AuthService
from .config import AIMCoreConfig

DEFAULT_TIMEOUT_S = 30.0


class MarketClientError(Exception):
    """Base ai.market client error."""


class MarketClientHTTPError(MarketClientError):
    """HTTP error returned by ai.market."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)


class MarketClient:
    """Async client for ai.market APIs."""

    def __init__(
        self,
        config: AIMCoreConfig,
        auth_service: AuthService | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.config = config
        self.auth_service = auth_service
        self.base_url = config.market_api_url.rstrip("/")
        self.timeout = timeout

    async def negotiate_session(
        self,
        listing_id: str,
        buyer_node_id: str,
        spend_cap_cents: int,
        session_type: str,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/sessions/negotiate",
            json_body={
                "listing_id": listing_id,
                "buyer_node_id": buyer_node_id,
                "spend_cap_cents": spend_cap_cents,
                "session_type": session_type,
            },
        )

    async def keepalive_session(self, session_id: str) -> None:
        await self._request("POST", f"/sessions/{session_id}/keepalive")

    async def close_session(self, session_id: str) -> None:
        await self._request("POST", f"/sessions/{session_id}/close")

    async def search_listings(self, query: str) -> list[dict[str, Any]]:
        payload = await self._request("GET", "/listings/search", params={"query": query})
        listings = payload.get("listings", payload)
        if not isinstance(listings, list):
            raise MarketClientError("listings search returned non-list payload")
        return [item for item in listings if isinstance(item, dict)]

    async def get_listing(self, listing_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/listings/{listing_id}")

    async def register_node(
        self, public_key: str, endpoint_url: str, serial: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/nodes/register",
            json_body={
                "public_key": public_key,
                "endpoint_url": endpoint_url,
                "serial": serial,
            },
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = await self._auth_headers()
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout
            ) as client:
                response = await client.request(
                    method,
                    path,
                    headers=headers,
                    json=json_body,
                    params=params,
                )
        except httpx.HTTPError as exc:
            raise MarketClientError(f"request to ai.market failed: {exc}") from exc

        if response.is_error:
            raise MarketClientHTTPError(response.status_code, response.text)

        if not response.content:
            return {}

        payload = response.json()
        if not isinstance(payload, dict):
            raise MarketClientError("ai.market returned non-object payload")
        return payload

    async def _auth_headers(self) -> dict[str, str]:
        if self.auth_service is not None:
            return await self.auth_service.get_auth_headers()
        if self.config.api_key:
            return {"X-API-Key": self.config.api_key}
        raise MarketClientError("no authentication credentials configured")
