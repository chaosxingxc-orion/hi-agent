# Wave 35 Corrective Response

Date: 2026-05-05
Wave: 35 (corrective response)
From: hi-agent platform team
To: Research Intelligence Application (RIA) team
Status: in-progress while corrective tracks (A through F) land
Manifest: `2026-05-05-24cfa0a6` (built at HEAD `24cfa0a6`)
Provenance: derived (this document references the W35 manifest and prior delivery notice; per-item evidence carries its own provenance once each track lands)
Functional HEAD: `3bf04dff138343ce397a751e66ca81e10376e56a`
Predecessor: `docs/downstream-responses/2026-05-05-w35-delivery-notice.md` (W35 delivery notice, manifest `2026-05-05-24cfa0a6`)
Directives addressed:
- `docs/upstream-directives/2026-05-05-hi-agent-w35-acceptance-audit.md`
- `docs/upstream-directives/2026-05-05-hi-agent-w35-corrective-directive.md`
- `docs/upstream-directives/2026-05-05-hi-agent-wave36-engineering-expectations.md` (forward, separate response when due)

> Per Rule 14 §4.4, this response cites the W35 manifest's release_head
> (`24cfa0a6`). All commits since the manifest commit are docs-only
> (closure-notice + signoff updates + this corrective response), so
> `check_doc_consistency.py` accepts the head divergence under its
> docs-only-gap exemption. The W35 corrective tracks below reference
> their own evidence at the correction-window head as it lands.

---

## 1. Acknowledgement

We accept all six corrective items raised in `docs/upstream-directives/2026-05-05-hi-agent-w35-corrective-directive.md` (C-1, C-2, C-3, C-4, §5.1 wave-ledger, §5.2 captain artifacts) as binding on the W35 corrective window. Each item aligns with our positioning of the platform as a capability-layer northbound facade: C-1 (Prometheus label consistency) and C-2 (cap-factor naming clarity) are stability-of-contract obligations to downstream consumers; C-3 (Rule 15 closure-level honesty) and C-4 (test symmetry across postures) are observable-degradation discipline at the regression net itself; §5.1 (wave-ledger consistency) and §5.2 (release-captain artifacts at the final HEAD) are sustainable-evolution obligations of the governance system to its own future readers. None of the six relax our capability/business separation; all six narrow the contract surface to what the platform actually delivers.

We treat the corrective items as an extension of W35 rather than a regression of it. The W35 ship and the W34 acceptance both stand. The work below tightens the regression net and restores self-policing of the governance ledger that the platform team itself put in place.

---

## 2. Per-item Disposition

