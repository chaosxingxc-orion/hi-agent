# Package Consolidation Decisions — Wave 31 (2026-05-02 directive)

This document records the resolutions adopted under the W31 H-track directive
(see directive §4 B-6) for the six confusable-package-name pairs and the four
hidden findings (H-1', H-2', H-3', H-13') surfaced during structural audit.

These decisions are **the canonical source of intent**; the actual code moves
land across waves W31 (this wave, H-track), W32 (Wave B follow-up), and later.

## Per-pair resolutions

| Pair | Resolution | Why |
|---|---|---|
| `skill` / `skills` | Rename `hi_agent/skills/` → `hi_agent/skill_runtime/`; deprecation shim at `hi_agent/skills/` for one wave | Distinguishes lifecycle (`skill`) from runtime strategy (`skill_runtime`) |
| `profile` / `profiles` | Merge `hi_agent/profile/` into `hi_agent/profiles/directory.py`; deprecation shim | profiles has 47 imports vs profile's 10 — profiles is canonical |
| `state` / `state_machine` | Rename `hi_agent/state/` → `hi_agent/run_state_store/` | state has 1 file (RunStateSnapshot/Store); state_machine has formal FSM definitions |
| `failures` / `errors` | Move `hi_agent/errors/categories.py` → `hi_agent/contracts/errors.py`; document split rule | errors = contract-boundary typed errors; failures = runtime trace failures |
| `ops` / `operations` | Rename `hi_agent/ops/` → `hi_agent/operator_tools/` | operations has 150+ imports (canonical long-running ops); ops is operator-facing tools (doctor/diagnostics) |
| `runtime` / `runtime_adapter` / `harness` | (Wave B handles) Move `hi_agent/harness/` → `hi_agent/runtime/harness/`; drop `runtime_adapter/__init__.py:3-7 from agent_kernel.testing import ...` | Three-namespace problem reduces to two; testing imports leak into production |

## Additional hidden findings (H-1', H-2', H-3', H-13')

| Finding | Resolution |
|---|---|
| H-1' (runtime_adapter exports test fixtures) | Move test fixtures to `hi_agent/testing/__init__.py` only; drop from `runtime_adapter/__all__`. Wave B subtask. |
| H-2' (`hi_agent/ops/__init__.py` is 0 bytes) | After H.5 rename to `operator_tools/`, the new init must carry a docstring distinguishing it from `operations`. |
| H-3' (`hi_agent/experiment/` is 51-LOC permanent shim) | Audit external consumers; if zero, delete entire pkg + permanent allowlist row. Wave B subtask. |
| H-13' (`task_mgmt/task_view/task_decomposition` triplet) | Defer to W32 — not in directive scope; document as future work. |

## Sequencing

1. **W31 (current)** — H.0 (this doc), H.7 (delete agent_server shells), H.8 (gate).
   These are non-disruptive: only the agent_server shells land; no `hi_agent/`
   structural moves in W31.
2. **W32 / Wave B** — execute the per-pair resolutions above. Each rename or
   merge ships with a deprecation shim for one wave (W33), tracked via
   `docs/governance/allowlists.yaml` with `expiry_wave: 33`.
3. **W33** — drop the deprecation shims; refresh `docs/governance/dead-code-audit-*.md`.

## Non-goals (W31 H-track scope)

- No `hi_agent/` package renames or moves in W31. Those land in W32.
- No imports rewrites in callers; W31 only touches agent_server shells.
- The triplet `task_mgmt` / `task_view` / `task_decomposition` is **out of scope**
  for the 6-pair directive and is recorded as W32+ future work.
