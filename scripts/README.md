# scripts — Governance Gates Index

> **Last refreshed:** 2026-05-06 (W35 corrective close + W36 plans). HEAD `276917d8`.
> **Audience:** GOV-track owners + anyone touching CI configuration.

This directory hosts **governance gate scripts** that enforce CLAUDE.md rules, plus the runners that drive Rule 8 / Rule 4 verification. Each script has a single responsibility. Most run as required CI gates; a handful are advisory or scheduled.

**Coverage status (W35 corrective):** 89 `check_*.py` scripts total; after the W35-corrective audit (`docs/governance/orphan-gates-audit-2026-05-05.md`) wired 11 previously-orphan gates into `release-gate.yml`, **100 % of governance scripts are now invoked by CI** — directly or indirectly through `scripts/_governance/multistatus_runner.py`.

---

## Invocation

All scripts use the `python scripts/<name>.py [--json]` shape and run from repo root. Standard exit codes:

| Code | Meaning |
|---|---|
| `0` | Pass / clean |
| `1` | Fail / defect detected |
| `2` | Deferred / not applicable (a few scripts only — e.g. `check_t3_evidence.py` when scoped freshness deferred) |

Most scripts also accept `--json` to emit a structured report consumed by `_governance_json.py`.

---

## Inventory by category

### A. Release gates (manifest, identity, freshness)

| Script | Asserts |
|---|---|
| `build_release_manifest.py` | Generates `docs/releases/platform-release-manifest-<date>-<short_sha>.json` from current HEAD + collected evidence; computes 3-tier scores (`raw_implementation_maturity` / `current_verified_readiness` / `conditional_readiness_after_blockers`). |
| `check_release_identity.py` | Manifest `release_head` equals `git rev-parse HEAD`; `git.is_dirty == false` (Rule 14 §4.2). |
| `check_manifest_freshness.py` | Manifest is the most recent in `docs/releases/`; gap to HEAD is docs-only or gov-infra-only (Rule 14 definitions). |
| `check_manifest_rewrite_budget.py` | Max 3 manifest rewrites per wave (W17/B19). |
| `check_manifest_budget.py` | Manifest size / count budget. |
| `check_signoff_evidence_exemption.py` | New W35-corrective §5.2 — validates evidence-exemption block is structurally sound when invoked. |
| `check_doc_consistency.py` | Closure notices cite manifest_id; Functional HEAD matches `release_head`; Check 11 enforces Rule 15 closure-level enum on every defect row. |
| `check_score_artifact_consistency.py` | Manifest scores agree across linked artifacts. |
| `check_score_cap.py` | Active cap factors in manifest justify the verified-readiness reduction. |
| `check_release_captain_checklist.py` (if present) | Captain checklist signoff present for release commit. |

### B. Wave discipline

| Script | Asserts |
|---|---|
| `check_wave_consistency.py` | `current-wave.txt`, `allowlists.yaml::current_wave`, latest manifest `wave`, latest non-draft notice all agree (W17/B11). |
| `check_doc_truth.py` | Doc-stated facts (HEAD shorts, dates, score numbers) match manifest. |
| `check_recurrence_ledger.py` | Defect classes that re-appear are tracked in `docs/governance/recurrence-ledger.yaml`. |
| `check_no_hardcoded_wave.py` | No literal wave numbers baked into source. |
| `check_no_wave_tags.py` | Old `[Wave N]` commit-tag style not used in current code. |
| `check_untracked_release_artifacts.py` | No uncommitted manifests / verifications outside `docs/.../archive/` (W17/B13). |
| `check_notice_pre_final_commit_clean.py` | Closure notices are clean of pre-final-commit noise (W35 specific). |
| `check_notice_score_match.py` | Closure-notice headlines cite the manifest's `current_verified_readiness` only. |

### C. Contract discipline (CO + AS-CO tracks)

| Script | Asserts |
|---|---|
| `check_contract_freeze.py` | `agent_server/contracts/v1/**` is byte-frozen against `docs/governance/contract_v1_freeze.json`. |
| `check_contract_spine_completeness.py` | Every persistent record carries `tenant_id` + spine subset (Rule 12). |
| `check_dataclass_spine_validation.py` | Spine fields are validated where mutated. |
| `check_contracts_purity.py` | `hi_agent/contracts/` and kernel contract modules import nothing from `hi_agent.runtime_*` or business strategy code. |
| `check_facade_loc.py` | Each `agent_server/facade/**` module ≤200 LOC (R-AS-8). |
| `check_facade_seams.py` | Facade modules don't import internal kernel state directly. |
| `check_layering.py` | Top-level layering rules: `agent_kernel` < `hi_agent` < `agent_server`. |
| `check_no_reverse_imports.py` | `agent_kernel` never imports `hi_agent.*` / `agent_server.*`. |
| `check_no_domain_types.py` | Kernel admission gate references no provider/model/strategy names. |
| `check_no_hi_agent_env_direct_read.py` | `agent_kernel` never reads `HI_AGENT_*` env vars directly. |
| `check_no_unscoped_knowledge_reads.py` | Knowledge graph reads always carry tenant scope. |
| `check_idempotency_contract_documented.py` | Idempotency-replay semantics documented per route. |
| `check_documented_routes.py` / `check_route_coverage.py` / `check_route_scope.py` / `check_route_tenant_context.py` | Route inventory complete; every route has a tenant-context fixture. |

