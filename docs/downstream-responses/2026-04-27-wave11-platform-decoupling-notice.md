# Wave 11 — Platform/Business Decoupling Sprint: Delivery Notice

Status: superseded

**Date:** 2026-04-27
**SHA:** 52cc431cd4968bb0fde804c39021ab1ded52970d
**Audience:** Research-Intelligence App team

---

## Summary

Wave 11 removes all research-domain vocabulary from Hi-Agent's public contracts and capability runtime, establishing a clean horizontal platform that can serve multiple downstream consumers without inheriting research-specific terminology.

All changes are **backward-compatible**: deprecated names continue to work with `DeprecationWarning` until Wave 12, which will remove them.

---

## Readiness Delta

| Dimension | Before | After | Evidence |
|---|---|---|---|
| Execution | L3 | L3 | Unchanged |
| Memory | L3 | L3 | Unchanged |
| Capability | L3 | L3 | Unchanged |
| Knowledge Graph | L3 | L3 | Unchanged |
| Planning | L2 | L2 | Unchanged |
| Artifact | L3 | L3 | Artifacts now in platform-agnostic base; research overlay in `examples/research_overlay/` |
| Evolution | L3 | L3 | `RunRetrospective`/`ProjectRetrospective`/`EvolutionTrial` now canonical; postmortem aliases kept one wave |
| Cross-Run | L3 | L3 | `lead_run_id` replaces `pi_run_id` in TeamRun; SQLite migration additive |

---

## PI-A through PI-E Impact

| Pattern | Impact |
|---|---|
| **PI-A** (single-agent task) | Unaffected — no contract surface change on single-agent path |
| **PI-B** (multi-agent team) | `TeamRun.lead_run_id` is now the canonical field; `pi_run_id` stays as alias with DeprecationWarning |
| **PI-C** (capability composition) | Plugin namespace unified to `hi_agent.plugins`; `hi_agent.plugin` shim kept one wave |
| **PI-D** (evolution/feedback) | `RunRetrospective`, `ProjectRetrospective`, `EvolutionTrial` are now canonical; old names kept one wave |
| **PI-E** (long-running ops) | Package renamed `hi_agent.operations`; `hi_agent.experiment` shim kept one wave |

---

## Changes by Track

### W11-A — Wave-Tagged Identifiers Cleanup

Sprint labels (`Wave 10.x`, `W5-F`, etc.) removed from all `hi_agent/**/*.py` and `scripts/**/*.py` source files.  
New CI gate: `scripts/check_no_wave_tags.py` blocks future regressions.

### W11-B — CI Decoupled from Downstream Process

`scripts/check_doc_consistency.py` no longer enforces the `verified_readiness > 76.5` score cap or the `Validated by:` header format. These checks moved to `scripts/check_downstream_response_format.py` which is optional (only run if you produce downstream response notices).  
New file: `docs/downstream-responses/README.md` clarifies scope of the notices directory.

### W11-C — Provider-Neutral T3 Gate

`scripts/inject_volces_key.py` → shim forwarding to `scripts/inject_provider_key.py --provider volces`  
`scripts/rule15_volces_gate.py` → shim forwarding to `scripts/run_t3_gate.py --provider volces`  
New canonical scripts: `inject_provider_key.py`, `run_t3_gate.py`, `run_t3_gate.sh`

### W11-D — Plugin Namespace Unification

`hi_agent.plugins` is now the canonical namespace.  
`hi_agent.plugin` is a shim emitting `DeprecationWarning`. Will be removed in Wave 12.  
All 10 internal import sites updated.

### W11-E — Operations Package Rename

`hi_agent.operations` is now the canonical location for `coordinator`, `op_store`, `poller`, `provenance`.  
`hi_agent.experiment` is a shim emitting `DeprecationWarning`. Will be removed in Wave 12.

### W11-F — TeamRun Contract Decoupling

`TeamRun.lead_run_id` added as the canonical field.  
`TeamRun.pi_run_id` retained as a deprecated alias — `__post_init__` copies to `lead_run_id` with `DeprecationWarning`.  
SQLite migration: `lead_run_id TEXT NOT NULL DEFAULT ''` column added additively via `_MIGRATE_COLS`.  
`AgentRole.role_name` docstring updated: `"lead" | "worker" | "reviewer" | "summarizer"` replace the research-specific examples.  
`TeamSharedContext`: `working_set` / `assertions` added as canonical aliases for deprecated `hypotheses` / `claims`.  
New CI gate: `scripts/check_deprecated_field_usage.py` blocks `pi_run_id` usage outside allowlisted shim files.

### W11-G — Postmortem → Retrospective Rename

