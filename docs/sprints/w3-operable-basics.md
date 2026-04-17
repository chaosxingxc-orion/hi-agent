# W3 Sprint — Operable Basics

**Sprint window**: 2026-04-17 (same day, sequential after W2)
**Goal**: Ops layer MVP — self-diagnostic CLI, structured health endpoint, and CI/CD release gate.

---

## Ticket Tracker

| Ticket | Description | Status | Commit | Merged |
|--------|-------------|--------|--------|--------|
| HI-W3-001 | `hi-agent doctor` CLI + `GET /doctor` | ✅ Merged | `1973730` | 2026-04-17 |
| HI-W3-002 | `GET /ops/release-gate` v1 with 6-gate CI/CD check | ✅ Merged | `958f8e6` | 2026-04-17 |

---

## Exit Criteria

| Check | Baseline (W2) | Target | Result |
|-------|---------------|--------|--------|
| pytest passed | 3131 | ≥ 3131 | 3161 ✅ |
| pytest failed | 0 | 0 | 0 ✅ |
| `hi-agent doctor` exit 0/1 | — | yes | yes ✅ |
| `GET /doctor` returns `{status, blocking, warnings, info, next_steps}` | — | yes | yes ✅ |
| `GET /ops/release-gate` returns 6-gate JSON | — | yes | yes ✅ |
| `pass=true` in dev (no failures) | — | yes | yes ✅ |
| `prod_e2e_recent` always skipped | — | yes | yes ✅ |

---

## New Modules Delivered

- `hi_agent/ops/__init__.py` — ops module
- `hi_agent/ops/doctor_report.py` — `DoctorIssue` + `DoctorReport` dataclasses
- `hi_agent/ops/diagnostics.py` — `build_doctor_report()` pure function (8 checks)
- `hi_agent/ops/release_gate.py` — `GateResult` + `ReleaseGateReport` + `build_release_gate_report()`
- `hi_agent/server/ops_routes.py` — `handle_doctor` + `handle_release_gate` HTTP handlers

### Doctor diagnostic checks (8 dimensions)
1. LLM credentials — prod hard-block on missing API key
2. Kernel reachable — prod HTTP probe, reports `HI_AGENT_KERNEL_URL` fix
3. Capability registry — must have at least one handler
4. MCP server health — warning if transport wired but server erroring
5. Skill loader — warning if `SKILL.md` path missing
6. Memory directories — warning if `.hi_agent` not writable
7. Profile parsing — info only
8. Evolve policy — info showing current `mode` value

### Release gate checks (6 gates)
| Gate | Normal status | Blocks pass? |
|------|--------------|-------------|
| readiness | pass | yes |
| doctor | pass | yes |
| config_validation | pass | yes |
| current_runtime_mode | info | no (always info) |
| known_prerequisites | pass | yes |
| prod_e2e_recent | skipped | no (W12: promote to required) |

---

## Deferred to W4+

- ARCHITECTURE.md Ops Layer section update (minor doc task)
- `prod_e2e_recent` gate promotion from skipped → required (W12 target)
- `hi-agent doctor --fix` auto-remediation commands
