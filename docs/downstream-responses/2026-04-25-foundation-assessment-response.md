# Response: Foundation Assessment 2026-04-25

Status: superseded

**Date**: 2026-04-25
**Wave**: 8
**Platform team**: hi-agent
**Downstream**: Research Intelligence App team

---

## Per-Gap Response

### Gap 1: project_id not first-class (assessment §4.1)

Track P1 (Wave 8): Added project_id to TaskContract, HTTP POST /runs body,
CLI --project-id flag, runner.py, memory_builder.py workspace L3/L2 path.
Fixed workspace-mode silent drop of project_id.
Cross-record coverage: Artifact/GateRecord/RunPostmortem/RunStore schema all
include project_id.

**Status: ADDRESSED (experimental)**

---

### Gap 2: Config-driven team declaration (assessment §4.2)

Track P4 (Wave 8): AgentRole/TeamSharedContext/TeamRun dataclasses added.
TeamRunRegistry + dispatch_subrun role_id support added.
ResearchProjectSpec DSL deferred to Wave 9 (Phase B).

**Status: PARTIAL** (foundation types added; full config-driven team deferred Wave 9)

---

### Gap 3: Capability source/evidence contract (assessment §4.3)

Track P2 (Wave 8): CapabilityDescriptor extended with provenance_required /
source_reference_policy / artifact_output_schema / reproducibility_level /
license_policy. Artifact extended with evidence_count / content_hash /
producer_run_id / producer_stage_id / producer_capability.
ArtifactLedger (durable JSONL). CitationArtifact / PaperArtifact /
DatasetArtifact / LeanProofArtifact types. CitationValidator.

**Status: ADDRESSED (experimental)**

---

### Gap 4: Long-running task durability (assessment §4.4)

Track P3 (Wave 8): cancel_run now propagates to CancellationToken + RunQueue.
Platform records (RunLease / StageCheckpoint / ActionAttempt /
CancellationSignal) typed. SQLiteGateStore added for gate persistence.
SQLiteRunQueue default-on deferred to Wave 9 (Phase C).
Temporal main-path wiring deferred Wave 9.

**Status: PARTIAL** (cancel fixed + gate persisted; durable-by-default deferred Wave 9)

---

### Gap 5: Team-level runtime contract (assessment §4.5)

Track P4 (Wave 8): AgentRole/TeamRun/TeamSharedContext + TeamRunRegistry +
dispatch_subrun role_id. Full shared-private memory scope enforcement deferred
to Wave 9.

**Status: PARTIAL** (types + registry; scope enforcement Wave 9)

---

### Gap 6: Evolution closed loop (assessment §4.6)

Track P6 (Wave 8):
- `ProjectPostmortem` dataclass (aggregates run postmortems at project level)
- `CalibrationSignal` dataclass (cost/quality signal for TierRouter)
- `EvolveEngine.on_project_completed()` — aggregates ProjectPostmortem for all runs
- `TierRouter.ingest_calibration_signal()` — record-only; routing influence deferred Wave 10
- `SkillPromotionPipeline.human_approval_required=True` — gate by default; `PromotionBlocked` exception

Feedback→route active closed loop deferred Phase E (Wave 10).

**Status: PARTIAL** (skeletons added; actual routing influence deferred Wave 10)

---

### Gap 7: KnowledgeGraphBackend abstraction (assessment §4.8)

Track P7 (Wave 8): `KnowledgeGraphBackend` Protocol defined in
`hi_agent.memory.graph_backend`. `LongTermMemoryGraph` now implements all
protocol methods: `upsert_node`, `upsert_edge`, `query_relation`,
`transitive_query`, `detect_conflict`, `export_visualization`.
`JsonGraphBackend = LongTermMemoryGraph` alias added.
Extension guide in `docs/extension-guide.md` shows how downstream can wire
a Neo4jGraphBackend without modifying platform code.

**Status: ADDRESSED** (protocol defined; downstream can implement any backend)

---

### Gap: Documentation drift (assessment §4.9)

Track P5 (Wave 8): `platform-capability-matrix.md` added with per-capability
honest status. `platform-gaps.md` updated with Wave 8 readiness delta.
`GET /manifest` endpoint already wired in app.py (serves dynamic capability
status to downstream integrators).

**Status: ADDRESSED**

---

## What is NOT done in Wave 8

| Deferred Item | Target Wave |
|---|---|
| ResearchProjectSpec / TeamRunSpec DSL | Wave 9 (Phase B) |
| SQLiteRunQueue as default server path | Wave 9 (Phase C) |
| Temporal as production main path | Wave 9 (Phase C) |
| Research workspace cold/warm/hot model | Wave 10 (Phase D/E) |
| TierRouter calibration active (feedback → routing) | Wave 10 (Phase E) |
| Full skill A/B eval + promotion event | Wave 10 (Phase E) |
| Full GraphML/Cytoscape export encoding | Wave 9 |

---

## Readiness Delta (downstream 7-dimension journey tests)

| Journey Test | Wave 8 Status |
|---|---|
| test_project_id_memory_shared_across_runs | DELIVERED (P1) |
| test_project_id_workspace_isolated_same_session | DELIVERED (P1 — bug fix) |
| test_human_gate_survives_restart | DELIVERED (P3 — SQLiteGateStore) |
| test_artifact_ledger_requires_provenance | DELIVERED (P2) |
| test_citation_requires_local_paper_meta | DELIVERED (P2) |
| test_long_run_resume_no_duplicate_actions | PARTIAL (cancel improved; full replay Wave 9) |
| test_research_project_config_creates_team_run | DEFERRED Wave 9 |
| test_backtrack_decision_inserts_remediation_stage | DEFERRED Wave 9 |
| test_feedback_changes_next_route_preference | DEFERRED Wave 10 |
| test_skill_promotion_requires_eval_and_approval | PARTIAL (human_approval_required=True gate; full eval Wave 10) |
| test_kg_backend_protocol_satisfied | DELIVERED (P7) |
| test_project_postmortem_aggregates_runs | DELIVERED (P6) |

---

## PI-A through PI-E Impact

| Pattern | Wave 8 Impact |
|---|---|
| PI-A | No change — already stable |
| PI-B | No change |
| PI-C | Improved: SQLiteGateStore makes gate durable across restarts |
| PI-D | Improved: project_id now flows into subrun dispatch |
| PI-E | Improved: PI-C improvement applies |

---

## Platform Gap Summary (P-1 through P-7)

| Gap | Status after Wave 8 |
|---|---|
| P-1 Provenance | ADDRESSED (experimental) |
| P-2 Reasoning trace | PARTIAL |
| P-3 Cross-run project | ADDRESSED (experimental) |
| P-4 Dynamic re-planning | NOT STARTED (Phase 3) |
| P-5 Confidence scoring | ADDRESSED (experimental) |
| P-6 KG inference layer | ADDRESSED (experimental) |
| P-7 Feedback integration | PARTIAL (record-only) |