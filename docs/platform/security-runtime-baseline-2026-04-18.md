# Security Runtime Baseline — 2026-04-18

Snapshot of the hi-agent platform security posture **before** any security remediation changes.
This document is a factual record; every section cites the source file and line range.

---

## 1. Builtin Tools Inventory

**Source:** `hi_agent/capability/tools/builtin.py`

### 1.1 Registered tools

Four tools are registered by `register_builtin_tools(registry)` into the default `CapabilityRegistry`:

| Tool name   | Handler function       |
|-------------|------------------------|
| `file_read` | `file_read_handler`    |
| `file_write`| `file_write_handler`   |
| `web_fetch` | `web_fetch_handler`    |
| `shell_exec`| `shell_exec_handler`   |

### 1.2 Handler signatures

```python
def file_read_handler(payload: dict) -> dict:
    # payload: {path: str, encoding: str = "utf-8"}
    # returns: {success: bool, content: str, size: int, error: str | None}

def file_write_handler(payload: dict) -> dict:
    # payload: {path: str, content: str, encoding: str = "utf-8"}
    # returns: {success: bool, bytes_written: int, error: str | None}

def web_fetch_handler(payload: dict) -> dict:
    # payload: {url: str, timeout: float = 15.0}
    # returns: {success: bool, content: str, status_code: int, error: str | None}

def shell_exec_handler(payload: dict) -> dict:
    # payload: {command: str, timeout: float = 30.0, cwd: str | None = None}
    # returns: {success: bool, stdout: str, stderr: str, returncode: int, error: str | None}
```

### 1.3 `shell_exec` — `shell=True` usage

`shell=True` is used unconditionally (lines 92–99):

```python
result = subprocess.run(
    command,
    shell=True,
    capture_output=True,
    text=True,
    timeout=timeout,
    cwd=cwd,
)
```

The docstring comment acknowledges this: `"Security: command must be a string (not list). Shell=True with string input."`

### 1.4 Path and URL validation

- **`file_read` / `file_write`**: No path validation. The only guard is a non-empty check (`if not path`). Any absolute or relative path accepted by `pathlib.Path` is accessible — including paths outside the working directory (e.g. `../../etc/passwd`).
- **`web_fetch`**: No URL scheme restriction. Only non-empty check (`if not url`). Any scheme accepted by `urllib.request` is permitted (e.g. `file://`, `ftp://`, `http://`).

---

## 2. Auth Middleware Behavior

**Source:** `hi_agent/server/auth_middleware.py`

### 2.1 When `HI_AGENT_API_KEY` is not set

The middleware is **disabled** — all requests pass through without authentication or authorization checks.

```python
self._enabled = bool(self._api_keys)
if not self._enabled:
    _logger.warning(
        "AuthMiddleware disabled: HI_AGENT_API_KEY not set. "
        "All endpoints are unauthenticated."
    )
```

### 2.2 When `HI_AGENT_API_KEY` is set

- Reads from `HI_AGENT_API_KEY` (comma-separated list of valid keys).
- Every non-exempt request must carry `Authorization: Bearer <token>`.
- **Plain API-key tokens**: compared directly against the configured key set; granted role `write`.
- **JWT tokens** (three dot-separated Base64 segments): payload claims validated (`sub`, `aud`, `exp`); role taken from `role` claim, defaulting to `read`.
- RBAC: POST/PUT/DELETE/PATCH require `write` or `admin` role; GET requires `read`, `write`, or `admin`.

### 2.3 Exempt paths

Only `/health`, `/metrics`, and `/metrics/json` bypass all auth checks.

```python
_EXEMPT_PATHS: frozenset[str] = frozenset({"/health", "/metrics", "/metrics/json"})
```

All other endpoints — including `/tools/call`, `/mcp/tools/call`, run management, and skill endpoints — are subject to the middleware when enabled.

### 2.4 Capability-level RBAC

There is **no capability-level RBAC**. The middleware applies a single HTTP-method-level policy (read vs. write). No per-tool or per-capability permission check exists at invocation time.

`operation_policy.py` defines a `@require_operation` decorator with finer-grained roles (`approver`, `admin`) and SOC separation, but it is applied to only three routes: `memory.consolidate`, `skill.evolve`, and `skill.promote`. Tool-call routes (`/tools/call`, `/mcp/tools/call`) do not use this decorator.

---

## 3. Tool Call Paths

**Source:** `hi_agent/server/app.py`

### 3.1 `/tools/call` handler

