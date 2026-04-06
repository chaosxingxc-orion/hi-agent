# TRACE Architecture Review Response

> Inputs reviewed:
> - `From Geimini - V1.txt`
> - `From Claude  - V1.txt`
> - `2026-04-05-trace-architecture-review.md`

## 1. Overall Judgment

Both reviewers converge on the same core point:

- the direction is correct
- the architecture is differentiated from ReAct in a meaningful way
- implementation should not begin until several architecture gaps are closed

This judgment is technically sound.

The most important conclusion is:

`TRACE should proceed as the architecture baseline, but only after Evolve, CTS budgeting, Task View reconstruction, and cross-repository interaction contracts are made explicit.`

## 2. Consolidated Response

### 2.1 Points Accepted

The following review points are accepted as correct and architecture-level:

1. `Evolve` is under-specified
2. `CTS` lacks an explicit exploration budget model
3. `Context OS / Task View` reconstruction is currently too implicit
4. `hi-agent / agent-kernel / agent-core` boundaries need a concrete sequence-level validation
5. human intervention points need to be modeled more explicitly
6. first-domain validation should not overfit the architecture to scientific research

### 2.2 Point Partially Accepted

The following point is partially accepted:

7. `LLM Gateway` capability roles may be too fine-grained if exposed as top-level stable contracts

Response:

- the concern is valid if those roles are treated as hard public API
- the concern is not fatal if those roles are treated as internal routing hints

Decision:

- keep `LLM Gateway` as a stable abstraction
- reduce public capability classes to coarse-grained roles
- move fine-grained role distinctions into upper-layer routing policy rather than kernel-level public API

### 2.3 Point Not Accepted as a Blocker

The engineering difficulty of durable runtime and asynchronous wakeup is real, but it is not a reason to reduce the architecture.

Response:

- this is precisely why `agent-kernel` exists
- durable run management is not optional for 7x24 enterprise agents
- complexity here should be absorbed by kernel design, not hidden by weakening the upper architecture

## 3. Specific Responses to Reviewer Questions

### 3.1 Response to the Gemini review: how will trajectory become skill?

This is the correct hardest question.

The answer should not be:

- one successful path immediately becomes a skill
- manual review does all the work

The architecture should define a three-stage skill crystallization pipeline:

1. `Skill Candidate`
- generated from one or more successful trajectory segments
- represented as a reusable procedural pattern hypothesis
- not yet trusted for broad reuse

2. `Provisional Skill`
- reused in later runs under limited scope
- evaluated on stability, quality, and efficiency
- compared against baseline execution

3. `Certified Skill`
- promoted only after repeated cross-run validation
- versioned and bound to clear applicability constraints

This means:

- trajectories do not directly become skills
- they become candidates
- candidates must survive evaluation before they become first-class skills

The likely initial implementation path is:

- LLM-assisted trajectory summarization
- structured extraction of reusable subgraphs or step templates
- judge-model or rule-based scoring
- challenger validation in later runs

This is closer to:

- reflective distillation plus replay validation

than to:

- pure RL

### 3.2 Response to Claude issue 1: Evolve is too vague

Accepted.

`Evolve` must become a concrete subsystem with:

- trigger modes
- input schema
- quality guards
- rollback or deactivation paths

Planned refinement:

#### Trigger Modes

- `per-run postmortem`: triggered when a run reaches terminal state
- `batch evolution`: triggered on periodic windows across similar runs
- `regression trigger`: triggered when quality or efficiency drops below baseline

#### Inputs

- trajectory summaries
- branch outcomes
- failure classifications
- evidence references
- quality metrics
- efficiency metrics
- human feedback
- skill usage records

#### Outputs

- skill candidate updates
- routing heuristic updates
- knowledge summary updates
- evaluation baseline updates

#### Guards

- champion/challenger comparison
- regression detection
- limited-scope rollout
- disable-on-regression

### 3.3 Response to Claude issue 2: CTS cost is not bounded

Accepted.

`CTS` needs a first-class exploration budget model.

Planned refinement:

#### Exploration Budget Dimensions

- max active branches per stage
- max total branches per run
- max compare calls per decision cycle
- max token budget for route comparison
- max wall-clock exploration budget

#### Pruning Criteria

- quality lower bound
- efficiency lower bound
- evidence sufficiency failure
- repeated failure signature
- budget exhaustion

#### Route Comparison Strategy

- compare only shortlisted branches
- use cheap heuristics before expensive model-based comparison
- permit staged escalation from lightweight scoring to heavy evaluation

This turns `CTS` from a concept into a controllable search system.

### 3.4 Response to Claude issue 3: Task View reconstruction is hidden risk

Accepted.

`Context OS` must be elevated from support language to architecture contract.

Planned refinement:

#### Task View Assembly Principle

Task View should be built from ordered layers:

1. task contract core
2. current stage state
3. active branch state
4. must-keep evidence
5. relevant memory slices
6. relevant knowledge slices
7. local execution budget

