"""Deprecated: use hi_agent.plugins instead.

This package is a compatibility shim for Wave 11 migration.
It will be removed in Wave 12.
"""
import warnings

warnings.warn(
    "hi_agent.plugin is deprecated; use hi_agent.plugins instead. "
    "This shim will be removed in Wave 12.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.plugins import *  # noqa: F403
from hi_agent.plugins import __all__  # noqa: F401
