# Runtime Profile Guide

This guide describes how upper-layer agents (such as `rnd_agent`) configure
themselves as first-class runtime profiles on the hi-agent platform.  A profile
is the platform's contract surface for business-specific customization — it
replaces reverse-engineering internal executor wiring with a single declarative
registration call.

---

## What is a ProfileSpec?

`ProfileSpec` (`hi_agent/profiles/contracts.py`) is a dataclass that declares
everything a business agent needs from the platform at runtime.

| Field | Type | Purpose |
|---|---|---|
| `profile_id` | `str` | Unique identifier used to look up this profile from a `TaskContract`. |
| `display_name` | `str` | Human-readable name shown in logs and management UIs. |
| `description` | `str` | Optional summary of the profile's purpose. |
| `required_capabilities` | `list[str]` | Capability names the platform must verify are registered before a run starts. |
| `stage_actions` | `dict[str, str]` | Maps stage IDs to capability names, overriding the `RuleRouteEngine` defaults. |
| `stage_graph_factory` | `Callable[[], StageGraph] \| None` | Zero-argument factory that returns a custom `StageGraph` topology. Replaces the TRACE S1-S5 graph when set. Excluded from serialization. |
| `evaluator_factory` | `Callable[..., Evaluator] \| None` | Zero-argument factory that returns a custom `Evaluator`. Injected into `EvaluationMiddleware` when set. Excluded from serialization. |
| `config_overrides` | `dict[str, Any]` | Key-value patches applied to `TraceConfig` for the duration of the run. |
| `metadata` | `dict[str, Any]` | Free-form bag for audit, versioning, or tagging metadata. |

Callable fields (`stage_graph_factory`, `evaluator_factory`) are excluded from
`to_dict()` / `from_dict()` serialization and default to `None` when restored.
They must be re-registered in-process at startup.

---

## The Runtime Path

```
CLI / API request (profile_id on TaskContract)
        |
        v
SystemBuilder.build_executor(contract)
        |
        v
SystemBuilder._resolve_profile(profile_id)
  - calls build_profile_registry() -> ProfileRegistry
  - ProfileRuntimeResolver(registry).resolve(profile_id)
        |
        v
ProfileRuntimeResolver.resolve(profile_id)
  - calls stage_graph_factory()   -> stage_graph
  - calls evaluator_factory()     -> evaluator
  - copies stage_actions, config_overrides, required_capabilities
  -> returns ResolvedProfile
        |
        v
SystemBuilder._build_executor_impl(contract, resolved_profile)
  - resolved_profile.stage_graph    -> replaces TRACE S1-S5 StageGraph
  - resolved_profile.stage_actions  -> passed to RuleRouteEngine
  - resolved_profile.evaluator      -> injected into EvaluationMiddleware
  - resolved_profile.config_overrides -> merged into TraceConfig for this run
        |
        v
RunExecutor (ready to execute)
```

**No profile — fallback behavior.** When `profile_id` is absent from the
contract, or the ID is not found in the registry, `_resolve_profile` returns
`None`.  `_build_executor_impl` receives `resolved_profile=None` and the
executor runs the built-in TRACE S1-S5 sample graph with default routing and
no custom evaluator.

---

## How to Register a Profile

Call `builder.build_profile_registry().register(ProfileSpec(...))` before
submitting runs that reference the profile.  `ProfileRegistry.register` raises
`ValueError` if the same `profile_id` is registered twice — use `.remove()`
first if you need to replace a profile at runtime.

### Minimal 3-Stage Example

```python
from hi_agent.config.builder import SystemBuilder
from hi_agent.profiles.contracts import ProfileSpec
from hi_agent.trajectory.stage_graph import StageGraph

# Build the platform builder (done once at service startup).
builder = SystemBuilder()

# Define a 3-stage linear topology.
def make_rnd_graph() -> StageGraph:
    graph = StageGraph()
    graph.add_stage("literature_search")
    graph.add_stage("synthesis")
    graph.add_stage("report")
    graph.add_edge("literature_search", "synthesis")
    graph.add_edge("synthesis", "report")
    return graph

spec = ProfileSpec(
    profile_id="rnd_agent_v1",
    display_name="R&D Research Agent",
    description="Searches literature, synthesizes findings, produces a report.",
    required_capabilities=["web_search", "document_fetch", "summarize"],
    stage_actions={
        "literature_search": "web_search",
        "synthesis": "summarize",
        "report": "document_generate",
    },
    stage_graph_factory=make_rnd_graph,
    config_overrides={
        "llm_budget_max_tokens": 200_000,
        "gate_quality_threshold": 0.85,
    },
)

builder.build_profile_registry().register(spec)
```

After registration, any `TaskContract` with `profile_id="rnd_agent_v1"` will
use the 3-stage graph and the declared capability mapping.

---

## What Happens With No Profile

When no `profile_id` is set on the contract (or the ID is not found):

1. `_resolve_profile` returns `None`.
2. `_build_executor_impl` passes `stage_graph=None` to `RunExecutor`.
3. `RunExecutor` falls back to the TRACE S1-S5 sample stages.
4. `RuleRouteEngine` uses its built-in default `stage_actions` mapping.
5. No custom evaluator is injected into `EvaluationMiddleware`.

The fallback is stable and suitable for general-purpose task execution.
Upper-layer agents that need domain-specific routing or evaluation **must**
register a profile.

---

## Key Source Locations

| Component | File |
|---|---|
| `ProfileSpec` | `hi_agent/profiles/contracts.py` |
| `ProfileRegistry` | `hi_agent/profiles/registry.py` |
| `ProfileRuntimeResolver`, `ResolvedProfile` | `hi_agent/runtime/profile_runtime.py` |
| `build_profile_registry`, `_resolve_profile`, `_build_executor_impl` | `hi_agent/config/builder.py` |
