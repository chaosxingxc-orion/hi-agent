# Incident Guide: MCP Server Crash

**Severity**: P2 (MCP servers are non-blocking for core TRACE execution; crash degrades tool access but does not halt the agent)  
**Category**: Infrastructure / Capability availability

## Symptoms

- Agent actions requiring MCP-backed tools fail with `harness_denied` or capability unavailable errors
- `/ready` shows `mcp_health: degraded` or `mcp_health: fail`
- Release gate `mcp_health` gate shows `unhealthy: <server-id>`
- Logs contain `MCPTransport disconnected` or `StdioMCPTransport: process exited`

## Immediate triage

### 1. Check MCP health status

```bash
curl -s localhost:8080/ready | jq '.subsystems | to_entries[] | select(.key | startswith("mcp"))'
```

Or via the release gate:

```bash
python -m hi_agent ops release-gate 2>&1 | grep mcp
```

### 2. Identify which server crashed

```bash
curl -s localhost:8080/manifest | jq '.mcp_servers'
```

Look for `transport_status: "crashed"` or `transport_status: "not_connected"`.

### 3. Check MCP server process logs

MCP servers run as child processes (stdio transport). Check the process table:

```bash
ps aux | grep mcp
```

If the process is absent, it has crashed and not been restarted.

## Recovery steps

### Automatic restart (preferred)

hi-agent's `MCPHealth` monitor triggers automatic restart on crash detection. If the process restarts within 30 seconds, no manual intervention is needed.

Verify:

```bash
curl -s localhost:8080/health | jq .mcp_restart_count
```

A non-zero restart count is expected after a crash; escalate only if the count exceeds 3 within 10 minutes (restart loop).

### Manual restart

If automatic restart fails:

```bash
# Restart the MCP binding via the API
curl -X POST localhost:8080/mcp/<server-id>/restart
```

Or if the HTTP endpoint is unavailable, restart the full server (see `rollback.md` step 4).

### Restart loop (crash-loop)

If the MCP server crashes repeatedly:

1. Disable the server to prevent further crashes from impacting core execution:

   ```bash
   curl -X POST localhost:8080/mcp/<server-id>/disable
   ```

2. Capture crash logs from the child process stderr before it exits:

   ```bash
   python -m hi_agent mcp diagnose --server-id <server-id>
   ```

3. File an incident with the MCP server vendor / maintainer.

4. Core agent execution continues without the crashed server — capabilities backed by that server will return `capability_unavailable` until restored.

## Impact assessment

| Crashed server type | Impact on TRACE | Workaround |
|--------------------|-----------------|------------|
| Tool-only server | Specific actions unavailable | Use alternative capability or skip action |
| Knowledge server | Knowledge retrieval degraded (falls back to BM25/grep) | Four-layer retrieval degrades gracefully |
| Auth/RBAC server | Mutation routes may be blocked | Manual approve via CLI |

## Prevention

- Ensure MCP servers are configured with health endpoints and restart policies
- Set `mcp_restart_max=3` and `mcp_restart_window_seconds=300` in `TraceConfig`
- Include MCP server health in pre-deployment release gate (already covered by `mcp_health` gate)
- Run `test_mcp_crash_restart.py` integration test as part of CI

## Escalation

Escalate to the MCP server owner if:
- Crash reproduces consistently within 5 minutes of restart
- The crash affects all MCP servers simultaneously (suggests shared infrastructure failure)
- Core TRACE execution is also impacted (suggests the crash caused unexpected side effects)
