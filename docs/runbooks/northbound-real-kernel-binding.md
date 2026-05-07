# Runbook: Northbound Real-Kernel Binding (W32-N)

**Status:** active (HIGH severity)
**Origin:** ledger entry W32-N
**Last updated:** 2026-05-07

## What this is

A platform-contract truthfulness defect: prior to W31-N1..N4, the northbound layer
was authored ahead of the actual served surface. `hi-agent serve` bound to a
hello-world FastAPI app rather than `agent_server.api.app.build_app()`. The
production middleware pipeline (idempotency, tenant scope) existed but was not
mounted. `check_layering.py` and `check_facade_seams.py` had a narrower scan radius
than the production surface, so an unwired service could pass CI while the matrix
declared L3. That declaration was a documentation-only assertion — the served
process did not expose the contract it claimed.

This runbook is HIGH severity because a regression here means the public contract
the platform advertises is not actually the contract callers exercise. Every
northbound-facing claim (idempotency semantics, tenant isolation, MCP surface,
contract version) must be backed by a binding test on the served process.

## When to use this runbook

- Triggered by: `hi_agent_northbound_real_binding_violations_total` non-zero
- Triggered by: `hi_agent_northbound_real_binding_alert` firing
- During: any change to `hi-agent serve` entry-point, `agent_server.api.app`,
  middleware mounting order, or the layering/facade-seam scan scopes
- During: any L-level promotion claim against a northbound contract

## Diagnostic steps

1. Confirm `hi-agent serve` actually binds the production app:
   - Read `agent_server/cli/` for the serve command implementation
   - Trace through to confirm `agent_server.api.app.build_app()` is the bound app
2. Confirm the middleware pipeline is production-mounted:
   - Inspect `agent_server/api/app.py` for the middleware stack (idempotency,
     tenant scope) and confirm it runs in the order required by the contract
   - Inspect `agent_server/runtime/kernel_adapter.py` for the single-seam
     real-kernel binding (R-AS-1 single-seam discipline)
3. Confirm the gates' scan radius covers the production surface:
   - Run `python scripts/check_layering.py --json` and confirm
     `agent_server/api/**` and `agent_server/middleware/**` are in scope
   - Run `python scripts/check_facade_seams.py --json` and confirm the same scope
4. Confirm the binding tests still assert end-to-end coverage:
   - Run `pytest tests/integration/test_serve_uses_agent_server_app.py`
   - Run `pytest tests/integration/test_middleware_pipeline_production.py`
5. Cross-reference with the ledger entry:
   `docs/governance/recurrence-ledger.yaml::W32-N`.

## Remediation steps

1. If `hi-agent serve` is bound to a placeholder or partial app: restore the
   `agent_server.api.app.build_app()` binding in the CLI. The serve command is the
   contract surface — never bind a stub.
2. If the middleware pipeline is not production-mounted: re-mount the idempotency
   and tenant-scope middleware in the order required by
   `agent_server/api/app.py::build_app()`. Verify with the integration test.
3. If `kernel_adapter.py` is not the single seam (R-AS-1): every cross-package
   import in `agent_server/facade/**` must carry an `r-as-1-seam` annotation. Audit
   imports and add missing annotations. The seam discipline keeps the served
   surface and the kernel decoupled at the contract boundary.
4. If layering or facade-seam gates fail: do NOT widen the gate scope as a fix.
   Restore the contract.
5. Re-run the binding tests and the layering/facade-seam gates to confirm green.

## Recurrence prevention

The release gate at `release-gate.yml` steps `check_layering / check_facade_seams`
enforces this in CI. The binding tests (`test_serve_uses_agent_server_app.py`,
`test_middleware_pipeline_production.py`) assert that the served process actually
exposes the declared contract.

Rule 13 hardening (per W32-N process change): an L3 claim against a northbound
contract requires a binding test that the served process actually exposes the
contract. Documentation-only L-level changes are not allowed.

If the gate has drifted, see runbook `release-gate-weakening.md`.

## References

- Ledger entry: `docs/governance/recurrence-ledger.yaml` issue_id W32-N
- Code fix history: W31-N1..N4 (commits b89c0373, 8eacb9fd, 83502449, c537e819)
- Regression test: `tests/integration/test_serve_uses_agent_server_app.py`,
  `tests/integration/test_middleware_pipeline_production.py`,
  `scripts/check_layering.py --json`, `scripts/check_facade_seams.py --json`
- Process change: Rule 13 hardening — L3 northbound claims require a binding test
  on the served process; doc-only L-promotion is forbidden
- Single-seam contract: `agent_server/runtime/kernel_adapter.py` (R-AS-1)
- Owner track: AS-RO (Agent-Server Runtime/Facade)
