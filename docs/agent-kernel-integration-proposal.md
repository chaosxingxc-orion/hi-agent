# Agent-Kernel Integration Proposal

**Date:** 2026-04-07
**Author:** hi-agent Architecture Team
**Status:** Draft
**agent-kernel version:** 0.2.1 (TRACE protocol 1.2.1)
**hi-agent target:** TRACE V2.8

---

## Executive Summary

agent-kernel (57K LOC, Temporal integration, full event sourcing, six-authority model) is architecturally ready for integration with hi-agent. The 17-method `RuntimeAdapter` protocol defined in hi-agent maps nearly 1:1 to `KernelFacade` methods already implemented in agent-kernel. Six targeted modifications are needed to close the remaining gaps: (1) an HTTP/gRPC service layer for cross-process deployment, (2) TRACE protocol version alignment from V1.2.1 to V2.8, (3) evolve-oriented postmortem query support, (4) child run orchestration enrichment, (5) PolicyVersionSet field parity, and (6) state machine enum alignment. None of these require rearchitecting agent-kernel; they are additive extensions to an already mature system.

---

## Current Compatibility

### RuntimeAdapter Method Mapping

The following table maps each method in `hi_agent/runtime_adapter/protocol.py` (`RuntimeAdapter`, 17 methods) to its agent-kernel counterpart in `KernelFacade` (`agent_kernel/adapters/facade/kernel_facade.py`).

| # | hi-agent `RuntimeAdapter` method | agent-kernel `KernelFacade` method | Status |
|---|---|---|---|
| 1 | `open_stage(stage_id)` | `open_stage(stage_id, run_id, branch_id?)` | Compatible -- hi-agent must supply `run_id` |
| 2 | `mark_stage_state(stage_id, target)` | `mark_stage_state(run_id, stage_id, new_state, failure_code?)` | Compatible -- hi-agent must supply `run_id` |
| 3 | `record_task_view(task_view_id, content)` | `record_task_view(TaskViewRecord)` | Compatible -- wrap into `TaskViewRecord` DTO |
| 4 | `bind_task_view_to_decision(task_view_id, decision_ref)` | `bind_task_view_to_decision(task_view_id, decision_ref)` | Exact match |
| 5 | `start_run(task_id)` | `start_run(StartRunRequest)` | Compatible -- wrap `task_id` into `StartRunRequest` |
| 6 | `query_run(run_id)` | `query_run(QueryRunRequest)` | Compatible -- wrap into `QueryRunRequest` |
| 7 | `cancel_run(run_id, reason)` | `cancel_run(CancelRunRequest)` | Compatible -- wrap into `CancelRunRequest` |
| 8 | `resume_run(run_id)` | `resume_run(ResumeRunRequest)` | Exact match |
| 9 | `signal_run(run_id, signal, payload)` | `signal_run(SignalRunRequest)` | Compatible -- wrap into `SignalRunRequest` |
| 10 | `query_trace_runtime(run_id)` | `query_trace_runtime(run_id)` | Exact match -- **response enrichment needed for evolve** |
| 11 | `stream_run_events(run_id)` | `stream_run_events(run_id, include_derived_diagnostic?)` | Compatible |
| 12 | `open_branch(run_id, stage_id, branch_id)` | `open_branch(OpenBranchRequest)` | Compatible -- wrap into DTO |
| 13 | `mark_branch_state(run_id, stage_id, branch_id, state, failure_code?)` | `mark_branch_state(BranchStateUpdateRequest)` | Compatible -- wrap into DTO |
| 14 | `open_human_gate(request: HumanGateRequest)` | `open_human_gate(HumanGateRequest)` | Exact match (DTO alignment needed) |
| 15 | `submit_approval(request: ApprovalRequest)` | `submit_approval(ApprovalRequest)` | Exact match (DTO alignment needed) |
| 16 | `get_manifest()` | `get_manifest()` | Exact match |
| 17 | `submit_plan(run_id, plan)` | `submit_plan(run_id, ExecutionPlan)` | Compatible -- plan dict needs type mapping |

