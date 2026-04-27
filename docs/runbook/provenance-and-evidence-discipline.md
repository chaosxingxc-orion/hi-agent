# Provenance and Evidence Discipline

When to use: Use this runbook whenever an operator action requires auditable proof for release, incident, or governance decisions.

## Steps
1. Start by recording command intent, operator identity, repository SHA, and UTC start time before execution.
2. Run only approved commands and capture raw outputs without manual rewriting of technical facts.
3. Write evidence artifacts to docs/verification using deterministic filenames that include commit discriminator.
4. Label each artifact with provenance mode (`real` or `structural`) and include started_at and finished_at timestamps.
5. Validate artifact integrity (JSON shape, required keys, and parseability) before sharing with reviewers.
6. Cross-link evidence files in the relevant delivery, release, or incident summary document.
7. On any failed or partial run, keep the failed evidence, annotate cause, and rerun with a new artifact rather than overwriting.

## Expected outcome
Every material operator action has verifiable, tamper-evident evidence that reviewers can trace to code state and execution time.

## Escalation path
Escalate missing or inconsistent evidence to release manager and governance owner immediately; block promotion decisions until evidence discipline is restored.
