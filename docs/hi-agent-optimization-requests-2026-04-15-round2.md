# hi-agent Optimization Requests — Round 2

**From:** Research Intelligence Application Team  
**To:** hi-agent Team  
**Date:** 2026-04-15  
**Re:** Follow-up after commit 42c9836 delivery review  
**References:**
- `docs/hi-agent-optimization-requests.md` (Round 1)
- `docs/hi-agent-optimization-response-2026-04-15.md` (hi-agent reply)
- Architecture spec: `docs/superpowers/specs/2026-04-15-research-intelligence-app-design.md`

---

## Acknowledgement of Round 1 Delivery

10 of 12 requests were delivered in commit 42c9836. The following Round 1 items are accepted as closed:

| ID | Item | Verdict |
|---|---|---|
| P0-1 | RunExecutorFacade start/run/stop | Accepted |
| P0-2 | check_readiness() | Accepted |
| P1-1 | profile_id-scoped L3 path isolation | Accepted (see caveat in §1 below) |
| P1-2 | RawMemoryStore L0 JSONL + ShortTermMemoryStore L1 | Accepted (see §2) |
| P1-3 | SkillLoader.load_dir() + get_skill() contract | Accepted |
| P1-4 | RestartPolicyEngine retry/reflect/escalate | Accepted (see §3) |
| P2-1 | TierRouter + TierAwareLLMGateway | Accepted (see §4) |
| P2-3 | dispatch_subrun / await_subrun | Accepted (see §5) |
| P3-1 | SkillLoader A/B versioning get_skill(version=) | Accepted |
| P2-2 (Neo4j declined) | LongTermMemoryGraph JSON-backed | Accepted |

Two Round 1 items remain open:

- **P3-2 (TierRouter calibrate())** — Indefinitely deferred pending quality scoring. We accept the deferral.
- **P1-5 (Human Gate)** — Partially delivered. **Critical gap remains.** See §1 below.

---

## Round 2 Requests

Issues are ordered by impact on the research pipeline. **Critical** items block pipeline execution. **High** items degrade research quality. **Medium** items cause operational problems at scale.

---

### C-1 (Critical) — Human Gate Must Block Stage Execution

**What was delivered:** `register_gate()` / `resume()` as a lifecycle notification API. Gate state is persisted to checkpoint.

**What the response stated:** "the gate does not yet automatically block stage execution. The current implementation is a lifecycle notification API — the caller controls the pause/resume flow."

**Why this is critical:** The research pipeline uses Gate D (final_approval) at every phase transition:

```
Survey phase completes → PI Agent registers gate → [execution must pause]
→ Human reviews output → human calls resume(decision="approved")
→ Analysis phase begins
```

Without automatic blocking, the pipeline races past the gate and starts the next phase before the human responds. The research application team cannot implement this externally without reimplementing the run lifecycle internally — which would violate the scope boundary.

**What we need:** When `register_gate()` is called inside an active run, stage execution suspends at the next stage boundary until `resume()` is called with a valid decision. The run must be in a "gate_pending" state, observable via `RunStateSnapshot`.

**Specifically:**
- `register_gate()` sets an internal flag that prevents the next stage from starting
- The run enters a `gate_pending` state (observable in `RunStateStore`)
- `resume(gate_id, decision)` clears the flag, records the decision, and allows execution to continue
- If `decision == "backtrack"`, the run terminates the current phase and the caller handles re-dispatch
- Gate state survives process restart (already delivered via checkpoint — keep that)

**Acceptance criteria:**
1. A test confirms that calling `register_gate()` during stage N prevents stage N+1 from starting
2. Calling `resume(decision="approved")` allows stage N+1 to start
3. Calling `resume(decision="backtrack")` causes the run to terminate the current phase cleanly
4. `RunStateSnapshot.status` reflects `"gate_pending"` while waiting

---

### C-2 (Critical) — dispatch_subrun Must Accept a Task Goal

**What was delivered:** `dispatch_subrun(agent, profile_id, strategy, restart_policy)` encodes the sub-run goal as:
```python
goal=f"agent={agent} profile={profile_id} strategy={strategy} restart_policy={restart_policy}"
```

