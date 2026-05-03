# hi-agent Platform Gaps — Response to Research Roadmap 2026-04-16

**Last updated**: 2026-05-03 (Wave 31 closed; Wave 32 in this PR)
**Source**: research/docs/hi-agent-strategic-roadmap-2026-04-16.md
**Contact**: hi-agent platform team

---

## Overview

hi-agent is the **capability platform layer**. The research team is the **business application layer**. This document formally responds to each platform gap identified in the 2026-04-16 roadmap using downstream's vocabulary.

---

## P-1 through P-7 Gap Status

**Schema note (W31 D-1', refreshed W32-D D.4):** P-1..P-7 below use the **W30-notice taxonomy** (canonical, per
`docs/governance/p-gap-vocabulary.md`). A different P-N taxonomy used in pre-W31 notices
(P-1=Provenance, P-2=Reasoning trace, P-3=Cross-Run Project, P-4=Dynamic re-planning,
P-5=Confidence, P-6=KG inference, P-7=Feedback) is retired — see vocabulary doc for the
mapping. Status fields below remain byte-equal to the W30 delivery notice
(`docs/downstream-responses/2026-05-03-w30-delivery-notice.md` §"Platform Gap Status");
the W31 closure (`2026-05-03-w31-delivery-notice.md`) did not modify P-1..P-7 levels —
W31 deltas (Tenant L3, Functional idempotency L2-L3, Northbound L3, Configurable D OK)
are surfaced under "Readiness Delta" below and in the Capability Matrix, not in this P-N table.

| Gap | hi-agent Status | Latest Action | Target Phase |
|---|---|---|---|
| **P-1** Long-running task | **L3** (per W30 notice) | RunQueue posture-default durable (RO-3); RunStore project_id first-class (CO-4); TeamRunRegistry durable (RO-4); cross-process restart wired through full server boot (W10.4 Class L); RecoveryState enum + decide_recovery_action() at L3 (W10.5). | Phase 2 ✓ |
| **P-2** Multi-agent team | **L2** (per W30 notice) | TeamRunSpec platform contract (CO-7, Wave 9); TeamRunRegistry SQLite-durable (RO-4); status/finished_at spine (W10.2); TeamRun/AgentRole dataclasses; cross-tenant routes_team isolation (W10.5 Class H). | Phase 2 ✓ |
| **P-3** Evolution closed-loop | **L2** (per W30 notice) | ProjectPostmortem + CalibrationSignal + on_project_completed wired (W27 L16); ExperimentStore durable (W10.4); EvolveEngine writes EvolutionExperiment on proposals; ReasoningTrace schema + write hook (TE-5). | Phase 2 ✓ |
| **P-4** StageDirective wiring | **FULL** (per W30 notice — manifest 2026-05-02-aa073e12) | StageDirective(skip_to, insert_stage with target_stage_id) wired in run_linear + run_graph + run_resume with posture-aware fail-closed; 3 spine event kinds (stage_skipped/inserted/replanned). FULL closure recorded against W30 manifest `2026-05-02-aa073e12` (Functional HEAD aa073e129cb0ae9939034eeff29971df3d2b6e33). | Phase 3 ✓ |
| **P-5** KG abstraction | **L2** (per W30 notice) | KnowledgeGraphBackend Protocol + JsonGraphBackend alias (Wave 9); SqliteKnowledgeGraphBackend Protocol-compliant (W10.4 Class R); posture-aware factory (W10.4); cross-tenant routes_knowledge isolation (W10.4). Higher inference (transitive/conflict-detect) deployed as default under research/prod at W10.5 — see Capability Matrix "Knowledge Graph" L3 row. Neo4j permanently declined (see "Permanently Declined" below). | Phase 3 ✓ |
| **P-6** TierRouter | **L3** (per W30 notice) | TierRouter + TierAwareLLMGateway with active calibration (W27 L4); ingest_calibration_signal → routing weight feedback loop; rule-7 WARNING on tier upgrade; 19 unit + 8 integration tests at commit `984d3a2d`. | Phase 3 ✓ |
| **P-7** ResearchProjectSpec | **L0 unchanged** (deferred per RIA W31 directive §6 — calibration quality is post-integration) | ResearchProjectSpec is a research-team workspace model; platform layer offers `TeamRunSpec` as the platform-neutral equivalent (Wave 9 CO-7; L2). Active integration into hi-agent core is **out of capability-layer scope** per Rule 10 + 3-gate intake; calibration deferred per RIA W31 directive §6. | Phase 3 deferred |

---

## Readiness Delta — H1 Baseline through Wave 24

