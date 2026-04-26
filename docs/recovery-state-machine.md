# Recovery State Machine

When hi-agent restarts, `_rehydrate_runs()` examines pending runs with expired leases.

## States

- QUEUED: run waiting for a worker
- LEASED: run claimed by a worker
- RUNNING: worker actively executing
- LEASE_EXPIRED: lease TTL exceeded; worker may have crashed
- REQUEUED: re-enqueued for another worker to claim
- ADOPTED: claimed by current process
- FAILED_TERMINAL: unrecoverable failure

## Posture Matrix

| Posture | LEASE_EXPIRED behavior |
|---------|------------------------|
| dev | warn-only (no re-enqueue) |
| research | re-enqueue (default) |
| prod | re-enqueue (default) |

## Opt-out (migration period)

Set `HI_AGENT_RECOVERY_REENQUEUE=0` to revert to warn-only under research/prod.
This opt-out will be removed in Wave 11.

## Double-execute Prevention

Each re-enqueue sets an `adoption_token` UUID. A concurrent recovery pass
cannot claim the same run — the CAS update fails if the token is already set.
