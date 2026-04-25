# Wave 9 Delivery Notice — Owner-Track Hardening

**Date:** 2026-04-25
**HEAD SHA:** f768dc4
**Audience:** Research Intelligence App team + downstream platform consumers
**Authority:** Expert engineering leadership hardening guide (2026-04-25) + H1 post-delivery review

---

## 1. Developer Journey Coverage

The eight developer journeys identified by the leadership team are now supported:

| Journey | Coverage | Evidence |
|---|---|---|
| J1 — Scaffold a research config in < 30 min | **Covered** | `hi-agent init --posture research` writes config dir with profiles, env example, README; `docs/quickstart-research-profile.md` 9-step guide |
| J2 — Doctor check before first run | **Covered** | `hi-agent doctor` under research posture checks HI_AGENT_DATA_DIR, project_id strictness, profile_id strictness, T3 freshness; blocking checks raise errors |
| J3 — Submit a run with project_id | **Covered** | `POST /runs {project_id}` → 400 under research/prod with structured error; 200 + `X-Hi-Agent-Warning` header under dev |
| J4 — Read structured errors and know what to fix | **Covered** | All `/runs` errors include `{error_category, message, retryable, next_action}` (6 categories); catalog in `docs/api-reference.md` |
| J5 — Know which capabilities require approval / are high-risk | **Covered** | `GET /manifest` per-capability views include `risk_class`, `requires_approval`, `provenance_required`, `source_reference_policy`, `reproducibility_level`, `license_policy` |
| J6 — Confirm artifact is not corrupted | **Covered** | ArtifactLedger emits `hi_agent_artifact_corrupt_line_total` counter + writes `.quarantine.jsonl` + WARNING log with line offset |
| J7 — Confirm idempotency works across tenants | **Covered** | Idempotency keyed on authenticated `TenantContext.tenant_id`, not request body; 5 concurrent same-key requests → exactly 1 run created; cross-tenant collision impossible |
| J8 — Understand posture defaults without reading source | **Covered** | `docs/posture-reference.md` defines all three postures, feature matrix, migration checklists dev→research and research→prod |

---

## 2. Contract Maturity Matrix

| Component | Level | Commit | Tests | Posture Coverage |
|---|---|---|---|---|
| TRACE single-run execution | **L2** | RunExecutor + StageOrchestrator + TE-5 reasoning trace schema | test_run_lifecycle*.py | dev ✓ research ✓ |
| Config-driven extensibility | **L2** | HI_AGENT_CONFIG_DIR; JSON profile loader with jsonschema validation (CO-8) | test_config_dir_resolution.py, test_profile_loader_schema.py | dev ✓ research ✓ (fail-closed) |
| Registry-based capability | **L2** | Canonical CapabilityDescriptor (CO-6 closes DF-50); /manifest full surface (DX-4) | test_capability_descriptor_canonical.py | dev ✓ research ✓ |
| Long-running task stability | **L2** | RunQueue posture-default durable (RO-3); TeamRunRegistry durable (RO-4) | test_run_queue_posture_default.py, test_team_run_registry_durability.py | dev ✓ research L2→L3 Wave 10 |
| Project-level cross-run state | **L2** | RunRecord project_id first-class (CO-4); list_runs_by_project query | test_run_store_project_id.py, test_project_id_posture.py | dev warn research 400 |
| Contract Spine Completeness | **L2** | Artifact spine (CO-5); IdempotencyStore auth-scoped (RO-1/2); Artifact tenant-first (TE-3) | test_artifact_spine_fields.py, test_idempotency_auth_scope.py, test_artifact_cross_tenant.py | dev ✓ research ✓ |
| Multi-agent team runtime | **L1** | TeamRunSpec platform contract (CO-7); TeamRunRegistry durable (RO-4) | test_team_run_spec.py, test_team_run_registry_durability.py | dev ✓ research partial |
| Evidence / anti-hallucination | **L2** | ArtifactLedger: corrupt-line quarantine+metric (TE-1); posture-default durable (TE-2); tenant-first (TE-3) | test_artifact_ledger_corruption.py, test_ledger_posture_default.py, test_artifact_cross_tenant.py | dev ✓ research ✓ |
| Observability & Fallback | **L2** | record_fallback() wired to per-kind Prometheus Counters (TE-4): hi_agent_{llm,heuristic,capability,route}_fallback_total | test_fallback_counters.py | dev ✓ research ✓ |
| Error contract | **L2** | Structured error categories (CO-9): {error_category, message, retryable, next_action} | test_run_error_envelope.py | dev ✓ research ✓ |
| Developer Experience (DX) | **L2** | hi-agent init CLI (DX-1); quickstart doc (DX-2); posture-aware doctor (DX-3); full manifest (DX-4); path redaction (DX-5); posture-reference.md (DX-7) | test_cli_init.py, test_doctor_posture_checks.py, test_manifest_full_descriptor_surface.py | dev ✓ research ✓ |
| Ops and release governance | **L2** | Posture enum (CO-1/R11); G1-G4 intake gates; doctor checks (DX-3); T3 CI gate (GOV-4) | test_posture.py, test_doctor_posture_checks.py | dev ✓ research ✓ |

