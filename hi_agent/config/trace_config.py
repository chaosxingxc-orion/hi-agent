"""Centralized configuration for all TRACE subsystems."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from typing import Any


@dataclass
class TraceConfig:
    """Centralized configuration for all TRACE subsystems.

    Provides a single source of truth for every tunable parameter across
    the hi-agent system.  Instances can be created from defaults, loaded
    from a JSON file, or populated from environment variables with the
    ``HI_AGENT_`` prefix.
    """

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
    gate_budget_crisis_threshold: float = 0.8

    # Watchdog
    watchdog_window_size: int = 10
    watchdog_min_success_rate: float = 0.2
    watchdog_max_consecutive_failures: int = 5

    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8080
    server_max_concurrent_runs: int = 4

    # Kernel adapter
    kernel_base_url: str = "mock"
    kernel_max_retries: int = 3
    kernel_circuit_breaker_threshold: int = 5

    # Evolve
    evolve_enabled: bool = True
    evolve_min_confidence: float = 0.6

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
    anthropic_default_model: str = "claude-sonnet-4-20250514"
    anthropic_api_version: str = "2023-06-01"

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
