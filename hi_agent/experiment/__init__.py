"""Deprecated: use hi_agent.operations instead.

This package is a compatibility shim for Wave 11 migration.
It will be removed in Wave 14.
"""
import warnings

warnings.warn(
    "hi_agent.experiment is deprecated; use hi_agent.operations instead. "
    "This shim will be removed in Wave 14.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.operations import *  # noqa: F403
