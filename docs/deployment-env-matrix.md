# Deployment Environment Matrix

> Authoritative list of every environment variable **actually consumed** by
> hi-agent at runtime, with the exact code site that reads it. If a variable
> is not on this list it is not honoured — do not set it expecting behaviour.
>
> Created in response to the 2026-04-21 incident where `KERNEL_BASE_URL=…` was
> set on the downstream deploy but ignored (correct name is
> `HI_AGENT_KERNEL_BASE_URL`, and it was only wired after 04-21). See
> [hi-agent-prod-mode-issue-20260421.md](hi-agent-prod-mode-issue-20260421.md).

---

## 1. Runtime mode & profile

| Variable | Default | Effect | Code site |
|----------|---------|--------|-----------|
| `HI_AGENT_ENV` | `dev` | `prod` enables fail-fast executor build, disables heuristic fallback, forces real LLM + real kernel expectations. `dev` enables heuristic fallback and relaxed auth. | `hi_agent/server/app.py:1613`, `hi_agent/capability/defaults.py:33`, `hi_agent/config/cognition_builder.py:325`, `hi_agent/server/runtime_mode_resolver.py:25` |
| `HI_AGENT_PROFILE` | `""` | Selects a named profile overlay in the config stack. | `hi_agent/config/stack.py:99` |
| `HI_AGENT_CONFIG_FILE` | `""` | Path to a JSON file merged on top of defaults and under env overrides. | `hi_agent/server/app.py:1616`, `hi_agent/cli.py:179` |
| `HI_AGENT_HOME` | `""` | Project-home override propagated to storage subsystems. | `hi_agent/cli.py:134` |

---

## 2. Kernel adapter (the 04-21 incident root cause)

| Variable | Default | Effect | Code site |
|----------|---------|--------|-----------|
| **`HI_AGENT_KERNEL_BASE_URL`** | `local` | Selects kernel routing. `local` (or empty) → in-process LocalFSM adapter. An HTTP URL → `KernelFacadeClient` that talks to a detached `agent-kernel` service. **This is the only name that works** — `KERNEL_BASE_URL` (no `HI_AGENT_` prefix) and the legacy `HI_AGENT_KERNEL_URL` are **ignored** by the builder. | `hi_agent/config/trace_config.py:from_env`, `hi_agent/config/runtime_builder.py:57` |
| `HI_AGENT_KERNEL_MODE` | `""` | Readiness hint — `http` signals to `resolve_runtime_mode` that a separate kernel is intended. | `hi_agent/server/runtime_mode_resolver.py:27` |
| `HI_AGENT_KERNEL_BASE_URL_OVERRIDE_UNSAFE` | `""` | Developer escape hatch to disable the loopback-address safety check on the HTTP kernel client. Do not use in production. | `hi_agent/runtime_adapter/kernel_facade_client.py:57` |

> **Legacy names still accepted as a fallback only in `/doctor`:** `HI_AGENT_KERNEL_URL`. Everywhere else, set `HI_AGENT_KERNEL_BASE_URL`.

---

## 3. LLM gateway

