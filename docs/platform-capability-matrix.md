# hi-agent Platform Capability Matrix

Last updated: 2026-04-25 (Wave 9 — Owner-Track Hardening)

---

## Capability Status Legend (Rule 13 — L0–L4 Maturity Model)

| Level | Name | Criterion |
|---|---|---|
| L0 | demo code | happy path only, no stable contract |
| L1 | tested component | unit/integration tests exist, not default path |
| L2 | public contract | schema/API/state machine stable, docs + full tests |
| L3 | production default | research/prod default-on, migration + observability |
| L4 | ecosystem ready | third-party can register/extend/upgrade/rollback without source |

Legacy labels still shown for backward reference: `experimental`≈L1, `implemented_unstable`≈L1, `public_contract`≈L2, `production_ready`≈L3.

---

## Core Platform Dimensions

| Dimension | Level | Evidence | Tests | Endpoint | Posture Coverage |
|---|---|---|---|---|---|
| TRACE single-run execution | L2 | RunExecutor + StageOrchestrator; K-defects resolved; Wave 9 TE-5 adds reasoning trace schema | tests/integration/test_run_lifecycle*.py | POST /runs | dev ✓ research ✓ |
| Config-driven extensibility | L2 | HI_AGENT_CONFIG_DIR; JSON profile loader with jsonschema validation (CO-8); hi_agent_config.json; extension-guide; quickstart (DX-2) | tests/integration/test_config_dir_resolution.py, test_profile_loader_schema.py | GET /tools | dev ✓ research ✓ (fail-closed) |
| Registry-based capability | L2 | Canonical CapabilityDescriptor (CO-6 — DF-50 closed); /manifest exposes full descriptor surface (DX-4) | tests/contract/test_capability_descriptor_canonical.py | GET /tools, GET /manifest | dev ✓ |
| Long-running task stability | L1 (server-path); L2 component-only | RunQueue posture-default durable (RO-3); RunStore project_id first-class (CO-4); TeamRunRegistry durable (RO-4); cross-process restart not yet wired through full server boot (RO-5 pending Wave 10) | test_run_queue_posture_default.py, test_team_run_registry_durability.py | - | dev ✓ research L2→L3 in Wave 10 |
| Project-level cross-run state | L2 | project_id in RunRecord + upsert (CO-4); posture-enforced required field (CO-2); list_runs_by_project query | test_run_store_project_id.py, test_project_id_posture.py | POST /runs {project_id} | dev warn research 400 |
| Contract Spine Completeness | L2 | Artifact + tenant/user/session/team_space fields (CO-5); IdempotencyStore auth-scoped (RO-1/2); Artifact tenant-first query (TE-3) | test_artifact_spine_fields.py, test_idempotency_auth_scope.py, test_artifact_cross_tenant.py | - | dev ✓ research ✓ |
| Multi-agent team runtime | L1 | TeamRunSpec platform contract (CO-7); TeamRunRegistry durable (RO-4); TeamRun/AgentRole dataclasses | test_team_run_spec.py, test_team_run_registry_durability.py | - | dev ✓ research partial |
| Evidence / anti-hallucination | L2 | ArtifactLedger: corrupt-line quarantine+metric (TE-1); posture-default durable (TE-2); tenant-first query (TE-3); provenance fields on Artifact | test_artifact_ledger_corruption.py, test_ledger_posture_default.py, test_artifact_cross_tenant.py | GET /artifacts | dev ✓ research ✓ (fail-closed) |
| Observability & Fallback | L2 | record_fallback() wired to per-kind Prometheus Counters (TE-4): hi_agent_{llm,heuristic,capability,route}_fallback_total | test_fallback_counters.py | GET /metrics | dev ✓ research ✓ |
| Evolution closed loop | L1 | ProjectPostmortem + CalibrationSignal + on_project_completed; record-only; ReasoningTrace schema + write hook (TE-5) | test_reasoning_trace_schema.py | GET /runs/{id}/reasoning-trace (stub) | dev only |
| Knowledge graph abstraction | L1 | KnowledgeGraphBackend Protocol + JsonGraphBackend alias | test_knowledge_graph_backend_protocol.py | GET /knowledge/status | dev only |
| Research workspace model | L0 | ResearchProjectSpec deferred Wave 10; TeamRunSpec available as platform-neutral alternative | - | - | - |
| Ops and release governance | L2 | Posture enum (CO-1/R11); G1-G4 intake gates; doctor posture checks (DX-3); T3 CI gate (GOV-4); capability matrix L0–L4 (GOV-2) | test_posture.py, test_doctor_posture_checks.py | GET /health, GET /manifest | dev ✓ research ✓ |
| Human gate lifecycle | L2 | GatePendingError + continue_from_gate + SQLiteGateStore | tests/integration/test_dangerous_capability*.py | POST /runs/{id}/signal | dev ✓ research ✓ |
| LLM tier routing | L1 | TierRouter + TierAwareLLMGateway; calibration signal ingest record-only | tests/unit/test_evolve_policy_resolution.py | - | dev only |
| Error contract | L2 | Structured error categories at /runs boundary (CO-9): {error_category, message, retryable, next_action}; catalog in docs/api-reference.md | test_run_error_envelope.py | POST /runs | dev ✓ research ✓ |
| Developer Experience (DX) | L2 | hi-agent init CLI (DX-1); quickstart doc (DX-2); posture-aware doctor (DX-3); full manifest surface (DX-4); profile path redaction (DX-5); posture-reference.md (DX-7) | test_cli_init.py, test_doctor_posture_checks.py, test_manifest_full_descriptor_surface.py | - | dev ✓ research ✓ |

