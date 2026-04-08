"""Pydantic v2 request/response models for management HTTP API."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, field_validator, model_validator


def _validate_http_url(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    if not isinstance(v, str):
        raise ValueError("url must be a string")
    if not (v.startswith("http://") or v.startswith("https://")):
        raise ValueError("url must use http or https scheme")
    return v


# ---------- Request Models ----------


class KeypairRequest(BaseModel):
    passphrase: Optional[str] = None


class TestConnectionRequest(BaseModel):
    api_url: str
    api_key: str

    @field_validator("api_url")
    @classmethod
    def _validate_api_url(cls, v: str) -> str:
        return _validate_http_url(v)  # type: ignore[return-value]


class FinalizeSetupRequest(BaseModel):
    mode: Literal["provider", "consumer", "both"]
    api_url: str
    api_key: str
    upstream_url: Optional[str] = None

    @field_validator("api_url")
    @classmethod
    def _validate_api_url(cls, v: str) -> str:
        return _validate_http_url(v)  # type: ignore[return-value]

    @field_validator("upstream_url")
    @classmethod
    def _validate_upstream_url(cls, v: Optional[str]) -> Optional[str]:
        return _validate_http_url(v)

    @model_validator(mode="after")
    def _require_upstream_for_provider(self):
        if self.mode in ("provider", "both") and not self.upstream_url:
            raise ValueError("upstream_url required when mode includes provider")
        return self


class UnlockRequest(BaseModel):
    passphrase: str


class ConfigUpdateRequest(BaseModel):
    mode: Optional[Literal["provider", "consumer", "both"]] = None
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    upstream_url: Optional[str] = None

    @field_validator("api_url")
    @classmethod
    def _validate_api_url(cls, v: Optional[str]) -> Optional[str]:
        return _validate_http_url(v)

    @field_validator("upstream_url")
    @classmethod
    def _validate_upstream_url(cls, v: Optional[str]) -> Optional[str]:
        return _validate_http_url(v)

    # Upstream-required check is enforced at route level (config_update),
    # which merges the request with persisted config so partial updates work.


# ---------- Response Models ----------


class HealthResponse(BaseModel):
    healthy: bool = True
    setup_complete: bool
    locked: bool


class SetupStatusResponse(BaseModel):
    setup_complete: bool
    locked: bool
    unlocked: bool
    current_step: int


class KeypairResponse(BaseModel):
    fingerprint: str
    created: bool


class TestConnectionResponse(BaseModel):
    reachable: bool
    version: Optional[str] = None


class FinalizeResponse(BaseModel):
    ok: bool = True


class DashboardResponse(BaseModel):
    node_id: str
    fingerprint: str = ""
    mode: str = ""
    uptime_s: float
    version: str = ""
    market_connected: bool
    provider_running: bool
    consumer_running: bool


class ConfigReadResponse(BaseModel):
    mode: str
    api_url: str
    api_key_set: bool
    upstream_url: Optional[str] = None
    data_dir: str


class ConfigUpdateResponse(BaseModel):
    ok: bool = True
    restart_required: bool


class ProviderStartResponse(BaseModel):
    started: bool = True


class ProviderStopResponse(BaseModel):
    stopped: bool = True


class ProviderHealthResponse(BaseModel):
    upstream_reachable: bool
    latency_ms: Optional[float] = None
    last_check: str


class ConsumerStartResponse(BaseModel):
    started: bool = True
    proxy_port: int


class ConsumerStopResponse(BaseModel):
    stopped: bool = True


class SessionItem(BaseModel):
    id: str
    role: str
    state: str
    created_at: float
    peer_fingerprint: str = ""
    bytes_transferred: int = 0


class SessionsResponse(BaseModel):
    sessions: list[SessionItem]


class SessionDetailResponse(BaseModel):
    id: str
    role: str
    state: str
    metering_events: list[dict] = []
    latency_ms: Optional[float] = None
    error_count: int = 0
    created_at: float


class UnlockResponse(BaseModel):
    unlocked: bool = True


class KeypairInfoResponse(BaseModel):
    fingerprint: str
    algorithm: str = "Ed25519"
    created_at: str


class ErrorResponse(BaseModel):
    error: str
