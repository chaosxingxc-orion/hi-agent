# Orphan Governance Gates Audit (2026-05-05)

**Trigger.** Hidden-defect scan revealed `scripts/check_*.py` files not invoked by any
`.github/workflows/*.yml` and not invoked indirectly via
`scripts/_governance/multistatus_runner.py`. Per CLAUDE.md Rule 17 ("an allowlist entry is
tracked technical debt, not a closure"), an orphan governance script is undeclared technical
debt: the rule it asserts is unenforced even though the code exists to assert it.

**Method.** Glob `scripts/check_*.py` (89 scripts total). Cross-reference against
`.github/workflows/*.yml` (69 direct CI references) and the multistatus runner registry
(9 indirect references via `scripts._governance.multistatus_runner`). Subtract: 11 truly
orphan scripts. Run each locally at HEAD `3bf04dff` against the repo root. Wire only the
PASSING scripts to `release-gate.yml` per the W35-corrective audit; any FAILing scripts
would be deferred to this document with reason and target wave.

## Coverage map (all 89 scripts)

| script                                         | direct CI? | multistatus? | imported? | passes locally? | proposal                |
|------------------------------------------------|-----------:|-------------:|----------:|----------------:|-------------------------|
| check_admin_session_store_imports.py           |         no |           no |        no |             yes | wire (W35-corrective)   |
| check_agent_kernel_pin.py                      |        yes |           no |        no |             yes | already wired           |
| check_allowlist_discipline.py                  |        yes |           no |        no |             yes | already wired           |
| check_allowlist_universal.py                   |        yes |           no |        no |             yes | already wired           |
| check_async_init_resources.py                  |        yes |           no |        no |             yes | already wired           |
| check_boundary.py                              |        yes |           no |        no |             yes | already wired           |
| check_capability_maturity.py                   |        yes |           no |        no |             yes | already wired           |
| check_chaos_runtime_coupling.py                |        yes |           no |        no |             yes | already wired           |
| check_clean_env.py                             |        yes |           no |        no |             yes | already wired           |
| check_closure_levels.py                        |        yes |           no |        no |             yes | already wired           |
| check_closure_taxonomy.py                      |        yes |           no |        no |             yes | already wired           |
| check_concurrency_evidence.py                  |         no |           no |        no |             yes | wire (W35-corrective)   |
| check_conftest_fallback_scope.py               |        yes |           no |        no |             yes | already wired           |
| check_contract_freeze.py                       |         no |          yes |        no |             yes | already covered         |
| check_contract_spine_completeness.py           |        yes |           no |        no |             yes | already wired           |
| check_contracts_purity.py                      |         no |          yes |        no |             yes | already covered         |
| check_dataclass_spine_validation.py            |         no |           no |        no |             yes | wire (W35-corrective)   |
| check_deprecated_field_usage.py                |        yes |           no |        no |             yes | already wired           |
| check_doc_canonical_symbols.py                 |        yes |           no |        no |             yes | already wired           |
| check_doc_consistency.py                       |        yes |           no |        no |             yes | already wired           |
| check_doc_truth.py                             |        yes |           no |        no |             yes | already wired           |
| check_documented_routes.py                     |         no |           no |        no |             yes | wire (W35-corrective)   |
| check_downstream_response_format.py            |        yes |           no |        no |             yes | already wired           |
| check_durable_wiring.py                        |        yes |           no |        no |             yes | already wired           |
| check_env_var_routing.py                       |         no |           no |        no |             yes | wire (W35-corrective)   |
| check_evidence_identity.py                     |        yes |           no |        no |             yes | already wired           |
| check_evidence_provenance.py                   |        yes |           no |        no |             yes | already wired           |
| check_expired_waivers.py                       |        yes |           no |        no |             yes | already wired           |
| check_facade_loc.py                            |         no |          yes |        no |             yes | already covered         |
| check_facade_seams.py                          |         no |           no |        no |             yes | wire (W35-corrective)   |
| check_gate_strictness.py                       |        yes |           no |        no |             yes | already wired           |
| check_idempotency_contract_documented.py       |         no |           no |        no |             yes | wire (W35-corrective)   |
| check_layering.py                              |        yes |           no |        no |             yes | already wired           |
| check_lineage_population.py                    |         no |           no |        no |             yes | wire (W35-corrective)   |
| check_manifest_budget.py                       |        yes |           no |        no |             yes | already wired           |
| check_manifest_freshness.py                    |        yes |           no |        no |             yes | already wired           |
| check_manifest_rewrite_budget.py               |        yes |           no |        no |             yes | already wired           |
| check_metric_producers.py                      |        yes |           no |        no |             yes | already wired           |
| check_metrics_cardinality.py                   |        yes |           no |        no |             yes | already wired           |
| check_multistatus_gates.py                     |        yes |           no |        no |             yes | already wired           |
| check_no_domain_types.py                       |         no |          yes |        no |             yes | already covered         |
| check_no_hardcoded_wave.py                     |        yes |           no |        no |             yes | already wired           |
| check_no_hi_agent_env_direct_read.py           |         no |           no |        no |             yes | wire (W35-corrective)   |
| check_no_research_vocab.py                     |        yes |           no |        no |             yes | already wired           |
| check_no_reverse_imports.py                    |         no |          yes |        no |             yes | already covered         |
| check_no_shell_packages.py                     |         no |           no |        no |             yes | wire (W35-corrective)   |
| check_no_unscoped_knowledge_reads.py           |         no |           no |        no |             yes | wire (W35-corrective)   |
| check_no_wave_tags.py                          |        yes |           no |        no |             yes | already wired           |
| check_noqa_discipline.py                       |        yes |           no |        no |             yes | already wired           |
| check_notice_pre_final_commit_clean.py         |        yes |           no |        no |             yes | already wired           |
| check_notice_score_match.py                    |        yes |           no |        no |             yes | already wired           |
| check_observability_spine_completeness.py      |        yes |           no |        no |             yes | already wired           |
| check_operator_drill.py                        |        yes |           no |        no |             yes | already wired           |
| check_owner_tag.py                             |        yes |           no |        no |             yes | already wired           |
| check_posture_coverage.py                      |        yes |           no |        no |             yes | already wired           |
| check_pytest_markers.py                        |        yes |           no |        no |             yes | already wired           |
| check_pytest_skip_discipline.py                |        yes |           no |        no |             yes | already wired           |
| check_recurrence_ledger.py                     |        yes |           no |        no |             yes | already wired           |
| check_release_identity.py                      |        yes |           no |        no |             yes | already wired           |
| check_root_cause_block.py                      |        yes |           no |        no |             yes | already wired           |
| check_route_coverage.py                        |        yes |           no |        no |             yes | already wired           |
| check_route_scope.py                           |        yes |           no |        no |             yes | already wired           |
| check_route_tenant_context.py                  |         no |          yes |        no |             yes | already covered         |
| check_rule7_observability.py                   |        yes |           no |        no |             yes | already wired           |
| check_rule9_open_findings.py                   |        yes |           no |        no |             yes | already wired           |
| check_rules.py                                 |        yes |           no |        no |             yes | already wired           |
| check_score_artifact_consistency.py            |         no |          yes |        no |             yes | already covered         |
| check_score_cap.py                             |        yes |           no |        no |             yes | already wired           |
| check_secrets.py                               |        yes |           no |        no |             yes | already wired           |
| check_select_completeness.py                   |        yes |           no |        no |             yes | already wired           |
| check_self_audit.py                            |        yes |           no |        no |             yes | already wired           |
| check_silent_degradation.py                    |        yes |           no |        no |             yes | already wired           |
| check_slo_health.py                            |        yes |           no |        no |             yes | already wired           |
| check_soak_evidence.py                         |        yes |           no |        no |             yes | already wired           |
| check_spine_completeness.py                    |        yes |           no |        no |             yes | already wired           |
| check_sqlite_pragma.py                         |        yes |           no |        no |             yes | already wired           |
| check_state_transition_centralization.py       |         no |          yes |        no |             yes | already covered         |
| check_state_transition_coverage.py             |        yes |           no |        no |             yes | already wired           |
| check_surgical_changes.py                      |        yes |           no |        no |             yes | already wired           |
| check_t3_evidence.py                           |        yes |           no |        no |             yes | already wired           |
| check_t3_freshness.py                          |        yes |           no |        no |             yes | already wired           |
| check_targeted_default_path.py                 |        yes |           no |        no |             yes | already wired           |
| check_tdd_evidence.py                          |         no |          yes |        no |             yes | already covered         |
| check_test_honesty.py                          |        yes |           no |        no |             yes | already wired           |
| check_untracked_release_artifacts.py           |        yes |           no |        no |             yes | already wired           |
| check_vacuous_asserts.py                       |        yes |           no |        no |             yes | already wired           |
| check_validate_before_mutate.py                |        yes |           no |        no |             yes | already wired           |
| check_verification_artifacts.py                |        yes |           no |        no |             yes | already wired           |
| check_wave_consistency.py                      |        yes |           no |        no |             yes | already wired           |

## Wired in this audit (W35-corrective)

11 scripts moved from orphan → CI-blocking via `.github/workflows/release-gate.yml`
(W35-corrective step block). All eleven were verified to exit 0 against current `main`
(HEAD `3bf04dff`) before wiring; an always-failing CI gate is worse than no gate, so
none of these are advisory.

| # | Script                                       | Asserts                                                  |
|---|----------------------------------------------|----------------------------------------------------------|
| 1 | check_admin_session_store_imports.py         | only `_admin_session_store.py` imports the admin module  |
| 2 | check_concurrency_evidence.py                | concurrency baseline artifact freshness                  |
| 3 | check_dataclass_spine_validation.py          | spine dataclasses carry `__post_init__` validation       |
| 4 | check_documented_routes.py                   | documented↔decorated route inventory match               |
| 5 | check_env_var_routing.py                     | env vars routed via `Posture.from_env()` (Rule 6)        |
| 6 | check_facade_seams.py                        | `agent_server.facade/runtime` annotates `hi_agent` seams (R-AS-1) |
| 7 | check_idempotency_contract_documented.py     | idempotency contract surface documented                  |
| 8 | check_lineage_population.py                  | RunExecutionContext lineage is not hardcoded-empty       |
| 9 | check_no_hi_agent_env_direct_read.py         | no direct `os.environ['HI_AGENT_*']` outside allowlist (Rule 6) |
| 10 | check_no_shell_packages.py                  | no unannotated shell packages under `agent_server/`/`hi_agent/` |
| 11 | check_no_unscoped_knowledge_reads.py        | KG reads carry tenant scope                              |

## Deferred

None. All 11 truly orphan scripts pass at HEAD `3bf04dff` and are now CI-blocking. If a
future change introduces a regression, the gate will fire on the offending PR and the
debt-recurrence ledger entry below will be re-opened.

## Recurrence-ledger recommendation

This audit recommends a recurrence-ledger entry titled
`W35-orphan-gates-corrective` (Track GOV / Track E owns), pointing to this document and
attesting that 11 previously-orphan scripts are now wired. The author of this audit
**does not** modify `recurrence-ledger.yaml` directly per CLAUDE.md ownership rules —
the recommendation is filed here for the release captain's intake.

**Class root cause.** A script written under `scripts/` is not a gate until a workflow
invokes it. There was no build-time check that every `check_*.py` is referenced from at
least one workflow OR from the multistatus runner. The corrective: add a meta-gate that
fails CI when a `scripts/check_*.py` exists with zero workflow references.

**Suggested follow-up** (not done in this audit): land a `check_orphan_check_scripts.py`
meta-gate in W36 so this class never recurs.
