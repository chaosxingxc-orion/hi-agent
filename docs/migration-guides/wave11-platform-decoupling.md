# Wave 11 Migration Guide — Platform/Business Decoupling

**Applies to:** All consumers of `hi_agent` public contracts  
**Deprecation wave:** Wave 11 (2026-04-27)  
**Removal wave:** Wave 12

---

## Overview

Wave 11 removes research-domain vocabulary from Hi-Agent's public contracts. All changes are backward-compatible: deprecated names continue to work with `DeprecationWarning` for one wave. **Wave 12 removes the deprecated names permanently.**

---

## 1. Plugin Namespace

| Before (deprecated) | After (canonical) |
|---|---|
| `from hi_agent.plugin import PluginManifest` | `from hi_agent.plugins import PluginManifest` |
| `from hi_agent.plugin.manifest import PluginManifest` | `from hi_agent.plugins.manifest import PluginManifest` |
| `from hi_agent.plugin.lifecycle import ...` | `from hi_agent.plugins.lifecycle import ...` |
| `from hi_agent.plugin.loader import ...` | `from hi_agent.plugins.loader import ...` |

The old `hi_agent.plugin` package is a shim that re-exports everything from `hi_agent.plugins` with `DeprecationWarning`.

---

## 2. Operations Package

| Before (deprecated) | After (canonical) |
|---|---|
| `from hi_agent.experiment.coordinator import ...` | `from hi_agent.operations.coordinator import ...` |
| `from hi_agent.experiment.op_store import LongRunningOpStore` | `from hi_agent.operations.op_store import LongRunningOpStore` |
| `from hi_agent.experiment.poller import ...` | `from hi_agent.operations.poller import ...` |
| `from hi_agent.experiment.provenance import ...` | `from hi_agent.operations.provenance import ...` |

The old `hi_agent.experiment` package is a shim that re-exports from `hi_agent.operations`.

---

## 3. TeamRun Fields

| Before (deprecated) | After (canonical) |
|---|---|
| `team_run.pi_run_id` | `team_run.lead_run_id` |
| `TeamRun(pi_run_id="x", ...)` | `TeamRun(lead_run_id="x", ...)` |
| `context.hypotheses` | `context.working_set` |
| `context.claims` | `context.assertions` |

**Migration path for `TeamRun` construction:**
```python
# Before
run = TeamRun(team_id="t1", pi_run_id="run-coordinator-001", ...)

# After
run = TeamRun(team_id="t1", lead_run_id="run-coordinator-001", ...)
```

**`__post_init__` migration rule:** If only `pi_run_id` is set, it is automatically copied to `lead_run_id` with `DeprecationWarning`. If `lead_run_id` is set, `pi_run_id` is ignored. If both are set to different values, `ValueError` is raised.

**SQLite migration:** The `lead_run_id` column is added additively via `_MIGRATE_COLS` — existing databases are automatically migrated on first connect. Old rows with empty `lead_run_id` fall back to reading `pi_run_id` at read time.

**`AgentRole.role_name` docstring update:**  
Old examples: `"pi" | "survey" | "analysis" | "writer_author"`  
New examples: `"lead" | "worker" | "reviewer" | "summarizer"`  
(role_name is an opaque string the platform does not interpret)

---

## 4. Evolve Contract Renames

| Before (deprecated) | After (canonical) |
|---|---|
| `RunPostmortem` | `RunRetrospective` |
| `ProjectPostmortem` | `ProjectRetrospective` |
| `EvolutionExperiment` | `EvolutionTrial` |
| `ProjectPostmortem.hypothesis_outcomes` | `ProjectRetrospective.outcome_assessments` |
| `ProjectPostmortem.failed_assumptions` | `ProjectRetrospective.invalidated_assumptions` |

**Migration:**
```python
# Before
from hi_agent.evolve.contracts import RunPostmortem, ProjectPostmortem, EvolutionExperiment

retro = RunPostmortem(run_id="r1", tenant_id="t1", ...)
proj = ProjectPostmortem(project_id="p1", hypothesis_outcomes=[...], failed_assumptions=[...])

# After
from hi_agent.evolve.contracts import RunRetrospective, ProjectRetrospective, EvolutionTrial

retro = RunRetrospective(run_id="r1", tenant_id="t1", ...)
proj = ProjectRetrospective(project_id="p1", outcome_assessments=[...], invalidated_assumptions=[...])
```

