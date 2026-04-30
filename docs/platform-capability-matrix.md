# hi-agent Platform Capability Matrix

Last updated: 2026-05-01 (Wave 25 — in progress)

---

## Capability Status Legend (Rule 13 — L0–L4 Maturity Model)

| Level | Name | Criterion |
|---|---|---|
| L0 | demo code | happy path only, no stable contract |
| L1 | tested component | unit/integration tests exist, not default path |
| L2 | public contract | schema/API/state machine stable, docs + full tests |
| L3 | production default | research/prod default-on, migration + observability |
| L4 | ecosystem ready | third-party can register/extend/upgrade/rollback without source |

Active docs use L0–L4 exclusively (Rule 13, Wave 9+). Mapping from retired labels: see `docs/governance/maturity-glossary.md`.

---

## Core Platform Dimensions

| Dimension | Level | Evidence | Tests | Endpoint | Posture Coverage |
|---|---|---|---|---|---|
| TRACE single-run execution | L2 | RunExecutor + StageOrchestrator; K-defects resolved; Wave 9 TE-5 adds reasoning trace schema | tests/integration/test_run_lifecycle*.py | POST /runs | dev ✓ research ✓ |
| Config-driven extensibility | L2 | HI_AGENT_CONFIG_DIR; JSON profile loader with jsonschema validation (CO-8); hi_agent_config.json; extension-guide; quickstart (DX-2) | tests/integration/test_config_dir_resolution.py, test_profile_loader_schema.py | GET /tools | dev ✓ research ✓ (fail-closed) |
| Registry-based capability | L3 | Canonical CapabilityDescriptor (CO-6 — DF-50 closed); /manifest exposes full descriptor surface (DX-4); per-posture matrix wired (Track D, W24); probe_availability_with_posture raises CapabilityNotAvailableError (structured 400) | tests/contract/test_capability_descriptor_canonical.py, tests/unit/test_capability_posture_matrix.py | GET /tools, GET /manifest | dev ✓ research ✓ prod ✓ |
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
| Knowledge graph durable backend | JsonGraphBackend at L1 (tested, not default path) | Wave 10 |
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

## Wave 10.5 Additions — Default-Path Closure & Evidence Sprint (2026-04-26, HEAD 3b99805)

| Capability | Level | Owner | Evidence | Rule / Class |
|---|---|---|---|---|
| RecoveryState enum + decide_recovery_action() | L3 | RO | `tests/unit/test_recovery_state_machine.py` | R11 — posture-driven default; dev=warn, research/prod=re-enqueue |
| _rehydrate_runs posture-aware re-enqueue | L3 | RO | W5-C integration in `server/app.py` | Class L — default ON under research/prod |
| RunExecutionContext all 11 durable writers | L3 | CO+RO+TE | `tests/unit/test_artifact_registry_exec_ctx.py` + 10 per-writer tests | R12 — Class K full coverage |
| ArtifactRegistry.create() factory with exec_ctx | L3 | CO+TE | `tests/unit/test_artifact_registry_exec_ctx.py` | R12 — spine merge at construction |
| ExtensionManifest 4 enforcement fields | L3 | CO | `tests/unit/test_extension_manifest_enforcement_fields.py` (17 cases) | Class D — required_posture, tenant_scope, dangerous_capabilities, config_schema |
| ExtensionRegistry validated register() | L3 | CO+RO | `tests/unit/test_extension_registry_validation.py` (13 cases) | Class D — posture-aware; dev=warn, research/prod=reject |
| ExtensionRegistry fail-closed enable() gate | L3 | CO+RO | `tests/unit/test_extension_registry_enable_gate.py` (13 cases) | Class D — production_eligibility check before enable |
| ExtensionDisallowedError typed exception | L3 | CO | `tests/unit/test_extension_registry_enable_gate.py` | Class D — reasons list on exception |
| hi-agent extensions validate CLI subcommand | L3 | DX | `tests/integration/test_extensions_cli_validate.py` | Class P — dry-run manifest validation |
| KG SQLite backend default under research/prod | L3 | RO | `tests/integration/test_kg_server_uses_factory.py` | Class R — make_knowledge_graph_backend() wired into SystemBuilder |
| KG backend posture-aware factory (dev→JSON, research/prod→SQLite) | L3 | RO | `tests/integration/test_kg_backend_factory_posture.py` | Class R — HI_AGENT_KG_BACKEND env override for migration |
| _tenant_guard.py centralized tenant isolation | L3 | RO | `scripts/check_route_scope.py` | R12 — require_tenant_owns() returns 404 |
| Cross-tenant denial: routes_runs, artifacts, sessions, team, ops | L3 | TE | 5 new cross-tenant test files (W5-G) | Class H — 25-route audit complete |
| verify_clean_env.py portable CLI with JSON evidence | L3 | GOV | `tests/unit/test_verify_clean_env_args.py`, `test_verify_clean_env_preflight.py` | R8 — basetemp+cache-dir CLI, no repo pollution |
| check_doc_consistency HEAD-alignment + score-cap rules | L3 | GOV | `tests/unit/test_check_notice_head_alignment.py`, `test_check_score_cap.py` | Class A — governance enforcement for delivery notices |
| API key source policy (config/llm_config.json only) | L3 | DX | `tests/unit/test_json_config_loader_no_env.py` | Class E — VOLCE_API_KEY env var removed from production path |
| Wave 10.5 clean-env evidence (90 tests) | L3 | DX | `docs/delivery/2026-04-26-3b9980594e887a6ce4a733f93b27724f58c00708-clean-env.json` | R8 — portable tmpdir, HEAD-aligned |

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

