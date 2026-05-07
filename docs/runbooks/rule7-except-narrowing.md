# Rule 7 Except Narrowing

**Status:** active
**Origin:** ledger entry W28-F
**Last updated:** 2026-05-07

## What this is

Roughly 17 broad `except` clauses across `hi_agent/` (diagnostics, `skill/observer`, `routes_*`, auth, `event_store`, `runtime_adapter`) carry `rule7-exempt` annotations with `replacement_test: wave22-tests`. The wave22 tests exist and assert specific exception types, but the clauses themselves were never narrowed to match those assertions. As written, they continue to swallow exception classes broader than the tests require, weakening Rule 7's "Resilience Must Not Mask Signals" invariant.

## When to use this runbook

- Triggered by: `hi_agent_rule7_exempt_count` firing (count fails to decrease wave-over-wave)
- Triggered by: `hi_agent_rule7_exempt_alert`
- During: routine quarterly burndown review or when working on any of the listed surfaces

## Diagnostic steps

1. Run `python scripts/check_silent_degradation.py --json` and read the `rule7-exempt` inventory; record the current count and which files carry annotations.
2. For each annotated `except` clause, locate the paired wave22 test (regression test that asserts the specific exception type the clause should catch).
3. Confirm whether the `except` body still re-raises, logs at WARNING+, or converts to a typed failure -- the four Rule 7 requirements (Countable, Attributable, Inspectable, Gate-asserted).
4. Cross-reference with the ledger entry: `docs/governance/recurrence-ledger.yaml::W28-F` (defect_class `rule7_except_narrowing`).
5. Confirm the regression-test commitment in the ledger: "Existing wave22-tests plus narrowed exception handling; ruff check confirms no broad `except: pass`".

## Remediation steps

1. For each `rule7-exempt` clause, narrow the exception filter to the specific types the paired wave22 test asserts (e.g., `except (HTTPError, TimeoutError):` rather than `except Exception:`).
2. Remove the `rule7-exempt` annotation once the clause is narrowed.
3. Verify the wave22 test still passes; verify ruff is clean (no broad `except: pass`).
4. Re-run `scripts/check_silent_degradation.py --json` to confirm the `rule7-exempt` count has decreased.

## Recurrence prevention

The release gate at `scripts/check_silent_degradation.py` enforces this in CI: the `rule7-exempt` count is part of the gate's output and trends downward across waves. CLAUDE.md Rule 7 ("Resilience Must Not Mask Signals") requires every silent-degradation path to be Countable + Attributable + Inspectable + Gate-asserted; a `rule7-exempt` annotation is tracked debt, not closure. If the gate has drifted (script renamed, workflow not invoking it, or the annotation bumped without structural fix), see runbook `release-gate-weakening.md`.

## References

- Ledger entry: `docs/governance/recurrence-ledger.yaml` issue_id `W28-F`
- Code fix history: W29 target -- narrow each `except` clause to the specific types asserted in wave22-tests; remove `rule7-exempt` annotation
- Regression test: existing wave22 tests plus narrowed exception handling; `ruff check` confirms no broad `except: pass`
- Process change: CLAUDE.md Rule 7 (silent-degradation paths must be Countable + Attributable + Inspectable + Gate-asserted)
- Triage record: `docs/governance/wave-28-expiry-triage.md#group-10`
