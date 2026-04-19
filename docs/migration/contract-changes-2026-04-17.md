# Contract Change Notice — 2026-04-17

**Audience**: Research Intelligence App team and any downstream consumers of hi-agent APIs  
**Effective**: 2026-04-17 (W1 Runtime Truth MVP)  
**Breaking level**: Additive (safe to deploy without consumer changes) except where marked **breaking in prod**

---

## Breaking / Additive Changes

### RunResult.execution_provenance (additive)

- **Type**: `ExecutionProvenance | None`
- **New in**: W1 Runtime Truth MVP (HI-W1-D3-001)
- **Contract version**: `"2026-04-17"`
- **Impact**: New field added to `RunResult`. Existing consumers unaffected — field is `None` in dev-smoke mode and populated in local-real / prod-real mode.

`ExecutionProvenance` shape:

```json
{
  "runtime_mode": "prod-real",
  "fallback_used": false,
  "contract_version": "2026-04-17",
  "llm_mode": null,
  "kernel_mode": null,
  "capability_mode": null
}
```

`llm_mode`, `kernel_mode`, `capability_mode` are deferred to W2 — consumers should treat `null` as "not yet available" rather than "unknown".

**Downstream action**: Consumers that deserialize `RunResult` should accept the new optional field. No structural changes required.

---

### GET /manifest — New fields (additive)

Three new fields added to the `/manifest` response:

| Field | Type | Description |
|-------|------|-------------|
| `runtime_mode` | `"dev-smoke" \| "local-real" \| "prod-real"` | Current runtime classification |
| `evolve_policy` | `{mode, effective, source}` | Active evolve policy and whether evolution is effectively enabled |
| `provenance_contract_version` | `"2026-04-17"` | Version of the provenance contract in effect |

Example response (prod-real):

```json
{
  "runtime_mode": "prod-real",
  "evolve_policy": {
    "mode": "auto",
    "effective": false,
    "source": "env"
  },
  "provenance_contract_version": "2026-04-17"
}
```

**Note on `runtime_mode` change**: The previous value `"platform"` is replaced by the tri-state above. Consumers checking `manifest.runtime_mode == "platform"` must update their comparisons.

**Downstream action**: Update `/manifest` consumers to handle the three new fields. Update any `runtime_mode == "platform"` checks to use the new tri-state values.

---

### POST /skills/{id}/promote, /skills/evolve, /memory/consolidate — RBAC (breaking in prod)

- **Ticket**: HI-W1-D5-001
- **Change**: These three routes now require `role=approver` JWT claim in prod-real mode.
- **Dev bypass**: Still accessible without auth in dev-smoke mode (no token required).

| Mode | Behavior |
|------|----------|
| `dev-smoke` | No auth required (dev bypass active) |
| `local-real` | No auth required (dev bypass active) |
| `prod-real` | `role=approver` JWT required; returns `403` otherwise |

**Downstream action**: The Research Intelligence App team must obtain and include an approver-role JWT token when calling these routes from prod environments. Requests without auth will receive `403 Forbidden` starting from this version.

---

## Previously Deferred Items (status unchanged)

| Item | Status |
|------|--------|
| P2-2 Neo4j integration | Permanently declined — JSON-backed L3 covers all graph ops at our scale |
| P3-2 `calibrate()` method | Deferred; no timeline yet |
| `ExecutionProvenance.llm_mode` | Deferred to W2 |
| `ExecutionProvenance.kernel_mode` | Deferred to W2 |
| `AsyncRunResult.execution_provenance` | Deferred to W2+ |

---

## Summary table

| Change | Type | Consumer action required |
|--------|------|--------------------------|
| `RunResult.execution_provenance` | Additive | Accept new optional field |
| `/manifest.runtime_mode` tri-state | Additive + value change | Update `== "platform"` comparisons |
| `/manifest.evolve_policy` | Additive | Handle new nested field |
| `/manifest.provenance_contract_version` | Additive | No action needed |
| Mutation routes RBAC in prod | Breaking in prod-real | Add approver JWT to prod calls |
