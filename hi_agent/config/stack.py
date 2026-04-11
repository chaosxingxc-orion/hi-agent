# hi_agent/config/stack.py
"""Five-layer configuration stack for hi-agent.

Priority (highest → lowest):
  5. RunOverrideLayer  — per-run patch dict
  4. EnvLayer          — HI_AGENT_* environment variables
  3. ProfileLayer      — config.<profile>.json
  2. FileBaseLayer     — config.json
  1. DefaultsLayer     — TraceConfig field defaults
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, fields as dc_fields
from typing import Any

logger = logging.getLogger(__name__)


class ConfigStack:
    """Resolves configuration from five stacked layers.

    Thread-safe for read access; ``invalidate()`` must be called externally
    when files change (done by ConfigFileWatcher).
    """

    def __init__(
        self,
        base_config_path: str | None = None,
        profile: str | None = None,
        env: str | None = None,
    ) -> None:
        self._base_path = base_config_path
        # Profile: explicit argument > HI_AGENT_PROFILE env var > ""
        self._profile = profile if profile is not None else os.environ.get("HI_AGENT_PROFILE", "")
        self._env = env if env is not None else os.environ.get("HI_AGENT_ENV", "prod")
        self._cached: "TraceConfig | None" = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, run_patch: dict[str, Any] | None = None) -> "TraceConfig":
        """Merge all layers and return a TraceConfig.

        When *run_patch* is ``None``, the result is cached.
        When *run_patch* is provided, a fresh (non-cached) instance is returned.
        """
        if run_patch is None:
            if self._cached is None:
                self._cached = self._build()
            return self._cached
        return self._build(run_patch=run_patch)

    def invalidate(self) -> None:
        """Clear the cached resolved config (called after file change)."""
        self._cached = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build(self, run_patch: dict[str, Any] | None = None) -> "TraceConfig":
        from hi_agent.config.trace_config import TraceConfig
        from hi_agent.config.profile import deep_merge, load_profile_file
        from hi_agent.config.validator import ConfigValidator

        # Layer 1: defaults
        merged: dict[str, Any] = asdict(TraceConfig())

        # Layer 2: base file
        if self._base_path and os.path.exists(self._base_path):
            with open(self._base_path, encoding="utf-8") as fh:
                file_data = json.load(fh)
            merged = deep_merge(merged, file_data)

        # Layer 3: profile file
        if self._profile:
            profile_data = load_profile_file(self._base_path, self._profile)
            if profile_data:
                merged = deep_merge(merged, profile_data)

        # Layer 4: env vars
        env_overrides = {
            f.name: getattr(TraceConfig.from_env(), f.name)
            for f in dc_fields(TraceConfig)
            if os.environ.get(f"HI_AGENT_{f.name.upper()}")
        }
        if env_overrides:
            merged = deep_merge(merged, env_overrides)

        # Layer 5: run patch
        if run_patch:
            merged = deep_merge(merged, run_patch)

        # Validate
        validator = ConfigValidator(env=self._env)
        validated = validator.validate(merged)

        # Build TraceConfig — only known fields
        known = {f.name for f in dc_fields(TraceConfig)}
        return TraceConfig(**{k: v for k, v in validated.items() if k in known})