**Summary:** 4 exact matches, 13 compatible with thin DTO wrapping. Zero methods require fundamental new kernel capability.

---

## Proposed Modifications to agent-kernel

### 1. HTTP/gRPC Service Layer

#### Why needed

agent-kernel currently exposes `KernelFacade` as an in-process Python API. hi-agent requires three deployment modes:

1. **In-process direct** (development) -- works today
2. **HTTP/gRPC service** (staging / multi-process) -- **not yet available**
3. **Temporal substrate** (production) -- substrate layer exists, but the facade is still in-process only

Without a network-accessible service layer, hi-agent cannot call agent-kernel from a separate process or container.

#### What to build

A thin HTTP service that wraps `KernelFacade` methods 1:1. Recommended approach:

```
agent_kernel/
  service/
    __init__.py
    http_server.py        # FastAPI/Starlette app
    grpc_server.py        # Optional gRPC for latency-sensitive paths
    serialization.py      # DTO <-> JSON/Protobuf conversion
```

#### Suggested API design

| HTTP Endpoint | Method | Maps to `KernelFacade` |
|---|---|---|
| `POST /runs` | POST | `start_run(StartRunRequest)` |
| `POST /runs/{run_id}/signal` | POST | `signal_run(SignalRunRequest)` |
| `POST /runs/{run_id}/cancel` | POST | `cancel_run(CancelRunRequest)` |
| `POST /runs/{run_id}/resume` | POST | `resume_run(ResumeRunRequest)` |
| `GET /runs/{run_id}` | GET | `query_run(QueryRunRequest)` |
| `GET /runs/{run_id}/dashboard` | GET | `query_run_dashboard(run_id)` |
| `GET /runs/{run_id}/trace` | GET | `query_trace_runtime(run_id)` |
| `GET /runs/{run_id}/events` | GET (SSE) | `stream_run_events(run_id)` |
| `POST /runs/{run_id}/children` | POST | `spawn_child_run(SpawnChildRunRequest)` |
| `POST /runs/{run_id}/plan` | POST | `submit_plan(run_id, ExecutionPlan)` |
| `POST /runs/{run_id}/approval` | POST | `submit_approval(ApprovalRequest)` |
| `POST /runs/{run_id}/stages/{stage_id}/open` | POST | `open_stage(stage_id, run_id)` |
| `PUT /runs/{run_id}/stages/{stage_id}/state` | PUT | `mark_stage_state(run_id, stage_id, ...)` |
| `POST /runs/{run_id}/branches` | POST | `open_branch(OpenBranchRequest)` |
| `PUT /runs/{run_id}/branches/{branch_id}/state` | PUT | `mark_branch_state(BranchStateUpdateRequest)` |
| `POST /runs/{run_id}/human-gates` | POST | `open_human_gate(HumanGateRequest)` |
| `POST /runs/{run_id}/task-views` | POST | `record_task_view(TaskViewRecord)` |
| `PUT /task-views/{task_view_id}/decision` | PUT | `bind_task_view_to_decision(...)` |
| `GET /manifest` | GET | `get_manifest()` |
| `GET /health/liveness` | GET | `get_health()` |
| `GET /health/readiness` | GET | `get_health_readiness()` |
| `POST /tasks` | POST | `register_task(TaskDescriptor)` |
| `GET /tasks/{task_id}/status` | GET | `get_task_status(task_id)` |

**SSE streaming** for `stream_run_events` is recommended over WebSocket to match the append-only event model.

hi-agent will implement a `KernelHttpClient` adapter behind `RuntimeAdapter` that calls these endpoints, keeping the protocol.py interface unchanged.

---

### 2. TRACE Protocol Version Alignment (V1.2.1 -> V2.8)

agent-kernel currently declares `trace_protocol_version = "1.2.1"` in `KernelManifest` (see `INTERFACES.md` section 3.3). hi-agent targets TRACE V2.8 semantics. The following specific alignments are required:

