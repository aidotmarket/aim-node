from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import httpx

from .contracts import CLIENT_METHODS, GatewaySurface, reject_payload_contract_fields


VERIFY_PROVIDER_CLIENT_METHOD = CLIENT_METHODS[GatewaySurface.VERIFY_PROVIDER]
REQUEST_ACCESS_CLIENT_METHOD = CLIENT_METHODS[GatewaySurface.REQUEST_ACCESS]
ESTIMATE_COST_CLIENT_METHOD = CLIENT_METHODS[GatewaySurface.ESTIMATE_COST]
CREATE_BILLING_SESSION_CLIENT_METHOD = CLIENT_METHODS[GatewaySurface.CREATE_BILLING_SESSION]


@dataclass(frozen=True)
class BuyerBudgetCap:
    per_session_cents: int
    lifetime_cents: int
    lifetime_spend_cents: int = 0
    currency: str = "USD"


@dataclass(frozen=True)
class BuyerPolicyEnvelope:
    agent_id: str
    delegated_user_id: str
    delegated_account_id: str
    scopes: list[str]
    budget_cap: BuyerBudgetCap
    human_approval_required: bool = False
    human_approval_state: str = "not_required"


@dataclass(frozen=True)
class VerifyProviderRequest:
    metadata: dict[str, Any]
    seller_id: str
    listing_id: str
    policy_envelope: BuyerPolicyEnvelope
    seller_verification_ref: str
    provenance_attestation_ref: str
    terms_use_rights_ref: str
    quality_profile_ref: str
    sample_receipt_ref: str


@dataclass(frozen=True)
class RequestAccessRequest:
    metadata: dict[str, Any]
    buyer_account_id: str
    seller_id: str
    listing_id: str
    requested_use: str
    policy_envelope: BuyerPolicyEnvelope


@dataclass(frozen=True)
class EstimateCostRequest:
    metadata: dict[str, Any]
    buyer_account_id: str
    listing_id: str
    policy_envelope: BuyerPolicyEnvelope
    requested_units: int = 1


@dataclass(frozen=True)
class CreateBillingSessionRequest:
    metadata: dict[str, Any]
    buyer_account_id: str
    seller_id: str
    quote_id: str
    access_request_id: str
    terms_acceptance_id: str
    budget_cap_cents: int
    payment_state: str
    policy_envelope: BuyerPolicyEnvelope


class GatewayBuyerClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or httpx.Client()

    def VerifyProvider(self, request: VerifyProviderRequest) -> dict[str, Any]:
        return self._post("/v1/gateway/buyer/verify_provider", request, idempotent=False)

    def RequestAccess(self, request: RequestAccessRequest) -> dict[str, Any]:
        return self._post("/v1/gateway/buyer/request_access", request, idempotent=True)

    def EstimateCost(self, request: EstimateCostRequest) -> dict[str, Any]:
        return self._post("/v1/gateway/buyer/estimate_cost", request, idempotent=False)

    def CreateBillingSession(self, request: CreateBillingSessionRequest) -> dict[str, Any]:
        return self._post("/v1/gateway/buyer/billing_sessions", request, idempotent=True)

    def verify_provider(self, request: VerifyProviderRequest) -> dict[str, Any]:
        return self.VerifyProvider(request)

    def request_access(self, request: RequestAccessRequest) -> dict[str, Any]:
        return self.RequestAccess(request)

    def estimate_cost(self, request: EstimateCostRequest) -> dict[str, Any]:
        return self.EstimateCost(request)

    def create_billing_session(self, request: CreateBillingSessionRequest) -> dict[str, Any]:
        return self.CreateBillingSession(request)

    def _post(self, path: str, request: Any, *, idempotent: bool) -> dict[str, Any]:
        data = _drop_none(asdict(request))
        reject_payload_contract_fields(list(data.keys()))
        metadata = data["metadata"]
        headers = {
            "content-type": "application/json",
            "x-request-id": str(_pick(metadata, "requestId", "request_id")),
        }
        idempotency_key = _pick(metadata, "idempotencyKey", "idempotency_key")
        if idempotent and idempotency_key:
            headers["idempotency-key"] = str(idempotency_key)
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"

        response = self.client.post(f"{self.base_url}{path}", json=data, headers=headers)
        response.raise_for_status()
        return response.json()


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}
