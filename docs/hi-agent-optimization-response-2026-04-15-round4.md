# hi-agent Optimization Response — Round 4

**From:** hi-agent Team  
**To:** Research Intelligence Application Team  
**Date:** 2026-04-15  
**Re:** Round 4 defect resolution  
**References:**
- `docs/hi-agent-optimization-requests-2026-04-15-round4.md` (Round 4 requests)
- `docs/hi-agent-optimization-response-2026-04-15-round3.md` (Round 3 response)

---

## Executive Summary

All 6 Round 4 defects (F-1 through F-6) are resolved. The Human Gate propagation mechanism is restored, multi-project memory isolation is enforced across all three memory tiers, the full L0→L2→L3 consolidation chain now persists to disk, and reflect(N) fires correctly on both sync and async execution paths.

---

## Delivery Table

| ID | Title | Severity | Status | Key Change |
|---|---|---|---|---|
| F-1 | `GatePendingError` swallowed by `execute()` | Critical | Closed | Inside `except Exception as exc:` handler of `execute()`, added `isinstance(exc, GatePendingError): raise` as first action — gate exceptions escape before run finalization |
| F-2 | Memory store paths missing `profile_id` | Critical | Closed | `build_short_term_store`, `build_mid_term_store`, `build_long_term_graph` each accept `profile_id: str = ""`; `build_executor` extracts `contract.profile_id` and forwards to all three; non-empty profile_id scopes L1/L2 under `profiles/{id}/` subdirectory |
| F-3 | `consolidate()` never calls `graph.save()` | High | Closed | Added `if count > 0: self._graph.save()` after `_merge_duplicates()` in `LongTermConsolidator.consolidate()` |
| F-4 | `RawMemoryStore()` missing `base_dir` | High | Closed | `build_executor` now generates `_run_id = uuid.uuid4().hex` and passes `RawMemoryStore(run_id=_run_id, base_dir=self._config.episodic_storage_dir)` |
| F-5 | `reflect_and_infer()` skipped async + no context injection | Medium | Closed | When `loop.is_running()`, replaced silent skip with `loop.create_task(reflect_and_infer(...))` so reflection fires as a background task; sync path now saves `decision.reflection_prompt` to `short_term_store` as `ShortTermMemory` record for retry LLM visibility |
| F-6 | `reflect_and_infer(attempts=[])` hardcoded | Medium | Closed | Added `_get_attempt_history(stage_id)` helper that delegates to `self._restart_policy._get_attempts(policy_task_id)`; both reflect call sites now pass this instead of `[]` |

---

## Files Modified

| File | Changes |
|------|---------|
| `hi_agent/runner.py` | F-1 gate re-raise guard; F-5 async `create_task` + sync context injection; F-6 `_get_attempt_history` helper + `attempts` argument wired |
| `hi_agent/config/builder.py` | F-2 `profile_id` param on three builder methods + forwarding in `build_executor`; F-4 `_run_id` + `_raw_base` wired into `RawMemoryStore` |
| `hi_agent/memory/long_term.py` | F-3 `self._graph.save()` after consolidation loop |

---

## Tests Added

12 new unit tests across 3 files (2936 → 2948 total):

| File | Tests | Covers |
|------|-------|--------|
| `tests/unit/test_round4_defects_runner.py` | 5 | F-1 gate propagation (×2), F-6 attempt history (×2), F-5 async create_task |
| `tests/unit/test_round4_defects_builder.py` | 4 | F-4 base_dir wired (×2), F-2 profile scoping (×2) |
| `tests/unit/test_round4_defects_long_term.py` | 3 | F-3 save on consolidation, no save when empty, return count |

Full suite: **2948 passed, 5 skipped, 0 failed**.

---

## Deferred Items (unchanged)

| ID | Title | Status |
|---|---|---|
| P3-2 | `TierRouter.calibrate()` | Deferred — awaiting quality scoring infrastructure |
