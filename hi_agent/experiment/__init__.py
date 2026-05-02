"""Deprecated: use hi_agent.operations instead.

This package is a compatibility shim for Wave 11 migration.
Retained for backward compatibility; new code must import from
``hi_agent.operations``.
"""
import warnings

warnings.warn(
    "hi_agent.experiment is deprecated; use hi_agent.operations instead. "
    "This shim is retained for backward compatibility only.",
    DeprecationWarning,
    stacklevel=2,
)
from hi_agent.operations import *  # noqa: F403  expiry_wave: permanent
