# Wave 36 A5 — Boot-Time Assertions B1–B14

**Date:** 2026-05-06
**Wave:** W36 binding
**Reference:** RIA W36 directive §3.2; W35-T8 reference impl; `docs/governance/boot-time-assertions-roadmap.md`
**Owner:** DX (track lead) + AS-RO (agent_server side) + RO (agent_kernel side)

---

## 1. Architectural baseline (W35-T8 verified)

The reference assertion shape lives at `agent_server/api/__init__.py:138-156` (verified by direct read; matches roadmap description). Verbatim:

```python
_routes_requiring_idempotency = {
    "include_mcp_tools": include_mcp_tools,
    "include_skills_memory": include_skills_memory,
}
if idempotency_facade is None:
    enabled_dependent = [
        name for name, enabled in _routes_requiring_idempotency.items() if enabled
    ]
    if enabled_dependent:
        raise ValueError(
            f"build_app: {enabled_dependent} require idempotency_facade is not None "
            f"to ensure mutating-route replay semantics; supply idempotency_facade "
            f"in the bootstrap or set the include_* flags to False (W35-T8)."
        )
```

Five baseline properties extracted from this reference:

1. **Location:** at the construction-site function entry, before any side-effecting wiring. Not in middleware, not in lazy-init, not at first request.
2. **Error type:** `ValueError` (configuration error) for `build_app`-shape sites; `RuntimeError` for lifespan/runtime-construction sites where the resource is environmental rather than caller-supplied.
3. **Message shape:** `<site>: <missing-resource> required for <stated-invariant>; <fix-direction> (W36-B<N>)`. Naming both the invariant and the fix is mandatory.
4. **Posture awareness:** W35-T8 raises unconditionally because the dependent flags default to `False`. For B1–B14 the equivalent property is achieved by gating with `Posture.is_strict` (research/prod raise, dev WARNING + degraded path).
5. **Test trio per assertion:**
   - `test_boot_rejects_<feature>_without_<resource>_in_research`
   - `test_boot_accepts_<feature>_with_<resource>_in_research`
   - `test_boot_warns_<feature>_without_<resource>_in_dev`

The single shared helper introduced this wave:

```python
# hi_agent/config/posture.py (extension)
def assert_research_posture_required(
    *, name: str, value: object, posture: Posture, fix_hint: str, defect_id: str
) -> None:
    if value is not None:
        return
    msg = f"{name} required under {posture.value} posture; {fix_hint} ({defect_id})"
    if posture.is_strict:
        raise RuntimeError(msg)
    LOG.warning(msg)
```

All B1–B14 sites call this helper; the helper is the single construction path (Rule 6) for boot-time assertion semantics.

---

## 2. Per-assertion plan (B1–B14)

### B1. agent_server.run_manager attribute existence

- **Site:** `agent_server/runtime/lifespan.py::build_real_kernel_lifespan`, lifespan body before lease-expiry / watchdog / purge task scheduling.
- **Today:** Lifespan tasks call `backend.agent_server.run_manager.list_runs()`; absent attribute crashes inside `record_silent_degradation` and the loop continues with no-op output.
- **Posture matrix:** research/prod → `RuntimeError("build_real_kernel_lifespan: run_manager required for lease-expiry/watchdog tasks; bootstrap must construct RealKernelBackend with run_manager wired (W36-B1).")`; dev → WARNING + skip lifespan tasks (no-op lifespan yield).
- **Tests:** `tests/integration/test_lifespan_boot_assertions.py::test_lifespan_b1_*` (3 tests).
- **Three-part closure:** code-fix = lifespan.py edit; gate-evidence = the new test file; process-change = roadmap entry retired and `check_route_presence.py`-class assertion ledger updated.

### B2. RealKernelBackend executor_factory at boot

- **Site:** `agent_server/runtime/kernel_adapter.py::RealKernelBackend.__init__`.
- **Today:** Each `start_run` raises `ContractError(503)` when `executor_factory is None`; Rule 8 step 3 runs would all 503 but boot would succeed.
- **Posture matrix:** research/prod → `RuntimeError` at `__init__`; dev → WARNING + accept (legacy stub-test path).
- **Tests:** `tests/integration/test_kernel_adapter_boot_assertions.py::test_b2_*` (3).
- **Three-part closure:** code-fix per `__init__`; regression test per trio; process-change updates `Risk 2` mitigation in the registry.

