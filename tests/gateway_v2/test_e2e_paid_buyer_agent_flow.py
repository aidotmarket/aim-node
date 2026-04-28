from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

AIM_NODE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = AIM_NODE_ROOT.parent / "ai-market-backend"
sys.path.insert(0, str(AIM_NODE_ROOT / "python"))
sys.path.insert(1, str(BACKEND_ROOT))
sys.modules.pop("aim_node", None)

from aim_node.gateway_v2.buyer import (  # type: ignore[import-not-found]
    BuyerBudgetCap,
    BuyerPolicyEnvelope,
    EstimateCostRequest,
    GatewayBuyerClient,
    RequestAccessRequest,
    VerifyProviderRequest,
)
from aim_node.gateway_v2.connect import ConnectorPreferences, ConnectRequest, GatewayConnectClient
from aim_node.gateway_v2.discover import DiscoverRequest, GatewayDiscoverClient
from aim_node.gateway_v2.invoke import GatewayInvokeClient, InvokeRequest
from aim_node.gateway_v2.meter import GatewayMeterClient, MeterMeasures, MeterRecordRequest
from aim_node.gateway_v2.quote import GatewayQuoteClient, QuoteRequest
from aim_node.gateway_v2.receipt import GatewayReceiptClient, ReceiptLookupRequest, ReceiptViewPrincipal


CANONICAL_FLOW = (
    "discover -> verify_provider -> estimate_cost -> quote -> request_access -> "
    "create_billing_session -> connect -> invoke -> meter -> receipt"
)


class _TestClientAdapter:
    def __init__(self, client: Any, captures: list[dict[str, Any]]) -> None:
        self.client = client
        self.captures = captures

    def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> "ResponseAdapter":
        path = "/" + url.split("/", 3)[3]
        response = self.client.post(path, json=json, headers=headers)
        self.captures.append({"method": "POST", "path": path, "request": json, "headers": headers, "status_code": response.status_code, "response": _json_or_text(response)})
        return ResponseAdapter(response)

    def get(self, url: str, params: dict[str, Any], headers: dict[str, str]) -> "ResponseAdapter":
        path = "/" + url.split("/", 3)[3]
        response = self.client.get(path, params=params, headers=headers)
        self.captures.append({"method": "GET", "path": path, "request": params, "headers": headers, "status_code": response.status_code, "response": _json_or_text(response)})
        return ResponseAdapter(response)


class ResponseAdapter:
    def __init__(self, response: Any) -> None:
        self.response = response

    def raise_for_status(self) -> None:
        self.response.raise_for_status()

    def json(self) -> Any:
        return self.response.json()


