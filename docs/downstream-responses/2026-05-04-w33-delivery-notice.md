# Wave 33 Delivery Notice

**Date:** 2026-05-04
**Wave:** 33
Status: SHIP
Manifest: 2026-05-03-fce71cc0
Functional HEAD: 11959967ceb6ed5ed8df473ccfacc0ab8c33ef52

> **Cross-wave context:** Wave 33 closes the 2 RIA-flagged soft drifts in the W32 acceptance §5 + RIA's §7 preemptive coverage ask + 13 hidden BLOCKER/HIGH findings from the W32 systematic audit (5 BLOCKERs + 2 HIGHs in defense-in-depth + 1 Rule 11 unification + 1 Rule 12 spine lineage). RIA fully accepted W32; W33 is non-corrective, primarily focused on closing items we know are real but RIA didn't see in their acceptance audit.

---

## Verified Readiness

| Tier | Score | Cap factors |
|---|---|---|
| `raw_implementation_maturity` | 94.5 | — |
| `current_verified_readiness` | **75.0** | identical to W32; RIA acceptance §3 cap holds |
| `seven_by_24_operational_readiness` | 90.0 | architectural_seven_by_twenty_four (5/5 PASS) |
| `conditional_readiness_after_blockers` | 75.0 | identical to verified |

**Honest read:** The 75.0 cap is unchanged from W32 per RIA acceptance §3. W33 deepens architectural coverage but does not unlock a new tier. Cap factors remaining are `soak_evidence_not_real` (waived per RIA acceptance §2 architectural-feasibility 7×24 criterion) and `evidence_provenance` (3 historical W27 artifacts; W28 erratum).

---

## Wave 33 Closure Evidence

