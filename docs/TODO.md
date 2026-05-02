# hi-agent Engineering TODO

Last updated: 2026-05-01 (Wave 27 — in progress; W25 + W26 closed)

## DONE (Wave 1-4, SA-1..SA-8, 2026-04-22/24)

- SA-1..SA-8 self-audit: profile_id scoping, async stage graph, store registry
- DF-33..DF-40: Rule 8 gate teeth, structural + volces gate evidence
- W1-4: LLM path attribution, env isolation, run-scoped fallback events, gate teeth
- K-1/K-2/K-3/K-6/K-9/K-10/K-15: CLOSED-incidental (triage confirmed)
- Rule 7: tier_router run_id attribution (WS-1)
- Rule 8 gate: llm_fallback_count assertion (WS-1)
- K-4/K-5/K-7/K-8: executor_facade + context + dream_scheduler fixes (WS-2/3)
- K-11/K-12/K-13/K-14: test honesty + Language Rule (WS-4)
- Platform positioning docs, Rule 10 response (WS-5)
- [x] Round-8 downstream response written (`docs/hi-agent-optimization-response-2026-04-15-round8.md`) — 2026-04-24

## DONE (Wave H1, DF-46, 2026-04-25)

- [x] DF-46 CI gate enforcement: scripts/check_t3_freshness.py + .github/workflows/claude-rules.yml step — 2026-04-25

## DONE (Wave H2, 2026-04-25)

- [x] **DF-47** I-6/F-5/F-6 reflection-path regression pins — `tests/integration/test_reflection_path_regression.py`
- [x] **DF-48** reasoning trace persistence regression pin — `tests/integration/test_reasoning_trace_persistence.py`
- [x] **DF-49** Rule 6 inline-fallback sweep — 12 sites fixed across `runner.py`, `evolve/engine.py`, `task_mgmt/scheduler.py`, `knowledge/knowledge_manager.py`
- [x] **C1** broken test collection (`test_skill_runtime_factory.py` deleted)
- [x] **C2/C3** `routes_profiles.py` tenant scope + Rule 7 observability
- [x] **K-13** PI-C + PI-D combination test (`tests/integration/test_picd_combination.py`)

## DONE (Wave 9 — Owner-Track Hardening, 2026-04-25)

Expert findings F1–F18 from `hi-agent-engineering-leadership-hardening-guide-2026-04-25.md` and H1 review:

### Contract Owner (CO) track — CLOSED

- [x] **F5/CO-1** Posture enum (dev/research/prod) — `hi_agent/config/posture.py`; `test_posture.py` (32 tests); commit b35af2c
- [x] **F1/CO-2** project_id posture-required (research/prod → 400, dev → warning header) — `routes_runs.py`; `test_project_id_posture.py`
- [x] **CO-3** profile_id posture-required — `routes_runs.py`; `test_project_id_posture.py`
- [x] **F2/CO-4** RunRecord project_id first-class + orphan column closed in SQLiteRunStore — `run_store.py`; `test_run_store_project_id.py` (7 tests)
- [x] **F4/CO-5** Artifact spine fields (tenant_id, user_id, session_id, team_space_id) — `artifacts/contracts.py`; `test_artifact_spine_fields.py` (8 tests)
- [x] **F6/DF-50/CO-6** CapabilityDescriptor unified — registry.py canonical, descriptor_factory.py converted to factory fn; `test_capability_descriptor_canonical.py` (8 tests)
- [x] **F16/CO-7** TeamRunSpec platform-neutral contract — `contracts/team_runtime.py`; `test_team_run_spec.py` (10 tests)
- [x] **F8/CO-8** Profile jsonschema validation fail-closed under research/prod — `profiles/loader.py` + `profiles/schema.json`; `test_profile_loader_schema.py` (6 tests)
- [x] **CO-9** Structured HTTP error categories at /runs boundary — `server/error_categories.py`; `test_run_error_envelope.py` (3 tests)

### Runtime Owner (RO) track — CLOSED

