# Systematic Audit — Wave 35 close (2026-05-05)

**Date:** 2026-05-05
**Predecessor wave:** W34 close (HEAD `77222f8b`, manifest `2026-05-05-77222f8b`, verified=75.0)
**Wave:** W35
**Author:** hi-agent platform team
**Audit dispatch:** 5 parallel reconnaissance agents (A1 spine, A2 posture, A3 stores, A4 lineage, A5 boot-time)
**Triggered by:** RIA W34 acceptance + W35 endorsement directive (`docs/upstream-directives/2026-05-05-hi-agent-wave35-acceptance-and-wave36-expectations.md`)

This document records hidden findings beyond the 8 W35-T items named in the W35 plan. Each section lists the named scope, what audit reconnaissance surfaced, and the disposition (closed in W35 / scoped for W36 / scoped for W37+).

---

## A1 — Spine validation (Rule 12)

**W35-T1 named scope:** 13 contract dataclasses across 6 files in `agent_server/contracts/`.

**Audit found additional 24 hidden sites:**
- `hi_agent/contracts/reasoning_trace.py` (LEGACY) — `ReasoningTraceEntry`, `ReasoningTrace` (2 classes)
- `hi_agent/contracts/requests.py` — 11 classes carrying partial validation only
- `hi_agent/contracts/team_runtime.py::TeamRun`
- `hi_agent/contracts/task.py::TaskContract` — has warning-only `__post_init__`
- `hi_agent/server/idempotency.py::IdempotencyRecord`
- `hi_agent/server/session_store.py::SessionRecord`
- `hi_agent/server/team_event_store.py::TeamEvent`
- `hi_agent/server/tenant_context.py::TenantContext`
- `hi_agent/artifacts/contracts.py::Artifact` (has __post_init__ but only computes content_hash)
- `hi_agent/evolve/contracts.py::EvolveMetrics`, `EvolveResult`
- `hi_agent/evolve/feedback_store.py::RunFeedback`
- `hi_agent/skill/observer.py::SkillObservation` (has truncation-only __post_init__)
- `hi_agent/memory/episodic.py::EpisodeRecord`
- `hi_agent/operations/op_store.py::OpHandle` (has enum-normalize __post_init__)
- `agent_kernel/kernel/contracts.py::HumanGateRequest`, `HumanGateResolution`
- `agent_server/contracts/gate.py::PauseToken`, `ResumeRequest`, `GateEvent` (5 in same module + W35-T1)
- `agent_server/contracts/workspace.py::BlobRef`, `WorkspaceObject`

**Disposition (W35):** ALL 24 hidden sites closed within W35 alongside the named 13. Total 37+ classes acquired posture-aware spine validation. Single batched commit triggered one contract-digest re-snapshot.

---

## A2 — Posture parity (Rule 11)

**W35-T2 named scope:** 8 WEAK_PARITY sites + W35-T3 1 INVERTED site.

**Audit found additional 12 WEAK_PARITY sites + 0 additional INVERTED sites.**

WEAK_PARITY hidden:
- `hi_agent/skill/version.py::SkillVersionRecord.__post_init__` (MEDIUM)
- `hi_agent/skill/registry.py::ManagedSkill.__post_init__` (MEDIUM)
- `hi_agent/skill/observer.py::SkillMetrics.__post_init__` (LOW)
- `hi_agent/skill/evolver.py::SkillAnalysis.__post_init__` (LOW)
- `hi_agent/evolve/skill_extractor.py::SkillCandidate.__post_init__` (MEDIUM)
- `hi_agent/evolve/regression_detector.py::RegressionReport.__post_init__` (LOW)
- `hi_agent/evolve/dataset_evaluator.py::SkillEvalSummary.__post_init__` (LOW)
- `hi_agent/evolve/dataset_evaluator.py::DatasetEvalResult.__post_init__` (LOW)
- `hi_agent/evolve/champion_challenger.py::ComparisonResult.__post_init__` (LOW)
- `hi_agent/evolve/contracts.py::EvolveChange.__post_init__` (MEDIUM)
- `hi_agent/contracts/gate_decision.py::GateDecisionRequest.__post_init__` (HIGH)
- `hi_agent/execution/stage_orchestrator.py::run_graph skip_to handler` (MEDIUM — directive silently swallowed in dev)

**Disposition (W35):** ALL 12 hidden sites closed alongside the named 8. The dominant pattern was a one-line dev-warn else branch addition.

INVERTED hidden: none. The W35-T3 site is the only INVERTED case in production code.

---

## A3 — Unbounded-growth stores (7×24 feasibility — Lens 7)

**W35-T4 named scope:** `IdempotencyStore`.

**Audit found 24 additional stores at risk of unbounded growth.**

Highest-volume risk (W36 carryover, retention plan in `docs/governance/retention-roadmap.md`):
- `SQLiteEventStore` — events per run, biggest volume risk
- `SQLiteRunStore` — 1 row per `POST /runs`
- `agent_kernel sqlite_event_log + sqlite_dedupe_store + sqlite_task_view_log` triplet
- `SqliteDecisionAuditStore`, `SqliteEvidenceStore`
- `SQLiteGateStore` — resolved gates pile up
- `SqliteExperimentStore`, `LongRunningOpStore`, `SessionStore`

In-memory unbounded (RAM-fatal):
- `OpsSnapshotStore` — pure append list
- `EventSummaryStore` — dict keyed by run_id
- `InMemoryDecisionAuditStore`
- `InMemoryKnowledgeStore`