---

## Wave 8 Additions (P1–P7) — Final Status

| Track | Capability | L-Level | Wave 9 Uplift |
|---|---|---|---|
| P1 | project_id first-class in TaskContract + memory + HTTP | L2 | CO-2 (posture-required), CO-4 (RunRecord field), CO-3 (profile_id) |
| P2 | CapabilityDescriptor provenance/evidence fields + ArtifactLedger | L2 | CO-6 (canonical unification), TE-1/2/3 (ledger hardening) |
| P3 | cancel_run CancellationToken propagation + SQLiteGateStore | L2 | - |
| P4 | AgentRole/TeamRun/TeamSharedContext dataclasses | L1 | CO-7 (TeamRunSpec), RO-4 (durable registry) |
| P5 | /manifest endpoint + platform-capability-matrix.md | L2 | DX-4 (full descriptor surface), GOV-2 (L0–L4 migration) |
| P6 | ProjectPostmortem + CalibrationSignal + evolution hooks | L1 | TE-5 (reasoning trace schema + write hook) |
| P7 | KnowledgeGraphBackend Protocol + JsonGraphBackend alias | L1 | - |

---

## H1 Hardening Additions (post-Wave 8) — Final Status

| Track | Capability | L-Level | Wave 9 Uplift |
|---|---|---|---|
| H1-T0 | G1/G2/G3/G4 intake decisions doc (governance gate) | L2 | GOV-1 adds G4 Posture & Spine gate to CLAUDE.md |
| H1-T1 | Idempotency replay 200 + snapshot; mark_complete wired | L2 | RO-1/2/7/9 (auth scope, spine fields, terminal state, race fix) |
| H1-T2 | Tenant scope universal: all routes | L2 | DX-5 (profile path leak), TE-3 (artifact tenant-first), RO-6 (cross-tenant tests) |
| H1-T3 | /manifest: version from metadata, per-capability schemas | L2 | DX-4 (full canonical descriptor surface) |
| H1-T4 | Test honesty; DF-46 CI gate closed | L2 | RO-5/6/8 (real restart, cross-tenant, finished_at) |
| H1-T5 | HI_AGENT_CONFIG_DIR; JSON profile loader; strict-mode | L2 | CO-8 (jsonschema validation fail-closed), CO-1 (posture enum), R11 |

---

## Wave 9 Additions (CO/RO/DX/TE)

