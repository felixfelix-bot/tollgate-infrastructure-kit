# Plan: Squash Merge `act-runner-tollgate-module-ci` → `main`

## Context

The `act-runner-tollgate-module-ci` branch has diverged from `main` by **50 commits**
(150 files changed, +6,779 / -642 lines). The merge is **conflict-free** (verified via
`git merge-tree --write-tree main HEAD`, exit 0). Main has 1 commit not on the branch
(`81bc548e` keypair fix), but its patch is byte-for-byte identical to branch commit
`f4a69693`, so git merges it trivially.

This plan squashes all 50 commits into a single commit on `main`.

## Branch Stats

| Metric | Value |
|--------|-------|
| Commits ahead | 50 |
| Commits behind | 1 (identical patch, no real divergence) |
| Files changed | 150 (71 new) |
| Lines | +6,779 / -642 |
| Merge conflicts | None |
| Merge base | `df072299` |

## Checklist

### Step 0 — Stash local doc changes
- [x] `git stash push -m "local doc edits — not for merge" -- PROGRESS.md docs/nsite-upstream-pr-plan.md`
- [x] Verify working tree is clean (untracked `auditable-voting/` is OK — it stays)

### Step 1 — Checkout main and squash merge
- [x] `git checkout main`
- [x] `git merge --squash act-runner-tollgate-module-ci` — clean, 147 files staged
- [x] Verify staged changes look correct (`git status`)

### Step 2 — Commit
- [x] `git commit` — `bb4b6c28` created
- [x] Verify single new commit on main (`git log --oneline -3`)

### Step 3 — Restore local doc edits
- [x] `git stash pop` — applied cleanly, no conflicts
- [x] Verify PROGRESS.md and nsite-upstream-pr-plan.md have local edits back
- [x] Resolve stash conflict if any (none)

### Step 4 — Push
- [x] `git push origin main` — pushed `81bc548..bb4b6c2`

## Post-Merge Verification
- [x] `git log --oneline -5` — main has the squash commit at HEAD (`bb4b6c28`)
- [x] `git status` — working tree has local doc edits + untracked auditable-voting/
- [x] `git diff main act-runner-tollgate-module-ci --stat` — empty (branch fully merged)

## Risk Assessment: Low
- Merge verified clean via `git merge-tree`
- No secrets in diff (only `.env.example` with empty placeholders)
- Stash protects local doc edits
- Duplicate commit on main absorbed cleanly (identical patch)
