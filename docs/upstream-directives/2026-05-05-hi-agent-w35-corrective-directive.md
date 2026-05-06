> **Mirrored from RIA on 2026-05-05.**
> Source: D:\chao_workspace\research\docs\hi-agent-w35-corrective-directive-2026-05-05.md
> Maturity in this repo: M2 (mirrored to docs/upstream-directives/).
> See `docs/downstream-responses/2026-05-05-w35-corrective-response.md` for hi-agent's response.
> No content changes from source other than this preamble.

# hi-agent Wave 35 Corrective Directive

**Date:** 2026-05-05
**From:** Research Intelligence Application (RIA) team — downstream platform consumer
**To:** hi-agent upstream engineering team
**Status:** Corrective directive (M1 — internally reviewed; binding on the W35 ship between today's signing and W36 entry)
**Position:** Companion to the prior W35 acceptance + W36 forward expectations directive (`hi-agent-wave35-acceptance-and-wave36-expectations-2026-05-05.md`). Refines the W35 ship after a code-level audit (`hi-agent-w35-acceptance-audit-2026-05-05.md`) surfaced four corrective items and two governance items not enumerated in the W35 delivery notice.

---

## 0. Standing on Wave 35

The W35 ship is **accepted**; the eight named acceptance items (W35-T1 through W35-T8) plus the hidden HIGH (W35-T9) are closed in code at the release_head. The W34 acceptance signed in the predecessor directive **stands**. This directive **does not retract** the W35 endorsement — it adds four corrective items and two governance items that emerged from independent code-level verification.

The corrective items are scheduled to close in the W35-corrective-window (target: before W36 entry directive moves to binding). They affect notice truth, test symmetry, closure-level honesty, label-naming consistency, and governance-ledger consistency — not the runtime correctness of the W35 ship.

---

## 1. Corrective C-1 — Prometheus label revert (`{tenant_bucket}` → `{tenant_id}`)

**Finding.** The four W35-new idempotency metrics use the `{tenant_bucket}` label (mod-16 hash) inconsistently with `hi_agent_run_*` metrics (which use raw `{tenant_id}`). Specifically:

| Metric | Label at HEAD `bd4d38d5` | W34 commitment / RIA expectation |
|---|---|---|
| `hi_agent_idempotency_replay_total` | `{tenant_bucket, outcome}` | `{tenant_id, outcome}` |
| `hi_agent_idempotency_conflict_total` | `{tenant_bucket}` | `{tenant_id}` |
| `hi_agent_idempotency_record_age_seconds` | `{tenant_bucket}` | `{tenant_id}` |
| `hi_agent_idempotency_purged_total` | **no labels at all** | `{tenant_id}` |

The label drift was undertaken under cardinality-control rationale (mirroring `hi_agent_llm_tokens_total` from W31) but was not announced as a contract change in any wave directive or delivery notice. Two label conventions now coexist in the platform's Prometheus surface; this fragments dashboard portability and is a violation of the W31/W34 "naming accretion is a defect" rule (closure-claim-cohort failure: contract-level commitment in `{tenant_id}`; implementation drifted to `{tenant_bucket}` without surfacing the change).

**Required action.**
- (a) Revert the four metrics to `{tenant_id}` (raw). For `purged_total`, add the missing label.
- (b) Route cardinality control through PromQL recording rules (an ops-side concern), not contract-side label rewriting. If a `{tenant_bucket}` aggregate is desired for ops dashboards, derive it via a recording rule, leaving the source metric carrying `{tenant_id}`.
- (c) Document the policy in `hi_agent/observability/ARCHITECTURE.md` (or equivalent): platform-side metric labels remain `{tenant_id}`; cardinality-control buckets are derived ops-side.

**Acceptance criteria.**
- All four idempotency metrics carry `{tenant_id}` (raw) at the W35-corrective head.
- A regression test in `tests/integration/test_idempotency_metrics.py` asserts the label name set on each metric.
- The label-policy paragraph appears in `hi_agent/observability/ARCHITECTURE.md` or `docs/observability/idempotency-metrics.md`.

**Three-part closure (Rule 15).** Required: (a) code fix with file:line; (b) regression test as named above; (c) process change recording the label policy.

**Note on `hi_agent_llm_tokens_total`.** This pre-existing W31 metric remains `{tenant_bucket}` for backwards compatibility; we do not request its revert, but we do expect the cardinality-control policy paragraph to record it as a documented exception with rationale.

---

## 2. Corrective C-2 — `provenance_unknown_or_synthetic` cap-factor active-set clarification

**Finding.** In RIA's W34 acceptance §0.3, we wrote that two cap factors hold: `soak_evidence_not_real` and `evidence_provenance`. The literal canonical cap-factor name in `docs/governance/score_caps.yaml` is `provenance_unknown_or_synthetic` (cap=67); the name `evidence_provenance` was an RIA-side conceptual shorthand for it. At the W35 release_head, `wave35-signoff.json::cap_factors_active` lists **only** `soak_evidence_not_real`. The `provenance_unknown_or_synthetic` cap is therefore not currently triggering.

Two readings:
- (a) The provenance cap was implicitly resolved during W34's evidence consolidation (W27 historical artifacts plus the W28 erratum), and therefore no longer triggers. This should have been announced in a wave delivery notice.
- (b) The gate that would surface the cap has a scope hole at the W35 release_head and is silently not firing despite the cap rule remaining in `score_caps.yaml`.

**Required action.**
- (a) State which reading applies in the W35 corrective response.
- (b) If reading (a): publish the resolution announcement in a delivery-notice supplement and link it from `docs/governance/score_caps.yaml` (lifecycle_note on the `provenance_unknown_or_synthetic` rule).
- (c) If reading (b): identify the gate scope hole, add the missing detection, and either re-fire the cap or document why historical W27/W28 evidence at HEAD `bd4d38d5` does not meet the cap conditions.
- (d) RIA-side terminology is corrected: future RIA correspondence will use `provenance_unknown_or_synthetic` (canonical) instead of "evidence_provenance" (shorthand).

**Acceptance criteria.**
- W35 corrective response names which reading applies and the supporting evidence.
- If (a): a documented `lifecycle_note` in `score_caps.yaml` on the relevant cap rule.
- If (b): the gate fix landed at the W35-corrective head and either the cap fires or the lifecycle_note explains the conditions of non-firing.

**Three-part closure (Rule 15).** Required.

---

## 3. Corrective C-3 — W35-T9 closure level downgrade

**Finding.** The W35 delivery notice §"Three-Part Defect Closure (Rule 15) — HIGH items" classifies W35-T9 (re-lease attempt_id bump) as `verified_at_release_head`. Three-part closure under Rule 15 requires (a) code fix, (b) recurrence-prevention check, (c) process change.

- (a) Code fix: VERIFIED at `hi_agent/server/app.py:1340-1400`.
- (b) Recurrence-prevention check: NOT VERIFIED. The cited test `tests/integration/test_run_lifecycle_recovery.py` does not exist in the repository. The notice itself, in §T9(b), names a substitute test path `tests/integration/test_run_manager_release_attempt_id_bump.py` and lists it as W36 work.
- (c) Process change: documented in `docs/governance/systematic-audit-w35-2026-05-05.md` §A4 — sufficient.

**Required action.**
- (a) Downgrade the W35-T9 closure level from `verified_at_release_head` to `code-fix-only` in the W35 delivery notice supplement.
- (b) Land `tests/integration/test_run_manager_release_attempt_id_bump.py` (or equivalent) inside the W35 corrective window so the closure level can be promoted to `verified_at_release_head` before W36 entry.

**Acceptance criteria.**
- W35-T9 closure level explicitly stated as `code-fix-only` in the corrective response, OR upgraded to `verified_at_release_head` with the regression test landed.
- Three-part closure documentation updated with the new closure level.

---

## 4. Corrective C-4 — W35-T3 dev-side symmetric test

**Finding.** The W35-T3 fix at `hi_agent/server/run_manager.py:442-518` is symmetric (research/prod raises `TenantScopeError`; dev logs WARNING + uses middleware value). The regression test `tests/integration/test_run_manager_tenant_strict.py` covers the `research/prod` direction (`test_research_posture_body_tenant_id_mismatch_raises` at line 93) but does **not** cover the dev-side direction of the same cross-check — the `body≠middleware → WARNING + middleware-value-used` branch at `run_manager.py:490-497` has no asserting test.

The risk: a future drift on the dev side will not be caught by the existing regression. Symmetric code with asymmetric tests is half a regression net.

**Required action.**
- (a) Add `test_dev_posture_body_tenant_id_mismatch_warns_and_uses_middleware` (or equivalent) to `tests/integration/test_run_manager_tenant_strict.py`.
- (b) The test must assert WARNING is logged AND the middleware value is used (not the body value).

**Acceptance criteria.**
- Test exists with the dual assertion.
- Test passes at the W35 corrective head.

**Three-part closure (Rule 15).** This is test-symmetry completion of C-3-equivalent shape; (b) regression-prevention is the test itself; (c) process change recorded in the audit-doc §A2.

---

## 5. Governance items (W35-corrective-window)

These two items are governance hygiene rather than runtime defects, but both reflect self-referential governance failure (a gate that exists to prevent a class of drift did not fire).

### 5.1 Wave-ledger drift

| Source | Value |
|---|---|
| `docs/governance/current-wave.txt` | `35` |
| `docs/governance/recurrence-ledger.yaml::current_wave` | `33` |

Two-wave drift. The W32-D entry (`recurrence-ledger.yaml` lines 564-589) was created **specifically** to prevent this class of drift and named `check_doc_truth.py` and `check_wave_consistency.py` as enforcement gates. Either the gates have not run on W33–W35 or have a scope regression.

**Required action.**
- (a) Update `recurrence-ledger.yaml::current_wave` from `33` to `35`.
- (b) Identify why `check_wave_consistency.py` (or equivalent) did not catch this. If the gate is not in CI, add it. If it is in CI, fix the scope hole.
- (c) Add a regression test that constructs a deliberate drift and asserts the gate fails.

**Acceptance criteria.**
- `recurrence-ledger.yaml` and `current-wave.txt` byte-match (both report `35`).
- The wave-consistency gate runs in CI and the regression test passes.

### 5.2 Release-captain artifacts at parent HEAD

The W35 release_head is `bd4d38d5`. Pending evidence rows in the delivery notice were filled at parent `d767fde0` and parent-of-parent `04c1faa4`, not at the final HEAD:

| Path | Filled at | Matches `bd4d38d5`? |
|---|---|---|
| `docs/verification/04c1faa4-default-offline-clean-env.json` | `04c1faa4` | NO |
| `docs/verification/04c1faa-arch-7x24.json` | `04c1faa4` | NO |
| `docs/delivery/2026-05-05-460a64bb-t3-volces.json` | does not exist | NO |
| `docs/releases/platform-release-manifest-2026-05-05-460a64bb.json` | does not exist; manifest is at `...-bd4d38d5.json` | NO |
| `docs/verification/d767fde0-default-offline-clean-env.json`, etc. | `d767fde0` (W35 parent) | NO |

The cap rule `clean_env_not_final_head` (cap=60) exists in `docs/governance/score_caps.yaml` for exactly this case but is not in `wave35-signoff.json::cap_factors_active`. Either the gate fails to detect the parent-HEAD condition under the captain's "non-hot-path docs-only" exemption, or the exemption short-circuits the check.

**Required action.**
- (a) Either re-run clean-env / arch-7×24 / T3 Volces evidence at the W35 release_head `bd4d38d5` and emit the `bd4d38d5-*` files; **or** explicitly invoke the "non-hot-path docs-only" exemption in `wave35-signoff.json` with rationale (which W35 hot-path code, if any, was changed between the captain runs and the final HEAD).
- (b) Land a CI gate that detects the parent-HEAD-evidence condition and either fires `clean_env_not_final_head` or applies the exemption with explicit rationale recorded.

**Acceptance criteria.**
- Either evidence files exist at `bd4d38d5` and `cap_factors_active` reflects the cap correctly, OR `wave35-signoff.json` carries an explicit exemption clause naming the hot-path-equivalent code change scope between captain and final HEAD.
- CI gate landed and exercised.

---

## 6. Reporting format (for W35 corrective response)

When you respond to this directive, provide a structured corrective-response section in the W36 entry directive's predecessor or as a standalone supplement:

```
## W35 Corrective Response

| Corrective ID | Status | Evidence path | Provenance | Three-part closure summary |
|---|---|---|---|---|
| C-1 | PASS / IN-PROGRESS | <path to label-revert commit + test + ARCHITECTURE.md edit> | measured | (a) commit SHA + file:line  (b) test path  (c) ARCHITECTURE.md section |
| C-2 | (a) DOCUMENTED / (b) PASS | <path to lifecycle_note OR gate fix> | derived OR measured | three-part as appropriate |
| C-3 | code-fix-only / verified_at_release_head | <path to test if landed> | derived OR measured | three-part as appropriate |
| C-4 | PASS | <path to dev-direction test> | measured | three-part |
| §5.1 wave-ledger | PASS | <ledger update + gate fix + regression test> | measured | three-part |
| §5.2 captain artifacts | PASS or EXEMPT | <evidence at bd4d38d5 OR exemption clause + CI gate> | measured | three-part |
```

`PARTIAL` is **not** an accepted outcome for any of the four C-items. For the two governance items, partial closure with explicit named carryover into W36 is acceptable.

---

## 7. Cross-references

| Document | Purpose |
|---|---|
| `D:\chao_workspace\research\docs\hi-agent-w35-acceptance-audit-2026-05-05.md` | RIA-internal audit (the basis for this directive) |
| `D:\chao_workspace\research\docs\hi-agent-wave35-acceptance-and-wave36-expectations-2026-05-05.md` | predecessor — W35 acceptance + W36 forward (not retracted) |
| `D:\chao_workspace\research\docs\hi-agent-wave36-engineering-expectations-2026-05-05.md` | W36 entry directive (companion to this corrective) |
| `D:\chao_workspace\hi-agent\docs\downstream-responses\2026-05-05-w35-delivery-notice.md` | W35 delivery notice (subject of corrective) |
| `D:\chao_workspace\hi-agent\docs\releases\wave35-signoff.json` | W35 signoff (release_head `bd4d38d5`) |
| `D:\chao_workspace\hi-agent\docs\governance\score_caps.yaml` | cap factor canonical definitions |
| `D:\chao_workspace\hi-agent\docs\governance\recurrence-ledger.yaml` | governance ledger (drifted at W33; §5.1 corrective) |
| `D:\chao_workspace\hi-agent\hi_agent\observability\idempotency_metrics.py` | label drift site (C-1) |
| `D:\chao_workspace\hi-agent\hi_agent\server\run_manager.py:442-518` | T3 symmetric code (C-4 test target) |
| `D:\chao_workspace\hi-agent\hi_agent\server\app.py:1340-1400` | T9 code path (C-3 closure level downgrade) |

---

## 8. Acknowledgement

The W35 ship is accepted. The four corrective items above are not a regression of the W35 endorsement — they are the natural surface area of the deeper code-level audit that follows from the eight named acceptance items. Three of them (C-1 label drift, C-3 closure-level downgrade, C-4 test asymmetry) are pattern-level discipline reminders, not isolated defects: each is a single instance of a class that the platform team has the maturity to handle in the corrective window.

The two governance items (§5) are self-referential failures of gates the platform team itself put in place. Their closure restores the recurrence ledger to its intended self-policing role and is a higher-leverage win than the runtime corrections.

---

**Signed:** RIA team
**Audit head (RIA side):** `main` at 2026-05-05
**Platform head under audit:** `bd4d38d5` (hi-agent W35 release_head per signoff)
**Document maturity:** M1 — internally reviewed; promotes to M2 when mirrored into hi-agent's `docs/upstream-directives/`.

---

**End of W35 Corrective Directive.**