- [x] **F3/RO-1** IdempotencyStore auth-scoped (tenant from workspace, not body) — `idempotency.py`; `test_idempotency_auth_scope.py`
- [x] **RO-2** Idempotency record binds project_id/user_id/session_id — `idempotency.py`
- [x] **F12/RO-3** RunQueue posture-default durable (SQLite under research/prod) — `run_queue.py`; `test_run_queue_posture_default.py`
- [x] **F11/RO-4** TeamRunRegistry SQLite-durable (in-memory dev only) — `team_run_registry.py`; `test_team_run_registry_durability.py`
- [x] **F15/RO-5** Cross-process restart integration test (xfail — boot path not yet fully wired) — `test_process_kill_restart.py`
- [x] **F15/RO-6** Cross-tenant isolation tests — `test_cross_tenant_isolation.py`
- [x] **RO-7** Idempotency terminal-state differentiation — `run_manager.py`; `test_idempotency_terminal_state.py`
- [x] **DF-51/RO-8** finished_at populated on all terminal paths — `run_manager.py`; `test_run_lifecycle_finished_at.py`
- [x] **DF-52/RO-9** Idempotency atomic insert (UNIQUE-constraint race fix) — `idempotency.py`; `test_idempotency_concurrency.py`

### Developer Experience (DX) track — CLOSED

- [x] **F7/DX-1** hi-agent init --posture CLI scaffolds config dir — `cli.py` + `cli_commands/init.py`; `test_cli_init.py`
- [x] **F17/DX-2** docs/quickstart-research-profile.md (30-min first run guide) — `docs/quickstart-research-profile.md`
- [x] **DX-3** Doctor posture checks (blocking under research) — `ops/diagnostics.py`; `test_doctor_posture_checks.py`
- [x] **F13/DX-4** /manifest full canonical descriptor surface — `routes_manifest.py`; `test_manifest_full_descriptor_surface.py`
- [x] **F9/DX-5** routes_profiles path leak fix (path_token not absolute path) — `routes_profiles.py`; `test_routes_profiles_no_path_leak.py`
- [x] **DX-6** Error category catalog in docs/api-reference.md — `docs/api-reference.md`
- [x] **DX-7** docs/posture-reference.md (posture defaults per capability) — `docs/posture-reference.md`
- [x] **DF-53/DX-8** HI_AGENT_RUN_MANAGER_CAPACITY documented in api-reference.md

### Trust & Evolution (TE) track — CLOSED

- [x] **F10/TE-1** ArtifactLedger corrupt-line quarantine + metric + WARNING — `artifacts/ledger.py`; `test_artifact_ledger_corruption.py`
- [x] **TE-2** ArtifactLedger posture-default durable — `artifacts/registry.py`; `test_ledger_posture_default.py`
- [x] **TE-3** Artifact tenant-first query scope (cross-tenant → 404) — `routes_artifacts.py`; `test_artifact_cross_tenant.py`
- [x] **F14/TE-4** Fallback per-kind Prometheus Counters (Rule 7 four-prong) — `observability/fallback.py`; `test_fallback_counters.py`
- [x] **TE-5** ReasoningTrace schema + write hook + deferred query route — `contracts/reasoning_trace.py`; `test_reasoning_trace_schema.py`

### Governance (GOV) track — CLOSED

- [x] **GOV-1** CLAUDE.md restructured — Ownership Tracks, R11/R12/R13, G4 gate, owner-track table — commit f768dc4
- [x] **GOV-2** docs/platform-capability-matrix.md migrated to L0–L4 model — commit f768dc4
- [x] **GOV-3** docs/TODO.md updated — all Wave 9 findings closed — (this commit)
- [x] **GOV-4** T3 freshness hard CI gate — scripts/check_t3_freshness.py + .github/workflows/claude-rules.yml (already in H1 wave, confirmed active)
- [x] **GOV-5** Wave 9 delivery notice — `docs/downstream-responses/2026-04-25-wave9-delivery-notice.md`

## DONE (Waves 10–24 summary, 2026-04-26–30)

### Wave 10 — Platform Spine + Strict Defaults
- Contract spine (tenant_id across all 5 writers), Rule 7 alarms, GateStore, TeamRunRegistry durable
- ExperimentStore, ExtensionManifest, RecoveryCoordinator, KG SQLite backend
- verified=72.0 (t3_deferred cap at Wave 12 baseline)

