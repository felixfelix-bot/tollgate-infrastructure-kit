# ACT Runner Custom Pipeline Support

Adds `pipeline: custom` mode to act-runner, enabling it to run arbitrary shell commands (e.g. `test-pr.sh`) instead of `nektos/act`. Primary use case: Plebeian Market E2E testing via `pr/*` branch triggers.

## Phase 1: Source Code Changes

### 1a. `config.py` — Extend `RepoConfig`

- [x] Add `pipeline: str = "act"` field
- [x] Add `custom_command: str = ""` field
- [x] Add `trigger: str = "push"` field
- [x] Parse new fields from YAML in `RunnerConfig.load()`

### 1b. `watcher.py` — PR branch detection

- [x] Add `get_pr_branches(repo_url) -> list[tuple[str, str]]` function
- [x] In `watch_repos()`, branch on `repo.trigger == "pr_branch"`
- [x] Change `on_change` signature to accept optional `branch_name` param

### 1c. `executor.py` — Custom command execution

- [x] Add `execute_custom_command(repo, commit_sha, branch_name, log_dir) -> dict`
- [x] Substitute `{branch}` and `{sha}` in command template
- [x] Set `ACT_RUNNER_BRANCH` / `ACT_RUNNER_COMMIT` env vars
- [x] Capture output, write log file, return result dict

### 1d. `daemon.py` — Pipeline dispatch

- [x] Update `_on_repo_change` to accept `branch_name` param
- [x] Queue 3-tuple `(repo, commit_sha, branch_name)`
- [x] `_build_worker` unpacks 3-tuple
- [x] `_run_build` uses `branch_name` for Build record
- [x] Dispatch to `execute_custom_command()` when `repo.pipeline == "custom"`

## Phase 2: Tests

### 2a. `test_config.py`

- [x] Test `RepoConfig` new fields default correctly
- [x] Test YAML parsing of `pipeline`, `custom_command`, `trigger`

### 2b. `test_watcher.py`

- [x] Test `get_pr_branches()` with mock subprocess output
- [x] Test `watch_repos` with `trigger: pr_branch` invokes on_change with branch_name

### 2c. `test_executor.py`

- [x] Test `execute_custom_command` runs command, substitutes vars, writes log

### 2d. Run all tests

- [x] `pytest` passes all tests (old + new)

## Phase 3: Ansible & Config

### 3a. Config template

- [x] `act-runner-config.yaml.j2` renders `pipeline`, `custom_command`, `trigger` per repo

### 3b. Group vars

- [x] `group_vars/all.yml` — update `market` repo entry with custom pipeline config

## Phase 4: Deploy (manual)

- [ ] Run Ansible playbook `27-act-runner.yml` to redeploy act-runner
- [ ] Push a `pr/*` branch to `market` repo on GRASP
- [ ] Verify act-runner detects PR branch, runs `test-pr.sh`
- [ ] Verify Nostr Kind 1985 event published with build result

## Files Changed

| File | Change |
|------|--------|
| `act-runner/src/act_runner/config.py` | 3 new fields on `RepoConfig` + YAML parsing |
| `act-runner/src/act_runner/watcher.py` | `get_pr_branches()` + `pr_branch` trigger in `watch_repos()` |
| `act-runner/src/act_runner/executor.py` | `execute_custom_command()` |
| `act-runner/src/act_runner/daemon.py` | 3-tuple queue, branch_name passthrough, custom dispatch |
| `act-runner/src/act_runner/tests/test_config.py` | 2 new tests |
| `act-runner/src/act_runner/tests/test_watcher.py` | 2 new tests |
| `act-runner/src/act_runner/tests/test_executor.py` | 1 new test |
| `ansible/roles/act_runner/templates/act-runner-config.yaml.j2` | Render new fields |
| `ansible/inventory/group_vars/all.yml` | Market repo custom pipeline config |
