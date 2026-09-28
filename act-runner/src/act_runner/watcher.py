import asyncio
import logging

from act_runner.config import RepoConfig

logger = logging.getLogger(__name__)


async def get_remote_head(repo: RepoConfig) -> str | None:
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            "ls-remote",
            repo.url,
            f"refs/heads/{repo.branch}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        if process.returncode != 0:
            logger.warning(
                f"git ls-remote failed for {repo.url}: {stderr.decode().strip()}"
            )
            return None
        output = stdout.decode().strip()
        if not output:
            logger.debug(f"No {repo.branch} branch found at {repo.url}")
            return None
        parts = output.split("\t")
        return parts[0].strip() if parts else None
    except asyncio.TimeoutError:
        logger.warning(f"git ls-remote timed out for {repo.url}")
        return None
    except Exception as e:
        logger.error(f"Error checking {repo.url}: {e}")
        return None


async def get_pr_branches(repo_url: str) -> list[tuple[str, str]]:
    try:
        process = await asyncio.create_subprocess_exec(
            "git", "ls-remote", "--refs", repo_url, "refs/heads/pr/*",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        if process.returncode != 0:
            return []
        lines = stdout.decode().strip().split("\n")
        results = []
        for line in lines:
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) == 2:
                sha = parts[0].strip()
                ref = parts[1].strip().replace("refs/heads/", "")
                results.append((ref, sha))
        return results
    except (asyncio.TimeoutError, Exception):
        return []


async def watch_repos(
    repos: list[RepoConfig],
    on_change,
    get_last_commit_fn,
    poll_interval: int = 30,
    stop_event: asyncio.Event | None = None,
):
    if stop_event is None:
        stop_event = asyncio.Event()

    while not stop_event.is_set():
        for repo in repos:
            if stop_event.is_set():
                break

            if repo.trigger == "pr_branch":
                branches = await get_pr_branches(repo.url)
                for branch_name, remote_head in branches:
                    if stop_event.is_set():
                        break
                    last_commit = get_last_commit_fn(repo.url, branch_name)
                    if last_commit is None or last_commit != remote_head:
                        logger.info(
                            f"New commit on {repo.url} ({branch_name}): {remote_head[:12]}"
                        )
                        await on_change(repo, remote_head, branch_name=branch_name)
            else:
                remote_head = await get_remote_head(repo)
                if remote_head is None:
                    continue
                last_commit = get_last_commit_fn(repo.url, repo.branch)
                if last_commit is None or last_commit != remote_head:
                    logger.info(
                        f"New commit on {repo.url} ({repo.branch}): {remote_head[:12]}"
                    )
                    await on_change(repo, remote_head)

        if stop_event.is_set():
            break

        stopped = False
        for _ in range(poll_interval):
            if stop_event.is_set():
                stopped = True
                break
            await asyncio.sleep(1)
        if stopped:
            break
