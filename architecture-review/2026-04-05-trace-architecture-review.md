# TRACE Enterprise Agent Architecture Review

> Status: Architecture review draft
> Scope: Enterprise agent architecture, validated first in scientific-research tasks
> Repository: `D:\chao_workspace\hi-agent`

## 1. Positioning

`hi-agent` is not a "research agent". It is an enterprise agent architecture for long-running task execution.
Scientific-research tasks are only the first validation domain because they naturally contain:

- long task horizons
- multi-stage execution
- strong evidence requirements
- repeated exploration and backtracking
- writing and delivery packaging
- clear quality and efficiency feedback

The architecture is designed for enterprise agents in general, then validated first on research workflows.

## 2. Core Abstraction

The proposed architecture is:

`TRACE = Task -> Route -> Act -> Capture -> Evolve`

Each phase is defined as follows:

- `Task`: define the task contract, not just the user prompt
- `Route`: perform constrained multi-trajectory exploration and path selection
- `Act`: execute against real environments through a controlled harness
- `Capture`: persist structured evidence, outcomes, failures, and trajectory state
- `Evolve`: improve quality and efficiency through feedback-driven updates

This architecture differs from ReAct in one central way:

- ReAct centers on a short-horizon reasoning loop
- TRACE centers on a long-horizon durable task run

## 3. Design Constraints

The architecture is built under two hard constraints:

### Constraint A: The model is the cognitive driver, but its context window is bounded

Implications:

- the agent cannot be modeled as an infinitely growing conversation
- long-term execution must not depend on keeping full history inside one prompt
- every model call must receive a reconstructed `Task View`, not the whole history

### Constraint B: Model capabilities will keep evolving, and providers will keep changing

Implications:

- the system must maximize model capability usage
- the system must not bind its core cognition to any one provider or API dialect
- provider-specific details must be hidden behind a stable `LLM Gateway`

## 4. First-Class Concepts

The review version keeps the number of first-class concepts intentionally small.

- `Task`: goal, constraints, acceptance criteria, budget, deadline, risk boundaries
- `Run`: durable task instance with checkpoint, wait, resume, recovery
- `Route`: candidate path generation, comparison, and selection
- `Act`: controlled environment operations through harness
- `Capture`: evidence, metrics, failure reasons, stage updates, branch outcomes
- `Evolve`: feedback-driven updates to strategy, skill, knowledge, and evaluation
- `Memory`: working and episodic experience
- `Knowledge`: stable facts, methods, rules, and enterprise assets understanding
- `Skill`: reusable procedural unit crystallized from successful trajectories
- `Feedback`: business outcomes, human review, experiment results, quality and efficiency signals

## 5. Constrained Trajectory Space

The key mechanism behind TRACE is:

`CTS = Constrained Trajectory Space`

CTS defines how the agent explores multiple possible trajectories without falling into unstructured trial-and-error.

CTS contains two layers:

- `Stage Graph`: what stages exist, what transitions are legal, what actions are allowed in each stage
- `Trajectory Tree`: what branches have actually been explored for the current run

This gives the model a structured cognitive frame:

- what stage it is in
- what candidate routes remain
- which routes failed
- why they failed
- which routes succeeded
- which routes succeeded but were too slow or too costly
- what budget remains for further exploration

### 5.1 CTS Overview

```text
Task Contract
    |
    v
Constrained Trajectory Space (CTS)
    |
    +-- Stage Graph
    |      |
    |      +-- Stage S1: Understand / Frame Task
    |      +-- Stage S2: Gather Assets / Evidence
    |      +-- Stage S3: Build / Experiment / Analyze
    |      +-- Stage S4: Synthesize / Write / Package
    |      +-- Stage S5: Review / Revise / Finalize
    |
    +-- Trajectory Tree
           |
           +-- Branch A: high quality, medium cost
           +-- Branch B: failed due to missing evidence
           +-- Branch C: succeeded but low efficiency
           +-- Branch D: pending external callback
```

### 5.2 Why CTS matters

Without CTS:

- the agent only has an opaque loop
- failure signals stay local to one step
- exploration is hard to compare and optimize

With CTS:

- exploration becomes explicit
- failures become structured data
- route quality can be compared
- route efficiency can be optimized
- skills can be extracted from repeated successful branches

## 6. Architecture Overview

### 6.1 Layered Architecture