---

## Wave 11 — Comprehensive Hardening (2026-04-27, HEAD 88960cc)

| Capability | Level | Owner | Evidence | Rule / Class |
|---|---|---|---|---|
| Platform vocabulary decoupling (no research-domain terms) | L3 | GOV | `scripts/check_no_research_vocab.py` | R2 — platform must not couple business logic |
| Route scope completeness (all 25+ routes carry tenant isolation) | L3 | TE | `scripts/check_route_scope.py` | R12 — tenant guard on every handler |
| Silent degradation sweep (16 sites audited) | L3 | TE | `scripts/check_silent_degradation.py` | R7 — all fallback branches emit metrics |
| Metric producer completeness | L3 | TE | `scripts/check_metric_producers.py` | R7 — metric registration cross-check |
| Evidence provenance validation | L3 | GOV | `scripts/check_evidence_provenance.py` | R8 — no synthetic-only evidence in release |
| Validate-before-mutate pattern | L3 | RO | `scripts/check_validate_before_mutate.py` | R3 — all store mutations validate first |

---

## Waves 12–13 — Default-Path Hardening + Systemic Class Closure (2026-04-27)

| Capability | Level | Owner | Evidence | Rule / Class |
|---|---|---|---|---|
| Async client lifetime (cross-loop stress, Rule 5) | L3 | RO | `tests/integration/test_async_client_lifetime.py` | R5 — no Event-loop-closed on run ≥2 |
| Durable backend wiring gate | L3 | GOV | `scripts/check_durable_wiring.py` | R11 — durable stores required under research/prod |
| Closure taxonomy enforcement | L3 | GOV | `scripts/check_closure_taxonomy.py` (W14-D8) | R15 — all closures carry level enum |
| Test honesty audit (MagicMock on subsystem) | L3 | TE | `scripts/check_test_honesty.py` | R4 — integration tests use real components |
| noqa discipline gate | L3 | GOV | `scripts/check_noqa_discipline.py` | R3 — no noqa added same commit as offending line |
| pytest skip discipline gate | L3 | GOV | `scripts/check_pytest_skip_discipline.py` | R4 — skips carry reason + expiry_wave |
| No hardcoded wave strings | L3 | GOV | `scripts/check_no_hardcoded_wave.py` | R2 — wave labels never hardcoded in source |
| Multi-status gate support | L3 | GOV | `scripts/check_multistatus_gates.py` | R8 — deferred gates declare multi-status |

---

## Waves 14–15 — Systemic Class Closure Sprint (2026-04-27)

