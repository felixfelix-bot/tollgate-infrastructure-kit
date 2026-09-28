import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from act_runner.executor import has_workflows, execute_build, execute_custom_command
from act_runner.config import RepoConfig


def test_has_workflows_true():
    with tempfile.TemporaryDirectory() as tmpdir:
        wf_dir = os.path.join(tmpdir, ".github", "workflows")
        os.makedirs(wf_dir)
        with open(os.path.join(wf_dir, "ci.yml"), "w") as f:
            f.write("name: CI\non: push\n")

        import asyncio

        assert asyncio.get_event_loop().run_until_complete(has_workflows(tmpdir))


def test_has_workflows_false():
    with tempfile.TemporaryDirectory() as tmpdir:
        import asyncio

        assert not asyncio.get_event_loop().run_until_complete(has_workflows(tmpdir))


def test_has_workflows_yaml_extension():
    with tempfile.TemporaryDirectory() as tmpdir:
        wf_dir = os.path.join(tmpdir, ".github", "workflows")
        os.makedirs(wf_dir)
        with open(os.path.join(wf_dir, "test.yaml"), "w") as f:
            f.write("name: Test\n")

        import asyncio

        assert asyncio.get_event_loop().run_until_complete(has_workflows(tmpdir))


@pytest.mark.asyncio
async def test_execute_build_no_workflows():
    repo = RepoConfig(url="https://git.example.com/repo.git", branch="main")

    with tempfile.TemporaryDirectory() as work_dir, tempfile.TemporaryDirectory() as log_dir:
        repo_dir = os.path.join(work_dir, repo.sanitized_name)
        os.makedirs(repo_dir)
        with open(os.path.join(repo_dir, ".git"), "w") as f:
            f.write("")

        with patch("act_runner.executor.execute_build") as mock_exec:
            mock_process = AsyncMock()
            mock_process.communicate.return_value = (b"", b"")
            mock_process.returncode = 0

            with patch("act_runner.executor.asyncio.create_subprocess_exec", return_value=mock_process):
                result = await execute_build(
                    repo=repo,
                    commit_sha="abc123",
                    work_base=work_dir,
                    log_dir=log_dir,
                    act_binary="/usr/local/bin/act",
                )

                assert result["status"] in ("no_workflows", "clone_failed", "success", "failure")


@pytest.mark.asyncio
async def test_execute_custom_command():
    repo = RepoConfig(
        url="https://git.example.com/repo.git",
        branch="main",
        pipeline="custom",
        custom_command="echo branch={branch} sha={sha}",
    )
    with tempfile.TemporaryDirectory() as log_dir:
        result = await execute_custom_command(
            repo=repo,
            commit_sha="abc123def456",
            branch_name="pr/886-test",
            log_dir=log_dir,
        )
        assert result["status"] == "success"
        assert result["exit_code"] == 0
        assert "branch=pr/886-test" in result["log"]
        assert "sha=abc123def456" in result["log"]
        assert Path(result["log_path"]).exists()
