import asyncio
import logging
import os
import signal
from datetime import datetime, timezone

from act_runner.api import RunnerAPI
from act_runner.config import RunnerConfig, RepoConfig
from act_runner.db import BuildDB, Build
from act_runner.executor import execute_build, execute_custom_command
from act_runner.nostr_publisher import build_nostr_event, publish_event
from act_runner.watcher import watch_repos, get_remote_head

logger = logging.getLogger(__name__)

_build_queue: asyncio.Queue | None = None
_db: BuildDB | None = None
_config: RunnerConfig | None = None
_stop_event: asyncio.Event | None = None


async def queue_build(repo: RepoConfig, commit_sha: str, branch_name: str = "") -> int | None:
    if _build_queue is None or _db is None:
        return None
    effective_branch = branch_name or repo.branch
    logger.info(f"Triggered build for {repo.url} ({effective_branch}) @ {commit_sha[:12]}")
    await _build_queue.put((repo, commit_sha, effective_branch))
    return 0


async def _on_repo_change(repo, commit_sha: str, branch_name: str = ""):
    if _build_queue is None:
        return
    effective_branch = branch_name or repo.branch
    logger.info(f"Queueing build for {repo.url} ({effective_branch}) @ {commit_sha[:12]}")
    await _build_queue.put((repo, commit_sha, effective_branch))


async def _build_worker():
    while True:
        repo, commit_sha, branch_name = await _build_queue.get()
        try:
            await _run_build(repo, commit_sha, branch_name)
        except Exception as e:
            logger.error(f"Build failed with exception: {e}", exc_info=True)
        finally:
            _build_queue.task_done()


async def _run_build(repo, commit_sha: str, branch_name: str):
    now = datetime.now(timezone.utc).isoformat()
    build = Build(
        repo_url=repo.url,
        repo_name=repo.sanitized_name,
        branch=branch_name,
        commit_sha=commit_sha,
        status="running",
        started_at=now,
    )
    build_id = _db.insert_build(build)
    logger.info(f"Starting build #{build_id}: {repo.url} @ {commit_sha[:12]}")

    try:
        if repo.pipeline == "custom":
            result = await execute_custom_command(
                repo=repo,
                commit_sha=commit_sha,
                branch_name=branch_name,
                log_dir=_config.log_dir,
            )
        else:
            result = await execute_build(
                repo=repo,
                commit_sha=commit_sha,
                work_base=_config.work_dir,
                log_dir=_config.log_dir,
                act_binary=_config.act_binary,
                secrets=_config.secrets,
                artifact_dir=_config.artifact_dir,
            )
    except Exception as e:
        _db.update_build(
            build_id,
            status="error",
            error=str(e),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.error(f"Build #{build_id} error: {e}")
        return

    finished = datetime.now(timezone.utc).isoformat()
    _db.update_build(
        build_id,
        status=result["status"],
        exit_code=result.get("exit_code"),
        duration_ms=result.get("duration_ms"),
        log_path=result.get("log_path"),
        finished_at=finished,
    )

    logger.info(
        f"Build #{build_id} finished: {result['status']} in {result.get('duration_ms', 0)}ms"
    )

    if result["status"] in ("success", "failure"):
        log_url = f"https://runner.{os.environ.get('BASE_DOMAIN', 'localhost')}/api/builds/{build_id}/log"
        event = build_nostr_event(
            repo_url=repo.url,
            commit_sha=commit_sha,
            branch=branch_name,
            status=result["status"],
            duration_ms=result.get("duration_ms", 0),
            log_url=log_url,
            nsec=_config.nsec,
        )
        published = await publish_event(event, _config.relays)
        logger.info(f"Published CI result to {len(published)}/{len(_config.relays)} relays")


async def run_daemon():
    global _build_queue, _db, _config, _stop_event

    _config = RunnerConfig.load()
    log_level = getattr(logging, _config.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    logger.info(
        f"Starting act-runner with {len(_config.repos)} repos, poll interval {_config.poll_interval}s"
    )

    _db = BuildDB(_config.db_path)
    _build_queue = asyncio.Queue()
    _stop_event = asyncio.Event()

    api = RunnerAPI(_config, _db, trigger_fn=queue_build)
    await api.start()

    loop = asyncio.get_event_loop()

    def _signal_handler():
        _stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    worker_task = asyncio.create_task(_build_worker())
    watcher_task = asyncio.create_task(
        watch_repos(
            repos=_config.repos,
            on_change=_on_repo_change,
            get_last_commit_fn=_db.get_last_commit,
            poll_interval=_config.poll_interval,
            stop_event=_stop_event,
        )
    )

    try:
        await _stop_event.wait()
    finally:
        watcher_task.cancel()
        worker_task.cancel()
        for task in (watcher_task, worker_task):
            try:
                await task
            except asyncio.CancelledError:
                pass
        await api.stop()


def main():
    asyncio.run(run_daemon())


if __name__ == "__main__":
    main()
