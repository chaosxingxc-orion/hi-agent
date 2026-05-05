# W34 Naming Hygiene Closure (W34-NAMING-CLOSE)

**Date:** 2026-05-04
**Wave:** 34
**Disposition source:** docs/upstream-directives/hi-agent-wave34-engineering-expectations-2026-05-04.md §7
**Plan reference:** docs/superpowers/plans/2026-05-04-wave-34-ria-engineering-expectations.md §7
**Predecessor:** docs/governance/package-consolidation-2026-05-02.md (W31 H.0 — six pair resolutions + four hidden findings)

---

## Summary

| ID | Item | Disposition |
|---|---|---|
| H-3' | `hi_agent/experiment/` shim deletion | **CLOSE** — deleted at commit `d694541e` |
| H-13' | task triplet umbrella | **DECLINE** — three structurally distinct concerns |
| H-14' | templates dir consolidation | **CLOSE (no-op)** — already consolidated under one path |

---

## H-3' — Experiment Shim Deletion

**Disposition:** Close
**Commit SHA:** `d694541e` (`[W34-F] H-3' close: delete hi_agent.experiment shim package`)
**Files deleted:** 7 (entire `hi_agent/experiment/` package, ~50 LOC of `warnings.warn` + `from … import *` re-exports)
**Import sites updated:** 1 (`tests/unit/test_operations_module_canonical.py` — assertion inverted from "warns on import" to "raises ModuleNotFoundError on import")
**Production callers:** 0 (verified via Grep prior to deletion; only the assertion test referenced the package)
**Tests verified:** `tests/unit/test_operations_module_canonical.py` — all 3 tests pass post-deletion. Adjacent suites (`test_experiment_backend.py`, `test_evolution_experiment_dataclass.py`) all pass — these reference `hi_agent.operations.backend` and `hi_agent.evolve.contracts` respectively, never the deleted shim.

**Background.** `hi_agent.experiment` was introduced in W11 (Wave 11 platform decoupling — see `docs/migration-guides/wave11-platform-decoupling.md`) as a temporary re-export shim from the legacy "research-vocabulary" package name into the new domain-neutral `hi_agent.operations`. It was scheduled for removal in W12, then explicitly extended to "permanent" status in W30 (`docs/downstream-responses/2026-05-03-w30-delivery-notice.md` §72) when 19 "will be removed in W30" promises were rephrased to retain deprecation warnings without committing to a date. The W31 H.0 doc (`docs/governance/package-consolidation-2026-05-02.md`) authorised: "Audit external consumers; if zero, delete entire pkg + permanent allowlist row. Wave B subtask." W34-F executes that authorisation. No allowlist row needed removing — the shim was tracked via inline `expiry_wave: permanent` markers, which are deleted along with the files.

**Recurrence prevention.** The new test `test_legacy_experiment_package_removed` asserts `importlib.import_module("hi_agent.experiment")` raises `ModuleNotFoundError`. Any future commit that reintroduces the package fails this test in CI. This converts the deletion into a structural invariant rather than a one-shot cleanup.

---

## H-13' — Task Triplet Umbrella

**Disposition:** Decline (formal rationale)

The directive text describes "task / tasks / task_manager"; the actual triplet under `hi_agent/` (and `agent_kernel/`) is somewhat different in name but identical in shape — three names, three structurally distinct concerns. Below is a literal accounting of what exists today.

### Module inventory

| Module | LOC | Concern |
|---|---|---|
| `hi_agent/contracts/task.py` | 189 | **Request shape.** Defines `TaskContract` (the immutable HTTP/SDK request body) and `TaskBudget`. Pure dataclass; no imports from `task_mgmt`/`task_decomposition`/`task_view`. |
| `hi_agent/task_mgmt/` | 2,486 (12 files) | **Lifecycle authority.** Scheduler, handle, monitor, delegation, restart policy, reflection bridge — owns the run state machine and orchestrates retries. |
| `hi_agent/task_decomposition/` | 1,120 (5 files) | **Plan decomposition.** Builds a `TaskDAG` from a `TaskContract`, executes the DAG, collects feedback. Independent of `task_mgmt`. |
| `hi_agent/task_view/` | 1,442 (6 files) | **Observation/rendering.** Builds the prompt-side task view, enforces token budgets, triggers auto-compression. Read-only on contract; never schedules. |
| `agent_kernel/kernel/task_manager/` | (4 files) | **Kernel substrate.** Watchdog + registry + event log for the lower-level execution kernel. Independent codepath from `hi_agent/task_mgmt/`. |

