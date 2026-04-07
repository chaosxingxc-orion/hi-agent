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
    kernel_base_url: str = "http://localhost:9090"
    kernel_max_retries: int = 3
    kernel_circuit_breaker_threshold: int = 5

    # Evolve
    evolve_enabled: bool = True
    evolve_min_confidence: float = 0.6

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