#### 2.1 Run lifecycle state enumeration

| hi-agent `run_state_machine()` | agent-kernel `RunLifecycleState` | Delta |
|---|---|---|
| `created` | `created` | Match |
| `active` | `ready` / `dispatching` / `waiting_result` | **Kernel is finer-grained** |
| `waiting` | `waiting_external` | Rename alignment |
| `recovering` | `recovering` | Match |
| `completed` | `completed` | Match |
| `failed` | *(not present)* | **Gap: kernel has no `failed` terminal state** |
| `aborted` | `aborted` | Match |

**File references:**
- hi-agent: `hi_agent/state_machine/definitions.py`, `run_state_machine()` -- 7 states: `{created, active, waiting, recovering, completed, failed, aborted}`
- agent-kernel: `agent_kernel/kernel/contracts.py` line 20 -- 8 states: `{created, ready, dispatching, waiting_result, waiting_external, recovering, completed, aborted}`

**Proposed resolution:**
- agent-kernel `TraceRunState` (line 2564 of `contracts.py`) already defines the 7-state set: `{created, active, waiting, recovering, completed, failed, aborted}`. This matches hi-agent exactly.
- The mapping layer in `query_trace_runtime` already collapses `ready`/`dispatching`/`waiting_result` into `active` and `waiting_external` into `waiting`.
- **Required change:** Add `failed` as a valid `RunLifecycleState` value (or ensure `TraceRunState.failed` is derivable from `aborted` + failure metadata). Currently `RunLifecycleState` has no `failed` terminal state separate from `aborted`. The `TraceRunState` type at line 2564 does include `failed`, so the projection-to-trace mapping must explicitly produce `failed` when a run terminates due to task failure (as distinct from cancellation/abort).

#### 2.2 TRACE feature set expansion

agent-kernel's `supported_trace_features` (frozen set in `KernelManifest`) should be extended to declare:

| Feature flag | Description | Current status |
|---|---|---|
| `branch_protocol` | Branch open/close/prune lifecycle | Supported |
| `task_view_record` | Task view record and decision binding | Supported |
| `policy_version_pinning` | Policy version freezing at run creation | Supported |
| `stage_protocol` | Stage open/mark lifecycle | Supported |
| `human_gate_protocol` | Human gate open/approve/reject | Supported |
| `evolve_postmortem` | Postmortem query for evolve analysis | **New -- see section 3** |
| `child_run_orchestration` | Enhanced child run with parent context | **New -- see section 4** |

#### 2.3 `trace_protocol_version` bump

After all alignments are complete, agent-kernel should update `KernelManifest.trace_protocol_version` from `"1.2.1"` to `"2.8"`. hi-agent will check this value at startup via `get_manifest()` and refuse to operate if the version is below `"2.0"`.

---

### 3. Evolve Integration Support

#### What hi-agent evolve needs

The Evolve subsystem (`hi_agent/evolve/contracts.py`) requires `RunPostmortem` data to perform post-run analysis. The `RunPostmortem` dataclass has 16 fields:

```python
# hi_agent/evolve/contracts.py
@dataclass
class RunPostmortem:
    run_id: str
    task_id: str
    task_family: str
    outcome: str                    # completed | failed | aborted
    stages_completed: list[str]
    stages_failed: list[str]
    branches_explored: int
    branches_pruned: int
    total_actions: int
    failure_codes: list[str]
    duration_seconds: float
    quality_score: float | None
    efficiency_score: float | None
    trajectory_summary: str
    human_feedback: list[str]
    policy_versions: dict[str, str]
```

#### What `query_trace_runtime` currently returns

`TraceRuntimeView` (`agent_kernel/kernel/contracts.py` line 2604) provides:

```python
@dataclass
class TraceRuntimeView:
    run_id: str
    run_state: TraceRunState
    wait_state: TraceWaitState
    review_state: TraceReviewState
    active_stage_id: str | None
    branches: list[TraceBranchView]
    policy_versions: RunPolicyVersions | None
    projected_at: str
    stages: list[TraceStageView]
```

