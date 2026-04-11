from __future__ import annotations

import base64
import hashlib
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from aim_node.core.crypto import DeviceCrypto


def _assert_status(response: httpx.Response, expected: tuple[int, ...]) -> None:
    assert response.status_code in expected, (
        f"unexpected status {response.status_code} for {response.request.method} "
        f"{response.request.url}: {response.text}"
    )


async def _register_node(
    client: httpx.AsyncClient,
    smoke_state: dict[str, object],
    smoke_cleanup: dict[str, list[str]],
    smoke_email: str,
    *,
    mode: str,
) -> dict[str, Any]:
    registrations = smoke_state.setdefault("registrations", {})
    cached = registrations.get(mode)
    if cached is not None:
        return cached

    seed = hashlib.sha256(
        f"aim-node-smoke:{smoke_email.lower()}:{mode}".encode("utf-8")
    ).digest()
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    public_key = private_key.public_key()
    public_key_b64 = base64.b64encode(public_key.public_bytes_raw()).decode("ascii")
    stable_suffix = hashlib.sha256(
        f"{smoke_email.lower()}:{mode}".encode("utf-8")
    ).hexdigest()[:16]
    # The production API does not expose a documented node deregistration route in this
    # repository, so smoke registration reuses a deterministic keypair and endpoint URL.
    # Re-running the suite updates the same logical node instead of creating unbounded
    # one-off registrations when cleanup endpoints are unavailable.
    endpoint_url = f"https://example.com/smoke-test-aim-node/{stable_suffix}/{mode}"

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
    signature = base64.urlsafe_b64encode(
        DeviceCrypto.sign(private_key, challenge.encode("utf-8"))
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
    smoke_cleanup["node_ids"].append(record["node_id"])
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
    smoke_cleanup: dict[str, list[str]],
    smoke_email: str,
) -> dict[str, Any]:
    cached = smoke_state.get("session")
    if cached is not None:
        return cached

    buyer_node = await _register_node(
        client,
        smoke_state,
        smoke_cleanup,
        smoke_email,
        mode="buyer",
    )
    listings = await _discover_listings(client, smoke_state)
    listing = next((item for item in listings if item.get("status") == "active"), None)
    if listing is None:
        pytest.skip("No active listings available for session negotiation")

    listing_id = listing.get("listing_id") or listing.get("id")
    assert listing_id, f"active listing missing identifier: {listing}"
    assert listing.get("tool_name"), f"active listing missing tool_name: {listing}"

    session_payload: dict[str, Any] | None = None
    try:
        response = await client.post(
            "/api/v1/aim/sessions",
            json={
                "node_id": buyer_node["node_id"],
                "listing_id": listing_id,
                "tool_name": listing["tool_name"],
                "spend_cap_cents": 0,
            },
        )
        _assert_status(response, (200, 201))

        session_payload = response.json()
        smoke_cleanup["session_ids"].append(session_payload["session_id"])
        smoke_state["session"] = session_payload
        return session_payload
    finally:
        if session_payload is not None and "session" not in smoke_state:
            response = await client.post(
                f"/api/v1/aim/sessions/{session_payload['session_id']}/close"
            )
            _assert_status(response, (200, 202, 204, 404, 405))


@pytest.mark.asyncio
async def test_health_check(smoke_client: httpx.AsyncClient) -> None:
    response = await smoke_client.get("/health")
    _assert_status(response, (200,))


@pytest.mark.asyncio
async def test_auth_valid(
    smoke_auth_client: httpx.AsyncClient,
) -> None:
    response = await smoke_auth_client.get("/api/v1/auth/me")
    _assert_status(response, (200,))
    payload = response.json()
    assert isinstance(payload.get("email"), str)
    assert payload["email"].strip()
    assert payload.get("user_id") or payload.get("id") or payload.get("sub"), (
        f"Missing user identifier in /auth/me response: {list(payload.keys())}"
    )


@pytest.mark.asyncio
async def test_consumer_register(
    smoke_client: httpx.AsyncClient,
    smoke_state: dict[str, object],
    smoke_cleanup: dict[str, list[str]],
    smoke_email: str,
) -> None:
    registration = await _register_node(
        smoke_client,
        smoke_state,
        smoke_cleanup,
        smoke_email,
        mode="buyer",
    )
    assert registration["node_id"]
    smoke_state["device_id"] = registration["node_id"]


@pytest.mark.asyncio
async def test_provider_register(
    smoke_client: httpx.AsyncClient,
    smoke_state: dict[str, object],
    smoke_cleanup: dict[str, list[str]],
    smoke_email: str,
) -> None:
    seller_node = await _register_node(
        smoke_client,
        smoke_state,
        smoke_cleanup,
        smoke_email,
        mode="seller",
    )
    # No relay-specific deregistration route is documented in this repository.
    # Cleanup falls back to node teardown in the session-scoped smoke_cleanup fixture.
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
    assert len(results) > 0, "Discovery returned no results — marketplace may be empty"
    assert all(
        isinstance(item, dict)
        and any(key in item and item[key] for key in ("id", "listing_id", "slug"))
        for item in results
    ), "Discovery results missing an identifier field"


@pytest.mark.asyncio
async def test_trace_submit(
) -> None:
    """Disabled in production smoke: trace-event writes have no cleanup endpoint."""
    pytest.skip(
        "Trace smoke test skipped because production trace-event writes cannot be cleaned up; cleanup is manual until the API exposes a delete or dry-run path"
    )
