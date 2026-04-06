# TRACE Architecture Review Response V1.1

> Inputs reviewed:
> - `From Geimini - V1.1.txt`
> - `From Claude  - V1 .1.txt`
> - `2026-04-05-trace-architecture-review-v1.1.md`

## 1. Overall Conclusion

The V1.1 review outcome is positive.

The reviewers no longer challenge the TRACE direction itself. The shared conclusion is now:

- TRACE is directionally correct
- V1.1 materially improves the architecture
- the remaining work is hardening kernel-level contracts, not rethinking the architecture

This means V1.1 has crossed the line from:

- architecture idea

to:

- architecture baseline that can enter implementation planning after a small number of targeted clarifications

## 2. Consolidated Judgment

### 2.1 What is now considered solid

The following parts are effectively validated by both reviewers:

- `Run` as the durable subject instead of chat history
- bounded-context execution via reconstructed `Task View`
- `CTS` as constrained exploration rather than free-form trial-and-error
- `Harness` as a mandatory execution boundary
- `LLM Gateway` as provider-decoupling infrastructure
- `Evolve` as an explicit subsystem rather than a slogan

### 2.2 What remains weak

The remaining weak points are narrower and more concrete than in V1:

1. evolution governance is still not fully isolated
2. task-view failure handling is still underdefined
3. human gates exist but lack system-trigger conditions
4. evolve itself has no explicit budget model
5. state-machine truth and idempotency contracts are still not explicit enough
6. skill lifecycle is still missing deprecation and conflict handling

## 3. Review-by-Review Response

### 3.1 Response to Gemini V1.1

Gemini's judgment is technically sound:

- the architecture is now strong enough to continue
- it still lacks kernel-hardening before large-scale implementation

The most important accepted points are:

- `Evolve` is still closer to a governed learning plane than a full evolution governance system
- state-machine truth is still missing
- idempotency and side-effect contracts must be promoted to first-class architecture concerns
- repository boundaries are improved but still require strict ownership wording
- CTS still needs more structural controls if it is to stay affordable and not collapse into expensive tree search

I agree with Gemini's strongest warning:

`having Evolve does not automatically mean the system is truly evolvable`

That is the right caution.

### 3.2 Response to Claude V1.1

Claude's second-round review is also technically sound and more implementation-focused.

The most important accepted points are:

- `Evolve` now has structure, but one evolution run should not update evaluation baselines and evaluated objects at the same time
- `Task View` needs completeness checks and degradation behavior
- cross-repository sequence improved, but "assemble model invocation envelope" is still ambiguous
- `Human Gate` needs system-trigger conditions
- `Evolve` itself needs a budget model
- `Skill` needs lifecycle completion beyond promotion

I agree with Claude's central refinement:

`V1.1 is already good enough for implementation planning, but not yet for uncontrolled implementation expansion`

That is the correct read.

## 4. Accepted Changes for V1.1.x

I do not think TRACE needs a V2-level rewrite.

The right next step is a `V1.1.x` hardening pass with six focused additions.

### 4.1 Evolve Change-Scope Isolation

Accepted.

Each evolve execution should declare a `change_scope`.

Examples:

- `routing_only`
- `skill_candidates_only`
- `knowledge_summaries_only`
- `evaluation_baselines_only`

Rule:

- one evolve execution must not update evaluation baselines and evaluated targets in the same change set

This reduces attribution ambiguity.

### 4.2 Task View Completeness Check and Degradation Policy

Accepted.

`Task View` must gain a completeness check before model invocation.

If must-keep information cannot fit in the allowed budget, the system must not silently continue.

Allowed degradation actions:

- pause and trigger a human gate
- fall back to conservative routing
- escalate to a larger-context model tier

This is an architecture-level safeguard, not only an implementation detail.

### 4.3 Human Gate System Triggers

Accepted.

Human gates should remain user-invocable, but they also need system-trigger conditions.

Examples:

- `Gate A`: trigger when task contract becomes inconsistent with newly captured evidence
- `Gate B`: trigger when exploration budget is heavily consumed without a viable branch
- `Gate C`: trigger when intermediate artifact quality is below threshold
- `Gate D`: trigger on final high-risk package approval

### 4.4 Evolve Budget Model

Accepted.

Evolve needs a budget model parallel to CTS.

Suggested controls:

- max runs analyzed per batch evolution
- max LLM calls per evolve execution
- cooldown interval for regression triggers
- max summary tokens consumed during evolution analysis

### 4.5 Skill Lifecycle Completion

Accepted.

The current promotion path is good but incomplete.

Skill lifecycle should be:

- `candidate`
- `provisional`
- `certified`
- `deprecated`
- `retired`

In addition, each skill should eventually carry:

- applicability scope
- preconditions
- forbidden conditions
- evidence requirements
- side-effect class
- rollback or disable policy

### 4.6 Ownership Wording for Task View Assembly

Accepted.

The current wording around "assemble model invocation envelope" is ambiguous.

It should be tightened to:

- `hi-agent` owns semantic selection of Task View contents
- `agent-kernel` owns stable packaging, persistence, replay, and provider transport mapping
- `agent-core` only supplies capabilities and resources

This keeps upper-layer cognition out of the kernel while preserving kernel replayability.

## 5. Additional Hard Problems That Remain Open

These are real issues, but I do not think they should block implementation planning if they are explicitly called out as V1.1.x hardening items.

### 5.1 Formal State Machine

Still missing:

- `RunState`
- `StageState`
- `BranchState`
- `ActionState`
- `WaitState`
- `ReviewState`

This is the single biggest architecture truth gap still open.

### 5.2 Idempotency and Side-Effect Contract

Still too weak.

The architecture will need explicit contracts for:

- identifiers
- dedupe boundaries
- callback idempotency
- side-effect classes
- compensatable vs irreversible actions

Gemini is right that this is not a detail; it is a structural requirement for long-running enterprise execution.

### 5.3 Failure Taxonomy

Still not frozen.

This matters for:

- postmortem quality
- evolve triggers
- branch pruning
- human gate triggers

## 6. Recommended Next Step

The right next step is not a major architecture rewrite.

The right next step is:

`TRACE V1.1.x hardening`

Scope:

1. add evolve change-scope isolation
2. add task-view completeness check and degradation rules
3. add human-gate system triggers
4. add evolve budget model
5. tighten task-view ownership wording
6. sketch formal state-machine and idempotency contracts

After that:

- freeze vocabulary
- start hi-agent to agent-kernel contract mapping
- write the implementation plan

## 7. Bottom Line

V1.1 should be treated as a successful architecture revision.

The remaining feedback is no longer asking:

- "is TRACE the right architecture?"

It is now asking:

- "can TRACE be hardened enough to become a trustworthy kernel-facing system?"

That is a much better place to be.

