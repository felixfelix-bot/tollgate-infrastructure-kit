import pytest
from aiohttp.test_utils import TestClient, TestServer
from tollgate_mint_orchestrator.api import OrchestratorAPI
from tollgate_mint_orchestrator.audit_log import AuditLogger
from tollgate_mint_orchestrator.mint_registry import MintEntry, MintRegistry


def _make_registry(tmp_path):
    path = str(tmp_path / "registry.json")
    reg = MintRegistry(path)
    reg.add_mint({
        "npub": "npub1abc",
        "hex_pubkey": "a" * 64,
        "subdomain": "test",
        "url": "https://test.mints.example",
        "rest_port": 3338,
        "grpc_port": 50051,
        "container_name": "mint-test",
        "created_at": "2026-01-01T00:00:00Z",
    })
    reg.add_mint({
        "npub": "npub1def",
        "hex_pubkey": "b" * 64,
        "subdomain": "other",
        "url": "https://other.mints.example",
        "rest_port": 3339,
        "grpc_port": 50052,
        "container_name": "mint-other",
        "created_at": "2026-01-02T00:00:00Z",
    })
    return reg


@pytest.fixture
def registry(tmp_path):
    return _make_registry(tmp_path)


@pytest.fixture
def audit(tmp_path):
    return AuditLogger(str(tmp_path / "audit.jsonl"))


@pytest.fixture
def api(registry, audit):
    return OrchestratorAPI(registry, audit)


@pytest.fixture
async def client(api):
    server = TestServer(api.app)
    tc = TestClient(server)
    await tc.start_server()
    yield tc
    await tc.close()


class TestOrchestratorAPI:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert data["mints"] == 2

    @pytest.mark.asyncio
    async def test_list_mints(self, client):
        resp = await client.get("/mints")
        assert resp.status == 200
        data = await resp.json()
        assert len(data["mints"]) == 2
        urls = {m["url"] for m in data["mints"]}
        assert "https://test.mints.example" in urls
        assert "https://other.mints.example" in urls

    @pytest.mark.asyncio
    async def test_get_mint_found(self, client):
        resp = await client.get("/mints/test")
        assert resp.status == 200
        data = await resp.json()
        assert data["subdomain"] == "test"
        assert data["url"] == "https://test.mints.example"
        assert data["rest_port"] == 3338
        assert data["grpc_port"] == 50051

    @pytest.mark.asyncio
    async def test_get_mint_not_found(self, client):
        resp = await client.get("/mints/nonexistent")
        assert resp.status == 404
        data = await resp.json()
        assert data["error"] == "mint not found"

    @pytest.mark.asyncio
    async def test_audit_default_count(self, client, audit):
        audit.log_approval(
            event_id="e1", npub="n1", mint_url="u1",
            quote_id="q1", amount=100, unit="sat", success=True,
        )
        audit.log_approval(
            event_id="e2", npub="n2", mint_url="u2",
            quote_id="q2", amount=200, unit="sat", success=False,
        )
        resp = await client.get("/audit")
        assert resp.status == 200
        data = await resp.json()
        assert len(data["entries"]) == 2

    @pytest.mark.asyncio
    async def test_audit_with_count(self, client, audit):
        for i in range(10):
            audit.log_approval(
                event_id=f"e{i}", npub="n1", mint_url="u1",
                quote_id=f"q{i}", amount=i * 100, unit="sat", success=True,
            )
        resp = await client.get("/audit?count=3")
        assert resp.status == 200
        data = await resp.json()
        assert len(data["entries"]) == 3
        assert data["entries"][0]["event_id"] == "e7"

    @pytest.mark.asyncio
    async def test_audit_empty(self, client):
        resp = await client.get("/audit")
        assert resp.status == 200
        data = await resp.json()
        assert data["entries"] == []

    def test_setup_routes(self, registry, audit):
        api = OrchestratorAPI(registry, audit)
        routes = [r.resource.canonical for r in api.app.router.routes()]
        assert "/health" in routes
        assert "/mints" in routes
        assert "/mints/{subdomain}" in routes
        assert "/audit" in routes

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self, registry, audit):
        api = OrchestratorAPI(registry, audit, host="127.0.0.1", port=0)
        await api.start()
        assert api._runner is not None
        await api.stop()
        assert api._runner is None

    @pytest.mark.asyncio
    async def test_stop_without_start(self, registry, audit):
        api = OrchestratorAPI(registry, audit)
        await api.stop()
        assert api._runner is None
