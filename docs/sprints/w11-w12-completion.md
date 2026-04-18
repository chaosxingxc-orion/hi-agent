# W11–W12 Sprint Retro — Operational Hardening

**Sprint**: 2026-04-18 (same-day delivery, sequential after W10)  
**Goal**: Release gate hard gates, runbooks, migration guide, `config/builder.py` + `runner.py` surgical cleanup, sprint retrospectives.  
**Declared**: Operational Hardening complete ✅

---

## Ticket Tracker

| Ticket | Description | Status | Notes |
|--------|-------------|--------|-------|
| HI-W11-002 | `config/builder.py` + `runner.py` surgical cleanup (staged mutations eliminated) | ✅ Delivered | Modified files tracked in branch |
| HI-W12-001 | `ServerBuilder` + `GateCoordinator` unit tests | ✅ Delivered | `tests/unit/test_server_builder.py`, `tests/unit/test_gate_coordinator.py` |
| HI-W12-002 | Release gate `prod_e2e_recent` hard gate | ✅ Delivered | `hi_agent/ops/release_gate.py`, `tests/integration/test_release_gate_prod_hard_gate.py` |
| HI-W12-003 | Runbooks + migration guide docs | ✅ Delivered | `docs/runbook/`, `docs/migration/contract-changes-2026-04-17.md` |
| HI-W12-004 | Sprint retrospectives (W10, W11–W12) | ✅ Delivered | `docs/sprints/w10-m2-completion.md`, `docs/sprints/w11-w12-completion.md` |

---

## Exit Criteria

| Check | Result |
|-------|--------|
| `prod_e2e_recent` gate implemented and tested | ✅ 10/10 tests pass |
| Release gate no longer has stub "no nightly yet" | ✅ Gate 7 is now a live hard gate |
| Runbook files created with real content | ✅ 5 runbook files |
| Migration guide sent to downstream | ✅ `docs/migration/contract-changes-2026-04-17.md` |
| Sprint retros created | ✅ W10 + W11–W12 |
| `tests/unit/test_server_builder.py` present | ✅ |
| `tests/unit/test_gate_coordinator.py` present | ✅ |
| pytest green on new integration test file | ✅ |

---

## Key Technical Decisions

### 1. ProdE2EResult as a separate dataclass (not reusing GateResult)

The existing `GateResult` dataclass uses `name/status/evidence` semantics matching the release gate report format. The `prod_e2e_recent` check needed richer return semantics (`passed: bool`, `reason: str`, `details: dict`) for composability — downstream callers can check `result.passed` without parsing status strings. This motivated `ProdE2EResult` as a separate dataclass, keeping `GateResult` unchanged.

### 2. Episodic store scan — runtime_mode at top level or nested under execution_provenance

Episodes may record `runtime_mode` either at the top-level JSON key (simple writers) or nested under `execution_provenance.runtime_mode` (W1+ writers using the full provenance struct). The gate checks both locations, which makes it compatible with episodes written by both old and new code paths without requiring a migration.

### 3. Hard gate replaces stub — no env var escape hatch

The previous stub (`GateResult("prod_e2e_recent", "skipped", "no nightly yet")`) was replaced with a hard `fail` when no recent prod run exists. There is no env var to bypass this gate — the intent is to force a real prod-real execution before every production deployment, making this a genuine pre-deployment quality signal rather than a checkbox.

### 4. Runbooks cover the full ops surface

Five runbook files were created covering: deployment (`deploy.md`), operational verification (`verify.md`), rollback (`rollback.md`), MCP crash incident (`incident-mcp-crash.md`), and evolve mutation incident (`incident-evolve-unexpected-mutation.md`). Each runbook contains actionable commands and decision tables, not just headings.

### 5. Contract change notice formalizes downstream obligations

The `docs/migration/contract-changes-2026-04-17.md` notice explicitly separates additive changes (safe to ignore) from the single breaking change (RBAC on mutation routes in prod-real). This distinction is important: the Research Intelligence App team can deploy their consumer without changes, but must update their prod integration to include an approver JWT for promote/evolve/consolidate calls.

---

## W12-002 Test Coverage

`tests/integration/test_release_gate_prod_hard_gate.py` covers 10 scenarios:

| Test | Scenario |
|------|----------|
| `test_gate_passes_when_recent_prod_run_exists` | Happy path — prod run 2h old |
| `test_gate_fails_when_no_prod_run_exists` | Empty episodic store |
| `test_gate_fails_when_only_non_prod_runs_exist` | dev-smoke + local-real only |
| `test_gate_fails_when_prod_run_too_old` | prod run 30h old, 24h window |
| `test_gate_passes_with_custom_max_age` | 10h run: fails 8h window, passes 12h window |
| `test_gate_result_has_required_fields` | `ProdE2EResult` dataclass shape |
| `test_gate_fails_when_episodic_dir_missing` | Directory does not exist |
| `test_gate_picks_most_recent_prod_run` | 40h + 1h runs: gate selects 1h |
| `test_gate_uses_execution_provenance_runtime_mode` | Nested `execution_provenance.runtime_mode` |
| `test_gate_skips_malformed_episode_files` | Bad JSON silently skipped |

---

## Not Completed

- None — all W11–W12 tickets delivered.

## Deferred to W13+

- Full ruff cleanup pass on new-file style errors (I001, D101, UP037, E501) introduced across W7–W12
- `AsyncRunResult.execution_provenance` — deferred from W1, still pending
- `SystemBuilder` final LOC target ≤ 900 — current ~1050; further decomposition deferred
- Nightly automated prod-real smoke run setup — gate currently requires manual prod run; CI nightly job is the long-term solution

---

## Blockers Encountered

- None. `check_prod_e2e_recent` required careful handling of the `utcnow()` deprecation warning (Python 3.14) — kept `utcnow()` for consistency with the rest of the codebase rather than introducing a mixed timezone-aware/naive comparison.

---

## Sprint Series Summary (W1 → W12)

| Sprint | Milestone | Key Deliverable |
|--------|-----------|-----------------|
| W1 | Runtime Truth MVP | `execution_provenance`, `/manifest` tri-state, RBAC skeleton |
| W2 | M1 Runtime Truth | Full provenance fields; snapshot tests locked |
| W3 | Operable Basics | Doctor, diagnostics, release gate scaffold |
| W4 | Capability Governance | Dangerous capability RBAC, PermissionGate |
| W5 | MCP Dynamic Discovery | MCPHealth, transport_status, schema drift |
| W6 | SystemBuilder Split | ReadinessProbe, SkillBuilder, MemoryBuilder extracted |
| W7 | RunExecutor Characterization | KnowledgeBuilder, RetrievalBuilder, RunFinalizer extracted; 12 characterization tests |
| W8 | Decomposition Continues | ServerBuilder, GateCoordinator, CapabilityPlaneBuilder |
| W9 | RunExecutor Decomposition | ActionDispatcher, RecoveryCoordinator |
| W10 | **M2: Composable Runtime** | StageOrchestrator, CognitionBuilder, RuntimeBuilder; last post-construction mutations eliminated |
| W11 | Config/Runner Cleanup | `builder.py` + `runner.py` staged mutations removed; unit test stubs filled |
| W12 | **Operational Hardening** | `prod_e2e_recent` hard gate; 5 runbooks; migration guide; retros |