| Capability | Level | Owner | Evidence | Rule / Class |
|---|---|---|---|---|
| Governance gate infrastructure (35 CI gates) | L3 | GOV | `release-gate.yml` — all 35 steps blocking | W14/W15 gate additions |
| Allowlist universal coverage | L3 | GOV | `scripts/check_allowlist_universal.py` (W14-D3) | R17 — every allowlist entry carries owner/risk/expiry |
| Score cap automation | L3 | GOV | `scripts/check_score_cap.py` (W14-A7) | R14 — no manual score increase path |
| Operator drill evidence | L3 | GOV | `scripts/check_operator_drill.py` (W16-H4) | R8 — operator-shape drill recorded |
| Observability spine completeness (structural) | L2 | TE | `scripts/check_observability_spine_completeness.py` | P0-3 — real spine deferred to W19 |
| Soak evidence (pilot 360m) | L2 | TE | `scripts/check_soak_evidence.py` | P0-4 — 24h soak deferred; 7x24=65 cap enforced |
| Chaos runtime coupling | L3 | TE | `scripts/check_chaos_runtime_coupling.py` | P0-5 — real HTTP chaos scenarios with runtime_coupled:true |
| Manifest rewrite budget gate | L3 | GOV | `scripts/check_manifest_rewrite_budget.py` (W17-B19) | R14 — max 3 manifest rewrites per wave |
| Untracked release artifacts gate | L3 | GOV | `scripts/check_untracked_release_artifacts.py` (W17-B13) | R14 — no uncommitted manifests in working tree |

---

## Wave 16 — Release Identity + Operator Drill (2026-04-28)

| Capability | Level | Owner | Evidence | Rule / Class |
|---|---|---|---|---|
| Release identity triple-SHA consistency | L3 | GOV | `scripts/check_release_identity.py` (W16-A8) | R14 — manifest.release_head == git HEAD == notice HEAD |
| Manifest freshness gate | L3 | GOV | `scripts/check_manifest_freshness.py` (W16-A8) | R14 — manifest not stale vs current HEAD |
| Wave label consistency gate | L3 | GOV | `scripts/check_wave_consistency.py` (W17-B11) | R14 — current-wave.txt, allowlists, manifest, notice all agree |
| Recurrence ledger gate | L3 | GOV | `scripts/check_recurrence_ledger.py` (W16-G3) | R15 — all 13 ledger fields present per entry |
| Release captain checklist | L3 | GOV | `docs/governance/release-captain-checklist.md` | R15 — named captain signs off on all 13 steps |
| Delivery protocol | L3 | GOV | `docs/governance/delivery-protocol.md` | R15 — 13-step protocol documented |
| Gate-weakening freeze policy | L3 | GOV | `docs/governance/recurrence-ledger.yaml` W17-A | R8 — no new --allow-* flags without ledger entry |
| Cross-tenant run_store primitive safety | L3 | RO | `tests/security/test_run_store_tenant_required.py` | W17-B — get_for_tenant() required; bare run_id blocked |
| Test fallback scope isolation | L3 | TE | `scripts/check_conftest_fallback_scope.py` | W17-C — heuristic fallback blocked in release profile |

---

## Wave 17 — Anti-Loop + Governance Tightening (2026-04-28)

| Capability | Level | Owner | Evidence | Rule / Class |
|---|---|---|---|---|
| Governance gap classification (docs-only vs gov-infra vs functional) | L3 | GOV | `scripts/_governance/governance_gap.py` | R14 — binding gap definitions added to CLAUDE.md |
| Manifest rewrite budget enforcement | L3 | GOV | `scripts/check_manifest_rewrite_budget.py` (W17-B19) | R14 — 4th rewrite requires captain escalation |
| Override schema for rewrite budget | L3 | GOV | `scripts/check_manifest_rewrite_budget.py` — `--override` flag with ledger reference | W17-B19 — budget gate + override documented |
| Smoke-test archive mechanism | L3 | GOV | `docs/delivery/` W17-B13.1 archive smoke artifact | W17-B13 — CI fails on uncommitted test artifacts |

---

## Wave 18 — Vocabulary Debt Clearance + Stable 80 Baseline (2026-04-29)

