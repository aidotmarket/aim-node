from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))
sys.modules.pop("aim_node", None)

from aim_node.gateway_v2.invoke import (  # type: ignore[import-not-found]
    INVOKE_CLIENT_METHOD,
    INVOKE_GRPC_STREAMING_METHOD,
    INVOKE_GRPC_UNARY_METHOD,
    INVOKE_HTTP_ROUTE,
    ConnectorRuntime,
    InvokeLimits,
    InvokeRequest,
    InvokeRuntimeError,
    InvokeState,
    ResumeCursor,
    RuntimeGrantBinding,
)


def _grant(**overrides: object) -> RuntimeGrantBinding:
    data: dict[str, object] = {
        "access_grant_id": "agr_1",
        "buyer_account_id": "acct_1",
        "listing_id": "lst_1",
        "listing_version_id": "lstv_1",
        "connector_id": "conn_1",
        "delivery_mode": "seller_edge_direct",
        "terms_hash": "sha256:terms",
        "operations": ["invoke", "meter.record"],
        "expires_at": "2026-04-28T01:00:00Z",
        "state": "active",
        "seller_edge_identity_hash": "sha256:edge",
        "max_concurrency": 4,
    }
    data.update(overrides)
    return RuntimeGrantBinding(**data)


def _request(**overrides: object) -> InvokeRequest:
    data: dict[str, object] = {
        "metadata": {
            "request_id": "req_1",
            "account_id": "acct_1",
            "idempotency_key": "idem_1",
            "signed_envelope": "valid",
        },
        "access_grant_id": "agr_1",
        "buyer_account_id": "acct_1",
        "listing_id": "lst_1",
        "listing_version_id": "lstv_1",
        "connector_id": "conn_1",
        "delivery_mode": "seller_edge_direct",
        "terms_hash": "sha256:terms",
        "operation": "invoke",
        "mode": "stream",
        "seller_edge_identity_hash": "sha256:edge",
    }
    data.update(overrides)
    return InvokeRequest(**data)


def test_invoke_names_match_gate_1_http_grpc_streaming_unary_ts_and_python_sdk() -> None:
    ts_text = (REPO_ROOT / "src/gateway_v2/invoke.ts").read_text()

    assert INVOKE_HTTP_ROUTE == "/v1/gateway/invoke"
    assert INVOKE_GRPC_UNARY_METHOD == "Invoke"
    assert INVOKE_GRPC_STREAMING_METHOD == "InvokeStream"
    assert INVOKE_CLIENT_METHOD.sdk_method == "gateway.invoke"
    assert 'sdkMethod: "gateway.invoke"' in (REPO_ROOT / "src/gateway_v2/client_contracts.ts").read_text()
    assert 'export const invokeGrpcUnaryMethod = "Invoke"' in ts_text
    assert 'export const invokeGrpcStreamingMethod = "InvokeStream"' in ts_text
    assert 'async invoke(request: InvokeRequest)' in ts_text


def test_runtime_requires_active_unexpired_unrevoked_grant_bound_to_all_dimensions() -> None:
    ok = ConnectorRuntime().invoke(_request(), _grant(), [b"abc"])
    assert ok.state == InvokeState.COMPLETED
    assert ok.metering.bytes == 3

    cases = (
        (_request(buyer_account_id="acct_other"), _grant(), "buyer_account_id"),
        (_request(listing_id="lst_other"), _grant(), "listing_id"),
        (_request(listing_version_id="lstv_other"), _grant(), "listing_version_id"),
        (_request(connector_id="conn_other"), _grant(), "connector_id"),
        (_request(delivery_mode="local"), _grant(), "delivery_mode"),
        (_request(terms_hash="sha256:other"), _grant(), "terms_hash"),
        (_request(operation="export"), _grant(), "operation"),
        (_request(seller_edge_identity_hash="sha256:other"), _grant(), "seller_edge_identity_hash"),
        (_request(), _grant(expires_at="2026-04-27T00:00:00Z"), "active unexpired"),
        (_request(), _grant(state="revoked"), "active unexpired"),
    )
    for request, grant, message in cases:
        with pytest.raises(InvokeRuntimeError, match=message):
            ConnectorRuntime().invoke(request, grant, [b"abc"])


def test_runtime_represents_all_required_states() -> None:
    assert {state.value for state in InvokeState} == {
        "pending",
        "running",
        "completed",
        "failed",
        "partial_transfer",
        "provider_timeout",
        "grant_revoked_mid_stream",
        "trust_revoked_mid_stream",
        "resume_unsupported",
        "metering_accepted_receipt_pending",
    }


def test_streaming_retries_use_signed_offsets_or_resume_tokens_and_unsupported_resume_fails() -> None:
    with pytest.raises(ValueError, match="signed offset or resume token"):
        ResumeCursor()

    request = _request(resume=ResumeCursor(signed_offset="offset:42.sig"))
    ok = ConnectorRuntime().invoke(request, _grant(), [b"abc"], resume_supported=True)
    assert ok.resume_required is True
    assert ok.metering.retries == 1

    with pytest.raises(InvokeRuntimeError) as exc:
        ConnectorRuntime().invoke(request, _grant(), [b"abc"], resume_supported=False)
    assert exc.value.state == InvokeState.RESUME_UNSUPPORTED


def test_caps_cover_bytes_rows_records_wall_clock_idle_per_grant_concurrency_and_retry_after() -> None:
    limits = InvokeLimits(
        byte_cap=3,
        row_cap=2,
        record_cap=1,
        wall_clock_cap_seconds=10,
        idle_timeout_seconds=5,
        per_grant_concurrency=1,
        retry_after_seconds=23,
    )
    assert limits.row_cap == 2
    assert limits.idle_timeout_seconds == 5
    with pytest.raises(InvokeRuntimeError) as partial:
        ConnectorRuntime().invoke(_request(limits=limits), _grant(), [b"ab", b"cd"])
    assert partial.value.state == InvokeState.PARTIAL_TRANSFER

    runtime = ConnectorRuntime()
    runtime.active_per_grant["agr_1"] = 1
    with pytest.raises(InvokeRuntimeError) as limited:
        runtime.invoke(_request(limits=limits), _grant(), [b"a"])
    assert limited.value.retry_after_seconds == 23
    assert "per_grant" in str(limited.value)


def test_mid_stream_grant_and_trust_revocation_states_are_explicit_failures() -> None:
    with pytest.raises(InvokeRuntimeError) as grant_revoked:
        ConnectorRuntime().invoke(_request(), _grant(), [b"a"], grant_revoked=True)
    assert grant_revoked.value.state == InvokeState.GRANT_REVOKED_MID_STREAM

    with pytest.raises(InvokeRuntimeError) as trust_revoked:
        ConnectorRuntime().invoke(_request(), _grant(), [b"a"], trust_revoked=True)
    assert trust_revoked.value.state == InvokeState.TRUST_REVOKED_MID_STREAM


def test_observability_metric_fields_are_redacted_summaries_not_payload_bytes() -> None:
    result = ConnectorRuntime().invoke(_request(), _grant(), [b"secret-bytes"])

    assert result.metering.bytes == len(b"secret-bytes")
    assert result.metering.records == 1
    assert result.metering.calls == 1
    assert result.metering.provider_latency_ms >= 0
    assert result.metering.cache_state == "unknown"
    assert result.metering.connector_type == "conn_1"
    assert result.metering.seller_edge_route == "sha256:edge"
    assert "secret-bytes" not in str(result)
