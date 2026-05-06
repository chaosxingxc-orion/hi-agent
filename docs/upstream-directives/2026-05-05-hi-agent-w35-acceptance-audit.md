> **Mirrored from RIA on 2026-05-05.**
> Source: D:\chao_workspace\research\docs\hi-agent-w35-acceptance-audit-2026-05-05.md
> Maturity in this repo: M2 (mirrored to docs/upstream-directives/).
> See `docs/downstream-responses/2026-05-05-w35-corrective-response.md` for hi-agent's response.
> No content changes from source other than this preamble.

# hi-agent Wave 35 Acceptance Audit (RIA-internal)

**Date:** 2026-05-05
**Document maturity:** M1 — internally reviewed
**Audit author:** RIA team
**Audit basis:** four independent code-level verification agents dispatched in parallel against the hi-agent repository at `D:\chao_workspace\hi-agent\`
**HEAD note up front:**
- The W35 delivery notice (`docs/downstream-responses/2026-05-05-w35-delivery-notice.md`) cites "Manifest `2026-05-05-460a64bb` (built at HEAD `460a64bb`)" and a separate "Functional HEAD: `460a64bb65c8c5a797e086b499749842019fe966`".
- The actual W35 release_head per `docs/releases/wave35-signoff.json` and `docs/releases/platform-release-manifest-2026-05-05-bd4d38d5.json` is **`bd4d38d5`**.
- Repo working HEAD at audit time: `8ae5314a`.
- The string `460a64bb` does **not** appear as a referenced HEAD in any signoff or manifest in the repository — only as the "Functional HEAD" label in the delivery notice prose.
- This is the same class of inconsistency previously surfaced in W30 (notice text vs. release-truth divergence) and is recorded as a governance finding (§3.C below).

This audit does not retract the W34 acceptance or the W35 endorsement signed in `hi-agent-wave35-acceptance-and-wave36-expectations-2026-05-05.md`. It refines RIA's reading of the W35 ship by surfacing the defects the delivery notice did not enumerate, and feeds two outgoing artifacts: the W35 corrective directive and the W36 entry directive.

---

## 0. Audit method

Four parallel verification agents were dispatched, each with a self-contained brief and read-only access to the hi-agent repository:

1. **Agent 1** — W35-T1 spine validation 53-target verification + W35-T9 re-lease attempt_id bump verification + audit-doc carryover catalogue cross-check + cap-factor invariance.
2. **Agent 2** — W35-T3 INVERTED posture rewrite verification + W35-T4 idempotency TTL purge code + lifespan loop registration + Prometheus label naming verification.
3. **Agent 3** — Retention roadmap inventory + boot-time assertions roadmap inventory + pending evidence file existence + score caps + current-wave consistency + hidden findings audit-doc consistency.
4. **Agent 4** — RIA on-disk inventory (out-of-scope for this hi-agent audit but used in the engineering plan).

Each agent returned a written report with file:line citations. The findings below are synthesised from those reports; raw outputs are retained internally.

---

## 1. W35-T1 through W35-T9 closure verification

| ID | Notice claim | Code/test verification | Audit verdict |
|---|---|---|---|
| **T1** spine 53 targets | PASS / `verified_at_release_head` | `scripts/check_dataclass_spine_validation.py` `REQUIRED_VALIDATION_TARGETS` confirmed at exactly 53 entries; 5/5 sampled dataclasses across the 13/24/16 buckets carry posture-aware `__post_init__` (sampled: `agent_server/contracts/run.py::RunRequest`, `hi_agent/contracts/requests.py::StartRunRequest`, `hi_agent/server/idempotency.py::IdempotencyRecord`, `hi_agent/operations/op_store.py::OpHandle`, `hi_agent/server/run_manager.py::ManagedRun`); gate exit 0 | **PASS** |
| **T2** WEAK_PARITY 12+8 | PASS | Notice anchors site list in audit doc §A2; not exhaustively re-checked at file level beyond Agent 1's sampling; remains coherent | **PASS (claim coherent)** |
| **T3** INVERTED posture rewrite | PASS / `verified_at_release_head` | `hi_agent/server/run_manager.py:442-518` confirmed: auth-authoritative precedence + anti-forgery cross-check; `DeprecationWarning` removed from code (only retained in two retrospective comments at lines 457, 462). **No remaining branch where dev fail-closes and strict is permissive.** | **PASS — but dev-side test asymmetric (see §2.B)** |
| **T4** Idempotency TTL purge | PASS / `verified_at_release_head` | `hi_agent/server/idempotency.py::purge_expired` thread-safe (`self._lock` at line 209), VACUUM at 100-row threshold; lazy-purge in `reserve_or_replay` lines 291-310; `agent_server/runtime/lifespan.py::_idempotency_purge_loop` registered at lines 300-309 with proper `CancelledError` handling and `record_silent_degradation` on failure (lines 127-131). **Two notice prose discrepancies vs. code**: (a) SQL is `expires_at < ?` not `<= ?` as notice prose says; (b) `hi_agent_idempotency_purged_total` is emitted with **no labels at all**, contradicting the notice's `{tenant_bucket}` mention (the other 3 idempotency metrics do carry `{tenant_bucket}`). 5 integration tests confirmed structural (10K + WAL checkpoint disk shrink). | **PASS — code OK, notice prose inaccurate; label drift (§2.A)** |
| **T5** float canonicalization plan | DOCUMENTED | `agent_server/contracts/idempotency.py` Limitations section confirmed | **PASS** |
| **T6** Idempotency observability 4 metrics | PASS | 4 metrics registered in `hi_agent/observability/idempotency_metrics.py` and `hi_agent/observability/collector.py::_METRIC_DEFS`. **Label `tenant_bucket` (mod-16 hash) used on 3 of 4 metrics; `purged_total` has no labels.** Run-lifecycle metrics still use raw `{tenant_id}` — taxonomic split surfaces here for the first time. | **PASS — naming drift (§2.A)** |
| **T7** CONFIG layer expansion deferral | DOCUMENTED | `agent_server/config/settings.py` module docstring confirmed | **PASS** |
| **T8** build_app boot-time MCP idempotency assertion | PASS | `agent_server/api/__init__.py::build_app` confirmed; 10 integration tests in `tests/integration/test_mcp_tools_idempotency.py` confirmed | **PASS** |
| **T9** re-lease attempt_id bump (hidden HIGH) | PASS / `verified_at_release_head` | Code path verified at `hi_agent/server/app.py:1340-1400`: `new_attempt_id = str(uuid.uuid4())` (L1356); `parent_run_id=run_id` (L1360); `attempt_count = (existing.attempt_count or 0) + 1` (L1361); ManagedRun in-memory mirror updated (L1381-1400). **However**: the notice cites `tests/integration/test_run_lifecycle_recovery.py` as the regression-test anchor — **this file does not exist in the repository** at audit time. The notice itself contradicts at §T9(b): "If a follow-up test is required, it carries to W36 as `tests/integration/test_run_manager_release_attempt_id_bump.py`". | **DEGRADED — code-fix-only; closure level should be `code-fix-only`, not `verified_at_release_head`** |

**Summary**: 7 of 9 W35-T items are clean PASS at the code level. T9 is **DEGRADED** (soft closure) and T3/T4/T6 carry secondary defects (test asymmetry on T3; SQL boundary semantic on T4; label naming drift on T4/T6). T1, T2, T5, T7, T8 are clean.

---

## 2. Defects newly surfaced by this audit (not in the W35 delivery notice)

### 2.A — Prometheus label naming drift

| Metric family | Label convention at HEAD `bd4d38d5` |
|---|---|
| `hi_agent_run_*` (run-lifecycle, pre-W35) | `{tenant_id}` (raw) |
| `hi_agent_llm_tokens_total` (W31 cardinality-control precedent) | `{tenant_bucket}` (mod-16 hash, "unknown" for empty) |
| **`hi_agent_idempotency_replay_total`** (W35 new) | `{tenant_bucket}` |
| **`hi_agent_idempotency_conflict_total`** (W35 new) | `{tenant_bucket}` |
| **`hi_agent_idempotency_record_age_seconds`** (W35 new) | `{tenant_bucket}` |
| **`hi_agent_idempotency_purged_total`** (W35 new) | **no labels at all** (notice prose contradicts the code) |

**The defect.** The W34 delivery notice and RIA's W34 acceptance directive both used `{tenant_id}` as the documented label form for new platform metrics. The W35 implementation switched the new idempotency metrics to `{tenant_bucket}` (a mod-16 hash) without an explicit notice or contract change. This is naming drift relative to a documented commitment, and is a Rule 11 cohort failure (the contract-side commitment was in `{tenant_id}`; the implementation drifted under cardinality discipline cover).

**Why this is RIA-blocking (small but firm).** RIA's `ria/observability/` and any future dashboards/queries that filter by `tenant_id` will not match metrics that carry `{tenant_bucket}` instead. Two label conventions in the same Prometheus surface fragments dashboard portability and query consistency.

**Disposition.** This becomes corrective C-1 in the W35 corrective directive: revert the four new metrics to `{tenant_id}`, and route cardinality control through PromQL recording rules (an ops-side concern), not contract-side label rewriting.

### 2.B — W35-T3 dev-side asymmetric test coverage

`tests/integration/test_run_manager_tenant_strict.py` covers the `research/prod` cross-check direction (`test_research_posture_body_tenant_id_mismatch_raises` at line 93), but does not cover the `dev` direction of the **same** cross-check (body≠middleware → WARNING + middleware-value-used at `run_manager.py:490-497`).

**Why it matters.** The W35-T3 fix is symmetric in code; if the test is asymmetric, a future inversion drift on the dev side will not be caught by the existing regression. This is a "half a regression net" pattern.

**Disposition.** Corrective C-4 in the W35 corrective directive: add the dev-direction test before W36 entry.

### 2.C — W35-T9 closure level overstatement

The W35 delivery notice §"Three-Part Defect Closure (Rule 15) — HIGH items" classifies W35-T9 as `verified_at_release_head`. Three-part closure under Rule 15 requires (a) code fix, (b) recurrence-prevention check, (c) process change. The recurrence-prevention test cited (`tests/integration/test_run_lifecycle_recovery.py`) does not exist; the notice itself names a substitute test path (`tests/integration/test_run_manager_release_attempt_id_bump.py`) but lists it as W36 work.

**Disposition.** Corrective C-3 in the W35 corrective directive: downgrade W35-T9 closure level to `code-fix-only`; commit the regression test in W36.

### 2.D — `provenance_unknown_or_synthetic` cap-factor naming + active-set absence

In RIA's W34 acceptance §0.3, we used the conceptual shorthand "evidence_provenance" for the cap factor governing W27 historical artifact provenance + the W28 erratum. The literal cap factor name in `docs/governance/score_caps.yaml` is `provenance_unknown_or_synthetic` (cap=67). At the W35 release_head, `cap_factors_active` in `wave35-signoff.json` lists **only** `soak_evidence_not_real`. Two readings:

- (a) The provenance cap was implicitly resolved during W34's evidence work (W27 historicals + W28 erratum) and therefore no longer triggers; this should have been announced.
- (b) The gate that would surface the cap has a scope hole at HEAD `bd4d38d5`.

**Disposition.** Corrective C-2 in the W35 corrective directive: (i) clarify which reading applies; (ii) align RIA's language to the canonical cap factor name `provenance_unknown_or_synthetic` going forward.

### 2.E — Wave-ledger drift (self-referential governance failure)

| Source | Value |
|---|---|
| `docs/governance/current-wave.txt` | `35` |
| `docs/governance/recurrence-ledger.yaml::current_wave` | `33` |

Two-wave drift on the canonical governance ledger. The W32-D entry in `docs/governance/recurrence-ledger.yaml` (lines 564-589) was created **specifically** to prevent this drift and named `check_doc_truth.py` / `check_wave_consistency.py` as the gates. Either the gate did not run on W33–W35 or it has a scope regression.

**Disposition.** §5 governance items in the W35 corrective directive; W36 entry directive will require the `check_wave_consistency.py` gate to be re-validated.

### 2.F — Release-captain artifacts at parent HEAD

The W35 release_head is `bd4d38d5`. The "pending" evidence rows in the delivery notice were intended to be filled at the final HEAD. They were instead filled at parent `d767fde0` and at parent-of-parent `04c1faa4`:

| Path | Filled at | Matches `bd4d38d5`? |
|---|---|---|
| `docs/verification/04c1faa4-default-offline-clean-env.json` | `04c1faa4` | NO |
| `docs/verification/04c1faa-arch-7x24.json` | `04c1faa4` | NO |
| `docs/delivery/2026-05-05-460a64bb-t3-volces.json` | does not exist | NO |
| `docs/releases/platform-release-manifest-2026-05-05-460a64bb.json` | does not exist | NO |
| `docs/releases/wave35-signoff.json` | `bd4d38d5` | YES |
| `docs/verification/d767fde0-default-offline-clean-env.json`, `d767fde-arch-7x24.json`, `docs/delivery/2026-05-05-d767fde0-t3-volces.json` | `d767fde0` (W35 parent) | NO |

The cap rule `clean_env_not_final_head` (cap=60) exists in `docs/governance/score_caps.yaml` precisely for this case, but `cap_factors_active` does not list it. Either the gate fails to detect the parent-HEAD condition under the captain's "non-hot-path docs-only" exemption, or the exemption is short-circuiting the check inappropriately.

**Disposition.** §5 governance items in the W35 corrective directive; W36 entry directive will require either the cap to fire in such conditions or the exemption pathway to be explicitly named in the signoff.

---

## 3. Eight-lens delta vs. the W35 endorsement

For each lens, this audit refines the W35 endorsement (`hi-agent-wave35-acceptance-and-wave36-expectations-2026-05-05.md` §2):

| Lens | W35 endorsement | Audit-refined position |
|---|---|---|
| **L1 Tenant isolation** | T3 closes INVERTED; T1 closes spine 53 | Confirmed structural close; secondary T3 dev-side test asymmetry → corrective C-4 |
| **L2 Functional idempotency** | T4+T6+T8 three-piece set | Confirmed code-level close; **label naming drift requires explicit corrective C-1** |
| **L3 High reliability** | T1 + T9 close lineage | Confirmed code-level for T9; **T9 closure level downgraded to `code-fix-only` — corrective C-3**; A4 schema-shape lineage extensions remain W36 binding |
| **L4 High concurrency** | unchanged from W34 | Maintained; no W35 regression |
| **L5 Configurable development** | T2+T7 | Confirmed |
| **L6 Continuous intelligence evolution** | T1+T9 transitively | Same caveat as L3 (T9 soft closure) |
| **L7 7×24 architectural feasibility** | T4 retention reference + roadmap 24 stores catalogued | **Defect quantified**: 8 of 24 unbounded-growth stores in Tier-1 W36 binding currently have **0 retention code**; only idempotency has the W35-T4 reference. Env-var convention `HI_AGENT_<STORE>_RETENTION_DAYS` is documentation-only, not implemented anywhere except idempotency. Feasibility position holds, but the magnitude of the architectural counter-example is now visible |
| **L8 Agent service to upper systems** | T6 metrics + T8 boot reject | Confirmed; same label naming drift (corrective C-1) |

---

## 4. W36-binding items the audit confirmed (will appear in W36 entry directive)

Ranked by RIA priority:

1. **HIGH — A3 Tier-1 retention 8 stores** (per `docs/governance/retention-roadmap.md`): `SQLiteEventStore`, `SQLiteRunStore`, `SQLiteGateStore`, `SqliteDecisionAuditStore`, `SqliteEvidenceStore`, plus 6 `agent_kernel/kernel/persistence/sqlite_*.py` files. All currently 0 retention code. Lens 7 feasibility-blocking class.
2. **HIGH — A5 boot-time assertions B1–B14** (per `docs/governance/boot-time-assertions-roadmap.md`): includes B13 silent-route-omission, which is **structurally identical** to RIA's R-RIA-9 outbound-seam concern. RIA mirrors this defence as `check_route_presence.py` (G-RIA-13) on the RIA side.
3. **HIGH — A4 schema-shape lineage extensions**: `RunResponse` / `RunStatus` / `RunStream` / `StoredEvent` / `ReasoningTrace` need attempt-chain fields exposed at the wire/SSE level so RIA's `evolution_engine/postmortem.py` can reconstruct attempt trees from platform reads.
4. **MEDIUM — A4 minor 4 sites**: `OpHandle` parent_run_id/attempt_id/phase_id; `ManagedRun` replayed-stub lineage; `StoredEvent` runtime-event default; `event_bus` `RuntimeEvent` silent default.
5. **MEDIUM — Recovery system events** (`dlq_checked`, `recovery_decision`) using `tenant_id="__system__"` — lineage absent.

---

## 5. Outgoing artifacts gated by this audit

This audit is the basis for two outgoing directives, both signed today:

- **`docs/hi-agent-w35-corrective-directive-2026-05-05.md`** — corrective items C-1 through C-4 plus governance items §5 (wave-ledger drift, release-captain artifacts at parent HEAD).
- **`docs/hi-agent-wave36-engineering-expectations-2026-05-05.md`** — the W36 entry directive incorporating the §4 RIA-binding items above plus the carry-forward W35 corrective items.

This audit also informs the RIA-internal engineering plan:

- **`docs/ria/ria-engineering-plan-r-w1-2026-05-05.md`** — RIA Wave R-W1 plan, which lands the R-RIA-9 outbound seam, real `agent-server serve` integration fixture, and 9 new CI gates including the route-presence mirror of hi-agent's B13.

---

## 6. Closure standing

The W34 acceptance and W35 endorsement signed in `hi-agent-wave35-acceptance-and-wave36-expectations-2026-05-05.md` remain valid. The W35 ship is accepted with the four corrective items above scheduled for W35-corrective-window closure (target: before W36 entry). RIA's R-W1 engineering wave can begin under the three guard rails stated in the engineering plan §5 — the 4 outstanding corrective items do not block RIA work, because they affect notice/test/governance hygiene rather than the execution paths RIA's `tests/integration/` exercises.

---

## 7. Cross-references

| Document | Role |
|---|---|
| `D:\chao_workspace\hi-agent\docs\downstream-responses\2026-05-05-w35-delivery-notice.md` | hi-agent W35 delivery notice (the basis verified) |
| `D:\chao_workspace\hi-agent\docs\releases\wave35-signoff.json` | W35 signoff (release_head `bd4d38d5`) |
| `D:\chao_workspace\hi-agent\docs\releases\platform-release-manifest-2026-05-05-bd4d38d5.json` | W35 manifest |
| `D:\chao_workspace\hi-agent\docs\governance\systematic-audit-w35-2026-05-05.md` | hi-agent's own audit doc (91 hidden findings) |
| `D:\chao_workspace\hi-agent\docs\governance\retention-roadmap.md` | 24 unbounded-growth stores catalogued |
| `D:\chao_workspace\hi-agent\docs\governance\boot-time-assertions-roadmap.md` | 22 boot-time gaps catalogued |
| `D:\chao_workspace\hi-agent\docs\governance\score_caps.yaml` | Cap factor canonical definitions |
| `D:\chao_workspace\hi-agent\docs\governance\current-wave.txt` | `35` |
| `D:\chao_workspace\hi-agent\docs\governance\recurrence-ledger.yaml` | `current_wave: 33` (drift, see §2.E) |
| `D:\chao_workspace\research\docs\hi-agent-wave35-acceptance-and-wave36-expectations-2026-05-05.md` | RIA's W35 acceptance + W36 forward expectations (predecessor) |
| `D:\chao_workspace\research\docs\hi-agent-w35-corrective-directive-2026-05-05.md` | corrective directive (this audit's outgoing artifact) |
| `D:\chao_workspace\research\docs\hi-agent-wave36-engineering-expectations-2026-05-05.md` | W36 entry directive (this audit's outgoing artifact) |
| `D:\chao_workspace\research\docs\ria\ria-engineering-plan-r-w1-2026-05-05.md` | RIA-internal engineering plan |

---

**Signed:** RIA team
**Audit head (hi-agent side):** `bd4d38d5` (W35 release_head per signoff)
**Document maturity:** M1 — internally reviewed; not promoted to M2.