| Variable | Default | Effect | Code site |
|----------|---------|--------|-----------|
| `OPENAI_API_KEY` | `""` | Credentials for any OpenAI-compatible endpoint (includes MaaS glm, DeepSeek, Volcengine when using `openai_base_url`). | `hi_agent/llm/http_gateway.py:49`, readiness probes |
| `ANTHROPIC_API_KEY` | `""` | Credentials for Anthropic Claude endpoints. | `hi_agent/llm/anthropic_gateway.py`, readiness probes |
| `VOLCE_API_KEY` | `""` | Live-API test gate in CI; not consumed at runtime by the server itself. | `.github/workflows/ci.yml` |
| `HI_AGENT_LLM_MODE` | `""` | Readiness hint — `real` signals that a real LLM gateway is intended. | `hi_agent/server/runtime_mode_resolver.py:27` |
| `HI_AGENT_LLM_DEFAULT_PROVIDER` | `anthropic` | Selects `openai` or `anthropic` as the primary gateway. | `hi_agent/config/trace_config.py:from_env` |
| `HI_AGENT_OPENAI_BASE_URL` | `https://api.openai.com/v1` | Base URL for the OpenAI-compatible gateway. **Must include the API version path** (e.g. `/v1`, `/v2`, or a vendor-specific prefix) — hi-agent issues `POST {base}/chat/completions`. | `hi_agent/config/trace_config.py:from_env` |
| `HI_AGENT_OPENAI_DEFAULT_MODEL` | `gpt-4o` | Model id substituted for requests whose `model=="default"`. | `hi_agent/config/trace_config.py:from_env` |
| `HI_AGENT_OPENAI_API_KEY_ENV` | `OPENAI_API_KEY` | Name of the env var the gateway reads the key from. Override if you rotate secrets under a different variable name. | `hi_agent/config/trace_config.py:from_env` |
| `HI_AGENT_ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | Same pattern as OpenAI. | `hi_agent/config/trace_config.py:from_env` |
| `HI_AGENT_ANTHROPIC_DEFAULT_MODEL` | `claude-sonnet-4-6` | Default Anthropic model id. | `hi_agent/config/trace_config.py:from_env` |
| `HI_AGENT_ANTHROPIC_API_KEY_ENV` | `ANTHROPIC_API_KEY` | Anthropic key env var name. | `hi_agent/config/trace_config.py:from_env` |
| `HI_AGENT_ANTHROPIC_API_VERSION` | `2023-06-01` | Anthropic API version header. | `hi_agent/config/trace_config.py:from_env` |
| `HI_AGENT_COMPAT_SYNC_LLM` | `false` | Opt into the deprecated sync/urllib gateway. Off by default since 04-15. | `hi_agent/config/trace_config.py:from_env` |
| `HI_AGENT_DEFAULT_MODEL` | `gpt-4o` | Cross-provider default model id. | `hi_agent/config/trace_config.py:from_env` |
| `HI_AGENT_LLM_TIMEOUT_SECONDS` | `120` | Per-request HTTP timeout. dev-smoke clamp no longer applies when an API key is present (fixed 04-21, P0-2). | `hi_agent/config/trace_config.py:from_env`, `hi_agent/llm/http_gateway.py:89` |
| `HI_AGENT_LLM_MAX_RETRIES` | `2` | Exponential-backoff retry count for transient LLM failures. | `hi_agent/config/trace_config.py:from_env` |

---

## 3b. Auth & identity

| Variable | Default | Effect | Code site |
|----------|---------|--------|-----------|
| `HI_AGENT_JWT_SECRET` | `""` | HS256 secret for JWT signature verification. When unset and the runtime mode is not a test mode, requests carrying a JWT are rejected unless `HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS=true`. | `hi_agent/server/auth_middleware.py` |
| `HI_AGENT_ALLOW_UNSIGNED_JWT_FOR_TESTS` | `false` | **Test-only escape hatch**: when `true`, accepts claims-only (unsigned) JWTs. Must NOT be set in production. | `hi_agent/server/auth_middleware.py:278` |
| `HI_AGENT_RUNTIME_PROFILE` | `dev` | Script-runtime profile in `agent_kernel.cognitive.script_runtime`. Distinct from `HI_AGENT_PROFILE` (which is hi-agent's config stack profile) — this one lives in agent-kernel. | `agent_kernel/kernel/cognitive/script_runtime.py:179` |

---

## 4. Capability / tool gates

| Variable | Default | Effect | Code site |
|----------|---------|--------|-----------|
| `HI_AGENT_ALLOW_HEURISTIC_FALLBACK` | unset | Explicit override for heuristic fallback. `1`/`true` forces on, `0`/`false` forces off; unset falls back to `HI_AGENT_ENV!=prod`. | `hi_agent/capability/defaults.py:30` |
| `HI_AGENT_ENABLE_SHELL_EXEC` | `false` | Enables the `shell_exec` built-in capability. Dangerous — gate behind deliberate opt-in. | `hi_agent/capability/tools/builtin.py:313` |

---

## 5. Evolve / observability

| Variable | Default | Effect | Code site |
|----------|---------|--------|-----------|
| `HI_AGENT_EVOLVE_MODE` | `auto` | `on` / `off` / `auto`. `auto` is runtime-resolved by `evolve_policy`. | `hi_agent/cli.py:191`, `hi_agent/config/trace_config.py:from_env` |
| `WEBHOOK_URL` | `""` | When set, alerts from `MetricsCollector` are posted to this URL. | `hi_agent/config/runtime_builder.py:107` |
| `HI_AGENT_API_TIMEOUT_SECONDS` | `120` | Timeout for CLI API-client calls (not the server). | `hi_agent/cli.py:29` |

---

## 6. Server posture

| Variable | Default | Effect | Code site |
|----------|---------|--------|-----------|
| `HI_AGENT_SERVER_HOST` | `0.0.0.0` | Bind address via `TraceConfig.from_env`. | `hi_agent/config/trace_config.py:from_env` |
| `HI_AGENT_SERVER_PORT` | `8080` | Bind port via `TraceConfig.from_env`. | `hi_agent/config/trace_config.py:from_env` |
| `HI_AGENT_SERVER_MAX_CONCURRENT_RUNS` | `32` | Max parallel runs per RunManager. | `hi_agent/config/trace_config.py:from_env` |

---

## 7. Reference: recommended prod deploy block

```js
// pm2 ecosystem.config.cjs (fragment)
env: {
  HI_AGENT_ENV: 'prod',
  HI_AGENT_KERNEL_BASE_URL: 'http://127.0.0.1:8400',  // points to detached agent-kernel
  HI_AGENT_KERNEL_MODE: 'http',                        // readiness hint
  HI_AGENT_LLM_MODE: 'real',                           // readiness hint
  HI_AGENT_LLM_DEFAULT_PROVIDER: 'openai',
  HI_AGENT_OPENAI_BASE_URL: 'https://api.modelarts-maas.com/v2',
  HI_AGENT_DEFAULT_MODEL: 'glm-5.1',
  OPENAI_API_KEY: '<secret>',
  HI_AGENT_LLM_TIMEOUT_SECONDS: '180',                 // glm-5.1 reasoning is slow
  HI_AGENT_LLM_MAX_RETRIES: '1',
}
```

Verify the deploy picked up the values by calling the new diagnostics endpoint:

```bash
curl -s http://127.0.0.1:8080/diagnostics | jq
# expect:
#   .env == "prod"
#   .runtime_mode == "prod-real"
#   .resolved_config.kernel_base_url == "http://127.0.0.1:8400"
#   .credentials_present.OPENAI_API_KEY == true
```

---

## 8. Variables explicitly **not** supported

- `KERNEL_BASE_URL` — missing the `HI_AGENT_` prefix; ignored.
- `HI_AGENT_KERNEL_URL` — legacy name; only the `/doctor` fallback reads it, nothing else does.
- `OPENAI_BASE_URL` — use `HI_AGENT_OPENAI_BASE_URL`.
- `MODEL` / `DEFAULT_MODEL` — use `HI_AGENT_DEFAULT_MODEL`.

Setting any of the above will silently have no effect.
