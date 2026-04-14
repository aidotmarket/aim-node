from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time

import httpx
import pytest

from aim_node.management.app import create_management_app
from aim_node.management.metrics import (
    METRICS_STORE_KEY,
    TIMESERIES_STORE_KEY,
    MetricsCollector,
)
from aim_node.management.process import ProcessManager
from aim_node.management.state import ProcessStateStore, SessionSnapshot, read_store


@pytest.fixture(autouse=True)
def _reset_state():
    ProcessStateStore.reset()
    os.environ.pop("AIM_KEYSTORE_PASSPHRASE", None)
    yield
    ProcessStateStore.reset()
    os.environ.pop("AIM_KEYSTORE_PASSPHRASE", None)


def _build_app(data_dir: Path):
    app = create_management_app(data_dir)
    state = ProcessStateStore(data_dir)
    process_mgr = ProcessManager(state, data_dir)
    app.state.store = state
    app.state.process_mgr = process_mgr
    return app, state


def _make_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://localhost"},
    )


def _bucket(timestamp: datetime, *, calls: int, errors: int, latency: float):
    return {
        "timestamp": timestamp.isoformat(),
        "calls": calls,
        "errors": errors,
        "avg_latency_ms": latency,
    }


async def test_metrics_summary_returns_current_counters(tmp_path: Path):
    app, state = _build_app(tmp_path)
    now = time.time()
    state.add_session(
        SessionSnapshot(
            session_id="s-1",
            role="consumer",
            state="active",
            created_at=now,
        )
    )
    state.add_session(
        SessionSnapshot(
            session_id="s-2",
            role="provider",
            state="active",
            created_at=now,
        )
    )
    await app.state.metrics.record_call(latency_ms=12, error=False)
    await app.state.metrics.record_call(latency_ms=30, error=True)

    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/metrics/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_calls"] == 2
    assert body["total_errors"] == 1
    assert body["active_sessions"] == 2
    assert body["uptime_s"] >= 0


