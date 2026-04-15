# hi-agent Platform Self-Audit Report

**Date:** 2026-04-15
**Scope:** Systematic defect analysis from user-journey perspective, pre-scaling readiness
**Trigger:** 7 rounds of downstream review (38 defects total) revealed repeating structural patterns

---

## Part 1: Seven-Round Defect Pattern Analysis

### 1.1 The Numbers

| Round | Defects | Critical/High | Theme |
|-------|---------|---------------|-------|
| R1-R2 | 10+8 | — | API surface alignment (facades, exports, config) |
| R3 | 4 | 0 | Behavioral correctness (reflect semantics, gate error, memory wiring) |
| R4 | 6 | 2 | Deeper wiring (gate swallowed, profile_id missing, store not wired) |
| R5 | 5 | 2 | Cross-cutting (async parity, store sharing, import fragility) |
| R6 | 8 | 3 | Capability combinations (attempt recording, backtrack, sub-run cleanup, gate resume) |
| R7 | 8 | 2 | End-to-end integration (path separator, lifecycle manager, cross-loop, default config) |

**Observation:** High/Critical defects did NOT decrease across rounds. Each round found defects of equal or greater depth. This is a systemic quality problem, not a convergence trend.

### 1.2 Five Structural Root Causes

**Root Cause A: Fix-Then-Miss Cascade**

Each fix was applied to ONE code path while the same pattern existed in parallel paths:

| Pattern | Path Fixed | Parallel Paths Left Broken |
|---------|-----------|---------------------------|
| GatePendingError propagation | execute() (F-1) | _handle_stage_failure (G-4), execute_graph() (still broken), _execute_remaining() (still broken), execute_async() (still broken) |
| Profile scoping | Executor stores (F-2) | retrieval_engine (G-5), memory_lifecycle_manager (I-7), knowledge_manager (still broken) |
| Reflection context injection | Sync path (F-5) | Async path (G-1), session_id path safety (I-6) |

**Root Cause B: Stub-to-Production Gap**

Features were designed and stubbed but never wired end-to-end:

| Feature | Stub Exists | Production Wiring Missing |
|---------|------------|--------------------------|
| execute_async() | Method exists, returns AsyncRunResult | Never calls _finalize_run(), no gate propagation, no session state |
| resume_from_checkpoint() | Method exists, restores session | Missing: _stage_attempt, profile_id, raw_memory, gate_pending |
| _run_terminated | Flag set in resume() | Was never read by any method (H-3) |
| record_attempt() | Method exists in RestartPolicyEngine | Was never called from runner (H-1) |

**Root Cause C: Instance Duplication**

Multiple call sites create fresh instances of the same service instead of sharing one:

| Store | Authoritative Instance | Duplicate Instances Created By |
|-------|----------------------|-------------------------------|
| ShortTermMemoryStore | build_executor()._short_term_store | build_retrieval_engine() (fixed G-5), build_memory_lifecycle_manager() fallback (fixed I-7 partially), build_knowledge_manager() (still broken) |
| LongTermMemoryGraph | build_executor()._long_term_graph | build_knowledge_manager() (still broken) |

**Root Cause D: Missing Async/Sync Parity Protocol**

No process ensures that when a feature is added to the sync path, it is also added to the async path:

| Feature | Sync Path | Async Path |
|---------|-----------|------------|
| GatePendingError guard | execute() line 2053 | execute_async() handler: MISSING |
| _finalize_run() call | execute() line 2032 | execute_async(): MISSING |
| Hook manager wrapping | execute() line 758 | execute_async(): MISSING |
| Reflection context inject | Both branches in _handle_stage_failure | Timing: sync saves AFTER reflect, async saves BEFORE (inconsistent but functional) |
| await_subrun | await_subrun() | await_subrun_async() added in I-1 |

**Root Cause E: No User-Journey Integration Test**

All tests are unit-level or per-defect. No test exercises a full user journey:

| Journey | Tested? |
|---------|---------|
| execute() → gate → continue_from_gate() → complete | No |
| execute() → reflect(N) → retry → complete | No |
| execute() → dispatch_subrun → await_subrun → complete | No |
| execute_graph() → gate → resume | No |
| resume_from_checkpoint() → complete | No |
| Two concurrent profile_id runs → memory isolation | No |

---

## Part 2: Full Defect Inventory (User-Journey Perspective)

### Journey 1: execute() Linear Pipeline ✅ PRODUCTION-READY

Fully exercised by 7 rounds of downstream review. All known defects fixed.

---

### Journey 2: execute_graph() Dynamic Graph Traversal

| ID | Description | Severity | Root Cause |
|----|-------------|----------|------------|
| J2-1 | `execute_graph()` has NO `except GatePendingError: raise` — gate during graph traversal propagates as unhandled exception | Critical | A: fix-then-miss |
| J2-2 | `continue_from_gate()` calls `_execute_remaining()` which uses linear `trace_order()`, not graph topology — resuming after gate in graph mode follows wrong path | High | B: stub gap |

