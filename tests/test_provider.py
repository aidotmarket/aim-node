from __future__ import annotations

import json

import httpx
import pytest

from aim_node.provider.adapter import AdapterConfig, AdapterError, HttpJsonAdapter, extract_path


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_adapter_forward_request_success() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True}, request=request)

    adapter = HttpJsonAdapter(AdapterConfig(endpoint_url="http://localhost:8080/predict"))
    adapter._client = httpx.AsyncClient(transport=_transport(handler))

    body, latency_ms = await adapter.forward_request(b'{"prompt":"hello"}')

    assert json.loads(body) == {"ok": True}
    assert latency_ms >= 0
    assert captured == {
        "method": "POST",
        "url": "http://localhost:8080/predict",
        "body": {"prompt": "hello"},
    }
    await adapter.stop()


@pytest.mark.asyncio
async def test_adapter_forward_request_non_2xx_raises_1006() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"}, request=request)

    adapter = HttpJsonAdapter(AdapterConfig(endpoint_url="http://localhost:8080/predict"))
    adapter._client = httpx.AsyncClient(transport=_transport(handler))

    with pytest.raises(AdapterError) as exc_info:
        await adapter.forward_request(b'{"prompt":"hello"}')

    assert exc_info.value.code == 1006
    assert exc_info.value.message == "adapter: HTTP 503"
    await adapter.stop()


@pytest.mark.asyncio
async def test_adapter_forward_request_timeout_raises_1007() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    adapter = HttpJsonAdapter(AdapterConfig(endpoint_url="http://localhost:8080/predict"))
    adapter._client = httpx.AsyncClient(transport=_transport(handler))

    with pytest.raises(AdapterError) as exc_info:
        await adapter.forward_request(b'{"prompt":"hello"}')

    assert exc_info.value.code == 1007
    await adapter.stop()


@pytest.mark.asyncio
async def test_adapter_forward_request_non_json_response_raises_1006() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", request=request)

    adapter = HttpJsonAdapter(AdapterConfig(endpoint_url="http://localhost:8080/predict"))
    adapter._client = httpx.AsyncClient(transport=_transport(handler))

    with pytest.raises(AdapterError) as exc_info:
        await adapter.forward_request(b'{"prompt":"hello"}')

    assert exc_info.value.code == 1006
    assert exc_info.value.message == "adapter: non-JSON response"
    await adapter.stop()


@pytest.mark.asyncio
async def test_adapter_input_transform() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True}, request=request)

    adapter = HttpJsonAdapter(
        AdapterConfig(
            endpoint_url="http://localhost:8080/predict",
            input_path="$.data",
            wrap_key="input",
        )
    )
    adapter._client = httpx.AsyncClient(transport=_transport(handler))

    await adapter.forward_request(b'{"data":{"prompt":"hello"},"meta":{"id":"1"}}')

    assert captured["json"] == {"input": {"prompt": "hello"}}
    await adapter.stop()


@pytest.mark.asyncio
async def test_adapter_output_transform() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"text": "ok"}}, request=request)

    adapter = HttpJsonAdapter(
        AdapterConfig(
            endpoint_url="http://localhost:8080/predict",
            output_path="$.result.text",
        )
    )
    adapter._client = httpx.AsyncClient(transport=_transport(handler))

    body, _ = await adapter.forward_request(b'{"prompt":"hello"}')

    assert json.loads(body) == "ok"
    await adapter.stop()


@pytest.mark.asyncio
async def test_adapter_max_body_rejects_oversized() -> None:
    adapter = HttpJsonAdapter(
        AdapterConfig(endpoint_url="http://localhost:8080/predict", max_body_bytes=8)
    )
    adapter._client = httpx.AsyncClient(transport=_transport(lambda request: httpx.Response(200, json={}, request=request)))

    with pytest.raises(AdapterError) as exc_info:
        await adapter.forward_request(b'{"prompt":"too long"}')

    assert exc_info.value.code == 1001
    await adapter.stop()


@pytest.mark.asyncio
async def test_adapter_health_check_success_resets_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204, request=request)

    adapter = HttpJsonAdapter(AdapterConfig(endpoint_url="http://localhost:8080/predict"))
    adapter._client = httpx.AsyncClient(transport=_transport(handler))
    adapter._consecutive_failures = 2
    adapter._healthy = False

    healthy = await adapter.health_check()

    assert healthy is True
    assert adapter._consecutive_failures == 0
    assert adapter._healthy is True
    await adapter.stop()


@pytest.mark.asyncio
async def test_adapter_health_check_3_failures_marks_unhealthy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    adapter = HttpJsonAdapter(AdapterConfig(endpoint_url="http://localhost:8080/predict"))
    adapter._client = httpx.AsyncClient(transport=_transport(handler))

    assert await adapter.health_check() is False
    assert await adapter.health_check() is False
    assert await adapter.health_check() is False
    assert adapter._consecutive_failures == 3
    assert adapter._healthy is False
    await adapter.stop()


def test_extract_path_simple() -> None:
    assert extract_path({"data": 1}, "$.data") == 1


def test_extract_path_nested() -> None:
    assert extract_path({"data": {"result": "ok"}}, "$.data.result") == "ok"


def test_extract_path_missing_returns_none() -> None:
    assert extract_path({"data": {}}, "$.data.result") is None