### D. Evidence discipline

| Script | Asserts |
|---|---|
| `check_evidence_provenance.py` | Evidence files (clean-env, arch-7x24, observability-spine) carry `provenance: real|synthetic|deferred` and identity-bind to `release_head`. |
| `check_evidence_identity.py` | Evidence file `commit_sha` matches its filename short. |
| `check_clean_env.py` | A `default-offline-clean-env` artifact exists for current HEAD. |
| `check_t3_evidence.py` | T3 real-LLM evidence exists for hot-path commits (Rule 8). |
| `check_t3_freshness.py` | T3 evidence freshness window valid for current HEAD. |
| `check_observability_spine_completeness.py` | Spine evidence covers all 8 mandatory targets. |
| `check_chaos_runtime_coupling.py` | All 10 chaos scenarios are runtime-coupled (Rule 8 architectural 7×24 §3). |
| `check_concurrency_evidence.py` | Concurrency-baseline artifact present + recent. |
| `check_verification_artifacts.py` | Required verification artifacts exist for current HEAD. |
| `check_soak_evidence.py` | Soak evidence file present and identity-bound when soak gate is required. |

### E. Code discipline (Rules 1–7)

| Script | Asserts |
|---|---|
| `check_rules.py` | Bundle: Language rule, Rule 4 (3-layer testing, advisory), Rule 5 (`asyncio.run` site discipline), Rule 6 (inline-fallback `x or DefaultX()` ban). |
| `check_async_init_resources.py` | No `httpx.AsyncClient` / `aiohttp.ClientSession` constructed in `__init__` of sync-facing classes. |
| `check_silent_degradation.py` | Every fallback branch emits Countable + Attributable + Inspectable signal (Rule 7). |
| `check_rule7_observability.py` | Rule 7 specifically — fallback metrics + WARNING+ logs + run metadata. |
| `check_rule9_open_findings.py` | No open ship-blocking finding in self-audit (Rule 9). |
| `check_root_cause_block.py` | PR descriptions include the four-line root-cause block (Rule 1). |
| `check_test_honesty.py` | No `MagicMock` on the unit-under-test in integration tests (Rule 4). |
| `check_vacuous_asserts.py` | No `assert True` / `assert <something not under test>` patterns. |
| `check_pytest_skip_discipline.py` | Skip reasons cite the dependency that is absent. |
| `check_pytest_markers.py` | All registered markers are documented and used. |
| `check_tdd_evidence.py` | Every new `agent_server/api/routes_*.py` handler carries `# tdd-red-sha: <sha>` (R-AS-5). |
| `check_targeted_default_path.py` | Default path is exercised by ≥1 E2E test (Rule 4 layer 3). |
| `check_state_transition_centralization.py` / `check_state_transition_coverage.py` | State machines have one writer + full transition coverage. |
| `check_select_completeness.py` | `select`/dispatch tables exhaustive over their enum domain. |
| `check_validate_before_mutate.py` | Validation precedes mutation. |
| `check_durable_wiring.py` | Every persistent dependency has a single construction path (Rule 6). |
| `check_secrets.py` | No secrets committed; `inject_provider_key.py` is the only sanctioned path. |
| `check_no_shell_packages.py` | No `shell=True` subprocess calls. |
| `check_sqlite_pragma.py` | Production SQLite stores set `journal_mode=WAL` and reasonable timeouts. |
| `check_metric_producers.py` / `check_metrics_cardinality.py` / `check_slo_health.py` | Metrics are produced where claimed; cardinality is bounded; SLO targets healthy. |
| `check_lineage_population.py` | Spine fields propagate through all facade boundaries. |
| `check_env_var_routing.py` | Each `HI_AGENT_*` env var is read in exactly one place. |
| `check_owner_tag.py` | Commit body declares `Owner: CO|RO|DX|TE|GOV|AS-*`. |
| `check_capability_maturity.py` | L0–L4 declarations cite required evidence (Rule 13). |
| `check_closure_levels.py` / `check_closure_taxonomy.py` | Closure claims declare a Rule-15 maturity level. |
| `check_posture_coverage.py` | Posture-aware paths covered by both `dev` and `research` tests (Rule 11). |
| `check_allowlist_discipline.py` / `check_allowlist_universal.py` / `check_expired_waivers.py` | Allowlist entries carry required fields; expired entries fail closed (Rule 17). |
| `check_admin_session_store_imports.py` | Session-store imports are scoped. |
| `check_conftest_fallback_scope.py` | Test fallbacks are scope-narrow. |
| `check_deprecated_field_usage.py` | Deprecated field reads tracked. |
| `check_doc_canonical_symbols.py` | Docs reference canonical symbol names. |
| `check_downstream_response_format.py` | Downstream response notices follow the required schema. |
| `check_gate_strictness.py` | Strict-mode gates are not weakened. |
| `check_multistatus_gates.py` | Multistatus runner output structurally valid. |
| `check_no_research_vocab.py` | Platform-layer code uses no research-team vocabulary. |
| `check_noqa_discipline.py` | `# noqa` lines have justification + linked issue. |
| `check_spine_completeness.py` | Spine coverage across persisted records. |
| `check_surgical_changes.py` | PRs touch only what their owner declares. |
| `rule15_structural_gate.py` | Rule 15 closure-claim three-part discipline at structural level. |

