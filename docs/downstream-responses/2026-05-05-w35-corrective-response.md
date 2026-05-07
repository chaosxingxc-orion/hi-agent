# Wave 35 Corrective Response

Date: 2026-05-05
Wave: 35 (corrective response)
From: hi-agent platform team
To: Research Intelligence Application (RIA) team
Status: PASS — all 6 corrective items closed at HEAD ad521c07 per RIA audit 2026-05-07
Manifest: `2026-05-06-ad521c07` (built at HEAD `ad521c07`)
Provenance: measured (per-item evidence paths recorded against the corrective close HEAD; cross-checked by RIA's 2026-05-07 acceptance audit)
Functional HEAD: `975b7911494502a829b45d96ce8c59bc5482d31f`
Predecessor: `docs/downstream-responses/2026-05-05-w35-delivery-notice.md` (W35 delivery notice, manifest `2026-05-05-24cfa0a6`)
Directives addressed:
- `docs/upstream-directives/2026-05-05-hi-agent-w35-acceptance-audit.md`
- `docs/upstream-directives/2026-05-05-hi-agent-w35-corrective-directive.md`
- `docs/upstream-directives/2026-05-05-hi-agent-wave36-engineering-expectations.md` (forward, separate response when due)

> Per Rule 14 §4.4, this response cites the W35 corrective-close manifest's
> release_head (`ad521c07`). All commits since the manifest commit are
> docs-only (this reissue + RIA-mirrored 2026-05-07 directives + W36
> supplement plan-index), so `check_doc_consistency.py` accepts the head
> divergence under its docs-only-gap exemption. RIA's 2026-05-07 acceptance
> audit cross-checked each row's evidence at HEAD `ad521c07` and verified
> all 6 items at M2; this reissue updates each row's Status from
> IN-PROGRESS / TBD to PASS with measured-evidence paths.

---

## 1. Acknowledgement

We accept all six corrective items raised in `docs/upstream-directives/2026-05-05-hi-agent-w35-corrective-directive.md` (C-1, C-2, C-3, C-4, §5.1 wave-ledger, §5.2 captain artifacts) as binding on the W35 corrective window. Each item aligns with our positioning of the platform as a capability-layer northbound facade: C-1 (Prometheus label consistency) and C-2 (cap-factor naming clarity) are stability-of-contract obligations to downstream consumers; C-3 (Rule 15 closure-level honesty) and C-4 (test symmetry across postures) are observable-degradation discipline at the regression net itself; §5.1 (wave-ledger consistency) and §5.2 (release-captain artifacts at the final HEAD) are sustainable-evolution obligations of the governance system to its own future readers. None of the six relax our capability/business separation; all six narrow the contract surface to what the platform actually delivers.

We treat the corrective items as an extension of W35 rather than a regression of it. The W35 ship and the W34 acceptance both stand. The work below tightens the regression net and restores self-policing of the governance ledger that the platform team itself put in place.

---

## 2. Per-item Disposition

| Corrective ID | Status | Evidence path | Provenance | Three-part closure summary |
|---|---|---|---|---|
| C-1 (Prometheus label revert) | PASS | `hi_agent/observability/idempotency_metrics.py:88,108,137,158` + `tests/integration/test_idempotency_metrics.py:236-307` + `docs/observability/idempotency-metrics.md:185-204` + `hi_agent/observability/ARCHITECTURE.md:288-302` (ADR-OBS-2) | measured | (a) `hi_agent/observability/idempotency_metrics.py:88,108,137,158` reverts four metrics from `{tenant_bucket}` to `{tenant_id}`; (b) `tests/integration/test_idempotency_metrics.py:236-307::test_metric_label_set` asserts the frozenset label set per metric (drift guard); (c) Cardinality-control policy paragraph anchored in two places — `docs/observability/idempotency-metrics.md:185-204` AND `hi_agent/observability/ARCHITECTURE.md:288-302` (ADR-OBS-2): platform-side metrics carry `{tenant_id}`; bucketing is derived ops-side via PromQL recording rules; `hi_agent_llm_tokens_total` documented as W31 cardinality precedent |
| C-2 (provenance cap clarification) | PASS | `docs/governance/score_caps.yaml:147-152` (`lifecycle_note`) | derived | (a) `docs/governance/score_caps.yaml:147-152` carries the `lifecycle_note` declaring **reading (a) implicit-resolution** with verification grep evidence at W35 release_head + post-W34 heads (zero `provenance:synthetic|unknown` files), re-fire trigger named, detection scope at `build_release_manifest.py::_compute_cap`; (b) latest `wave35-signoff.json::cap_factors_active` correctly omits the rule (gate evidence — only `t3_deferred` + `soak_evidence_not_real` fire); (c) lifecycle_note process-change discipline: any future cap-rule whose live state is implicit-resolution must declare its lifecycle inline at the `score_caps.yaml` row |
| C-3 (W35-T9 closure level) | PASS — verified_at_release_head | `tests/integration/test_run_manager_release_attempt_id_bump.py` + `hi_agent/server/app.py:1218-1275` (`_bump_attempt_id_on_release` extraction) | measured | (a) `_bump_attempt_id_on_release` extracted at `hi_agent/server/app.py:1218-1275` for testability without semantic change; `_rehydrate_runs` calls helper at `app.py:1410-1413`; mirror-update at `app.py:1417-1436` preserved; (b) `tests/integration/test_run_manager_release_attempt_id_bump.py` (3 tests, 3/3 PASS) asserts fresh uuid4 `attempt_id`, `parent_run_id=run_id`, and `attempt_count` increment across both populated and zero-baseline branches; (c) Closure-taxonomy promotion from `code-fix-only` to `verified_at_release_head` recorded in `docs/governance/closure-taxonomy.md` and W35 delivery notice supplement (in-memory `ManagedRun` mirror update remains a documented scope choice) |
| C-4 (W35-T3 dev-side test) | PASS | `tests/integration/test_run_manager_tenant_strict.py:181-223::test_dev_posture_body_tenant_id_mismatch_warns_and_uses_middleware` | measured | (a) NONE — code already symmetric at `hi_agent/server/run_manager.py:442-518` (research/prod raises `TenantScopeError`; dev WARNs and uses middleware value); (b) `tests/integration/test_run_manager_tenant_strict.py:181-223::test_dev_posture_body_tenant_id_mismatch_warns_and_uses_middleware` — caplog WARNING assertion (lines 215-220, both tenant ids named) + middleware-value-used assertion (line 207); 8/8 tests PASS; (c) Recurrence-ledger entry on the test-symmetry defect class (symmetric code with asymmetric tests is a defect detected at PR time) |
| §5.1 wave-ledger drift | PASS | `recurrence-ledger.yaml::current_wave=35` + `scripts/check_wave_consistency.py` (5th source) + `tests/integration/test_check_wave_consistency_ledger.py` + ledger entry W32-D-recurrence | measured | (a) `current-wave.txt:1` and `recurrence-ledger.yaml::current_wave` both `35` (drift removed); (b) `scripts/check_wave_consistency.py` extended with 5th source via new helper `_recurrence_ledger_current_wave()` (L64-L88; sources dict updated at L207-L213); regression `tests/integration/test_check_wave_consistency_ledger.py` (3 cases — drift-fails, agree-passes, missing-ledger-does-not-block); CI wired at `.github/workflows/release-gate.yml:213`; (c) `recurrence-ledger.yaml:591-608` self-documents the gate-scope hole as entry W32-D-recurrence with `current_closure_level: verified_at_release_head` — the higher-leverage fix per RIA's 2026-05-07 audit §0.2 |
| §5.2 captain artifacts at parent HEAD | PASS (path a chosen) | `wave35-signoff.json::evidence_exemption.kind="none"` + `scripts/check_signoff_evidence_exemption.py` (CI wired at `release-gate.yml:379`) + clean-env at `5b1e4d25` + arch-7×24 at `5ba9bb7` | measured | (a) Path (a) executed — re-rolled clean-env at intermediate corrective HEAD `5b1e4d25` (`docs/verification/5b1e4d25-default-offline-clean-env.json`) and arch-7×24 at `5ba9bb7` (`docs/verification/5ba9bb7-arch-7x24.json`); the remaining 6-commit gap to final HEAD `ad521c07` is governance-only and declared in `wave35-signoff.json::evidence_exemption.kind: "none"` block with all 5 required fields populated; (b) `scripts/check_signoff_evidence_exemption.py` enforces 5-field + enum + gov-only-gap reality check; CI wired at `.github/workflows/release-gate.yml:379` (live gate run PASS exit 0); (c) Signoff schema discipline — `wave35-signoff.json` carries the `evidence_exemption` block with full `hot_path_audit` so future asymmetries cannot ship silently. RIA 2026-05-07 audit §0.2 cited this as "the harder path chosen over the easier path" |

`PARTIAL` is not used as a status — each row above has reached `PASS` with three-part closure landed at corrective-window HEAD `ad521c07`. RIA's 2026-05-07 acceptance audit cross-checked each row's evidence and verified all 6 items at maturity M2.

---

## 3. Cross-Reference Table (mirrors §7 of the corrective directive, with local paths)

| Document | Purpose |
|---|---|
| `docs/upstream-directives/2026-05-05-hi-agent-w35-acceptance-audit.md` | RIA-internal audit (the basis for the corrective directive) |
| `docs/upstream-directives/2026-05-05-hi-agent-w35-corrective-directive.md` | Corrective directive (subject of this response) |
| `docs/upstream-directives/2026-05-05-hi-agent-wave36-engineering-expectations.md` | W36 entry directive (separate response when due) |
| `docs/downstream-responses/2026-05-05-w35-delivery-notice.md` | W35 delivery notice (subject of corrective) |
| `docs/releases/wave35-signoff.json` | W35 corrective-close signoff (manifest `2026-05-06-ad521c07`, release_head `ad521c07`) |
| `docs/releases/platform-release-manifest-2026-05-06-ad521c07.json` | W35 corrective-close release manifest (latest); predecessor `2026-05-05-24cfa0a6` archived under `docs/releases/archive/W35/` |
| `docs/upstream-directives/2026-05-07-hi-agent-w35-corrective-acceptance-audit.md` | RIA acceptance audit verifying M2 closure |
| `docs/upstream-directives/2026-05-07-hi-agent-w35-corrective-acceptance-and-w36-supplement-directive.md` | RIA acceptance directive (basis for this PASS reissue) |
| `docs/governance/score_caps.yaml` | Cap-factor canonical definitions (C-2) |
| `docs/governance/recurrence-ledger.yaml` | Governance ledger (drift cited by §5.1) |
| `docs/governance/systematic-audit-w35-2026-05-05.md` | Internal W35 audit (process-change anchor for several tracks) |
| `hi_agent/observability/idempotency_metrics.py` | Label drift site (C-1 code fix) |
| `hi_agent/server/run_manager.py` lines 442-518 | T3 symmetric code (C-4 test target) |
| `hi_agent/server/app.py:1218-1275` | T9 code path (`_bump_attempt_id_on_release` extracted for C-3 closure) |

---

## 4. Statement on Hidden Findings (Class-level Sweep)

The six corrective items are individual instances of five defect classes:
- C-1: contract-surface naming drift (label, route, field, env-var renames without notice).
- C-2: cap-factor active-set hygiene (gate scope holes vs. silent resolution).
- C-3: closure-level overstatement (Rule 15 levels asserted without all three parts).
- C-4: asymmetric tests on symmetric code (half-a-regression-net pattern).
- §5.2: evidence-at-parent-HEAD (captain artifacts not at the manifest release_head).

We are running a parallel systematic codebase scan for hidden instances of each class — Prometheus label inventory across `hi_agent/observability/**`, cap-rule vs. signoff-active-set audit across `docs/governance/score_caps.yaml`, Rule-15 closure-level audit across delivery notices and waivers, posture-test symmetry audit across `tests/integration/**`, evidence-head audit across `docs/verification/` and `docs/delivery/`. Supplemental findings will be filed as `docs/downstream-responses/2026-05-05-w35-corrective-response-supplement.md` and will follow the same per-item disposition format as §2 above.

The supplement will name each class instance individually with `IN-PROGRESS` or `OUT-OF-SCOPE-FOR-W35-CORRECTIVE-WINDOW` (carry to W36) status; we do not bundle class instances into single tracks unless the fix is mechanically uniform (e.g., a single label-revert commit covering N drifted metrics).

---

## 5. Sign-off

Signed: hi-agent platform team
Date: 2026-05-05 (initial); reissued 2026-05-07 (PASS)
Document maturity: M2 — reissued at HEAD `975b7911` after RIA's 2026-05-07 acceptance audit cross-checked all six tracks at corrective-window HEAD `ad521c07` and verified each row at M2 with measured-evidence paths populated.
Status: PASS — all 6 corrective items closed at HEAD ad521c07 per RIA audit 2026-05-07
