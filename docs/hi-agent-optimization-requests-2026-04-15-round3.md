# hi-agent Optimization Requests — Round 3

**From:** Research Intelligence Application Team  
**To:** hi-agent Team  
**Date:** 2026-04-15  
**Re:** Code review of commit 2754333 — 4 defects found  
**References:**
- `docs/hi-agent-optimization-requests-2026-04-15-round2.md` (Round 2 requests)
- `docs/hi-agent-optimization-response-2026-04-15-round2.md` (Round 2 response)

---

## Round 2 Delivery Review

Code-level inspection of commit 2754333 confirms the following Round 2 items are fully correct and closed:

| ID | Item | Verdict |
|---|---|---|
| C-2 | `dispatch_subrun` goal parameter | Accepted — goal forwarded to `DelegationRequest.goal` correctly |
| H-1 | L3 TF-IDF search + embedding_fn | Accepted — TF-IDF index maintained in `_tf`/`_df`; `_rebuild_index()` called from `load()` |
| H-2 | `LongTermMemoryGraph` auto-load on init | Accepted — `if self._storage_path.exists(): self.load()` in `__init__` |
| H-3 | TierRouter research purpose defaults | Accepted — `tier_presets.py` correct; `allow_downgrade=False` on critical purposes |
| M-1 | `RawMemoryStore.close()` | Accepted — `close()` implemented; `_base_dir` stored; `_finalize_run()` calls close |
| C-1 | Human Gate blocks stage execution | Accepted with one usability defect — see D-1 below |

4 defects were found. They are documented below as Round 3 requests.

---

## Round 3 Defect Reports

---

### D-1 — `GatePendingError` Has No Structured `gate_id` Attribute

**Severity:** High — breaks the documented integration pattern  
**File:** `hi_agent/gate_protocol.py`

**What exists:**
```python
class GatePendingError(Exception):
    """Raised when stage execution is attempted while a human gate is pending.

    Call :meth:`~hi_agent.runner.RunExecutor.resume` with the blocking
    gate_id before continuing execution.
    """
```

The class body is empty — no fields, no constructor.

**What the response document shows:**
```python
try:
    result = await run_executor.execute_async(contract)
except GatePendingError as e:
    decision = await human_review_interface.wait(e.gate_id)   # ← AttributeError
    run_executor.resume(e.gate_id, decision=decision)
```

`e.gate_id` raises `AttributeError` at runtime. The gate_id is embedded in the exception message string (`"Gate 'approval-1' is pending — call resume() before continuing"`) but is not accessible as a structured attribute.

**Impact:** Every caller that catches `GatePendingError` must parse the message string to extract the gate_id. This is fragile and will break if the message format ever changes.

**What we need:**
```python
class GatePendingError(Exception):
    def __init__(self, gate_id: str, message: str = "") -> None:
        super().__init__(message or f"Gate {gate_id!r} is pending")
        self.gate_id = gate_id
```

`runner.py` must be updated to raise `GatePendingError(gate_id=self._gate_pending, ...)` instead of `GatePendingError("Gate ... is pending")`.

**Acceptance criteria:**
- `except GatePendingError as e: e.gate_id` returns the exact string passed to `register_gate(gate_id=...)`
- Existing message format preserved for backward compatibility
- Test: catch `GatePendingError`, assert `e.gate_id == "test-gate"` without string parsing

---

### D-2 — `reflect(N)` Still Does Not Inject Reflection Prompt Before Retry

**Severity:** High — reflect(N) is structurally identical to retry(N)  
**File:** `hi_agent/task_mgmt/restart_policy.py`

**What exists:**

`RestartPolicyEngine._decide()` returns `action="retry"` unconditionally when `attempt_seq < policy.max_attempts`, with `reflection_prompt=None`. The reflection prompt is only generated when `on_exhausted == "reflect"` AND the budget is already exhausted — at which point `next_attempt_seq=None` and no further attempt is made.