**Why this is critical:** The sub-run receives a metadata string as its goal, not an actual task instruction. In the Writing Team:

```python
handle = pi_run.dispatch_subrun(
    agent="author",
    profile_id="proj-001",
    strategy="sequential",
    restart_policy="reflect(2)",
)
```

The Author Agent's actual task is "Write a full IMRaD-structured LaTeX draft incorporating these survey findings and experiment results: [...]". That instruction is never passed. The sub-run has no content to act on.

**What we need:** Add a `goal` parameter to `dispatch_subrun()`:

```python
def dispatch_subrun(
    self,
    agent: str,
    profile_id: str,
    strategy: str = "sequential",
    restart_policy: str = "reflect(2)",
    goal: str = "",                    # ← add this
) -> SubRunHandle:
```

The `goal` must be forwarded as the `TaskContract.goal` of the child run, not embedded in metadata.

**Acceptance criteria:**
1. `dispatch_subrun(..., goal="Write a LaTeX draft of the introduction section.")` produces a sub-run whose `contract.goal` is exactly that string
2. A test confirms that sub-run output reflects the content of the supplied goal

---

### H-1 (High) — L3 Memory Needs Semantic Search, Not Keyword Overlap

**What was delivered:** `LongTermMemoryGraph.search(query)` uses keyword overlap — lowercases both query and node content, counts matching words.

**Why keyword search fails for research:** Academic concepts share few exact words across related ideas:

- "attention mechanism" vs "multi-head self-attention" — zero keyword overlap, deeply related
- "gradient vanishing" vs "residual connection" — solving the same problem, no shared keywords
- "BLEU score" vs "translation quality" — semantically equivalent, no shared terms

A PI Agent querying its cross-project memory for "efficient attention variants" will miss all nodes tagged with "flash attention", "linear attention", "sparse attention" unless those exact words appear in the query.

**What we need:** A search backend that supports semantic similarity, not just keyword overlap. Options in order of implementation cost:

1. **(Preferred)** Embedding-based search: Store a vector for each node on `add_node()`, use cosine similarity for `search()`. Accept an embedding function as a constructor parameter (keeps the class dependency-free). Fall back to keyword search when no embedding function is configured.

2. **(Acceptable)** TF-IDF search: Maintain an inverted index across the graph. Significantly better recall than exact keyword match, zero external dependencies.

**Acceptance criteria:**
- `search("attention mechanism")` returns nodes containing "multi-head self-attention" and "transformer encoder" when those nodes exist in the graph
- The embedding function is injected, not hard-coded (e.g., `LongTermMemoryGraph(embedding_fn=...)`)
- Falls back to keyword search when `embedding_fn` is None

---

### H-2 (High) — LongTermMemoryGraph Does Not Auto-Load on Instantiation

**What was delivered:** `LongTermMemoryGraph.__init__` sets up paths and empty in-memory structures. `load()` must be called explicitly by the caller.

**Why this is a problem:** The PI Agent's cross-project memory (P1 evolution principle) is the primary asset that grows across projects. If `load()` is not called before the first `add_node()` or `search()`, all previous project knowledge is silently discarded — new nodes are added to an empty graph, then `save()` overwrites the file, erasing all prior knowledge.

The research application team cannot reliably call `load()` because the `LongTermMemoryGraph` is constructed deep inside `SystemBuilder` — its construction is not under our direct control.

**What we need:** `LongTermMemoryGraph.__init__` calls `self.load()` automatically if `self._storage_path` exists. If the file doesn't exist yet (new project), `load()` is a no-op (already the case).

**Acceptance criteria:**
- If `graph.json` exists when `LongTermMemoryGraph(profile_id=...)` is called, its nodes and edges are immediately available without any explicit `load()` call
- A test confirms this: save a graph, construct a new `LongTermMemoryGraph` with the same `profile_id`, verify nodes are present without calling `load()`

---

### H-3 (High) — TierRouter Purpose Vocabulary Does Not Cover Research Agent Roles

