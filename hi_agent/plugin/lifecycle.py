"""Deprecated: use hi_agent.plugins.lifecycle instead."""
import warnings

warnings.warn(
    "hi_agent.plugin.lifecycle is deprecated; use hi_agent.plugins.lifecycle instead. "
    "This shim will be removed in Wave 30.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.plugins.lifecycle import *  # noqa: F403  expiry_wave: Wave 30
from hi_agent.plugins.lifecycle import (
    PluginLifecycle,  # noqa: F401  expiry_wave: Wave 30  # scope: legacy-compatibility — re-export shim for backward compat
)