### Wave 11 — Event Spine + Idempotency
- EventStore append exec_ctx, SessionStore, ArtifactRegistry spine
- 8-writer consistency integration test, HTTP body enrichment (RunResult/TaskContract)

### Wave 12 — Default-Path Hardening (Rules 14–17)
- 16 tracks A–P; manifest as single release truth; allowlist discipline gate
- Rules 14–17 in CLAUDE.md; check_manifest_freshness, check_doc_consistency, check_wave_consistency
- verified=70.0 (docs-only gap cap)

### Wave 13 — Systemic Hardening
- 5 systemic pattern classes; snapshot-then-diff cross-tenant denial; route-scope gate
- verified=72.0 (t3_deferred cap)

### Wave 14 — Systemic Class Closure
- 7 classes closed; 35-gate infrastructure; check_recurrence_ledger; check_allowlist_discipline
- verified=72.0 (gate_warn cap)

### Wave 15 — Systemic Class Closure
- 8 classes; verified=77.6 (+5.6); noqa migration; type:ignore sweep

### Wave 16 — Observability Spine + Chaos + Operator Drill
- Operator drill scenarios; chaos matrix (10 scenarios); observability spine E2E driver
- Score capped at 80 by gate_warn (5 deferred) + soak 24h missing

### Wave 17 — Governance Hardening
- check_manifest_rewrite_budget, captain-checklist, W17-B* series
- verified=80.0 (gate_warn cap, 7 expired vocab allowlists)

### Wave 18 — "Stop Lying" (class-driven)
- C1: Gate strictness — removed all continue-on-error + --allow-docs-only-gap weakening; check_gate_strictness.py
- C2: Evidence honesty — spine driver observation-based, chaos runner ENV injection, /ops/drain endpoint
- C4: Vocab debt — all 7 expired aliases deleted atomically; allowlists cleared
- Clean-env: 8707 passed, 0 failures; chaos matrix: 4 passed, 6 skipped, 0 failed

### Wave 19 — Test Honesty
- [x] C1: Gate strictness — check_gate_strictness.py all sites resolved (CLOSED)
- [x] C2: Evidence honesty — spine driver observation-based, /ops/drain endpoint (CLOSED)
- [x] C5: Delete conftest global HI_AGENT_ALLOW_HEURISTIC_FALLBACK + convert to fixture (CLOSED)
- [x] C6: tests/posture/ matrix (34 Posture.from_env() callsites) (CLOSED)
- [x] C7: error_categories.py typed exception hierarchy (CLOSED)
- [x] C10: check_doc_truth.py in release-gate; Wave 17/18 written response (CLOSED)
- [x] C11: ledger schema + metric/alert/runbook fields (CLOSED)

### Wave 20 — CL class closures (partial; CL1–CL10 IN PROGRESS this session)
- Wave-label drift cleanup (CL8) applied
- CL1–CL10: IN PROGRESS — closing in W26 Phase 5 Lane I

### Wave 21 — Ecosystem Closure (partial; C7b/C11/C12 IN PROGRESS this session)
- C7b: type:ignore/noqa burndown: IN PROGRESS — Phase 5 Lane B (target: <25/<15)
- C11: ledger entries → operationally_observable: IN PROGRESS — Phase 5 Lane D
- C12: ExtensionRegistry lifecycle: IN PROGRESS — Phase 5 Lane E

### Wave 22 — Contract V1 Freeze
- V1_RELEASED=True flag in agent_server/config/version.py
- contract_v1_freeze.json committed
- docs/platform/agent-server-northbound-contract-v1.md: RELEASED (patched W25)

### Wave 23 — Multistatus + Rule 7 LLM hot-path
- Multistatus runner + 9 boundary gates; Rule 7 LLM hot-path closure
- verified=94.55 (manifest: 2026-04-30-a3f4353)

