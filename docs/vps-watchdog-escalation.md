# VPS Watchdog Escalation Architecture

## The Problem

Current watchdog is a script-only cron that alerts the user when it can't fix
something. We need a 3-tier escalation chain:

```
Tier 0: Script (free, every 10 min) → health check + mechanical fix
  ↓ fails
Tier 1: LLM agent (token burn) → diagnose root cause + fix autonomously
  ↓ fails
Tier 2: Surface to operator → only design decisions, not raw errors
```

## Architecture

### Tier 0: Script cron (no_agent=true)

`vps_nostr_health.py` — runs every 10 min, zero tokens:
1. SSH to VPS1, check tollgate-* containers
2. Check disk usage
3. If container stopped → attempt `docker restart` (fast mechanical fix)
4. If all healthy → exit 0 (silent)
5. If can't fix → write failure to state file + exit 1

When it exits 1, the cron output is delivered to the chat. But instead of
alerting the user directly, the output is formatted as a task instruction
for the agent to pick up.

### Tier 1: Agent cron (no_agent=false, triggered on failure)

A second cron runs every 10 min (offset 2 min from Tier 0). It's a lightweight
agent that:
1. Reads the state file to check if Tier 0 reported failures
2. If no failures → exit immediately (~200 tokens — negligible)
3. If failures → full diagnostic mode:
   - SSH to VPS, inspect container logs
   - Read Ansible playbooks to understand expected state
   - Run `ansible-playbook` to redeploy broken service
   - Check if fix worked
   - If fixed → report briefly what was wrong + what was done
   - If can't fix → Tier 2

The agent cron loads the `vps-nostr-watchdog` skill which has all the
context about the VPS architecture, Ansible roles, and common failures.

### Tier 2: Surface to operator

Only reached when the LLM agent can't fix it. Format:
```
⚠️ VPS Service Down — needs operator decision

SERVICE: tollgate-strfry (Nostr relay)
PROBLEM: Container exits immediately with "LMDB mapsize exceeded"
WHAT I TRIED: 
  - docker restart → same error
  - ansible-playbook redeploy → same error
  - Increased mapsize in strfry.conf → needs manual verification
DESIGN DECISION NEEDED: Increase LMDB mapsize from 5G to 10G? 
  This doubles disk usage for the relay database.
```

## Implementation

### Changes needed:

1. **Rewrite `vps_nostr_health.py`** — use `docker restart` for mechanical
   fix (not full Ansible redeploy). Simpler, faster, fewer dependencies.

2. **Create agent cron** — `vps-watchdog-agent` that runs every 10 min,
   checks state file, escalates if needed.

3. **Update skill** — add diagnostic procedures for common failures
   (container OOM, LMDB full, Caddy config errors, etc.)

4. **Soul.md rule** — "When infrastructure monitoring fires, autonomously
   diagnose and fix before surfacing to the operator."

5. **State file contract** — Tier 0 writes, Tier 1 reads + clears:

```json
{
  "alert_time": "2026-07-04T22:50:00Z",
  "vps": "66.92.204.38",
  "failures": [
    {
      "service": "tollgate-strfry",
      "reason": "container exited (status=137)",
      "mechanical_fix_attempted": "docker restart",
      "mechanical_fix_result": "failed",
      "container_logs": "...last 5 lines..."
    }
  ]
}
```

## Token Cost Analysis

| Scenario | Tokens burned | Frequency |
|----------|--------------|-----------|
| All healthy | ~0 (script only) | 99% of runs |
| Agent checks state file, no failure | ~200 | 1% of runs (false trigger) |
| Agent diagnoses + fixes | ~2000-5000 | Rare (first time per issue) |
| Agent can't fix, surfaces to user | ~3000-8000 | Very rare |

The 200-token "check state file" cost on every Tier 1 run is acceptable.
The agent prompt is just: "Read ~/.local/state/vps-nostr-watchdog/alert.json.
If it doesn't exist or is empty, exit immediately."