| ID | Capability | L-Level | Commit / Test Evidence |
|---|---|---|---|
| CO-1 | Posture enum (dev/research/prod) | L2 | b35af2c; test_posture.py (32 tests) |
| CO-2/3 | project_id/profile_id posture-required | L2 | CO merge; test_project_id_posture.py (8 tests) |
| CO-4 | RunRecord project_id first-class | L2 | CO merge; test_run_store_project_id.py (7 tests) |
| CO-5 | Artifact spine fields (tenant/user/session/team_space) | L2 | CO merge; test_artifact_spine_fields.py (8 tests) |
| CO-6 | Canonical CapabilityDescriptor (DF-50 closed) | L2 | CO merge; test_capability_descriptor_canonical.py (8 tests) |
| CO-7 | TeamRunSpec platform-neutral contract | L1 | CO merge; test_team_run_spec.py (10 tests) |
| CO-8 | Profile jsonschema validation (fail-closed under research/prod) | L2 | CO merge; test_profile_loader_schema.py (6 tests) |
| CO-9 | Structured HTTP error categories at /runs | L2 | CO merge; test_run_error_envelope.py (3 tests) |
| RO-1/2 | Auth-scoped idempotency + spine fields | L2 | RO merge; test_idempotency_auth_scope.py |
| RO-3 | RunQueue posture-default durable | L2 | RO merge; test_run_queue_posture_default.py |
| RO-4 | TeamRunRegistry SQLite-durable | L2 | RO merge; test_team_run_registry_durability.py |
| RO-5 | Cross-process restart integration test | L1 | RO merge; test_process_kill_restart.py (pending boot-path wiring — not valid evidence) |
| RO-6 | Cross-tenant isolation tests | L2 | RO merge; test_cross_tenant_isolation.py |
| RO-7 | Idempotency terminal-state differentiation | L2 | RO merge; test_idempotency_terminal_state.py |
| RO-8 | DF-51: finished_at on all terminal paths | L2 | RO merge; test_run_lifecycle_finished_at.py |
| RO-9 | DF-52: idempotency race fix (atomic insert) | L2 | RO merge; test_idempotency_concurrency.py |
| DX-1 | hi-agent init --posture CLI | L2 | DX merge; test_cli_init.py |
| DX-2 | Quickstart doc (30-min research profile) | L2 | DX merge; docs/quickstart-research-profile.md |
| DX-3 | Doctor posture checks (blocking under research) | L2 | DX merge; test_doctor_posture_checks.py |
| DX-4 | /manifest full canonical descriptor surface | L2 | DX merge; test_manifest_full_descriptor_surface.py |
| DX-5 | routes_profiles path leak fix | L2 | DX merge; test_routes_profiles_no_path_leak.py |
| DX-7 | docs/posture-reference.md | L2 | DX merge; docs/posture-reference.md |
| TE-1 | ArtifactLedger corrupt-line quarantine + metric | L2 | TE merge; test_artifact_ledger_corruption.py |
| TE-2 | ArtifactLedger posture-default durable | L2 | TE merge; test_ledger_posture_default.py |
| TE-3 | Artifact tenant-first query scope | L2 | TE merge; test_artifact_cross_tenant.py |
| TE-4 | Fallback per-kind Prometheus Counters (Rule 7) | L2 | TE merge; test_fallback_counters.py |
| TE-5 | ReasoningTrace schema + write hook + deferred route | L1 | TE merge; test_reasoning_trace_schema.py |

---

## What is NOT done in Wave 9 (deferred to Wave 10)

| Item | Reason | Target |
|---|---|---|
| ResearchProjectSpec → TeamRunSpec compile reference | Business-layer compile; platform provides TeamRunSpec | Wave 10 |
| POST /artifacts write API | Needs CO-5 + TE-3 stable first | Wave 10 |
| ProjectPostmortem lifecycle integration | Needs TE-2 durable ledger wired | Wave 10 |
| Budget multi-level enforcement (project/profile/run/stage) | Descriptor fields exist; runtime enforcement deferred | Wave 10 |
| Knowledge graph durable backend | JsonGraphBackend remains experimental | Wave 10 |
| Self-evolution gated update + rollback | Needs human-approval design; TE-5 is schema only | Wave 10 |
| Process-kill restart full boot integration | RO-5 xfail — durable queue not yet wired through server boot | Wave 10 pre-work |
| Temporal as production main path | Not prioritized | Deferred |

---

## Wave 10.2 / Wave 10.3 Additions