#### Gap analysis

| `RunPostmortem` field | Available in `TraceRuntimeView`? | Source |
|---|---|---|
| `run_id` | Yes | `TraceRuntimeView.run_id` |
| `task_id` | **No** | Must be derived from `StartRunRequest.input_json` or a new field |
| `task_family` | **No** | Must be supplied by hi-agent or stored in run metadata |
| `outcome` | Derivable | Map `run_state` terminal values |
| `stages_completed` | Yes | Filter `stages` where state == `completed` |
| `stages_failed` | Yes | Filter `stages` where state == `failed` |
| `branches_explored` | Derivable | `len(branches)` |
| `branches_pruned` | Derivable | Count branches where `state == "pruned"` |
| `total_actions` | **No** | Not tracked in `TraceRuntimeView` |
| `failure_codes` | **No** | Not aggregated; individual events may contain codes |
| `duration_seconds` | **No** | Not present; computable from event timestamps |
| `quality_score` | **No** | hi-agent computes this; not a kernel concern |
| `efficiency_score` | **No** | hi-agent computes this; not a kernel concern |
| `trajectory_summary` | **No** | hi-agent generates this; not a kernel concern |
| `human_feedback` | **No** | Human gate resolutions exist but are not aggregated as feedback strings |
| `policy_versions` | Yes | `RunPolicyVersions` -- but needs field expansion (see section 5) |

#### Proposed modification: `query_run_postmortem` facade method

Add a new `KernelFacade` method:

```python
async def query_run_postmortem(self, run_id: str) -> RunPostmortemView:
    """Aggregate run data for post-run analysis by hi-agent evolve."""
```

**`RunPostmortemView` DTO** (new, in `agent_kernel/kernel/contracts.py`):

```python
@dataclass(frozen=True, slots=True)
class RunPostmortemView:
    run_id: str
    task_id: str | None                # from StartRunRequest or task registry
    run_kind: str                       # from StartRunRequest.run_kind
    outcome: TraceRunState              # terminal state
    stages: list[TraceStageView]        # full stage history
    branches: list[TraceBranchView]     # full branch history
    total_action_count: int             # count of action dispatch events
    failure_codes: list[str]            # aggregated TraceFailureCode values
    duration_ms: int                    # run.created to terminal event delta
    human_gate_resolutions: list[HumanGateResolution]  # gate decisions
    policy_versions: RunPolicyVersions | None
    event_count: int                    # total events in the run
    created_at: str                     # ISO-8601
    completed_at: str | None            # ISO-8601, None if still running
```

This method would be implemented by scanning the run's `EventLog` to aggregate action counts, failure codes, timestamps, and human gate outcomes. hi-agent's evolve layer would then enrich this with `task_family`, `quality_score`, `efficiency_score`, and `trajectory_summary` which are hi-agent-owned semantics.

**Implementation location:** `agent_kernel/adapters/facade/kernel_facade.py` -- add `query_run_postmortem` alongside existing `query_trace_runtime`.

---

### 4. Task Decomposition / Child Run Support

#### Current state

agent-kernel already provides `spawn_child_run(SpawnChildRunRequest) -> SpawnChildRunResponse` in `KernelFacade` (see `INTERFACES.md` section 3.2). The `SpawnChildRunRequest` (`contracts.py` line 737) includes:

```python
@dataclass
class SpawnChildRunRequest:
    parent_run_id: str
    child_kind: str
    input_ref: str | None = None
    input_json: dict[str, Any] | None = None
    context_ref: str | None = None
```

#### What hi-agent's Orchestrator needs

hi-agent's Harness Orchestrator requires:

1. **Policy inheritance**: Child runs should inherit `PolicyVersionSet` from parent (or explicitly override).
2. **Task contract binding**: Child runs should be linkable to a `task_id` in the `TaskRegistry` (especially for `task_kind = "plan_step"` or `"parallel_branch"`).
3. **Aggregated child status**: Parent run needs to query all children's states efficiently.
4. **Child completion signaling**: When a child run completes, the parent should be notified via signal.

