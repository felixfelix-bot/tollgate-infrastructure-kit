import json
import os
from tollgate_mint_orchestrator.audit_log import AuditLogger


class TestAuditLogger:
    def test_log_approval(self, tmp_path):
        path = str(tmp_path / "audit.jsonl")
        logger = AuditLogger(path)
        logger.log_approval(
            event_id="abc123",
            npub="npub1test",
            mint_url="https://test.mints.example",
            quote_id="q1",
            amount=100,
            unit="sat",
            success=True,
        )
        assert os.path.exists(path)
        with open(path) as f:
            entry = json.loads(f.readline())
        assert entry["event_id"] == "abc123"
        assert entry["npub"] == "npub1test"
        assert entry["success"] is True
        assert entry["timestamp"] > 0
        assert "iso_time" in entry

    def test_log_approval_failure(self, tmp_path):
        path = str(tmp_path / "audit.jsonl")
        logger = AuditLogger(path)
        logger.log_approval(
            event_id="abc123",
            npub="npub1test",
            mint_url="https://test.mints.example",
            quote_id="q1",
            amount=100,
            unit="sat",
            success=False,
            error="invalid signature",
        )
        with open(path) as f:
            entry = json.loads(f.readline())
        assert entry["success"] is False
        assert entry["error"] == "invalid signature"

    def test_log_event(self, tmp_path):
        path = str(tmp_path / "audit.jsonl")
        logger = AuditLogger(path)
        logger.log_event({"type": "test", "data": "hello"})
        with open(path) as f:
            entry = json.loads(f.readline())
        assert entry["type"] == "test"
        assert entry["data"] == "hello"

    def test_read_recent(self, tmp_path):
        path = str(tmp_path / "audit.jsonl")
        logger = AuditLogger(path)
        for i in range(10):
            logger.log_approval(
                event_id=f"evt-{i}",
                npub="npub1test",
                mint_url="https://test.mints.example",
                quote_id=f"q{i}",
                amount=i * 100,
                unit="sat",
                success=True,
            )
        recent = logger.read_recent(5)
        assert len(recent) == 5
        assert recent[0]["event_id"] == "evt-5"
        assert recent[-1]["event_id"] == "evt-9"

    def test_read_recent_empty(self, tmp_path):
        logger = AuditLogger(str(tmp_path / "nonexistent.jsonl"))
        assert logger.read_recent() == []

    def test_creates_directory(self, tmp_path):
        path = str(tmp_path / "subdir" / "audit.jsonl")
        logger = AuditLogger(path)
        logger.log_event({"type": "test"})
        assert os.path.exists(path)