---

## 3. Default Posture Table

| Knob / Behaviour | dev | research | prod |
|---|---|---|---|
| `project_id` missing | 200 + `X-Hi-Agent-Warning` header | 400 `scope_required` | 400 `scope_required` |
| `profile_id` missing | 200 + `X-Hi-Agent-Warning` header | 400 `scope_required` | 400 `scope_required` |
| RunQueue backend | `:memory:` | SQLite file (HI_AGENT_DATA_DIR) | SQLite file (HI_AGENT_DATA_DIR) |
| ArtifactLedger backend | in-memory allowed | file required; startup error if HI_AGENT_DATA_DIR unset | file required |
| TeamRunRegistry backend | in-memory dict | SQLite file | SQLite file |
| Profile jsonschema validation | warn + skip | ValueError (fail-closed) | ValueError (fail-closed) |
| Idempotency scope | body tenant_id (lenient) | authenticated TenantContext.tenant_id | authenticated TenantContext.tenant_id |
| Doctor blocking checks | — | HI_AGENT_DATA_DIR, project_id, profile_id, T3 freshness | same + additional |
| ArtifactLedger corruption | WARNING log only | quarantine file + metric + WARNING | quarantine file + metric + WARNING |

---

## 4. Contract Spine Coverage

Every persistent record carrying `tenant_id` + relevant subset of spine fields:

| Record | tenant_id | project_id | user_id | session_id | run_id | profile_id |
|---|---|---|---|---|---|---|
| `RunRecord` | ✓ | ✓ (CO-4) | — | — | ✓ | ✓ |
| `IdempotencyRecord` | ✓ (auth-scoped RO-1) | ✓ (RO-2) | ✓ (RO-2) | ✓ (RO-2) | ✓ | — |
| `Artifact` | ✓ (CO-5) | — (filter only) | ✓ (CO-5) | ✓ (CO-5) | ✓ | — |
| `GateRecord` | ✓ | — | — | — | ✓ | — |
| `ReasoningTraceEntry` | — | — | — | — | ✓ (TE-5) | — |
| `TeamRunSpec` | — | ✓ (CO-7) | — | — | — | ✓ (CO-7) |

Gap: `ReasoningTraceEntry` and `GateRecord` do not yet carry `tenant_id`. Accepted deferred — these are not cross-tenant query targets in Wave 9.

---

## 5. Durability Evidence

| Component | Dev default | Research/Prod default | Test evidence |
|---|---|---|---|
| RunQueue | `:memory:` | `$HI_AGENT_DATA_DIR/run_queue.sqlite` | `test_run_queue_posture_default.py` |
| TeamRunRegistry | in-memory dict | `$HI_AGENT_DATA_DIR/team_run_registry.sqlite` | `test_team_run_registry_durability.py` |
| ArtifactLedger | in-memory allowed | `$HI_AGENT_DATA_DIR/artifacts/<name>.jsonl` required | `test_ledger_posture_default.py` |
| IdempotencyStore | SQLite (always) | SQLite + auth scope + atomic insert | `test_idempotency_concurrency.py`, `test_idempotency_auth_scope.py` |
| Cross-process restart | xfail (boot wiring pending) | xfail (boot wiring pending) | `test_process_kill_restart.py` (marked `xfail`) |

**Known limitation (Wave 10 pre-work):** The durable RunQueue path is correctly implemented in `run_queue.py` but the server `app.py` boot path does not yet pass the resolved SQLite path through. Cross-process restart tests are honest `xfail`. Resolution targeted Wave 10.

---

## 6. DX Evidence

| Artifact | Location | Status |
|---|---|---|
| Scaffold CLI | `hi-agent init --posture {dev,research,prod}` | Complete — DX-1 |
| 30-min quickstart | `docs/quickstart-research-profile.md` | Complete — DX-2 |
| Doctor posture checks | `hi-agent doctor` under `HI_AGENT_POSTURE=research` | Complete — DX-3 (blocking checks) |
| Full manifest surface | `GET /manifest` per-capability descriptor fields | Complete — DX-4 |
| Path leak fix | `GET /profiles` returns `path_token` not absolute host path | Complete — DX-5 |
| Error catalog | `docs/api-reference.md` "Error Response Format" section | Complete — DX-6 |
| Posture reference | `docs/posture-reference.md` | Complete — DX-7 |
| Capacity documentation | `docs/api-reference.md` "Run Manager Capacity" section | Complete — DX-8 |

---

## 7. Release Evidence

**Test suite:** All tests pass at HEAD f768dc4

