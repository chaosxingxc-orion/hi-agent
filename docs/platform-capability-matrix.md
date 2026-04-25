# hi-agent Platform Capability Matrix

Last updated: 2026-04-25 (H1 Hardening, post-Wave 8)

---

## Capability Status Legend

| Status | Meaning |
|---|---|
| `not_started` | Not implemented |
| `experimental` | Code exists, no stable tests or contract |
| `implemented_unstable` | Code + tests exist, contract may change |
| `public_contract` | Stable interface + full test coverage |
| `production_ready` | Passed T3 Rule 8 gate |

---

## Dimensions

| Dimension | Status | Notes | Tests | Endpoint |
|---|---|---|---|---|
| TRACE single-run execution | `public_contract` | RunExecutor + StageOrchestrator; K-defects resolved | tests/integration/test_run_lifecycle*.py | POST /runs |
| Config-driven extensibility | `public_contract` | HI_AGENT_CONFIG_DIR override; JSON profile loader; hi_agent_config.json; extension-guide walkthrough (H1-Track5) | tests/integration/test_config_dir_resolution.py | GET /tools |
| Registry-based capability | `implemented_unstable` | CapabilityRegistry + CapabilityDescriptor with provenance_required/source_reference_policy | tests/unit/test_capability_descriptor_extended.py | GET /tools |
| Long-running task stability | `experimental` | RunQueue typed; SQLiteRunQueue default-on deferred Wave 9; Temporal not wired | - | - |
| Project-level cross-run state | `experimental` | project_id in TaskContract + memory (Wave 8); workspace L3 path fix | tests/integration/test_project_id*.py | POST /runs {project_id} |
| Multi-agent team runtime | `experimental` | AgentRole/TeamRun/TeamSharedContext (Wave 8); no ResearchProjectSpec | tests/unit/test_agent_role*.py | - |
| Evidence / anti-hallucination | `experimental` | ArtifactLedger (Wave 8); CitationValidator; provenance_required | tests/integration/test_artifact_ledger*.py | GET /artifacts |
| Evolution closed loop | `experimental` | ProjectPostmortem + CalibrationSignal + on_project_completed + human_approval_required (Wave 8) | tests/unit/test_project_postmortem_dataclass.py | - |
| Knowledge graph abstraction | `experimental` | KnowledgeGraphBackend Protocol + JsonGraphBackend alias (Wave 8) | tests/unit/test_knowledge_graph_backend_protocol.py | GET /knowledge/status |
| Research workspace model | `not_started` | ResearchProjectSpec deferred Wave 10 (needs Phase B) | - | - |
| Ops and release governance | `public_contract` | Tenant scope universal (H1-T2); /manifest auth + schema discovery (H1-T3); CI Rule-8 gate enforcement DF-46 closed (H1-T4); check_t3_freshness.py | tests/integration/test_tenant_scope_universal.py, test_manifest_contract.py | GET /health, GET /manifest |
| Human gate lifecycle | `public_contract` | GatePendingError + continue_from_gate + SQLiteGateStore | tests/integration/test_dangerous_capability*.py | POST /runs/{id}/signal |
| LLM tier routing | `implemented_unstable` | TierRouter + TierAwareLLMGateway; calibration signal ingest record-only | tests/unit/test_evolve_policy_resolution.py | - |
| Provenance contract | `experimental` | CapabilityDescriptor + Artifact extended fields; ArtifactLedger | tests/integration/test_artifact_provenance.py | - |

---

## Wave 8 Additions (P1–P7)

| Track | Capability | Status |
|---|---|---|
| P1 | project_id first-class in TaskContract + memory + HTTP | `experimental` |
| P2 | CapabilityDescriptor provenance/evidence fields + ArtifactLedger | `experimental` |
| P3 | cancel_run CancellationToken propagation + SQLiteGateStore | `implemented_unstable` |
| P4 | AgentRole/TeamRun/TeamSharedContext dataclasses | `experimental` |
| P5 | /manifest endpoint + platform-capability-matrix.md | `implemented_unstable` |
| P6 | ProjectPostmortem + CalibrationSignal + on_project_completed + human_approval_required | `experimental` |
| P7 | KnowledgeGraphBackend Protocol + JsonGraphBackend alias | `experimental` |

---

## H1 Hardening Additions (post-Wave 8)

| Track | Capability | Status |
|---|---|---|
| H1-T0 | G1/G2/G3 intake decisions doc (governance gate) | `public_contract` |
| H1-T1 | Idempotency replay 200 + snapshot; mark_complete wired | `public_contract` |
| H1-T2 | Tenant scope universal: artifacts/knowledge/memory/tools/manifest/skills/cost/replay | `public_contract` |
| H1-T3 | /manifest: version from metadata, auto-derived endpoints, per-capability schemas | `public_contract` |
| H1-T4 | Test honesty (5 weak assertions tightened, 4 mock-on-SUT skipped); DF-46 CI gate closed | internal |
| H1-T5 | HI_AGENT_CONFIG_DIR; JSON profile loader; runtime_config_loader; strict-mode P-1/P-3 | `public_contract` |

## What is NOT done in Wave 8 or H1

- ResearchProjectSpec / TeamRunSpec DSL → Wave 9 (Phase B) — DECLINED as business-layer
- Force capability outputs into ArtifactLedger → DECLINED as business-layer (research team policy)
- SQLiteRunQueue as default server path → Wave 9 (Phase C)
- Temporal as production main path → Wave 9 (Phase C)
- Research workspace cold/warm/hot model → Wave 10 (Phase D/E)
- feedback → routing decisions (TierRouter calibration active) → Wave 10 (Phase E)
- Reflection-path silent-drop (I-6/F-5/F-6) → H2
- Reasoning trace side-channel (P-2) → H2
- Full skill A/B eval + promotion event → Wave 10 (Phase E)
- Full GraphML/Cytoscape export encoding → Wave 9
