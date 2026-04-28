# hi-agent Engineering TODO

Last updated: 2026-04-29 (Wave 18 — "Stop Lying" governance class fixes)

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
- [x] **GOV-5** Wave 9 delivery notice — `docs/downstream-responses/2026-04-25-wave9-delivery-notice.md` (pending)

## PENDING — Phase 2 (deferred from Wave 9)

- P-1 Provenance: `RawMemoryEntry.provenance` field, `CapabilitySpec.source_reference`
- P-3 Cross-Run Project aggregation: `project_id` scope model design
- P-5 Confidence scoring: `Artifact.confidence: float` field
- docs/specs/provenance-spec.md (design draft)

## PENDING — Phase 3 (P-4, P-6, P-7)

- P-4 Dynamic re-planning API: `StageDirective(skip_to, insert_stage)`
- P-6 KG inference: transitive query + conflict detection on LongTermMemoryGraph (JSON)
- P-7 Feedback path: `submit_run_feedback()` → EvolveEngine

## OPEN — Wave 10 Candidates (deferred from Wave 9)

- **RO-5 boot path**: Process-kill restart xfail — durable RunQueue not yet wired through `app.py` server boot; full posture-aware boot requires server startup changes
- **POST /artifacts write API**: Needs CO-5 + TE-3 stable first (now satisfied; Wave 10 P1)
- **ProjectPostmortem lifecycle integration**: Needs TE-2 durable ledger wired (now satisfied; Wave 10)
- **Budget multi-level enforcement (project/profile/run/stage)**: Descriptor fields exist; runtime enforcement deferred
- **Knowledge graph durable backend**: JsonGraphBackend remains experimental
- **Self-evolution gated update + rollback**: Needs human-approval design; TE-5 is schema only
- **ResearchProjectSpec → TeamRunSpec compile reference**: CO-7 introduces TeamRunSpec; downstream compile is research team's

## DONE (Waves 10–18 summary, 2026-04-26–29)

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

### Wave 15 — systemic class closure
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

## PENDING — Wave 19 (Test Honesty)
- C5: Delete conftest global HI_AGENT_ALLOW_HEURISTIC_FALLBACK + convert to fixture
- C6: tests/posture/ matrix (34 Posture.from_env() callsites)
- C10: check_doc_truth.py in release-gate; Wave 17/18 written response
- C11: ledger schema + metric/alert/runbook fields

## PENDING — Wave 20 (Operational Evidence)
- C8: event_emitter.py + 12 typed events (llm_call, tool_call, heartbeat_renewed, etc.)
- C9: 24h soak with mid-soak SIGTERM; sampler bind to server PID; check_soak_evidence hardening
- C7a: error_categories.py typed exception hierarchy; app.py/runner.py/run_manager.py narrowing

## PENDING — Wave 21 (Ecosystem Closure)
- C7b: type:ignore 85→<25; noqa 47→<15
- C11: all 10 ledger entries to operationally_observable
- C12: ExtensionRegistry upgrade/rollback, ExperimentStore rollback, StageDirective skip_to

## WARNING DEBT (low priority)

- Python 3.14 Windows SQLite `PytestUnraisableExceptionWarning` in agent_kernel
