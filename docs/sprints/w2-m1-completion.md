# W2 Sprint — M1 Runtime Truth (Complete)

**Sprint window**: 2026-04-17 (same day, parallel to W1)
**Goal**: Close all `"unknown"` fields in ExecutionProvenance; lock contract shape with snapshot tests.
**M1 status**: **ACHIEVED** — Runtime Truth MVP complete.

---

## Ticket Tracker

| Ticket | Description | Status | Commit | Merged |
|--------|-------------|--------|--------|--------|
| HI-W2-001 | Stage-level StageProvenance; llm_mode/capability_mode aggregation | ✅ Merged | `00dfe80` | 2026-04-17 |
| HI-W2-002 | Capability/Action-level provenance; capability_mode no longer unknown | ✅ Merged | `20f358c` | 2026-04-17 |
| HI-W2-003 | Kernel mode real aggregation via adapter.mode | ✅ Merged | `92eee51` | 2026-04-17 |
| HI-W2-004 | Snapshot golden tests for /manifest, /ready, RunResult | ✅ Merged | `f6dbd2c` | 2026-04-17 |

---

## Exit Criteria

| Check | Baseline (W1) | Target | Result |
|-------|---------------|--------|--------|
| pytest passed | 3107 | ≥ 3107 | 3131 ✅ |
| pytest failed | 0 | 0 | 0 ✅ |
| coverage | 81% | ≥ 81% | ✅ |
| `execution_provenance.llm_mode` | `"unknown"` | `"heuristic"` | `"heuristic"` ✅ |
| `execution_provenance.kernel_mode` | `"unknown"` | `"local-fsm"` | `"local-fsm"` ✅ |
| `execution_provenance.capability_mode` | `"unknown"` | `"sample"` | `"sample"` ✅ |
| Snapshot files locked | — | 3 snapshots | 3 ✅ |
| UPDATE_SNAPSHOTS=1 regenerates | — | yes | yes ✅ |

---

## New Modules Delivered

- `hi_agent/contracts/execution_provenance.py` — extended with `StageProvenance` dataclass
- `hi_agent/runtime_adapter/protocol.py` — `mode` property added to `RuntimeAdapter` protocol
- `hi_agent/runtime_adapter/kernel_facade_adapter.py` — `mode = "local-fsm"`
- `hi_agent/runtime_adapter/async_kernel_facade_adapter.py` — `mode` delegates to sync adapter
- `hi_agent/runtime_adapter/resilient_kernel_adapter.py` — `mode` via `getattr(inner, "mode", "local-fsm")`
- `hi_agent/capability/invoker.py` — `_provenance` dict attached to every invocation result
- `hi_agent/capability/defaults.py` — heuristic handler emits `_provenance.mode="sample"`
- `hi_agent/runner.py` — `_capability_provenance_store`; `_collect_stage_type_summaries` derives real modes
- `tests/snapshots/manifest_dev_smoke.json` — locked manifest shape
- `tests/snapshots/ready_dev_smoke.json` — locked ready shape
- `tests/snapshots/run_result_dev_fallback.json` — locked RunResult provenance shape

---

## Deferred to W3+

- AsyncRunResult provenance propagation (W1 carry-over)
- local-real runtime_mode path (requires real kernel wiring)
- `/ready` endpoint direct `resolve_runtime_mode` wiring (W1 carry-over)
- `prod_e2e_recent` gate in release-gate (W12 target)

---

## M1 Declaration

**M1 Runtime Truth is achieved.**

All `ExecutionProvenance` fields are no longer `"unknown"` in a default dev-smoke run:

```json
{
  "contract_version": "2026-04-17",
  "runtime_mode": "dev-smoke",
  "llm_mode": "heuristic",
  "kernel_mode": "local-fsm",
  "capability_mode": "sample",
  "mcp_transport": "not_wired",
  "fallback_used": true,
  "fallback_reasons": ["heuristic_stages_present"],
  "evidence": {"heuristic_stage_count": N}
}
```

Contract shape is locked by snapshot tests. Any future field change must update snapshots explicitly.

**Next sprint**: W3 — Ops layer (hi-agent doctor CLI + /doctor endpoint + /ops/release-gate v1).
