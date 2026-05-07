# Mypy Ignore Burndown (Bundle and Context)

**Status:** active
**Origin:** ledger entry W28-G
**Last updated:** 2026-05-07

## What this is

Two structural mypy-ignore hotspots carry `expiry_wave: Wave 29`. `agent_kernel/runtime/bundle.py` contains Rule-6-violating inline fallbacks of the form `x or DefaultConfig()` -- these require refactoring constructor arguments to required kwargs. `agent_kernel/kernel/turn_engine.py` dynamically attaches attributes to `ctx`, which mypy cannot type-check; closing this requires adding typed dataclass fields. Both are structural debt, not annotation churn.

## When to use this runbook

- Triggered by: `hi_agent_inline_fallback_count` firing (inline-fallback scan flags new or persisting hits)
- Triggered by: `hi_agent_inline_fallback_alert`
- During: routine quarterly burndown review or when touching `bundle.py` or `turn_engine.py`

## Diagnostic steps

1. Run `python scripts/check_rules.py` and inspect the inline-fallback scan output for `agent_kernel/runtime/bundle.py`.
2. Run `mypy --strict agent_kernel/runtime/bundle.py agent_kernel/kernel/turn_engine.py` and record current error counts.
3. Inspect the existing `# type: ignore` annotations in both files and confirm each carries an `expiry_wave` marker pointing at Wave 29.
4. Cross-reference with the ledger entry: `docs/governance/recurrence-ledger.yaml::W28-G` (defect_class `mypy_ignore_burndown_bundle_and_context`).
5. Confirm the regression-test commitment in the ledger: "mypy --strict passes on `bundle.py` and `turn_engine.py`; `check_rules.py` inline-fallback scan exits 0".

## Remediation steps

1. **`bundle.py`** -- refactor each `x or DefaultX()` site so the constructor takes the scope as a required kwarg (per CLAUDE.md Rule 6). Update every caller in the same PR; missing scope must raise `ValueError`, not silently default.
2. **`turn_engine.py`** -- add typed dataclass fields to `ctx` for every dynamically-attached attribute. Replace the dynamic-set sites with typed assignment.
3. Remove the `# type: ignore` annotations once the type errors are resolved.
4. Re-run `mypy --strict` and `scripts/check_rules.py` to confirm both scans pass; re-run the release gate.

## Recurrence prevention

The release gate at `scripts/check_rules.py` enforces the inline-fallback scan in CI: every match is treated as a defect candidate per CLAUDE.md Rule 6 ("Single Construction Path Per Resource Class"; inline `x or DefaultX()` is forbidden). If the gate has drifted (script renamed, workflow not invoking it, or the annotation bumped without structural fix), see runbook `release-gate-weakening.md`. Note that `P0-W30` in the ledger forbids paperwork-only `expiry_wave` bumps for this class of debt.

## References

- Ledger entry: `docs/governance/recurrence-ledger.yaml` issue_id `W28-G`
- Code fix history: W29 target -- refactor `bundle.py` to required constructor args; add typed dataclass fields to `ctx` in `turn_engine.py`
- Regression test: W29 target -- `mypy --strict` passes on `bundle.py` and `turn_engine.py`; `check_rules.py` inline-fallback scan exits 0
- Process change: CLAUDE.md Rule 6 (inline fallback `x or DefaultX()` is forbidden; scope is a required constructor arg)
- Triage record: `docs/governance/wave-28-expiry-triage.md#group-11`
