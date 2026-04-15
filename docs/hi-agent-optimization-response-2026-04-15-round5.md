# hi-agent Optimization Response — Round 5

**From:** hi-agent Team  
**To:** Research Intelligence Application Team  
**Date:** 2026-04-15  
**Re:** Round 5 defect resolution  
**References:**
- `docs/hi-agent-optimization-requests-2026-04-15-round5.md` (Round 5 requests)
- `docs/hi-agent-optimization-response-2026-04-15-round4.md` (Round 4 response)

---

## Executive Summary

All 5 Round 5 defects (G-1 through G-5) are resolved. The async reflect path now injects the reflection prompt synchronously before the retry LLM call and surfaces background task errors via a done-callback. Stage-scoped attempt history filtering is in place. `GatePendingError` is imported at module level and propagates cleanly from both `execute()` and `_handle_stage_failure()` via dedicated `except` clauses. The retrieval engine now shares the same pre-built store instances as the executor, completing the F-2 profile isolation.

---

## Delivery Table

| ID | Title | Severity | Status | Key Change |
|---|---|---|---|---|
| G-1 | Async reflect path does not inject reflection prompt | Medium | Closed | Added synchronous `short_term_store.save()` in the async branch **before** `create_task()`; added module-level `_reflect_task_done_callback` that logs ERROR on exception and WARNING on cancellation; `task.add_done_callback(_reflect_task_done_callback)` attached to every background task |
| G-2 | `_get_attempt_history` uses `contract.task_id` for all stages | Low | Closed | Added hasattr-guarded stage_id filter: `[a for a in all_attempts if getattr(a, "stage_id", None) == stage_id]`; fallback to full list when no record carries `stage_id` (backwards compat) |
| G-3 | `execute()` gate re-raise uses lazy import — fragile | Low | Closed | `GatePendingError` imported at module level (line 72); `execute()` uses dedicated `except GatePendingError: raise` before `except Exception`; lazy import in `_execute_stage()` removed |
| G-4 | `_handle_stage_failure` outer `except Exception` swallows `GatePendingError` | Critical | Closed | Added `except GatePendingError: raise` between try body and `except Exception as exc` in `_handle_stage_failure()` — gate raised during retry or reflect-retry now propagates to caller |
| G-5 | `build_retrieval_engine()` creates unscoped stores | Critical | Closed | `build_retrieval_engine()` now accepts `short_term_store`, `mid_term_store`, `long_term_graph`, `profile_id` params; `build_executor()` hoists `_short_term_store` to a local variable and passes all three pre-built stores to `build_retrieval_engine()` — executor and retrieval engine share identical store instances |

---

## Files Modified

| File | Changes |
|------|---------|
| `hi_agent/runner.py` | G-1: sync inject + done-callback; G-2: hasattr-guarded stage filter in `_get_attempt_history`; G-3: module-level import + dedicated `except GatePendingError: raise` in `execute()`; G-4: `except GatePendingError: raise` in `_handle_stage_failure()` |
| `hi_agent/config/builder.py` | G-5: `build_retrieval_engine()` signature update + store-passing in `build_executor()` |

---

## Tests Added

9 new unit tests across 2 files (2948 → 2957 total):

| File | Tests | Covers |
|------|-------|--------|
| `tests/unit/test_round5_defects_runner.py` | 6 | G-3 module-level import (×1), G-4 gate propagation in `_handle_stage_failure` (×2), G-2 stage-scoped filter (×2), G-1 async sync inject + callback (×1) |
| `tests/unit/test_round5_defects_builder.py` | 3 | G-5 store sharing (×3) |

Full suite: **2957 passed, 5 skipped, 0 failed**.

---

## Cross-Defect Interaction Notes

**G-1 + G-5 dependency:** G-1 fixes the async branch injection; G-5 ensures the injected record is visible to the retrieval engine. Both must be in place for `reflect(N)` to reach the retry LLM when `profile_id` is non-empty. Both are closed.

**G-3 + G-4 dependency:** G-3 moves `GatePendingError` to module scope, which G-4 leverages. With G-3 applied, G-4 requires no additional import. Both are closed.

**F-2 (Round 4) completion status:** F-2 is now fully closed. Round 4 scoped the executor's own stores; G-5 closes the gap by sharing those stores with the retrieval engine. Cross-project contamination is eliminated on all retrieval paths.

---

## Deferred Items (unchanged)

| ID | Title | Status |
|---|---|---|
| P3-2 | `TierRouter.calibrate()` | Deferred — awaiting quality scoring infrastructure |