### Wave 24 — Honest Manifest Reset + 7×24 + Agent Server MVP
- 12 tracks + J-series; memory L1/L2 SQLite; capability per-posture matrix
- 8 agent_server routes + idempotency middleware + CLI; deployment harness
- verified=94.55 (manifest: 2026-04-30-09dd77f); 7×24=65.0 (soak/spine/chaos deferred)

### Wave 25 — W25 Close (this session)
- P-4 StageDirective wiring (PARTIAL: skip_to + insert_stage)
- Contract V1 markdown patched RELEASED
- Run manager QueueSaturatedError raise (Rule 7)
- Integration test guards (offline environment)
- Chaos matrix 8/8 committed at HEAD 374bce79
- W24 notice TBDs patched
- W25 manifest + closure + signoff: IN PROGRESS (Phase 3)
- Evidence (T3, spine, chaos, drill, 1h soak): IN PROGRESS (Phase 2)

---

## IN PROGRESS — Wave 27 (this session, Phase 5 parallel lanes)

### P-4 Dynamic re-planning (PARTIAL → closing this session)
- StageDirective wired in run_linear + run_graph + run_resume (W25)
- Phase 5 Lane M includes remaining integration evidence

### P-7 TierRouter active calibration (deferred Wave 19 → closing this session)
- ingest_calibration_signal() record-only since Wave 10.4
- Phase 5 Lane L: wire signal → routing weight influence

### CL1 — Rule 12 Spine completeness (IN PROGRESS — Phase 5 Lane I)
- Track X 4th store test (test_gate_store_restart_survival.py) included

### CL2 — Rule 7 Silent Degradation full closure (IN PROGRESS — Phase 5 Lane I)
- All 95 sites: Countable + Attributable + Inspectable + Gate-asserted

### CL3 — Stale expiry markers (IN PROGRESS — Phase 5 Lane I)
- 557 Wave 26 markers → stagger across W27/W28/W29/W30 by ownership track

### CL4 — Rule 5/6 sweep (IN PROGRESS — Phase 5 Lane I)

### CL5 — Rule 13 maturity (IN PROGRESS — Phase 5 Lane I)

### CL6 — Manifest hygiene (IN PROGRESS — Phase 5 Lane I)

### CL7 — Test honesty (IN PROGRESS — Phase 5 Lane I)

### CL8 — Wave-label drift (IN PROGRESS — Phase 5 Lane I)

### CL9 — Observability spine wiring (IN PROGRESS — Phase 5 Lane I; depends on Lane C)

### CL10 — Dimension lifts (IN PROGRESS — Phase 5 Lane I)

### C7b — type:ignore/noqa burndown (IN PROGRESS — Phase 5 Lane B)
- Current: 132 type:ignore, 119 noqa (regressed from W21 baseline)
- Target: <25 type:ignore, <15 noqa

### C8 — RunEventEmitter + 12 typed events (IN PROGRESS — Phase 5 Lane C)
- W20 PENDING: event_emitter.py + 12 record_* methods

### C11 — 10 ledger entries → operationally_observable (IN PROGRESS — Phase 5 Lane D)

### C12 — Extension lifecycle (IN PROGRESS — Phase 5 Lane E)
- ExtensionRegistry upgrade/rollback + ExperimentStore rollback + CLI

### Track AA — 3-layer test fills (IN PROGRESS — Phase 5 Lane A)
- Subsystems: trajectory, orchestrator, state, replay, task_view, failures

### W24 carries (IN PROGRESS — Phase 5 Lanes N/O/P)
- N: Posture coverage 86%→100% (9 decorator-only sites in artifact validation)
- O: MCP-tools northbound adapter
- P: Idempotency on skill register + memory write routes

### Wave 10 carryover (IN PROGRESS — Phase 5 Lane M, time-boxed 4h)
- RO-5 boot path: Wire durable RunQueue through app.py server boot
- POST /artifacts write API
- ProjectPostmortem lifecycle integration
- Budget multi-level enforcement (deferrable)
- KG L2 default-on (deferrable)
- Self-evolution gated update + rollback (deferrable, depends on Lane E)

---

## WARNING DEBT (low priority)

- Python 3.14 Windows SQLite `PytestUnraisableExceptionWarning` in agent_kernel
