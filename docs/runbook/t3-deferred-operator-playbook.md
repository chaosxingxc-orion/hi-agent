# T3 Deferred Operator Playbook

When to use: Use this runbook when T3 execution is deferred due to provider issues, policy holds, or dependency instability.

## Steps
1. Verify the deferral trigger and record the blocker category (provider outage, policy gate, missing dependency, or capacity constraint).
2. Mark impacted T3 runs as deferred in the operations tracker with run IDs, owner, and next-review timestamp.
3. Notify stakeholders of deferred scope, customer impact, and expected re-evaluation window.
4. Execute fallback handling for queued work (pause intake, downgrade priority tiers, or route to safe manual handling).
5. Validate that no automated retries are creating repeated failed attempts or evidence noise.
6. Re-test readiness predicates at the agreed checkpoint and document pass/fail with timestamps.
7. Resume deferred T3 runs only after blocker clearance is verified and rollback plan is prepared.

## Expected outcome
Deferred runs remain controlled, stakeholder expectations are explicit, and T3 execution resumes with low re-failure risk.

## Escalation path
Escalate to platform on-call and governance owner if deferral exceeds one review cycle, then escalate to product and incident leadership if customer commitments are at risk.
