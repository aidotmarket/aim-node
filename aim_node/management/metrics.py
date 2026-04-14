"""Management API local metrics collection."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypedDict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from aim_node.management.errors import ErrorCode, make_error
from aim_node.management.state import read_store, write_store

METRICS_STORE_KEY = "local_metrics"
TIMESERIES_STORE_KEY = "metrics_timeseries"
BUCKET_SIZE_S = 300
MAX_BUCKETS = 7 * 24 * 12
FLUSH_INTERVAL_S = 60

_RANGE_WINDOWS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}
_METRIC_TYPES = frozenset({"calls", "errors", "latency"})


class MetricBucket(TypedDict):
    timestamp: str
    calls: int
    errors: int
    avg_latency_ms: float


class MetricsCollector:
    """Tracks local counters and 5-minute bucketed history."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._lock = asyncio.Lock()
        self._started_at = time.monotonic()
        self.total_calls = 0
        self.total_errors = 0
        self.active_sessions = 0
        self.timeseries: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        counters = read_store(self._data_dir, METRICS_STORE_KEY) or {}
        self.total_calls = int(counters.get("total_calls", 0))
        self.total_errors = int(counters.get("total_errors", 0))
        self.active_sessions = int(counters.get("active_sessions", 0))

        persisted = read_store(self._data_dir, TIMESERIES_STORE_KEY) or {}
        buckets = persisted.get("buckets", [])
        if not isinstance(buckets, list):
            buckets = []

        normalized: list[dict[str, Any]] = []
        for item in buckets:
            if not isinstance(item, dict):
                continue
            calls = int(item.get("calls", 0))
            avg_latency_ms = float(item.get("avg_latency_ms", 0.0))
            normalized.append(
                {
                    "timestamp": str(item.get("timestamp")),
                    "calls": calls,
                    "errors": int(item.get("errors", 0)),
                    "avg_latency_ms": avg_latency_ms,
                    "latency_sum_ms": avg_latency_ms * calls,
                }
            )
        self.timeseries = normalized[-MAX_BUCKETS:]

    @property
    def uptime_s(self) -> float:
        return time.monotonic() - self._started_at

    async def record_call(self, *, latency_ms: float, error: bool) -> None:
        async with self._lock:
            self.total_calls += 1
            if error:
                self.total_errors += 1

            bucket = self._current_bucket()
            bucket["calls"] += 1
            if error:
                bucket["errors"] += 1
            bucket["latency_sum_ms"] += float(latency_ms)
            bucket["avg_latency_ms"] = (
                bucket["latency_sum_ms"] / bucket["calls"] if bucket["calls"] else 0.0
            )

    async def flush(self) -> None:
        async with self._lock:
            write_store(
                self._data_dir,
                METRICS_STORE_KEY,
                {
                    "total_calls": self.total_calls,
                    "total_errors": self.total_errors,
                    "active_sessions": self.active_sessions,
                },
            )
            write_store(
                self._data_dir,
                TIMESERIES_STORE_KEY,
                {"buckets": self._public_buckets()},
            )

    async def flush_loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_S)
            await self.flush()

    def sync_active_sessions(self, count: int) -> None:
        self.active_sessions = count

    def summary(self) -> dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "total_errors": self.total_errors,
            "active_sessions": self.active_sessions,
            "uptime_s": round(self.uptime_s, 3),
        }

    def series_for(self, *, range_key: str, metric: str) -> list[dict[str, Any]]:
        if range_key not in _RANGE_WINDOWS:
            raise ValueError("range must be one of 1h, 24h, 7d")
        if metric not in _METRIC_TYPES:
            raise ValueError("metric must be one of calls, errors, latency")

        cutoff = datetime.now(timezone.utc) - _RANGE_WINDOWS[range_key]
        points: list[dict[str, Any]] = []
        for bucket in self._public_buckets():
            timestamp = _parse_bucket_ts(bucket["timestamp"])
            if timestamp < cutoff:
                continue
            if metric == "latency":
                value = bucket["avg_latency_ms"]
            elif metric == "errors":
                value = bucket["errors"]
            else:
                value = bucket["calls"]
            points.append({"timestamp": bucket["timestamp"], "value": value})
        return points

    def _current_bucket(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        bucket_start = now - timedelta(
            minutes=now.minute % 5,
            seconds=now.second,
            microseconds=now.microsecond,
        )
        timestamp = bucket_start.isoformat()

        if self.timeseries and self.timeseries[-1]["timestamp"] == timestamp:
            return self.timeseries[-1]

        bucket = {
            "timestamp": timestamp,
            "calls": 0,
            "errors": 0,
            "avg_latency_ms": 0.0,
            "latency_sum_ms": 0.0,
        }
        self.timeseries.append(bucket)
        self.timeseries = self.timeseries[-MAX_BUCKETS:]
        return bucket

    def _public_buckets(self) -> list[MetricBucket]:
        return [
            {
                "timestamp": bucket["timestamp"],
                "calls": int(bucket["calls"]),
                "errors": int(bucket["errors"]),
                "avg_latency_ms": round(float(bucket["avg_latency_ms"]), 3),
            }
            for bucket in self.timeseries
        ]


def _parse_bucket_ts(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        collector: MetricsCollector | None = getattr(request.app.state, "metrics", None)
        if collector is None or request.scope["type"] != "http":
            return await call_next(request)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            latency_ms = (time.perf_counter() - start) * 1000
            await collector.record_call(latency_ms=latency_ms, error=True)
            raise

        latency_ms = (time.perf_counter() - start) * 1000
        await collector.record_call(
            latency_ms=latency_ms,
            error=response.status_code >= 400,
        )
        return response


async def metrics_summary(request: Request) -> JSONResponse:
    collector: MetricsCollector = request.app.state.metrics
    store = getattr(request.app.state, "store", None)
    if store is not None:
        collector.sync_active_sessions(len(store.get_sessions()))
    return JSONResponse(collector.summary())


async def metrics_timeseries(request: Request) -> JSONResponse:
    collector: MetricsCollector = request.app.state.metrics
    range_key = request.query_params.get("range", "1h")
    metric = request.query_params.get("metric", "calls")
    try:
        points = collector.series_for(range_key=range_key, metric=metric)
    except ValueError as exc:
        err = make_error(ErrorCode.CONFIG_INVALID, str(exc))
        return JSONResponse(err.model_dump(exclude_none=True), status_code=422)

    return JSONResponse(
        {
            "range": range_key,
            "metric": metric,
            "points": points,
        }
    )
