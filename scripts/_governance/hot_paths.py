"""Canonical hot-path file patterns for T3 invariance checking.

Single source of truth — imported by check_t3_evidence.py, check_t3_freshness.py,
precommit_t3_reminder.sh (shell script reads the _SHELL_PREFIXES list below).

Rule 8 (CLAUDE.md): a gate pass is valid only for the SHA at which it was recorded.
Any commit touching these files invalidates T3 until a fresh gate run is recorded.
"""

HOT_PATH_PATTERNS: list[str] = [
    # Core LLM path
    "hi_agent/llm/**",
    # Runtime kernel
    "hi_agent/runtime/**",
    # Config builders
    "hi_agent/config/cognition_builder.py",
    "hi_agent/config/json_config_loader.py",
    "hi_agent/config/builder.py",
    # Runner
    "hi_agent/runner.py",
    "hi_agent/runner_stage.py",
    # Runtime adapter
    "hi_agent/runtime_adapter/**",
    # Memory
    "hi_agent/memory/compressor.py",
    # Server core
    "hi_agent/server/app.py",
    # Profiles
    "hi_agent/profiles/**",
    # Agent server API / facade / CLI
    "agent_server/api/**",
    "agent_server/facade/**",
    "agent_server/cli/**",
    # Wave 25 additions (Track Y) — critical request-path files previously absent:
    "hi_agent/config/posture.py",
    "hi_agent/skill/registry.py",
    "agent_server/contracts/**",
    "agent_server/api/middleware/idempotency.py",
    "agent_server/api/middleware/tenant_context.py",
    "hi_agent/server/error_categories.py",
    "hi_agent/server/recovery.py",
    "hi_agent/server/auth_middleware.py",
]

# ---------------------------------------------------------------------------
# Shell-friendly prefix list used by precommit_t3_reminder.sh.
# Each entry is a path prefix matched with grep (not a glob).
# Keep in sync with HOT_PATH_PATTERNS above.
# ---------------------------------------------------------------------------
_SHELL_PREFIXES: list[str] = [
    "hi_agent/llm/",
    "hi_agent/runtime/",
    "hi_agent/config/cognition_builder.py",
    "hi_agent/config/json_config_loader.py",
    "hi_agent/config/builder.py",
    "hi_agent/runner.py",
    "hi_agent/runner_stage.py",
    "hi_agent/runtime_adapter/",
    "hi_agent/memory/compressor.py",
    "hi_agent/server/app.py",
    "hi_agent/profiles/",
    "agent_server/api/",
    "agent_server/facade/",
    "agent_server/cli/",
    # Wave 25 additions (Track Y):
    "hi_agent/config/posture.py",
    "hi_agent/skill/registry.py",
    "agent_server/contracts/",
    "agent_server/api/middleware/idempotency.py",
    "agent_server/api/middleware/tenant_context.py",
    "hi_agent/server/error_categories.py",
    "hi_agent/server/recovery.py",
    "hi_agent/server/auth_middleware.py",
]
