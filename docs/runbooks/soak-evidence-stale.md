# Runbook: soak_evidence_stale (P0-4)

**Alert**: `hi_agent_soak_evidence_age_hours > 168` (7 days)
**Owner**: TE
**Severity**: Warning (degrades 7×24 readiness score)

## What this alert means

The soak evidence artifact (`docs/verification/*-soak-*.json`) is more than 168 hours old.
Per the platform posture decision (2026-04-28), 7×24 operational readiness is an architectural
posture claim, not an engineering requirement for every wave. The score cap `cap_7x24=65` applies
when soak evidence is older than 7 days.

## Immediate actions

1. Check soak evidence age:
   ```bash
   python scripts/check_soak_evidence.py --json
   ```

2. If age > 168h and wave is releasing: run a fresh pilot soak (minimum 4h):
   ```bash
   HI_AGENT_LLM_MODE=real VOLCES_API_KEY=<key> python scripts/run_soak.py --duration 4h
   ```

3. After soak completes, verify the output artifact:
   ```bash
   python scripts/check_soak_evidence.py --json
   ```

## Root cause investigation

Check:
- When was the last soak run? (`ls -lt docs/verification/*soak*.json | head -5`)
- Did a recent wave skip the soak intentionally? (Check recurrence-ledger.yaml P0-4 `code_fix` field)
- Is the score cap `cap_7x24=65` currently being applied? (`python scripts/check_score_cap.py`)

## Escalation

If soak cannot be run (no Volces API key, no prod-e2e environment):
- Accept `cap_7x24=65` for this wave
- Document the skip reason in the wave's delivery notice under "Deferred items"
- Do NOT claim 7×24 readiness without a ≥4h soak with `provenance: real`

## Metric definition

Gauge: `hi_agent_soak_evidence_age_hours`
- Value: age of the most recent soak evidence artifact in hours
- Labels: `provenance` (real | pilot_run | structural | shape_verified)
- Updated: at manifest build time by `build_release_manifest.py`

## Prevention

- `scripts/check_soak_evidence.py` is wired into `release-gate.yml` (continue-on-error for 7×24 scope)
- Per P0-4 root cause: soak must sample server PID, not script PID, for resource metrics
- Wave 20+ soak pilots must use `provenance: pilot_run` at minimum
