# Boot-Time Assertions Roadmap

**Date:** 2026-05-05
**Wave:** W35 → W36+ scoping
**Source audit:** `docs/governance/systematic-audit-w35-2026-05-05.md` §A5
**Status:** W36 binding for HIGH severity; W37+ for the rest.

A boot-time assertion fails at process startup if a wired feature requires a resource that was not provided. The alternative — silent route registration without the backing resource — produces failure modes invisible to smoke tests (route returns 404 or 500 only when first traffic arrives, after deployment is "complete").

Reference implementation: W35-T8 — `agent_server/api/__init__.py::build_app` rejects `include_mcp_tools=True` or `include_skills_memory=True` when `idempotency_facade is None`.

---

## HIGH severity (W36 binding)

### B1. agent_server/runtime/lifespan.py — agent_server attribute existence

**Site:** `build_real_kernel_lifespan(backend)` line 232.

**Today:** silently calls `backend.agent_server.run_manager.list_runs()` etc. inside the lifespan tasks. If `run_manager` is missing, the watchdog crashes inside `record_silent_degradation` and the loop continues running with no-op output.

**W36 fix:** Before starting the lease-expiry / watchdog / purge tasks in `_lifespan`, assert:
```python
if not hasattr(agent_server, "run_manager") or agent_server.run_manager is None:
    raise RuntimeError("build_real_kernel_lifespan: run_manager required")
```

### B2. agent_server/runtime/kernel_adapter.py — executor_factory present at boot

**Site:** `RealKernelBackend.start_run` raises `ContractError(503)` per request when `executor_factory is None`. Rule 8 step 3 requires 3 sequential real-LLM runs to PASS — but this defect would 503 each one rather than fail at boot.

**W36 fix:** In `RealKernelBackend.__init__` under research/prod posture, assert `_agent_server.executor_factory is not None`. Under dev, log warning.

### B3. kernel_adapter event_store / artifact_registry

**Site:** kernel_adapter.py:341-343 returns `iter(())` silently when `event_store is None`. Rule 8 step 5 (current_stage observable) cannot fire because no events flow.

**W36 fix:** Boot-time assertion that `event_store is not None` under research/prod.

### B4. agent_kernel/service/http_server.py — api_key under prod posture

**Site:** `create_app(facade, *, api_key=None, ...)`. With `api_key=None`, `ApiKeyMiddleware` runs in open-no-auth mode.

**W36 fix:** Under `KernelConfig.posture == prod`, raise if `api_key is None`. Document expected env var (`AGENT_KERNEL_API_KEY`).

### B5. agent_kernel http_server — facade is not None

**Site:** `app.state.facade = facade` accepts any value. First request crashes with `AttributeError: NoneType`.

**W36 fix:** Boot-time `if facade is None: raise ValueError("facade required")` in `create_app`.

### B6–B10. hi_agent/server/app.py — routes-without-resource (5 sites)

Routes for memory_manager / retrieval_engine / slo_monitor / session_store / feedback_store are mounted unconditionally. The corresponding resource is optional; when absent, the route returns 500 NoneType or falls back to defaults.

**W36 fix:** Under research/prod posture, refuse to mount the route if its backing resource is None. Under dev posture, mount with fail-closed handler (returns 503 with structured error).

### B11. agent_kernel http_server — InMemory* under prod posture

**Site:** `create_app_default` constructs `InMemoryDedupeStore` etc. without posture check.

**W36 fix:** If `KernelConfig.from_env().posture in ("research", "prod")`, refuse and require explicit SQLite-backed store wiring.

### B12. ManifestFacade resolver validity at boot

**Site:** `bootstrap.py:316` constructs `ManifestFacade(posture_resolver=lambda: posture.value)`. No boot-time call validates the resolver returns a usable string.

**W36 fix:** At boot, call `manifest_facade.manifest()` once and assert it returns a contract-shaped dict; cache the result for the first request.