```python
if attempt_seq < policy.max_attempts:
    return RestartDecision(
        action="retry",               # always "retry" — no reflection
        next_attempt_seq=attempt_seq + 1,
        reflection_prompt=None,       # always None during budget
        ...
    )

# Budget exhausted:
if on_exhausted == "reflect":
    reflection_prompt = f"Previous attempt {attempt_seq} failed: ..."
return RestartDecision(
    action="reflect",                 # exhausted — no further retry
    next_attempt_seq=None,            # ← no next attempt
    reflection_prompt=reflection_prompt,
)
```

When `RunExecutor` handles `action="reflect"` (line 2183), it records a `ReflectionPrompt` event. But because `next_attempt_seq=None`, no new attempt is launched. The reflection prompt is written to the event log and discarded.

**What `reflect(N)` must mean:**

"On each failure, inject a self-critique prompt into the LLM context and retry. Do this up to N times. After N failed reflection attempts, escalate."

Concretely, for `reflect(3)`:
- Attempt 0 fails → inject reflection prompt, retry as attempt 1
- Attempt 1 fails → inject reflection prompt, retry as attempt 2
- Attempt 2 fails → inject reflection prompt, retry as attempt 3 (last)
- Attempt 3 fails → escalate (budget exhausted)

**What we need:**

When `policy.on_exhausted == "reflect"` (i.e., the policy is configured as `reflect(N)`), `_decide()` should return `action="reflect"` with `reflection_prompt` populated AND `next_attempt_seq = attempt_seq + 1` on every failure within budget:

```python
if attempt_seq < policy.max_attempts:
    if policy.on_exhausted == "reflect":
        return RestartDecision(
            action="reflect",
            next_attempt_seq=attempt_seq + 1,
            reflection_prompt=(
                f"Attempt {attempt_seq} failed: {failure_reason}. "
                f"Stage: {stage_id}. "
                f"Identify what went wrong and correct it in the next attempt."
            ),
            reason=f"attempt {attempt_seq}/{policy.max_attempts} failed; reflecting",
        )
    return RestartDecision(action="retry", next_attempt_seq=attempt_seq + 1, ...)
```

Additionally, `RunExecutor` must inject the `reflection_prompt` into the LLM context when `action="reflect"` AND `next_attempt_seq` is not None. The current code only records an event; the prompt must reach the next stage's system context.

Two further sub-issues:
- `"Stage: unknown"` in the reflection prompt — the stage_id must be passed from `RunExecutor` down to `_decide()` (it is available as `self.current_stage`)
- `_decide()` currently receives no `stage_id` argument — add it

**Acceptance criteria:**
- A run with `restart_policy="reflect(2)"` produces 2 stage attempts where the second attempt has the reflection prompt in its LLM context (verifiable via the event log or observability hook)
- Reflection prompt contains the actual stage name, not `"Stage: unknown"`
- After N reflection attempts, the engine escalates (not retries silently)
- A test compares `reflect(2)` vs `retry(2)` — the event logs differ: reflect produces `ReflectionPrompt` events before each retry

---

### D-3 — `mid_term_store` Not Injected Into `RunExecutor`: L0→L2 Chain Is Silent No-Op

**Severity:** Medium — L0→L2 step extracts DailySummary but immediately discards it  
**File:** `hi_agent/runner.py`

**What exists:**

`_finalize_run()` at line 1909:
```python
_mid_term = getattr(self, "mid_term_store", None)
if _summary is not None and _mid_term is not None:
    _mid_term.save(_summary)
```

`RunExecutor.__init__` signature (lines 108–170) has no `mid_term_store` parameter. `self.mid_term_store` is never set. Therefore `_mid_term` is always `None`, and `DailySummary` is extracted from L0 but immediately discarded. The L0→L2 step produces the correct data but throws it away every time.

**What we need:**

1. Add `mid_term_store` as an optional constructor parameter to `RunExecutor`:
```python
def __init__(
    self,
    ...
    mid_term_store: MidTermMemoryStore | None = None,
    ...
) -> None:
    ...
    self.mid_term_store = mid_term_store
```

