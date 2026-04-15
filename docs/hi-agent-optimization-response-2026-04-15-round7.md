# hi-agent Optimization Response — Round 7

**From:** hi-agent Team  
**To:** Research Intelligence Application Team  
**Date:** 2026-04-15  
**Re:** Round 7 defect resolution  
**References:**
- `docs/hi-agent-optimization-requests-2026-04-15-round7.md` (Round 7 requests)
- `docs/hi-agent-optimization-response-2026-04-15-round6.md` (Round 6 response)

---

## Executive Summary

All 8 Round 7 defects (I-1 through I-8) are resolved. The two highest-impact fixes: `ShortTermMemoryStore._memory_path()` now sanitizes session IDs so reflection saves/loads actually work (I-6 unblocks H-7 and the entire reflect-context injection chain), and `build_memory_lifecycle_manager()` now receives the profile-scoped store instances (I-7 closes the last L0→L3 contamination gap). The default restart policy is now `on_exhausted="reflect"` (I-8), making the reflect path active in all standard deployments. Cross-loop `await_subrun()` crashes are eliminated with a new `await_subrun_async()` API (I-1).

---

## Delivery Table

| ID | Title | Severity | Status | Key Change |
|---|---|---|---|---|
| I-6 | `ShortTermMemoryStore.save()` fails for reflection session IDs | High | Closed | `_memory_path()` sanitizes session_id: replaces `/` and `\` with `__` before constructing the file path — reflection IDs like `"{run_id}/reflect/{stage_id}/{attempt}"` are stored as flat `.json` files; `glob("*.json")` in eviction finds them correctly; H-7 pinned retrieval is now operative |
| I-7 | `build_memory_lifecycle_manager()` unscoped stores | High | Closed | `build_memory_lifecycle_manager(short_term_store, mid_term_store, long_term_graph)` now accepts pre-built instances; `build_executor()` passes its profile-scoped stores — MemoryLifecycleManager reads from the correct `profiles/{id}/` directory; L0→L2→L3 consolidation chain is correct for all profile runs |
| I-1 | `await_subrun()` cross-loop `ValueError` | Medium | Closed | `await_subrun()` detects running loop: if task is done → `future.result()`; if task is pending → raises clear `RuntimeError` directing caller to `await_subrun_async()`; new `await_subrun_async()` method uses `await future` on the current loop — no cross-loop issue |
| I-2 | `_handle_stage_failure()` wasted LLM calls after backtrack | Medium | Closed | `_run_terminated` guard added as first check in `_handle_stage_failure()` — returns `"failed"` immediately; no `_record_attempt()`, no `reflect_and_infer()` LLM call, no false history records |
| I-8 | Default restart policy prevents reflect path | Medium | Closed | `TraceConfig` gains `restart_max_attempts: int = 3` and `restart_on_exhausted: str = "reflect"`; `_build_restart_policy_engine()` reads both via `getattr(..., fallback)` — reflect path active by default; deployments requiring escalate behavior configure `restart_on_exhausted="escalate"` |
| I-3 | `_execute_remaining()` return annotation is `str` | Low | Closed | Annotation changed to `-> "RunResult"` — no logic change; type-check error in `continue_from_gate()` resolved |
| I-4 | `ContextBudget.from_config()` missing `reflection_context` | Low | Closed | `from_config()` forwards `getattr(cfg, "context_reflection_context_budget", 500)` — reflection partition size is now configurable; fallback maintains backward compatibility |
| I-5 | `_get_attempt_history()` dead backward-compat branch | Low | Closed | `hasattr(all_attempts[0], "stage_id")` branch removed; direct filter always applied; two earlier tests updated to match |

---

## Files Modified

| File | Changes |
|------|---------|
| `hi_agent/memory/short_term.py` | I-6: `_memory_path()` session_id sanitization |
| `hi_agent/config/builder.py` | I-7: `build_memory_lifecycle_manager()` signature + call-site; I-8: `_build_restart_policy_engine()` reads config fields |
| `hi_agent/config/trace_config.py` | I-8: `restart_max_attempts` and `restart_on_exhausted` fields added |
| `hi_agent/runner.py` | I-1: `await_subrun()` cross-loop guard + new `await_subrun_async()`; I-2: `_run_terminated` guard in `_handle_stage_failure()`; I-3: annotation fix; I-5: dead branch removed |
| `hi_agent/context/manager.py` | I-4: `from_config()` forwards `reflection_context` |

---

## Tests Added / Updated

16 new tests across 4 files + 2 existing tests updated (2979 → 2995 total):

| File | New Tests | Covers |
|------|-----------|--------|
| `tests/unit/test_round7_defects_short_term.py` | 3 | I-6: slash session save/load (×1), no subdirectory (×1), eviction finds reflection memories (×1) |
| `tests/unit/test_round7_defects_builder.py` | 4 | I-7: MLM uses profile stores (×1), shared store instances (×1); I-8: default reflect (×1), escalate config (×1) |
| `tests/unit/test_round7_defects_context.py` | 2 | I-4: config-forwarded budget (×1), fallback budget (×1) |
| `tests/unit/test_round7_defects_runner.py` | 7 | I-1: async collect (×1), clear error (×1), done future (×1); I-2: immediate return (×1), no LLM after backtrack (×1); I-3: annotation (×1); I-5: empty for unknown stage (×1) |

Updated: `test_round4_defects_runner.py`, `test_round5_defects_runner.py` — adjusted to match I-5 filter semantics.

Full suite: **2995 passed, 5 skipped, 0 failed**.

---

## Capability Status After Round 7

| Capability | Status |
|---|---|
| `reflect(N)` path triggerable (default config) | ✅ I-8 closed |
| `reflect(N)` context injection — save/load works | ✅ I-6 closed |
| `reflect(N)` context injection — pinned retrieval (H-7) | ✅ I-6 + H-7 combined |
| `reflect(N)` attempt history scoped by stage | ✅ |
| Gate → backtrack → clean termination (no wasted LLM) | ✅ I-2 closed |
| Gate → approve → `continue_from_gate()` | ✅ |
| `dispatch_subrun` + `await_subrun` (sync path) | ✅ |
| `dispatch_subrun` + `await_subrun_async` (async path) | ✅ I-1 closed |
| L0→L2→L3 consolidation for all profile runs | ✅ I-7 closed |
| Context reflection partition configurable | ✅ I-4 closed |
| Type-safe `continue_from_gate()` return | ✅ I-3 closed |

---

## Deferred Items (unchanged)

| ID | Title | Status |
|---|---|---|
| P3-2 | `TierRouter.calibrate()` | Deferred — awaiting quality scoring infrastructure |
| H-7 Change B | `_evict_oldest()` eviction protection for reflecting records | Superseded by I-6 — flat file storage means `glob("*.json")` finds all records; eviction is correct |
