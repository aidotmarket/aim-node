from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

BASE_URL = "https://api.ai.market"
DEFAULT_EMAIL = "max@bbi.com"


@pytest.fixture(scope="session")
def smoke_api_key() -> str | None:
    return os.environ.get("AIM_TEST_API_KEY")


@pytest.fixture(scope="session", autouse=True)
def require_smoke_api_key(smoke_api_key: str | None) -> None:
    if not smoke_api_key:
        pytest.skip("AIM_TEST_API_KEY is not set; skipping live smoke tests")


@pytest.fixture(scope="session")
def smoke_email() -> str:
    return os.environ.get("AIM_TEST_EMAIL", DEFAULT_EMAIL)


@pytest.fixture(scope="session")
def test_run_id() -> str:
    return uuid.uuid4().hex[:12]


@pytest.fixture(scope="session")
def smoke_state() -> dict[str, object]:
    return {}


@pytest_asyncio.fixture(scope="session")
async def smoke_client(smoke_api_key: str) -> AsyncIterator[httpx.AsyncClient]:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {smoke_api_key}",
        # The live AIM API advertises X-Internal-API-Key for several node endpoints.
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