```text
+----------------------------------------------------------------------------------+
|                                 Enterprise Task Inputs                           |
|    user instructions | task requests | business constraints | feedback signals   |
+----------------------------------------------------------------------------------+
                                         |
                                         v
+----------------------------------------------------------------------------------+
|                                     TRACE Agent                                  |
|----------------------------------------------------------------------------------|
|  Task Runtime    | Route Engine     | Evolution Engine                           |
|  - task contract | - CTS routing    | - feedback ingestion                       |
|  - stage control | - branch compare | - skill crystallization                    |
|  - completion    | - explore/prune  | - knowledge updates                        |
+----------------------------------------------------------------------------------+
         |                     |                     |
         |                     |                     |
         v                     v                     v
+----------------------------------------------------------------------------------+
|                               Cognitive Support Plane                            |
|----------------------------------------------------------------------------------|
|  Context OS           | Memory System        | Knowledge System   | Skill System  |
|  - task view build    | - working memory     | - semantic knowledge| - reusable    |
|  - context budgeting  | - episodic memory    | - asset knowledge   |   procedures  |
|  - evidence selection | - run summaries      | - procedural methods | - versions    |
+----------------------------------------------------------------------------------+
                                         |
                                         v
+----------------------------------------------------------------------------------+
|                                LLM Gateway Plane                                 |
|----------------------------------------------------------------------------------|
|  unified capability contract -> provider/model routing -> inference abstraction   |
|  examples: reason / judge / summarize / extract / write / review / compare        |
+----------------------------------------------------------------------------------+
                                         |
                                         v
+----------------------------------------------------------------------------------+
|                                  Harness Plane                                   |
|----------------------------------------------------------------------------------|
|  IT systems | data systems | file systems | code env | browser | experiment env  |
|  enterprise assets | documentation assets | writing assets | packaging tools      |
|                                                                                  |
|  governed by: authz, timeout, retry, audit, evidence capture, async callback     |
+----------------------------------------------------------------------------------+
                                         |
                                         v
+----------------------------------------------------------------------------------+
|                              Durable Runtime Plane                               |
|----------------------------------------------------------------------------------|
|  checkpoint | resume | wait/wakeup | watchdog | recovery | event log | tracing   |
|  trajectory ledger | metrics | health probe | long-running task orchestration     |
+----------------------------------------------------------------------------------+
```

### 6.2 Runtime Loop

```text
Task Contract
    |
    v
Build Current Task View
    |
    v
Route in CTS
    |
    +--> choose best next branch
    +--> or open new exploratory branch
    +--> or prune failed/inefficient branches
    |
    v
Act through Harness
    |
    v
Capture Evidence and Outcome
    |
    +--> update stage state
    +--> update trajectory tree
    +--> update metrics
    +--> trigger wait/resume if external dependency exists
    |
    v
Evolve
    |
    +--> update skill candidates
    +--> update knowledge summaries
    +--> update routing heuristics
    +--> update evaluation baselines
    |
    v
Next Task View
```

## 7. Knowledge, Memory, Data Systems, and IT Systems

These concepts must be explicit in the architecture review because they represent different roles.

### 7.1 Memory

Memory stores what the agent experienced.

- `Working Memory`: active run state, current hypotheses, pending branches, stage-local notes
- `Episodic Memory`: prior runs, prior failures, prior successful trajectories, prior reviews

### 7.2 Knowledge

Knowledge stores what the agent knows in a relatively stable form.

- `Semantic Knowledge`: domain facts, methods, document abstractions, enterprise rules
- `Procedural Knowledge`: abstracted procedures, reusable execution templates, skill schemas

### 7.3 Data Systems

Data systems are external operational and analytical sources:

- databases
- data warehouses
- vector stores
- experiment result stores
- object stores

They are not "memory". They are harness-accessible enterprise resources.

### 7.4 IT Systems

IT systems are operational systems that the agent must act upon:

- workflow tools
- code repositories
- office systems
- business systems
- publishing or delivery preparation tools

They are also accessed through the harness, not directly by the model.

### 7.5 Boundary Summary

```text
Memory / Knowledge = internal evolving assets
Data Systems / IT Systems = external enterprise environments
Harness = controlled bridge between the two
```

## 8. Harness in TRACE

Harness is a required architectural component, not an optional adapter layer.

Its responsibilities are:

- unify all environment operations behind stable contracts
- enforce permission and safety boundaries
- provide retries, timeout, rate, and budget controls
- collect execution evidence for Capture
- support async waits and external callbacks for long-running tasks
- normalize execution outputs for routing and evaluation

In short:

