# Wave 28 Expiry Triage

Generated: 2026-05-02

## Summary

- close-now: 2
- defer-W29: 13
- permanent-with-Rule17: 7

Total logical marker groups: 22 (spanning ~200+ individual inline annotations)

---

## Disposition Key

| Disposition | Meaning |
|---|---|
| close-now | Work is done or permanently resolved; marker can be removed |
| defer-W29 | Work not done; needs W29 entry in recurrence-ledger.yaml + expiry bump |
| permanent-with-Rule17 | Pattern is structurally necessary; convert to permanent allowlist entry under Rule 17 |

---

## Triage Table

### Group 1 — Deprecation Shims: `hi_agent.plugin`, `hi_agent.experiment` re-export shims

| File | Lines | Marker Context | Disposition | Rationale |
|---|---|---|---|---|
| `hi_agent/plugin/__init__.py` | 14, 16 | `expiry_wave: Wave 28` on `from hi_agent.plugins import *` re-export shim | defer-W29 | Shim still present; removal requires auditing all consumers of `hi_agent.plugin`. Target namespace `hi_agent.plugins` exists. No removal was completed in W28. |
| `hi_agent/plugin/manifest.py` | 10, 12 | `expiry_wave: Wave 28` on PluginManifest re-export shim | defer-W29 | Same group as above; shim not removed in W28. |
| `hi_agent/plugin/loader.py` | 10, 12 | `expiry_wave: Wave 28` on PluginLoader re-export shim | defer-W29 | Same group as above. |
| `hi_agent/plugin/lifecycle.py` | 10, 12 | `expiry_wave: Wave 28` on PluginLifecycle re-export shim | defer-W29 | Same group as above. |
| `hi_agent/experiment/__init__.py` | 14 | `expiry_wave: Wave 28` on `from hi_agent.operations import *` shim | defer-W29 | Shim still present; target `hi_agent.operations` exists. Removal requires consumer audit. |
| `hi_agent/experiment/coordinator.py` | 9 | `expiry_wave: Wave 28` on operations.coordinator re-export | defer-W29 | Same experiment→operations shim group. |
| `hi_agent/experiment/provenance.py` | 9 | `expiry_wave: Wave 28` on operations.provenance re-export | defer-W29 | Same experiment→operations shim group. |
| `hi_agent/experiment/poller.py` | 9 | `expiry_wave: Wave 28` on operations.poller re-export | defer-W29 | Same experiment→operations shim group. |
| `hi_agent/experiment/op_store.py` | 9 | `expiry_wave: Wave 28` on operations.op_store re-export | defer-W29 | Same experiment→operations shim group. |
| `hi_agent/experiment/backend/__init__.py` | 9 | `expiry_wave: Wave 28` on operations.backend re-export | defer-W29 | Same experiment→operations shim group. |
| `hi_agent/experiment/backend/local.py` | 10 | `expiry_wave: Wave 28` on operations.backend.local re-export | defer-W29 | Same experiment→operations shim group. |

### Group 2 — Deprecation Shims: `hi_agent.capability.bundles` (ResearchBundle)

| File | Line | Marker Context | Disposition | Rationale |
|---|---|---|---|---|
| `hi_agent/capability/bundles/__init__.py` | 32 | `expiry_wave: Wave 28` in check_layering.py ALLOWLIST (lazy shim for ResearchBundle from examples layer) | defer-W29 | Deprecation warning fires but shim not removed. `examples.bundles.research.ResearchBundle` still referenced. Must audit downstream consumers before removal. |

### Group 3 — Deprecation Shims: `hi_agent.contracts.team_runtime` deprecated fields

| File | Lines | Marker Context | Disposition | Rationale |
|---|---|---|---|---|
| `hi_agent/contracts/team_runtime.py` | 41, 51, 59, 79 | `# Will be removed in Wave 28.` on `hypotheses`, `claims`, `phase_history`, `pi_run_id` fields | defer-W29 | Fields are still present in the dataclass. Removal requires verifying no callers use them (beyond the migration path already in `__post_init__`). No removal commit was made in W28. |

### Group 4 — Deprecation Shims: `hi_agent.evaluation.contracts` citations key

| File | Line | Marker Context | Disposition | Rationale |
|---|---|---|---|---|
| `hi_agent/evaluation/contracts.py` | 91, 96 | `# citations deprecated (Wave 28 removal)` | defer-W29 | The `citations` key is still accepted as a fallback (with a DeprecationWarning) in `DefaultEvaluator.evaluate`. The removal was not executed in W28. |