Old names are accessible via module-level `__getattr__` and emit `DeprecationWarning` on import.

---

## 5. Research Artifact Types

| Before (deprecated import path) | After (canonical import path) |
|---|---|
| `from hi_agent.artifacts.contracts import CitationArtifact` | `from examples.research_overlay.artifacts import CitationArtifact` |
| `from hi_agent.artifacts.contracts import PaperArtifact` | `from examples.research_overlay.artifacts import PaperArtifact` |
| `from hi_agent.artifacts.contracts import LeanProofArtifact` | `from examples.research_overlay.artifacts import LeanProofArtifact` |

The old import paths return the same classes via a shim with `DeprecationWarning`.

The `examples/research_overlay/` package is a reference implementation showing how to extend the platform artifact system for a research domain. Copy and adapt it to your own package if needed — the `examples/` directory is not guaranteed stable across waves.

---

## 6. LLM Preset Function

| Before (deprecated) | After (canonical) |
|---|---|
| `apply_research_defaults(builder)` | `apply_strict_defaults(builder)` |

The old function is a shim that calls the new one with `DeprecationWarning`.

---

## 7. T3 Gate Scripts

| Before (deprecated) | After (canonical) |
|---|---|
| `python scripts/inject_volces_key.py` | `python scripts/inject_provider_key.py --provider volces` |
| `python scripts/rule15_volces_gate.py` | `python scripts/run_t3_gate.py --provider volces` |
| `bash scripts/run_t3_gate.sh` | `bash scripts/run_t3_gate.sh --provider auto` |

The new scripts support `--provider {volces,anthropic,openai,auto}`. The old scripts forward to the new ones with `DeprecationWarning`.

---

## 8. Platform CI Changes (for platform contributors)

`scripts/check_doc_consistency.py` no longer enforces:
- `verified_readiness > 76.5` score cap
- `Validated by:` header format

These checks are now in `scripts/check_downstream_response_format.py` (optional, only run if producing downstream response notices).

New CI gates added:
- `scripts/check_no_wave_tags.py` — blocks sprint labels (`Wave N.M`, `WN-X`) in source
- `scripts/check_no_research_vocab.py` — blocks research-domain identifiers in production code
- `scripts/check_deprecated_field_usage.py` — blocks `pi_run_id` access outside allowlisted shims

---

## 9. Wave 12 Removal Schedule

Wave 12 will remove all deprecated aliases and shims. **All consumers must migrate before Wave 12 merges.**

Wave 12 also plans `Posture.RESEARCH` → `Posture.STRICT` rename (deferred from Wave 11 due to 40+ source-file scope). This rename will be announced separately with a dedicated migration guide.

---

## Quick Reference: Deprecation to Canonical

```python
# Plugins
from hi_agent.plugins import PluginManifest  # was hi_agent.plugin

# Operations
from hi_agent.operations.op_store import LongRunningOpStore  # was hi_agent.experiment.op_store

# TeamRun
TeamRun(lead_run_id="x", ...)  # was pi_run_id
team_ctx.working_set  # was hypotheses
team_ctx.assertions   # was claims

# Evolve
RunRetrospective  # was RunPostmortem
ProjectRetrospective  # was ProjectPostmortem
EvolutionTrial  # was EvolutionExperiment
proj.outcome_assessments  # was hypothesis_outcomes
proj.invalidated_assumptions  # was failed_assumptions

# Artifacts
from examples.research_overlay.artifacts import CitationArtifact  # was hi_agent.artifacts.contracts

# LLM preset
apply_strict_defaults(builder)  # was apply_research_defaults

# CI scripts
python scripts/inject_provider_key.py --provider volces  # was inject_volces_key.py
python scripts/run_t3_gate.py --provider volces           # was rule15_volces_gate.py
```
