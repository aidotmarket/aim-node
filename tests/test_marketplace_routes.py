from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock

from starlette.testclient import TestClient

from aim_node.management.app import create_management_app
from aim_node.management.errors import make_error
from aim_node.management.facade import FacadeError


def _app(tmp_path: Path):
    return create_management_app(tmp_path)


def test_marketplace_node_returns_backend_response(tmp_path: Path) -> None:
    facade = Mock()
    facade.get = AsyncMock(return_value={"node_id": "node-123"})
    app = _app(tmp_path)

    with TestClient(app) as client:
        app.state.facade = facade
        response = client.get("/api/mgmt/marketplace/node")

    assert response.status_code == 200
    assert response.json() == {"node_id": "node-123"}
    facade.get.assert_awaited_once_with("/aim/nodes/mine", cache_ttl_s=30.0)


def test_marketplace_node_facade_error_normalized(tmp_path: Path) -> None:
    normalized = make_error("market_error", "Marketplace returned an error")
    facade = Mock()
    facade.get = AsyncMock(side_effect=FacadeError(normalized, 502))
    app = _app(tmp_path)

    with TestClient(app) as client:
        app.state.facade = facade
        response = client.get("/api/mgmt/marketplace/node")

    assert response.status_code == 502
    assert response.json()["code"] == "market_error"


def test_marketplace_tools_publish_invalidates_cache(tmp_path: Path) -> None:
    facade = Mock(node_id="node-123")
    facade.post = AsyncMock(return_value={"published": True})
    facade.invalidate_cache = Mock()
    app = _app(tmp_path)

    with TestClient(app) as client:
        app.state.facade = facade
        response = client.post(
            "/api/mgmt/marketplace/tools/publish",
            json={"name": "tool"},
            headers={"Origin": "http://localhost:3000"},
        )

    assert response.status_code == 200
    facade.post.assert_awaited_once_with(
        "/aim/nodes/node-123/tools/publish",
        json_body={"name": "tool"},
    )
    facade.invalidate_cache.assert_called_once_with(
        "GET:/aim/nodes/node-123/tools"
    )


def test_marketplace_facade_none_returns_412(tmp_path: Path) -> None:
    app = _app(tmp_path)

    with TestClient(app) as client:
        app.state.facade = None
        response = client.get("/api/mgmt/marketplace/node")

    assert response.status_code == 412
    assert response.json()["code"] == "setup_incomplete"


def test_marketplace_discover_uses_post_to_backend(tmp_path: Path) -> None:
    facade = Mock()
    facade.post = AsyncMock(return_value={"results": []})
    facade.get = AsyncMock()
    app = _app(tmp_path)

    with TestClient(app) as client:
        app.state.facade = facade
        response = client.post(
            "/api/mgmt/marketplace/discover",
            json={"query": "agents"},
            headers={"Origin": "http://localhost:3000"},
        )

    assert response.status_code == 200
    facade.post.assert_awaited_once_with(
        "/aim/discover/search",
        json_body={"query": "agents"},
    )
    facade.get.assert_not_called()


def test_marketplace_trust_cache_ttl_300(tmp_path: Path) -> None:
    facade = Mock(node_id="node-123")
    facade.get = AsyncMock(return_value={"score": 99})
    app = _app(tmp_path)

    with TestClient(app) as client:
        app.state.facade = facade
        response = client.get("/api/mgmt/marketplace/trust")

    assert response.status_code == 200
    facade.get.assert_awaited_once_with(
        "/aim/nodes/node-123/trust",
        cache_ttl_s=300.0,
    )
