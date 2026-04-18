"""Centralized configuration for all TRACE subsystems."""

from __future__ import annotations

import json
import logging
import os
import warnings
from dataclasses import asdict, dataclass, fields
from typing import Any, ClassVar, Literal

logger = logging.getLogger(__name__)


@dataclass
class TraceConfig:
    """Centralized configuration for all TRACE subsystems.

    Provides a single source of truth for every tunable parameter across
    the hi-agent system.  Instances can be created from defaults, loaded
    from a JSON file, or populated from environment variables with the
    ``HI_AGENT_`` prefix.
    """

    # Project scoping
    project_id: str = ""

    # Run limits
    max_stages: int = 10
    max_branches_per_stage: int = 5
    max_total_branches: int = 20
    max_actions_per_run: int = 100

    # LLM
    default_model: str = "gpt-4o"
    llm_timeout_seconds: int = 120
    llm_max_retries: int = 2

    # Route
    route_confidence_threshold: float = 0.6
    route_max_proposals: int = 3

    # Memory
    l1_compression_enabled: bool = True
    episodic_storage_dir: str = ".hi_agent/episodes"
    max_episodic_query_results: int = 10

    # Skill
    skill_storage_dir: str = ".hi_agent/skills"
    skill_min_provisional_evidence: int = 2
    skill_min_certified_evidence: int = 5
    skill_min_certified_success_rate: float = 0.8

    # Harness
    harness_default_timeout: int = 60
    harness_max_retries: int = 3

    # Human Gate
    gate_quality_threshold: float = 0.5

    # Watchdog
    watchdog_window_size: int = 10
    watchdog_min_success_rate: float = 0.2
    watchdog_max_consecutive_failures: int = 5

    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8080
    server_max_concurrent_runs: int = 32

    # Trace export (empty string = disabled)
    trace_export_dir: str = ""

    # Kernel adapter
    kernel_base_url: str = "local"
    kernel_max_retries: int = 3
    kernel_circuit_breaker_threshold: int = 5

    # Evolve
    evolve_mode: Literal["auto", "on", "off"] = "auto"
    evolve_min_confidence: float = 0.6
    feedback_store_enabled: bool = True

    # --- Auto-compression (NEW) ---
    compress_snip_threshold: int = 50
    compress_window_threshold: int = 6000
    compress_compress_threshold: int = 4000
    compress_default_budget_tokens: int = 8192

    # --- Memory compressor (NEW) ---
    memory_compress_threshold: int = 25
    memory_compress_timeout_seconds: float = 10.0
    memory_compress_fallback_items: int = 20
    memory_compress_max_findings: int = 8
    memory_compress_max_decisions: int = 8
    memory_compress_max_entities: int = 10
    memory_compress_temperature: float = 0.2
    memory_compress_max_tokens: int = 2048

    # --- Task View (NEW) ---
    task_view_default_budget: int = 9728
    task_view_tokens_per_char: float = 0.25
    task_view_l1_budget_fraction: float = 0.6
    task_view_evidence_budget_fraction: float = 0.85

    # --- LLM Gateway (NEW) ---
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key_env: str = "OPENAI_API_KEY"
    openai_default_model: str = "gpt-4o"
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_api_key_env: str = "ANTHROPIC_API_KEY"
    anthropic_default_model: str = "claude-sonnet-4-6"
    anthropic_api_version: str = "2023-06-01"
    llm_default_provider: str = "anthropic"
    # Set True to explicitly opt into the deprecated sync/urllib gateway (HttpLLMGateway).
    # For prod-real / local-real profiles the async HTTPGateway is the default.
    compat_sync_llm: bool = False

    # --- LLM Budget (NEW) ---
    llm_budget_max_calls: int = 100
    llm_budget_max_tokens: int = 500_000
    llm_default_max_output_tokens: int = 4096

    # --- Route Engine (NEW) ---
    route_skill_base_priority: int = 10
    route_skill_precondition_boost: int = 5
    route_rule_priority: int = 50

    # --- Evolve detail (NEW) ---
    evolve_skill_initial_evidence: int = 1
    evolve_skill_initial_confidence: float = 0.5
    evolve_stages_threshold: int = 3
    evolve_branches_threshold: int = 2
    evolve_successful_confidence: float = 0.5
    evolve_exploration_confidence: float = 0.6
    evolve_regression_window: int = 10
    evolve_regression_threshold: float = 0.15
    evolve_failure_codes_threshold: int = 3
    evolve_prune_ratio_threshold: float = 0.5

    # --- Capability (NEW) ---
    circuit_breaker_failure_threshold: int = 3
    circuit_breaker_cooldown_seconds: float = 30.0

    # --- Harness (NEW) ---
    harness_backoff_base_ms: int = 1000
    harness_backoff_max_ms: int = 30000
    harness_action_default_timeout: int = 60
    evidence_store_backend: str = "sqlite"
    evidence_store_path: str = ".hi_agent/evidence.db"
    audit_store_backend: str = "memory"
    audit_store_path: str = ".hi_agent/audit.db"

    # --- Task Budget defaults (NEW) ---
    task_budget_max_llm_calls: int = 100
    task_budget_max_wall_clock_seconds: int = 3600
    task_budget_max_actions: int = 50
    task_budget_max_cost_cents: int = 1000
    task_default_priority: int = 5

    # --- CTS Exploration (NEW) ---
    cts_max_active_branches_per_stage: int = 3
    cts_max_total_branches: int = 20
    cts_max_route_compare_calls: int = 5
    cts_route_compare_token_budget: int = 4096
    cts_exploration_wall_clock_budget: int = 1800

    # --- Memory retriever (NEW) ---
    memory_retriever_default_budget: int = 2000
    memory_retriever_default_limit: int = 3
    memory_retriever_max_findings_display: int = 3

    # --- Gate (NEW) ---
    gate_default_timeout_seconds: float = 300.0

    # --- Memory auto-consolidation (NEW) ---
    auto_dream_interval: int = 5     # trigger dream every N runs (0=disabled)
    auto_consolidate_interval: int = 20  # trigger LTM consolidation every N runs (0=disabled)

    # --- Async scheduler (NEW) ---
    max_concurrency: int = 64        # AsyncTaskScheduler Semaphore limit

    # --- Prompt caching (Track C) ---
    prompt_cache_enabled: bool = True
    prompt_cache_anchor_messages: int = 3   # lock first N messages as cache prefix
    prompt_cache_min_tokens: int = 1024     # skip caching if system prompt is tiny

    # --- LLM Failover (Track B) ---
    llm_failover_enabled: bool = True
    llm_failover_max_retries: int = 3
    llm_failover_base_delay_ms: int = 500
    llm_failover_max_delay_ms: int = 30_000
    llm_credential_pool_env_var: str = "ANTHROPIC_API_KEY"  # comma-sep multi-key

    # --- Tool result budget (Track D) ---
    tool_result_max_single_chars: int = 32_000   # per-result char limit (~8k tokens)
    tool_result_max_cumulative_chars: int = 128_000  # cross-turn cumulative limit
    tool_result_budget_enabled: bool = True

    # --- Memory & Skill Nudge (Track I) ---
    nudge_enabled: bool = True
    memory_nudge_interval: int = 10    # nudge every N turns without memory save
    skill_nudge_interval: int = 15     # nudge every N tool-iters without skill create

    # --- Delegation (Track F) ---
    delegation_max_concurrent: int = 3
    delegation_poll_interval_seconds: float = 2.0
    delegation_summary_max_chars: int = 2000

    # --- Trajectory export ---
    trajectory_export_enabled: bool = False   # 默认关闭，避免生产环境磁盘爆满
    trajectory_export_dir: str = ".hi_agent/trajectories"

    # --- Context window budget (新增) ---
    context_total_window: int = 200_000
    context_output_reserve: int = 8_000
    context_system_prompt_budget: int = 2_000
    context_tool_definitions_budget: int = 3_000
    context_skill_prompts_budget: int = 2_000
    context_knowledge_context_budget: int = 1_500
    context_health_green_threshold: float = 0.70
    context_health_yellow_threshold: float = 0.85
    context_health_orange_threshold: float = 0.95
    context_max_compression_failures: int = 3
    context_diminishing_window: int = 3
    context_diminishing_threshold: int = 100

    # --- Perception middleware (新增) ---
    perception_summary_threshold_tokens: int = 2_000
    perception_summarize_char_threshold: int = 500
    perception_max_entities: int = 50
    perception_summarize_temperature: float = 0.3
    perception_summarize_max_tokens: int = 200

    # --- BudgetGuard thresholds (新增) ---
    budget_guard_low_threshold: float = 0.10
    budget_guard_mid_threshold: float = 0.30
    budget_guard_high_threshold: float = 0.70

    # --- Skill evolver / loader / observer (新增) ---
    skill_evolver_success_threshold: float = 0.70
    skill_evolver_min_pattern_occurrences: int = 3
    skill_loader_max_skills_in_prompt: int = 50
    skill_loader_max_prompt_tokens: int = 10_000
    skill_observer_max_summary_len: int = 500

    # --- LLM retry (新增) ---
    llm_retry_base_seconds: float = 1.0

    # --- Restart policy ---
    restart_max_attempts: int = 3
    restart_on_exhausted: str = "reflect"   # "reflect" | "escalate" | "abort"

    # ------------------------------------------------------------------
    # Deprecated field registry
    # ------------------------------------------------------------------

    # Fields that exist for backward compatibility but have no downstream
    # consumers — setting them produces no runtime effect.  Use the
    # successor field listed in the comment instead.
    _DEPRECATED_WITH_SUCCESSOR: ClassVar[dict[str, tuple[Any, str]]] = {
        # (default_value, successor_field_name)
        "default_model": ("gpt-4o", "openai_default_model / anthropic_default_model"),
        "llm_max_retries": (2, "llm_failover_max_retries"),
        "harness_default_timeout": (60, "harness_action_default_timeout"),
        "max_stages": (10, "cts_max_active_branches_per_stage (stage count is CTS-driven)"),
        "max_branches_per_stage": (5, "cts_max_active_branches_per_stage"),
        "max_total_branches": (20, "cts_max_total_branches"),
        "max_actions_per_run": (100, "task_budget_max_actions"),
    }

    _DEPRECATED_DEAD: ClassVar[frozenset[str]] = frozenset({
        "l1_compression_enabled",
        "max_episodic_query_results",
        "route_max_proposals",
        "skill_min_provisional_evidence",
        "skill_min_certified_evidence",
        "skill_min_certified_success_rate",
        "kernel_circuit_breaker_threshold",
        "task_default_priority",
    })

    @property
    def evolve_enabled(self) -> bool:
        """Deprecated backward-compat accessor.

        Use ``evolve_mode`` and ``resolve_evolve_effective`` instead.
        """
        warnings.warn(
            "evolve_enabled is deprecated; use evolve_mode instead",
            DeprecationWarning,
            stacklevel=2,
        )
        from hi_agent.config.evolve_policy import resolve_evolve_effective
        enabled, _ = resolve_evolve_effective(self.evolve_mode, "dev-smoke")
        return enabled

    def validate_no_deprecated(self) -> list[str]:
        """Log warnings for deprecated fields set to non-default values.

        Returns list of warning messages emitted.  Callers (e.g. SystemBuilder)
        should call this once at startup to surface configuration drift.
        """
        warnings: list[str] = []
        for field_name, (default_val, successor) in self._DEPRECATED_WITH_SUCCESSOR.items():
            current = getattr(self, field_name, None)
            if current != default_val:
                msg = (
                    f"TraceConfig: deprecated field '{field_name}' is set to {current!r} "
                    f"but has no effect — use '{successor}' instead."
                )
                logger.warning(msg)
                warnings.append(msg)
        for field_name in self._DEPRECATED_DEAD:
            default_val = next(
                (f.default for f in fields(self) if f.name == field_name), None
            )
            current = getattr(self, field_name, None)
            if current != default_val:
                msg = (
                    f"TraceConfig: deprecated field '{field_name}' is set to {current!r} "
                    f"but is no longer consumed by any subsystem."
                )
                logger.warning(msg)
                warnings.append(msg)
        return warnings

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, path: str) -> TraceConfig:
        """Load config from JSON file, with defaults for missing keys.

        Any key present in the JSON file overrides the corresponding
        default.  Keys in the file that do not match a known field are
        silently ignored.
        """
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    @classmethod
    def from_env(cls) -> TraceConfig:
        """Load config from environment variables with ``HI_AGENT_`` prefix.

        Environment variable names are upper-cased field names prefixed
        with ``HI_AGENT_``.  For example the ``server_port`` field is
        read from ``HI_AGENT_SERVER_PORT``.  Values are cast to the
        field's declared type.  Missing variables fall back to defaults.
        """
        overrides: dict[str, Any] = {}
        for f in fields(cls):
            env_key = f"HI_AGENT_{f.name.upper()}"
            raw = os.environ.get(env_key)
            if raw is None:
                continue
            overrides[f.name] = _cast(raw, f.type)
        return cls(**overrides)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a plain ``dict`` of all configuration values."""
        return asdict(self)

    def save(self, path: str) -> None:
        """Persist the configuration to a JSON file."""
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _cast(value: str, type_hint: str) -> Any:
    """Cast a string environment variable value to the target type."""
    if type_hint == "bool":
        return value.lower() in ("1", "true", "yes")
    if type_hint == "int":
        return int(value)
    if type_hint == "float":
        return float(value)
    return value