#### Reconstruction Policy

- stage-aware selection first
- evidence-first before narrative history
- branch-local context before global history
- retrieval and summarization under explicit token budgets

#### Reconstruction Validation

- capture what context was shown to the model
- measure downstream route quality
- detect missing-evidence failures
- compare alternative reconstruction policies offline

### 3.5 Response to Claude issue 4: three-repository boundaries may blur

Accepted.

The current layered ownership is directionally correct, but it needs sequence validation.

Planned refinement:

- add a cross-repository run sequence diagram
- define which repository owns:
  - storage
  - semantics
  - execution policy
  - evaluation policy
  - harness policy templates

Working boundary proposal:

- `agent-kernel` owns durable mechanics and generic ledger storage
- `hi-agent` owns semantics, evaluation logic, and routing/evolution policy
- `agent-core` owns environment capability supply and integration adapters

Important note:

`Trajectory Ledger` storage may live in kernel, while trajectory semantics live in hi-agent. This is acceptable if the contract is event- and schema-driven rather than object-sharing and ad hoc queries.

### 3.6 Response to Claude issue 5: LLM Gateway roles may be over-designed

Partially accepted.

Planned refinement:

- define only coarse public roles in kernel
- keep detailed task-specific capability mapping in hi-agent routing logic

Likely coarse public classes:

- `heavy_reasoning`
- `light_processing`
- `evaluation`

Then `hi-agent` may internally distinguish:

- route generation
- route comparison
- summarization
- review
- writing

without forcing kernel public API to encode all of them.

### 3.7 Response to Claude issue 6: human involvement is too passive

Accepted.

TRACE must explicitly model `Human Gates`.

Planned refinement:

- `Human Gate A`: task contract correction
- `Human Gate B`: route direction choice for ambiguous high-cost exploration
- `Human Gate C`: intermediate artifact review and edit
- `Human Gate D`: final package approval

The effect on CTS must be defined:

- human may revise task contract
- human may prune or prioritize branches
- human may inject new evidence or edit artifacts

### 3.8 Response to Claude issue 7: research domain may bias the architecture

Accepted as a validation warning, not a direction change.

Planned refinement:

- keep scientific research as phase-1 primary validation
- add one shadow validation scenario from a non-research enterprise task

Suggested shadow domain:

- enterprise data analysis and reporting task

This is close enough to reuse much of TRACE while exposing different stage and evaluation behavior.

## 4. New Architecture Commitments Before Implementation

Before implementation begins, the architecture should be extended with four concrete deliverables.

### Deliverable 1: Evolve Specification

Must define:

- triggers
- input schema
- output schema
- promotion rules for skill candidates
- regression guards

### Deliverable 2: CTS Budget Model

Must define:

- branching limits
- comparison limits
- pruning rules
- route scoring strategy
- exploration stop conditions

### Deliverable 3: Task View Contract

Must define:

- assembly layers
- selection policy
- evidence retention rules
- token budgeting
- replay and validation mechanism

### Deliverable 4: Cross-Repository Run Sequence

Must define:

- exact repository responsibilities across one full run
- event and data exchange boundaries
- kernel requirements vs upper-layer semantics
- harness invocation ownership

## 5. Additional Explicit Demands on `agent-kernel`

The reviews imply several additional demands that should be communicated to the kernel team.

### 5.1 Kernel must support bounded-context replayability

Needed capabilities:

- persist exact Task View references used per model call
- persist branch and stage identifiers
- persist evidence references shown to the model

This is necessary for:

- debugging
- quality evaluation
- evolution validation

### 5.2 Kernel must support branch-aware ledgering

Needed capabilities:

- branch id
- parent branch id
- stage id
- branch state
- failure category
- compare score references

### 5.3 Kernel must support async long-job coordination

Needed capabilities:

- waiting on external tasks
- wakeup by callback or signal
- preserving working-state references across wakeup

### 5.4 Kernel should expose minimal but sufficient APIs

Kernel should not own:

- domain-specific reward logic
- domain-specific success semantics
- direct research-only abstractions

Kernel should own:

- durable mechanics
- generic ledger substrate
- LLM Gateway abstraction
- orchestration primitives

## 6. Recommended Next Action

Implementation should remain paused.

The next work should be:

1. revise the architecture doc with the accepted review points
2. add one dedicated `Evolve` section
3. add one dedicated `CTS budget` section
4. add one dedicated `Task View / Context OS` section
5. add one cross-repository sequence diagram
6. then freeze vocabulary and write the implementation plan

## 7. Bottom Line

The reviews do not invalidate TRACE.

They reveal that the architecture is directionally strong but currently weakest exactly where it claims the most differentiation:

- evolution
- bounded multi-trajectory exploration
- context reconstruction
- repository interaction contracts

That is useful feedback and should be treated as architecture-shaping, not implementation-detail feedback.

