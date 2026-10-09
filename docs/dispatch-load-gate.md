# Dispatch resource gate (per-CPU + PSI, hard memory/swap)

`staggered-dispatch.sh` gates each dispatch pass on host resources. The old
absolute `LOAD_THRESHOLD=3.4` did not scale with cores and treated
uninterruptible IO wait as load, so a box doing disk work read as "loaded"
while its CPUs were idle, and the same number meant different things on every
host.

## Verdicts

`resource_verdict()` returns one of:

- **0 — ok**: dispatch normally.
- **1 — degrade**: a *soft* CPU/PSI breach. Dispatch exactly **one** board pass
  (CPU pressure should reduce concurrency, not stop dispatch entirely).
- **2 — stop**: a *hard* breach. No dispatch.

## Policy (precedence: env > `dispatch_policy.json` > defaults)

| key | default | kind | signal |
|---|---|---|---|
| `cpu.per_core` / `CPU_PER_CORE` | 0.8 | soft | `load1 / nproc` |
| `cpu.storm_per_core` / `CPU_STORM_PER_CORE` | 2.0 | hard | `load1 / nproc` |
| `memory.min_available_mb` / `RAM_MIN_MB` | 1536 | hard | `MemAvailable` |
| `swap.max_used_pct` / `SWAP_MAX_PCT` | 90 | hard | swap used % |
| `psi.cpu_avg10_max` / `PSI_CPU_MAX` | 2.0 | soft | `/proc/pressure/cpu` full avg10 |
| `psi.memory_avg10_max` / `PSI_MEM_MAX` | 1.0 | hard | `/proc/pressure/memory` full avg10 |

Memory/swap are the **hard** stop because the observed failure was oomd killing
workers under memory pressure, not CPU starvation. CPU is the **soft** signal:
a breach reduces to one pass. PSI measures actual contention (not IO wait) and
is preferred where available; the loadavg path is the fallback.

## Metric sources (injectable for tests)

`NPROC`, `LOADAVG_FILE` (`/proc/loadavg`), `MEMINFO_FILE` (`/proc/meminfo`),
`PRESSURE_CPU_FILE` (`/proc/pressure/cpu`), `PRESSURE_MEM_FILE`
(`/proc/pressure/memory`).

## Tests

`bash tests/test_staggered_dispatch.sh` — legs `t16`–`t21` cover the gate with
injected `/proc` fixtures: CPU soft-degrade (one pass), CPU storm (no dispatch),
memory hard stop, swap hard stop, cpu PSI degrade, mem PSI hard stop.
