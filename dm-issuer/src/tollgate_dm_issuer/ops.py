"""Ops endpoints — health + Prometheus-compatible metrics (spec §9 DM-OPS-1).

The Poller owns a ``Metrics`` instance and updates counters as requests flow
through the pipeline.  The FastAPI app reads from the same instance and emits
text/plain ``# HELP / # TYPE`` lines on ``GET /metrics``.

``GET /healthz`` returns 200 OK when the poller loop is alive; returns 503
when the loop has stopped (last_seen older than 3× poll_seconds).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from fastapi import FastAPI, Response


@dataclass
class Metrics:
    requests_total: int = 0
    sats_issued_total: int = 0
    errors_total: int = 0
    active_requests: int = 0
    last_seen_ts: float = 0.0
    poll_seconds: int = 20

    def observe_request_started(self) -> None:
        self.requests_total += 1
        self.active_requests += 1

    def observe_request_delivered(self, sats: int) -> None:
        self.active_requests = max(0, self.active_requests - 1)
        self.sats_issued_total += sats

    def observe_request_error(self) -> None:
        self.errors_total += 1
        self.active_requests = max(0, self.active_requests - 1)

    def observe_heartbeat(self) -> None:
        self.last_seen_ts = time.time()


def build_app(metrics: Metrics) -> FastAPI:
    app = FastAPI(title="tollgate-dm-issuer", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz(response: Response):
        if metrics.last_seen_ts <= 0:
            return {"status": "starting"}
        stale_after = max(3, metrics.poll_seconds * 3)
        age = time.time() - metrics.last_seen_ts
        if age > stale_after:
            response.status_code = 503
            return {"status": "stale", "age_secs": int(age)}
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics_endpoint():
        body = "\n".join([
            "# HELP dm_requests_total Total DM requests processed since start.",
            "# TYPE dm_requests_total counter",
            f"dm_requests_total {metrics.requests_total}",
            "# HELP dm_sats_issued_total Total sats issued (DELIVERED).",
            "# TYPE dm_sats_issued_total counter",
            f"dm_sats_issued_total {metrics.sats_issued_total}",
            "# HELP dm_errors_total Total pipeline errors since start.",
            "# TYPE dm_errors_total counter",
            f"dm_errors_total {metrics.errors_total}",
            "# HELP dm_active_requests Requests currently in-flight.",
            "# TYPE dm_active_requests gauge",
            f"dm_active_requests {metrics.active_requests}",
            "",
        ])
        return Response(content=body, media_type="text/plain")

    return app