### F. Runners (Rule 8, Rule 4 layer 3, soak, chaos)

| Script | Drives |
|---|---|
| `run_arch_7x24.py` | Architectural 7×24 readiness — 5 assertions, evidence at `docs/verification/<sha>-arch-7x24.json` (Rule 8). |
| `run_chaos_matrix.py` / `run_chaos_runtime_coupled.py` | 10-scenario chaos matrix; all scenarios `runtime_coupled: true`. |
| `run_concurrency_baseline.py` | Concurrency-baseline benchmark + artifact. |
| `run_observability_spine.py` | Builds observability-spine evidence (sync). |
| `build_observability_spine_evidence.py` / `build_observability_spine_e2e_real.py` | Evidence builders for sync + real-LLM E2E spines. |
| `run_operator_drill.py` / `run_pm2_operator_drill.sh` | Rule 8 operator-shape drill (PM2 / docker mirror of prod). |
| `run_soak.py` / `soak_24h.py` | Soak runners (1 h / 24 h / 72 h). |
| `run_t3_gate.py` / `run_t3_gate.sh` | T3 real-LLM gate (Rule 8 step 3). |
| `run_delivery_gate.py` | Composite delivery gate runner. |
| `run_concurrency_gate.sh` | Concurrency gate shell wrapper. |
| `run_dead_code_audit.py` | Dead-code audit (W35 cleanup). |
| `runbook_drill.py` | Operator runbook dry-run (`docs/runbooks/`). |
| `verify_clean_env.py` | Default-offline clean-env verifier (Rule 16) — reads `tests/profiles.toml`. |
| `verify_llm.py` | LLM provider connectivity smoke. |
| `validate_config.py` | Config schema + env-var sanity. |
| `dev_smoke.sh` / `e2e_verify.sh` | Developer smoke + E2E shell drivers. |

### G. Ops + utilities

| Script | Purpose |
|---|---|
| `inject_provider_key.py` | Sanctioned secret injection (no plaintext keys in repo). |
| `backfill_provenance.py` | Backfill `provenance` field on legacy evidence. |
| `export_trajectories.py` | Export run trajectories for offline replay. |
| `load_test_runs.py` | Synthetic run-load generator. |
| `migrate_kg_json_to_sqlite.py` | One-shot KG backend migration. |
| `release_notice.py` | Generate release closure notice from manifest. |
| `render_doc_metadata.py` | Render doc-front-matter metadata. |
| `generate_route_inventory.py` | Generate `docs/route-inventory.md` from route handlers. |
| `audit_unit_test_purity.py` | Audit unit tests for integration-style mocks. |
| `sweep_suppression_expiry.py` | Sweep allowlist entries past `expiry_wave`. |
| `precommit_t3_reminder.sh` | Pre-commit hook reminding hot-path PRs to run T3. |
| `_current_wave.py` | Library — current-wave resolver. |
| `_governance_json.py` | Library — JSON report writer used by gate scripts. |
| `_governance/` | Helpers: `evidence_picker.py`, `evidence_writer.py`, `governance_gap.py` (`is_docs_only_gap` + `is_gov_only_gap`), `hot_paths.py`, `manifest_picker.py`, `multistatus.py`, `multistatus_runner.py`, `wave.py`. |
| `git_hooks/` | Git hook implementations (pre-commit, etc.). |

---

## Cross-references

- **Orphan-gates audit:** `docs/governance/orphan-gates-audit-2026-05-05.md` — coverage map for all 89 `check_*.py` scripts; this is where the 11 W35-corrective wirings (`check_admin_session_store_imports`, `check_concurrency_evidence`, `check_dataclass_spine_validation`, etc.) are recorded.
- **CI workflow:** `.github/workflows/release-gate.yml` is the canonical invocation site; `claude-rules.yml` runs the Rule-bundle check on every PR; `main-ci.yml` is the build/test pipeline; `smoke.yml` is the smoke-only pipeline.
- **Rule-script map:** `scripts/check_rules.py` is the entry for Rules 4 / 5 / 6; the other `check_*.py` scripts each cover a more specific rule or invariant.
- **Wave discipline:** `_governance/governance_gap.py::is_docs_only_gap` and `is_gov_only_gap` are the binding implementations of Rule 14 gap definitions; closure-notice and signoff scripts use them.

To-confirm: this inventory lists every script in the directory at HEAD `276917d8`; if a future PR adds a `check_*.py`, the orphan-gates audit must re-run.
