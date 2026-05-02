"""Deprecated: use hi_agent.plugins.manifest instead."""
import warnings

warnings.warn(
    "hi_agent.plugin.manifest is deprecated; use hi_agent.plugins.manifest instead. "
    "This shim is retained for backward compatibility only.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.plugins.manifest import *  # noqa: F403  expiry_wave: permanent
from hi_agent.plugins.manifest import (
    PluginManifest,  # noqa: F401  expiry_wave: permanent  # scope: legacy-compatibility — re-export shim for backward compat
)