@pytest.mark.xfail(
    reason=(
        "Gate 2 Chunk 8 exposes an SDK/backend contract gap: aim-node Python SDK "
        "discover/quote/verify_provider envelopes are legacy SDK shapes, while backend "
        "Gateway v2 models require results-based discover responses, TrustArtifactReference "
        "objects, and QuoteCreateRequest fields."
    ),
    strict=True,
)
def test_python_sdk_canonical_paid_buyer_agent_flow_against_backend_asgi_fixtures() -> None:
    backend_e2e = _load_backend_e2e_module()
    fixture = _load_fixture()
    state = backend_e2e.FlowState(fixture)
    test_client = backend_e2e.TestClient(backend_e2e._build_app(state))
    captures: list[dict[str, Any]] = []
    http = _TestClientAdapter(test_client, captures)
    base_url = "http://testserver"
    token = fixture["buyer_agent_token"]["value"]
    listing = fixture["sample_listing"]

    discover = GatewayDiscoverClient(base_url, api_key=token, client=http).discover(
        DiscoverRequest(metadata=_metadata("discover"), query="retail demand", limit=10)
    )
    selected = discover.listings[0]

    buyer = GatewayBuyerClient(base_url, api_key=token, client=http)
    verify = buyer.verify_provider(
        VerifyProviderRequest(
            metadata=_metadata("verify"),
            seller_id=selected.seller_id,
            listing_id=selected.listing_id,
            policy_envelope=_policy(fixture),
            seller_verification_ref=fixture["trust_artifact_references"]["seller_verification_ref"],
            provenance_attestation_ref=fixture["trust_artifact_references"]["provenance_attestation_ref"],
            terms_use_rights_ref=fixture["trust_artifact_references"]["terms_use_rights_ref"],
            quality_profile_ref=fixture["trust_artifact_references"]["quality_profile_ref"],
            sample_receipt_ref=fixture["trust_artifact_references"]["sample_receipt_ref"],
        )
    )
    assert verify["checked_refs"] == list(fixture["trust_artifact_references"].values())

    estimate = buyer.estimate_cost(
        EstimateCostRequest(
            metadata=_metadata("estimate"),
            buyer_account_id=fixture["buyer_agent_token"]["account_id"],
            listing_id=selected.listing_id,
            requested_units=fixture["quote"]["requested_units"],
            policy_envelope=_policy(fixture),
        )
    )
    assert estimate["quote_required_for_billing"] is True

    quote = GatewayQuoteClient(base_url, api_key=token, client=http).quote(
        QuoteRequest(
            metadata=_metadata("quote", idempotency_key="idem_quote_sdk_e2e"),
            listing_id=selected.listing_id,
            listing_version_id=selected.listing_version_id,
            seller_id=listing["seller_id"],
            quantity=fixture["quote"]["requested_units"],
            buyer_context={"usage_purpose": "Forecast retail demand."},
        )
    )

    access = buyer.request_access(
        RequestAccessRequest(
            metadata=_metadata("access", idempotency_key="idem_access_sdk_e2e"),
            buyer_account_id=fixture["buyer_agent_token"]["account_id"],
            seller_id=listing["seller_id"],
            listing_id=quote.listing_id,
            requested_use="Forecast retail demand.",
            policy_envelope=_policy(fixture),
        )
    )

    billing = buyer.create_billing_session(
        backend_e2e._billing_payload(
            fixture,
            token,
            {"quote_id": quote.quote_id, "subtotal_cents": quote.amount, "currency": quote.currency},
            access,
            backend_e2e.BuyerPaymentState.COMPLETED,
            "idem_billing_sdk_e2e",
        )
    )
    connect = GatewayConnectClient(base_url, api_key=token, client=http).connect(
        ConnectRequest(
            metadata=_metadata("connect", idempotency_key="idem_connect_sdk_e2e"),
            quote_id=quote.quote_id,
            billing_session_id=billing["billing_session_id"],
            delivery_mode=fixture["access_grant"]["delivery_mode"],
            accepted_terms_hash=listing["terms_hash"],
            connector_preferences=ConnectorPreferences(
                preferred_connector_ids=[listing["connector_id"]],
                preferred_seller_edge_id=listing["seller_edge_id"],
                connection_types=["seller_edge"],
            ),
            seller_edge_id=listing["seller_edge_id"],
        )
    )
    invoke = GatewayInvokeClient(base_url, api_key=token, client=http).invoke(
        InvokeRequest(**backend_e2e._invoke_payload(fixture, token, {"access_grant_id": connect.access_grant_id}))
    )
    meter = GatewayMeterClient(base_url, api_key=token, client=http).record(
        MeterRecordRequest(
            metadata=_metadata("meter", idempotency_key="idem_meter_sdk_e2e"),
            access_grant_id=connect.access_grant_id,
            invocation_id=invoke.invocation_id,
            buyer_account_id=fixture["buyer_agent_token"]["account_id"],
            seller_account_id=fixture["seller_token"]["account_id"],
            listing_id=listing["listing_id"],
            listing_version_id=listing["listing_version_id"],
            connector_id=listing["connector_id"],
            event_type="invocation",
            measures=MeterMeasures(**fixture["meter_event_sequence"][0]["measures"]),
            artifact_hash=listing["artifact_hash"],
            occurred_at=fixture["meter_event_sequence"][0]["occurred_at"],
            seller_edge_identity_hash=listing["seller_edge_identity_hash"],
            signed_reference=backend_e2e._trust_set(fixture),
        )
    )
    receipts = GatewayReceiptClient(base_url, api_key=token, client=http).lookup(
        ReceiptLookupRequest(
            metadata=_metadata("receipt"),
            principal=ReceiptViewPrincipal(
                principal_type="buyer_agent",
                principal_id="agent_e2e",
                delegated_account_id=fixture["buyer_agent_token"]["account_id"],
            ),
            quote_id=quote.quote_id,
            access_grant_id=connect.access_grant_id,
        )
    )

    assert [capture["path"].rsplit("/", 1)[-1] for capture in captures]
    assert meter.access_grant_id == connect.access_grant_id
    assert receipts[0].quote_id == quote.quote_id
    assert CANONICAL_FLOW


def test_python_sdk_emitted_request_shapes_are_captured_for_gate3_contract_repair() -> None:
    backend_e2e = _load_backend_e2e_module()
    fixture = _load_fixture()
    state = backend_e2e.FlowState(fixture)
    test_client = backend_e2e.TestClient(backend_e2e._build_app(state), raise_server_exceptions=False)
    captures: list[dict[str, Any]] = []
    http = _TestClientAdapter(test_client, captures)

    with pytest.raises(Exception):
        GatewayDiscoverClient("http://testserver", api_key=fixture["buyer_agent_token"]["value"], client=http).discover(
            DiscoverRequest(metadata=_metadata("discover"), query="retail demand", limit=10)
        ).listings[0]

    assert captures[0]["path"] == "/v1/gateway/discover"
    assert captures[0]["request"]["metadata"]["request_id"] == "req_discover"
    assert captures[0]["status_code"] == 500
    assert "metadata" in json.dumps(captures[0]["request"])


def _json_or_text(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text


def _load_backend_e2e_module() -> Any:
    module_path = BACKEND_ROOT / "tests/gateway_v2/test_e2e_paid_buyer_agent_flow.py"
    spec = importlib.util.spec_from_file_location("backend_gateway_v2_e2e", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_fixture() -> dict[str, Any]:
    return json.loads((BACKEND_ROOT / "tests/fixtures/gateway_v2/e2e_paid_buyer_agent/flow.json").read_text())


def _metadata(suffix: str, *, idempotency_key: str | None = None) -> dict[str, Any]:
    return {
        "request_id": f"req_{suffix}",
        "principal_id": "agent_e2e",
        "account_id": "acct_buyer_e2e",
        "idempotency_key": idempotency_key,
        "request_timestamp": "2026-04-28T00:00:00Z",
        "nonce": f"nonce_{suffix}",
        "signed_envelope": "valid",
    }


def _policy(fixture: dict[str, Any]) -> BuyerPolicyEnvelope:
    token = fixture["buyer_agent_token"]
    return BuyerPolicyEnvelope(
        agent_id=token["principal_id"],
        delegated_user_id="usr_buyer_e2e",
        delegated_account_id=token["account_id"],
        scopes=["gateway:agent:act"],
        budget_cap=BuyerBudgetCap(per_session_cents=100_000, lifetime_cents=500_000),
    )
