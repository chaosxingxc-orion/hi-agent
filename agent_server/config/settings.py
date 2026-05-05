"""Runtime settings for agent_server.

W35-T7 disposition (deferred): the `agent_server/config/` surface is
intentionally minimal in v1. It carries `AgentServerSettings` (3 fields:
host / port / api_version) plus `version.py` (5 constants).

Future v2 contract work and per-tenant config overrides will require
additional surfaces: per-tenant rate-limit budgets, model routing
overrides, posture-aware lease intervals, retention policies, etc. RIA's
W35 directive §2.5 deferred this expansion — it is correctly out of
scope for W35 because v2 contract work is not staged.

When v2 work is approved, the expansion follows:

  1. Add a `TenantOverrides` dataclass alongside `AgentServerSettings`
     keyed by `tenant_id` and supplying per-tenant overrides for the
     posture-aware knobs.
  2. Add a `load_tenant_overrides(tenant_id)` reader that merges
     environment defaults with per-tenant overrides from a config file
     under `<state_dir>/tenant_config/<tenant_id>.yaml`.
  3. Wire into bootstrap so `build_production_app` reads tenant
     overrides at request time via `RealKernelBackend`.

Until v2 work is staged, no expansion happens. Adding fields to
`AgentServerSettings` ad-hoc is forbidden — the Rule 17 allowlist
discipline applies: every new field carries owner / risk / reason /
expiry_wave / replacement_test.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentServerSettings:
    """Runtime settings resolved from environment."""

    host: str = "0.0.0.0"
    port: int = 8080
    api_version: str = "v1"


def load_settings() -> AgentServerSettings:
    """Load settings from environment variables."""
    port_str = os.environ.get("AGENT_SERVER_PORT", "8080")
    try:
        port = int(port_str)
    except ValueError as exc:
        raise ValueError(f"AGENT_SERVER_PORT must be an integer, got: {port_str!r}") from exc
    if not (1 <= port <= 65535):
        raise ValueError(f"AGENT_SERVER_PORT must be in [1, 65535], got: {port}")
    return AgentServerSettings(
        host=os.environ.get("AGENT_SERVER_HOST", "0.0.0.0"),
        port=port,
        api_version=os.environ.get("AGENT_SERVER_API_VERSION", "v1"),
    )
