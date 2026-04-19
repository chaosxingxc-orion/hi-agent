# hi_agent/config/validator.py
"""Schema validation for TraceConfig data dicts.

Prod mode: raise ConfigValidationError on any violation.
Dev mode: log WARNING, replace invalid fields with TraceConfig defaults.
"""
from __future__ import annotations

import logging
import os
from dataclasses import fields as dc_fields
from typing import Any

logger = logging.getLogger(__name__)


def _get_defaults() -> dict[str, Any]:
    from hi_agent.config.trace_config import TraceConfig
    cfg = TraceConfig()
    return {f.name: getattr(cfg, f.name) for f in dc_fields(cfg)}


def _get_field_types() -> dict[str, type]:
    from hi_agent.config.trace_config import TraceConfig
    type_map: dict[str, type] = {}
    for f in dc_fields(TraceConfig):
        hint = f.type
        if hint == "int":
            type_map[f.name] = int
        elif hint == "float":
            type_map[f.name] = float
        elif hint == "bool":
            type_map[f.name] = bool
        elif hint == "str":
            type_map[f.name] = str
    return type_map


# Fields whose values must be in [0.0, 1.0]
_FRACTION_FIELDS = {
    "route_confidence_threshold",
    "skill_min_certified_success_rate",
    "gate_quality_threshold",
    "watchdog_min_success_rate",
    "evolve_min_confidence",
    "evolve_successful_confidence",
    "evolve_exploration_confidence",
    "evolve_regression_threshold",
    "evolve_prune_ratio_threshold",
    "context_health_green_threshold",
    "context_health_yellow_threshold",
    "context_health_orange_threshold",
    "budget_guard_low_threshold",
    "budget_guard_mid_threshold",
    "budget_guard_high_threshold",
    "skill_evolver_success_threshold",
    "task_view_l1_budget_fraction",
    "task_view_evidence_budget_fraction",
}


class ConfigValidationError(ValueError):
    """Raised in prod mode when validation fails."""


class ConfigValidator:
    """Validates a config data dict against TraceConfig schema."""

    def __init__(self, env: str = "prod") -> None:
        self.env = env  # "prod" | "dev"

    @classmethod
    def from_env(cls) -> "ConfigValidator":
        env = os.environ.get("HI_AGENT_ENV", "prod")
        return cls(env=env)

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate *data* and return a cleaned copy.

        Unknown keys are silently dropped.
        """
        defaults = _get_defaults()
        type_map = _get_field_types()
        errors: list[str] = []
        result: dict[str, Any] = {}

        for key, val in data.items():
            if key not in defaults:
                continue  # unknown key — drop silently

            expected_type = type_map.get(key)
            if expected_type and not isinstance(val, expected_type):
                msg = f"{key}: expected {expected_type.__name__}, got {type(val).__name__} ({val!r})"
                errors.append(msg)
                result[key] = defaults[key]  # use default as fallback
                continue

            if key in _FRACTION_FIELDS and isinstance(val, (int, float)):
                if not (0.0 <= float(val) <= 1.0):
                    msg = f"{key}: value {val} is outside [0, 1]"
                    errors.append(msg)
                    result[key] = defaults[key]
                    continue

            result[key] = val

        # Cross-field constraints: green < yellow < orange
        g = result.get("context_health_green_threshold", defaults["context_health_green_threshold"])
        y = result.get("context_health_yellow_threshold", defaults["context_health_yellow_threshold"])
        o = result.get("context_health_orange_threshold", defaults["context_health_orange_threshold"])
        if not (g < y < o):
            msg = f"green_threshold ({g}) must be < yellow_threshold ({y}) < orange_threshold ({o})"
            errors.append(msg)
            result["context_health_green_threshold"] = defaults["context_health_green_threshold"]
            result["context_health_yellow_threshold"] = defaults["context_health_yellow_threshold"]
            result["context_health_orange_threshold"] = defaults["context_health_orange_threshold"]

        if errors:
            if self.env == "prod":
                raise ConfigValidationError(
                    f"Config validation failed ({len(errors)} error(s)):\n"
                    + "\n".join(f"  - {e}" for e in errors)
                )
            for msg in errors:
                logger.warning("Config validation warning (dev mode): %s", msg)

        return result
