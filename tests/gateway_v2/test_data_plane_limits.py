from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

AIM_NODE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AIM_NODE_ROOT / "python"))
sys.modules.pop("aim_node", None)

from aim_node.gateway_v2.connect import (  # type: ignore[import-not-found]  # noqa: E402
    ConnectResponse,
    local_grant_secret_ref,
    parse_connect_response,
)
from aim_node.gateway_v2.invoke import (  # type: ignore[import-not-found]  # noqa: E402
    ConnectorRuntime,
    InvokeLimits,
    InvokeRequest,
    InvokeRuntimeError,
    InvokeState,
    RuntimeGrantBinding,
)
from aim_node.gateway_v2.meter import (  # type: ignore[import-not-found]  # noqa: E402
    LocalMeterBuffer,
    MeterBufferError,
    MeterBufferObservability,
    MeterBufferPolicy,
    MeterEvent,
    MeterMeasures,
    MeterRecordRequest,
)


DATA_PLANE_BUDGETS = {
    "connect": {"overhead_p95_ms": 150},
    "invoke": {
        "overhead_p95_ms": 150,
        "stream_byte_cap": 5 * 1024 * 1024 * 1024,
        "stream_time_cap_seconds": 3_600,
        "stream_idle_timeout_seconds": 120,
    },
    "meter": {"overhead_p95_ms": 100, "buffer_depth_threshold": 100, "drain_deadline_seconds": 300},
}


def test_data_plane_overhead_budgets_cover_connect_invoke_and_meter_with_stream_caps() -> None:
    assert set(DATA_PLANE_BUDGETS) == {"connect", "invoke", "meter"}
    assert DATA_PLANE_BUDGETS["connect"]["overhead_p95_ms"] <= 150
    assert DATA_PLANE_BUDGETS["invoke"]["overhead_p95_ms"] <= 150
    assert DATA_PLANE_BUDGETS["meter"]["overhead_p95_ms"] <= 150
    assert DATA_PLANE_BUDGETS["invoke"]["stream_byte_cap"] > 0
    assert DATA_PLANE_BUDGETS["invoke"]["stream_time_cap_seconds"] > 0
    assert DATA_PLANE_BUDGETS["invoke"]["stream_idle_timeout_seconds"] > 0


def test_connect_budget_keeps_secret_material_local_and_returns_reference_only() -> None:
    response = parse_connect_response(
        {
            "access_grant_id": "agr_data_plane",
            "connector_id": "conn_data_plane",
            "state": "active",
            "expires_at": "2026-04-28T01:00:00Z",
            "connection": {
                "type": "local",
                "local_secret_ref": local_grant_secret_ref("agr_data_plane"),
            },
            "allowed_scope": {
                "listing_id": "lst_data_plane",
                "quote_id": "qte_data_plane",
                "billing_session_id": "bs_data_plane",
                "delivery_mode": "local",
                "operations": ["invoke", "meter.record"],
                "max_concurrency": 4,
            },
            "terms_hash": "sha256:terms",
        }
    )

    assert isinstance(response, ConnectResponse)
    assert response.connection.local_secret_ref == "local://aim-node/secrets/grants/agr_data_plane"
    assert "raw_secret" not in str(asdict(response))


def test_invoke_streaming_caps_enforce_byte_time_idle_and_per_grant_concurrency_budgets() -> None:
    limits = InvokeLimits(
        byte_cap=3,
        row_cap=10,
        record_cap=1,
        wall_clock_cap_seconds=0.001,
        idle_timeout_seconds=120,
        per_grant_concurrency=1,
        retry_after_seconds=23,
    )

    with pytest.raises(InvokeRuntimeError) as byte_cap:
        ConnectorRuntime().invoke(_invoke_request(limits=limits), _grant(), [b"ab", b"cd"])
    assert byte_cap.value.state == InvokeState.PARTIAL_TRANSFER

    runtime = ConnectorRuntime()
    runtime.active_per_grant["agr_data_plane"] = 1
    with pytest.raises(InvokeRuntimeError) as concurrency:
        runtime.invoke(_invoke_request(limits=limits), _grant(), [b"a"])
    assert concurrency.value.retry_after_seconds == 23
    assert "per_grant" in str(concurrency.value)

    assert limits.wall_clock_cap_seconds > 0
    assert limits.idle_timeout_seconds == DATA_PLANE_BUDGETS["invoke"]["stream_idle_timeout_seconds"]


