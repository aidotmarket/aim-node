from __future__ import annotations

import os
import uuid
import warnings
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

BASE_URL = "https://api.ai.market"


async def _close_session(client: httpx.AsyncClient, session_id: str) -> None:
    response = await client.post(f"/api/v1/aim/sessions/{session_id}/close")
    if response.status_code not in {200, 202, 204, 404, 405}:
        warnings.warn(
            f"session cleanup failed for {session_id}: "
            f"{response.status_code} {response.text}",
            stacklevel=2,
        )


@pytest.fixture(scope="session")
def smoke_api_key() -> str:
    smoke_api_key = os.environ.get("AIM_TEST_API_KEY")
    if not smoke_api_key:
        pytest.exit("AIM_TEST_API_KEY not set — aborting smoke suite", returncode=1)
    return smoke_api_key


@pytest.fixture(scope="session")
def event_loop_policy():
    import asyncio

    return asyncio.DefaultEventLoopPolicy()


async def _cleanup_node_registration(
    client: httpx.AsyncClient, node_id: str
) -> None:
    cleanup_attempts = (
        ("DELETE", f"/api/v1/aim/nodes/{node_id}"),
        ("POST", f"/api/v1/aim/nodes/{node_id}/deregister"),
        ("DELETE", f"/api/v1/aim/nodes/{node_id}/deregister"),
    )
    for method, path in cleanup_attempts:
        response = await client.request(method, path)
        if response.status_code in {200, 202, 204, 404, 405}:
            if response.status_code not in {404, 405}:
                return
            continue
        warnings.warn(
            f"node cleanup failed for {node_id} via {method} {path}: "
            f"{response.status_code} {response.text}",
            stacklevel=2,
        )
        return


@pytest.fixture(scope="session")
def smoke_email() -> str:
    value = os.environ.get("AIM_TEST_EMAIL")
    if not value:
        pytest.exit("AIM_TEST_EMAIL not set", returncode=1)
    return value


@pytest.fixture(scope="session", autouse=True)
def require_smoke_env(smoke_api_key: str, smoke_email: str) -> None:
    del smoke_api_key, smoke_email


@pytest.fixture(scope="session")
def test_run_id() -> str:
    return uuid.uuid4().hex[:12]


@pytest.fixture(scope="session")
def smoke_state() -> dict[str, object]:
    return {}


@pytest_asyncio.fixture(scope="session")
async def smoke_auth_client(smoke_api_key: str) -> AsyncIterator[httpx.AsyncClient]:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {smoke_api_key}",
    }
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        headers=headers,
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def smoke_client(smoke_api_key: str) -> AsyncIterator[httpx.AsyncClient]:
    headers = {
        "Accept": "application/json",
        # Internal smoke endpoints expect the API key in X-Internal-API-Key, not Bearer auth.
        "X-Internal-API-Key": smoke_api_key,
    }
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        headers=headers,
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def smoke_cleanup(
    smoke_client: httpx.AsyncClient,
) -> AsyncIterator[dict[str, list[str]]]:
    tracked = {"node_ids": [], "session_ids": []}
    yield tracked

    for session_id in reversed(tracked["session_ids"]):
        await _close_session(smoke_client, session_id)

    for node_id in reversed(tracked["node_ids"]):
        await _cleanup_node_registration(smoke_client, node_id)
