# W1 Sprint — Runtime Truth MVP

**Sprint window**: 2026-04-17 ~ 2026-04-18  
**Goal**: Make the runtime tell the truth about what it actually does.  
**M1 milestone dependency**: W1 is a prerequisite for M1 (M1 requires W2+).

---

## Ticket Tracker

| Ticket | Description | Status | Merged |
|--------|-------------|--------|--------|
| HI-W0-001 | Freeze runtime baseline (pytest count, coverage %, ruff count) | ✅ Merged | 2026-04-18 |
| HI-W1-D1-001 | Freeze runtime baseline 2026-04-17 | ✅ Merged | 2026-04-18 |
| HI-W1-D2-001 | Introduce evolve_mode tri-state policy (auto/on/off) with audit and deprecation compat | ✅ Merged | 2026-04-18 |
| HI-W1-D3-001 | Add RunResult.execution_provenance structured dataclass | ✅ Merged | 2026-04-18 |
| HI-W1-D3-002 | Baseline diff verification after D3-001 | ✅ Merged | 2026-04-18 |
| HI-W1-D4-001 | Manifest runtime_mode from resolver; evolve_policy + provenance contract | ✅ Merged | 2026-04-18 |
| HI-W1-D5-001 | Operation-driven RBAC/SOC wiring for mutation routes | ✅ Merged | 2026-04-18 |

---

## Exit Criteria

| Check | Baseline | Target | Result |
|-------|----------|--------|--------|
| pytest passed | 3059 | ≥ 3100 | 3107 ✅ |
| pytest failed | 0 | 0 | 0 ✅ |
| coverage | 80.89% | ≥ 80.89% | 81% ✅ |
| ruff errors | 3178 | ≤ 3178 + new-file allowance | 3224 (46 from new sprint files) ⚠️ |
| new modules present | — | 6 files | 6 ✅ |
| /manifest runtime_mode | — | "dev-smoke" | "dev-smoke" ✅ |
| /manifest evolve_policy | — | present | present ✅ |
| /manifest provenance_contract_version | — | "2026-04-17" | "2026-04-17" ✅ |
| RBAC dev bypass | — | not 403 in dev | 200 ✅ |

---

## New Modules Delivered

- `hi_agent/config/evolve_policy.py` — tri-state evolve_mode resolver
- `hi_agent/observability/audit.py` — audit event emitter
- `hi_agent/contracts/execution_provenance.py` — ExecutionProvenance dataclass (CONTRACT_VERSION="2026-04-17")
- `hi_agent/server/runtime_mode_resolver.py` — runtime_mode resolution logic
- `hi_agent/auth/operation_policy.py` — RBAC/SOC policy table + @require_operation decorator
- `hi_agent/auth/authorization_context.py` — AuthorizationContext from HTTP request headers

---

## Deferred to W2

- `llm_mode`, `kernel_mode`, `capability_mode` fields in ExecutionProvenance
- AsyncRunResult provenance propagation
- local-real runtime_mode path (requires real kernel wiring)
- /ready endpoint direct resolve_runtime_mode wiring
