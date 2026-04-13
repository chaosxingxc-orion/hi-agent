# Provider and MCP Boundaries

This document defines what the platform owns in the capability invocation stack,
describes the current MCP status, and tells upper-layer teams how to integrate
without blocking on MCP readiness.

---

## What the Platform Owns

The platform is the sole owner of the following invocation infrastructure.
Upper layers must not reimplement or bypass these components.

| Component | Location | Responsibility |
|---|---|---|
| `CapabilityRegistry` | `hi_agent/capability/registry.py` | Central store of all invokable capabilities (`CapabilitySpec` by name). |
| `CapabilityInvoker` | `hi_agent/capability/invoker.py` | Synchronous invocation with timeout and retry. |
| `AsyncCapabilityInvoker` | `hi_agent/capability/async_invoker.py` | Asyncio-native invocation with `asyncio.wait_for` and exponential backoff. |
| Provider adapters | `hi_agent/capability/adapters/` | Adapter implementations that bridge external providers to `CapabilitySpec` handlers. |
| `CircuitBreaker` | `hi_agent/capability/circuit_breaker.py` | Closed → open → half-open state machine with configurable cooldown. |

Retry, timeout, and circuit-breaker logic live entirely in the platform.
Upper-layer code invokes capabilities by name and receives results or typed
exceptions — it does not manage retry loops or connection state.

---

## MCP Status: Path A — Deferred

MCP (Model Context Protocol) is optional transport infrastructure.  It is
**not required** for upper-layer development and is explicitly deferred.

### Current Behavior

`MCPBinding` (`hi_agent/mcp/binding.py`) manages the relationship between MCP
server registrations and the `CapabilityRegistry`.  Its behavior depends on
whether a transport is provided at construction:

| Transport supplied? | Result of `bind_all()` |
|---|---|
| Yes | MCP tools are registered as invokable capabilities in `CapabilityRegistry`. |
| No | MCP tools are enumerated for discovery but **NOT** registered. They are tracked in `_unavailable`. |

When no transport is configured, `bind_all()` logs:

```
MCPBinding.bind_all: transport not configured — N MCP tool(s) are known but
NOT registered as capabilities: [...]. Provide an MCPTransport to enable invocation.
```

This is intentional.  The platform prevents broken stubs from being silently
registered as runtime-usable capabilities.

### How to Check Which MCP Tools Are Unavailable

After `bind_all()` has been called, inspect the unavailable list:

```python
unavailable = binding.list_unavailable()
# Example: ["mcp.search_server.web_search", "mcp.code_server.execute"]
```

A non-empty list means those tools exist in the MCP server registry but cannot
be invoked until a transport is configured.  This is not an error — it is a
discovery signal.

### Error Message Guidance

When upper-layer code attempts to invoke a capability that was not registered
because MCP transport is absent, `CapabilityRegistry.get()` raises `KeyError`.
Surface this to callers with:

```
MCP transport not configured — use provider adapters or configure
MCPBinding(transport=...) to enable MCP tools.
```

Do not mask this error.  It indicates that the required tool is not available
on the current deployment.

---

## Primary Integration Path: Provider Adapters

Upper-layer agents should use provider adapters as their primary integration
path.  Provider adapters register directly to `CapabilityRegistry` without
requiring MCP transport.

```python
from hi_agent.capability.registry import CapabilityRegistry, CapabilitySpec

registry = CapabilityRegistry()

def my_search_handler(payload: dict) -> dict:
    # Real provider call here.
    ...

registry.register(CapabilitySpec(
    name="web_search",
    handler=my_search_handler,
    description="Search the web for a query.",
))
```

Capabilities registered this way are immediately invokable through
`CapabilityInvoker` or `AsyncCapabilityInvoker` with full retry and
circuit-breaker coverage.

---

## Non-Goals for Upper Layers

- Upper layers must not assume MCP tools are always available at runtime.
- Upper layers must not poll `list_unavailable()` in a hot loop expecting MCP
  to become available — availability is determined at service startup when
  `bind_all()` is called.
- Upper layers must not block their development roadmap on MCP transport
  readiness.  All capability needs can be met through provider adapters.
- Upper layers must not implement their own retry or circuit-breaker logic on
  top of platform invokers.

---

## Enabling MCP in the Future

To enable MCP tool invocation when transport is available:

1. Implement an `MCPTransport` with `invoke(server_id, tool_name, payload) -> dict`.
2. Pass it to `MCPBinding.__init__(registry, mcp_registry, transport=my_transport)`.
3. Call `binding.bind_all()` — tools will be registered to `CapabilityRegistry`
   and `list_unavailable()` will return an empty list.

No upper-layer code changes are required.  The capability names remain the same
(`mcp.<server_id>.<tool_name>`); only the invocation path changes from
"unavailable" to "registered."

---

## Key Source Locations

| Component | File |
|---|---|
| `MCPBinding.bind_all`, `list_unavailable` | `hi_agent/mcp/binding.py` |
| `CapabilityRegistry` | `hi_agent/capability/registry.py` |
| `CapabilityInvoker` | `hi_agent/capability/invoker.py` |
| `AsyncCapabilityInvoker` | `hi_agent/capability/async_invoker.py` |
| `CircuitBreaker` | `hi_agent/capability/circuit_breaker.py` |