### B3. kernel_adapter event_store / artifact_registry

- **Site:** `agent_server/runtime/kernel_adapter.py:341-343` (silent `iter(())` when `event_store is None`).
- **Today:** Rule 8 step 5 (`current_stage` observable) cannot fire because no events flow.
- **Posture matrix:** research/prod → `RuntimeError`; dev → WARNING + return empty iterator.
- **Tests:** `tests/integration/test_kernel_adapter_boot_assertions.py::test_b3_*` (3).
- **Three-part closure:** standard.

### B4. agent_kernel http_server api_key under prod

- **Site:** `agent_kernel/service/http_server.py::create_app(facade, *, api_key=None, ...)`.
- **Today:** `api_key=None` makes `ApiKeyMiddleware` open-no-auth.
- **Posture matrix:** prod → `RuntimeError("create_app: api_key required under prod posture; set AGENT_KERNEL_API_KEY env var (W36-B4).")`; research → WARNING (research path is internal); dev → silent.
- **Tests:** `tests/integration/test_kernel_http_boot_assertions.py::test_b4_*` (3).
- **Three-part closure:** standard. Note env-var name is documented in the error message itself.

### B5. agent_kernel http_server facade non-None

- **Site:** `agent_kernel/service/http_server.py::create_app` `app.state.facade = facade`.
- **Today:** Accepts any value; first request `AttributeError: NoneType`.
- **Posture matrix:** all postures → `ValueError("create_app: facade required (W36-B5).")` (this one is not posture-conditional — None is always wrong; aligns with W35-T8 semantic).
- **Tests:** `tests/integration/test_kernel_http_boot_assertions.py::test_b5_*` (2 tests; no posture matrix because the assertion is unconditional).
- **Three-part closure:** standard.

### B6–B10. hi_agent/server/app.py routes-without-resource (5 sites)

Five resources mounted unconditionally despite optional construction: `memory_manager`, `retrieval_engine`, `slo_monitor`, `session_store`, `feedback_store`. Sites are `hi_agent/server/app.py` lifespan-bound construction; today routes 500 with `NoneType` AttributeError when resource absent.

- **Posture matrix (all five):** research/prod → refuse to mount the route group; emit structured error via `assert_research_posture_required`; dev → mount with fail-closed handler returning 503 + structured error per Rule 7 (countable + attributable).
- **Tests:** `tests/integration/test_app_boot_assertions.py::test_b6_*` ... `::test_b10_*` (5 × 3 = 15 tests).
- **Three-part closure (each):** code-fix at construction-site; gate per route-group; process-change adds the route name to the lifespan supervisor inventory.
- **Key implementation note:** rather than 5 separate raise-call sites, register all five through the `assert_research_posture_required` helper in a single lifespan registration block so the call sites match by shape.

### B11. agent_kernel http_server InMemory* under prod

- **Site:** `agent_kernel/service/http_server.py::create_app_default` (constructs `InMemoryDedupeStore` and friends with no posture check).
- **Today:** Persistence claims silently regress to in-memory under prod.
- **Posture matrix:** prod → `RuntimeError` requiring explicit SQLite-backed wiring; research → WARNING (research can run in-memory by exception); dev → silent.
- **Tests:** `tests/integration/test_kernel_http_boot_assertions.py::test_b11_*` (3).
- **Three-part closure:** standard. Process-change: `KernelConfig` schema gains a posture-required-store policy.

### B12. ManifestFacade resolver validity at boot

- **Site:** `bootstrap.py:316` constructs `ManifestFacade(posture_resolver=lambda: posture.value)`.
- **Today:** Resolver never invoked at boot; first `/v1/manifest` request discovers a broken resolver.
- **Fix:** at boot, call `manifest_facade.manifest()` once; assert returned dict has the contract-shaped keys; cache for first-request reuse.
- **Posture matrix:** research/prod → raise on failure; dev → WARNING.
- **Tests:** `tests/integration/test_manifest_facade_boot.py::test_b12_*` (3).
- **Three-part closure:** standard. The boot probe doubles as a smoke test of manifest contract.

### B13. agent_server build_app silent route omission — CROSS-TEAM with RIA G-RIA-13

