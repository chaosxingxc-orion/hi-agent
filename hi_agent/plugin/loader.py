"""Deprecated: use hi_agent.plugins.loader instead."""
import warnings

warnings.warn(
    "hi_agent.plugin.loader is deprecated; use hi_agent.plugins.loader instead. "
    "This shim will be removed in Wave 15.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.plugins.loader import *  # noqa: F403
from hi_agent.plugins.loader import PluginLoader  # noqa: F401
