from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from aim_node.core.crypto import DeviceCrypto


def _assert_status(response: httpx.Response, expected: tuple[int, ...]) -> None:
    assert response.status_code in expected, (
        f"unexpected status {response.status_code} for {response.request.method} "
        f"{response.request.url}: {response.text}"
    )


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def _register_node(
    client: httpx.AsyncClient,
    smoke_state: dict[str, object],
    test_run_id: str,
    *,
    mode: str,
) -> dict[str, Any]:
    registrations = smoke_state.setdefault("registrations", {})
    cached = registrations.get(mode)
    if cached is not None:
        return cached

    private_key, public_key = DeviceCrypto.generate_ed25519_keypair()
    public_key_b64 = base64.b64encode(public_key.public_bytes_raw()).decode("ascii")
    endpoint_url = f"https://example.com/aim-node-smoke/{test_run_id}/{mode}"

    challenge_response = await client.post(
        "/api/v1/aim/nodes/register/challenge",
        json={
            "endpoint_url": endpoint_url,
            "public_key": public_key_b64,
            "mode": mode,
        },
    )
    _assert_status(challenge_response, (200,))

    challenge = challenge_response.json()["challenge"]
    signature = base64.b64encode(
        DeviceCrypto.sign(private_key, bytes.fromhex(challenge))
    ).decode("ascii")

    register_response = await client.post(
        "/api/v1/aim/nodes/register",
        json={
            "endpoint_url": endpoint_url,
            "public_key": public_key_b64,
            "mode": mode,
            "challenge": challenge,
            "pop_signature": signature,
        },
    )
    _assert_status(register_response, (200, 201))

    payload = register_response.json()
    record = {
        "node_id": payload["node_id"],
        "status": payload.get("status"),
        "created_at": payload.get("created_at"),
        "mode": mode,
        "endpoint_url": endpoint_url,
    }
    registrations[mode] = record
    return record


async def _discover_listings(
    client: httpx.AsyncClient,
    smoke_state: dict[str, object],
) -> list[dict[str, Any]]:
    cached = smoke_state.get("discover_results")
    if cached is not None:
        return cached

    response = await client.post("/api/v1/aim/discover/search", json={"limit": 5})
    _assert_status(response, (200,))
    payload = response.json()
    results = payload.get("results", [])
    assert isinstance(results, list), f"unexpected discovery payload: {payload}"
    smoke_state["discover_results"] = results
    return results


async def _negotiate_session(
    client: httpx.AsyncClient,
    smoke_state: dict[str, object],
    test_run_id: str,
) -> dict[str, Any]:
    cached = smoke_state.get("session")
    if cached is not None:
        return cached

    buyer_node = await _register_node(client, smoke_state, test_run_id, mode="buyer")
    listings = await _discover_listings(client, smoke_state)
    listing = next((item for item in listings if item.get("status") == "active"), None)
    if listing is None and listings:
        listing = listings[0]
    if listing is None:
        pytest.skip("No AIM listings are currently discoverable in production")

    response = await client.post(
        "/api/v1/aim/sessions",
        json={
            "node_id": buyer_node["node_id"],
            "listing_id": listing["listing_id"],
            "tool_name": listing["tool_name"],
            "spend_cap_cents": 0,
        },
    )
    _assert_status(response, (200, 201))

    payload = response.json()
    smoke_state["session"] = payload
    return payload


@pytest.mark.asyncio
async def test_health_check(smoke_client: httpx.AsyncClient) -> None:
    response = await smoke_client.get("/health")
    _assert_status(response, (200,))


@pytest.mark.asyncio
async def test_auth_valid(
    smoke_client: httpx.AsyncClient, smoke_email: str
) -> None:
    response = await smoke_client.get("/api/v1/auth/me")
    _assert_status(response, (200,))
    payload = response.json()
    assert payload["email"] == smoke_email


@pytest.mark.asyncio
async def test_device_register(
    smoke_client: httpx.AsyncClient,
    smoke_state: dict[str, object],
    test_run_id: str,
) -> None:
    registration = await _register_node(
        smoke_client, smoke_state, test_run_id, mode="buyer"
    )
    assert registration["node_id"]
    smoke_state["device_id"] = registration["node_id"]


@pytest.mark.asyncio
async def test_provider_register(
    smoke_client: httpx.AsyncClient,
    smoke_state: dict[str, object],
    test_run_id: str,
) -> None:
    seller_node = await _register_node(
        smoke_client, smoke_state, test_run_id, mode="seller"
    )
    response = await smoke_client.post(
        "/api/v1/aim/relay/register",
        json={"node_id": seller_node["node_id"]},
    )
    _assert_status(response, (200, 201))
    payload = response.json()
    assert payload["node_id"] == seller_node["node_id"]
    assert isinstance(payload["relay_mode"], bool)


@pytest.mark.asyncio
async def test_consumer_discovery(
    smoke_client: httpx.AsyncClient, smoke_state: dict[str, object]
) -> None:
    results = await _discover_listings(smoke_client, smoke_state)
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_trace_submit(
    smoke_client: httpx.AsyncClient,
    smoke_state: dict[str, object],
    test_run_id: str,
) -> None:
    session = await _negotiate_session(smoke_client, smoke_state, test_run_id)
    timestamp = _now_iso()
    response = await smoke_client.post(
        "/api/v1/aim/traces/events",
        json={
            "event": {
                "trace_id": session["trace_id"],
                "session_id": session["session_id"],
                "event_type": "request_sent",
                "source": "buyer_app",
                "node_timestamp": timestamp,
                "metadata": {"test_run_id": test_run_id},
            },
            "signature": "0" * 64,
            "timestamp": timestamp,
            "nonce": f"{test_run_id}trace1234",
        },
    )
    _assert_status(response, (200, 201))
    payload = response.json()
    assert payload["event_id"]
