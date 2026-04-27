# Wave 12 Release Captain Assignments

Wave: 12
Date: 2026-04-27

| Role | Owner | Files of record | Mandate |
|---|---|---|---|
| Release Captain | GOV-track | scripts/build_release_manifest.py, scripts/check_doc_consistency.py, docs/releases/ | Manifest HEAD/gates/score/notice consistency |
| Runtime Captain | RO-track | hi_agent/server/run_manager.py, hi_agent/server/run_queue.py, hi_agent/server/routes_*.py | /runs, RunQueue, recovery, event stream, observability |
| Test Captain | TE-track | scripts/verify_clean_env.py, tests/profiles.toml, scripts/run_t3_gate.py | Profile taxonomy, clean-env, T3, soak, chaos evidence |
| Security Captain | GOV-track | scripts/check_route_scope.py, scripts/check_allowlist_discipline.py, docs/governance/allowlists.yaml | Route scope, tenant isolation, allowlist burn-down |

## Conduct Spec Reference

Per upstream-engineering-conduct-spec-2026-04-27.md §12:
- These owners are accountable for their domains in every release.
- An unmanaged release (no owner listed) is not a valid release.
- Captain assignments are referenced in the release manifest `captains` field.
