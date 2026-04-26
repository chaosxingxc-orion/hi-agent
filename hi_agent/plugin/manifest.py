"""Deprecated: use hi_agent.plugins.manifest instead."""
import warnings

warnings.warn(
    "hi_agent.plugin.manifest is deprecated; use hi_agent.plugins.manifest instead. "
    "This shim will be removed in Wave 12.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.plugins.manifest import *  # noqa: F403
from hi_agent.plugins.manifest import PluginManifest  # noqa: F401
