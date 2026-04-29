# Runbook: release_gate_weakening (W17-A)

**Alert**: `hi_agent_release_gate_continue_on_error_total{job} > 0`
**Owner**: GOV
**Severity**: Critical (masks real failures; blocks ship per Rule 9)

## What this alert means

A release gate job in `.github/workflows/release-gate.yml` used `continue-on-error: true`
and a failure was silently suppressed. This is a W17-A recurrence — gate weakening during release.

Per Rule 9: a self-audit with open ship-blocking findings blocks delivery. A gate that is
wired with `continue-on-error: true` can silently absorb failures that would otherwise block ship.

## Immediate actions

1. Find which gate failed silently:
   ```bash
   grep -r "continue-on-error: true" .github/workflows/release-gate.yml
   python scripts/check_gate_strictness.py
   ```

2. Identify the job name from the metric label:
   ```
   hi_agent_release_gate_continue_on_error_total{job="<job_name>"}
   ```

3. Investigate the underlying failure:
   - Check the CI run logs for the `<job_name>` step
   - Run the failing gate locally: `python scripts/<gate_script>.py`

4. Fix the underlying failure before proceeding with release.

## Root cause investigation

W17-A root cause: gate scripts were modified to produce passes rather than fixing underlying code.
Common recurrence patterns:
- New `--allow-*` flag added to a gate script without justification
- `continue-on-error: true` added to bypass a blocking check
- Exemption regex broadened in check scripts (check_doc_consistency.py, check_verification_artifacts.py)

Run: `python scripts/check_gate_strictness.py --json`

This script detects: new `--allow-*` flags, new `continue-on-error`, new exemption regexes.

## Escalation

Any `continue-on-error` addition to `release-gate.yml` requires:
1. A recurrence-ledger.yaml entry with `defect_class: gate_weakening_during_release`
2. Release captain sign-off
3. A `expiry_wave` pointing to when the weakening will be removed

The weakening itself must NOT be left permanent. Permanent weakening = shipping with open findings.

## Metric definition

Counter: `hi_agent_release_gate_continue_on_error_total`
- Incremented whenever a `continue-on-error: true` gate completes with a non-zero exit
- Labels: `job` (name of the CI job step), `script` (gate script path)
- Updated: by CI infrastructure monitoring hook in release-gate.yml

## Prevention

- `scripts/check_gate_strictness.py` validates no new `continue-on-error` without justification
- Governance Freeze policy (W17): no new `--allow-*` flags; any gate-pass via exemption must be documented in recurrence-ledger.yaml within the same PR
- Rule 9: ship-blocking findings cannot be masked by advisory gates