---

### Journey 3: execute_async() Full Async Pipeline

| ID | Description | Severity | Root Cause |
|----|-------------|----------|------------|
| J3-1 | `execute_async()` handler silently converts `GatePendingError` to `status="failed"` — gate is lost | Critical | A: fix-then-miss |
| J3-2 | `execute_async()` never calls `_finalize_run()` — no resource cleanup, no L0→L3 chain, no sub-run cancellation, no observability | Critical | B: stub gap |
| J3-3 | `execute_async()` does not populate `session.stage_states` — resume after async run re-executes everything | High | B: stub gap |
| J3-4 | `execute_async()` bypasses `ExecutionHookManager.wrap_tool_call()` — governance hooks not applied in async path | High | D: async parity |

---

### Journey 4: Gate Flow (approve / backtrack)

| ID | Description | Severity | Root Cause |
|----|-------------|----------|------------|
| J4-1 | `_execute_remaining()` has no `except GatePendingError: raise` — second gate during resume crashes with unhandled exception | Critical | A: fix-then-miss |

---

### Journey 5: resume_from_checkpoint()

| ID | Description | Severity | Root Cause |
|----|-------------|----------|------------|
| J5-1 | `resume_from_checkpoint()` does not restore `_stage_attempt` counters — reflect(N) after resume has wrong attempt numbers, wrong retry budget | Critical | B: stub gap |
| J5-2 | `resume_from_checkpoint()` does not restore `raw_memory` with correct `run_id`/`base_dir` — L0 JSONL events from resumed execution lost | Critical | B: stub gap |
| J5-3 | `resume_from_checkpoint()` does not restore `profile_id` — memory stores may be unscoped after resume | High | B: stub gap |
| J5-4 | `resume_from_checkpoint()` does not restore `_gate_pending` state — pending gate may be silently lost or incorrectly double-raised | High | B: stub gap |

---

### Journey 6: Sub-Run Dispatch + Await

