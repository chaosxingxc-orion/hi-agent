"""Deprecated: use hi_agent.plugins.loader instead."""
import warnings

warnings.warn(
    "hi_agent.plugin.loader is deprecated; use hi_agent.plugins.loader instead. "
    "This shim will be removed in Wave 19.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.plugins.loader import *  # noqa: F403  expiry_wave: Wave 17
from hi_agent.plugins.loader import PluginLoader  # noqa: F401