| Capability | Level | Owner | Evidence | Rule incidents |
|---|---|---|---|---|
| GateStore contract spine (tenant/user/session/resolved_at) | L3 | CO+RO | `tests/integration/test_gate_store_spine.py` (W3-A) | R12 — no explicit spine fields until Wave 10.2 |
| TeamRunRegistry contract spine (status/finished_at) | L3 | CO+RO | `tests/integration/test_team_run_registry_spine.py` (W3-A) | R12 — status column absent until Wave 10.2 |
| FeedbackStore contract spine (tenant/user/session/project) | L3 | CO+RO | `tests/integration/test_feedback_store_spine_via_http.py` (W3-A) | R12 — spine fields absent until Wave 10.2 |
| RunQueue contract spine (tenant/user/session/project) | L3 | CO+RO | `tests/integration/test_run_queue_spine_via_http.py` (W3-A) | R12 — spine columns absent until Wave 10.2 |
| Cross-tenant object-level isolation | L3 | RO | `tests/integration/test_cross_tenant_object_level.py` (W3-A) | R12 — object-level scope not enforced until Wave 10.2 |
| HumanGate contract spine | L3 (post W3-A) | CO+RO | `tests/integration/test_human_gate_spine_strict.py` | R12, R6 — no explicit spine fields until Wave 10.3 |
| OpHandle strict-deny empty tenant | L3 (post W3-A) | RO | `tests/integration/test_op_handle_strict.py` | R11 — posture not wired until Wave 10.3 |
| GateStore unscoped read strict raise | L3 (post W3-A) | RO | `tests/integration/test_gate_store_unscoped_strict.py` | R11 — warn-only until Wave 10.3 |
| runner.py finalize alarm | L3 (post W3-B) | RO | `tests/unit/test_runner_finalize_fallback_alarm.py` | R7 — silent fallback until Wave 10.3 |
| runner.py get_fallback_events alarm | L3 (post W3-B) | RO | `tests/unit/test_runner_get_fallback_events_alarm.py` | R7 — silent fallback until Wave 10.3 |
| http_gateway FailoverChain alarm | L3 (post W3-B) | RO | `tests/integration/test_http_gateway_failover_alarm.py` | R7 — silent failover until Wave 10.3 |
| RunExecutionContext plumbing (3-writer pilot) | L2 | CO+RO | `tests/unit/test_run_execution_context_pilot.py`, `tests/integration/test_intake_to_finalizer_spine_consistency.py` | R12 — seed only until Wave 10.3 |
| Posture guard helpers (require_tenant) | L3 (post W3-A) | CO | `tests/unit/test_posture_guards.py` | R11 — inline guard logic duplicated until Wave 10.3 |
| select_completeness CI gate | L2 | RO | `tests/unit/test_check_select_completeness.py` | R12 — defensive len() fallbacks until Wave 10.2 |
| RunExecutionContext dataclass | L2 | CO+RO | `tests/unit/test_run_execution_context.py` | R12 — seed-level carrier until Wave 10.3 |
| Wave 10.3 clean-env verification | L2 | DX | `scripts/verify_clean_env.py` | R8 — Windows basetemp PermissionError until Wave 10.3 |

---

## Wave 10.4 Additions — Platform Maturation Sprint (2026-04-26, HEAD f5e3cff)

