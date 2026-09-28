import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from act_runner.watcher import watch_repos, get_remote_head, get_pr_branches
from act_runner.config import RepoConfig


@pytest.mark.asyncio
async def test_get_remote_head_success():
    repo = RepoConfig(url="https://git.example.com/repo.git", branch="main")
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b"abc123def456\trefs/heads/main\n", b"")
    mock_process.returncode = 0

    with patch("act_runner.watcher.asyncio.create_subprocess_exec", return_value=mock_process):
        sha = await get_remote_head(repo)
        assert sha == "abc123def456"


@pytest.mark.asyncio
async def test_get_remote_head_failure():
    repo = RepoConfig(url="https://git.example.com/repo.git", branch="main")
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b"", b"fatal: repository not found")
    mock_process.returncode = 128

    with patch("act_runner.watcher.asyncio.create_subprocess_exec", return_value=mock_process):
        sha = await get_remote_head(repo)
        assert sha is None


@pytest.mark.asyncio
async def test_get_remote_head_empty():
    repo = RepoConfig(url="https://git.example.com/repo.git", branch="nonexistent")
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b"", b"")
    mock_process.returncode = 0

    with patch("act_runner.watcher.asyncio.create_subprocess_exec", return_value=mock_process):
        sha = await get_remote_head(repo)
        assert sha is None


@pytest.mark.asyncio
async def test_get_remote_head_timeout():
    repo = RepoConfig(url="https://git.example.com/repo.git", branch="main")

    async def hang(*args, **kwargs):
        mock = AsyncMock()
        mock.communicate.side_effect = asyncio.TimeoutError()
        return mock

    with patch("act_runner.watcher.asyncio.create_subprocess_exec", side_effect=hang):
        sha = await get_remote_head(repo)
        assert sha is None


@pytest.mark.asyncio
async def test_watch_repos_detects_new_commit():
    repo = RepoConfig(url="https://git.example.com/repo.git", branch="main")
    changes = []

    async def on_change(r, sha):
        changes.append((r.url, sha))
        stop_event.set()

    def get_last(url, branch):
        return None

    stop_event = asyncio.Event()

    async def mock_get_remote_head(r):
        return "newsha123"

    with patch("act_runner.watcher.get_remote_head", side_effect=mock_get_remote_head):
        await watch_repos([repo], on_change, get_last, 30, stop_event)

    assert len(changes) == 1
    assert changes[0] == ("https://git.example.com/repo.git", "newsha123")


@pytest.mark.asyncio
async def test_watch_repos_skips_same_commit():
    repo = RepoConfig(url="https://git.example.com/repo.git", branch="main")
    changes = []

    async def on_change(r, sha):
        changes.append((r.url, sha))

    def get_last(url, branch):
        return "samesha123"

    stop_event = asyncio.Event()

    call_count = 0

    async def mock_get_remote_head(r):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            stop_event.set()
        return "samesha123"

    with patch("act_runner.watcher.get_remote_head", side_effect=mock_get_remote_head):
        await watch_repos([repo], on_change, get_last, 0, stop_event)

    assert len(changes) == 0


@pytest.mark.asyncio
async def test_watch_repos_stops_immediately():
    repo = RepoConfig(url="https://git.example.com/repo.git", branch="main")
    stop_event = asyncio.Event()
    stop_event.set()

    async def mock_get_remote_head(r):
        return None

    with patch("act_runner.watcher.get_remote_head", side_effect=mock_get_remote_head):
        await watch_repos(
            [repo],
            on_change=AsyncMock(),
            get_last_commit_fn=lambda u, b: None,
            poll_interval=1,
            stop_event=stop_event,
        )


@pytest.mark.asyncio
async def test_watch_repos_handles_none_head():
    repo = RepoConfig(url="https://git.example.com/repo.git", branch="main")
    changes = []

    async def on_change(r, sha):
        changes.append((r.url, sha))

    stop_event = asyncio.Event()

    call_count = 0

    async def mock_get_remote_head(r):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            stop_event.set()
        return None

    with patch("act_runner.watcher.get_remote_head", side_effect=mock_get_remote_head):
        await watch_repos([repo], on_change, lambda u, b: None, 0, stop_event)

    assert len(changes) == 0


@pytest.mark.asyncio
async def test_get_pr_branches():
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (
        b"sha1\trefs/heads/pr/886-foo\nsha2\trefs/heads/pr/926-bar\n",
        b"",
    )
    mock_process.returncode = 0

    with patch("act_runner.watcher.asyncio.create_subprocess_exec", return_value=mock_process):
        branches = await get_pr_branches("https://git.example.com/repo.git")
        assert len(branches) == 2
        assert branches[0] == ("pr/886-foo", "sha1")
        assert branches[1] == ("pr/926-bar", "sha2")


@pytest.mark.asyncio
async def test_get_pr_branches_empty():
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b"", b"")
    mock_process.returncode = 0

    with patch("act_runner.watcher.asyncio.create_subprocess_exec", return_value=mock_process):
        branches = await get_pr_branches("https://git.example.com/repo.git")
        assert branches == []


@pytest.mark.asyncio
async def test_watch_repos_pr_branch_trigger():
    repo = RepoConfig(
        url="https://git.example.com/repo.git",
        branch="master",
        trigger="pr_branch",
    )
    changes = []

    async def on_change(r, sha, branch_name=""):
        changes.append((r.url, sha, branch_name))
        stop_event.set()

    stop_event = asyncio.Event()

    async def mock_get_pr_branches(url):
        return [("pr/886-foo", "newsha123")]

    with patch("act_runner.watcher.get_pr_branches", side_effect=mock_get_pr_branches):
        await watch_repos([repo], on_change, lambda u, b: None, 30, stop_event)

    assert len(changes) == 1
    assert changes[0] == ("https://git.example.com/repo.git", "newsha123", "pr/886-foo")