### Structural distinctness

The five modules sit at four orthogonal layers that the architecture has carried since W12 hardening:

- **Contract layer** (`contracts/task.py`) — pure value type; serialised over HTTP, owned by CO. A field added here propagates through `from_dict`/spine validation; nothing else needs to change.
- **Decomposition layer** (`task_decomposition/`) — converts the contract's `goal` + `decomposition_strategy` into a DAG. Reads `TaskContract`; never reads or writes `TaskHandle`.
- **Lifecycle layer** (`task_mgmt/`) — authoritative state machine for a running task. Owns `TaskHandle`, `TaskStatus`, `RestartPolicyEngine`. Reads `TaskContract` for budget/policy fields; never reads `TaskNode` or `TaskView`.
- **View layer** (`task_view/`) — derives a prompt-shaped projection of run state for LLM consumption. Reads run context; never schedules, never decomposes.
- **Kernel substrate** (`agent_kernel/kernel/task_manager/`) — watchdog/registry/event-log under the kernel boundary. Distinct from `hi_agent/task_mgmt/` because the kernel is the lower substrate that hi-agent's `task_mgmt` sits on top of.

### Import-site asymmetry (verified via Grep on 2026-05-04)

| From → To | `task_mgmt` | `task_decomposition` | `task_view` | `contracts.task` | `kernel.task_manager` |
|---|---|---|---|---|---|
| `hi_agent/orchestrator/task_orchestrator.py` | 0 | **4** | 0 | 0 | 0 |
| `hi_agent/context/manager.py` + `run_context.py` | 0 | 0 | **2** | 0 | 0 |
| `hi_agent/runner.py` | **7** | 0 | **1** | 0 | 0 |
| `hi_agent/runner_stage.py` | 0 | 0 | **2** | 0 | 0 |
| `hi_agent/executor_facade.py` | 0 | 0 | 0 | **1** | 0 |
| `hi_agent/cli.py` | 0 | 0 | 0 | **1** | 0 |
| `hi_agent/server/app.py` | 0 | 0 | 0 | **1** | 0 |
| `hi_agent/task_mgmt/restart_policy.py` | (self) | 0 | 0 | 0 | **1** |
| `agent_kernel/runtime/bundle.py` | 0 | 0 | 0 | 0 | **2** |
| `agent_kernel/service/http_server.py` | 0 | 0 | 0 | 0 | **1** |

Concrete asymmetries (each row "X imports A but never B"):

1. `hi_agent/orchestrator/task_orchestrator.py` imports `task_decomposition` four times and never imports `task_mgmt`, `task_view`, or `contracts.task` — decomposition is its sole concern.
2. `hi_agent/context/manager.py` and `run_context.py` import `task_view` only — never `task_mgmt` or `task_decomposition` — because the context manager is read-only on lifecycle.
3. `hi_agent/cli.py`, `executor_facade.py`, and `server/app.py` import `contracts.task` only — they accept the request shape but do not touch the runtime modules.
4. `agent_kernel/` modules import `agent_kernel.kernel.task_manager` only — never any `hi_agent/task_*` module — because the kernel boundary is one-way (hi-agent calls into kernel, never the reverse).
5. The 80 import sites of `hi_agent.task_mgmt` and the 23 import sites of `hi_agent.task_view` overlap at exactly one file (`hi_agent/runner.py`) — and even there the imports come from disjoint submodules (`task_mgmt.delegation` vs `task_view.auto_compress`). No call site treats them as a single concept.

### Downstream consumer expectation

The downstream RIA team's W31 directive (`docs/upstream-directives/`) explicitly references `TaskContract` (request shape) and `TaskHandle` (lifecycle handle) as separately-named concepts in their integration vocabulary. RIA composes their multi-phase research agents by writing `TaskContract` instances and observing `TaskHandle` transitions — they never refer to a unified "task package". Folding the triplet under one umbrella name would break their import paths without delivering any structural simplification on our side.

