from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from .config import AIMCoreConfig

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 30.0
DEFAULT_TOKEN_PATH = "auth_token.json"


class AuthError(Exception):
    """Raised for authentication failures."""


class AuthService:
    """Handles ai.market API authentication and bearer-token refresh."""

    def __init__(
        self,
        config: AIMCoreConfig,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        token_path: str | Path | None = None,
    ) -> None:
        self.config = config
        self.base_url = config.market_api_url.rstrip("/")
        self.timeout = timeout
        self.token_path = (
            Path(token_path) if token_path is not None else config.data_dir / DEFAULT_TOKEN_PATH
        )
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.expires_at: datetime | None = None
        self._load_tokens()

    async def authenticate(self) -> str:
        if not self.config.api_key:
            raise AuthError("api_key is required for authentication")

        payload = await self._request_json(
            "POST",
            "/auth/token",
            headers={"X-API-Key": self.config.api_key},
        )
        self._store_tokens(payload)
        return self.access_token or self.config.api_key

    async def refresh(self) -> str:
        if not self.refresh_token:
            return await self.authenticate()

        payload = await self._request_json(
            "POST",
            "/auth/refresh",
            headers={"Authorization": f"Bearer {self.refresh_token}"},
        )
        self._store_tokens(payload)
        return self.access_token or self.config.api_key or ""

    async def get_access_token(self) -> str:
        if self.access_token and not self._is_expired():
            return self.access_token
        if self.refresh_token:
            return await self.refresh()
        if self.config.api_key:
            return await self.authenticate()
        raise AuthError("no authentication credentials configured")

    async def get_auth_headers(self) -> dict[str, str]:
        if self.access_token or self.refresh_token:
            token = await self.get_access_token()
            return {"Authorization": f"Bearer {token}"}
        if self.config.api_key:
            return {"X-API-Key": self.config.api_key}
        raise AuthError("no authentication credentials configured")

    def _is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at

    def _store_tokens(self, payload: dict[str, Any]) -> None:
        self.access_token = payload.get("access_token") or self.access_token
        self.refresh_token = payload.get("refresh_token") or self.refresh_token

        expires_in = payload.get("expires_in")
        expires_at = payload.get("expires_at")
        if expires_at:
            self.expires_at = self._parse_datetime(expires_at)
        elif expires_in is not None:
            self.expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

        self._persist_tokens()

    def _load_tokens(self) -> None:
        if not self.token_path.exists():
            return
        try:
            payload = json.loads(self.token_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load auth token cache from %s", self.token_path)
            return

        self.access_token = payload.get("access_token")
        self.refresh_token = payload.get("refresh_token")
        expires_at = payload.get("expires_at")
        self.expires_at = self._parse_datetime(expires_at) if expires_at else None

    def _persist_tokens(self) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
        self.token_path.write_text(json.dumps(payload), encoding="utf-8")

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout
            ) as client:
                response = await client.request(
                    method, path, headers=headers, json=json_body
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AuthError(f"authentication request failed: {exc}") from exc

        payload = response.json()
        if not isinstance(payload, dict):
            raise AuthError("authentication endpoint returned non-object payload")
        return payload

    def _parse_datetime(self, value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