| Corrective ID | Status | Evidence path | Provenance | Three-part closure summary |
|---|---|---|---|---|
| C-1 (Prometheus label revert) | IN-PROGRESS (Track A) | tests/integration/test_idempotency_metrics.py + docs/observability/idempotency-metrics.md + hi_agent/observability/ARCHITECTURE.md | measured | (a) `hi_agent/observability/idempotency_metrics.py` revert four metrics from `{tenant_bucket}` to `{tenant_id}`; (b) `test_metric_label_set` asserts label name set per metric; (c) Cardinality-control policy paragraph — platform-side metrics carry `{tenant_id}`; bucketing is derived ops-side via PromQL recording rules; `hi_agent_llm_tokens_total` recorded as documented exception |
| C-2 (provenance cap clarification) | IN-PROGRESS (Track B) | docs/governance/score_caps.yaml lifecycle_note OR scripts/build_release_manifest.py gate fix | derived | TBD pending Track B disposition: reading (a) implicit-resolution publishes a lifecycle_note on `provenance_unknown_or_synthetic`; reading (b) gate-scope-hole adds the missing detection at manifest-build time and either re-fires the cap or documents non-firing conditions |
| C-3 (W35-T9 closure level) | IN-PROGRESS (Track C) — promoting to verified_at_release_head | tests/integration/test_run_manager_release_attempt_id_bump.py | measured | (a) Code fix already at `hi_agent/server/app.py:1340-1400` (verified by RIA audit); (b) New regression test landing at `tests/integration/test_run_manager_release_attempt_id_bump.py` asserting fresh `attempt_id`, `parent_run_id=run_id`, and `attempt_count` bump on re-lease; (c) Closure-taxonomy promotion from `code-fix-only` to `verified_at_release_head` recorded in `docs/governance/closure-taxonomy.md` and W35 delivery notice supplement |
| C-4 (W35-T3 dev-side test) | IN-PROGRESS (Track D) | tests/integration/test_run_manager_tenant_strict.py | measured | (a) NONE — code already symmetric at `hi_agent/server/run_manager.py:442-518` (research/prod raises `TenantScopeError`; dev WARNs and uses middleware value); (b) New test `test_dev_posture_body_tenant_id_mismatch_warns_and_uses_middleware` asserts dual property (WARNING logged AND middleware value used, not body value); (c) Recurrence-ledger entry on the test-symmetry pattern — symmetric code with asymmetric tests is a defect class to be detected at PR time |
| §5.1 wave-ledger drift | IN-PROGRESS (Track E) | docs/governance/recurrence-ledger.yaml + scripts/check_wave_consistency.py | measured | (a) Update `recurrence-ledger.yaml::current_wave` from `33` to `35`; (b) Extend `scripts/check_wave_consistency.py` to assert byte-match between `current-wave.txt`, `recurrence-ledger.yaml::current_wave`, latest manifest `wave`, and latest non-draft notice; new gate test constructs a deliberate drift and asserts the gate fails; (c) Rule 14 / W17 reinforcement note in CLAUDE.md narrow-trigger appendix that a wave-ledger drift detected after a manifest is published triggers a recurrence-ledger entry, not a silent fix |
| §5.2 captain artifacts at parent HEAD | IN-PROGRESS (Track F) | docs/verification/<release_head>-* OR explicit signoff exemption | TBD (real if Volces re-run; derived if exemption clause) | (a) Either re-run clean-env / arch-7×24 / T3 Volces evidence at the W35 release_head and emit the `24cfa0a6-*` files OR add an explicit "non-hot-path docs-only" exemption clause to `wave35-signoff.json` naming the descendant scope; (b) New gate to detect parent-HEAD-evidence: `scripts/check_evidence_at_release_head.py` asserts that captain-recorded evidence files match the manifest `release_head` field, otherwise fires `clean_env_not_final_head` cap unless an explicit exemption is present; (c) Signoff schema enrichment — `wave35-signoff.json` schema gains optional `evidence_head_exemption` block (rationale, descendant-commit-scope, captain signature) |

`PARTIAL` is not used as a status — each row is `IN-PROGRESS` until its three-part closure lands at the corrective-window head, at which point the row becomes `PASS` and this document is reissued (or supplemented).

---

## 3. Cross-Reference Table (mirrors §7 of the corrective directive, with local paths)

| Document | Purpose |
|---|---|
| `docs/upstream-directives/2026-05-05-hi-agent-w35-acceptance-audit.md` | RIA-internal audit (the basis for the corrective directive) |
| `docs/upstream-directives/2026-05-05-hi-agent-w35-corrective-directive.md` | Corrective directive (subject of this response) |
| `docs/upstream-directives/2026-05-05-hi-agent-wave36-engineering-expectations.md` | W36 entry directive (separate response when due) |
| `docs/downstream-responses/2026-05-05-w35-delivery-notice.md` | W35 delivery notice (subject of corrective) |
| `docs/releases/wave35-signoff.json` | W35 signoff (release_head `24cfa0a6`) |
| `docs/releases/platform-release-manifest-2026-05-05-24cfa0a6.json` | W35 release manifest |
| `docs/governance/score_caps.yaml` | Cap-factor canonical definitions (C-2) |
| `docs/governance/recurrence-ledger.yaml` | Governance ledger (drift cited by §5.1) |
| `docs/governance/systematic-audit-w35-2026-05-05.md` | Internal W35 audit (process-change anchor for several tracks) |
| `hi_agent/observability/idempotency_metrics.py` | Label drift site (C-1 code fix) |
| `hi_agent/server/run_manager.py` lines 442-518 | T3 symmetric code (C-4 test target) |
| `hi_agent/server/app.py` lines 1340-1400 | T9 code path (C-3 closure level promotion target) |

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
Date: 2026-05-05
Document maturity: M1 — in-progress; promotes to M2 after all six tracks (A through F) land at the corrective-window head and this document is reissued with each row marked `PASS` and three-part evidence paths populated.
Status: in-progress while corrective tracks land
