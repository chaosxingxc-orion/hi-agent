# Dead Code Audit — 2026-05-02

Methodology: grep-based inbound-import count + git log recent activity.
Candidates: `<=1` grepped references AND no git activity in past 7 days.

**IMPORTANT**: Stem-based grep has false negatives (dynamic imports) and
false positives (short stems matching unrelated identifiers). Review before
deleting anything.

**Candidates found: 21**

| Module | Grepped refs |
|---|---|
| `hi_agent\auth\authorization_context.py` | 1 |
| `hi_agent\config\mcp_config_loader.py` | 1 |
| `hi_agent\config\tools_config_loader.py` | 1 |
| `hi_agent\events\payload_schemas.py` | 1 |
| `hi_agent\management\ops_governance_commands.py` | 1 |
| `hi_agent\management\ops_health_commands.py` | 1 |
| `hi_agent\management\temporal_health_commands.py` | 1 |
| `hi_agent\mcp\schema_registry.py` | 1 |
| `hi_agent\route_engine\confidence_commands.py` | 1 |
| `hi_agent\skills\runtime_factory.py` | 1 |
| `hi_agent\trajectory\backpropagation.py` | 1 |
| `hi_agent\trajectory\optimizer_base.py` | 0 |
| `agent_kernel\kernel\adapter_ports.py` | 1 |
| `agent_kernel\kernel\branch_monitor.py` | 1 |
| `agent_kernel\kernel\failure_code_registry.py` | 1 |
| `agent_kernel\kernel\failure_mappings.py` | 1 |
| `agent_kernel\kernel\persistence\kafka_event_export.py` | 0 |
| `agent_kernel\kernel\persistence\pg_colocated_bundle.py` | 1 |
| `agent_kernel\kernel\persistence\sqlite_circuit_breaker_store.py` | 1 |
| `agent_kernel\kernel\persistence\sqlite_projection_cache.py` | 1 |
| `agent_kernel\kernel\remote_service_verifier.py` | 1 |

## Proposed Deletions

None proposed in W28. All candidates require manual verification before deletion.
Formal deletion of confirmed dead code deferred to W29.