| Capability | Level | Owner | Evidence | Rule / Class |
|---|---|---|---|---|
| Research-vocabulary clean (C4 closed) | L3 | GOV | `scripts/check_no_research_vocab.py` — 0 violations | C4 — 7 expired allowlist entries cleared; aliases deleted |
| Release identity stable (C3 closed) | L3 | GOV | `scripts/check_manifest_freshness.py`, `check_wave_consistency.py` | C3 — manifest at functional HEAD 58394d6 |
| T3 evidence at functional HEAD | L3 | TE | `docs/delivery/2026-04-29-9ed019c-t3-volces.json` | R8 — 3 Volces real-LLM runs, provenance=real |
| Clean-env evidence at functional HEAD (8707 tests) | L3 | DX | `docs/verification/58394d6-default-offline-clean-env.json` | R8/R16 — portable clean-env, 0 failures |
| Verified readiness baseline 80.0 held | L3 | GOV | `docs/releases/2026-04-28-58394d6.json` | R14 — no regression from W17; C1/C2 deferred to W19 |

---

## Waves 19–22 — Score Lift + Observability + Cross-Tenant (2026-04-29)

| Capability | Level | Owner | Evidence | Rule / Class |
|---|---|---|---|---|
| Gate strictness enforcement (C1 closed) | L3 | GOV | `scripts/check_gate_strictness.py` — all sites fixed | W19 — `continue-on-error: true` on blocking gates resolved |
| Evidence driver observation-based (C2 closed) | L3 | TE | `/ops/drain` + real observation functions | W19 — synthetic/in-process evidence blocked |
| Posture matrix tests (C6 closed) | L3 | RO | `tests/posture/` — 34 Posture.from_env() callsites | W19 — posture matrix delivered |
| Error category hierarchy (C7 closed) | L3 | RO | `hi_agent/server/error_categories.py`; narrowing in app.py/runner.py | W19 — typed exception hierarchy |
| Test fixture cleanup (C5 closed) | L3 | TE | HI_AGENT_ALLOW_HEURISTIC_FALLBACK removed from conftest | W19 — converted to fixture |
| Ledger schema + observability (C11 closed) | L3 | TE | Ledger schema + metric/alert/runbook fields | W19 — delivered |
| Doc truth gate (C10 closed) | L3 | GOV | `scripts/check_doc_truth.py` in release-gate | W19 — W17/18 written response delivered |
| Multistatus gate protocol + 9 gate conversions | L3 | GOV | `scripts/_governance/multistatus_runner.py` — pass=9, fail=0 | W23 Track A — multistatus debt cleared |
| Rule 7 closure on LLM hot path | L3 | TE | `tests/integration/test_http_gateway_rule7_closure.py` (7 tests) | W23 Track B — 3 swallow sites fixed |
| Rule 5 closure on LLM hot path | L3 | RO | `tests/integration/test_http_gateway_loop_stability.py` (7 tests) | W23 Track C — lazy AsyncClient; loop binding fixed |
| Multi-tenant spine phase 1 (9 dataclasses) | L3 | CO | `scripts/check_contract_spine_completeness.py` PASS, 40 files | W23 Track D — tenant_id required under research/prod |
| Content-addressed artifact identity (A-11) | L3 | TE | `tests/integration/test_artifact_content_address.py` (17 tests) | W23 Track E — ArtifactConflictError 409 on hash mismatch |
| Northbound facade phase 1 (3 routes) | L2 | AS-RO | `tests/integration/test_agent_server_routes_phase1.py` (10 tests) | W23 Track F — POST /v1/runs, GET /v1/runs/{id}, POST /v1/runs/{id}/signal |

---

## Wave 23–24 — Agent Server MVP + Memory/Capability L3 Lift (2026-04-30)