**What was delivered:** TierRouter ships with default purposes: `perception`, `control`, `execution`, `evaluation`, `compression`, `routing`, `skill_extraction`.

**Why this is a gap:** Research pipeline agents dispatch LLM calls with purposes like `"survey"`, `"analysis"`, `"lean_proof"`, `"experiment_design"`, `"paper_writing"`, `"peer_review"`. None of these map to the defaults. The `TierAwareLLMGateway` falls back to `"routing"` (medium tier) for any unknown purpose.

This means:
- PI Agent calls — which require `strong` tier — fall back to `medium`
- Survey Agent calls — which should use `light` for paper fetching and `medium` for synthesis — all hit `medium`
- Lean proof calls — which require `strong` — hit `medium`

**What we need:** Either:

1. **(Preferred)** Ship a `ResearchTierDefaults` preset that can be applied to a `TierRouter` instance:

```python
from hi_agent.llm.tier_presets import apply_research_defaults
apply_research_defaults(tier_router)
```

Which sets:
```
pi_agent           → strong (no downgrade)
lean_proof         → strong (no downgrade)
survey_synthesis   → medium
survey_fetch       → light
experiment_design  → medium
experiment_eval    → medium
paper_writing      → strong
peer_review        → strong
```

2. **(Acceptable)** Document clearly in TierRouter's docstring that callers must call `set_tier()` for each domain-specific purpose before use, and provide the above table as the recommended research configuration.

**Acceptance criteria:**
- A `TierRouter` configured with research defaults routes `purpose="pi_agent"` to strong tier and `purpose="survey_fetch"` to light tier
- Callers do not need to set these manually for the research pipeline use case

---

### M-1 (Medium) — RawMemoryStore File Handle Is Never Closed

**What was delivered:** `RawMemoryStore.__init__` opens a file handle when `run_id` and `base_dir` are provided. There is no `close()` method, no `__del__`, and no context manager support.

**Why this matters:** The PI Agent's `RawMemoryStore` is held for the entire project lifecycle — potentially hours or days. In long-running processes, unclosed file handles accumulate. On Windows (the target deployment platform), open file handles also prevent file rotation, backup, and archival operations on the log directory.

**What we need:** Add a `close()` method that flushes and closes the file handle:

```python
def close(self) -> None:
    if self._file is not None:
        self._file.flush()
        self._file.close()
        self._file = None
```

Also implement `__enter__` / `__exit__` for use as a context manager.

**Acceptance criteria:**
- `RawMemoryStore.close()` closes the underlying file handle
- After `close()`, subsequent `append()` calls raise `ValueError` (not silently no-op)
- `RunExecutor` calls `close()` on its `raw_memory` during `stop()` / teardown

---

### M-2 (Medium) — reflect(N) Is Structurally Identical to retry(N)

**What was delivered:** `RestartPolicyEngine._decide()` returns `action="retry"` when `attempt_seq < policy.max_attempts`, and `action=policy.on_exhausted` otherwise. The `reflect` action is only triggered as the `on_exhausted` strategy.

**What was requested:** `reflect(N)` means: on failure, append a self-critique prompt to the agent's context and retry, up to N times. After N reflection attempts, escalate.

**The gap:** The current implementation treats `reflect(N)` as `retry(N)` unless the policy specifically sets `on_exhausted="reflect"`. There is no "reflect for the first N failures, then escalate" behavior. More importantly, when `action="reflect"` is returned, the reflection prompt content is not generated by the engine — the caller receives `action="reflect"` but has no structured feedback from the engine about *what* to reflect on.

**What we need:**

1. `RestartPolicyEngine` should generate a reflection prompt when deciding `action="reflect"`:

```python
@dataclass(frozen=True)
class RestartDecision:
    task_id: str
    action: RestartAction
    next_attempt_seq: int | None
    reason: str
    reflection_prompt: str | None = None   # ← add this
```

The `reflection_prompt` should include: which stage failed, the failure reason, and a structured self-critique instruction ("Identify what went wrong and how to correct it in the next attempt").

2. `RunExecutor` should inject `reflection_prompt` into the context before the next stage attempt when `action="reflect"`.

