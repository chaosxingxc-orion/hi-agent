# agent-kernel Caller-Perspective Audit — 2026-04-15

Audit of agent-kernel commit `ff4d25c7e90cd2e2e0e62acb4cf929b0b77eca08`
from hi-agent's caller perspective (call chain:
hi-agent → KernelFacadeAdapter / KernelFacadeClient → KernelFacade → substrate gateway).

---

## Commits Pulled This Session

| Commit | Title | Impact on hi-agent |
|--------|-------|-------------------|
| `2f5b73a` | fix: close architectural gaps (dedupe store, consistency) | **None** — internal refactor, public API unchanged |
| `43fda27` | docs: sync ARCHITECTURE/README with 2f5b73a | **None** — documentation only |
| `ae2acc7` | fix(temporal): raise RuntimeError when event_stream_query_method_name is unset | **P1 fix resolved** — changes behavior at `stream_run_events`; hi-agent adapters already wrap this correctly (see §Impact) |
| `ff4d25c` | docs: sync ARCHITECTURE/README with ae2acc7 | **None** — documentation only |

---

## Impact of `ae2acc7` on hi-agent

**What changed:** `TemporalSDKWorkflowGateway._stream_run_events()` previously yielded a silent empty
iterator when `TemporalGatewayConfig.event_stream_query_method_name` was `None` (the default).
It now raises `RuntimeError` with an actionable message, eliminating the P1 silent-data-loss gap
reported in the prior audit.

**Call-site impact analysis:**

| Call site | File | Behavior with new RuntimeError | Action |
|-----------|------|-------------------------------|--------|
| `KernelFacadeAdapter.stream_run_events` | `runtime_adapter/kernel_facade_adapter.py:285-301` | `except Exception as exc` on line 298 catches it, wraps as `RuntimeAdapterBackendError` | **None** — already protected |
| `AsyncKernelFacadeAdapter.stream_run_events` | `runtime_adapter/async_kernel_facade_adapter.py:100-105` | delegates to `_sync.stream_run_events`; error propagates cleanly to KernelFacadeAdapter | **None** |
| `AsyncKernelFacadeAdapter.subscribe_events` fallback | `runtime_adapter/async_kernel_facade_adapter.py:259` | calls the above; error converts to `RuntimeAdapterBackendError` | **None** |
| `ResilientKernelAdapter.stream_run_events` | `runtime_adapter/resilient_kernel_adapter.py:265-267` | `_call()` retry logic re-raises after `max_retries`; not a write path, no buffering | **None** |
| `KernelFacadeClient.stream_run_events` (direct mode) | `runtime_adapter/kernel_facade_client.py:212` | previously unguarded — `RuntimeError` escaped uncaught | **Fixed in this session** — wrapped in try/except, converts to `RuntimeAdapterBackendError` |
| `sse_routes.py` event endpoint | `server/sse_routes.py:15-43` | uses hi-agent's internal `event_bus`, NOT the adapter streaming path | **Not affected** |

**Verdict:** Safe drop-in. The one unguarded path in `KernelFacadeClient` direct mode has been fixed.

---

## Remaining Findings After Full Audit

The following areas were audited for fake/incomplete implementations in agent-kernel production code
(`agent_kernel/` excluding `minimal_runtime.py` and test files).

### No Incomplete Implementations Found

| Area | Verdict |
|------|---------|
| `KernelFacade` — all 22 methods | Complete; no stubs, no `raise NotImplementedError` |
| `TemporalSDKWorkflowGateway.execute_turn` | Complete; routes `tool_call` → `execute_tool`, `mcp_call` → `execute_mcp`; raises `RuntimeError` for missing `activity_gateway` |
| `TemporalSDKWorkflowGateway.stream_run_events` | **Fixed in `ae2acc7`** — now raises `RuntimeError` when unconfigured instead of silent empty stream |
| `LocalWorkflowGateway` | Complete; event streaming backed by real SQLite event log |
| `_SharedConnectionDedupeStore` | Complete; `mark_succeeded()` and `count_by_run()` added in `2f5b73a` |
| `ConsistencyService` | Complete; `_detect_violations()` refactored in `2f5b73a`, public API unchanged |
| Recovery gate, dispatch admission, capability snapshot | No gaps |
| `kernel/cognitive/llm_gateway.py` | Out of scope — not in hi-agent → KernelFacade call path; no interface gap visible to hi-agent |

### Intentional Design Choices (Not Bugs)

**`cancel_run()` race swallow** (`kernel_facade.py:638-642`):  
When a workflow has already completed, `cancel_workflow()` raises with messages like
`"not found"` or `"already completed"`. `_is_expected_cancel_race_error()` silently absorbs
these. This is idempotent cancel semantics — appropriate for distributed systems.
Hi-agent callers cannot distinguish "cancelled successfully" from "was already done",
but both outcomes are terminal and safe.

**`query_projection()` dict coercion** (`temporal/gateway.py:212-251`):  
When Temporal returns a raw dict, missing fields default to `"created"` / `0` / `False`.
This is defensive deserialization of the Temporal SDK's polymorphic return type —
the defaults are the safest values for each field. Not a data-loss risk in practice
because the dict shape is determined by the `RunActorWorkflow.run` query handler,
which is under agent-kernel's own control.

### Documented Limitations (No Action Required)

From agent-kernel `CLAUDE.md`:
- `minimal_runtime.py` in-memory implementations — PoC/test only, never production
- Peer signal auth checks `active_child_runs` only (production uses `peer_run_bindings`)
- `DispatchAdmissionService.check()` soft-deprecated — use `admit(action, snapshot)`
- Heartbeat watchdog requires caller to invoke `monitor.watchdog_once()` periodically

---

## Changes Made to hi-agent This Session

| File | Change |
|------|--------|
| `pyproject.toml` | Updated agent-kernel pin from `43fda27` → `ff4d25c` |
| `hi_agent/runtime_adapter/kernel_facade_client.py:212-219` | Wrapped direct-mode `async for` in try/except to convert `RuntimeError` to `RuntimeAdapterBackendError` |

---

*Written by hi-agent engineering — 2026-04-15*
