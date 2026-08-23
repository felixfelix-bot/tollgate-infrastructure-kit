"""Phase E — ops: /healthz + /metrics tests (spec §9 DM-OPS-1, §7.5)."""
import time

import pytest
from fastapi.testclient import TestClient

from tollgate_dm_issuer.ops import Metrics, build_app


@pytest.fixture
def metrics():
    return Metrics()


@pytest.fixture
def client(metrics):
    return TestClient(build_app(metrics))


class TestHealthz:
    def test_healthz_starting_when_no_heartbeat(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "starting"

    def test_healthz_ok_after_heartbeat(self, client, metrics):
        metrics.observe_heartbeat()
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_healthz_stale_when_heartbeat_old(self, client, metrics):
        metrics.poll_seconds = 20
        metrics.last_seen_ts = time.time() - 120
        resp = client.get("/healthz")
        assert resp.status_code == 503
        assert resp.json()["status"] == "stale"


class TestMetrics:
    def test_metrics_contains_all_counters(self, client, metrics):
        metrics.requests_total = 5
        metrics.sats_issued_total = 7000
        metrics.errors_total = 2
        metrics.active_requests = 1
        resp = client.get("/metrics")
        assert resp.status_code == 200
        body = resp.text
        assert "dm_requests_total 5" in body
        assert "dm_sats_issued_total 7000" in body
        assert "dm_errors_total 2" in body
        assert "dm_active_requests 1" in body

    def test_metrics_includes_help_type_lines(self, client):
        resp = client.get("/metrics")
        body = resp.text
        assert "# HELP dm_requests_total" in body
        assert "# TYPE dm_requests_total counter" in body

    def test_metrics_media_type_is_text_plain(self, client):
        resp = client.get("/metrics")
        assert resp.headers["content-type"].startswith("text/plain")


class TestMetricsObservations:
    def test_observe_request_started_increments_counters(self, metrics):
        metrics.observe_request_started()
        assert metrics.requests_total == 1
        assert metrics.active_requests == 1

    def test_observe_request_delivered_decrements_active_increments_sats(self, metrics):
        metrics.observe_request_started()
        metrics.observe_request_delivered(5000)
        assert metrics.active_requests == 0
        assert metrics.sats_issued_total == 5000

    def test_observe_request_error_increments_errors_decrements_active(
            self, metrics):
        metrics.observe_request_started()
        metrics.observe_request_error()
        assert metrics.errors_total == 1
        assert metrics.active_requests == 0

    def test_active_requests_never_negative(self, metrics):
        metrics.observe_request_error()
        assert metrics.active_requests == 0