#### Proposed modifications

**4.1 Extend `SpawnChildRunRequest`:**

```python
@dataclass
class SpawnChildRunRequest:
    parent_run_id: str
    child_kind: str
    input_ref: str | None = None
    input_json: dict[str, Any] | None = None
    context_ref: str | None = None
    # --- New fields ---
    task_id: str | None = None             # Bind to task registry entry
    inherit_policy_versions: bool = True    # Inherit parent's PolicyVersionSet
    policy_version_overrides: dict[str, str] | None = None  # Selective overrides
    notify_parent_on_complete: bool = True  # Signal parent on child terminal state
```

**4.2 Add child aggregation query:**

```python
async def query_child_runs(self, parent_run_id: str) -> list[ChildRunSummary]:
    """Return summary status of all child runs spawned by parent."""
```

```python
@dataclass(frozen=True, slots=True)
class ChildRunSummary:
    child_run_id: str
    child_kind: str
    task_id: str | None
    lifecycle_state: RunLifecycleState
    outcome: TraceRunState | None
    created_at: str
    completed_at: str | None
```

**4.3 Child completion signal:**

When a child run reaches a terminal state (`completed`, `failed`, `aborted`), agent-kernel should auto-inject a signal to the parent run:

```python
# Signal type: "child_run_completed"
# Payload: {"child_run_id": "...", "outcome": "completed|failed|aborted", "task_id": "..."}
```

This signal should be mapped in `RunActorWorkflow._SIGNAL_EVENT_TYPE_MAP`:

```python
"child_run_completed" -> "run.child_run_completed"
```

**Implementation locations:**
- `agent_kernel/kernel/contracts.py` -- extend `SpawnChildRunRequest`, add `ChildRunSummary`
- `agent_kernel/adapters/facade/kernel_facade.py` -- add `query_child_runs`, modify `spawn_child_run`
- `agent_kernel/substrate/temporal/run_actor_workflow.py` -- add child completion signal mapping

---

### 5. PolicyVersionSet Alignment

#### hi-agent's 6-field PolicyVersionSet

From `hi_agent/contracts/policy.py`:

```python
@dataclass(frozen=True)
class PolicyVersionSet:
    route_policy: str = "route_v1"
    acceptance_policy: str = "acceptance_v1"
    memory_policy: str = "memory_v1"
    evaluation_policy: str = "evaluation_v1"
    task_view_policy: str = "task_view_v1"
    skill_policy: str = "skill_v1"
```

#### agent-kernel's current RunPolicyVersions

From `agent_kernel/kernel/contracts.py` line 241:

```python
@dataclass
class RunPolicyVersions:
    route_policy_version: str | None = None
    skill_policy_version: str | None = None
    evaluation_policy_version: str | None = None
    task_view_policy_version: str | None = None
    pinned_at: str = ""
```

#### Gap: 2 missing fields

| hi-agent `PolicyVersionSet` field | agent-kernel `RunPolicyVersions` field | Status |
|---|---|---|
| `route_policy` | `route_policy_version` | Match (naming convention differs) |
| `acceptance_policy` | *(missing)* | **Gap** |
| `memory_policy` | *(missing)* | **Gap** |
| `evaluation_policy` | `evaluation_policy_version` | Match |
| `task_view_policy` | `task_view_policy_version` | Match |
| `skill_policy` | `skill_policy_version` | Match |

#### Proposed modification

Extend `RunPolicyVersions` in `agent_kernel/kernel/contracts.py`:

```python
@dataclass(frozen=True, slots=True)
class RunPolicyVersions:
    route_policy_version: str | None = None
    acceptance_policy_version: str | None = None    # NEW
    memory_policy_version: str | None = None         # NEW
    evaluation_policy_version: str | None = None
    task_view_policy_version: str | None = None
    skill_policy_version: str | None = None
    pinned_at: str = ""
```