| Old name | New canonical name |
|---|---|
| `RunPostmortem` | `RunRetrospective` |
| `ProjectPostmortem` | `ProjectRetrospective` |
| `EvolutionExperiment` | `EvolutionTrial` |
| `hypothesis_outcomes` | `outcome_assessments` |
| `failed_assumptions` | `invalidated_assumptions` |

Old names kept as deprecated aliases via module-level `__getattr__` with `DeprecationWarning`. Will be removed in Wave 12.

### W11-H — Research Artifacts to Overlay Package

`CitationArtifact`, `PaperArtifact`, `LeanProofArtifact` moved to `examples/research_overlay/artifacts.py`.  
Old import paths retained via `hi_agent.artifacts.contracts.__getattr__` shim with `DeprecationWarning`. Will be removed in Wave 12.  
Platform artifact base (`hi_agent/contracts/artifacts.py`) now contains only generic types: `TextArtifact`, `JSONArtifact`, `BinaryArtifact`, `URLReferenceArtifact`.

### W11-I — Strict-Defaults LLM Preset Rename

`apply_strict_defaults` is now the canonical name; `apply_research_defaults` is a shim with `DeprecationWarning`.  
New CI gate: `scripts/check_no_research_vocab.py` blocks research-domain identifiers in production code.

---

## Gap Status

| Gap | Status |
|---|---|
| P-1 Cross-run memory | L3 — unchanged |
| P-2 Knowledge graph | L3 — unchanged |
| P-3 Evolution calibration | L3 — unchanged |
| P-4 Artifact provenance | L3 — unchanged |
| P-5 Multi-agent coordination | L3 — `lead_run_id` decouples from `pi` terminology |
| P-6 Extension ecosystem | L3 — plugin namespace unified |
| P-7 Platform/business separation | **Resolved this wave** — all research vocabulary decoupled |

---

## Wave 12 Removal Manifest

The following will be removed in Wave 12 (all have had one full wave of deprecation notice):

- `hi_agent.plugin` package (use `hi_agent.plugins`)
- `hi_agent.experiment` package (use `hi_agent.operations`)
- `TeamRun.pi_run_id` field (use `lead_run_id`)
- `TeamSharedContext.hypotheses` / `.claims` (use `working_set` / `assertions`)
- `RunPostmortem`, `ProjectPostmortem` classes (use `RunRetrospective`, `ProjectRetrospective`)
- `EvolutionExperiment` class (use `EvolutionTrial`)
- `ProjectRetrospective.hypothesis_outcomes` / `.failed_assumptions` (use `outcome_assessments` / `invalidated_assumptions`)
- `hi_agent.artifacts.contracts.CitationArtifact` shim (import from `examples.research_overlay.artifacts`)
- `hi_agent.artifacts.contracts.PaperArtifact` shim (same)
- `hi_agent.artifacts.contracts.LeanProofArtifact` shim (same)
- `apply_research_defaults()` function (use `apply_strict_defaults()`)
- `scripts/inject_volces_key.py` shim (use `inject_provider_key.py --provider volces`)
- `scripts/rule15_volces_gate.py` shim (use `run_t3_gate.py --provider volces`)

**Also deferred to Wave 12 by design:** `Posture.RESEARCH` → `Posture.STRICT` rename (affects 40+ source files; requires dedicated wave with full design).

---

## Required Reader Actions

| Consumer | Action |
|---|---|
| Research-Intelligence App | Update any direct `from hi_agent.plugin import ...` → `from hi_agent.plugins import ...` |
| Research-Intelligence App | Replace `RunPostmortem(...)` → `RunRetrospective(...)`, `ProjectPostmortem(...)` → `ProjectRetrospective(...)`, `EvolutionExperiment(...)` → `EvolutionTrial(...)` |
| Research-Intelligence App | Replace `team_run.pi_run_id` → `team_run.lead_run_id` |
| Research-Intelligence App | Replace `from hi_agent.artifacts.contracts import CitationArtifact` → `from examples.research_overlay.artifacts import CitationArtifact` |
| CI pipelines | Replace `inject_volces_key.py` invocations → `inject_provider_key.py --provider volces` |
| CI pipelines | Replace `rule15_volces_gate.py` → `run_t3_gate.py --provider volces` |
| Platform consumers (non-research) | No breaking changes; deprecation warnings are informational |

---

## Governance Gate Results

```
python scripts/check_no_wave_tags.py          → OK
python scripts/check_select_completeness.py   → OK
python scripts/check_no_research_vocab.py     → OK
python scripts/check_deprecated_field_usage.py → OK
```

Targeted W11 test bundle: 46/46 passed (sha 0b495b8, post-integration fixes at 52cc431).

---

*This notice is produced by the hi-agent platform team for the research-intelligence consumer. The platform CI does not enforce this format.*