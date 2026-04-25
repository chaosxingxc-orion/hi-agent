# hi-agent Platform Gaps — Response to Research Roadmap 2026-04-16

**Last updated**: 2026-04-25 (Wave 8 → H1 Hardening)
**Source**: research/docs/hi-agent-strategic-roadmap-2026-04-16.md
**Contact**: hi-agent platform team

---

## Overview

hi-agent is the **capability platform layer**. The research team is the **business application layer**. This document formally responds to each platform gap identified in the 2026-04-16 roadmap using downstream's vocabulary.

---

## P-1 through P-7 Gap Status

| Gap | Research Priority | hi-agent Status | Wave 8 Action | Target Phase |
|---|---|---|---|---|
| **P-1** Provenance standard — `RawMemoryEntry.provenance` field, `CapabilitySpec.source_reference` contract | HIGH | **CLOSED (H1)** | project_id documented as top-level body field (Track P1). Opt-in strict mode `HI_AGENT_PROJECT_ID_REQUIRED=1` → 400 (H1-Track5). | Phase 2 ✓ H1 ✓ |
| **P-2** Reasoning trace storage — structured side-channel for stage LLM reasoning steps | HIGH | **PARTIAL** | Artifact extended with evidence_count/content_hash/producer fields. Full reasoning trace side-channel deferred Wave 9. | Phase 2 partial |
| **P-3** Cross-Run Project aggregation — `project_id` scope alongside `profile_id`; memory spanning multiple runs | HIGH | **CLOSED (H1)** | Opt-in strict mode `HI_AGENT_PROFILE_ID_REQUIRED=1` → 400 (H1-Track5). project_id workspace L3 fix (Wave 8). | Phase 2 ✓ H1 ✓ |
| **P-4** Dynamic re-planning API — `StageDirective(skip_to, insert_stage)` mid-run plan mutation | MEDIUM | **NOT STARTED** | Deferred Phase 3. TRACE loop currently static; API design needed first. | Phase 3 |
| **P-5** Confidence scoring contract — `Artifact.confidence: float`, `evidence_count` fields | MEDIUM | **CLOSED (H1)** | Idempotency replay returns 200 + cached snapshot; mark_complete wired in RunManager._execute_run (H1-Track1). ArtifactLedger + evidence_count on Artifact (Track P2). | Phase 2 ✓ H1 ✓ |
| **P-6** Knowledge Graph inference layer — transitive queries, conflict detection on `LongTermMemoryGraph` | MEDIUM | **ADDRESSED (experimental)** | KnowledgeGraphBackend Protocol defined. LongTermMemoryGraph now implements upsert_node/upsert_edge/query_relation/transitive_query/detect_conflict/export_visualization (Track P7). Neo4j permanently declined. | Phase 3 ✓ |
| **P-7** Feedback integration path — `submit_run_feedback()` API wired to `EvolveEngine`/`HybridRouteEngine` | MEDIUM | **PARTIAL** | CalibrationSignal + TierRouter.ingest_calibration_signal (record-only). Auto-calibration (routing influence) deferred Wave 10 (Phase E). | Phase 3 partial |

---

## Readiness Delta (2026-04-16 → 2026-04-25 H1)

| Dimension | 2026-04-16 | 2026-04-24 | 2026-04-25 (Wave 8) | 2026-04-25 (H1 hardening) | Delta H1 | Driver |
|---|---|---|---|---|---|---|
| Execution Engine (TRACE) | 75% | 80% | 82% | 84% | +2% | Idempotency replay fixed (H1-T1); tenant isolation complete (H1-T2) |
| Memory Infrastructure (L0–L3) | 70% | 75% | 78% | 78% | 0% | No H1 changes |
| Capability Plugin System | 65% | 67% | 70% | 75% | +5% | Config-dir override + JSON profiles + strict-mode gates (H1-T5) |
| Knowledge Graph | 35% | 35% | 50% | 50% | 0% | No H1 changes |
| Planning & Re-planning | 40% | 40% | 40% | 40% | 0% | Deferred Wave 9 |
| Artifact / Output Contracts | 30% | 30% | 50% | 50% | 0% | No H1 changes |
| Evolution & Feedback | 20% | 20% | 35% | 35% | 0% | Deferred Wave 10 |
| Cross-Run State (Project) | 0% | 0% | 20% | 22% | +2% | project_id strict-mode opt-in (H1-T5) |
| Ops / Documentation | 45% | 46% | 55% | 65% | +10% | Tenant scope universal (H1-T2); /manifest discovery enhanced (H1-T3); DF-46 CI gate closed (H1-T4); extension-guide accuracy (H1-T5) |
| **Overall** | **43%** | **46%** | **56%** | **59%** | **+3%** | |

---

## PI-A through PI-E Pattern Support

| Pattern | Description | Status |
|---|---|---|
| PI-A | Multi-stage TRACE pipeline execution | Supported (stable) |
| PI-B | PI-A + reflect_and_infer + restart_policy | Supported (K-7 recursion guard fixed WS-2/3/4) |
| PI-C | PI-B + Human Gate (GatePendingError + continue_from_gate) | Supported (SQLiteGateStore added Wave 8 Track P3) |
| PI-D | PI-B + dispatch_subrun + await_subrun_async | Supported (async path parity confirmed K-2/K-3/K-15) |
| PI-E | PI-C + PI-D (gate + subrun orchestration) | Supported (combination test K-13 added to backlog) |

---

## Permanently Declined

| Ask | Reason |
|---|---|
| P2-2: Neo4j-backed L3 with Cypher | Permanently declined. JSON-backed `LongTermMemoryGraph` satisfies all required graph operations at our scale. Neo4j adds external service dependency without functional gain. Downstream can implement `KnowledgeGraphBackend` Protocol with Neo4j if needed. |
| P3-2: `TierRouter.calibrate()` | Renamed to `ingest_calibration_signal()` — record-only in Wave 8. Active calibration (routing influence) deferred Wave 10. |
