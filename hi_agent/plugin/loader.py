"""Deprecated: use hi_agent.plugins.loader instead."""
import warnings

warnings.warn(
    "hi_agent.plugin.loader is deprecated; use hi_agent.plugins.loader instead. "
    "This shim is retained for backward compatibility only.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.plugins.loader import *  # noqa: F403  expiry_wave: permanent
from hi_agent.plugins.loader import (
    PluginLoader,  # noqa: F401  expiry_wave: permanent  # scope: legacy-compatibility — re-export shim for backward compat
)
