# nsite E2E Dashboard — Upstream PR Plan

## Problem

E2E test dashboard URLs posted to PlebeianApp/market PRs returned 404.
Root causes: wrong URL format (path vs subdomain), hex vs bech32 npub, missing DNS wildcard.

## What's Done

- [x] Fix `publish.sh`: hex→bech32 npub, path→subdomain URL (commit `f711cac`)
- [x] Create `test-publish-url.sh` — 10/10 assertions pass
- [x] Fix DNS: `*.nsite.orangesync.tech` → `23.182.128.51`, remove dead records
- [x] E2E verification: CI run #27241295341 — dashboard loads with 130 test results
- [x] Update infra PROGRESS.md/PLAN.md

## What's Left

### Step 1: Make `announce-nsec` optional in `plebeian-testing-nsite-actions`

- [ ] Edit `.github/actions/publish-nsite/action.yml`: `required: true` → `required: false`, add `default: ''`
- [ ] Commit + push to `main`

**Why**: So the workflow works on any repo without the `CI_ANNOUNCE_NSEC` secret. The shell script already handles empty `ANNOUNCE_NSEC` gracefully (skips Kind 1985 announcement).

### Step 2: Create clean branch off `PlebeianApp/market` master

- [ ] Create branch `ci/nsite-e2e-dashboard-sharding` off `plebian/master`
- [ ] Cherry-pick 7 commits (all verified: zero conflicts):

| # | Commit | Message |
|---|--------|---------|
| 1 | `f0b352c0` | feat(ci): add nsite dashboard publishing to E2E workflow |
| 2 | `ccb99ca9` | feat(ci): add 3-way sharding with conditional screenshot re-run |
| 3 | `204d7f04` | fix(ci): skip e2e-report when e2e-shard was skipped |
| 4 | `b0d17eb3` | fix(ci): make extract-failures resilient to missing arrays |
| 5 | `9c409af3` | fix(ci): backup first-pass results before re-run clears outputDir |
| 6 | `db005499` | fix(ci): save first-pass results outside outputDir |
| 7 | `68d02035` | fix(ci): make merge-results resilient to missing arrays |

Files touched (4 only, no source code changes):
- `.github/workflows/e2e.yml` (modified)
- `e2e/playwright.config.ts` (modified)
- `e2e/extract-failures.ts` (new)
- `e2e/merge-results.ts` (new)

### Step 3: Push branch + open PR to `PlebeianApp/market`

- [ ] Push `ci/nsite-e2e-dashboard-sharding` to fork
- [ ] Open PR to `PlebeianApp/market` master
- [ ] PR title: `ci: nsite E2E dashboard publishing with 3-way sharding`

Key points for PR body:
- CI/test infrastructure only — no source code changes
- Uses public composite actions from `c03rad0r/plebeian-testing-nsite-actions`
- `CI_ANNOUNCE_NSEC` secret optional — works without it
- Sharding: 3 parallel jobs + report job (faster CI)
- `e2e-shard`/`e2e-report` only run on `workflow_dispatch` or `schedule` — no overhead on normal PRs

### Step 4: Update infra tracking

- [ ] Update `PROGRESS.md` in tollgate-infrastructure-kit

## Dependency Chain

```
Step 1 (optional announce-nsec) → Step 2 (cherry-pick) → Step 3 (open PR) → Step 4 (update docs)
```

## Repos Involved

| Repo | Action |
|------|--------|
| `c03rad0r/plebeian-testing-nsite-actions` | Make announce-nsec optional |
| `PlebeianApp/market` | New PR with cherry-picked CI commits |
| `c03rad0r/tollgate-infrastructure-kit` | Track progress |