```text
LLM decides
Harness executes
Runtime persists
Ledger records
Evolution improves
```

## 9. Long-Running 7x24 Execution

The architecture must support real long-horizon work. The run is the persistent subject, not the model session.

Required properties:

- `Durable Run`: each task run has an explicit lifecycle
- `Checkpoint`: any phase can be resumed after interruption
- `Wait State`: the run can pause for experiments, external systems, or human review
- `Wakeup`: asynchronous events can resume the run
- `Watchdog`: detect timeout, no-progress, deadlock, repeated failures, budget exhaustion
- `Recovery`: recover with evidence, not only blind retry
- `Rebuildable Task View`: context is reconstructed from durable state

This is why the architecture must rely on a durable runtime rather than a pure chat loop.

## 10. Responsibilities by Repository

### 10.1 `hi-agent`

Owns the enterprise-agent architecture itself:

- TRACE abstraction
- CTS definition
- task contract model
- routing policy
- evolution policy
- skill crystallization logic
- evaluation logic

### 10.2 `agent-kernel`

Owns the durable kernel capabilities:

- durable task runtime
- event truth and trajectory ledger substrate
- checkpoint/wait/resume/recovery
- health, watchdog, tracing
- LLM Gateway contract
- stage/run orchestration primitives

### 10.3 `agent-core`

Owns the application and environment capability supply:

- session and context resources
- workflow and tool resources
- system operation resources
- data and asset access patterns
- operator-facing building blocks for harness integration

## 11. Explicit Requirements for `agent-kernel`

The optimizing kernel team should treat the following as explicit architectural requirements from `hi-agent`.

### 11.1 Runtime Requirements

- the kernel must treat `Run` as the durable execution subject
- the kernel must support long waits and later wakeups
- the kernel must support task checkpoint and full resume
- the kernel must support watchdog detection for no-progress and timeout states
- the kernel must support evidence-based recovery, not only retry

### 11.2 LLM Requirements

- the kernel must expose a stable `LLM Gateway`
- the gateway must hide provider-specific API details
- the gateway must support model routing by task role or cognitive role
- the gateway must not force the upper layer to bind to a single provider
- the gateway contract should focus on capability roles, not provider request shapes

Recommended upper-layer usage pattern:

```text
hi-agent asks for capability role
agent-kernel routes to provider/model implementation
```

Example capability roles:

- `reason`
- `judge`
- `summarize`
- `extract`
- `write`
- `review`
- `compare_routes`

### 11.3 Context Requirements

- the kernel must not assume full-history prompting
- the kernel should support bounded `Task View` assembly inputs
- the kernel should preserve durable state separately from model context
- the kernel should allow deterministic replay of what context was shown to the model

### 11.4 Trajectory Requirements

- the kernel must support structured trajectory recording
- the kernel must distinguish branches, stages, outcomes, and failure reasons
- the kernel must allow branch comparison metrics such as quality, latency, and cost
- the kernel should support explicit branch states: active, pruned, failed, succeeded, waiting

### 11.5 Harness Requirements

- kernel execution primitives must support harness-mediated actions
- kernel events must capture action inputs, outputs, evidence references, and execution metadata
- kernel must support async harness callbacks for long-running external jobs

### 11.6 Evaluation Requirements

- kernel events and state should expose enough information to compute quality and efficiency metrics
- kernel should not hard-code business evaluation logic
- kernel should provide clean extension points for upper-layer evaluation and evolution logic

## 12. First Validation Scope

The first validation scope is a research-domain closed loop, but the architecture remains enterprise-general.

The validation run may include:

- task understanding and decomposition
- literature and asset retrieval
- data analysis or experiment execution
- synthesis and paper writing
- supplementary material generation
- submission package generation
- human review feedback ingestion

The first version stops at:

- generating a reviewable submission package

The first version does not require:

- direct autonomous submission into an external submission system

## 13. Review Invariants

The following invariants should remain stable during review and later implementation:

- the durable subject is the `Run`, not the chat thread
- model context is bounded and must be reconstructed
- provider binding must be hidden behind `LLM Gateway`
- exploration must happen inside `CTS`
- environment operations must pass through `Harness`
- trajectory must be captured as structured data
- evolution must optimize route quality and efficiency, not only prompt wording

## 14. Next Step After Review

After architecture approval:

1. freeze TRACE and CTS vocabulary
2. map `hi-agent` concepts to `agent-kernel` contracts
3. identify missing kernel capabilities
4. define first implementation plan for the research validation loop

