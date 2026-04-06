# TRACE Architecture Review Response V1.2

> Inputs reviewed:
> - `From Geimini - V1.2.txt`
> - `From Claude  - V1 .2.txt`
> - `2026-04-05-trace-architecture-review-v1.2.md`

## 1. Overall Conclusion

The V1.2 review outcome is effectively a pass.

Both reviewers now agree on the core points:

- TRACE is directionally correct
- V1.2 is a real hardening step, not a cosmetic revision
- the architecture can move into implementation planning
- only a few small contract refinements remain before vocabulary freeze

This is a materially different position from V1 and V1.1.

## 2. Consolidated Judgment

### 2.1 What is now validated

The following parts are now validated strongly enough to be treated as stable architecture baseline:

- `Run` as the durable subject
- `Task View` reconstruction under bounded context
- `CTS` with explicit exploration budget
- `Harness` as mandatory execution boundary
- `LLM Gateway` as provider-decoupled capability layer
- `Evolve` with trigger modes, change-scope isolation, and budget control
- `Skill` lifecycle as a governed long-term asset
- `Task View` ownership split across `hi-agent / agent-kernel / agent-core`
- runtime truth, idempotency, and side-effect governance as architecture-level concerns

### 2.2 Remaining changes are now small and local

The remaining reviewer requests are no longer architecture-shaping. They are precision-level hardening items:

1. add `succeeded` to `ActionState`
2. extend failure taxonomy with model-layer failures
3. add a side-effect classification boundary principle
4. later, during implementation planning, produce hard tables for runtime arbitration and evolution rollout domains

## 3. Response to Gemini V1.2

Gemini's review is technically sound.

The most important judgment is:

- V1.2 is now implementable within controlled scope
- but it should still not be oversold as a fully closed enterprise evolution kernel

I agree with Gemini on three especially important points:

### 3.1 Evolution is now governable, but not yet fully publishable

Correct.

`change_scope`, version pinning, budgets, and skill lifecycle are now present, but rollout domains and dependency matrices are still not fully written out.

This should be treated as:

- implementation-planning work

not:

- architecture rewrite work

### 3.2 Runtime truth still needs event arbitration tables

Correct.

The state sketch is enough for architecture approval, but not enough for implementation safety.

The missing next-layer artifact is:

- state transition and event arbitration tables

Examples:

- callback vs timeout race
- human gate edits vs existing branches
- `effect_unknown` recovery arbitration

### 3.3 Skill is close to a contract object, but not fully one yet

Correct.

The lifecycle and metadata are now strong enough architecturally, but implementation planning still needs:

- input/output contract
- success contract
- evidence-binding contract
- inheritance of idempotency and side-effect class

## 4. Response to Claude V1.2

Claude's review is also technically sound and more precise at the contract edge.

The most important accepted items are:

### 4.1 `ActionState` should distinguish acceptance from completion

Accepted.

Current gap:

- `acknowledged` means the external system accepted the request
- but does not mean the action is complete

Refinement to make:

```text
prepared -> dispatched -> acknowledged -> succeeded
                                     |-> effect_unknown
                                     |-> failed
```

This is especially important for long-running external jobs.

### 4.2 Failure taxonomy should include model-layer failures

Accepted.

Two additions should be made:

- `model_output_invalid`
- `model_refusal`

These belong in the same taxonomy family as runtime and harness failures because they affect routing, postmortem, and evolve triggers.

### 4.3 Side-effect classification needs a boundary principle

Accepted.

The classification should be based on:

- blast radius and operational impact

not:

- whether the target is technically local or remote

This avoids ambiguity such as shared file systems being "local" in location but "external" in effect.

## 5. What Should Happen Next

The architecture should not be expanded into V1.3.

The correct next move is:

`freeze TRACE at V1.2 with a tiny V1.2.x polish`

That polish should include only:

1. add `succeeded` to `ActionState`
2. add `model_output_invalid` and `model_refusal` to failure taxonomy
3. add one sentence defining side-effect class by blast radius

After that:

- freeze vocabulary
- move into contract mapping
- write implementation plan

## 6. Bottom Line

V1.2 is the first version that both reviewers treat as architecture-complete enough for implementation planning.

That does not mean:

- the enterprise agent problem is solved

It means:

- the architecture is now coherent enough to stop revising concepts and start defining contracts

This is the right transition point.

