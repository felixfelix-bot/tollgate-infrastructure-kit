# ADR Index — FIPS Private Mesh

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](ADR-001-use-fips-mesh-for-device-connectivity.md) | Use FIPS mesh for device-to-device connectivity | Accepted |
| [ADR-002](ADR-002-private-mesh-not-public-test-mesh.md) | Private mesh instead of public test mesh (bloom filter saturation) | Accepted |
| [ADR-003](ADR-003-vps2-as-hub-in-hub-and-spoke.md) | VPS2 as hub in hub-and-spoke topology | Accepted |
| [ADR-004](ADR-004-pin-fips-version-to-v0.4.1.md) | Pin FIPS version to v0.4.1 | Accepted |
| [ADR-005](ADR-005-nostr-discovery-configured-only.md) | Nostr discovery with configured_only policy | Accepted |
| [ADR-006](ADR-006-two-pass-deployment-for-npub-discovery.md) | Two-pass deployment for persistent identity npub discovery | Accepted |
| [ADR-007](ADR-007-ansible-role-for-config-management.md) | Ansible role for reproducible config management | Accepted |
| [ADR-008](ADR-008-tcp-fallback-transport.md) | TCP fallback transport (UDP silently fails) | Accepted |
| [ADR-009](ADR-009-fips-dns-required-for-dot-fips-resolution.md) | fips-dns required for .fips DNS resolution | Accepted |
| [ADR-010](ADR-010-ssh-over-fips-standard-sshd.md) | SSH-over-FIPS uses standard sshd on [::]:22 | Accepted |
| [ADR-011](ADR-011-fips-ingress-gate-for-home-services.md) | FIPS ingress gate for hosting services from home machines | Accepted |

## Related Documents

- [FIPS Mesh Setup Plan](../../PLAN-FIPS-MESH-SETUP.md) — full deployment plan with phased rollout
- [FIPS Mesh Deployment Plan](../FIPS-MESH-DEPLOYMENT-PLAN.md) — implementation plan with task graph
- [Roadmap](../../ROADMAP.md) — phase-based roadmap with timelines
- [Kanban Tasks](../FIPS-MESH-KANBAN-TASKS.md) — kanban-ready task breakdown
- [FIPS Ingress Gate](../FIPS-INGRESS-GATE.md) — reverse proxy for hosting services from home