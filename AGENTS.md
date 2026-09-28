# AGENTS.md

## Standing Instructions

1. **Always maintain these files:**
   - `PLAN.md` — up-to-date implementation plan for the entire repo
   - `PROGRESS.md` — checklist of done/pending items

2. **Testing requirements:**
   - All code must have unit tests, integration tests, E2E tests, and Playwright tests where applicable
   - Run all tests before committing

3. **Commit discipline:**
   - Commit every time a test passes that previously didn't pass
   - Commit after completing each logical unit of work
   - Push to git remote after each commit

4. **No comments in code** unless explicitly requested

5. **No secrets in git** — all secrets in `.env` (gitignored)

6. **Ansible safety** — destructive system ops (apt upgrade, UFW, fail2ban, timezone) must be opt-in with safe defaults

7. **Code style** — follow existing patterns in the codebase; check neighboring files for conventions

## Repository Structure

```
tollgate-infrastructure-kit/
├── AGENTS.md              # This file — standing instructions
├── PLAN.md                # Implementation plan
├── PROGRESS.md            # Checklist of done/pending items
├── .env                   # Secrets (gitignored)
├── ansible/               # Ansible playbooks and roles
├── mint-orchestrator/     # Python orchestrator daemon
├── mint-approve/          # CLI approval tool
├── mint-dashboard/        # Web dashboard
├── scripts/               # Deploy/test scripts
├── tests/                 # Integration and E2E tests
└── docs/                  # Documentation
```

## Key Decisions

- **Mint software**: CDK (cashubtc/cdk) — `cashubtc/mintd` Docker image with `cdk-mint-rpc` gRPC
- **Reverse proxy**: Caddy (not Traefik)
- **Approval mechanism**: Nostr kind 38010 events with cryptographic signatures
- **Orchestrator language**: Python
- **VPS**: Debian 13, SSH key auth, domain on Cloudflare
