from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx


def extract_path(data: dict[str, Any], path: str):
    """Extract value at path like '$.data.result'. Returns None if not found."""
    parts = path.lstrip("$").lstrip(".").split(".")
    current: Any = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


@dataclass
class AdapterConfig:
    endpoint_url: str
    health_check_url: str | None = None
    timeout_seconds: int = 30
    max_concurrent: int = 10
    max_body_bytes: int = 32768
    input_path: str | None = None
    wrap_key: str | None = None
    output_path: str | None = None


class AdapterError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class HttpJsonAdapter:
    def __init__(self, config: AdapterConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._healthy: bool = True
        self._consecutive_failures: int = 0

    async def start(self) -> None:
        """Initialize httpx client."""
        if self._client is not None:
            return

        limits = httpx.Limits(max_connections=self.config.max_concurrent)
        self._client = httpx.AsyncClient(timeout=self.config.timeout_seconds, limits=limits)

    async def stop(self) -> None:
        """Close httpx client."""
        if self._client is None:
            return

        await self._client.aclose()
        self._client = None

    async def forward_request(self, body: bytes) -> tuple[bytes, int]:
        """
        Forward a request to the seller's endpoint.
        """
        if len(body) > self.config.max_body_bytes:
            raise AdapterError(1001, "adapter: request body too large")

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdapterError(1001, "adapter: invalid JSON") from exc

        outbound_payload = payload
        if self.config.input_path is not None:
            outbound_payload = extract_path(payload, self.config.input_path)
        if self.config.wrap_key is not None:
            outbound_payload = {self.config.wrap_key: outbound_payload}

        client = self._require_client()
        started = time.perf_counter()
        try:
            response = await client.post(
                self.config.endpoint_url,
                json=outbound_payload,
                headers={"Content-Type": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise AdapterError(1007, "adapter: timeout") from exc
        except httpx.ConnectError as exc:
            raise AdapterError(1006, "adapter: connection refused/reset") from exc
        except httpx.NetworkError as exc:
            raise AdapterError(1006, "adapter: connection refused/reset") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        if not 200 <= response.status_code < 300:
            raise AdapterError(1006, f"adapter: HTTP {response.status_code}")

        try:
            response_payload = response.json()
        except json.JSONDecodeError as exc:
            raise AdapterError(1006, "adapter: non-JSON response") from exc

        if self.config.output_path is not None:
            if isinstance(response_payload, dict):
                response_payload = extract_path(response_payload, self.config.output_path)
            else:
                response_payload = None

        response_body = json.dumps(response_payload, separators=(",", ":")).encode("utf-8")
        return response_body, latency_ms

    async def health_check(self) -> bool:
        """
        GET health_check_url (or endpoint_url).
        """
        client = self._require_client()
        health_url = self.config.health_check_url or self.config.endpoint_url
        was_healthy = self._healthy

        try:
            response = await client.get(health_url, timeout=5.0)
            ok = 200 <= response.status_code < 300
        except httpx.HTTPError:
            ok = False

        if ok:
            self._consecutive_failures = 0
            self._healthy = True
            return True

        self._consecutive_failures += 1
        if self._consecutive_failures >= 3:
            self._healthy = False
        elif not was_healthy:
            self._healthy = False
        return False

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("adapter client is not started")
        return self._client
