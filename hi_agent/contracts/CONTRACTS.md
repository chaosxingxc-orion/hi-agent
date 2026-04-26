# Contract Spine Precedence Rule (Wave 10.6)

## The Rule

When both `exec_ctx` and explicit kwargs supply the same spine field, **explicit kwargs win**.
`exec_ctx` fills only fields the caller did not specify (or specified as empty string / None).

## Pattern

```python
# Right — kwargs win
tenant_id = tenant_id or (exec_ctx.tenant_id if exec_ctx else "")

# Wrong — exec_ctx wins (forbidden after Wave 10.6)
tenant_id = (exec_ctx.tenant_id if exec_ctx else "") or tenant_id
```

## Rationale

- Caller intent is most specific; exec_ctx is a propagation convenience.
- ArtifactRegistry.create() already uses kwargs-wins (Wave 10.5 post-integration fix).
- Uniform rule: "kwargs always win, exec_ctx fills gaps" is the mental model.

## Scope

Applies to all 11 durable writers as of Wave 10.6:
RunStore, RunQueue, IdempotencyStore, EventStore, GateStore, GateAPI,
TeamRunRegistry, TeamEventStore, FeedbackStore, ArtifactRegistry/Ledger, op_store.