| ID | Description | Severity | Root Cause |
|----|-------------|----------|------------|
| J6-1 | `dispatch_subrun()` futures created via `loop.create_task()` have NO error callback — silent failure, discovered only at `await_subrun()` time | Medium | D: async parity (reflection tasks have callback, subrun tasks don't) |

---

### Journey 7: Memory Chain (L0 -> L3) for Profile Runs

| ID | Description | Severity | Root Cause |
|----|-------------|----------|------------|
| J7-1 | `build_knowledge_manager()` calls `build_long_term_graph()` without `profile_id` — creates unscoped graph copy separate from executor's graph | High | C: instance dup |
| J7-2 | `build_memory_lifecycle_manager()` fallback paths create unscoped stores (no `profile_id` param in signature) — any standalone caller gets cross-project contamination | Medium | C: instance dup |

---

### Journey 8: Reflection Task Lifecycle

| ID | Description | Severity | Root Cause |
|----|-------------|----------|------------|
| J8-1 | Background reflection tasks (`loop.create_task()`) are NOT tracked or cancelled at `_finalize_run()` — orphaned tasks may write to memory stores after run ends | High | Same as H-2 pattern but for reflection tasks |

---

### Journey 9: RunExecutorFacade

| ID | Description | Severity | Root Cause |
|----|-------------|----------|------------|
| J9-1 | `RunExecutorFacade.run()` exposes no gate handling — caller must catch `GatePendingError` manually and has no access to `continue_from_gate()` | Medium | API gap |
| J9-2 | `RunExecutorFacade.stop()` does not call `_finalize_run()` — resources not cleaned up on forced stop | Medium | Resource lifecycle |

---

## Part 3: Prioritized Repair Plan

### Phase 1: Exception Propagation Completeness (5 defects, Critical)

All `except Exception` blocks on execution paths must have `except GatePendingError: raise` guards.

| Defect | File | Change |
|--------|------|--------|
| J2-1 | runner.py `execute_graph()` | Wrap main while loop in `try/except GatePendingError: raise` before any `except Exception` |
| J4-1 | runner.py `_execute_remaining()` | Wrap for loop in `try/except GatePendingError: raise` |
| J3-1 | runner.py `execute_async()` handler | Add gate detection in `make_handler()`: if `run_in_executor` raises GatePendingError, re-raise |
| — | runner.py general audit | Grep all `except Exception` on execution paths; add gate guard where missing |

**Verification:** Write a single parameterized test that exercises gate propagation through execute(), execute_graph(), _execute_remaining(), and execute_async().

---

### Phase 2: execute_async() Production Wiring (3 defects, Critical/High)

| Defect | File | Change |
|--------|------|--------|
| J3-2 | runner.py `execute_async()` | Call `_finalize_run()` in success and error paths; adapt RunResult/AsyncRunResult |
| J3-3 | runner.py `execute_async()` | Populate `session.stage_states` from handler results after scheduler completes |
| J3-4 | runner.py `execute_async()` handler | Wire hook manager `wrap_tool_call()` in async handler |

**Verification:** Integration test: execute_async() on a 3-stage graph with one failing stage and reflect(N); verify L0 JSONL written, session checkpoint updated, hook fired.

---

### Phase 3: resume_from_checkpoint() Production Wiring (4 defects, Critical/High)

| Defect | File | Change |
|--------|------|--------|
| J5-1 | runner.py `resume_from_checkpoint()` | Save/restore `_stage_attempt` dict in checkpoint schema |
| J5-2 | runner.py `resume_from_checkpoint()` | Reconstruct `RawMemoryStore(run_id=session.run_id, base_dir=...)` with correct params |
| J5-3 | runner.py `resume_from_checkpoint()` | Save/restore `profile_id` from contract; pass to store builders |
| J5-4 | runner.py `resume_from_checkpoint()` | Save/restore `_gate_pending` state; raise GatePendingError on resume if gate still pending |

**Verification:** Integration test: execute 2/5 stages → checkpoint → kill → resume → verify stages 1-2 not re-executed, stage_attempt counters correct, L0 file appended (not new), profile_id scoped.

---

### Phase 4: Store Wiring Completeness (2 defects, High/Medium)

| Defect | File | Change |
|--------|------|--------|
| J7-1 | builder.py `build_knowledge_manager()` | Add `profile_id` param; pass scoped `long_term_graph` or accept pre-built instance; update call in `_build_executor_impl()` |
| J7-2 | builder.py `build_memory_lifecycle_manager()` | Add `profile_id` param for fallback paths (defense-in-depth even though `_build_executor_impl` passes stores) |

**Verification:** Unit test: build executor with profile_id="test"; assert knowledge_manager.graph IS the same instance as executor's long_term_graph.

---

### Phase 5: Resource Lifecycle Completeness (3 defects, High/Medium)

| Defect | File | Change |
|--------|------|--------|
| J8-1 | runner.py | Track reflection tasks in `_pending_reflection_tasks`; cancel in `_finalize_run()` like sub-run futures |
| J6-1 | runner.py `dispatch_subrun()` | Add `_subrun_task_done_callback` (same pattern as `_reflect_task_done_callback`) |
| J9-2 | executor_facade.py `stop()` | Call `_finalize_run("cancelled")` or equivalent cleanup before nulling executor |

---

### Phase 6: Graph Resume + Facade API (2 defects, High/Medium)

| Defect | File | Change |
|--------|------|--------|
| J2-2 | runner.py | Add `continue_from_gate_graph()` that stores/resumes graph traversal state (current_stage, completed_stages) instead of using linear trace_order |
| J9-1 | executor_facade.py | Add `continue_from_gate()` delegation method; expose gate_id from last GatePendingError |

---

### Phase 7: Journey-Level Integration Tests (Process fix)

| Test | Capabilities Exercised |
|------|----------------------|
| `test_journey_execute_gate_approve` | execute() → GatePendingError → continue_from_gate("approved") → complete |
| `test_journey_execute_gate_backtrack` | execute() → GatePendingError → continue_from_gate("backtrack") → failed (no LLM waste) |
| `test_journey_execute_reflect_retry` | execute() → stage fail → reflect(N) → reflection prompt in STM → retry → complete |
| `test_journey_execute_graph_gate` | execute_graph() → GatePendingError → resume → correct graph path |
| `test_journey_subrun_dispatch_await` | execute() → dispatch_subrun() → await_subrun() → parent continues |
| `test_journey_checkpoint_resume` | execute() 2/5 stages → checkpoint → resume → stages 3-5 only |
| `test_journey_profile_isolation` | Two concurrent runs with different profile_ids → no memory cross-contamination |
| `test_journey_async_full` | execute_async() → 3 stages → finalization → L0 written → session updated |

---

## Summary

| Phase | Defects | Max Severity | Effort |
|-------|---------|--------------|--------|
| 1. Exception propagation | 4 | Critical | Small — mechanical: add guards |
| 2. execute_async() wiring | 3 | Critical | Medium — finalization + session state |
| 3. resume_from_checkpoint() wiring | 4 | Critical | Medium — checkpoint schema + reconstruction |
| 4. Store wiring | 2 | High | Small — signature + call-site update |
| 5. Resource lifecycle | 3 | High | Small — tracking + cleanup |
| 6. Graph resume + facade | 2 | High | Medium — graph state management |
| 7. Integration tests | 8 tests | — | Medium — test infrastructure |

**Total: 18 production defects remaining (8 Critical, 7 High, 3 Medium) + 8 journey-level integration tests to add.**

Phases 1-3 are blocking for any production deployment. Phases 4-5 are blocking for multi-profile deployments. Phase 6-7 are needed for full platform maturity.