### Group 5 — Deprecation Warning: `hi_agent.config.json_config_loader` env alias

| File | Line | Marker Context | Disposition | Rationale |
|---|---|---|---|---|
| `hi_agent/config/json_config_loader.py` | 135 | `"alias removal scheduled for Wave 28"` in deprecation warning log message | defer-W29 | Env alias warning message still references Wave 28 removal. Old aliases still accepted. No removal was made in W28. |

### Group 6 — Layering Allowlist: `hi_agent/artifacts/contracts.py` deprecation shim

| File | Line | Marker Context | Disposition | Rationale |
|---|---|---|---|---|
| `scripts/check_layering.py` | 46 | `"expiry_wave": "Wave 28"` — lazy DeprecationWarning shim in artifacts/contracts.py line 193 | defer-W29 | The allowlist entry in check_layering.py expires Wave 28. The underlying shim at `hi_agent/artifacts/contracts.py:193` has not been removed. Needs W29 entry. |

### Group 7 — E2E Test Skeletons: `tests/e2e/test_e2e_trajectory_replay.py`

| File | Lines | Marker Context | Disposition | Rationale |
|---|---|---|---|---|
| `tests/e2e/test_e2e_trajectory_replay.py` | 7, 14, 17, 31, 43, 55 | `expiry_wave: Wave 28` — 4 `@pytest.mark.skip` tests requiring operator-shape (PM2 + real LLM) | defer-W29 | These are legitimate prod_e2e-profile skeletons. The 24h soak / real LLM operator drill (P0-4 in recurrence-ledger) is deferred to W28+, meaning these tests have not been run in operator shape. Bump skip expiry to W29. |

### Group 8 — CI Gate: `release-gate.yml` release-identity advisory step

| File | Line | Marker Context | Disposition | Rationale |
|---|---|---|---|---|
| `.github/workflows/release-gate.yml` | 168 | `# TODO: promote to blocking in W28 once manifest commit is atomic at release HEAD.` | defer-W29 | The W27 `[w27-fix2]` commit added the `release_identity` step with `--allow-docs-only-gap`, annotated with a TODO to promote in W28. The W28 fix commits (w27-fix, w27-gov3) show the HEAD identity flow is not yet atomic enough to remove the `--allow-docs-only-gap` flag. Bump to W29 with a specific action plan: make manifest generation+commit atomic in CI. |

### Group 9 — Rule 7 Exempt: Spine Emitters (contextlib.suppress / except Exception on spine paths)

This is the largest group. All of the following are `rule7-exempt` annotations on spine event emission paths (observability hooks, turn engine, SQLite teardowns, recovery gate hooks, etc.) with `expiry_wave: Wave 28`. The pattern is: "spine emitters must never block the execution path", "SQLite ROLLBACK on error path must not mask original exception", "observability hook must not block turn engine", etc.

| File Group | Count | Marker Pattern | Disposition | Rationale |
|---|---|---|---|---|
| `agent_kernel/runtime/observability_hooks.py` | 19 | `rule7-exempt: expiry_wave="Wave 28"` on contextlib.suppress blocks | permanent-with-Rule17 | The invariant "observability hooks must never block the execution path" is a permanent architectural invariant per Rule 7. No test can replace `contextlib.suppress` here — the exemption is correct indefinitely. Reclassify as permanent Rule 17 entries with `expiry_wave: permanent`. |
| `agent_kernel/kernel/turn_engine.py` | 21 | `rule7-exempt: ... expiry_wave: Wave 28 added: W25 baseline sweep` | permanent-with-Rule17 | Same reasoning: observability hooks on the hot turn-engine dispatch path must not block. This is structural. Permanent allowlist with Rule 17. |
| `agent_kernel/kernel/persistence/sqlite_*.py` (6 files) | ~30 | `rule7-exempt: SQLite ROLLBACK/WAL/close; best-effort teardown` | permanent-with-Rule17 | SQLite teardown (ROLLBACK on error, WAL checkpoint on close, connection close) must never raise on shutdown paths. This is an immutable structural requirement — no future test can make ROLLBACK safe to propagate. Permanent. |
| `hi_agent/observability/spine_events.py` | 11 | `rule7-exempt: spine emitters must never block execution path` | permanent-with-Rule17 | The spine event emission pattern is permanent architecture. Observability must be fire-and-forget. Permanent. |
| `hi_agent/server/routes_runs.py`, `app.py`, `run_manager.py`, `runtime/sync_bridge.py`, `server/tenant_scope_audit.py`, etc. | ~20 | Mixed `rule7-exempt` and `expiry_wave: Wave 28` on server-layer spine emitters | permanent-with-Rule17 | Same pattern as above: spine/recovery/shutdown suppress blocks are permanent per Rule 7.3 ("every silent-degradation path emits a loud, structured signal" but the catch itself is permanent). Reclassify as permanent. |
| `agent_kernel/kernel/recovery/gate.py`, `reasoning_loop.py`, `retry_executor.py` | 5 | `rule7-exempt: observability hook must not block` | permanent-with-Rule17 | Same: observability hooks on hot recovery/inference paths. Permanent. |

