# Wave 34 Delivery Notice

**Date:** 2026-05-05
**Wave:** 34
**Status:** SHIP
**Manifest:** `2026-05-05-3de2ba4b` (built at HEAD `3de2ba4b`)
**Functional HEAD:** `3de2ba4b` (per Rule 14 §4.4: closure notice cites the manifest's release_head)
**RIA directive:** `docs/upstream-directives/hi-agent-wave34-engineering-expectations-2026-05-04.md` (M1, 2026-05-04)
**Predecessor:** Wave 33 delivery notice `docs/downstream-responses/2026-05-04-w33-delivery-notice.md` (manifest `2026-05-03-ce9330fa`, verified=75.0)

> **Cross-wave context:** Wave 34 closes the seven RIA-flagged BLOCKERs (B-W34-1 through B-W34-7) plus the four governance items (W34-NAMING-CLOSE, W34-CONFIG-ENV-AUDIT, W34-T-FOLLOWUP, W34-LINUX-SOAK-ROADMAP). All twelve acceptance IDs are CLOSED. The W31 §B-5 follow-through audit (B-W34-4) is published in `docs/governance/registry-tenant-scoping-audit-2026-05-04.md`. No score-cap change is requested per RIA §6.

---

## Verified Readiness

| Tier | Score | Cap factors |
|---|---|---|
| `raw_implementation_maturity` | 94.5 | — |
| `current_verified_readiness` | **75.0** | identical to W33; RIA acceptance §3 cap holds (`soak_evidence_not_real`, `evidence_provenance`) |
| `seven_by_24_operational_readiness` | 90.0 | architectural_seven_by_twenty_four 5/5 PASS |
| `conditional_readiness_after_blockers` | 75.0 | identical to verified |

**Honest read.** Per RIA §6 the W34 directive does not request a score-cap change; the 75.0 cap continues to be governed by the same two cap factors as W33. W34 deepens architectural coverage (lineage spine, tenant partition, contract surface, idempotency contract, concurrency baseline) but does not unlock a new tier — that requires retiring the soak_evidence cap, which is W36+ work per RIA §2.7.

---

## Wave 34 Closure Evidence (per RIA §8 reporting format)

| Acceptance ID | Status | Evidence path | Provenance |
|---|---|---|---|
| W34-F.2 (B-W34-1: lineage population) | PASS | `tests/unit/test_run_execution_context_lineage_population.py` (9 tests) + `scripts/check_lineage_population.py` exit 0 + `hi_agent/context/run_execution_context.py` populated `from_managed_run` + `hi_agent/server/run_manager.py::create_run` mints `attempt_id`, threads `parent_run_id` / `attempt_id` / `phase_id` to `RunRecord` | measured |
| W34-F.3 (B-W34-2: ReasoningTrace spine validation) | PASS | `tests/unit/test_reasoning_trace_spine_validation.py` (10 tests; research/dev posture coverage) + `scripts/check_dataclass_spine_validation.py` exit 0 + `hi_agent/contracts/reasoning.py::ReasoningTrace.__post_init__` raises `SpineCompletenessError` under research/prod | measured |
| W34-F.4 (B-W34-3: KnowledgeWiki tenant partition) | PASS | `tests/integration/test_knowledge_wiki_tenant_partition.py` (30 tests; 6 cross-tenant cases × 3 postures + 6 posture-behaviour + 2 persistence) + `scripts/check_no_unscoped_knowledge_reads.py` exit 0 + `hi_agent/knowledge/wiki.py` per-tenant directory layout (`<wiki_dir>/<tenant_id>/<page_id>.json`) + `WikiPage.tenant_id` spine field with posture-aware `__post_init__` | measured |
| W34-T-FOLLOWUP (B-W34-4: 4-registry status audit) | PASS | `docs/governance/registry-tenant-scoping-audit-2026-05-04.md` (per-registry table for KnowledgeWiki / KG / Skill / Tool / Capability + RunQueue confirmation row); SkillRegistry schema-layer remains W35 carryover per existing xfail expiry_wave="Wave 35" | derived |
| W34-MANIFEST (B-W34-5: posture field) | PASS | `agent_server/contracts/manifest.py::ManifestResponse` declares frozen `posture: PostureLiteral` + `tests/integration/test_manifest_posture_field_present.py` (4 tests) + contract digest re-snapshot to `cc55145f` (V1_FROZEN_HEAD) — RIA R-RIA-6 binding | measured |
| W34-IDEMPOTENCY (B-W34-6: cross-process replay) | PASS | `agent_server/contracts/idempotency.py` documents Cache Scope / Cross-Process Replay / TTL / Body-Mismatch + `tests/integration/test_idempotency_cross_process_replay.py` (POSIX-only; skipped on Windows with documented reason) + `scripts/check_idempotency_contract_documented.py` exit 0 + `DEFAULT_TTL_SECONDS=86400.0` exported | measured |
| W34-CONCURRENCY-METHOD (B-W34-7: methodology) | PASS | `docs/perf/concurrency-methodology-v1.md` (workload, measurements, hardware target, output schema, equivalence scope, limitations, proposed W35 regression budget) | derived |
| W34-CONCURRENCY-BASELINE (B-W34-7: baseline) | PASS | `docs/verification/c7d1054e-concurrency-N50M5.json` provenance:real (P50=77.5ms, P95=200.4ms, P99=216.2ms, 50/50, fairness=1.44) + `docs/verification/c7d1054e-concurrency-N10M1.json` (P50=28.0ms, P95=51.8ms, 10/10, fairness=1.00) + `scripts/check_concurrency_evidence.py` exit 0 | real |
| W34-CONCURRENCY-EQUIV (B-W34-7: persistence equivalence) | PASS | `tests/integration/test_concurrency_persistence_swap.py` 1 PASS (SQLite leg) + 1 SKIP (PostgreSQL leg gated on `HI_AGENT_TEST_POSTGRES_DSN`); SQLite leg asserts deterministic terminal-state distribution at N=10 M=1 | measured |
| W34-NAMING-CLOSE (H-3' / H-13' / H-14') | PASS | `docs/governance/package-consolidation-2026-05-04.md` per-item disposition (H-3': close, deletion of `hi_agent/experiment/`; H-13': formal decline with import-site asymmetry rationale; H-14': close as no-op) + Rule 15 three-part closure table | measured/derived |
| W34-CONFIG-ENV-AUDIT | PASS | `docs/governance/env-var-audit-2026-05-04.md` (35 unique vars × 64 read sites classified) + `scripts/check_env_var_routing.py` enforces 4 most-policy-sensitive vars (HI_AGENT_POSTURE / HI_AGENT_LLM_MODE / HI_AGENT_JWT_SECRET / AGENT_SERVER_BACKEND); zero direct-read defects at HEAD | measured |
| W34-LINUX-SOAK-ROADMAP | NOTED | One paragraph below in §"Linux-runner soak roadmap" | advisory |
| Real T3 (Volces) at HEAD | PASS | `docs/delivery/2026-05-05-8d75aff5-t3-volces.json` provenance:real, 3/3 PASS, llm_fallback_count=0 (Rule 8 step 3) | real |
| arch-7×24 fresh evidence | PASS | `docs/verification/8556243-arch-7x24.json` 5/5 PASS | measured |
| Clean-env fresh evidence | PASS | `docs/verification/85562438-default-offline-clean-env.json` 9275 passed / 8 skipped / 0 failed | measured |

---

## Architectural-Positioning Rationale

Per our positioning ("northbound functional idempotency, performance stability, extensibility, evolvability, configurable development, sustainable evolution") aligned with RIA's 8 lenses, W34 closes:

- **L1 Tenant isolation:** B-W34-3 (KnowledgeWiki schema partition), B-W34-4 (4-registry status audit publishes the structural state of every registry RIA depends on).
- **L2 Functional idempotency:** B-W34-6 (cross-process replay test + frozen contract — exactly the "northbound functional idempotency" property our positioning names).
- **L3 High reliability:** B-W34-1 (lineage chain reconstructible across recovery), B-W34-2 (spine validation closes silent-empty fallback).
- **L4 High concurrency:** B-W34-7 (first measured baseline + methodology + persistence equivalence).
- **L5 Configurable development:** W34-CONFIG-ENV-AUDIT (35-variable inventory + per-var canonical-reader enforcement on the four most policy-sensitive vars).
- **L6 Continuous intelligence evolution:** B-W34-1 + B-W34-2 transitively close the postmortem-reconstruction gap (cross-attempt lineage now persists with non-empty fields).
- **L8 Agent service to upper systems:** B-W34-5 (manifest `posture` field is the binding contract surface for RIA R-RIA-6 startup compatibility check).

---

## Three-Part Defect Closure (Rule 15)

### W34-F.2 (B-W34-1)

(a) **Code fix:** commit `8978f0eb`. `hi_agent/context/run_execution_context.py:71-104` `from_managed_run` reads lineage from the live `ManagedRun` spine; `hi_agent/server/run_manager.py:496-540` `create_run` mints fresh `attempt_id` (uuid4) and threads it through `ManagedRun` + `RunExecutionContext` + `RunRecord`. New helpers `with_attempt`, `with_phase`, `to_lineage_kwargs`.
(b) **Recurrence-prevention check:** `scripts/check_lineage_population.py` AST-walks every `RunExecutionContext(...)` direct construction site under `hi_agent/` + `agent_server/`; fails on hardcoded empty-string lineage values (root-runs annotated `# scope: root-run` exempt for `parent_run_id` only).
(c) **Process change:** Track A entry in `docs/superpowers/plans/2026-05-04-wave-34-ria-engineering-expectations.md` §2; `RunExecutionContext` 12-field shape pinned by `tests/unit/test_run_execution_context_pilot.py::test_returns_all_twelve_fields`.

**Closure level (Rule 15):** `verified_at_release_head`.

### W34-F.3 (B-W34-2)

(a) **Code fix:** commit `8978f0eb`. `hi_agent/contracts/reasoning.py:55-110` adds `SpineCompletenessError(ValueError)` and `ReasoningTrace.__post_init__` raising under research/prod posture on missing `tenant_id` / `run_id` / `stage_id`; warning under dev posture.
(b) **Recurrence-prevention check:** `scripts/check_dataclass_spine_validation.py` walks `REQUIRED_VALIDATION_TARGETS` (currently `[(reasoning.py, ReasoningTrace)]`) and asserts `__post_init__` references `Posture` + spine fields + `raise`. New spine-bearing dataclasses must be added to the target list as they land.
(c) **Process change:** spine-completeness pattern documented in this notice; future Rule 12 spine-bearing dataclasses must follow the same `__post_init__` shape.

**Closure level (Rule 15):** `verified_at_release_head`.

### W34-F.4 (B-W34-3)

(a) **Code fix:** commits `68fc5ed7` + `5809e422`. `hi_agent/knowledge/wiki.py:55-90` adds `WikiPage.tenant_id` with posture-aware `__post_init__`; `KnowledgeWiki` switches to per-tenant directory layout (`<root>/<tenant>/<page_id>.json`); reads/writes require `tenant_id` kwarg (research/prod fail-closed; dev warn + default-tenant fallback for back-compat). Five production call sites updated (`knowledge_manager.py`, `graph_renderer.py`, `retrieval_engine.py`, `routes_knowledge.py`).
(b) **Recurrence-prevention check:** `scripts/check_no_unscoped_knowledge_reads.py` AST-walks every `KnowledgeWiki(...).get_page/list_pages/search/...` call site under `hi_agent/` + `agent_server/` and fails when `tenant_id=` is missing (allowlist: `wiki.py` itself + tests).
(c) **Process change:** `hi_agent/knowledge/ARCHITECTURE.md` §8 documents the W34-F.4 partition + posture rules + gate; Rule 11 / Rule 12 examples updated.

**Closure level (Rule 15):** `verified_at_release_head`.

### W34-T-FOLLOWUP (B-W34-4)

(a) **Code action:** None required at HEAD — the audit is the deliverable. No registry's status changed in W34 except `KnowledgeWiki` (closed via W34-F.4) and the W11-shimmed `hi_agent.experiment` (deleted via W34-F).
(b) **Recurrence-prevention check:** the audit document includes the four-registry status table; future waves with new registries must extend it.
(c) **Process change:** `docs/governance/registry-tenant-scoping-audit-2026-05-04.md` is the binding audit; SkillRegistry schema-layer enforcement is W35 carryover (existing xfail expiry_wave="Wave 35").

**Closure level (Rule 15):** `verified_at_release_head`.

### W34-MANIFEST (B-W34-5)

(a) **Code fix:** commit `7c938386`. `agent_server/contracts/manifest.py::ManifestResponse` (new file, frozen dataclass, `posture: PostureLiteral`); `agent_server/facade/manifest_facade.py` adds `posture_resolver` constructor kwarg + injects resolved posture into both response paths.
(b) **Recurrence-prevention check:** contract digest re-snapshot to `cc55145f` (`V1_FROZEN_HEAD`); `scripts/check_contract_freeze.py --enforce` blocks future undocumented mutations of `manifest.py`. `tests/integration/test_manifest_posture_field_present.py` pins the field shape across all three postures.
(c) **Process change:** RIA R-RIA-6 named in the contract module docstring as the binding consumer.

**Closure level (Rule 15):** `verified_at_release_head`.

### W34-IDEMPOTENCY (B-W34-6)

(a) **Code fix:** commit `97dde650`. `agent_server/contracts/idempotency.py` documents Cache Scope / Cross-Process Replay / TTL / Body-Mismatch with module constants (`DEFAULT_TTL_SECONDS=86400.0`, `SCOPE='tenant'`).
(b) **Recurrence-prevention check:** `scripts/check_idempotency_contract_documented.py` asserts the docstring carries the four required sub-headers and `DEFAULT_TTL_SECONDS` is positive. `tests/integration/test_idempotency_cross_process_replay.py` (POSIX runner) drives subprocess restart + replay end-to-end.
(c) **Process change:** the contract module is the authoritative spec for downstream `platform_client/idempotency.py`; future contract changes go through R-AS-3 freeze re-snapshot.

**Closure level (Rule 15):** `verified_at_release_head`.

### W34-CONCURRENCY-* (B-W34-7)

(a) **Code action:** commit `e122f2fd`. `docs/perf/concurrency-methodology-v1.md` published; `scripts/run_concurrency_baseline.py` harness; first baselines at HEAD `c7d1054e` (N=50/M=5 and N=10/M=1) with `provenance:real`; `tests/integration/test_concurrency_persistence_swap.py` SQLite-leg pass.
(b) **Recurrence-prevention check:** `scripts/check_concurrency_evidence.py` asserts at least one valid `docs/verification/<head>-concurrency-*.json` exists with schema + provenance + positive p95.
(c) **Process change:** v1 methodology pinned; W35 regression budget proposal in §9 of the methodology document; N=100 raise tracked as W35 carryover.

**Closure level (Rule 15):** `verified_at_release_head`.

### W34-NAMING-CLOSE

(a) **Code action:** commits `d694541e` (H-3' deletion) + `cc55145f` (closure document). H-3': `hi_agent/experiment/` package + 7 files deleted; `tests/unit/test_operations_module_canonical.py` flipped to assert `ModuleNotFoundError`. H-13': formal decline with import-site asymmetry table. H-14': close as no-op (already consolidated).
(b) **Recurrence-prevention check:** `docs/governance/package-consolidation-2026-05-04.md` is the binding decision; future naming concerns reopen the document with a new dated section.
(c) **Process change:** "RIA discretion" deferral pattern retired — every naming-hygiene item must close-or-formally-decline within the receiving wave per RIA §4.

**Closure level (Rule 15):** `verified_at_release_head` (close items) / `documented` (decline items).

### W34-CONFIG-ENV-AUDIT

(a) **Code action:** commit `c7d1054e`. No defects found at HEAD — the audit confirms the W33-E.1 closure remains intact and no other policy-sensitive variable has unrouted call sites. Audit deliverable + new gate.
(b) **Recurrence-prevention check:** `scripts/check_env_var_routing.py` per-variable allowlist enforcement for HI_AGENT_POSTURE / HI_AGENT_LLM_MODE / HI_AGENT_JWT_SECRET / AGENT_SERVER_BACKEND.
(c) **Process change:** `docs/governance/env-var-audit-2026-05-04.md` is the binding audit; future env-var additions extend the inventory.

**Closure level (Rule 15):** `verified_at_release_head`.

---

## Linux-runner soak roadmap (W34-LINUX-SOAK-ROADMAP, advisory)

Per RIA §2.7 advisory ask. The two OS-limited chaos scenarios that currently skip on Windows are (1) `signal_storm` (POSIX SIGUSR1/SIGUSR2 multiplexing) and (2) `fd_exhaustion_recovery` (POSIX rlimit nofile manipulation). Both are runtime-coupled via the existing `arch-7x24` `chaos_runtime_coupled_all` assertion (provenance=`runtime_partial`).

**Roadmap entry:** Linux-runner soak with the 2 OS-limited scenarios is targeted for **W36** alongside the proposed retirement of the `soak_evidence_not_real` cap. The soak duration will be **6h** (chosen to be long enough to surface lease/recovery interaction but short enough to fit a single CI matrix shard); workload will be the same `N=50, M=5` shape as the W34 concurrency baseline, with chaos injection on a 30s cadence. The soak will run on `ubuntu-latest` (4 vCPU, 16 GB RAM) so the methodology and hardware target match `docs/perf/concurrency-methodology-v1.md`.

This roadmap entry is a planning input; W34 closure is independent of its delivery.

---

## W31 §B-5 follow-through (B-W34-4 audit summary)

Full table at `docs/governance/registry-tenant-scoping-audit-2026-05-04.md`. Headline:

| Registry | At HEAD | Disposition |
|---|---|---|
| KnowledgeWiki | CLOSED W34-F.4 | schema-layer per-tenant directory partition |
| KnowledgeGraph (`SqliteKnowledgeGraphBackend`) | CLOSED | tenant_id NOT NULL + PK includes tenant_id (pre-W34) |
| SkillRegistry | API-LAYER CLOSED, schema-layer W35 | xfail expiry_wave="Wave 35" |
| Tool registry | TENANT-AGNOSTIC by design | per-tenant policy lives above this layer |
| CapabilityRegistry | TENANT-AGNOSTIC by design (W31 T-6') | metadata is platform-wide |
| RunQueue (W33-D.2) | CLOSED | 9 methods × 28 tests |

RIA can rely on API-layer scoping for SkillRegistry through W34; W35 closes the schema-layer gap.

---

## Out-of-scope per RIA §7

- v1 contract routes beyond manifest posture: not requested in W34.
- `evidence_provenance` cap factor (W27 historicals + W28 erratum): unchanged; remains as-is.
- Platform v2 contract work: hi-agent planning, not RIA request.
- Linux-runner extension of the 2 OS-limited chaos scenarios: noted in roadmap above; advisory.

---

## Cross-references

- RIA directive: `docs/upstream-directives/hi-agent-wave34-engineering-expectations-2026-05-04.md`
- W34 plan: `docs/superpowers/plans/2026-05-04-wave-34-ria-engineering-expectations.md`
- Manifest: `docs/releases/platform-release-manifest-2026-05-05-3de2ba4b.json`
- Signoff: `docs/releases/wave34-signoff.json`
- Audit docs: `docs/governance/registry-tenant-scoping-audit-2026-05-04.md`, `docs/governance/env-var-audit-2026-05-04.md`, `docs/governance/package-consolidation-2026-05-04.md`
- Methodology: `docs/perf/concurrency-methodology-v1.md`
- Predecessor: `docs/downstream-responses/2026-05-04-w33-delivery-notice.md`

---

**Signed:** hi-agent platform team
**Audit head:** docs match hi-agent main at 2026-05-05, manifest release_head `3de2ba4b`