**Acceptance criteria:**
- A failed run with `restart_policy="reflect(2)"` produces two attempts with distinct reflection prompts injected before each retry
- The reflection prompt includes the failure reason from the previous attempt
- After 2 reflection attempts, the engine escalates

---

### M-3 (Medium) — L0→L2→L3 Consolidation Chain Is Not Connected End-to-End

**What was delivered:**
- L0: `RawMemoryStore` appends `RawEventRecord` to JSONL
- L2: `RunMemoryIndex` (compact pointer-based stage outcome index) + `AsyncMemoryCompressor`
- L3: `LongTermConsolidator` reads from `MidTermMemoryStore` (`DailySummary` objects)

**The gap:** The consolidation chain is:
```
L0 (RawEventRecord JSONL) → ? → L2 (DailySummary) → L3 (MemoryNode graph)
```

The step from L0 raw events → L2 daily summaries is not implemented. `LongTermConsolidator` reads `DailySummary` objects, but nothing converts `RawEventRecord` objects into `DailySummary` objects. This means L3 is only populated from manually created mid-term summaries, not from the actual run logs.

For the PI Agent's research intuition to grow, the full chain must work:
1. Each run appends `RawEventRecord` to L0
2. After run completion, L0 events are condensed into a `DailySummary` (L2)
3. Periodically, `LongTermConsolidator.consolidate()` promotes L2 summaries to L3 graph nodes

**What we need:** A `L0Summarizer` (or similar) that reads a run's L0 JSONL and produces a `DailySummary`:

```python
class L0Summarizer:
    def summarize_run(self, run_id: str, base_dir: Path) -> DailySummary:
        """Read L0 JSONL for run_id, produce a DailySummary for L2."""
```

This does not need to be LLM-backed — a structured extraction of key event types (stage completions, gate decisions, errors, outcomes) is sufficient.

`RunExecutor` should call `L0Summarizer.summarize_run()` at run completion and append the result to the `MidTermMemoryStore`, completing the chain.

**Acceptance criteria:**
- After a run completes, a `DailySummary` entry exists in `MidTermMemoryStore` for that run
- `LongTermConsolidator.consolidate()` can then promote it to L3 graph nodes
- End-to-end test: run → L0 entries exist → L0Summarizer produces DailySummary → consolidate() produces L3 nodes

---

## Summary Table

| ID | Title | Priority | Status |
|---|---|---|---|
| C-1 | Human Gate must block stage execution | Critical | New — blocks pipeline |
| C-2 | dispatch_subrun must accept a task goal | Critical | New — blocks Writing Team |
| H-1 | L3 memory needs semantic search | High | New — degrades PI Agent intelligence |
| H-2 | LongTermMemoryGraph must auto-load on init | High | New — risks erasing cross-project memory |
| H-3 | TierRouter needs research purpose defaults | High | New — incorrect tier routing for all agents |
| M-1 | RawMemoryStore must have close() | Medium | New — resource leak |
| M-2 | reflect(N) must inject reflection prompt | Medium | New — reflect = retry without this |
| M-3 | L0→L2→L3 consolidation chain not connected | Medium | New — PI Agent memory does not grow |

---

## Recommended Delivery Sequence

```
Sprint 1: C-1 (blocking gate) + C-2 (subrun goal)
          → unblocks Writing Team and phase pipeline

Sprint 2: H-2 (auto-load) + H-3 (research tier defaults)
          → prevents silent memory loss, fixes tier routing

Sprint 3: H-1 (semantic search) + M-1 (file handle close)
          → improves research recall quality, fixes resource leak

Sprint 4: M-2 (reflect prompt) + M-3 (L0→L3 chain)
          → completes intelligence evolution loop
```

---

## Items Not Raised in Round 2

The following known limitations are intentionally not raised because the research application team can work around them at the integration layer:

- `skill_dir=None` handling in `RunExecutorFacade.start()` — we will validate before calling
- `success = str(run_result) == "completed"` fragility — we will check `run_result.status` directly if the field exists
- P3-2 (`calibrate()`) deferral — accepted as previously agreed
