from __future__ import annotations

from typing import Any

import httpx

from .auth import AuthService
from .config import AIMCoreConfig

DEFAULT_TIMEOUT_S = 30.0


class ConnectivityTokenError(Exception):
    """Raised for connectivity-token failures."""


class ConnectivityTokenService:
    """Client for ai.market connectivity-token endpoints."""

    def __init__(
        self,
        config: AIMCoreConfig,
        auth_service: AuthService,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.config = config
        self.auth_service = auth_service
        self.base_url = config.market_api_url.rstrip("/")
        self.timeout = timeout

    async def create_token(
        self,
        *,
        label: str,
        scopes: list[str] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"label": label}
        if scopes is not None:
            payload["scopes"] = scopes
        if expires_at is not None:
            payload["expires_at"] = expires_at
        return await self._request("POST", "/connectivity/tokens", json_body=payload)

    async def list_tokens(self) -> list[dict[str, Any]]:
        payload = await self._request("GET", "/connectivity/tokens")
        tokens = payload.get("tokens", payload)
        if not isinstance(tokens, list):
            raise ConnectivityTokenError("connectivity token list payload was not a list")
        return [token for token in tokens if isinstance(token, dict)]

    async def revoke_token(self, token_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/connectivity/tokens/{token_id}")

    async def verify_token(self, raw_token: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/connectivity/tokens/verify",
            json_body={"token": raw_token},
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = await self.auth_service.get_auth_headers()
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout
            ) as client:
                response = await client.request(
                    method, path, headers=headers, json=json_body
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ConnectivityTokenError(f"connectivity token request failed: {exc}") from exc

        payload = response.json()
        if not isinstance(payload, dict):
            raise ConnectivityTokenError("connectivity token endpoint returned non-object payload")
        return payload
