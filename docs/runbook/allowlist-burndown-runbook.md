# Allowlist Burndown Runbook

When to use: Use this runbook when reducing temporary allowlist entries or exception scope in production controls.

## Steps
1. Export the current allowlist with owner, reason, creation date, expiry date, and linked approval artifact.
2. Rank entries by risk and staleness, prioritizing expired, ownerless, or broad-scope exceptions.
3. For each target entry, confirm replacement controls are active before removal.
4. Remove entries in small batches and monitor authentication, authorization, and error-rate signals after each batch.
5. If regressions appear, rollback the last batch only and open a corrective action item with explicit owner.
6. Continue batch removals until burndown target is met and unresolved high-risk entries are explicitly accepted.
7. Publish burndown evidence with before/after counts and residual exceptions requiring leadership sign-off.

## Expected outcome
Allowlist scope is materially reduced without service disruption, and remaining exceptions are justified and time-bounded.

## Escalation path
Escalate unresolved high-risk exceptions to security lead and service owner, then to governance council if exceptions cannot be remediated within the committed window.