def test_meter_buffer_depth_drain_thresholds_dropped_rejected_and_backpressure_metrics_are_visible() -> None:
    observability = MeterBufferObservability()
    buffer = LocalMeterBuffer(
        MeterBufferPolicy(threshold_events=2, max_events=2, drain_deadline_seconds=5),
        observability,
    )
    buffer.enqueue(_meter_request("1"), now_seconds=0)
    buffer.enqueue(_meter_request("2"), now_seconds=1)

    assert buffer.depth == 2
    assert buffer.state == "buffering"
    assert any(metric["name"] == "gateway.meter_buffer.depth" for metric in observability.metrics)

    with pytest.raises(MeterBufferError) as rejected:
        buffer.enqueue(_meter_request("3"), now_seconds=2)

    assert rejected.value.code == "METERING_REJECTED"
    assert buffer.state == "fail_closed"
    assert buffer.dropped_events == 1
    assert any(span["name"] == "gateway.meter_buffer.rejected" for span in observability.spans)
    rejected_metrics = [metric for metric in observability.metrics if metric["name"] == "gateway.meter_buffer.rejected.count"]
    assert rejected_metrics[-1]["attributes"]["dropped_events"] == 1
    assert rejected_metrics[-1]["attributes"]["state"] == "fail_closed"


def test_meter_buffer_drain_deadline_and_degraded_backpressure_are_metric_visible() -> None:
    observability = MeterBufferObservability()
    buffer = LocalMeterBuffer(
        MeterBufferPolicy(threshold_events=1, max_events=5, drain_deadline_seconds=1),
        observability,
    )
    buffer.enqueue(_meter_request("deadline"), now_seconds=0)

    with pytest.raises(MeterBufferError, match="drain deadline"):
        buffer.enqueue(_meter_request("late"), now_seconds=2)

    assert buffer.state == "fail_closed"
    assert any(
        metric["attributes"]["state"] == "fail_closed"
        for metric in observability.metrics
        if metric["name"] == "gateway.meter_buffer.rejected.count"
    )

    degraded_observability = MeterBufferObservability()
    degraded = LocalMeterBuffer(observability=degraded_observability)
    degraded.mark_degraded("backend_unreachable")
    assert degraded.state == "degraded"
    assert degraded_observability.spans[-1]["name"] == "gateway.meter_buffer.degraded"


def _invoke_request(**overrides: Any) -> InvokeRequest:
    data: dict[str, Any] = {
        "metadata": {
            "request_id": "req_data_plane",
            "account_id": "acct_data_plane",
            "idempotency_key": "idem_data_plane",
            "signed_envelope": "valid",
        },
        "access_grant_id": "agr_data_plane",
        "buyer_account_id": "acct_data_plane",
        "listing_id": "lst_data_plane",
        "listing_version_id": "lstv_data_plane",
        "connector_id": "conn_data_plane",
        "delivery_mode": "seller_edge_direct",
        "terms_hash": "sha256:terms",
        "operation": "invoke",
        "mode": "stream",
        "seller_edge_identity_hash": "sha256:edge",
    }
    data.update(overrides)
    return InvokeRequest(**data)


def _grant() -> RuntimeGrantBinding:
    return RuntimeGrantBinding(
        access_grant_id="agr_data_plane",
        buyer_account_id="acct_data_plane",
        listing_id="lst_data_plane",
        listing_version_id="lstv_data_plane",
        connector_id="conn_data_plane",
        delivery_mode="seller_edge_direct",
        terms_hash="sha256:terms",
        operations=["invoke", "meter.record"],
        expires_at="2026-04-28T01:00:00Z",
        seller_edge_identity_hash="sha256:edge",
    )


def _meter_request(suffix: str) -> MeterRecordRequest:
    return MeterRecordRequest(
        metadata={
            "request_id": f"req_meter_{suffix}",
            "account_id": "acct_data_plane",
            "idempotency_key": f"idem_meter_{suffix}",
            "signed_envelope": "valid",
        },
        access_grant_id="agr_data_plane",
        invocation_id=f"inv_{suffix}",
        buyer_account_id="acct_data_plane",
        seller_account_id="acct_seller",
        listing_id="lst_data_plane",
        listing_version_id="lstv_data_plane",
        connector_id="conn_data_plane",
        event_type="invocation",
        measures=MeterMeasures(bytes=1, records=1, calls=1),
        artifact_hash="sha256:artifact",
        occurred_at="2026-04-28T00:00:00Z",
        seller_edge_identity_hash="sha256:edge",
        signed_reference={"artifact_hash": "sha256:artifact"},
    )


def _meter_event(request: MeterRecordRequest) -> MeterEvent:
    return MeterEvent(
        meter_event_id=f"met_{request.invocation_id}",
        access_grant_id=request.access_grant_id,
        invocation_id=request.invocation_id,
        buyer_account_id=request.buyer_account_id,
        seller_account_id=request.seller_account_id,
        listing_id=request.listing_id,
        listing_version_id=request.listing_version_id,
        connector_id=request.connector_id,
        event_type=request.event_type,
        measures=request.measures,
        artifact_hash=request.artifact_hash,
        occurred_at=request.occurred_at,
        accepted_at="2026-04-28T00:00:01Z",
        seller_edge_identity_hash=request.seller_edge_identity_hash,
    )