### B13. agent_server build_app silent route omission (events / artifacts / manifest)

**Site:** `build_app` accepts `event_facade=None, artifact_facade=None, manifest_facade=None` and silently omits the corresponding routes. Under production posture this is silent breakage (Rule 8 step 6 cancellation 404 etc.).

**W36 fix:** Under research/prod posture (or whenever bootstrap path is used), require all four facades to be non-None.

### B14. include_gates without idempotency_facade

**Site:** Default-on `include_gates=True` mounts gate routes; the IdempotencyMiddleware's `_is_gates_decide_mutation` only fires when middleware is registered. If `idempotency_facade is None` and `include_gates=True`, gate decisions become non-idempotent under research/prod.

**W35 disposition:** NOT closed in W35-T8 — would break ~50 route-level unit tests that pass `idempotency_facade=None`.
**W36 plan:** Posture-aware boot assertion: under research/prod, require `idempotency_facade is not None` when `include_gates=True`. Under dev, log warning. Migrate route-level tests to a shared fixture providing a stub IdempotencyFacade.

---

## MEDIUM severity (W37 binding)

### B15–B22

- B15: `agent_server/api/middleware/auth.py` — no boot-time check that `JWT_SECRET` env var is set under prod posture (currently per-request 401).
- B16: SIGTERM handler in lifespan.py:268 assumes `agent_server.run_manager.drain` and `.shutdown` exist — failures land at process-stop time.
- B17: `_rehydrate_runs` in app.py:1239 silently skips when `run_queue is None` — no boot rejection under research/prod.
- B18: `agent_kernel http_server.py /metrics` returns empty `[]` when `metrics_collector is None` — silent dashboard breakage.
- B19: `agent_server/runtime/auth_seam.py:138-145` returns `ok=False` per-request when `JWT_SECRET` unset under strict posture; should boot-fail.
- B20: routes_skills_memory.py falls back to `_strict_from_env()` reading `HI_AGENT_POSTURE` directly — Rule 6 violation (single construction path).
- B21: routes_runs_extended `cancel_run` route silently absent when `event_facade=None` — Rule 8 step 6 covers this; needs assertion.
- B22: `agent_server/api/__init__.py` event_facade silent omission for `/v1/runs/{id}/events`.

---

## Implementation pattern (W35-T8 reference)

For each assertion site:

1. **Identify the conditional flag** — `if include_mcp_tools and idempotency_facade is None:`
2. **Raise at the earliest point** — at the start of `build_app`, before FastAPI app construction.
3. **Error message names the fix** — `"set include_mcp_tools=False or supply idempotency_facade"`.
4. **Posture-aware** — under dev, downgrade to a warning log; under research/prod, raise.
5. **Test coverage** — `tests/integration/test_<feature>_boot_assertion.py`:
   - test_boot_rejects_<feature>_without_<resource>
   - test_boot_accepts_<feature>_with_<resource>
   - test_boot_accepts_<feature>_disabled

---

## Operational note — why this matters

The "boot fail-fast" pattern moves errors from runtime to deploy time. Under the 7×24 architectural lens (RIA W35 §2.7), a process that boots successfully but cannot serve its mounted routes is a structural feasibility defect: the process appears healthy to the orchestrator (PM2 / systemd / docker), but real traffic discovers the gap.

The systematic audit at W35 surfaced this class as a separate dimension because it is invisible to: smoke tests (no traffic), unit tests (no boot), pytest (test fixtures bypass boot). Only operator-shape gates (Rule 8) and integration-style boot tests catch it.

---

## Cross-reference

- W35-T8 reference: `agent_server/api/__init__.py::build_app` boot assertion + `tests/integration/test_mcp_tools_idempotency.py`
- Audit source: `docs/governance/systematic-audit-w35-2026-05-05.md` §A5
- Rule 8 (operator-shape gate): `CLAUDE.md` §"Rule 8"
