import os
import tempfile

import pytest

from act_runner.db import BuildDB, Build


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    database = BuildDB(path)
    yield database
    os.unlink(path)


def test_insert_and_get_build(db):
    build = Build(
        repo_url="https://git.example.com/repo.git",
        repo_name="repo",
        branch="main",
        commit_sha="abc123def456",
        status="pending",
        started_at="2026-01-01T00:00:00Z",
    )
    build_id = db.insert_build(build)
    assert build_id > 0

    fetched = db.get_build(build_id)
    assert fetched is not None
    assert fetched.repo_url == "https://git.example.com/repo.git"
    assert fetched.commit_sha == "abc123def456"
    assert fetched.status == "pending"


def test_update_build(db):
    build = Build(
        repo_url="https://git.example.com/repo.git",
        repo_name="repo",
        branch="main",
        commit_sha="abc123",
        status="running",
        started_at="2026-01-01T00:00:00Z",
    )
    build_id = db.insert_build(build)

    db.update_build(
        build_id,
        status="success",
        exit_code=0,
        duration_ms=5000,
        finished_at="2026-01-01T00:00:05Z",
    )

    fetched = db.get_build(build_id)
    assert fetched.status == "success"
    assert fetched.exit_code == 0
    assert fetched.duration_ms == 5000


def test_list_builds(db):
    for i in range(5):
        db.insert_build(
            Build(
                repo_url=f"https://git.example.com/repo{i}.git",
                repo_name=f"repo{i}",
                branch="main",
                commit_sha=f"sha{i}",
                status="success",
                started_at=f"2026-01-01T00:00:0{i}Z",
            )
        )

    builds = db.list_builds(limit=3, offset=0)
    assert len(builds) == 3
    assert builds[0].repo_name == "repo4"
    assert builds[2].repo_name == "repo2"


def test_get_last_build_for_repo(db):
    db.insert_build(
        Build(
            repo_url="https://git.example.com/repo.git",
            repo_name="repo",
            branch="main",
            commit_sha="sha1",
            status="success",
            started_at="2026-01-01T00:00:00Z",
        )
    )
    db.insert_build(
        Build(
            repo_url="https://git.example.com/repo.git",
            repo_name="repo",
            branch="main",
            commit_sha="sha2",
            status="failure",
            started_at="2026-01-01T00:01:00Z",
        )
    )

    last = db.get_last_build_for_repo("https://git.example.com/repo.git", "main")
    assert last is not None
    assert last.commit_sha == "sha2"
    assert last.status == "failure"


def test_get_last_commit(db):
    db.insert_build(
        Build(
            repo_url="https://git.example.com/repo.git",
            repo_name="repo",
            branch="main",
            commit_sha="deadbeef",
            status="success",
            started_at="2026-01-01T00:00:00Z",
        )
    )

    assert db.get_last_commit("https://git.example.com/repo.git", "main") == "deadbeef"
    assert db.get_last_commit("https://git.example.com/other.git", "main") is None


def test_get_build_not_found(db):
    assert db.get_build(99999) is None
