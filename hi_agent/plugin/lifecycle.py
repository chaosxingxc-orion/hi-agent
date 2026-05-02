"""Deprecated: use hi_agent.plugins.lifecycle instead."""
import warnings

warnings.warn(
    "hi_agent.plugin.lifecycle is deprecated; use hi_agent.plugins.lifecycle instead. "
    "This shim is retained for backward compatibility only.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.plugins.lifecycle import *  # noqa: F403  expiry_wave: permanent
from hi_agent.plugins.lifecycle import (
    PluginLifecycle,  # noqa: F401  expiry_wave: permanent  # scope: legacy-compatibility — re-export shim for backward compat
)
