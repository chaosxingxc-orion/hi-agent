# Runbook: Tenant Correctness Carryover (W32-T)

**Status:** active
**Origin:** ledger entry W32-T
**Last updated:** 2026-05-07

## What this is

A Rule 12 carryover: W31 closed the BLOCKER tenant-data-leak fixes (T-1'..T-7' +
T-13') and flipped 7 xfail tenant tests, but 5 MEDIUM/LOW carryover items remain
open: T-9'/T-10' (wiki/entry tenant-scope), T-15' (team_run_registry list-by-workspace),
T-16'/T-17' (run_store get_unsafe access-control escape hatch), T-25' (definition.py
'default' string coercion). These are non-leak defects but represent future-leak
surface area. They were carried to W33 with explicit `expiry_wave` markers because
W31 + W32 capacity went to closure verification rather than new structural work.

## When to use this runbook

- Triggered by: `hi_agent_tenant_correctness_carryover_count` non-zero
- Triggered by: `hi_agent_tenant_correctness_carryover_alert` firing
- During: routine ops or post-incident review when a new cross-tenant defect is
  discovered in wiki/entry/team_run_registry/run_store/profile-definition surfaces

## Diagnostic steps

1. Inspect each of the five named handlers and confirm tenant-scope enforcement:
   - `agent_server/api/routes_*.py` wiki + entry handlers (T-9'/T-10')
   - `team_run_registry` `list_by_workspace` (T-15')
   - `run_store.get_unsafe` callers (T-16'/T-17')
   - `hi_agent/profiles/definition.py` `default` coercion (T-25')
2. Cross-reference with the ledger entry:
   `docs/governance/recurrence-ledger.yaml::W32-T`.
3. Verify the regression test (the wired gate):
   `python scripts/check_route_scope.py --json` enforces
   `require_tenant_context()` + scoping primitives on every async `handle_*`
   function. The gate's source list must cover the five carryover surfaces.

## Remediation steps

1. T-9'/T-10': Add `require_tenant_context()` + workspace-scoped query to wiki
   and entry handlers. Add `tests/integration/test_route_handle_wiki_tenant_isolation.py`
   and `test_route_handle_entry_tenant_isolation.py`.
2. T-15': Make `team_run_registry.list_by_workspace` the only path; drop any
   bare `list()` callers. Add `test_team_run_registry_list_by_workspace_scope.py`.
3. T-16'/T-17': Rename `run_store.get_unsafe` to make the escape hatch explicit
   in callers, then migrate callers to `get_for_tenant`. Add
   `test_run_store_get_unsafe_replacement.py`.
4. T-25': Replace `definition.py` 'default' string coercion with explicit handling
   that surfaces missing tenant scope as `ValueError`. Add
   `test_profile_definition_default_coercion.py`.
5. Re-run `python scripts/check_route_scope.py --json` and the integration tests
   above to confirm green.

## Recurrence prevention

The release gate at `release-gate.yml` step "Check route tenant scope"
(`scripts/check_route_scope.py`) enforces tenant-scope discipline in CI.

Rule 12 hardening (per W32-T process change): every cross-tenant defect surfaced
by deep-scan agents enters the recurrence ledger as a tracked carryover with
explicit `expiry_wave` + regression-test commitment, not as an unannotated TODO.

W35 §5.1 amendment (per W32-T process change): ledger entries MUST cite a
release_gate script that exists in the repo at landing time; placeholder names
that gesture at a future gate are forbidden — use the actual wired gate (or
accept the entry is at `component_exists`, not `verified_at_release_head`).

If the gate has drifted, see runbook `release-gate-weakening.md`.

## References

- Ledger entry: `docs/governance/recurrence-ledger.yaml` issue_id W32-T
- Code fix history: W33 target — five named carryover items (T-9'/T-10', T-15',
  T-16'/T-17', T-25')
- Regression test: `scripts/check_route_scope.py --json`, plus W33 integration
  tests for each carryover surface
- Process change: Rule 12 hardening (carryover items enter recurrence ledger
  with explicit expiry + regression commitment); W35 §5.1 (release_gate scripts
  must exist at landing time)
- Related runbook: `docs/runbooks/cross-tenant-primitive-footgun.md` (parent class)