**Impact:** This is a backward-compatible additive change. Existing runs with `None` values for the new fields continue to work. The `pinned_at` timestamp ensures audit traceability. The naming convention `*_policy_version` is maintained for consistency within agent-kernel.

**Implementation location:** `agent_kernel/kernel/contracts.py`, `RunPolicyVersions` dataclass (line 241).

---

### 6. State Machine Alignment

hi-agent defines 6 state machines in `hi_agent/state_machine/definitions.py`. agent-kernel defines corresponding state types in `agent_kernel/kernel/contracts.py`. The following comparison ensures alignment:

#### 6.1 Run state machine

| hi-agent states | agent-kernel `TraceRunState` | Aligned? |
|---|---|---|
| `{created, active, waiting, recovering, completed, failed, aborted}` | `{created, active, waiting, recovering, completed, failed, aborted}` | **Yes** |

agent-kernel's `TraceRunState` (line 2564) matches exactly. The lower-level `RunLifecycleState` (line 20) is finer-grained (`ready`, `dispatching`, `waiting_result`, `waiting_external`) but the trace-facing view already collapses correctly.

#### 6.2 Stage state machine

| hi-agent states | agent-kernel `TraceStageState` | Aligned? |
|---|---|---|
| `{pending, active, blocked, completed, failed}` | `{pending, active, blocked, completed, failed}` | **Yes** |

Exact match at line 2567 of `contracts.py`.

#### 6.3 Branch state machine

| hi-agent states | agent-kernel `TraceBranchState` | Aligned? |
|---|---|---|
| `{proposed, active, pruned, waiting, succeeded, failed}` | `{proposed, active, waiting, pruned, succeeded, failed}` | **Yes** |

Exact match at line 2568 of `contracts.py`.

#### 6.4 Action state machine

| hi-agent states | agent-kernel `DedupeState` | Aligned? |
|---|---|---|
| `{prepared, dispatched, acknowledged, succeeded, effect_unknown, failed, compensated}` | `{reserved, dispatched, acknowledged, succeeded, unknown_effect}` | **Partial** |

Gaps:
- hi-agent `prepared` vs agent-kernel `reserved` -- **naming mismatch** (semantic equivalent)
- hi-agent `failed` -- **not present in `DedupeState`**; agent-kernel tracks failure via `RecoveryGate`, not the dedupe store
- hi-agent `compensated` -- **not present in `DedupeState`**; compensation is handled by `RecoveryGate`
- hi-agent `effect_unknown` vs agent-kernel `unknown_effect` -- **naming mismatch** (semantic equivalent)

**Proposed resolution:**
The action state machine in hi-agent is a higher-level TRACE concept. The `DedupeStore` in agent-kernel is a lower-level mechanism focused on idempotency, not full action lifecycle. The hi-agent `RuntimeAdapter` does not expose action state machine transitions directly; instead, `get_action_state` on `KernelFacade` returns the `DedupeState` string. hi-agent's adapter layer should map:
- `reserved` -> `prepared`
- `unknown_effect` -> `effect_unknown`
- `failed` and `compensated` are hi-agent-owned states derived from `RecoveryGate` events

No kernel modification required; the adapter handles translation.

#### 6.5 Wait state machine

| hi-agent states | agent-kernel `TraceWaitState` | Aligned? |
|---|---|---|
| `{none, external_callback, human_review, scheduled_resume}` | `{none, external_callback, human_review, scheduled_resume}` | **Yes** |

Exact match at line 2569 of `contracts.py`.

#### 6.6 Review state machine

| hi-agent states | agent-kernel `TraceReviewState` | Aligned? |
|---|---|---|
| `{not_required, requested, in_review, approved, rejected}` | `{not_required, requested, in_review, approved, rejected}` | **Yes** |

Exact match at line 2570 of `contracts.py`.

#### Summary

5 of 6 state machines are exactly aligned. The action state machine has naming differences that are resolved in the adapter layer with no kernel modification needed. This is a strong baseline for integration.