- **Site:** `agent_server/api/__init__.py::build_app` lines 197-208 — `event_facade`, `artifact_facade`, `manifest_facade` silently omit their routers when `None`.
- **Today:** Under research/prod this silently breaks `/v1/runs/{id}/events`, `/v1/runs/{id}/cancel`, `/v1/runs/{id}/artifacts`, `/v1/manifest` — Rule 8 step 6 cancellation 404 lands at first traffic.
- **Posture matrix:** research/prod → `ValueError("build_app: event_facade / artifact_facade / manifest_facade required under research/prod posture; bootstrap must wire all three (W36-B13).")`; dev → WARNING + silent omit (legacy route-test path).
- **Tests:** `tests/integration/test_build_app_boot_assertions.py::test_b13_*` (3 + a multi-omission combo test).
- **Three-part closure:** code-fix at `build_app`; regression test; process-change documents the cross-team coordination with RIA G-RIA-13.
- **Cross-team note:** structurally identical to RIA's R-RIA-9 outbound seam concern. RIA introduces `scripts/check_route_presence.py` (G-RIA-13) on the **consumer** side asserting the consumer fixture probes a documented route inventory before yielding. Hi-agent's B13 asserts the **platform** side `build_app` rejects the silent-omission shape under research/prod. Both implementations land in the same wave (W36) and closure documentation cross-references both at the corresponding wave-closure manifests.

### B14. include_gates without idempotency_facade

- **Site:** `agent_server/api/__init__.py::build_app` — `include_gates=True` (default) mounts gate routes; `IdempotencyMiddleware._is_gates_decide_mutation` only fires when middleware is registered; gate decisions become non-idempotent under research/prod when `idempotency_facade is None`.
- **W35 disposition:** NOT closed in W35-T8 (would have broken ~50 route-level unit tests passing `idempotency_facade=None`).
- **W36 sequencing (highest blast radius — see §4):**
  1. Build shared `tests/conftest.py::stub_idempotency_facade` fixture (in-memory; no posture-strict semantics).
  2. Bulk-edit existing route-level tests under `tests/route/` and `tests/integration/test_routes_*.py` to use the fixture under default-offline profile.
  3. Land the boot assertion AFTER test migration so default-offline stays green.
- **Posture matrix:** research/prod → `ValueError` matching W35-T8 message shape; dev → WARNING + accept (gates work but without dedup).
- **Tests:** `tests/integration/test_build_app_boot_assertions.py::test_b14_*` (3).
- **Three-part closure:** code-fix at `build_app`; gate-evidence test trio; process-change is the conftest fixture itself which prevents future tests from re-entering the un-asserted shape.

---

## 3. Cross-cutting concerns

### 3.1 Migration risk (B14)

50+ route-level unit tests currently pass `idempotency_facade=None`. The roadmap and RIA directive both call this out. Migration path is sequenced (see §4): land the fixture and test migration before the assertion, in the same PR.

### 3.2 Test fixture extraction

A `tests/conftest.py` module-level fixture for "minimal valid `build_app` config under research" — every B1–B14 test reuses it. Reduces boilerplate from ~12 lines per test to a single fixture parameter. Fixture composes: `RunFacade` stub, `EventFacade` stub, `ArtifactFacade` stub, `ManifestFacade` stub, `IdempotencyFacade` stub, posture-research env. Each test toggles exactly one facade to `None` to drive the corresponding rejection.

### 3.3 B13 cross-coordination with RIA G-RIA-13

- Both implementations land in W36.
- RIA G-RIA-13: consumer-side `scripts/check_route_presence.py` asserts the consumer fixture probes a documented route inventory before yielding (covers the "platform serves but consumer assumes wrong path" failure mode).
- Hi-agent B13: platform-side `build_app` raises when the bootstrap omits a facade under research/prod (covers the "platform silently omits but consumer assumes presence" failure mode).
- Closure documentation in both `docs/delivery/<W36-date>-<sha>-rule15-*.md` files cross-references the other team's manifest_id.
- A single shared route inventory anchor lives at `docs/platform/agent-server-northbound-contract-v1.md`; both gates derive expected routes from it.

### 3.4 Lifespan supervisor pattern

B1, B6–B10, and B11 all touch lifespan-bound resources. Centralize via `assert_research_posture_required(name, value, posture, fix_hint, defect_id)` invoked at the start of each lifespan registration (rather than duplicating raise/log shapes per callback). Single helper means single source of truth for the message shape and the posture downgrade rule.

### 3.5 Cross-platform constraint