| Dimension | H1 (2026-04-25) | Wave 10 | Wave 12 | Wave 15 | Wave 18 | Wave 23 | Wave 24 | Driver (latest) |
|---|---|---|---|---|---|---|---|---|
| Execution Engine (TRACE) | 84% | 88% | 90% | 90% | 90% | 90% | 90% | Cross-loop stress (R5); gate spine (Wave 10.2) |
| Memory Infrastructure (L0–L3) | 78% | 80% | 82% | 82% | 82% | 82% | **90%** | L1/L2 SQLite persistence + restart-survival (W24 Track E) |
| Capability Plugin System | 75% | 82% | 85% | 87% | 87% | 87% | **92%** | Per-posture matrix wired; shell_exec prod-blocked (W24 Track D) |
| Knowledge Graph | 50% | 72% | 75% | 75% | 75% | 75% | 75% | SQLite backend default (Wave 10.5); unchanged |
| Planning & Re-planning | 40% | 40% | 40% | 40% | 40% | 40% | **50%** | P-4 PARTIAL: StageDirective wired in W25 Track M |
| Artifact / Output Contracts | 50% | 70% | 75% | 78% | 78% | 82% | 82% | Content-addressed identity (W23 Track E); HD-4 tightened (W24) |
| Evolution & Feedback | 35% | 55% | 58% | 60% | 60% | 60% | 60% | ExperimentStore + EvolveEngine wired (Wave 10.4) |
| Cross-Run State (Project) | 22% | 55% | 62% | 65% | 65% | 72% | **85%** | 8 northbound routes + idempotency middleware + CLI (W24 Track I) |
| Ops / Documentation | 65% | 75% | 80% | 82% | 84% | 88% | **92%** | PM2/systemd/Docker harness + operator runbook (W24 Track F) |
| **Overall** | **59%** | **70%** | **74%** | **77%** | **80%** | **94.55%** | **≥95%** | Verified readiness ≥95 at Wave 24 HEAD (W24 manifest target) |

---

## PI-A through PI-E Pattern Support

| Pattern | Description | Status |
|---|---|---|
| PI-A | Multi-stage TRACE pipeline execution | Supported (stable, L3) |
| PI-B | PI-A + reflect_and_infer + restart_policy | Supported (K-7 recursion guard fixed WS-2/3/4) |
| PI-C | PI-B + Human Gate (GatePendingError + continue_from_gate) | Supported (SQLiteGateStore L3 — Wave 10.2) |
| PI-D | PI-B + dispatch_subrun + await_subrun_async | Supported (async path parity confirmed K-2/K-3/K-15) |
| PI-E | PI-C + PI-D (gate + subrun orchestration) | Supported (`tests/integration/test_picd_combination.py` — K-13 closed H2-T6) |

---

## Wave 17–20 New Gap Items

| Gap | Status | Notes |
|---|---|---|
| **C1** Gate strictness erosion — `continue-on-error: true` on blocking gates | **CLOSED (Wave 19)** | W17-A ledger entry resolved; check_gate_strictness.py gate enforced; all sites fixed in W19. |
| **C2** Evidence driver fakery — synthetic/in-process evidence accepted as real | **CLOSED (Wave 19)** | /ops/drain endpoint + real observation functions delivered W19; spine driver observation-based. |
| **C3** Release identity inconsistency | **CLOSED (Wave 18)** | Manifest at functional HEAD 58394d6; head_mismatch resolved; `check_manifest_freshness.py` + `check_wave_consistency.py` blocking |
| **C4** Vocabulary debt — research-domain terms in platform layer | **CLOSED (Wave 18)** | 7 expired allowlist entries cleared; aliases deleted; `check_no_research_vocab.py` 0 violations |
| **C5** Test fixture cleanup — conftest HI_AGENT_ALLOW_HEURISTIC_FALLBACK | **CLOSED (Wave 19)** | Global env var removed from conftest; converted to fixture. |
| **C6** Posture matrix tests | **CLOSED (Wave 19)** | tests/posture/ matrix for 34 Posture.from_env() callsites delivered W19. |
| **C7** Error category hierarchy | **CLOSED (Wave 19)** | error_categories.py typed exception hierarchy; app.py/runner.py narrowing delivered W19. |
| **C8** Observability typed events | **PENDING (Wave 20)** | event_emitter.py + 12 typed events; deferred to W20. |
| **C9** Soak evidence hardening | **PENDING (Wave 20)** | 24h soak + mid-soak SIGTERM; sampler bind to server PID; deferred to W20. |
| **C10** Doc truth gate | **CLOSED (Wave 19)** | check_doc_truth.py in release-gate; W17/18 written response delivered W19. |
| **C11** Ledger schema + observability | **CLOSED (Wave 19)** | Ledger schema + metric/alert/runbook fields delivered W19. |

---

## Permanently Declined

| Ask | Reason |
|---|---|
| P2-2: Neo4j-backed L3 with Cypher (under P-5 KG abstraction) | Permanently declined. SQLite-backed `SqliteKnowledgeGraphBackend` satisfies all required graph operations at our scale. Neo4j adds external service dependency without functional gain. Downstream can implement `KnowledgeGraphBackend` Protocol with Neo4j if needed. |
| P3-2: `TierRouter.calibrate()` (under P-6 TierRouter) | Renamed to `ingest_calibration_signal()` — record-only at W10.4. **Superseded by W27 L4: active calibration shipped — `ingest_calibration_signal` now influences routing weights** (`tests/integration/test_tier_router_ingest_calibration.py`, commit 984d3a2d). |