---

## Integration Plan

### Step 1: In-Process Direct Mode (Development)

**Target:** Local development and unit testing.

**Approach:**
- hi-agent imports `agent-kernel` as a Python dependency.
- `RuntimeAdapter` implementation (`KernelDirectAdapter`) holds a reference to `KernelFacade` in-process.
- Uses `LocalSubstrateConfig` (no Temporal dependency).
- All 17 `RuntimeAdapter` methods delegate directly to `KernelFacade` with thin DTO wrapping.

**File locations:**
- Adapter implementation: `hi_agent/runtime_adapter/kernel_direct.py`
- Configuration: `hi_agent/runtime_adapter/config.py` (substrate selection)

**Prerequisites:**
- PolicyVersionSet alignment (section 5) -- additive, low risk.
- State machine naming translation in adapter layer (section 6.4).

**Estimated effort:** 1-2 weeks.

### Step 2: HTTP Mode (Staging)

**Target:** Multi-process deployment where hi-agent and agent-kernel run as separate services.

**Approach:**
- agent-kernel team ships the HTTP service layer (section 1).
- hi-agent implements `KernelHttpAdapter` behind the same `RuntimeAdapter` protocol.
- Event streaming uses SSE via `GET /runs/{run_id}/events`.
- Health checks via `/health/liveness` and `/health/readiness`.

**File locations:**
- agent-kernel service: `agent_kernel/service/http_server.py` (new)
- hi-agent HTTP adapter: `hi_agent/runtime_adapter/kernel_http.py` (new)

**Prerequisites:**
- Step 1 completed and passing integration tests.
- HTTP service layer built and deployed (section 1).
- `query_run_postmortem` endpoint available (section 3).

**Estimated effort:** 2-3 weeks (kernel service) + 1 week (hi-agent adapter).

### Step 3: Temporal Substrate (Production)

**Target:** Full production deployment with durable run execution.

**Approach:**
- agent-kernel runs with `TemporalSubstrateConfig(mode="sdk")` connected to a production Temporal cluster.
- hi-agent connects via the HTTP service layer from Step 2 (the Temporal substrate is internal to agent-kernel).
- Event persistence via production-grade event log backend (SQLite or external store).
- `KernelManifest.trace_protocol_version` reports `"2.8"` after all alignments.

**Prerequisites:**
- Steps 1 and 2 completed.
- TRACE protocol version alignment (section 2).
- Child run orchestration enhancements (section 4).
- Evolve postmortem support (section 3).
- Temporal cluster provisioned and operational.

**Estimated effort:** 2-3 weeks (infra + integration testing).

---

## Testing Strategy

### Level 1: Contract Tests (Step 1)

Verify each `RuntimeAdapter` method round-trips correctly through `KernelDirectAdapter` to `KernelFacade`.

- **What:** 17 method-level contract tests, one per `RuntimeAdapter` method.
- **How:** Use `LocalSubstrateConfig`, in-process `KernelRuntime`.
- **Location:** `python_tests/hi_agent/runtime_adapter/test_kernel_direct.py`
- **Key assertions:**
  - `start_run` returns valid `run_id`.
  - `open_stage` / `mark_stage_state` produce correct `TraceStageView` in `query_trace_runtime`.
  - `open_branch` / `mark_branch_state` produce correct `TraceBranchView`.
  - `open_human_gate` / `submit_approval` cycle completes without error.
  - `record_task_view` / `bind_task_view_to_decision` round-trips via `get_task_view_by_decision`.
  - `PolicyVersionSet` 6 fields are preserved through `RunPolicyVersions`.

### Level 2: State Machine Conformance Tests (Step 1)

Verify hi-agent's 6 state machines are honored by agent-kernel's trace projections.