| Capability | Level | Owner | Evidence | Rule / Class |
|---|---|---|---|---|
| Evolve dataclass spine (RunPostmortem/CalibrationSignal/ProjectPostmortem/EvolveResult/EvolveMetrics) | L3 | CO+RO | `tests/unit/test_run_postmortem_spine.py` | R12 — Class F spine gap until Wave 10.4 |
| EpisodeRecord contract spine (5-field) | L3 | CO | `tests/unit/test_episode_record_spine.py` | R12 — no spine until Wave 10.4 |
| EvolutionExperiment dataclass (posture-aware) | L2 | CO | `tests/unit/test_evolution_experiment_dataclass.py` | Class Q — in-memory only until Wave 10.4 |
| ExperimentStore Protocol + Sqlite/InMemory implementations | L2 | CO+RO | `tests/integration/test_experiment_store_sqlite.py` | Class Q — research/prod durable proposals |
| EvolveEngine writes EvolutionExperiment on proposals | L2 | RO+TE | `tests/integration/test_evolve_engine_writes_experiment.py` | Class Q — engine wired to ExperimentStore |
| ExtensionManifest Protocol + ExtensionRegistry | L2 | CO | `tests/unit/test_extension_manifest_protocol.py`, `tests/unit/test_extension_registry.py` | Class P — 4 manifest kinds unified under Protocol |
| Unified /manifest extensions array (posture-filtered) | L3 | DX | `tests/integration/test_routes_manifest_unified.py` | Class P — /manifest additive extension surface |
| hi-agent extensions list/inspect CLI | L2 | DX | `tests/integration/test_cli_extensions_list.py` | Class P — extension discovery from CLI |
| Process recovery rehydration on startup | L2 | RO | `tests/integration/test_async_client_lifetime.py`, `test_lease_expired_reenqueue_under_prod` (unit) | Class L — lifespan _rehydrate_runs wired; subprocess E2E skipped (Windows sandbox) |
| RunQueue stale-lease expiry + HI_AGENT_RUN_LEASE_SECONDS | L2 | RO | `test_lease_expired_warned_under_research` (unit) | Class L — expire_stale_leases() method |
| Async client cross-loop lifetime stress | L2 | RO | `tests/integration/test_async_client_lifetime.py` | R5 — 5x asyncio.run() no loop errors |
| Cross-tenant denial: routes_events, routes_memory, routes_profiles | L3 | TE | `tests/integration/test_routes_{events,memory,profiles}_cross_tenant.py` | Class H — tenant denial tests |
| Cross-tenant denial: routes_tools_mcp (4 handlers fixed) | L3 | TE+RO | `tests/integration/test_routes_tools_mcp_cross_tenant.py` | Class H — handler scoping gap fixed |
| Cross-tenant denial: routes_knowledge | L3 | TE | `tests/integration/test_routes_knowledge_cross_tenant.py` | Class H — audit confirmed scoped |
| Rule 6 inline-fallback sweep (8 sites) | L3 | CO+RO | `tests/unit/test_check_rules_inline_fallback.py` | R6 + Class G — constructor-call form |
| check_rules.py Rule 6 constructor-call regex | L3 | GOV | `tests/unit/test_check_rules_inline_fallback.py` | R6 — check extended to catch x or ClassName() |
| IdempotencyStore exec_ctx spine | L3 | RO | `tests/unit/test_idempotency_exec_ctx.py` | Class K — writer 1 of 5 |
| EventStore.append exec_ctx spine | L3 | RO | `tests/unit/test_event_store_exec_ctx.py` | Class K — writer 2 of 5 |
| TeamRunRegistry.register exec_ctx spine | L3 | CO+RO | `tests/unit/test_team_run_registry_exec_ctx.py` | Class K — writer 3 of 5 |
| SessionStore.create exec_ctx spine | L3 | RO | `tests/unit/test_session_store_exec_ctx.py` | Class K — writer 4 of 5 |
| ArtifactRegistry.create exec_ctx spine | L3 | CO+TE | `tests/unit/test_artifact_registry_exec_ctx.py` | Class K — writer 5 of 5 |
| 8-writer spine consistency (intake→finalizer) | L3 | CO+RO+TE | `tests/integration/test_intake_to_finalizer_spine_extended.py` | Class K — all 8 writers proven consistent |
| RunResult.to_dict() optional spine keys (back-compat) | L2 | CO | `tests/integration/test_run_result_body_spine.py` | Class J — additive HTTP body enrichment |
| TaskContract optional body spine (precedence over middleware) | L2 | CO | `tests/integration/test_task_contract_body_spine.py` | Class J — explicit body field wins |
| SqliteKnowledgeGraphBackend (tenant-scoped, Protocol-compliant) | L2 | RO | `tests/unit/test_sqlite_kg_backend.py`, `tests/integration/test_kg_restart_survival.py` | Class R — KG SQLite backend |
| Knowledge graph posture-aware factory | L2 | RO | `tests/integration/test_kg_backend_factory_posture.py` | Class R — factory ready; default JSON until Wave 10.5 |
| release_gate episode skip Rule 7 alarms (2 sites) | L3 | TE | `tests/unit/test_release_gate_episode_skip_alarm.py` | R7 + Class I — corrupt+timestamp sites |
| failover Retry-After parse Rule 7 counter | L3 | RO | `tests/unit/test_failover_retry_after_parse_alarm.py` | R7 + Class I — counter-only |
| mcp/transport stderr tail Rule 7 counter | L3 | TE | `tests/unit/test_mcp_transport_stderr_tail_alarm.py` | R7 + Class I — counter-only |
| Wave 10.4 clean-env verification bundle (254 tests) | L3 | DX | `scripts/verify_clean_env.py` | R8 — expanded bundle passes in clean-env |