2. `SystemBuilder` should wire a `MidTermMemoryStore` scoped to the `profile_id` into `RunExecutor` during `build_executor()`.

**Acceptance criteria:**
- After a run completes with `base_dir` set on `RawMemoryStore`, a `DailySummary` entry exists in the injected `MidTermMemoryStore`
- Test: build a `RunExecutor` with `mid_term_store=MidTermMemoryStore(...)`, run it, assert `len(mid_term_store.list_recent(days=1)) > 0`

---

### D-4 — L2→L3 Consolidation Never Triggered Automatically

**Severity:** Medium — PI Agent's L3 knowledge graph never grows between projects  
**File:** `hi_agent/runner.py` / `hi_agent/memory/long_term.py`

**What exists:**

`LongTermConsolidator.consolidate()` exists and works correctly. But it is never called automatically — it requires explicit invocation by the caller. No scheduled trigger, no post-run hook, and no event-based mechanism calls it.

**Impact on architecture:** The PI Agent's cross-project memory (Principle P1: intelligence continuously evolves) depends on L3 being populated after each project. With no automatic trigger, the L3 graph remains empty unless the research application explicitly calls `consolidate()` — which it cannot do without holding both a `MidTermMemoryStore` and a `LongTermConsolidator` reference, neither of which are currently exposed through the `RunExecutorFacade` public API.

**What we need:**

`_finalize_run()` should call `LongTermConsolidator.consolidate()` after the L0→L2 step, if a `LongTermConsolidator` is wired in:

```python
# After L0→L2 step in _finalize_run():
_consolidator = getattr(self, "long_term_consolidator", None)
if _consolidator is not None:
    try:
        _consolidator.consolidate(days=1)  # consolidate just today's summaries
    except Exception as _exc:
        logger.debug("L2->L3 consolidation failed: %s", _exc)
```

And add `long_term_consolidator` as an optional constructor parameter:
```python
def __init__(
    self,
    ...
    long_term_consolidator: LongTermConsolidator | None = None,
    ...
) -> None:
```

`SystemBuilder` should wire a `LongTermConsolidator` (using the profile-scoped `MidTermMemoryStore` and `LongTermMemoryGraph`) into `RunExecutor` during `build_executor()`.

**Acceptance criteria:**
- After a run completes with all memory components wired, `LongTermMemoryGraph.node_count() > 0` for the associated profile
- The consolidation failure is logged at DEBUG and does not crash the run
- Test: full chain — run with L0 events → `_finalize_run()` → `MidTermMemoryStore` has entries → `LongTermMemoryGraph` has nodes

---

## Summary Table

| ID | Title | Severity | Root Cause |
|---|---|---|---|
| D-1 | `GatePendingError` missing `gate_id` attribute | High | Empty exception class; message-only encoding |
| D-2 | `reflect(N)` prompt not injected before retry | High | Reflection only at budget exhaustion; no prompt on mid-budget failures |
| D-3 | `mid_term_store` not wired into `RunExecutor` | Medium | Constructor parameter missing; getattr returns None always |
| D-4 | L2→L3 consolidation never auto-triggered | Medium | No auto-invoke in `_finalize_run()`; no `long_term_consolidator` param |

---

## Recommended Delivery Sequence

```
Sprint 1: D-1 (GatePendingError.gate_id)
          → fixes integration-blocking AttributeError; minimal change

Sprint 2: D-2 (reflect(N) with prompt injection)
          → requires _decide() stage_id parameter + RunExecutor context injection

Sprint 3: D-3 + D-4 (mid_term_store + consolidator wiring)
          → completes L0→L2→L3 chain; both need SystemBuilder wiring
```

---

## Items Not Raised in Round 3

The following known limitations are accepted as-is:

- `RunExecutorFacade.run()` success check via `str(run_result) == "completed"` — workaround documented on our side
- `LongTermConsolidator._find_relations()` uses keyword overlap for edges — acceptable quality for current scope; will re-evaluate after embedding-based `search()` is validated
- P3-2 (`TierRouter.calibrate()`) — still deferred as agreed