| Track | Status | Evidence path | Provenance |
|---|---|---|---|
| W33-A.1 recurrence-ledger 31→32 (RIA §5 drift #1) | PASS | `docs/governance/recurrence-ledger.yaml:9` + `scripts/check_wave_consistency.py --json` exit 0 | measured |
| W33-A.2 platform-capability-matrix headlines (RIA §5 drift #2) | PASS | `docs/platform-capability-matrix.md` lines 3, 355 + `check_doc_truth.py` exit 0 | measured |
| W33-B.1 signal-route preemptive coverage (RIA §7 hook (d)) | PASS | `tests/integration/test_v1_runs_signal_resume_real_kernel.py` (2 tests; dispatches to real RunManager) | measured |
| W33-C.1 agent_server lifespan W32-C reforms | PASS | `agent_server/runtime/lifespan.py` rewrite + `tests/integration/test_agent_server_w32c_lifespan_active.py` | measured |
| W33-C.2 SIGTERM graceful drain | PASS | `hi_agent/server/app.py:_sigterm_handler` + `tests/integration/test_sigterm_graceful_drain.py` (3 tests) | measured |
| W33-C.3 RunQueue.reenqueue clears adoption_token | PASS | `hi_agent/server/run_queue.py` + `tests/unit/test_run_queue.py::test_reenqueue_clears_adoption_token_for_second_recovery` | measured |
| W33-C.4 JWT auth middleware on v1 routes | PASS | `agent_server/api/middleware/auth.py` + `agent_server/runtime/auth_seam.py` + `tests/integration/test_v1_jwt_auth_middleware.py` (6 tests) | measured |
| W33-C.5 SSE iter_events live-stream | PASS | `agent_server/runtime/kernel_adapter.py` + `tests/integration/test_v1_runs_sse_live_stream.py` (2 tests) | measured |
| W33-D.1 Audit log tenant_id | PASS | `hi_agent/observability/audit.py` + `tests/unit/test_audit_tenant_id.py` (11 tests) | measured |
| W33-D.2 RunQueue defense-in-depth tenant scoping (9 methods) | PASS | `hi_agent/server/run_queue.py` + `tests/integration/test_run_queue_tenant_defense_in_depth.py` (28 tests) | measured |
| W33-E.1 Rule 11 HI_AGENT_ENV unification | PASS | `hi_agent/config/posture.py:resolve_runtime_mode()` + 19 callsites + `scripts/check_no_hi_agent_env_direct_read.py` + 20 tests | measured |
| W33-F.1 Rule 12 spine lineage fields | PASS | `hi_agent/server/event_store.py:StoredEvent` + `hi_agent/server/run_store.py:RunRecord` + `tests/unit/test_spine_lineage_fields.py` (10 tests) | measured |
| Real T3 (Volces) at HEAD | PASS | `docs/delivery/2026-05-04-65cdbbc0-t3-volces.json` provenance:real, 3/3 PASS | measured |
| arch-7x24 fresh evidence | PASS | `docs/verification/ac37383-arch-7x24.json` 5/5 PASS | measured |
| clean-env fresh evidence | PASS | `docs/verification/ac37383b-default-offline-clean-env.json` 9256 passed / 8 skipped / 0 failed | measured |

---

## Architectural-positioning rationale

Per our positioning ("northbound functional idempotency, performance stability, extensibility, evolvability, configurable development, sustainable evolution"), W33 closes:

- **Performance stability**: W33-C.1 (W32-C lifespan reforms now reach prod), W33-C.2 (graceful drain instead of 2s force-fail), W33-C.3 (runs survive arbitrary lease cycles).
- **Northbound functional idempotency / Extensibility**: W33-B.1 (signal route real-kernel coverage), W33-C.4 (JWT auth boundary).
- **Evolvability**: W33-C.5 (SSE live-stream contract honored — true streaming not snapshot-and-close).
- **Configurable development / Sustainable evolution**: W33-A.1, W33-A.2, W33-E.1 (HI_AGENT_ENV unification), W33-F.1 (spine lineage).

Defense-in-depth: W33-D.1 (audit log tenant attribution), W33-D.2 (RunQueue tenant scoping on 9 methods).

Deferred per RIA's W32 acceptance §7 (RIA explicitly says "at our discretion"):
- H-3' experiment shim deletion
- H-13' task triplet umbrella
- H-14' templates dir consolidation

---

## Three-Part Defect Closure (Rule 15)

### W33-C.4 JWT auth middleware (closed: `verified_at_release_head`)

- **Code fix**: commits `cca41924` (W33-C). New `agent_server/runtime/auth_seam.py` (R-AS-1 seam re-uses hi_agent JWT primitives) + `agent_server/api/middleware/auth.py:JWTAuthMiddleware` registered outermost in `agent_server/api/__init__.py`.
- **Regression test or hard gate**: `tests/integration/test_v1_jwt_auth_middleware.py` (6 tests covering missing/valid/invalid-sig/expired/dev-passthrough/exempt-path).
- **Delivery-process change**: agent_server middleware chain now `[JWTAuthMiddleware → TenantContextMiddleware → IdempotencyMiddleware]`. The `test_middleware_pipeline_no_extraneous_layers` regression test pins the chain.

### W33-C.1 lifespan W32-C reforms (closed: `operationally_observable`)

- **Code fix**: commit `cca41924`. Module-level `_lease_expiry_loop` and `_current_stage_watchdog` helpers in `agent_server/runtime/lifespan.py` are kicked off as asyncio tasks during agent_server FastAPI lifespan startup; cancelled cleanly on shutdown.
- **Regression test**: `tests/integration/test_agent_server_w32c_lifespan_active.py` asserts both tasks are running on the production app.
- **Delivery-process change**: the W32-C reforms are now active on the production deployment shape (RIA's actual surface), not just the legacy `python -m hi_agent serve` path.

---

## Outstanding Items (carried into W34)

| Item | Owner | Tracker | Notes |
|---|---|---|---|
| H-3' experiment shim deletion | DX | RIA-discretion | Pure naming hygiene; RIA does not depend |
| H-13' task triplet umbrella | RO | RIA-discretion | Naming hygiene |
| H-14' templates dir consolidation | DX | RIA-discretion | Naming hygiene |
| F.2 RunExecutionContext spine fields | RO | W34 carryover | from_managed_run hardcodes parent_run_id, attempt_id, etc. as empty |
| F.3 ReasoningTrace __post_init__ | CO | W34 carryover | Spine validation missing |
| F.4 KnowledgeWiki tenant partition | RO | W34 carryover | Per-tenant key composition |
| 3 historical W27 evidence_provenance artifacts | TE | W28 erratum | Out of scope per directive §6 |

---

## Manifest Rewrite Budget (Rule 14)

W33 manifest count in root: 1 (`2026-05-03-fce71cc0`). Prior W33 manifest `ac37383b` archived to `docs/releases/archive/W33/` after gate-fix commits invalidated its freshness. Budget: 2/3 used.

---

## Acknowledgement to RIA team

RIA's W32 acceptance was clean and cleanly-rationale'd. The two soft drifts surfaced (recurrence-ledger lag, capability-matrix headlines) were exactly the level of scrutiny that surfaces real issues without manufactured ones. We closed them inline with the wider audit follow-through. Section 4.1 endorsement of the two-seam pattern (`agent_server/runtime/**` as second R-AS-1 seam) and Section 4.2 endorsement of the test-honesty disclosure pattern in `_RecordingExecutorFactory` will both inform our future facade work.
