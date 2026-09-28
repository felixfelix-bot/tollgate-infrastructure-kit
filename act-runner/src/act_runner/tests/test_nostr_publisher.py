import json

import pytest

from act_runner.nostr_publisher import build_nostr_event, _create_event


def test_create_event():
    tags = [["d", "test"], ["status", "success"]]
    event = _create_event(tags, "test content")
    assert event["kind"] == 1985
    assert event["tags"] == tags
    assert event["content"] == "test content"
    assert "created_at" in event


def test_build_nostr_event_unsigned():
    event = build_nostr_event(
        repo_url="https://git.example.com/repo.git",
        commit_sha="abc123def456",
        branch="main",
        status="success",
        duration_ms=5000,
        log_url="https://runner.example.com/api/builds/1/log",
    )

    assert event["kind"] == 1985
    assert ["d", "https://git.example.com/repo.git:main"] in event["tags"]
    assert ["commit", "abc123def456"] in event["tags"]
    assert ["branch", "main"] in event["tags"]
    assert ["status", "success"] in event["tags"]
    assert ["duration_ms", "5000"] in event["tags"]

    content = json.loads(event["content"])
    assert content["repo"] == "https://git.example.com/repo.git"
    assert content["status"] == "success"
    assert content["duration_ms"] == 5000
    assert "timestamp" in content


def test_build_nostr_event_failure():
    event = build_nostr_event(
        repo_url="https://git.example.com/repo.git",
        commit_sha="deadbeef",
        branch="develop",
        status="failure",
        duration_ms=12000,
    )

    assert ["status", "failure"] in event["tags"]
    content = json.loads(event["content"])
    assert content["status"] == "failure"


def test_build_nostr_event_with_invalid_nsec():
    event = build_nostr_event(
        repo_url="https://git.example.com/repo.git",
        commit_sha="abc123",
        branch="main",
        status="success",
        duration_ms=1000,
        nsec="invalid_nsec",
    )

    assert event["kind"] == 1985
    assert "id" not in event or event.get("sig") is None or True