async def test_metrics_summary_request_is_counted_after_response(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    async with _make_client(app) as client:
        first = await client.get("/api/mgmt/metrics/summary")
        second = await client.get("/api/mgmt/metrics/summary")
    assert first.json()["total_calls"] == 0
    assert second.json()["total_calls"] == 1


async def test_metrics_middleware_counts_success_and_error_requests(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    async with _make_client(app) as client:
        await client.get("/api/mgmt/health")
        await client.get("/api/mgmt/does-not-exist")
        response = await client.get("/api/mgmt/metrics/summary")
    body = response.json()
    assert body["total_calls"] == 2
    assert body["total_errors"] == 1


async def test_metrics_timeseries_calls_metric_for_one_hour(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    now = datetime.now(timezone.utc)
    app.state.metrics.timeseries = [
        {
            "timestamp": (now - timedelta(minutes=10)).isoformat(),
            "calls": 5,
            "errors": 1,
            "avg_latency_ms": 20.0,
            "latency_sum_ms": 100.0,
        },
        {
            "timestamp": (now - timedelta(hours=2)).isoformat(),
            "calls": 9,
            "errors": 3,
            "avg_latency_ms": 30.0,
            "latency_sum_ms": 270.0,
        },
    ]
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/metrics/timeseries?range=1h&metric=calls")
    assert response.status_code == 200
    assert response.json()["points"] == [
        {
            "timestamp": app.state.metrics.timeseries[0]["timestamp"],
            "value": 5,
        }
    ]


async def test_metrics_timeseries_errors_metric(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    now = datetime.now(timezone.utc)
    app.state.metrics.timeseries = [
        {
            "timestamp": (now - timedelta(minutes=20)).isoformat(),
            "calls": 8,
            "errors": 2,
            "avg_latency_ms": 15.0,
            "latency_sum_ms": 120.0,
        }
    ]
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/metrics/timeseries?range=24h&metric=errors")
    assert response.json()["points"][0]["value"] == 2


async def test_metrics_timeseries_latency_metric(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    now = datetime.now(timezone.utc)
    app.state.metrics.timeseries = [
        {
            "timestamp": (now - timedelta(minutes=5)).isoformat(),
            "calls": 3,
            "errors": 0,
            "avg_latency_ms": 42.5,
            "latency_sum_ms": 127.5,
        }
    ]
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/metrics/timeseries?range=24h&metric=latency")
    assert response.json()["points"][0]["value"] == 42.5


async def test_metrics_timeseries_24h_excludes_older_buckets(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    now = datetime.now(timezone.utc)
    app.state.metrics.timeseries = [
        {
            "timestamp": (now - timedelta(hours=23)).isoformat(),
            "calls": 1,
            "errors": 0,
            "avg_latency_ms": 10.0,
            "latency_sum_ms": 10.0,
        },
        {
            "timestamp": (now - timedelta(days=2)).isoformat(),
            "calls": 7,
            "errors": 1,
            "avg_latency_ms": 11.0,
            "latency_sum_ms": 77.0,
        },
    ]
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/metrics/timeseries?range=24h&metric=calls")
    assert len(response.json()["points"]) == 1
    assert response.json()["points"][0]["value"] == 1


async def test_metrics_timeseries_7d_includes_week_window(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    now = datetime.now(timezone.utc)
    app.state.metrics.timeseries = [
        {
            "timestamp": (now - timedelta(days=6)).isoformat(),
            "calls": 4,
            "errors": 1,
            "avg_latency_ms": 12.0,
            "latency_sum_ms": 48.0,
        }
    ]
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/metrics/timeseries?range=7d&metric=calls")
    assert response.json()["points"][0]["value"] == 4


async def test_metrics_timeseries_invalid_range_returns_422(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/metrics/timeseries?range=30d&metric=calls")
    assert response.status_code == 422
    assert response.json()["code"] == "config_invalid"


async def test_metrics_timeseries_invalid_metric_returns_422(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/metrics/timeseries?range=1h&metric=foo")
    assert response.status_code == 422
    assert response.json()["code"] == "config_invalid"


async def test_metrics_collector_flush_persists_counters_and_timeseries(tmp_path: Path):
    collector = MetricsCollector(tmp_path)
    await collector.record_call(latency_ms=25.0, error=False)
    await collector.record_call(latency_ms=35.0, error=True)
    collector.sync_active_sessions(3)
    await collector.flush()

    counters = read_store(tmp_path, METRICS_STORE_KEY)
    timeseries = read_store(tmp_path, TIMESERIES_STORE_KEY)
    assert counters == {
        "total_calls": 2,
        "total_errors": 1,
        "active_sessions": 3,
    }
    assert timeseries is not None
    assert len(timeseries["buckets"]) == 1
    assert timeseries["buckets"][0]["calls"] == 2


async def test_metrics_collector_loads_persisted_state(tmp_path: Path):
    app, _ = _build_app(tmp_path)
    now = datetime.now(timezone.utc)
    app.state.metrics.timeseries = [
        {
            "timestamp": now.isoformat(),
            "calls": 2,
            "errors": 1,
            "avg_latency_ms": 15.0,
            "latency_sum_ms": 30.0,
        }
    ]
    app.state.metrics.total_calls = 7
    app.state.metrics.total_errors = 2
    app.state.metrics.active_sessions = 1
    await app.state.metrics.flush()

    reloaded = MetricsCollector(tmp_path)
    assert reloaded.total_calls == 7
    assert reloaded.total_errors == 2
    assert reloaded.active_sessions == 1
    assert reloaded.timeseries[0]["calls"] == 2
    assert reloaded.timeseries[0]["latency_sum_ms"] == 30.0


async def test_metrics_collector_aggregates_average_latency(tmp_path: Path):
    collector = MetricsCollector(tmp_path)
    await collector.record_call(latency_ms=10.0, error=False)
    await collector.record_call(latency_ms=40.0, error=False)
    assert collector.timeseries[0]["avg_latency_ms"] == 25.0
    assert collector.timeseries[0]["calls"] == 2


async def test_metrics_collector_marks_errors_in_bucket(tmp_path: Path):
    collector = MetricsCollector(tmp_path)
    await collector.record_call(latency_ms=5.0, error=True)
    assert collector.total_errors == 1
    assert collector.timeseries[0]["errors"] == 1


async def test_metrics_summary_reflects_active_sessions_live(tmp_path: Path):
    app, state = _build_app(tmp_path)
    state.add_session(
        SessionSnapshot(
            session_id="live-1",
            role="consumer",
            state="active",
            created_at=time.time(),
        )
    )
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/metrics/summary")
    assert response.json()["active_sessions"] == 1