### Conclusion

The triplet (in fact, a quintet once `agent_kernel.kernel.task_manager` is included) is not redundant naming — it reflects four distinct architectural layers (contract / decomposition / lifecycle / view) plus the kernel substrate. Each module has a non-overlapping import-site footprint and a disjoint semantic role. Consolidating any pair would erase a real boundary that the rest of the codebase relies on.

---

## H-14' — Templates Dir Consolidation

**Disposition:** Close (no-op — already consolidated)

**Inventory.** Exhaustive `git ls-files` for `templates/` paths under the repo:

| Path | Files | Consumer |
|---|---|---|
| `hi_agent/templates/posture/{dev,research,prod}/` | 9 `.tmpl` files | `hi_agent/cli_commands/init.py:23` (`_TEMPLATES_ROOT = Path(__file__).parent.parent / "templates" / "posture"`) — single consumer |
| `docs/downstream-responses/_templates/` | 4 markdown notice templates | Author-facing scaffolds for delivery notices; not loaded at runtime |

**Verification.** No other `templates/` directory exists under `hi_agent/`. The `hi_agent/templates/posture/` tree holds exactly the three posture variants the platform supports (`dev`/`research`/`prod`), each containing the three files `hi_agent_config.json.tmpl`, `profiles/<posture>.json.tmpl`, and `.env.example.tmpl`. The structure mirrors the `Posture` enum in `hi_agent/config/posture.py` and is loaded by exactly one CLI handler (`run_init` in `hi_agent/cli_commands/init.py`). The `docs/downstream-responses/_templates/` directory is a documentation-only scaffold under `docs/`; per the Rule 14 docs-only-gap definition it is governance paperwork, not runtime code, and has no overlap with the runtime templates.

**No code action.** There is nothing to consolidate: a single runtime templates directory with a single consumer is already at the minimal-structure end of the spectrum. Splitting `dev`/`research`/`prod` into per-posture subdirectories is intentional — `init.py` selects the subtree by argument, and flattening would require additional filename mangling. The directive's concern (templates dir scattered across the codebase) does not match the present state.

**Recurrence prevention.** This document records the audited single-directory state. Any future PR that adds a second `templates/` tree under `hi_agent/` would need to either (a) consolidate the new files into `hi_agent/templates/` or (b) update this closure record with rationale for the new split.

---

## Three-Part Closure (Rule 15)

| ID | (a) Code action | (b) Recurrence prevention | (c) Process change |
|---|---|---|---|
| H-3' | Commit `d694541e` deletes `hi_agent/experiment/` (7 files) and inverts the assertion test | `tests/unit/test_operations_module_canonical.py::test_legacy_experiment_package_removed` asserts `ModuleNotFoundError` — fails CI on reintroduction | This document records the deletion and the structural invariant; W31 H.0 (`docs/governance/package-consolidation-2026-05-02.md`) is now executed |
| H-13' | No code action — formal decline rationale | Decline rationale documented permanently in this file with file paths, LOC counts, and import-site asymmetry table; future "consolidate the task triplet" requests reference this section | This file is the binding decision under Rule 15 (`level: verified_at_release_head`); CLAUDE.md ownership table preserves the four-layer split (`task` contract / decomposition / lifecycle / view) under CO + RO + DX boundaries |
| H-14' | No code action — already consolidated | Decline rationale documented permanently in this file; any future PR adding a second `templates/` tree under `hi_agent/` must amend this section | This file documents the audited single-directory state as the canonical configuration |

---

## Closure-claim taxonomy (Rule 15 levels)

| ID | Level |
|---|---|
| H-3' | `verified_at_release_head` — code deleted, regression test in place at HEAD |
| H-13' | `verified_at_release_head` — rationale references current-HEAD import counts; LOC values from `wc -l` on 2026-05-04 |
| H-14' | `verified_at_release_head` — directory inventory taken from `git ls-files` at the current HEAD |

All three items meet the minimum level for `CLOSED` claim per Rule 15.
