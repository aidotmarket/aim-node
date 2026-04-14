"""Local allAI chat orchestration for the management UI."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from aim_node.management.config_writer import read_config
from aim_node.management.errors import ErrorCode, make_error
from aim_node.management.logs import _tail_entries
from aim_node.management.routes import _parse_body
from aim_node.management.state import ProcessStateStore, read_store

logger = logging.getLogger(__name__)

ALLOWED_TOOLS = [
    "inspect_local_config",
    "test_market_auth",
    "scan_provider_endpoint",
    "list_local_tools",
    "tail_recent_logs",
    "explain_last_failure",
]
MAX_AUTO_EXEC_DEPTH = 5
_AsyncClient = httpx.AsyncClient


class AllAIChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ProposedAction(BaseModel):
    action_id: str
    description: str
    tool_name: str
    params: dict[str, Any]
    requires_confirmation: bool


class AllAIChatResponse(BaseModel):
    reply: str
    conversation_id: str
    proposed_actions: list[ProposedAction] | None = None
    suggestions: list[str] | None = None


class AllAIConfirmRequest(BaseModel):
    action_id: str
    approved: bool


class AllAIConfirmResponse(BaseModel):
    status: str
    result: dict[str, Any] | None = None


def _error_response(code: str, message: str, status_code: int) -> JSONResponse:
    err = make_error(code, message)
    return JSONResponse(err.model_dump(exclude_none=True), status_code=status_code)


def _sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return (
        normalized.endswith("_passphrase")
        or normalized in {"passphrase", "api_key", "session_token", "csrf_token"}
        or normalized.endswith("_api_key")
        or normalized.endswith("_session_token")
        or normalized.endswith("_csrf_token")
        or normalized.endswith("_token")
        or normalized == "token"
    )


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            redacted[key] = "[redacted]" if _sensitive_key(key) else _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _data_dir(store: ProcessStateStore) -> Any:
    return store._data_dir


def _node_id(request: Request) -> str:
    facade = getattr(request.app.state, "facade", None)
    if facade is not None and getattr(facade, "node_id", None):
        return str(facade.node_id)
    store = request.app.state.store
    config = read_config(_data_dir(store))
    core = config.get("core", {}) if isinstance(config, dict) else {}
    return str(core.get("node_id") or core.get("node_serial") or "")


def _gather_context(request: Request) -> tuple[dict[str, Any], bool]:
    store = request.app.state.store
    data_dir = _data_dir(store)
    context: dict[str, Any] = {}
    degraded = False

    try:
        context["status"] = _redact(store.get_status())
    except Exception:
        degraded = True
    try:
        context["sessions"] = _redact(store.get_sessions())
    except Exception:
        degraded = True
    try:
        context["dashboard"] = _redact(store.get_dashboard())
    except Exception:
        degraded = True
    try:
        context["discovered_tools"] = _redact(read_store(data_dir, "discovered_tools") or {})
    except Exception:
        degraded = True

    return context, degraded


async def _tool_inspect_local_config(request: Request, params: dict[str, Any]) -> dict[str, Any]:
    store = request.app.state.store
    config = read_config(_data_dir(store))
    return {"config": _redact(config)}


async def _tool_test_market_auth(request: Request, params: dict[str, Any]) -> dict[str, Any]:
    facade = getattr(request.app.state, "facade", None)
    if facade is None:
        return {"ok": False, "reason": "facade_unavailable"}
    data = await facade.get("/aim/nodes/mine")
    return {"ok": True, "node": _redact(data)}


async def _tool_scan_provider_endpoint(request: Request, params: dict[str, Any]) -> dict[str, Any]:
    store = request.app.state.store
    config = read_config(_data_dir(store))
    provider = config.get("provider", {}) if isinstance(config, dict) else {}
    adapter = provider.get("adapter", {}) if isinstance(provider, dict) else {}
    endpoint_url = adapter.get("endpoint_url")
    if not endpoint_url:
        return {"reachable": False, "reason": "endpoint_not_configured"}

    try:
        async with _AsyncClient() as client:
            start = time.monotonic()
            response = await client.get(endpoint_url, timeout=3)
            latency_ms = round((time.monotonic() - start) * 1000.0, 2)
    except Exception as exc:
        return {"reachable": False, "url": endpoint_url, "error": str(exc)}

    return {
        "reachable": 200 <= response.status_code < 500,
        "url": endpoint_url,
        "status_code": response.status_code,
        "latency_ms": latency_ms,
    }


async def _tool_list_local_tools(request: Request, params: dict[str, Any]) -> dict[str, Any]:
    store = request.app.state.store
    cached = read_store(_data_dir(store), "discovered_tools") or {}
    return {"tools": _redact(cached)}


async def _tool_tail_recent_logs(request: Request, params: dict[str, Any]) -> dict[str, Any]:
    limit_raw = params.get("limit", 20)
    try:
        limit = max(1, min(int(limit_raw), 100))
    except Exception:
        limit = 20
    handler = request.app.state.log_handler
    return {"entries": _tail_entries(handler, limit=limit)}


async def _tool_explain_last_failure(request: Request, params: dict[str, Any]) -> dict[str, Any]:
    handler = request.app.state.log_handler
    entries = list(handler.buffer)
    for entry in reversed(entries):
        if entry.get("level") in {"ERROR", "CRITICAL"}:
            return {
                "summary": entry.get("message") or "Recent failure found",
                "entry": entry,
            }
    return {"summary": "No recent failure found", "entry": None}


_LOCAL_TOOL_HANDLERS = {
    "inspect_local_config": _tool_inspect_local_config,
    "test_market_auth": _tool_test_market_auth,
    "scan_provider_endpoint": _tool_scan_provider_endpoint,
    "list_local_tools": _tool_list_local_tools,
    "tail_recent_logs": _tool_tail_recent_logs,
    "explain_last_failure": _tool_explain_last_failure,
}


async def _execute_action(request: Request, action: ProposedAction) -> dict[str, Any]:
    if action.tool_name not in ALLOWED_TOOLS:
        raise HTTPException(403, f"Tool {action.tool_name} is not allowed")
    handler = _LOCAL_TOOL_HANDLERS.get(action.tool_name)
    if handler is None:
        raise HTTPException(404, f"Tool {action.tool_name} is not available")
    params = action.params if isinstance(action.params, dict) else {}
    return await handler(request, params)


def _cache_action(request: Request, action: ProposedAction) -> None:
    cache = getattr(request.app.state, "allai_action_cache", None)
    if cache is None:
        cache = {}
        request.app.state.allai_action_cache = cache
    cache[action.action_id] = action


def _append_execution_reply(reply: str, executed: list[tuple[ProposedAction, dict[str, Any]]]) -> str:
    if not executed:
        return reply
    lines = [reply.rstrip(), "", "Local action results:"]
    for action, result in executed:
        rendered = json.dumps(result, sort_keys=True, default=str)
        lines.append(f"- {action.tool_name}: {rendered}")
    return "\n".join(line for line in lines if line is not None)


def _coerce_actions(items: Any) -> list[ProposedAction]:
    actions: list[ProposedAction] = []
    if not isinstance(items, list):
        return actions
    for item in items:
        if not isinstance(item, dict):
            continue
        actions.append(ProposedAction(**item))
    return actions


async def allai_chat(request: Request) -> JSONResponse:
    body = await _parse_body(request, AllAIChatRequest)
    facade = getattr(request.app.state, "facade", None)
    if facade is None:
        return _error_response(ErrorCode.SETUP_INCOMPLETE, "Node not yet configured", 412)

    context, degraded_context = _gather_context(request)
    payload: dict[str, Any] = {
        "message": body.message,
        "context": context,
        "node_id": _node_id(request),
        "conversation_id": body.conversation_id,
        "allowed_tools": ALLOWED_TOOLS,
    }
    if degraded_context:
        payload["degraded_context"] = True

    reply = ""
    suggestions: list[str] | None = None
    conversation_id = body.conversation_id or ""
    pending_actions: list[ProposedAction] = []
    executed: list[tuple[ProposedAction, dict[str, Any]]] = []
    tool_results: list[dict[str, Any]] = []

    for depth in range(MAX_AUTO_EXEC_DEPTH):
        if tool_results:
            payload["tool_results"] = tool_results
        data = await facade.post("/allie/chat/agentic", json_body=payload)
        parsed = AllAIChatResponse(
            reply=str(data.get("reply") or ""),
            conversation_id=str(data.get("conversation_id") or conversation_id or ""),
            proposed_actions=_coerce_actions(data.get("proposed_actions")) or None,
            suggestions=data.get("suggestions"),
        )

        reply = parsed.reply
        conversation_id = parsed.conversation_id
        suggestions = parsed.suggestions
        actions = parsed.proposed_actions or []

        auto_actions: list[ProposedAction] = []
        pending_actions = []
        for action in actions:
            if action.requires_confirmation:
                pending_actions.append(action)
                continue
            if action.tool_name in ALLOWED_TOOLS:
                auto_actions.append(action)
                continue
            pending_actions.append(
                ProposedAction(
                    action_id=action.action_id,
                    description=action.description,
                    tool_name=action.tool_name,
                    params=action.params,
                    requires_confirmation=True,
                )
            )

        if not auto_actions:
            break

        if depth == MAX_AUTO_EXEC_DEPTH - 1:
            pending_actions.extend(
                ProposedAction(
                    action_id=action.action_id,
                    description=action.description,
                    tool_name=action.tool_name,
                    params=action.params,
                    requires_confirmation=True,
                )
                for action in auto_actions
            )
            break

        tool_results = []
        for action in auto_actions:
            result = await _execute_action(request, action)
            executed.append((action, result))
            tool_results.append(
                {
                    "action_id": action.action_id,
                    "tool_name": action.tool_name,
                    "result": result,
                }
            )

        if pending_actions:
            break

    for action in pending_actions:
        _cache_action(request, action)

    response = AllAIChatResponse(
        reply=_append_execution_reply(reply, executed),
        conversation_id=conversation_id,
        proposed_actions=pending_actions or None,
        suggestions=suggestions,
    )
    return JSONResponse(response.model_dump(exclude_none=True))


async def allai_confirm(request: Request) -> JSONResponse:
    body = await _parse_body(request, AllAIConfirmRequest)
    cache = getattr(request.app.state, "allai_action_cache", None) or {}
    action = cache.pop(body.action_id, None)
    if action is None:
        err = make_error(ErrorCode.NOT_FOUND, "Unknown action_id")
        return JSONResponse(err.model_dump(exclude_none=True), status_code=404)

    if not body.approved:
        response = AllAIConfirmResponse(status="denied")
        return JSONResponse(response.model_dump(exclude_none=True))

    result = await _execute_action(request, action)
    response = AllAIConfirmResponse(status="executed", result=result)
    return JSONResponse(response.model_dump(exclude_none=True))