No new POSIX-only signal handling this wave. The existing SIGTERM use in `agent_server/runtime/lifespan.py:268` is preserved unchanged (B16 covers SIGTERM robustness in W37). Windows test runners pass with the same fixture and assertion shapes — `assert_research_posture_required` uses no platform-specific calls.

---

## 4. Implementation sequencing (14 days)

- **Day 1:** Extract `assert_research_posture_required` helper in `hi_agent/config/posture.py`; build `tests/conftest.py::build_app_research_fixture` and `stub_idempotency_facade`; migrate ~10 sample existing route-level tests to the fixture (proves migration scales).
- **Day 2–3:** B14 (highest blast radius). Migrate remaining ~40 route-level tests to the conftest fixture; land the B14 assertion last in the PR.
- **Day 4–5:** B1 (lifespan), B6–B10 (hi_agent app.py — five sites in one PR through the lifespan supervisor pattern).
- **Day 6–7:** B2, B3 (kernel_adapter — both `__init__` time).
- **Day 8–9:** B4, B5, B11 (agent_kernel http_server — single PR, three sites).
- **Day 10:** B12 (manifest facade boot probe).
- **Day 11–12:** B13 with RIA cross-team verification: align route inventory, exchange manifest_ids, both teams land within 24h.
- **Day 13–14:** Drill — refuses-to-boot when key facade is None under research; warns under dev. Recorded in `docs/delivery/<W36-date>-<sha>-rule15-volces.json` per Rule 8 T3 evidence.

---

## 5. Acceptance criteria (W36 closure, per RIA §3.2)

- All 14 HIGH-severity boot-time gaps closed with posture-aware assertions.
- B13 closure documentation cross-references RIA G-RIA-13 (and vice versa).
- Three-part closure (Rule 15) per assertion with `level: verified_at_release_head`.
- Regression test trio per assertion (or pair where unconditional).
- Conftest fixture for deliberately-incomplete `build_app` lives in `tests/conftest.py` and is consumed by every B-test file.
- `default-offline` profile stays green throughout (Rule 16).
- Manifest scorecard reflects: 14 boot-time defects closed + 0 new allowlist entries + 0 process-internal exemptions.

---

## 6. Risk registry

- **Risk 1 — B14 test migration scale (50+ tests):** mitigation = shared conftest fixture; phased migration in single PR; sample migration on Day 1 proves scale before commitment.
- **Risk 2 — agent_kernel lifespan touches a different process from agent_server:** mitigation = separate test fixture per backend (`build_app_research_fixture` for agent_server; `kernel_app_research_fixture` for agent_kernel) with shared assertion helper.
- **Risk 3 — dev posture WARNING noise:** mitigation = log at WARNING level (not ERROR); rate-limit per assertion-class via the shared helper.
- **Risk 4 — cross-platform signal handling (B16 SIGTERM):** out of scope this wave (W37 binding).
- **Risk 5 — bootstrap.py interplay with B12 boot probe:** mitigation = boot probe is read-only; cache result for first-request use; failure logged with full context.

---

## 7. What's NOT in this plan (W37 binding)

B15–B22 (MEDIUM severity) — JWT_SECRET prod enforcement (B15), SIGTERM handler robustness (B16), `_rehydrate_runs` scope (B17), `/metrics` empty fallback (B18), auth_seam JWT (B19), `routes_skills_memory._strict_from_env` (B20, also a Rule 6 violation), `cancel_run` event_facade (B21), `/v1/runs/{id}/events` event_facade (B22). These remain MEDIUM-severity per the roadmap and are scheduled for W37.

---

## 8. References

- W35-T8 reference impl: `agent_server/api/__init__.py:138-156` (verified by direct read 2026-05-06)
- Roadmap: `docs/governance/boot-time-assertions-roadmap.md`
- Audit source: `docs/governance/systematic-audit-w35-2026-05-05.md` §A5
- RIA directive: `D:\chao_workspace\research\docs\hi-agent-wave36-engineering-expectations-2026-05-05.md` §3.2
- Cross-team: RIA G-RIA-13 `scripts/check_route_presence.py` (consumer-side counterpart to B13)
- CLAUDE.md rules invoked: Rule 6 (single construction path), Rule 8 (operator-shape gate), Rule 11 (posture-aware defaults), Rule 15 (closure taxonomy), Rule 16 (test profiles)
