# hi-agent Optimization Response — Round 6

**From:** hi-agent Team  
**To:** Research Intelligence Application Team  
**Date:** 2026-04-15  
**Re:** Round 6 defect resolution  
**References:**
- `docs/hi-agent-optimization-requests-2026-04-15-round6.md` (Round 6 requests)
- `docs/hi-agent-optimization-response-2026-04-15-round5.md` (Round 5 response)

---

## Executive Summary

All 8 Round 6 defects (H-1 through H-8) are resolved. The full PI Agent pattern (multi-stage + reflect(N) + human gates + sub-runs) is now end-to-end correct: `record_attempt` is called so reflect history is real; `_run_terminated` is enforced so backtrack aborts the run; `continue_from_gate()` resumes from the incomplete stage without re-executing completed ones; orphaned sub-runs are cancelled at finalization; L0 JSONL is flushed before `L0Summarizer` reads it; child sub-run gates propagate to the parent as `gate_pending`; reflection prompts survive the `list_recent()` window via pinned lookup; and reflection content has a dedicated context partition.

---

## Delivery Table

| ID | Title | Severity | Status | Key Change |
|---|---|---|---|---|
| H-1 | Stage-scoped attempt history non-functional | Medium | Closed | `TaskAttempt.stage_id: str = ""` added to contracts; `_record_attempt()` called in `_handle_stage_failure()` after attempt counter update; `_get_attempt_history()` wrong fallback removed — returns `[]` (not other stages' records) when current stage has no history |
| H-2 | `_finalize_run()` doesn't cancel pending sub-runs | Low | Closed | `_cancel_pending_subruns(status)` method added; called as first line of `_finalize_run()`; cancels unfinished futures, clears both `_pending_subrun_futures` and `_completed_subrun_results` |
| H-3 | `_run_terminated` dead code — backtrack ignored | High | Closed | `_execute_stage()` checks `_run_terminated` as first guard before gate-pending check; returns `"failed"` immediately with INFO log — every subsequent stage fails, `_finalize_run("failed")` called |
| H-4 | `RawMemoryStore` file not closed before L0Summarizer | High | Closed | `raw_memory.close()` called in `_finalize_run()` after `_cancel_pending_subruns()` and before `_lifecycle.finalize_run()` — all L0 events flushed to disk before `L0Summarizer.summarize_run()` reads the JSONL |
| H-5 | Gate resume re-executes completed stages | High | Closed | `continue_from_gate(gate_id, decision, rationale="")` public method added — calls `resume()` then `_execute_remaining()`; `_execute_remaining()` falls back to `stage_summaries` when `session` is `None`; calling `execute()` directly after `resume()` is no longer the expected pattern |
| H-6 | `GatePendingError` from child sub-runs not propagated | Medium | Closed | `DelegationResult` gains `status="gate_pending"` + `gate_id: str \| None`; `DelegationManager.delegate()` detects `GatePendingError` from `asyncio.gather` results before the generic `BaseException` handler; `SubRunResult` gains `gate_id` and `status` fields; `await_subrun()` surfaces `gate_pending` status with structured `gate_id` |
| H-7 | Reflection prompt outside `list_recent()` window | Medium | Closed | `_handle_stage_failure()` loads prior reflection via `short_term_store.load(prior_session_id)` (deterministic by exact key) and injects via `context_manager.set_reflection_context()` — bypasses `list_recent(limit=20)` entirely |
| H-8 | Reflection prompt truncated by context budget | Low | Closed | `ContextManager.set_reflection_context()` added with dedicated 500-token partition; `memory_context` default reduced 2,000 → 1,500 to maintain total budget; reflection content rendered before general memory content in LLM context assembly |

**H-7 Change B (eviction protection):** `_evict_oldest()` skip for `outcome="reflecting"` deferred — not strictly needed given H-7 Change A's pinned lookup guarantees delivery regardless of eviction state.

---

## Files Modified

| File | Changes |
|------|---------|
| `hi_agent/runner.py` | H-1 `_record_attempt` call + `_get_attempt_history` fix; H-2 `_cancel_pending_subruns()` + `_finalize_run()` prologue; H-3 `_run_terminated` guard in `_execute_stage()`; H-4 `raw_memory.close()` in `_finalize_run()`; H-5 `continue_from_gate()` + `_execute_remaining()` fallback; H-6 `SubRunResult.gate_id/status` + `await_subrun()` gate_pending handling; H-7 pinned reflection inject |
| `hi_agent/task_mgmt/delegation.py` | H-6 `DelegationResult.gate_id/status` fields + `DelegationManager.delegate()` gate detection |
| `hi_agent/context/manager.py` | H-8 `set_reflection_context()` + `reflection_context` budget partition |
| `external/agent-kernel/.../contracts.py` | H-1 `TaskAttempt.stage_id: str = ""` (submodule commit `988e9a6`) |

---

## Tests Added

22 new unit tests across 3 files (2957 → 2979 total):

| File | Tests | Covers |
|------|-------|--------|
| `tests/unit/test_round6_defects_runner.py` | 18 | H-1 record_attempt (×2), H-2 cancel_subruns (×1), H-3 run_terminated guard (×1), H-4 raw_memory close (×1), H-5 continue_from_gate (×1), H-6 await_subrun gate_pending (×1), H-7 pinned reflection inject (×1) + additional variants |
| `tests/unit/test_round6_defects_delegation.py` | 2 | H-6 gate_pending status (×1), generic failure unchanged (×1) |
| `tests/unit/test_round6_defects_context.py` | 2 | H-8 untruncated combined inject (×1), reflection budget truncation (×1) |

Full suite: **2979 passed, 5 skipped, 0 failed**.

---

## Capability Status After Round 6

| Capability | Status |
|---|---|
| Human Gate — first attempt propagation | ✅ |
| Human Gate — retry/reflect-retry propagation | ✅ |
| Human Gate — backtrack decision | ✅ H-3 closed |
| Human Gate — resume without re-executing completed stages | ✅ H-5 closed (`continue_from_gate()`) |
| Multi-project memory isolation | ✅ |
| L0 episodic JSONL persistence (crash-safe flush) | ✅ H-4 closed |
| L0→L2→L3 consolidation | ✅ |
| reflect(N) firing | ✅ |
| reflect(N) attempt history | ✅ H-1 closed |
| reflect(N) context injection (any window size) | ✅ H-7 closed |
| reflect(N) context injection (large knowledge base) | ✅ H-8 closed |
| Sub-run lifecycle cleanup | ✅ H-2 closed |
| Child sub-run gate propagation to parent | ✅ H-6 closed |

---

## Deferred Items (unchanged)

| ID | Title | Status |
|---|---|---|
| P3-2 | `TierRouter.calibrate()` | Deferred — awaiting quality scoring infrastructure |
| H-7 Change B | `_evict_oldest()` eviction protection for reflecting records | Deferred — Change A's pinned lookup makes this non-critical |
