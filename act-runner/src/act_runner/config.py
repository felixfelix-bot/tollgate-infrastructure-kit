import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class RepoConfig:
    url: str
    branch: str = "main"
    pipeline: str = "act"
    custom_command: str = ""
    trigger: str = "push"

    @property
    def sanitized_name(self) -> str:
        return (
            self.url.rstrip("/")
            .replace("https://", "")
            .replace("http://", "")
            .replace("/", "_")
            .replace(".", "_")
            .replace(":", "_")
        )


@dataclass
class RunnerConfig:
    config_path: str = "/opt/tollgate/act-runner/config.yaml"
    db_path: str = "/opt/tollgate/act-runner/builds.db"
    work_dir: str = "/opt/tollgate/act-runner/work"
    log_dir: str = "/opt/tollgate/act-runner/logs"
    artifact_dir: str = "/opt/tollgate/act-runner/artifacts"
    poll_interval: int = 30
    api_host: str = "0.0.0.0"
    api_port: int = 8095
    act_binary: str = "/usr/local/bin/act"
    relays: list[str] = field(default_factory=lambda: ["wss://ngit.orangesync.tech"])
    nsec: str = ""
    npub: str = ""
    log_level: str = "info"
    repos: list[RepoConfig] = field(default_factory=list)
    secrets: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "RunnerConfig":
        path = config_path or os.environ.get(
            "ACT_RUNNER_CONFIG", "/opt/tollgate/act-runner/config.yaml"
        )

        cfg = cls()

        if not Path(path).exists():
            logger.warning(f"Config file not found: {path}, using defaults")
            cfg._apply_env_overrides()
            return cfg

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        if "repos" in data and data["repos"] is not None:
            repos = []
            for r in data["repos"]:
                repo = RepoConfig(
                    url=r["url"],
                    branch=r.get("branch", "main"),
                    pipeline=r.get("pipeline", "act"),
                    custom_command=r.get("custom_command", ""),
                    trigger=r.get("trigger", "push"),
                )
                repos.append(repo)
            cfg.repos = repos
        if "poll_interval" in data:
            cfg.poll_interval = int(data["poll_interval"])
        if "api_port" in data:
            cfg.api_port = int(data["api_port"])
        if "api_host" in data:
            cfg.api_host = data["api_host"]
        if "db_path" in data:
            cfg.db_path = data["db_path"]
        if "work_dir" in data:
            cfg.work_dir = data["work_dir"]
        if "log_dir" in data:
            cfg.log_dir = data["log_dir"]
        if "artifact_dir" in data:
            cfg.artifact_dir = data["artifact_dir"]
        if "act_binary" in data:
            cfg.act_binary = data["act_binary"]
        if "relays" in data:
            cfg.relays = data["relays"]
        if "log_level" in data:
            cfg.log_level = data["log_level"]

        cfg._apply_env_overrides()
        return cfg

    def _apply_env_overrides(self):
        env_map = {
            "ACT_RUNNER_NSEC": "nsec",
            "ACT_RUNNER_NPUB": "npub",
            "ACT_RUNNER_API_HOST": "api_host",
            "ACT_RUNNER_API_PORT": "api_port",
            "ACT_RUNNER_LOG_LEVEL": "log_level",
            "ACT_RUNNER_POLL_INTERVAL": "poll_interval",
            "ACT_RUNNER_DB_PATH": "db_path",
            "ACT_RUNNER_WORK_DIR": "work_dir",
            "ACT_RUNNER_ARTIFACT_DIR": "artifact_dir",
        }
        for env_key, attr in env_map.items():
            val = os.environ.get(env_key)
            if val:
                if attr in ("api_port", "poll_interval"):
                    setattr(self, attr, int(val))
                else:
                    setattr(self, attr, val)

        for env_key, secret_name in os.environ.items():
            if env_key.startswith("ACT_RUNNER_SECRET_"):
                key = env_key[len("ACT_RUNNER_SECRET_"):]
                self.secrets[key] = os.environ[env_key]
