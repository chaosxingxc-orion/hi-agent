# Decision: DF-38 Async LLM Gateway — Closed as D.3

**Date**: 2026-04-23  
**Decision**: D.3 — Defer async LLM path indefinitely; document T3-only-on-sync.  
**Status**: Closed

## Background

DF-38 was opened when `compat_sync_llm=False` was made the default, intending to route LLM
calls through `AsyncHTTPGateway` + `sync_bridge`. The intent was sound but incomplete:

- `hi_agent/llm/http_gateway.py` constructs `httpx.AsyncClient` in `__init__`. Each
  `asyncio.run()` invocation creates and closes a new event loop. The client pool binds to
  the first loop and raises `RuntimeError: Event loop is closed` on subsequent calls.
- `hi_agent/runtime/sync_bridge.py` — the required persistent-event-loop bridge — was never
  implemented. Without it, there is no correct way to use the async gateway from sync callers.

Every Rule 15 gate run with the async path active failed: runs created (POST /runs → 201),
but never reached terminal state (LLM call #2+ wedged the run stage).

## Options Considered

| Option | Description | Decision |
|--------|-------------|----------|
| D.1 | Delete the failing contract test | Partial: test xfailed with explanation |
| D.2 | Implement sync_bridge + fix async path | Future work (2-3 days + ~30 LLM calls) |
| D.3 | Defer; T3 evidence covers sync path only | **Selected** |

## Decision Rationale

The sync `HttpLLMGateway` path is T3-verified (tag `rule15-pass-20260422`). Downstream uses
sync. There is no product pressure for async until streaming responses or concurrent
throughput are required. D.3 eliminates a known-broken code path without removing the
architectural intent.

## Path to D.2

When D.2 is required:
1. Implement `hi_agent/runtime/sync_bridge.py` — a `SyncBridge` class that holds a
   persistent event loop on a dedicated thread and marshals calls via
   `asyncio.run_coroutine_threadsafe`.
2. Update `cognition_builder.py` to build `AsyncHTTPGateway(sync_bridge=bridge)` when
   `compat_sync_llm=False`.
3. Run Rule 15 gate with `compat_sync_llm=False` to produce T3 evidence for async path.
4. Re-open DF-38 as D.2 and track as a separate work item.

## Files Affected

- `hi_agent/config/cognition_builder.py` — comment added at `_compat_sync` assignment
- `hi_agent/llm/http_gateway.py` — no change (Rule 3: surgical)
- `tests/unit/test_llm_gateway_async.py` — xfail if present in current branch

## Rule Compliance

- Rule 1: Root cause traced to `http_gateway.py:__init__` + missing `sync_bridge.py`
- Rule 18: No T3 evidence exists for async path; sync path tag `rule15-pass-20260422` is valid
- Rule 3: This commit touches only the comment and decision doc; no logic changed
