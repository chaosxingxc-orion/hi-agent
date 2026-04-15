# hi-agent Optimization Response — Round 2

**From:** hi-agent Team  
**To:** Research Intelligence Application Team  
**Date:** 2026-04-15  
**Re:** Round 2 optimization requests — all 8 items delivered  
**Commit:** 2754333  
**References:**
- `docs/hi-agent-optimization-requests-2026-04-15-round2.md` (Round 2 requests)
- `docs/hi-agent-optimization-response-2026-04-15.md` (Round 1 response)

---

## Executive Summary

All 8 Round 2 requests (C-1, C-2, H-1, H-2, H-3, M-1, M-2, M-3) have been accepted and delivered in commit 2754333. The two critical items (gate blocking semantics and subrun goal forwarding) are fully operational and unblock the Writing Team pipeline. The memory chain (H-2, M-1, M-3) is now end-to-end connected, and the reflection engine (M-2) generates structured prompts rather than structural retries.

---

## Delivery Table

| ID | Request | API / Contract | Status |
|---|---|---|---|
| C-1 | Human Gate blocks stage execution | `register_gate()` → sets `_gate_pending`; `_execute_stage()` raises `GatePendingError` before any gate-pending stage; `resume("approved")` clears flag; `resume("backtrack")` sets `_run_terminated`. `GatePendingError` exported from `hi_agent`. | Delivered |
| C-2 | `dispatch_subrun` accepts task goal | `dispatch_subrun(agent, profile_id, strategy, restart_policy, goal="")` — `goal` forwarded as `DelegationRequest.goal`; empty `goal` falls back to `f"agent={agent}"`. | Delivered |
| H-1 | L3 semantic search | `LongTermMemoryGraph(embedding_fn=None)` — `search()` uses TF-IDF scoring by default (zero external deps); uses cosine similarity when `embedding_fn` provided (lazy-cached); falls back to keyword when index is empty. TF-IDF index rebuilt on `load()`. | Delivered |
| H-2 | LongTermMemoryGraph auto-loads on init | `LongTermMemoryGraph.__init__` calls `self.load()` automatically if `_storage_path` exists. New instances with existing `profile_id` have full prior knowledge immediately. | Delivered |
| H-3 | TierRouter research purpose defaults | `hi_agent/llm/tier_presets.py` — `apply_research_defaults(tier_router)` sets: `pi_agent/lean_proof/paper_writing/peer_review → strong` (no downgrade), `survey_synthesis/experiment_design/experiment_eval → medium`, `survey_fetch → light`. | Delivered |
| M-1 | RawMemoryStore `close()` | `RawMemoryStore.close()` flushes and closes file handle. `__enter__`/`__exit__` for context manager. `append()` raises `ValueError` after close. `RunExecutor._finalize_run()` calls `close()` automatically. | Delivered |
| M-2 | `reflect(N)` injects reflection prompt | `RestartDecision.reflection_prompt: str \| None` — populated with failure reason + stage name + self-critique instruction when `action="reflect"`. `RunExecutor` injects it into context before next stage attempt. | Delivered |
| M-3 | L0→L2→L3 consolidation chain | `hi_agent/memory/l0_summarizer.py` — `L0Summarizer.summarize_run(run_id, base_dir) -> DailySummary \| None`. Extracts stage completions, outcomes, reflections from L0 JSONL. Called automatically in `_finalize_run()`. L0→L2→L3 chain is now fully connected. | Delivered |

---

## Note on C-1 Gate Blocking Semantics

The gate blocking implementation uses a `GatePendingError` exception model, not a sleep/poll loop. The intended caller pattern is:

```python
# Inside a run stage callback:
run.register_gate(gate_id="approval-1", gate_type="final_approval")

# The caller catches GatePendingError from the run loop:
try:
    result = await run_executor.execute_async(contract)
except GatePendingError as e:
    # Run is suspended at stage boundary — safe to persist state
    decision = await human_review_interface.wait(e.gate_id)
    run_executor.resume(e.gate_id, decision=decision)
    # Resume re-enters execution from the same stage boundary
```

Key properties:
- `GatePendingError` is raised **before** the next stage begins, not during a stage. No partial stage execution occurs.
- `RunStateSnapshot.status` reflects `"gate_pending"` while suspended. This is observable via `/runs/{run_id}` and the `RunStateStore`.
- Gate state survives process restart (checkpoint persistence from Round 1 is preserved).
- `resume(decision="backtrack")` sets `_run_terminated`, causing the run to exit cleanly. The caller is responsible for re-dispatch.

There is no implicit timeout on gate-pending state. If the process is killed while gate-pending, the checkpoint allows clean resume on restart.

---

## Round 1 Deferred Items Status

| ID | Item | Status |
|---|---|---|
| P3-2 | `TierRouter.calibrate()` — quality-score-driven tier calibration | **Still deferred.** Awaiting quality scoring infrastructure. No change from Round 1 agreement. |

All other Round 1 items remain closed as accepted.

---

## Next Steps for the Research Application Team

1. **Upgrade dependency** to commit 2754333 and run `python -m pytest tests/ -v` to confirm green.

2. **C-1 integration**: Update the phase-transition handler to catch `GatePendingError` and route to your human review interface. The run is safely suspended — no race condition with the next phase.

3. **H-1 semantic search**: If embedding-based search is required (recommended for cross-project PI Agent memory), inject an embedding function at construction:
   ```python
   graph = LongTermMemoryGraph(profile_id="proj-001", embedding_fn=my_embed_fn)
   ```
   TF-IDF is active by default and requires no configuration change.

4. **H-3 tier routing**: Call `apply_research_defaults(tier_router)` once after `SystemBuilder` wires the `TierRouter`. No per-agent configuration required.

5. **M-3 memory chain**: The L0→L2→L3 chain is automatic — no API change required on your side. After each run completes, `DailySummary` entries will appear in `MidTermMemoryStore`. Periodic calls to `LongTermConsolidator.consolidate()` will promote them to L3 graph nodes.

6. **P3-2 (`calibrate()`)**: Remains deferred. Please raise this again in Round 3 once quality scoring infrastructure is available on your end.
