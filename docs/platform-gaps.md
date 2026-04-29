# hi-agent Platform Gaps — Response to Research Roadmap 2026-04-16

**Last updated**: 2026-04-29 (Wave 18)
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
| **P-4** Dynamic re-planning API — `StageDirective(skip_to, insert_stage)` mid-run plan mutation | MEDIUM | **NOT STARTED** | Deferred Phase 3. TRACE loop currently static; API design needed first. No change through Wave 18. | Phase 3 |
| **P-5** Confidence scoring contract — `Artifact.confidence: float`, `evidence_count` fields | MEDIUM | **CLOSED (Wave 9)** | ArtifactLedger durable (TE-2, Wave 9); evidence_count/content_hash/producer fields on Artifact (CO-5, Wave 9); idempotency replay returns byte-identical snapshot (H1-Track1). | Phase 2 ✓ |
| **P-6** Knowledge Graph inference layer — transitive queries, conflict detection on `LongTermMemoryGraph` | MEDIUM | **CLOSED (Wave 10.5)** | SqliteKnowledgeGraphBackend deployed as default under research/prod (Wave 10.5); posture-aware factory; upsert_node/upsert_edge/query_relation/transitive_query/detect_conflict supported. Neo4j permanently declined. | Phase 3 ✓ |
| **P-7** Feedback integration path — `submit_run_feedback()` API wired to `EvolveEngine`/`HybridRouteEngine` | MEDIUM | **PARTIAL (Wave 10.4)** | ExperimentStore durable (Wave 10.4, L2); EvolveEngine writes EvolutionExperiment on proposals; auto-calibration (routing influence) deferred to Wave 19. | Phase 3 partial |

---

## Readiness Delta — H1 Baseline through Wave 18

| Dimension | H1 (2026-04-25) | Wave 10 | Wave 12 | Wave 15 | Wave 18 | Driver (latest) |
|---|---|---|---|---|---|---|
| Execution Engine (TRACE) | 84% | 88% | 90% | 90% | 90% | Cross-loop stress (R5); gate spine (Wave 10.2) |
| Memory Infrastructure (L0–L3) | 78% | 80% | 82% | 82% | 82% | Durable ledger + tenant-first query (Wave 9/10) |
| Capability Plugin System | 75% | 82% | 85% | 87% | 87% | ExtensionRegistry + enforce fields (Wave 10.5) |
| Knowledge Graph | 50% | 72% | 75% | 75% | 75% | SQLite backend default (Wave 10.5) |
| Planning & Re-planning | 40% | 40% | 40% | 40% | 40% | P-4 deferred; no change |
| Artifact / Output Contracts | 50% | 70% | 75% | 78% | 78% | ArtifactRegistry exec_ctx spine (Wave 10.4/10.5) |
| Evolution & Feedback | 35% | 55% | 58% | 60% | 60% | ExperimentStore + EvolveEngine wired (Wave 10.4) |
| Cross-Run State (Project) | 22% | 55% | 62% | 65% | 65% | project_id required + list_by_project (Wave 10.2) |
| Ops / Documentation | 65% | 75% | 80% | 82% | 84% | 35 CI gates; recurrence ledger; vocab clean (W18) |
| **Overall** | **59%** | **70%** | **74%** | **77%** | **80%** | Verified readiness 80.0 at Wave 18 functional HEAD |

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

## Wave 17–18 New Gap Items

| Gap | Status | Notes |
|---|---|---|
| **C1** Gate strictness erosion — `continue-on-error: true` on blocking gates | **DEFERRED to Wave 19** | W17-A ledger entry; 3 sites remain in release-gate.yml; check_gate_strictness.py gate created in W18-C1 |
| **C2** Evidence driver fakery — synthetic/in-process evidence accepted as real | **DEFERRED to Wave 19** | Requires `/ops/drain` endpoint + real observation functions; C8/C9 spine work prerequisite |
| **C3** Release identity inconsistency | **CLOSED (Wave 18)** | Manifest at functional HEAD 58394d6; head_mismatch resolved; `check_manifest_freshness.py` + `check_wave_consistency.py` blocking |
| **C4** Vocabulary debt — research-domain terms in platform layer | **CLOSED (Wave 18)** | 7 expired allowlist entries cleared; aliases deleted; `check_no_research_vocab.py` 0 violations |
| **C5–C9** Observability spine real coverage | **IN PROGRESS** | Structural provenance only through Wave 18; real spine requires live LLM trace in W19 |

---

## Permanently Declined

| Ask | Reason |
|---|---|
| P2-2: Neo4j-backed L3 with Cypher | Permanently declined. JSON-backed `LongTermMemoryGraph` satisfies all required graph operations at our scale. Neo4j adds external service dependency without functional gain. Downstream can implement `KnowledgeGraphBackend` Protocol with Neo4j if needed. |
| P3-2: `TierRouter.calibrate()` | Renamed to `ingest_calibration_signal()` — record-only. Active calibration (routing influence) deferred to Wave 19. |