Key test counts:
- `tests/unit/test_posture.py`: 32 tests ✓
- `tests/unit/test_run_store_project_id.py`: 7 tests ✓
- `tests/unit/test_artifact_spine_fields.py`: 8 tests ✓
- `tests/unit/test_team_run_spec.py`: 10 tests ✓
- `tests/unit/test_profile_loader_schema.py`: 6 tests ✓
- `tests/contract/test_capability_descriptor_canonical.py`: 8 tests ✓
- `tests/integration/test_project_id_posture.py`: 8 tests ✓
- `tests/integration/test_run_error_envelope.py`: 3 tests ✓
- `tests/integration/test_idempotency_concurrency.py`: ✓
- `tests/integration/test_cross_tenant_isolation.py`: ✓
- `tests/integration/test_fallback_counters.py`: ✓

**Ruff:** `ruff check .` exits 0 at HEAD

**T3 Gate:** Deferred — hot-path files not changed in Wave 9 (posture and contract layers are config/server, not the LLM runtime hot path). T3 inherited from Wave 7 gate at b035213. Wave 9 does not touch `hi_agent/llm/`, `hi_agent/runtime/`, or `hi_agent/runner.py` hot paths.

**Process-kill restart:** xfail at `tests/integration/test_process_kill_restart.py` — durable queue implemented at the component level but not yet wired through `app.py` server boot path. Known limitation, honest xfail, targeted Wave 10.

---

## 8. Decline With Platform Alternative

The following requests from the expert guide are declined with platform alternatives:

| Requested Item | Decision | Platform Alternative |
|---|---|---|
| **Self-evolution gated update + rollback** | Deferred — needs human-approval design | TE-5 provides `ReasoningTrace` schema + write hook as foundation; full gated promotion in Wave 10 |
| **POST /artifacts registration API** | Deferred — now unblocked by CO-5 + TE-3 | `GET /artifacts/by-project/{project_id}` query available; write API Wave 10 P1 |
| **ProjectPostmortem lifecycle integration** | Deferred — now unblocked by TE-2 durable ledger | `ProjectPostmortem` + `CalibrationSignal` dataclasses exist; lifecycle wiring Wave 10 |
| **Budget multi-level enforcement** | Deferred — descriptor fields exist | `TeamRunSpec.budget_policy` + `CapabilityDescriptor` descriptor fields carry budget metadata; runtime enforcement Wave 10 |
| **Knowledge graph durable backend** | Deferred — `JsonGraphBackend` remains L1 | JSON-backed graph covers all platform-layer graph ops at current scale; Wave 10 if downstream demands |
| **ResearchProjectSpec → TeamRunSpec compile** | Research team's responsibility | `TeamRunSpec` (CO-7) is the platform contract; downstream team maps `ResearchProjectSpec` → `TeamRunSpec` as business-layer compile |
| **Temporal as production main path** | Permanently deferred | `SQLiteRunStore` + `SQLiteRunQueue` + `TeamRunRegistry` cover durable-state requirements without additional service dependency |

---

## 9. Readiness Delta (7 Downstream Dimensions)

| Dimension | Before Wave 9 | After Wave 9 | Delta |
|---|---|---|---|
| **Execution** | L2 — runs complete, no posture awareness | L2 — posture-enforced project_id/profile_id, structured errors, DF-51/52 fixed | Hardened contract spine |
| **Memory** | L2 — in-memory default, no tenant first | L2 — ArtifactLedger posture-default durable, tenant-first query, corruption loud | Durability + observability |
| **Capability** | L1 — two divergent CapabilityDescriptor schemas | L2 — canonical CapabilityDescriptor, full /manifest surface, canonical test coverage | DF-50 closed, L1→L2 |
| **Knowledge Graph** | L1 — JsonGraphBackend experimental | L1 — unchanged (Wave 10 candidate) | No change |
| **Planning** | L1 — TeamRunSpec absent | L1 — TeamRunSpec introduced (CO-7), not yet production default | Foundation added |
| **Artifact** | L1 — spine fields absent, silent corruption | L2 — spine fields (CO-5), tenant-first query (TE-3), quarantine+metric (TE-1), posture-durable (TE-2) | L1→L2, four-prong Rule 7 |
| **Evolution** | L1 — CalibrationSignal record-only | L1 — ReasoningTrace schema + write hook (TE-5); deferred route stub | Foundation strengthened |

**Overall platform readiness:** Wave 9 closes the "inside-out" gap. The platform now has a documented developer journey (J1–J8), fail-closed posture defaults under research/prod, a single canonical descriptor schema, and louder signals on every silent-degradation path. Contract L2 is the ceiling for most capabilities; L3 (production default on) is the Wave 10 target for execution and memory.

---

*Delivery notice prepared under GOV-5 by hi-agent platform engineering, 2026-04-25.*