| Capability | Level | Owner | Evidence | Rule / Class |
|---|---|---|---|---|
| L1 SQLite compressed memory store | L3 | RO | `hi_agent/memory/l1_store.py`; `tests/integration/test_l1_memory_restart.py` (24 tests) | W24 Track E — wired under research/prod; dev stays in-memory |
| L2 run memory index store | L3 | RO | `hi_agent/memory/l2_store.py`; restart-survival integration test | W24 Track E — tenant_id NOT NULL schema; A-07 closed |
| Per-posture capability matrix | L3 | CO | `tests/unit/test_capability_posture_matrix.py` (16 tests) | W24 Track D — probe_availability_with_posture; shell_exec prod-blocked; A-03 closed |
| Northbound routes phase 2 (5 new routes + idempotency + CLI) | L3 | AS-RO | `tests/integration/test_agent_server_routes_phase2.py` | W24 Track I — 8 routes total; Idempotency-Key middleware; agent-server CLI 4 commands |
| SessionStore tenant scoping (HD-3) | L3 | RO | `tests/integration/test_session_store_tenant_scoping.py` | W24 J3 — get→get_unsafe; get_for_tenant is public API |
| ArtifactRegistry empty-tenant_id filter (HD-4) | L3 | TE | `tests/integration/test_artifact_tenant_filter.py` | W24 J4 — legacy artifacts no longer leak under research/prod |
| Auth-error envelope unified (HD-5) | L3 | AS-RO | `tests/integration/test_agent_server_auth_error_envelope.py` | W24 J5 — {error_category,message,retryable,next_action} |
| Log redaction (HD-6) | L3 | TE | `tests/unit/test_log_redaction.py` | W24 J6 — hash_tenant_id + redact_query; 4 routes_knowledge.py sites |
| Idempotency replay identity strip (HD-7) | L3 | RO | `tests/integration/test_idempotency_replay_strip.py` | W24 J7 — strips request_id/trace_id/_response_timestamp |
| MCP transport fd guard (HD-8) | L3 | TE | `tests/unit/test_mcp_transport_fd_guard.py` | W24 J8 — TransportClosedError; mcp_transport_closed_fd_total Counter |
| EventStore tenant scoping (HD-2) | L3 | RO | `tests/integration/test_event_store_tenant_scoping.py` (7 tests) | W24 J2 — get_events requires tenant_id under research/prod |
| Real observability spine (12/14 layers) | L3 | TE | `docs/verification/d8c7b0b-observability-spine.json` (provenance=real) | W24 Track A — 2 missing taps deferred to W25 |
| Runtime-coupled chaos (8/10 PASS) | L3 | TE | `docs/verification/04f8c91-chaos-runtime.json` (provenance=runtime_partial) | W24 Track B — 2 SKIP require research/prod posture |
| PM2/systemd/Docker operator harness | L2 | DX | `deployment/ecosystem.config.js`, `deployment/Dockerfile`, `docs/operator-runbook.md` | W24 Track F — A-04 closed |
| Operator drill v2 (5 scenarios) | L3 | TE | `docs/verification/d17ec96-operator-drill-v2.json` (5/5 PASS) | W24 Track G — 2 real + 3 simulated_pending_pm2 |

---

## Core Capability Summary (Wave 24 current)

| Dimension | L-Level | Notes |
|---|---|---|
| Execution Engine (TRACE) | L3 | Stable since Wave 10.2; cross-loop stress passing; R5/R8 gates green |
| Memory Infrastructure | L3 | L1CompressedMemoryStore + L2RunMemoryIndexStore SQLite-backed (Track E, W24); tenant_id NOT NULL; restart-survival test; wired under research/prod; dev posture remains in-memory |
| Capability Plugin System | L3-L4 | ExtensionRegistry with enforcement fields; posture-aware enable gate; per-posture matrix wired (Track D, W24); shell_exec prod-blocked observably |
| Knowledge Graph | L3 | SQLite backend default under research/prod (Wave 10.5) |
| Planning / Multi-stage | L2-L3 | TRACE static; dynamic re-planning (P-4) PARTIAL in W25 Track M |
| Artifact / Evidence | L3 | ArtifactLedger durable; provenance fields; tenant-first query; content-addressed identity (W23 Track E) |
| Evolution / Feedback | L2-L3 | ExperimentStore durable; EvolveEngine wired; auto-calibration deferred |
| Cross-Run / Northbound | L3 | 8 northbound routes (3 W23 + 5 W24); idempotency middleware; agent-server CLI; v1 contract freeze deferred to W25 |
| Observability | L3 | 14 fallback counters; real spine 12/14 layers (Track A, W24); chaos 8/10 PASS |
| Governance (gates) | L3 | 35 blocking CI gates; recurrence ledger; release captain protocol |