### Group 10 — Rule 7 Exempt: Non-spine error handlers (`rule7-exempt: expiry_wave="Wave 28" replacement_test: wave22-tests`)

These are non-spine except clauses that carry both `expiry_wave: Wave 28` AND `replacement_test: wave22-tests`. This indicates they were supposed to be converted to proper error handling by Wave 22 tests that were written, but the exempt status was never lifted.

| File | Lines | Pattern | Disposition | Rationale |
|---|---|---|---|---|
| `hi_agent/ops/diagnostics.py` | 163, 190, 212, 237, 249, 271 | `rule7-exempt: expiry_wave="Wave 28" replacement_test: wave22-tests` | defer-W29 | The wave22 tests were written, but the actual rule7-exempt still catches broadly. Need to confirm the wave22 tests actually assert on the narrow error path and the except can be narrowed. No narrowing was done in W28. |
| `hi_agent/skill/observer.py` | 204 | same pattern | defer-W29 | Same: needs narrowing of broad except. |
| `hi_agent/skill/definition.py` | 87 | `rule7-exempt: expiry_wave="Wave 28" replacement_test: wave22-tests` on except ValueError | defer-W29 | ValueError case can be narrowed. |
| `hi_agent/server/routes_ops.py` | 44 | same | defer-W29 | |
| `hi_agent/server/routes_knowledge.py` | 58, 95 | same | defer-W29 | |
| `hi_agent/server/routes_runs.py` | 123, 133 | same | defer-W29 | |
| `hi_agent/server/auth_middleware.py` | 72, 92 | same (pyjwt/Exception) | defer-W29 | |
| `hi_agent/server/event_store.py` | 158 | same | defer-W29 | |
| `hi_agent/server/routes_tools_mcp.py` | 180 | same | defer-W29 | |
| `hi_agent/security/url_policy.py` | 77 | same | defer-W29 | |
| `hi_agent/runtime_adapter/resilient_kernel_adapter.py` | 220 | same | defer-W29 | |
| `hi_agent/runtime_adapter/kernel_facade_client.py` | 511 | same (ImportError) | defer-W29 | |
| `agent_kernel/kernel/minimal_runtime.py` | 752 | same | defer-W29 | |
| `agent_kernel/runtime/otel_export.py` | 204 | same | defer-W29 | |
| `agent_kernel/runtime/observability_hooks.py` | 87 | same | defer-W29 | |
| `agent_kernel/substrate/temporal/_sdk_source.py` | 95 | same (ImportError) | defer-W29 | |
| `hi_agent/ops/diagnostics.py` | 163–271 | same (6 instances) | defer-W29 | |

### Group 11 — mypy type:ignore suppressions (non-rule7, `expiry_wave: Wave 28`)

These are `# type: ignore[...]  # expiry_wave: Wave 28` annotations. They indicate mypy stub gaps or complex union types where the type annotation should be fixed but was deferred. No rule violation — purely mypy technical debt.

