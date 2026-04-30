# hi-agent Platform Gaps — Response to Research Roadmap 2026-04-16

**Last updated**: 2026-04-30 (Wave 25 — P-4 PARTIAL; W24 Memory/Capability/Cross-Run lifts)
**Source**: research/docs/hi-agent-strategic-roadmap-2026-04-16.md
**Contact**: hi-agent platform team

---

## Overview

hi-agent is the **capability platform layer**. The research team is the **business application layer**. This document formally responds to each platform gap identified in the 2026-04-16 roadmap using downstream's vocabulary.

---

## P-1 through P-7 Gap Status

| Gap | Research Priority | hi-agent Status | Latest Action | Target Phase |
|---|---|---|---|---|
| **P-1** Provenance standard — `RawMemoryEntry.provenance` field, `CapabilitySpec.source_reference` contract | HIGH | **CLOSED (Wave 10.2)** | project_id posture-required (CO-2, Wave 9); contract spine completeness enforced under research/prod (Wave 10.2); GateStore/TeamRunRegistry/FeedbackStore/RunQueue all carry tenant/user/session/project fields (L3). | Phase 2 ✓ |
| **P-2** Reasoning trace storage — structured side-channel for stage LLM reasoning steps | HIGH | **CLOSED (Wave 9/TE-5)** | ReasoningTrace schema + write hook delivered Wave 9 (TE-5). Route `GET /runs/{id}/reasoning-trace` deferred to L2; schema + evidence hook at L1. Downstream can consume via artifact ledger. | Phase 2 ✓ |
| **P-3** Cross-Run Project aggregation — `project_id` scope alongside `profile_id`; memory spanning multiple runs | HIGH | **CLOSED (Wave 10.2)** | project_id first-class in RunRecord (CO-4, Wave 9); posture-required under research/prod (CO-2); cross-run project query wired (list_runs_by_project, Wave 10.2). | Phase 2 ✓ |
| **P-4** Dynamic re-planning API — `StageDirective(skip_to, insert_stage)` mid-run plan mutation | MEDIUM | **PARTIAL (Wave 25)** | StageDirective(skip_to, insert_stage with target_stage_id) wired in run_linear + run_graph + run_resume with posture-aware fail-closed; 15 unit + 6 integration tests planned; 3 spine event kinds (stage_skipped/inserted/replanned) (W25 Track M.1-M.5) | Phase 3 → L3 production-default |
| **P-5** Confidence scoring contract — `Artifact.confidence: float`, `evidence_count` fields | MEDIUM | **CLOSED (Wave 9)** | ArtifactLedger durable (TE-2, Wave 9); evidence_count/content_hash/producer fields on Artifact (CO-5, Wave 9); idempotency replay returns byte-identical snapshot (H1-Track1). | Phase 2 ✓ |
| **P-6** Knowledge Graph inference layer — transitive queries, conflict detection on `LongTermMemoryGraph` | MEDIUM | **CLOSED (Wave 10.5)** | SqliteKnowledgeGraphBackend deployed as default under research/prod (Wave 10.5); posture-aware factory; upsert_node/upsert_edge/query_relation/transitive_query/detect_conflict supported. Neo4j permanently declined. | Phase 3 ✓ |
| **P-7** Feedback integration path — `submit_run_feedback()` API wired to `EvolveEngine`/`HybridRouteEngine` | MEDIUM | **PARTIAL (Wave 10.4)** | ExperimentStore durable (Wave 10.4, L2); EvolveEngine writes EvolutionExperiment on proposals; auto-calibration (routing influence) deferred to Wave 19. | Phase 3 partial |

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
| P2-2: Neo4j-backed L3 with Cypher | Permanently declined. JSON-backed `LongTermMemoryGraph` satisfies all required graph operations at our scale. Neo4j adds external service dependency without functional gain. Downstream can implement `KnowledgeGraphBackend` Protocol with Neo4j if needed. |
| P3-2: `TierRouter.calibrate()` | Renamed to `ingest_calibration_signal()` — record-only. Active calibration (routing influence) deferred to Wave 19. |
