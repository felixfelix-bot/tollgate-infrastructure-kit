import asyncio
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from act_runner.config import RepoConfig

logger = logging.getLogger(__name__)


async def has_workflows(work_dir: str) -> bool:
    wf_dir = Path(work_dir) / ".github" / "workflows"
    if not wf_dir.exists():
        return False
    return any(wf_dir.glob("*.yml")) or any(wf_dir.glob("*.yaml"))


async def run_act(
    work_dir: str,
    act_binary: str = "/usr/local/bin/act",
    secrets: dict[str, str] | None = None,
    artifact_path: str = "",
) -> tuple[int, str, str]:
    cmd = [act_binary, "push", "--bind", "--concurrent-jobs", "1"]
    for key, value in (secrets or {}).items():
        cmd.extend(["-s", f"{key}={value}"])
    if artifact_path:
        os.makedirs(artifact_path, exist_ok=True)
        cmd.extend(["--artifact-server-path", artifact_path])
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=work_dir,
        env={**os.environ, "ACT": "true"},
    )
    stdout, _ = await process.communicate()
    output = stdout.decode(errors="replace")
    return process.returncode or 0, output, ""


async def execute_build(
    repo: RepoConfig,
    commit_sha: str,
    work_base: str,
    log_dir: str,
    act_binary: str = "/usr/local/bin/act",
    secrets: dict[str, str] | None = None,
    artifact_dir: str = "",
) -> dict:
    repo_work_dir = os.path.join(work_base, repo.sanitized_name)
    os.makedirs(repo_work_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    if os.path.exists(repo_work_dir):
        subprocess.run(["sudo", "rm", "-rf", repo_work_dir], check=False)

    clone_start = time.monotonic()
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            repo.branch,
            repo.url,
            repo_work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
        if process.returncode != 0:
            error = stderr.decode(errors="replace").strip()
            logger.error(f"git clone failed for {repo.url}: {error}")
            return {
                "status": "clone_failed",
                "exit_code": process.returncode,
                "log": error,
                "duration_ms": int((time.monotonic() - clone_start) * 1000),
                "log_path": None,
            }
    except asyncio.TimeoutError:
        return {
            "status": "clone_timeout",
            "exit_code": -1,
            "log": "git clone timed out",
            "duration_ms": int((time.monotonic() - clone_start) * 1000),
            "log_path": None,
        }

    if not await has_workflows(repo_work_dir):
        logger.info(f"No .github/workflows found in {repo.url}")
        return {
            "status": "no_workflows",
            "exit_code": 0,
            "log": "No .github/workflows/*.yml files found",
            "duration_ms": int((time.monotonic() - clone_start) * 1000),
            "log_path": None,
        }

    build_start = time.monotonic()
    exit_code, act_output, _ = await run_act(
        repo_work_dir, act_binary, secrets=secrets, artifact_path=artifact_dir,
    )
    duration_ms = int((time.monotonic() - build_start) * 1000)

    log_path = os.path.join(log_dir, f"{repo.sanitized_name}_{commit_sha[:12]}.log")
    with open(log_path, "w") as f:
        f.write(act_output)

    status = "success" if exit_code == 0 else "failure"

    return {
        "status": status,
        "exit_code": exit_code,
        "log": act_output,
        "duration_ms": duration_ms,
        "log_path": log_path,
    }


async def execute_custom_command(
    repo: RepoConfig,
    commit_sha: str,
    branch_name: str,
    log_dir: str,
) -> dict:
    os.makedirs(log_dir, exist_ok=True)

    command = repo.custom_command
    command = command.replace("{branch}", branch_name)
    command = command.replace("{sha}", commit_sha)

    build_start = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        "bash", "-c", command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "ACT_RUNNER_BRANCH": branch_name, "ACT_RUNNER_COMMIT": commit_sha},
    )
    stdout, _ = await process.communicate()
    output = stdout.decode(errors="replace")
    duration_ms = int((time.monotonic() - build_start) * 1000)

    safe_branch = branch_name.replace("/", "_")
    log_path = os.path.join(log_dir, f"{repo.sanitized_name}_{safe_branch}_{commit_sha[:12]}.log")
    with open(log_path, "w") as f:
        f.write(output)

    status = "success" if process.returncode == 0 else "failure"

    return {
        "status": status,
        "exit_code": process.returncode or 0,
        "log": output,
        "duration_ms": duration_ms,
        "log_path": log_path,
    }
