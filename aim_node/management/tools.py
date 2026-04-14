"""Local upstream tool discovery and validation handlers."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse

from aim_node.core.config import AIMCoreConfig
from aim_node.management.errors import ErrorCode, make_error
from aim_node.management.routes import _parse_body
from aim_node.management.schemas import (
    TestUpstreamRequest,
    TestUpstreamResponse,
    ToolDetailResponse,
    ToolListResponse,
    ToolSummary,
    ToolValidationResponse,
)
from aim_node.management.state import read_store, write_store

logger = logging.getLogger(__name__)

TOOLS_STORE_KEY = "discovered_tools"
_AsyncClient = httpx.AsyncClient


class UpstreamUnreachableError(Exception):
    pass


class UpstreamTimeoutError(Exception):
    pass


class ToolLookupError(Exception):
    pass


class ToolValidationFailedError(Exception):
    pass


@dataclass
class DiscoveredTool:
    tool_id: str
    name: str
    version: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    last_scanned_at: str
    last_validated_at: str | None
    validation_status: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tool_id(name: str, version: str) -> str:
    return hashlib.sha256(f"{name}:{version}".encode("utf-8")).hexdigest()[:12]


def _tools_list_url(upstream_url: str) -> str:
    return f"{upstream_url.rstrip('/')}/tools/list"


def _tools_call_url(upstream_url: str) -> str:
    return f"{upstream_url.rstrip('/')}/tools/call"


def _normalize_tools(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        candidate = payload.get("tools", [])
    elif isinstance(payload, list):
        candidate = payload
    else:
        candidate = []

    normalized: list[dict[str, Any]] = []
    for item in candidate:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        version = str(item.get("version") or "unknown")
        normalized.append(
            {
                "name": name,
                "version": version,
                "description": str(item.get("description") or ""),
                "input_schema": item.get("input_schema") or item.get("inputSchema") or {},
                "output_schema": item.get("output_schema") or item.get("outputSchema") or {},
            }
        )
    return normalized


def _minimal_value(schema: dict[str, Any]) -> Any:
    schema_type = schema.get("type")
    if "default" in schema:
        return schema["default"]
    if "enum" in schema and isinstance(schema["enum"], list) and schema["enum"]:
        return schema["enum"][0]
    if schema_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        result: dict[str, Any] = {}
        if isinstance(properties, dict):
            for key in required:
                prop_schema = properties.get(key, {})
                if isinstance(prop_schema, dict):
                    result[key] = _minimal_value(prop_schema)
        return result
    if schema_type == "array":
        return []
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0
    if schema_type == "boolean":
        return False
    return ""


def _matches_schema(value: Any, schema: dict[str, Any]) -> bool:
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            return False
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if key not in value:
                    return False
        if isinstance(properties, dict):
            for key, prop_schema in properties.items():
                if key in value and isinstance(prop_schema, dict):
                    if not _matches_schema(value[key], prop_schema):
                        return False
        return True
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def _load_cached_tools(data_dir: Path) -> dict[str, Any]:
    cached = read_store(data_dir, TOOLS_STORE_KEY)
    if cached is None:
        return {"scanned_at": None, "tools": []}
    return cached


def _update_cached_tool(
    data_dir: Path,
    tool_id: str,
    *,
    validation_status: str,
    last_validated_at: str,
) -> dict[str, Any]:
    cached = _load_cached_tools(data_dir)
    tools = cached.get("tools", [])
    for tool in tools:
        if tool.get("tool_id") == tool_id:
            tool["validation_status"] = validation_status
            tool["last_validated_at"] = last_validated_at
            write_store(data_dir, TOOLS_STORE_KEY, cached)
            return tool
    raise ToolLookupError("Tool not found")


def _config_upstream_url(config: AIMCoreConfig) -> str:
    upstream_url = getattr(config, "upstream_url", None)
    if not upstream_url:
        raise UpstreamUnreachableError("Upstream URL is not configured")
    return upstream_url


async def _get_json(url: str, *, timeout_s: float) -> tuple[Any, int]:
    try:
        async with _AsyncClient() as client:
            start = time.monotonic()
            response = await client.get(url, timeout=timeout_s)
            latency_ms = int((time.monotonic() - start) * 1000)
            response.raise_for_status()
            return response.json(), latency_ms
    except httpx.TimeoutException as exc:
        raise UpstreamTimeoutError("Upstream request timed out") from exc
    except httpx.RequestError as exc:
        raise UpstreamUnreachableError("Unable to reach upstream") from exc
    except httpx.HTTPStatusError as exc:
        raise UpstreamUnreachableError(
            f"Upstream returned HTTP {exc.response.status_code}"
        ) from exc


async def scan_upstream(config: AIMCoreConfig, data_dir: Path) -> list[dict[str, Any]]:
    upstream_url = _config_upstream_url(config)
    payload, _ = await _get_json(_tools_list_url(upstream_url), timeout_s=10.0)
    scanned_at = _now_iso()
    tools = [
        asdict(
            DiscoveredTool(
                tool_id=_tool_id(tool["name"], tool["version"]),
                name=tool["name"],
                version=tool["version"],
                description=tool["description"],
                input_schema=tool["input_schema"],
                output_schema=tool["output_schema"],
                last_scanned_at=scanned_at,
                last_validated_at=None,
                validation_status="pending",
            )
        )
        for tool in _normalize_tools(payload)
    ]
    write_store(
        data_dir,
        TOOLS_STORE_KEY,
        {"scanned_at": scanned_at, "tools": tools},
    )
    return tools


async def validate_tool(
    tool_id: str, config: AIMCoreConfig, data_dir: Path
) -> dict[str, Any]:
    upstream_url = _config_upstream_url(config)
    cached = _load_cached_tools(data_dir)
    tools = cached.get("tools", [])
    tool = next((item for item in tools if item.get("tool_id") == tool_id), None)
    if tool is None:
        raise ToolLookupError("Tool not found")

    sample_input = _minimal_value(tool.get("input_schema") or {})
    try:
        async with _AsyncClient() as client:
            start = time.monotonic()
            response = await client.post(
                _tools_call_url(upstream_url),
                json={"name": tool["name"], "arguments": sample_input},
                timeout=10.0,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException as exc:
        raise UpstreamTimeoutError("Upstream request timed out") from exc
    except httpx.RequestError as exc:
        raise UpstreamUnreachableError("Unable to reach upstream") from exc
    except httpx.HTTPStatusError as exc:
        last_validated_at = _now_iso()
        _update_cached_tool(
            data_dir,
            tool_id,
            validation_status="failed",
            last_validated_at=last_validated_at,
        )
        raise ToolValidationFailedError(
            f"Tool invocation failed with HTTP {exc.response.status_code}"
        ) from exc

    result = payload
    if isinstance(payload, dict) and "result" in payload:
        result = payload["result"]
    elif isinstance(payload, dict) and "output" in payload:
        result = payload["output"]

    if not _matches_schema(result, tool.get("output_schema") or {}):
        last_validated_at = _now_iso()
        _update_cached_tool(
            data_dir,
            tool_id,
            validation_status="failed",
            last_validated_at=last_validated_at,
        )
        raise ToolValidationFailedError("Tool response did not match output schema")

    last_validated_at = _now_iso()
    _update_cached_tool(
        data_dir,
        tool_id,
        validation_status="passed",
        last_validated_at=last_validated_at,
    )
    return {
        "tool_id": tool_id,
        "status": "passed",
        "latency_ms": latency_ms,
        "error": None,
    }


async def _probe_upstream(url: str, timeout_s: float) -> tuple[int, int]:
    payload, latency_ms = await _get_json(_tools_list_url(url), timeout_s=timeout_s)
    return latency_ms, len(_normalize_tools(payload))


def _tools_list_response(data_dir: Path) -> ToolListResponse:
    cached = _load_cached_tools(data_dir)
    tools = [
        ToolSummary(
            tool_id=tool["tool_id"],
            name=tool["name"],
            version=tool["version"],
            description=tool["description"],
            validation_status=tool["validation_status"],
            last_scanned_at=tool["last_scanned_at"],
        )
        for tool in cached.get("tools", [])
    ]
    return ToolListResponse(tools=tools, scanned_at=cached.get("scanned_at"))


def _tool_detail_response(data_dir: Path, tool_id: str) -> ToolDetailResponse:
    cached = _load_cached_tools(data_dir)
    for tool in cached.get("tools", []):
        if tool.get("tool_id") == tool_id:
            return ToolDetailResponse(**tool)
    raise ToolLookupError("Tool not found")


def _error_response(code: str, message: str, *, details: dict[str, Any] | None = None) -> JSONResponse:
    err = make_error(code, message, details=details)
    status_code = {
        ErrorCode.NOT_FOUND: 404,
        ErrorCode.TOOL_VALIDATION_FAILED: 422,
        ErrorCode.UPSTREAM_UNREACHABLE: 502,
        ErrorCode.UPSTREAM_TIMEOUT: 504,
    }[code]
    return JSONResponse(err.model_dump(exclude_none=True), status_code=status_code)


def _state_config(request: Request) -> AIMCoreConfig | None:
    return request.app.state.store._load_config()


async def tools_list_local(request: Request) -> JSONResponse:
    data_dir: Path = request.app.state.store._data_dir
    return JSONResponse(_tools_list_response(data_dir).model_dump())


async def tools_discover(request: Request) -> JSONResponse:
    data_dir: Path = request.app.state.store._data_dir
    config = _state_config(request)
    if config is None:
        return _error_response(
            ErrorCode.UPSTREAM_UNREACHABLE,
            "Upstream URL is not configured",
        )
    try:
        await scan_upstream(config, data_dir)
        return JSONResponse(_tools_list_response(data_dir).model_dump())
    except UpstreamTimeoutError as exc:
        return _error_response(ErrorCode.UPSTREAM_TIMEOUT, str(exc))
    except UpstreamUnreachableError as exc:
        return _error_response(ErrorCode.UPSTREAM_UNREACHABLE, str(exc))


async def tools_detail(request: Request) -> JSONResponse:
    data_dir: Path = request.app.state.store._data_dir
    tool_id = request.path_params.get("tool_id", "")
    try:
        return JSONResponse(_tool_detail_response(data_dir, tool_id).model_dump())
    except ToolLookupError as exc:
        return _error_response(ErrorCode.NOT_FOUND, str(exc))


async def tools_validate(request: Request) -> JSONResponse:
    data_dir: Path = request.app.state.store._data_dir
    config = _state_config(request)
    tool_id = request.path_params.get("tool_id", "")
    if config is None:
        return _error_response(
            ErrorCode.UPSTREAM_UNREACHABLE,
            "Upstream URL is not configured",
        )
    try:
        result = await validate_tool(tool_id, config, data_dir)
        return JSONResponse(ToolValidationResponse(**result).model_dump())
    except ToolLookupError as exc:
        return _error_response(ErrorCode.NOT_FOUND, str(exc))
    except UpstreamTimeoutError as exc:
        return _error_response(ErrorCode.UPSTREAM_TIMEOUT, str(exc))
    except UpstreamUnreachableError as exc:
        return _error_response(ErrorCode.UPSTREAM_UNREACHABLE, str(exc))
    except ToolValidationFailedError as exc:
        return _error_response(
            ErrorCode.TOOL_VALIDATION_FAILED,
            str(exc),
            details={"tool_id": tool_id},
        )


async def setup_test_upstream(request: Request) -> JSONResponse:
    body = await _parse_body(request, TestUpstreamRequest)
    try:
        latency_ms, tools_found = await _probe_upstream(body.url, body.timeout_s)
        response = TestUpstreamResponse(
            reachable=True,
            latency_ms=latency_ms,
            tools_found=tools_found,
            error=None,
        )
        return JSONResponse(response.model_dump())
    except UpstreamTimeoutError as exc:
        return _error_response(ErrorCode.UPSTREAM_TIMEOUT, str(exc))
    except UpstreamUnreachableError as exc:
        return _error_response(ErrorCode.UPSTREAM_UNREACHABLE, str(exc))
