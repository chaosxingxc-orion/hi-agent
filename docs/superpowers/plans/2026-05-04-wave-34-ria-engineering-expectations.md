# Wave 34 Plan — RIA Engineering Expectations

**Date:** 2026-05-04
**Author:** hi-agent platform team
**Source directive:** `docs/upstream-directives/hi-agent-wave34-engineering-expectations-2026-05-04.md` (RIA M1, 2026-05-04)
**Predecessor:** Wave 33 (`docs/superpowers/plans/2026-05-04-wave-33-ria-acceptance-followups.md`; manifest `2026-05-03-ce9330fa`; verified=75.0)
**Disposition:** ACCEPT ALL seven BLOCKERs + four governance items + advisory item (twelve total acceptance IDs). No pushback proposed; RIA's §10 positions are accepted as stated.

---

## 0. Acceptance Decision

Each W34 BLOCKER and acceptance item maps onto our positioning statement
("northbound functional idempotency, performance stability, extensibility,
evolvability, configurable development, sustainable evolution"). All twelve
items are accepted at the maturity level RIA requested.

| W34 ID | Positioning lens | Disposition |
|---|---|---|
| B-W34-1 (F.2 lineage) | Evolvability / Reliability | Accept (W33 carryover; binding) |
| B-W34-2 (F.3 spine validation) | Reliability / Spine completeness | Accept (W33 carryover; binding) |
| B-W34-3 (F.4 KnowledgeWiki tenant partition) | Tenant isolation | Accept (W33 carryover; binding) |
| B-W34-4 (B-5 four-registry status) | Tenant isolation | Accept (publish status only) |
| B-W34-5 (manifest posture spec) | Agent service / contract surface | Accept |
| B-W34-6 (idempotency cross-process replay) | Functional idempotency | Accept |
| B-W34-7 (concurrency first-baseline) | Performance stability | Accept (RIA §10.1 N/M flexibility) |
| W34-NAMING-CLOSE | Sustainable evolution | Accept |
| W34-CONFIG-ENV-AUDIT | Configurable development | Accept |
| W34-LINUX-SOAK-ROADMAP | Long-running 7×24 (advisory) | Accept (one paragraph) |

No item is reclassified, deferred, or rebadged. Per Engineering Discipline
1.3 we run the three-part closure protocol on every BLOCKER.

---

## 1. Wave 34 Track Map (parallel)

Tracks are independent except where annotated. Each track owns its files and
gates; no two tracks edit the same file. The dependency arrow at Track H
indicates Track H consumes Tracks A–G outputs to assemble the closure notice
+ manifest.

```
Track A (Lineage + Spine)         ──┐
Track B (Tenant Isolation)        ──┤
Track C (Manifest Posture)        ──┤
Track D (Idempotency Contract)    ──┼──> Track H (Closure)
Track E (Concurrency Baseline)    ──┤
Track F (Naming Hygiene)          ──┤
Track G (Env-Var Audit)           ──┘
```

---

## 2. Track A — Lineage Population + ReasoningTrace Spine Validation

**Closes:** B-W34-1 (F.2), B-W34-2 (F.3) · **Owners:** RO + CO

### A.1 RunExecutionContext lineage population

**Construction site to fix (TBD by exploration):** likely
`hi_agent/server/run_executor.py::RunExecutionContext.from_managed_run`. The
fix populates `parent_run_id`, `attempt_id`, `phase_id` from the
`ManagedRun` source rather than hardcoding empty strings.

**Tests:**
- `tests/unit/test_run_execution_context_lineage_population.py` — pure value
  test that the constructor copies through.
- `tests/integration/test_run_lineage_persisted_after_recovery.py` —
  start a run, advance to S2, SIGTERM the worker, restart kernel, reread
  `RunRecord` + `StoredEvent`; assert lineage chain is intact (`attempt_id`
  bumps, `parent_run_id` connects post-recovery rows back to pre-recovery).

**Gate:** `scripts/check_lineage_population.py` — AST walks every
`RunExecutionContext(...)` construction site and `RunExecutionContext.from_*`
call site. Fails CI if any pass empty strings to `parent_run_id` /
`attempt_id` / `phase_id`.

**Process change:** add §"Spine completeness" to `hi_agent/ARCHITECTURE.md`
(or extend an existing "Reliability" section); add a CLAUDE.md Rule 12
sub-bullet pointing to the gate.

### A.2 ReasoningTrace.__post_init__ spine validation

**Construction site to fix:** locate the `ReasoningTrace` class (likely
under `hi_agent/skill/` or `hi_agent/observability/trace/`); add
`__post_init__` raising `ValueError` (or new `SpineCompletenessError`) on:
- empty `tenant_id`
- empty `parent_run_id` when `attempt_id != "1"` (i.e. first attempt
  legitimately has no parent)
- empty `phase_id`

**Tests:**
- `tests/unit/test_reasoning_trace_spine_validation.py` — each spine field
  individually empty → raises; all-non-empty → succeeds.
- `tests/integration/test_no_existing_reasoning_trace_construction_violates_spine.py`
  — exercises every production `ReasoningTrace` construction path; each
  must produce a valid trace under realistic input. Catches the
  "we added the check but a constructor was already passing empty
  strings" failure mode.

**Gate:** `scripts/check_dataclass_spine_validation.py` — verifies every
`@dataclass` carrying spine fields also defines `__post_init__` with the
required asserts. If `check_contract_spine_completeness.py` is the natural
home, extend it; otherwise add a new gate.

**Process change:** same as A.1 — single ARCHITECTURE / CLAUDE.md edit
covers both A.1 and A.2.

---

## 3. Track B — KnowledgeWiki Tenant Partition + 4-Registry Audit

**Closes:** B-W34-3 (F.4), B-W34-4 (B-5 follow-through) · **Owner:** RO

### B.1 KnowledgeWiki tenant partition

- `KnowledgeWiki` persistent store: every key gains `tenant_id NOT NULL`
  (composite key shape `(tenant_id, ...)` as needed). Read paths require a
  `tenant_id` argument; any `get_unsafe()`-style escape hatches removed
  from public surface or annotated `# scope: process-internal`.
- Existing `xfail` tests under `tests/integration/test_knowledge_*` (if
  any) flip to PASS.
- New `tests/integration/test_knowledge_wiki_tenant_partition.py` (per
  RIA §B-W34-3 acceptance — 6 cases × 3 postures).
- Gate: `scripts/check_no_unscoped_knowledge_reads.py` AST-walks Wiki/KG
  read sites; fails when `tenant_id` is missing.

### B.2 Four-registry tenant-scoping audit

Audit each registry originally named in W31 §B-5:
1. KnowledgeGraph (`hi_agent/knowledge/`)
2. Skill registry (`hi_agent/skill/`)
3. Tool registry (locate; likely `hi_agent/capability/` or dedicated
   tools subpackage)
4. Capability registry (`hi_agent/capability/`)

For each: state `tenant_id` enforcement at HEAD (closed/open), cite the
integration test verifying it (or its absence). Any registry not closed at
HEAD is added inline to the Track B BLOCKER set with the same closure
shape as B.1.

Output table goes into both:
- `docs/downstream-responses/2026-05-04-w34-delivery-notice.md` (under
  W34-T-FOLLOWUP row)
- `docs/governance/registry-tenant-scoping-audit-2026-05-04.md` (audit
  detail)

---

## 4. Track C — `/v1/manifest` Posture Field (Frozen)

**Closes:** B-W34-5 · **Owner:** AS-CO

### C.1 Contract surface

Decide between two shapes (current `agent_server/contracts/` is flat —
there is no `v1/` subpackage today):

- Option A: introduce `agent_server/contracts/v1/` subpackage now and
  migrate manifest schema there. RIA's §6 row references
  `agent_server/contracts/v1/manifest.py`; aligns with the v2-when-needed
  pattern.
- Option B: declare the field on the existing flat
  `agent_server/contracts/manifest.py` (new file) without restructuring.

**Decision:** Option B. Reasoning: today's contracts package is the v1
package by virtue of `V1_RELEASED=True` + `V1_FROZEN_HEAD`; adding a
`v1/` directory implies the existence of a `v2/` directory, which is not
yet planned. Re-snapshot the contract digest after adding the field.

The contract dataclass (proposed):

```python
# agent_server/contracts/manifest.py
from dataclasses import dataclass, field
from typing import Literal

PostureLiteral = Literal["dev", "research", "prod"]

@dataclass(frozen=True)
class ManifestResponse:
    """Body of GET /v1/manifest. Posture field consumed by RIA R-RIA-6."""
    api_version: str
    posture: PostureLiteral
    capabilities: dict[str, str] = field(default_factory=dict)
    # ... existing fields preserved
```

`manifest_facade.manifest()` is updated to populate the posture from
`Posture.from_env().value`.

### C.2 Test

`tests/integration/test_manifest_posture_field_present.py`: GET
`/v1/manifest` under each posture; assert `posture` field present with
matching value; assert response shape matches the dataclass.

### C.3 Re-freeze

Run `python scripts/check_contract_freeze.py --snapshot` to bump
`V1_FROZEN_HEAD` (since contracts/ tree changed). Document the new SHA in
the W34 delivery notice.

---

## 5. Track D — Idempotency Cross-Process Replay + Spec

**Closes:** B-W34-6 · **Owners:** AS-CO + AS-RO

### D.1 Spec document

`agent_server/contracts/idempotency.py` (new) — pure documentation module
with module-level constants + a docstring section spec'ing:
1. **Cache scope:** keys are `(tenant_id, key)` composite. Cross-tenant
   key collisions are structurally impossible.
2. **Cross-process replay:** the SQLite-backed `IdempotencyStore`
   persists across kernel restarts. A retry after restart with the same
   `(tenant_id, key, body_hash)` returns the cached response from the
   pre-restart execution.
3. **TTL:** keys are cached for `run_lifetime + grace_period` minutes.
   If `grace_period` is currently 0 (no purge), document that.
4. **Body-mismatch behaviour:** same key + different body returns 409
   with `error_category="conflict"` regardless of restart history.

### D.2 Cross-process replay test

`tests/integration/test_idempotency_cross_process_replay.py`:
- Subprocess-launches `agent-server serve --state-dir tmp/`.
- POST `/v1/runs` with `Idempotency-Key=K1`, body B; expect 201 with
  `run_id=R1`.
- SIGTERM the subprocess; restart it (same `--state-dir`).
- POST `/v1/runs` with same `(K1, B)`; expect 201 `run_id=R1` (replay).
- POST `/v1/runs` with `(K1, B')` (different body); expect 409.
- Repeat for `cancel`, `signal`, `register_skill`, `write_artifact`.

### D.3 Gate

`scripts/check_idempotency_contract_documented.py`: verifies the spec
docstring section exists in `agent_server/contracts/idempotency.py`
with at least the four sub-headers above. Lightweight regex check.

---

## 6. Track E — Concurrency Baseline + Methodology + Equivalence

**Closes:** B-W34-7 · **Owner:** TE

### E.1 Methodology document

`docs/perf/concurrency-methodology-v1.md`:
- Workload definition: `N` parallel `POST /v1/runs` from `M` simulated
  tenants; goal = "queued" terminal state in steady-state.
- Measurement: P50/P95/P99 of run-start latency; per-tenant fairness
  coefficient; queue depth time series; SQLite lock-wait count.
- Hardware target: documented baseline (GitHub Actions
  `ubuntu-latest`: 4 vCPU, 16 GB RAM, SSD).
- `N` flexibility per RIA §10.1: target `N ∈ {1, 10, 50}` with
  `M ∈ {1, 5}` first; raise to `N=100/M=10` once CI runner stability
  confirmed.

### E.2 Bench harness

`scripts/run_concurrency_baseline.py` — pure Python harness using
`asyncio` + `httpx`. Spawns target server, fires `N×M` concurrent POSTs
through tenant-scoped clients, records response timings, writes a JSON
artifact at `docs/verification/<head>-concurrency-N{N}M{M}.json` with
`provenance: real`.

### E.3 First baseline

Run on the same Ubuntu runner that produces the manifest at W34 close.
Record `provenance: real`. The first baseline is `N=10, M=5` (most
likely; `N=50, M=5` if CI runner allows).

### E.4 Persistence equivalence

`tests/integration/test_concurrency_persistence_swap.py` — small `N=10,
M=1` workload; runs twice (SQLite, then PostgreSQL via
`AGENT_SERVER_DB_BACKEND=postgres`); asserts terminal-state distribution
matches.

### E.5 Gate

`scripts/check_concurrency_evidence.py`: verifies the latest
`docs/verification/<head>-concurrency-*.json` exists, has
`provenance: real`, and is reachable from current HEAD via gov-only-gap
discipline.

---

## 7. Track F — Naming Hygiene Closure (H-3', H-13', H-14')

**Closes:** W34-NAMING-CLOSE · **Owners:** DX/RO

For each item, decide between **close** (consolidate) or **decline** (write
formal rationale). Output a single document
`docs/governance/package-consolidation-2026-05-04.md` with one section per
item.

| ID | Item | Likely disposition | Rationale path |
|---|---|---|---|
| H-3' | experiment shim deletion | Close — short-lived shim from W30 evolve work | grep usage; if removable, remove + update import sites |
| H-13' | task triplet umbrella (`task` / `tasks` / `task_manager`) | Likely decline — three names map to three structurally distinct concerns (request-shape, plural collection, lifecycle authority) | rationale paragraph + import-site asymmetry table |
| H-14' | templates dir consolidation | Decide via grep — if a single dir holds all live templates, close; if split is intentional (test fixtures vs runtime), decline | grep + decision |

Closures get commit SHA + import-site update count. Declines get a
concrete rationale paragraph (per RIA §4 acceptance criterion).

---

## 8. Track G — Env-Var Audit + Routing Gate

**Closes:** W34-CONFIG-ENV-AUDIT · **Owner:** DX/GOV

### G.1 Enumeration

Grep every `os.environ.get`, `os.environ[...]`, `os.getenv` across
`hi_agent/**` and `agent_server/**`. Output to
`docs/governance/env-var-audit-2026-05-04.md` with rows:

| Variable | File:line | Classification | Action |
|---|---|---|---|
| `HI_AGENT_ENV` | `hi_agent/config/posture.py:??` | Posture-routed (W33-E.1) | none |
| `HI_AGENT_LLM_MODE` | `hi_agent/llm/...` | direct read | route through `hi_agent/config/llm_mode.py::resolve_llm_mode()` (new) |
| ... | ... | ... | ... |

### G.2 Classification rules

- **Posture-routed:** read inside `hi_agent/config/posture.py` and
  exposed via a typed accessor. ✓ no further action.
- **Direct:** read at the call site without routing. → either route
  through a new accessor in `hi_agent/config/<name>.py` OR mark as
  principled exception (entry-point CLI / test override / temporary
  shim with `expiry_wave`).
- **Principled exception:** documented inline with rationale + (where
  applicable) `expiry_wave` annotation.

### G.3 Gate

Extend `scripts/check_no_hi_agent_env_direct_read.py` →
`scripts/check_env_var_routing.py`:
- Reads an allowlist (file paths × env-var name) from
  `docs/governance/env-var-allowlist.yaml`.
- Fails CI on any `os.environ` access not on the allowlist OR not
  inside the documented router function.

---

## 9. Track H — Closure Notice + Manifest

**Owners:** GOV

Output sequence (after Tracks A–G closure):

1. Final implementation commit (the last functional commit closing all
   BLOCKERs).
2. Run gates: `scripts/verify_clean_env.py`, `scripts/run_arch_7x24.py`,
   `scripts/build_release_manifest.py`.
3. Run T3 (Volces real LLM) at the new HEAD; emit
   `docs/delivery/2026-05-04-<sha>-rule15-volces.json`.
4. Generate `docs/releases/platform-release-manifest-2026-05-04-<sha>.json`.
5. Generate `docs/releases/wave34-signoff.json`.
6. Author `docs/downstream-responses/2026-05-04-w34-delivery-notice.md`
   per RIA §8 reporting format:
   - W33 acknowledgement reference.
   - Verified Readiness table (with current cap factors).
   - W34 closure evidence table (12 rows).
   - Three-part closure block per BLOCKER (a/b/c).
   - Linux-runner soak roadmap paragraph (advisory).
   - W31-B-5 four-registry status sub-table (per Track B output).

The closure notice references the Step-9 manifest and is itself the
"closure commit"; per Rule 14 only the manifest, the notice, and the
signoff JSON may follow the final functional commit.

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Track E concurrency runner instability on GitHub Actions | RIA §10.1 explicitly accepts smaller N/M; we declare the largest feasible set |
| T3 cost (real Volces calls × 3+ for Rule 8) | Use the user-supplied key; rotate after wave close |
| Multiple tracks touching `agent_server/contracts/**` invalidates frozen digest | Track C will re-snapshot once at end (after Track D adds idempotency.py); single `--snapshot` invocation |
| Track A backfill test surfaces additional violators | Plan-of-record: fix violators inline; do not skip the test |
| Hot-path commits invalidate T3 (Rule 8) | Track A modifies hot-path files (`hi_agent/server/**`); T3 must run AFTER Track A completes |
| Manifest 3-rewrite budget (Rule 14) | Single manifest at wave close; intermediate evidence files only under `docs/verification/` |

---

## 11. Acceptance Mapping (CI-verifiable)

Each row maps a W34 acceptance ID (RIA §6) to the responsible track.

| W34 ID | Track | Path |
|---|---|---|
| W34-F.2 | A.1 | `tests/unit/test_run_execution_context_lineage_population.py` + `tests/integration/test_run_lineage_persisted_after_recovery.py` + `scripts/check_lineage_population.py` |
| W34-F.3 | A.2 | `tests/unit/test_reasoning_trace_spine_validation.py` + `tests/integration/test_no_existing_reasoning_trace_construction_violates_spine.py` + `scripts/check_dataclass_spine_validation.py` |
| W34-F.4 | B.1 | `tests/integration/test_knowledge_wiki_tenant_partition.py` + `scripts/check_no_unscoped_knowledge_reads.py` |
| W34-T-FOLLOWUP | B.2 | per-registry status table in W34 delivery notice + `docs/governance/registry-tenant-scoping-audit-2026-05-04.md` |
| W34-MANIFEST | C | `agent_server/contracts/manifest.py` + `tests/integration/test_manifest_posture_field_present.py` |
| W34-IDEMPOTENCY | D | `agent_server/contracts/idempotency.py` + `tests/integration/test_idempotency_cross_process_replay.py` + `scripts/check_idempotency_contract_documented.py` |
| W34-CONCURRENCY-METHOD | E.1 | `docs/perf/concurrency-methodology-v1.md` |
| W34-CONCURRENCY-BASELINE | E.3 | `docs/verification/<head>-concurrency-N{N}M{M}.json` + `scripts/check_concurrency_evidence.py` |
| W34-CONCURRENCY-EQUIV | E.4 | `tests/integration/test_concurrency_persistence_swap.py` |
| W34-NAMING-CLOSE | F | `docs/governance/package-consolidation-2026-05-04.md` |
| W34-CONFIG-ENV-AUDIT | G | `docs/governance/env-var-audit-2026-05-04.md` + `scripts/check_env_var_routing.py` exit 0 |
| W34-LINUX-SOAK-ROADMAP | H (advisory) | one paragraph in W34 delivery notice |

---

## 12. Out of Scope (per RIA §7)

- New v1 routes beyond manifest posture field
- Retiring `evidence_provenance` cap factor
- Platform v2 contract work
- Linux-runner extension of the 2 OS-limited chaos scenarios (advisory only)
- Front-end / SDK work

---

**End of Wave 34 plan.**
