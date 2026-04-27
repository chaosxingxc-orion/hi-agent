# SLO Breach Response

When to use: Use this runbook when any production SLO error budget burn or latency/availability objective breach is detected.

## Steps
1. Confirm the breach window in dashboards and capture UTC timestamps, affected service, and current error budget burn rate.
2. Declare an incident channel and assign incident commander, communications lead, and operator on execution.
3. Freeze risky deploys and feature flags that can amplify failure while keeping safe rollback paths available.
4. Run immediate triage commands for queue depth, worker health, dependency status, and saturation hotspots.
5. Apply the fastest safe mitigation (rollback, traffic shaping, throttling, or failover) and log every operator action.
6. Re-check SLO indicators every 5 minutes until burn rate and user-impact metrics return to acceptable thresholds.
7. Record evidence artifacts under docs/verification and summarize root-cause hypothesis, mitigation, and residual risk.

## Expected outcome
User impact is reduced quickly, SLO burn normalizes, and operators leave a complete evidence trail for post-incident review.

## Escalation path
Escalate to the on-call engineering manager and platform lead after 15 minutes without stabilization, then page executive incident sponsor at 30 minutes if SLOs remain breached.