- **What:** Drive runs through all transition paths and verify `TraceRuntimeView` states match.
- **How:** Use `signal_run` to force transitions, `query_trace_runtime` to verify.
- **Location:** `python_tests/hi_agent/runtime_adapter/test_state_machine_conformance.py`
- **Key scenarios:**
  - Run: `created -> active -> waiting -> recovering -> completed`
  - Run: `created -> active -> failed`
  - Stage: `pending -> active -> blocked -> active -> completed`
  - Branch: `proposed -> active -> pruned`
  - Wait: `none -> human_review -> none`
  - Review: `not_required -> requested -> in_review -> approved`

### Level 3: HTTP Integration Tests (Step 2)

Verify the HTTP service layer behaves identically to in-process mode.

- **What:** Same 17 method tests, but via HTTP client.
- **How:** Start agent-kernel HTTP server in test fixture, use `KernelHttpAdapter`.
- **Location:** `python_tests/hi_agent/runtime_adapter/test_kernel_http.py`
- **Key additions:**
  - SSE streaming for `stream_run_events` delivers events in order.
  - Health endpoints return correct liveness/readiness.
  - Concurrent requests do not produce race conditions.

### Level 4: Evolve Postmortem Tests (Step 2)

Verify `query_run_postmortem` returns data sufficient to construct `RunPostmortem`.

- **What:** Run a complete task through multiple stages with failures, then query postmortem.
- **How:** Execute multi-stage run, intentionally fail some stages, complete others, then call `query_run_postmortem`.
- **Location:** `python_tests/hi_agent/evolve/test_postmortem_integration.py`
- **Key assertions:**
  - `total_action_count` matches expected dispatch count.
  - `failure_codes` includes all `TraceFailureCode` values emitted.
  - `duration_ms` is within expected bounds.
  - `human_gate_resolutions` captures all gate decisions.

### Level 5: End-to-End with Temporal (Step 3)

Full TRACE lifecycle with durable substrate.

- **What:** Start run, signal through all 5 default stages (Understand -> Gather -> Build/Analyze -> Synthesize -> Review/Finalize), spawn child runs, exercise human gates, then verify postmortem.
- **How:** Use `TemporalSubstrateConfig(mode="host")` for test isolation.
- **Location:** `python_tests/hi_agent/integration/test_e2e_temporal.py`
- **Key assertions:**
  - Run survives worker restart (Temporal replay).
  - Child run completion signals parent correctly.
  - `KernelManifest.trace_protocol_version == "2.8"`.
  - Policy versions are preserved across Temporal replay.

---

## Appendix: File Reference Summary

### hi-agent files

| File | Role |
|---|---|
| `hi_agent/runtime_adapter/protocol.py` | 17-method `RuntimeAdapter` protocol |
| `hi_agent/evolve/contracts.py` | `RunPostmortem` data contract |
| `hi_agent/contracts/policy.py` | `PolicyVersionSet` (6 fields) |
| `hi_agent/state_machine/definitions.py` | 6 state machine definitions |
| `hi_agent/contracts/stage.py` | `StageState` enum |
| `hi_agent/contracts/requests.py` | `ApprovalRequest`, `HumanGateRequest` |

### agent-kernel files

| File | Role |
|---|---|
| `agent_kernel/kernel/contracts.py` | All DTOs, state types, `RunPolicyVersions` (line 241), `TraceRuntimeView` (line 2604), `SpawnChildRunRequest` (line 737) |
| `agent_kernel/adapters/facade/kernel_facade.py` | `KernelFacade` -- primary API surface |
| `agent_kernel/runtime/kernel_runtime.py` | `KernelRuntime` -- startup/shutdown |
| `agent_kernel/substrate/temporal/run_actor_workflow.py` | `RunActorWorkflow` -- lifecycle driver, signal-to-event mapping |
| `agent_kernel/kernel/minimal_runtime.py` | Six authorities implementation |
| `agent_kernel/kernel/dedupe_store.py` | `DedupeStore` protocol and implementations |
| `agent_kernel/kernel/task_manager/contracts.py` | `TaskDescriptor`, `TaskLifecycleState`, `TaskRestartPolicy` |
| `agent_kernel/kernel/peer_auth.py` | Peer run authorization |