| File Group | Count | Representative | Disposition | Rationale |
|---|---|---|---|---|
| `agent_kernel/runtime/bundle.py` | 10 | Optional-config inline defaults (`... if x is not None else DefaultConfig()`) | defer-W29 | These are Rule 6 violations (inline fallback pattern) that were waived as W25 baseline sweep. The check_rules.py inline-fallback gate should now flag these. They need to be refactored to required constructor args. Not a quick annotation removal. |
| `agent_kernel/kernel/turn_engine.py` (type-ignore only) | 6 | `ctx._dedupe_available`, `ctx._dedupe_outcome`, `ctx._legacy_alias_key` dynamic attrs | defer-W29 | Dynamic attribute attachment to ctx is a latent Rule 6 issue. Needs a typed dataclass field on context. Not trivially removable. |
| `agent_kernel/adapters/facade/kernel_facade.py` | 7 | Literal type narrowing mismatches (run_state, wait_state, review_state) | defer-W29 | Requires fixing the Literal type mismatch between the kernel facade contract and the protocol definition. |
| `hi_agent/server/run_state_transitions.py` | 2 | `run.state` dynamic attribute | defer-W29 | Needs typed attribute on run dataclass. |
| `hi_agent/config/cognition_builder.py` | 4 | `_llm_gateway`, `_tier_router` type mismatches | defer-W29 | Protocol/concrete type mismatch. Requires protocol adjustment. |
| Other scattered type:ignore in hi_agent/ | ~40 | Complex union resolution, attr-defined, arg-type | defer-W29 | Mypy stub gaps. Low urgency but each needs a specific fix plan. |

### Group 12 — check_layering.py `artifacts/contracts.py` deprecated shim

| File | Line | Marker | Disposition | Rationale |
|---|---|---|---|---|
| `scripts/check_layering.py` | 52 | `expiry_wave: Wave 28` for `hi_agent/capability/bundles/__init__.py:32` shim | defer-W29 | Already covered in Group 2. The ALLOWLIST entry in check_layering.py must also be bumped. |

### Group 13 — `tests/integration/test_project_postmortem_lifecycle.py`

| File | Line | Marker | Disposition | Rationale |
|---|---|---|---|---|
| `tests/integration/test_project_postmortem_lifecycle.py` | 30 | `expiry_wave: Wave 28` on local `executor` function (type annotation issue) | close-now | The annotation is on a nested function `def executor(r):` which has no return annotation. This is a trivial type annotation gap — the test runs and passes. The comment was added as a reminder but there is no underlying defect to track. Remove the expiry marker. |

### Group 14 — `agent_server/ARCHITECTURE.md` stub note

| File | Line | Marker | Disposition | Rationale |
|---|---|---|---|---|
| `agent_server/ARCHITECTURE.md` | 40 | `mcp/ — MCP integration hooks (stub, Wave 28+)` | close-now | This is a documentation note about future MCP work. It is not an expiry marker that blocks CI. The `Wave 28+` notation is a roadmap note, not an expiry_wave annotation. No CI gate depends on it. Mark as resolved by updating to `Wave 29+` in a docs-only PR, or simply leaving it as-is since it is not enforced by any gate. Treated as close-now since no CI enforcement applies. |

---

## Recurrence-Ledger Wave 28 Entries

The `docs/governance/recurrence-ledger.yaml` was scanned for `expiry_wave: Wave 28` entries. **None found.** The ledger's `current_wave` field is set to `25` (last updated Wave 25), and all entries use `expiry_or_followup` as a date (e.g. `2026-05-12`, `2026-07-15`), not a wave-numbered expiry. No ledger entries need wave-number bumping.

However, per the task requirements, the following W29-deferred items from the triage above should be added to `recurrence-ledger.yaml` as new entries:

| Proposed Issue ID | Defect Class | From Group | Minimum Fields |
|---|---|---|---|
| W28-A | legacy_shim_removal | Groups 1–2 (plugin/experiment/bundles shims) | expiry_wave: Wave 29, level: deferred |
| W28-B | deprecated_field_removal | Groups 3–5 (team_runtime fields, citations key, env alias) | expiry_wave: Wave 29, level: deferred |
| W28-C | layering_allowlist_burndown | Group 6 (check_layering.py allowlist) | expiry_wave: Wave 29, level: deferred |
| W28-D | prod_e2e_skeleton_activation | Group 7 (E2E trajectory tests) | expiry_wave: Wave 29, level: deferred |
| W28-E | release_identity_atomic_commit | Group 8 (release-gate.yml TODO) | expiry_wave: Wave 29, level: deferred |
| W28-F | rule7_except_narrowing | Group 10 (wave22-tests replacement_test not acted on) | expiry_wave: Wave 29, level: deferred |
| W28-G | mypy_ignore_burndown_bundle_and_context | Group 11 subset (bundle.py Rule-6 inline defaults + turn_engine ctx attrs) | expiry_wave: Wave 29, level: deferred |

---

## Permanent Rule 17 Reclassification Candidates