JSON / file append-only:
- `ArtifactLedger` — JSONL append-only (no rotation)
- `SkillRegistry promotion_history` — list per skill grows unbounded
- `FeedbackStore` — JSON file

**Disposition:**
- W35: `IdempotencyStore` closed (T4).
- W36: ALL highest-volume stores acquire retention strategy — see `docs/governance/retention-roadmap.md`.
- W37+: in-memory stores must adopt either eviction or persistence-with-retention; JSONL stores must rotate.

---

## A4 — Lineage population (Rule 12)

**W35-T1 transitive scope:** `RunResponse` / `RunStatus` / `RunStream` schema.

**Audit found 9 hidden sites; 5 HIGH severity:**

1. `agent_server/contracts/run.py::RunResponse, RunStatus` schema gap — only carries `tenant_id` + `run_id`; downstream cannot reconstruct attempt chain. **Closed in W35-T1 spine batch (the `__post_init__` validates what we have; the schema-shape extension is W36 scope.)**

2. `hi_agent/server/app.py::_rehydrate_runs dlq_checked + recovery_decision StoredEvent` omits attempt lineage. **Carryover to W36 — these are recovery system events using `tenant_id="__system__"`.**

3. `hi_agent/server/run_manager.py` re-lease path **never bumps `attempt_id` despite the W34-F.2 design comment promising this** — Rule 15 closure-claim defect. **CLOSED in W35-T9 (this wave) — added `attempt_id` bump in `_rehydrate_runs` re-enqueue path with `parent_run_id` linkage.**

4. `hi_agent/runner_stage.py + hi_agent/contracts/reasoning.py::ReasoningTrace` schema lacks lineage fields. **Carryover to W36 — schema extension.**

5. `agent_server/contracts/run.py::RunStream` SSE event lacks lineage. **Carryover to W36 — schema extension.**

MINOR (4 sites): OpHandle missing `parent_run_id`/`attempt_id`/`phase_id` (MEDIUM); ManagedRun replayed-stub lineage incomplete (MEDIUM); StoredEvent runtime-event default (LOW); event_bus.from RuntimeEvent silent default (LOW). **Carryover to W36.**

---

## A5 — Boot-time implication gaps

**W35-T8 named scope:** `include_mcp_tools=True ⟹ idempotency_facade is not None`.

**Audit found 22 additional boot-time gaps:**

By module:
- `agent_server/api/__init__.py` (build_app) — 6 silent route-omission gaps, 2 of which require idempotency middleware (mcp_tools + skills_memory). **Closed in W35-T8 (this wave) for the 2 idempotency-coupled routes; the 4 silent-omission gaps for events/artifacts/manifest/gates are CARRYOVER (lower severity — silent absence rather than middleware coverage gap).**
- `agent_server/runtime/lifespan.py` — silent failures in lease-expiry / watchdog loops (catch-all → loop continues). **CARRYOVER W36** — needs boot-time assertion that backend.agent_server.run_manager exists before starting loops.
- `agent_server/runtime/kernel_adapter.py` — per-request 503/empty-iter for missing executor_factory, event_store, artifact_registry. **CARRYOVER W36** — boot-time fail-closed under research/prod.
- `agent_kernel/service/http_server.py` — `api_key=None`, `metrics_collector=None`, `facade=Any` accepted with no posture check. **CARRYOVER W36** — production posture must reject these.
- `hi_agent/server/app.py` — feedback_store / memory_manager / retrieval_engine / slo_monitor / session_store all log warnings but mount routes anyway. **CARRYOVER W36** — research/prod posture must fail-closed; routes must NOT be wired without their backing resource.

**Disposition:**
- W35: 1 (named) + extension to skills_memory closed → 2 of 22 closed.
- W36 binding: the 14 highest-severity boot-time gaps will close — see `docs/governance/boot-time-assertions-roadmap.md`.
- W37+: the lower-severity silent-omission gaps in `build_app` for events/artifacts/manifest/gates close.

---

## Summary table

| Audit | Hidden findings | Closed in W35 | W36 carryover | W37+ carryover |
|---|---|---|---|---|
| A1 spine | 24 | 24 | 0 | 0 |
| A2 WEAK_PARITY | 12 | 12 | 0 | 0 |
| A2 INVERTED | 0 | 0 | 0 | 0 |
| A3 unbounded-growth | 24 | 0 | ~14 highest-volume | ~10 lower-volume |
| A4 lineage | 9 (5 HIGH) | 1 (HIGH — re-lease attempt_id bump T9) | 4 HIGH (schema) + 4 MEDIUM/LOW | 0 |
| A5 boot-time | 22 | 1 (skills_memory extension) | ~14 (high severity) | ~7 (silent route omission) |
| **Total** | **91** | **38** | **~32** | **~17** |

**Methodology note (per W31 §B-6 systematic-audit discipline carried to W34/W35):** dispatching parallel reconnaissance agents at wave-close is now the standard. Each wave's audit footprint is recorded here so successor waves can see the audit trail.

---

## References

- W35 plan: `docs/superpowers/plans/2026-05-05-wave-35-systematic-audit-followups.md`
- RIA W35 directive: `docs/upstream-directives/2026-05-05-hi-agent-wave35-acceptance-and-wave36-expectations.md`
- Retention roadmap: `docs/governance/retention-roadmap.md`
- Boot-time assertions roadmap: `docs/governance/boot-time-assertions-roadmap.md`
- W34 systematic audit: TIER 1 patches in commit `0b535f05`
