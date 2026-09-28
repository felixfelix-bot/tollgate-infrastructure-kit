import os
import tempfile
from pathlib import Path

import pytest
import yaml

from act_runner.config import RunnerConfig, RepoConfig


def test_repo_config_sanitized_name():
    repo = RepoConfig(url="https://git.orangesync.tech/my-repo.git", branch="main")
    assert repo.sanitized_name == "git_orangesync_tech_my-repo_git"


def test_repo_config_sanitized_name_trailing_slash():
    repo = RepoConfig(url="https://git.example.com/org/repo/")
    assert repo.sanitized_name == "git_example_com_org_repo"


def test_config_defaults():
    cfg = RunnerConfig()
    assert cfg.poll_interval == 30
    assert cfg.api_port == 8095
    assert cfg.act_binary == "/usr/local/bin/act"
    assert cfg.repos == []


def test_config_load_from_yaml():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(
            {
                "repos": [
                    {"url": "https://git.example.com/repo1.git", "branch": "main"},
                    {"url": "https://git.example.com/repo2.git", "branch": "develop"},
                ],
                "poll_interval": 60,
                "api_port": 9090,
                "relays": ["wss://relay.example.com"],
            },
            f,
        )
        f.flush()

        cfg = RunnerConfig.load(f.name)
        assert len(cfg.repos) == 2
        assert cfg.repos[0].url == "https://git.example.com/repo1.git"
        assert cfg.repos[0].branch == "main"
        assert cfg.repos[1].branch == "develop"
        assert cfg.poll_interval == 60
        assert cfg.api_port == 9090
        assert cfg.relays == ["wss://relay.example.com"]

    os.unlink(f.name)


def test_repo_config_custom_pipeline_defaults():
    repo = RepoConfig(url="https://git.example.com/repo.git", branch="main")
    assert repo.pipeline == "act"
    assert repo.custom_command == ""
    assert repo.trigger == "push"


def test_repo_config_custom_pipeline_fields():
    repo = RepoConfig(
        url="https://git.example.com/repo.git",
        branch="main",
        pipeline="custom",
        custom_command="bash /opt/test.sh --branch {branch} --commit {sha}",
        trigger="pr_branch",
    )
    assert repo.pipeline == "custom"
    assert repo.trigger == "pr_branch"
    assert "{branch}" in repo.custom_command


def test_config_load_custom_pipeline_from_yaml():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(
            {
                "repos": [
                    {
                        "url": "https://git.example.com/repo.git",
                        "branch": "master",
                        "pipeline": "custom",
                        "custom_command": "bash test.sh --branch {branch}",
                        "trigger": "pr_branch",
                    },
                ],
            },
            f,
        )
        f.flush()

        cfg = RunnerConfig.load(f.name)
        assert len(cfg.repos) == 1
        assert cfg.repos[0].pipeline == "custom"
        assert cfg.repos[0].trigger == "pr_branch"
        assert "bash test.sh" in cfg.repos[0].custom_command

    os.unlink(f.name)


def test_config_empty_yaml():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("")
        f.flush()

        cfg = RunnerConfig.load(f.name)
        assert cfg.repos == []
        assert cfg.poll_interval == 30

    os.unlink(f.name)