The following existing inline `expiry_wave: Wave 28` markers should be converted to **permanent** `allowlist` entries in `docs/governance/allowlists.yaml` under Rule 17 (with `expiry_wave: "permanent"`). Each entry needs: `owner`, `risk`, `reason`, `replacement_test`, `added_at`.

| Pattern | Files Affected | Rule 17 Rationale |
|---|---|---|
| `rule7-exempt: spine emitters must never block execution path` (spine_events.py, artifacts/ledger.py, server/*, runtime/sync_bridge.py) | ~12 files, ~20 sites | Observability is architecturally fire-and-forget per Rule 7.3. This invariant never expires. |
| `rule7-exempt: observability hook must not block turn engine` (turn_engine.py, retry_executor.py, recovery/gate.py, reasoning_loop.py, kernel_runtime.py) | ~6 files, ~20 sites | Hot-path invariant: observability must never degrade throughput. Permanent per Rule 7. |
| `rule7-exempt: SQLite ROLLBACK/WAL/connection close; best-effort teardown` (sqlite_pool.py, sqlite_dedupe_store.py, sqlite_colocated_bundle.py, sqlite_task_view_log.py, sqlite_decision_deduper.py, sqlite_recovery_outcome_store.py, sqlite_turn_intent_log.py, kernel health.py) | ~8 files, ~30 sites | Database teardown semantics: propagating ROLLBACK or WAL checkpoint errors on shutdown masks the original exception and corrupts crash diagnostics. Permanent structural requirement. |
| `rule7-exempt: process teardown after kill; wait must not raise` (script_runtime.py, script_runtime_subprocess.py) | 2 files, 3 sites | Process kill/wait semantics: wait() after kill() must be best-effort. Permanent. |
| `rule7-exempt: worker done callback must not block shutdown` (temporal/adaptor.py) | 1 file, 1 site | Shutdown hook invariant. Permanent. |
| `rule7-exempt: worker health check probe; must not block health endpoint` (kernel_runtime.py, health.py) | 2 files, 2 sites | Health endpoint must always respond. Permanent. |
| `rule7-exempt: Temporal dev-server shutdown; best-effort teardown` (temporal/adaptor.py) | 1 file, 1 site | Temporal teardown is best-effort. Permanent. |

---

## CI Gate Impact

The following gates will fail at Wave 28 if expiry markers are not updated before closing the wave:

1. `scripts/check_allowlist_discipline.py` — will fail on any allowlist entry with `expiry_wave: "Wave 28"` once `current_wave > 28`. **No such entries currently exist in `docs/governance/allowlists.yaml`** (all existing entries are `"permanent"`).

2. `scripts/check_layering.py` — has two inline ALLOWLIST entries with `"expiry_wave": "Wave 28"`. This script's internal allowlist is NOT read from `allowlists.yaml`; it is hardcoded in the script. These entries will cause the script to log a warning (and potentially fail) when its own expiry logic runs. Action: bump both entries to `Wave 29` in scripts/check_layering.py.

3. Any CI step that re-runs `scripts/verify_clean_env.py` or `build_release_manifest.py` for the W28 manifest will encounter the inline `expiry_wave: Wave 28` markers on active rule7-exempt and type:ignore sites. The `check_expired_waivers.py` gate (if it scans inline code comments) will fire. **Recommendation**: run `scripts/check_expired_waivers.py` to determine exact failure set before closing W28.

---

## Action Items for W28 Close-Out

| Priority | Action | Owner |
|---|---|---|
| P0 | Update `scripts/check_layering.py` ALLOWLIST entries from `Wave 28` to `Wave 29` | GOV |
| P0 | Add W28-A through W28-G entries to `docs/governance/recurrence-ledger.yaml` | GOV |
| P0 | Add permanent Rule 17 entries to `docs/governance/allowlists.yaml` for all spine/SQLite/observability hook `rule7-exempt` patterns | GOV |
| P1 | Bump `tests/e2e/test_e2e_trajectory_replay.py` skip reason from `Wave 28` to `Wave 29` | TE |
| P1 | Bump inline `expiry_wave: Wave 28` on `release-gate.yml` TODO to `Wave 29` | GOV |
| P2 | Plan and execute removal of `hi_agent.plugin` / `hi_agent.experiment` compat shims (W29 target) | CO |
| P2 | Plan removal of deprecated fields from `TeamSharedContext` and `TeamRun` (W29 target) | CO |
| P3 | Address Rule-6 inline default pattern in `agent_kernel/runtime/bundle.py` (W29 target) | RO |
