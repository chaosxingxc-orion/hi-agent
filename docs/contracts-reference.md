# Contracts Reference

Extracted from CLAUDE.md for readability. These are data contract definitions — not behavioral rules.

---

## Contract Field Consumption

| Level | Meaning |
|-------|---------|
| `ACTIVE` | Drives execution behavior in the default TRACE pipeline |
| `PASSTHROUGH` | Stored and returned; consumption is the business agent's responsibility |
| `QUEUE_ONLY` | Used for scheduling only; not consumed during stage execution |

`goal`, `task_family`, `risk_level`, `constraints`, `acceptance_criteria`, `budget`, `deadline`, `profile_id`, `decomposition_strategy` → **ACTIVE**

`environment_scope`, `input_refs`, `parent_task_id` → **PASSTHROUGH**

`priority` → **QUEUE_ONLY**

---

## Human Gate Types

| Gate | Trigger |
|------|---------|
| **A** `contract_correction` | Modify task contract mid-run |
| **B** `route_direction` | Guide path selection |
| **C** `artifact_review` | Review/edit outputs |
| **D** `final_approval` | Gate high-risk final actions |

---

## Standard Failure Codes

`missing_evidence` · `invalid_context` · `harness_denied` · `model_output_invalid` · `model_refusal` · `callback_timeout` · `no_progress` · `contradictory_evidence` · `unsafe_action_blocked` · `exploration_budget_exhausted` · `execution_budget_exhausted`

Defined as `hi_agent.failures.taxonomy.FailureCode` (StrEnum).