```python
async def handle_tools_call(request: Request) -> JSONResponse:
    body = await request.json()
    name = body.get("name", "")
    arguments = body.get("arguments", {})

    server: AgentServer = request.app.state.agent_server
    try:
        invoker = server._builder.build_invoker()
        result = invoker.invoke(name, arguments)
        return JSONResponse({"success": True, "result": result})
```

- `invoker.invoke()` is called **directly** from the route handler.
- No governance gate (`PermissionGate`, `Harness`) is involved.
- No per-call audit event is emitted.

### 3.2 `/mcp/tools/call` handler

```python
async def handle_mcp_tools_call(request: Request) -> JSONResponse:
    # ...
    mcp_server = getattr(server, "_mcp_server", None)
    if mcp_server is None:
        return JSONResponse({"error": "mcp_server_not_configured"}, status_code=503)
    # ...
    result = mcp_server.call_tool(name, arguments or {})
    return JSONResponse(result)
```

- Routes through `MCPServer.call_tool()` which delegates to the same `CapabilityRegistry`/invoker underneath.
- No governance gate involved.
- No per-call audit event.

### 3.3 Summary

Both `/tools/call` and `/mcp/tools/call` invoke tools directly without routing through the `Harness` governance layer (`hi_agent/harness/`). The Harness (dual-dimension governance: `EffectClass` + `SideEffectClass`, `PermissionGate`, `EvidenceStore`) is **not** in the tool invocation path for these HTTP endpoints.

---

## 4. CapabilityRegistry

**Source:** `hi_agent/capability/registry.py`

### 4.1 `CapabilitySpec` — no risk metadata

```python
@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    handler: Callable[[dict], dict]
    description: str = ""
    parameters: dict = field(default_factory=dict)  # JSON Schema dict
```

`CapabilitySpec` holds only name, handler, description, and JSON Schema parameters. There is no `risk_level`, `effect_class`, `side_effect_class`, or any risk metadata field.

### 4.2 `CapabilityDescriptor` — referenced but not defined in registry

`probe_availability` references `spec.descriptor` via `getattr(spec, "descriptor", None)`. This field is not defined on `CapabilitySpec`; it would need to be set externally. No `CapabilityDescriptor` class is defined in `registry.py`.

### 4.3 `GovernedToolExecutor` — does not exist

There is no `GovernedToolExecutor` class in `hi_agent/capability/registry.py` or in the capability module. Tool execution goes directly through `CapabilityInvoker.invoke()` without a governed wrapper.

---

## 5. Current Test Count

Command: `python -m pytest tests/ -q --tb=no`

```
3430 passed, 13 skipped, 47 warnings in 158.42s (0:02:38)
```

---

## 6. Ruff Lint Status

Command: `python -m ruff check hi_agent/ --statistics`

Top violations by count:

| Count | Code   | Fixable | Description                        |
|-------|--------|---------|-------------------------------------|
| 106   | E501   | no      | line-too-long                       |
| 81    | RUF100 | yes     | unused-noqa                         |
| 54    | D107   | no      | undocumented-public-init            |
| 54    | UP037  | yes     | quoted-annotation                   |
| 48    | E402   | no      | module-import-not-at-top-of-file    |
| 43    | I001   | yes     | unsorted-imports                    |
| 33    | D102   | no      | undocumented-public-method          |
| 30    | F401   | yes     | unused-import                       |
| 26    | RUF001 | no      | ambiguous-unicode-character-string  |
| 16    | SIM105 | no      | suppressible-exception              |
| 13    | D105   | no      | undocumented-magic-method           |
| 12    | D212   | yes     | multi-line-summary-first-line       |
| 11    | F821   | no      | undefined-name                      |
| 10    | D101   | no      | undocumented-public-class           |

**Total: 625 errors** (255 auto-fixable with `--fix`; 28 additional with `--unsafe-fixes`).

---

## Baseline Summary

| Area | Current State |
|------|---------------|
| `shell_exec` | `shell=True`, no allow-list, no sandbox |
| `file_read` / `file_write` | No path restriction; arbitrary filesystem access |
| `web_fetch` | No scheme restriction; `file://` and other schemes permitted |
| Auth when `HI_AGENT_API_KEY` unset | Fully unauthenticated; all endpoints open |
| Capability-level RBAC | Not implemented |
| `/tools/call` governance | Bypasses Harness; direct `invoker.invoke()` |
| `/mcp/tools/call` governance | Bypasses Harness; direct `mcp_server.call_tool()` |
| Risk metadata on `CapabilitySpec` | Not present |
| `GovernedToolExecutor` | Does not exist |
| Test suite | 3430 passed, 13 skipped |
| Ruff violations | 625 total, 255 auto-fixable |
