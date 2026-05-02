# Runtime layer split

This file documents the rule that splits `hi_agent/runtime/` from
`hi_agent/runtime_adapter/` after the W31 H.6 consolidation.

## Two namespaces

### `hi_agent/runtime/` — runtime helpers

In-process runtime support primitives. These are tools the platform uses
to manage event-loop lifetime, cancellation, profile-aware runtime config,
and the harness execution pipeline.

Members today:

- `sync_bridge.py` — single durable event-loop thread (Rule 5 sync bridge)
- `async_bridge.py` — async-side wrapper used by sync callers
- `cancellation.py` — cooperative cancellation primitives
- `profile_runtime.py` — profile-aware runtime helpers
- `harness/` — unified action execution pipeline (governance + evidence
  store + executor + permission rules); moved here from `hi_agent/harness/`
  in W31-H.6 so the runtime helper namespace is unified.

### `hi_agent/runtime_adapter/` — kernel facade adapter spine

The seam between hi_agent and `agent_kernel`. This package re-exports the
production kernel contract surface (`FAILURE_GATE_MAP`, `Action`,
`RuntimeEvent`, `TaskAttempt`, …) and the adapter implementations
(`KernelFacadeAdapter`, `AsyncKernelFacadeAdapter`,
`ResilientKernelAdapter`, `ReconcileLoop`, `EventBuffer`, …).

Test fixtures (`InMemoryDedupeStore`, `InMemoryKernelRuntimeEventLog`,
`StaticRecoveryGateService`) live in `hi_agent/testing/` instead of here
so production callers do not transitively pull in test-only primitives
(W31-H.6 / H-1' fix).

## Rule

- A module is a **runtime helper** if it does not require the kernel
  facade adapter spine to function. It belongs in `hi_agent/runtime/`.
- A module is a **kernel facade adapter** if it implements
  `RuntimeAdapter` or directly bridges to `agent_kernel.kernel`. It
  belongs in `hi_agent/runtime_adapter/`.

The two namespaces are NOT interchangeable. New code must declare which
namespace it belongs to before it lands.
