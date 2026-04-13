from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from aim_node.management.errors import ErrorCode, make_error
from aim_node.management.facade import FacadeError, MarketplaceFacade


def _facade(request: Request) -> MarketplaceFacade | None:
    return request.app.state.facade


def _facade_unavailable() -> JSONResponse:
    err = make_error(ErrorCode.SETUP_INCOMPLETE, "Node not yet configured")
    return JSONResponse(err.model_dump(exclude_none=True), status_code=412)


def _facade_error(exc: FacadeError) -> JSONResponse:
    return JSONResponse(
        exc.normalized.model_dump(exclude_none=True),
        status_code=exc.http_status,
    )


async def marketplace_node(request: Request) -> JSONResponse:
    facade = _facade(request)
    if facade is None:
        return _facade_unavailable()
    try:
        data = await facade.get("/aim/nodes/mine", cache_ttl_s=30.0)
    except FacadeError as exc:
        return _facade_error(exc)
    return JSONResponse(data)


async def tools_list(request: Request) -> JSONResponse:
    facade = _facade(request)
    if facade is None:
        return _facade_unavailable()
    try:
        data = await facade.get(
            f"/aim/nodes/{facade.node_id}/tools",
            cache_ttl_s=30.0,
        )
    except FacadeError as exc:
        return _facade_error(exc)
    return JSONResponse(data)


async def tools_publish(request: Request) -> JSONResponse:
    facade = _facade(request)
    if facade is None:
        return _facade_unavailable()
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        data = await facade.post(
            f"/aim/nodes/{facade.node_id}/tools/publish",
            json_body=body,
        )
    except FacadeError as exc:
        return _facade_error(exc)
    facade.invalidate_cache(f"GET:/aim/nodes/{facade.node_id}/tools")
    return JSONResponse(data)


async def tool_update(request: Request) -> JSONResponse:
    tool_id = request.path_params["tool_id"]
    facade = _facade(request)
    if facade is None:
        return _facade_unavailable()
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        data = await facade.put(
            f"/aim/nodes/{facade.node_id}/tools/{tool_id}",
            json_body=body,
        )
    except FacadeError as exc:
        return _facade_error(exc)
    facade.invalidate_cache(f"GET:/aim/nodes/{facade.node_id}/tools")
    return JSONResponse(data)


async def tool_delete(request: Request) -> JSONResponse:
    tool_id = request.path_params["tool_id"]
    facade = _facade(request)
    if facade is None:
        return _facade_unavailable()
    try:
        data = await facade.delete(f"/aim/nodes/{facade.node_id}/tools/{tool_id}")
    except FacadeError as exc:
        return _facade_error(exc)
    facade.invalidate_cache(f"GET:/aim/nodes/{facade.node_id}/tools")
    return JSONResponse(data)


async def marketplace_earnings(request: Request) -> JSONResponse:
    facade = _facade(request)
    if facade is None:
        return _facade_unavailable()
    range_param = request.query_params.get("range", "7d")
    try:
        data = await facade.get(
            "/aim/payouts/summary",
            params={"node_id": facade.node_id, "range": range_param},
            cache_ttl_s=60.0,
        )
    except FacadeError as exc:
        return _facade_error(exc)
    return JSONResponse(data)


async def earnings_history(request: Request) -> JSONResponse:
    facade = _facade(request)
    if facade is None:
        return _facade_unavailable()
    try:
        data = await facade.get("/aim/payouts/history", cache_ttl_s=60.0)
    except FacadeError as exc:
        return _facade_error(exc)
    return JSONResponse(data)


async def sessions(request: Request) -> JSONResponse:
    facade = _facade(request)
    if facade is None:
        return _facade_unavailable()
    range_param = request.query_params.get("range", "7d")
    try:
        data = await facade.get(
            "/aim/sessions",
            params={"node_id": facade.node_id, "range": range_param},
        )
    except FacadeError as exc:
        return _facade_error(exc)
    return JSONResponse(data)


async def settlements(request: Request) -> JSONResponse:
    facade = _facade(request)
    if facade is None:
        return _facade_unavailable()
    range_param = request.query_params.get("range", "30d")
    try:
        data = await facade.get(
            "/aim/settlements",
            params={"node_id": facade.node_id, "range": range_param},
            cache_ttl_s=60.0,
        )
    except FacadeError as exc:
        return _facade_error(exc)
    return JSONResponse(data)


async def marketplace_trust(request: Request) -> JSONResponse:
    facade = _facade(request)
    if facade is None:
        return _facade_unavailable()
    try:
        data = await facade.get(
            f"/aim/nodes/{facade.node_id}/trust",
            cache_ttl_s=300.0,
        )
    except FacadeError as exc:
        return _facade_error(exc)
    return JSONResponse(data)


async def trust_events(request: Request) -> JSONResponse:
    facade = _facade(request)
    if facade is None:
        return _facade_unavailable()
    try:
        data = await facade.get(
            f"/aim/nodes/{facade.node_id}/trust/events",
            cache_ttl_s=300.0,
        )
    except FacadeError as exc:
        return _facade_error(exc)
    return JSONResponse(data)


async def traces(request: Request) -> JSONResponse:
    facade = _facade(request)
    if facade is None:
        return _facade_unavailable()
    limit = request.query_params.get("limit", "50")
    try:
        data = await facade.get(
            "/aim/observability/traces",
            params={"node_id": facade.node_id, "limit": limit},
        )
    except FacadeError as exc:
        return _facade_error(exc)
    return JSONResponse(data)


async def listings(request: Request) -> JSONResponse:
    facade = _facade(request)
    if facade is None:
        return _facade_unavailable()
    try:
        data = await facade.get(
            "/listings",
            params={"node_id": facade.node_id},
            cache_ttl_s=30.0,
        )
    except FacadeError as exc:
        return _facade_error(exc)
    return JSONResponse(data)


async def discover(request: Request) -> JSONResponse:
    facade = _facade(request)
    if facade is None:
        return _facade_unavailable()
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        data = await facade.post("/aim/discover/search", json_body=body)
    except FacadeError as exc:
        return _facade_error(exc)
    return JSONResponse(data)
