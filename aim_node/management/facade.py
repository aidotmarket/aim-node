from __future__ import annotations

import time
from typing import Any

from aim_node.core.auth import AuthError, AuthService
from aim_node.core.config import AIMCoreConfig
from aim_node.core.market_client import (
    MarketClient,
    MarketClientError,
    MarketClientHTTPError,
)
from aim_node.management.errors import (
    ErrorCode,
    NormalizedError,
    make_error,
    make_market_error,
)


class FacadeError(Exception):
    """Raised by facade methods. Always carries a NormalizedError."""

    def __init__(self, normalized: NormalizedError, http_status: int) -> None:
        self.normalized = normalized
        self.http_status = http_status
        super().__init__(normalized.message)


class MarketplaceFacade:
    """Base class for marketplace route handlers."""

    _cache: dict[str, tuple[float, Any]]

    def __init__(self, client: MarketClient, node_id: str) -> None:
        self.client = client
        self.node_id = node_id
        self._cache = {}

    @classmethod
    def create(cls, config: AIMCoreConfig) -> "MarketplaceFacade":
        auth = AuthService(config)
        client = MarketClient(config, auth_service=auth)
        node_id = config.node_id
        if not node_id:
            raise ValueError(
                "node_id not set in config — complete node registration first. "
                "node_serial is a local identifier; node_id is the "
                "backend-assigned UUID."
            )
        return cls(client, node_id=node_id)

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        cache_ttl_s: float | None = None,
    ) -> dict[str, Any]:
        if cache_ttl_s is not None:
            cache_key = f"GET:{path}:{params}"
            cached = self._get_cache(cache_key)
            if cached is not None:
                return cached

        result = await self._request("GET", path, params=params)
        if cache_ttl_s is not None:
            self._set_cache(cache_key, result, cache_ttl_s)
        return result

    async def post(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._request("POST", path, json_body=json_body)

    async def put(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._request("PUT", path, json_body=json_body)

    async def delete(self, path: str) -> dict[str, Any]:
        return await self._request("DELETE", path)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        _is_retry: bool = False,
    ) -> dict[str, Any]:
        try:
            return await self.client._request(
                method,
                path,
                params=params,
                json_body=json_body,
            )
        except MarketClientHTTPError as exc:
            if exc.status_code == 401 and not _is_retry and self.client.auth_service:
                try:
                    await self.client.auth_service.refresh()
                except AuthError as refresh_exc:
                    normalized = make_error(
                        ErrorCode.AUTH_FAILED,
                        f"Marketplace authentication failed: {refresh_exc}",
                        suggested_action="Re-enter your API key in Settings",
                    )
                    raise FacadeError(normalized, 401) from refresh_exc
                except Exception:
                    pass
                else:
                    return await self._request(
                        method,
                        path,
                        params=params,
                        json_body=json_body,
                        _is_retry=True,
                    )

            normalized = make_market_error(exc.status_code, str(exc), path)
            raise FacadeError(normalized, 502) from exc
        except MarketClientError as exc:
            err_str = str(exc)
            if "timeout" in err_str.lower():
                normalized = make_error(
                    ErrorCode.MARKET_TIMEOUT,
                    f"Marketplace request timed out: {path}",
                )
                raise FacadeError(normalized, 504) from exc

            normalized = make_error(
                ErrorCode.MARKET_UNREACHABLE,
                f"Cannot reach marketplace: {path}",
                suggested_action=(
                    "Check your internet connection and API URL in Settings"
                ),
            )
            raise FacadeError(normalized, 502) from exc
        except AuthError as exc:
            normalized = make_error(
                ErrorCode.AUTH_FAILED,
                f"Marketplace authentication failed: {exc}",
                suggested_action="Re-enter your API key in Settings",
            )
            raise FacadeError(normalized, 401) from exc

    def _get_cache(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            return None

        expires_at, payload = entry
        if time.monotonic() > expires_at:
            del self._cache[key]
            return None
        return payload

    def _set_cache(self, key: str, payload: Any, ttl_s: float) -> None:
        self._cache[key] = (time.monotonic() + ttl_s, payload)

    def invalidate_cache(self, prefix: str = "") -> None:
        if not prefix:
            self._cache.clear()
            return

        for key in list(self._cache.keys()):
            if key.startswith(prefix):
                del self._cache[key]
